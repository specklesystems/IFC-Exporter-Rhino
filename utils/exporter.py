"""Export a received bundle Model to an IFC4X3 file."""

from dataclasses import dataclass, field

import ifcopenshell
import ifcopenshell.api.root
from specklepy.bundle.model import Model, ModelObject

from utils import bundle_geometry
from utils.geometry import GeometryConverter
from utils.helpers import mm_scale
from utils.mapper import PROXY, classify
from utils.materials import MaterialManager
from utils.properties import (
    GlobalIds,
    PropertySetManager,
    ValueCache,
    get_element_name,
    get_properties,
    get_storey,
    set_element_attributes,
)
from utils.type_manager import TypeManager
from utils.writer import StoreyManager, create_ifc_scaffold

SPATIAL_STRUCTURE_TYPES = {
    "IfcBuilding",
    "IfcBuildingStorey",
    "IfcExternalSpatialElement",
    "IfcSpatialZone",
    "IfcGrid",
    "IfcAnnotation",
}
AGGREGATED_TYPES = {"IfcSite", "IfcSpace"}


@dataclass
class ExportStats:
    exported: int = 0
    instanced: int = 0
    without_geometry: int = 0
    definition_members: int = 0
    skipped_spatial: int = 0
    rep_maps: int = 0
    mapped_items: int = 0
    types: int = 0
    styles: int = 0
    storeys: list[str] = field(default_factory=list)

    def print(self) -> None:
        print(f"  Exported elements  : {self.exported}")
        print(f"  ... with instances : {self.instanced}")
        print(f"  Without geometry   : {self.without_geometry}")
        print(
            f"  Definition members : {self.definition_members} (placed, not standalone)"
        )
        print(f"  Skipped (spatial)  : {self.skipped_spatial}")
        print(
            f"  Shared geometries  : {self.rep_maps} maps / {self.mapped_items} items"
        )
        print(f"  Type objects       : {self.types}")
        print(f"  Styles             : {self.styles}")
        print(f"  Storeys            : {', '.join(self.storeys) or '-'}")


def export_model(
    model: Model,
    project_name: str,
    site_name: str,
    building_name: str,
) -> tuple[ifcopenshell.file, ExportStats]:
    ifc, _site, building, body_ctx = create_ifc_scaffold(
        project_name=project_name, site_name=site_name, building_name=building_name
    )
    model_scale = mm_scale(model.units)
    storeys = StoreyManager(ifc, building)
    materials = MaterialManager(ifc)
    values = ValueCache(ifc)
    psets = PropertySetManager(ifc, values)
    types = TypeManager(ifc, values)
    geometry = GeometryConverter(ifc, body_ctx, model, materials)
    guids = GlobalIds()
    warned: set[str] = set()
    stats = ExportStats()

    # Definition members carry their definition's properties; their geometry is
    # exported through the objects that place the definition.
    members = {o.k for d in model.definitions for o in d.members}

    for obj in model.objects:
        props = get_properties(obj)
        ifc_class = classify(props, warned)
        if ifc_class in SPATIAL_STRUCTURE_TYPES:
            stats.skipped_spatial += 1
            continue

        source = bundle_geometry.resolve(model, obj)
        if not source:
            if obj.k in members:
                stats.definition_members += 1
            else:
                stats.without_geometry += 1
            continue

        if ifc_class == PROXY and source.placements:
            ifc_class = _class_from_definition(obj, warned) or ifc_class

        rep, placement = geometry.representation(source)
        if rep is None:
            stats.without_geometry += 1
            continue

        storey = storeys.get_or_create(*get_storey(obj, props, model_scale))
        element = ifcopenshell.api.root.create_entity(
            ifc, ifc_class=ifc_class, name=get_element_name(obj, props)
        )
        attrs = (
            props.get("Attributes") if isinstance(props.get("Attributes"), dict) else {}
        )
        element.GlobalId = guids.claim(attrs.get("GlobalId"), obj.application_id)
        element.Representation = ifc.createIfcProductDefinitionShape(
            Representations=(rep,)
        )
        element.ObjectPlacement = placement
        if ifc_class in AGGREGATED_TYPES:
            storeys.queue_aggregate(storey, element)
        else:
            storeys.queue_contain(storey, element)

        set_element_attributes(element, props)
        psets.queue(element, props)
        types.assign(element, props, ifc_class)

        stats.exported += 1
        if source.placements:
            stats.instanced += 1
        if stats.exported % 500 == 0:
            print(f"  ... processed {stats.exported} elements")

    storeys.flush()
    types.flush()
    psets.flush()

    stats.rep_maps = geometry.rep_maps_created
    stats.mapped_items = geometry.mapped_items
    stats.types = types.count
    stats.styles = materials.count
    stats.storeys = storeys.names
    return ifc, stats


def _class_from_definition(obj: ModelObject, warned: set[str]) -> str | None:
    """A placed object without its own IFC class takes its definition member's."""
    for definition in obj.definitions:
        for member in definition.members:
            ifc_class = classify(get_properties(member), warned)
            if ifc_class != PROXY:
                return ifc_class
    return None
