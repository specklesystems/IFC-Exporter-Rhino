"""IFC file scaffold (IfcProject → IfcSite → IfcBuilding) and storey management."""

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.root
import ifcopenshell.api.unit
import ifcopenshell.guid

from utils.mapper import SCHEMA


def create_ifc_scaffold(
    project_name: str = "Default Project",
    site_name: str = "Default Site",
    building_name: str = "Default Building",
):
    """Create the IFC file with its project/site/building hierarchy.

    Returns (ifc_file, site, building, body_context).
    """
    ifc = ifcopenshell.file(schema=SCHEMA)

    project = ifcopenshell.api.root.create_entity(
        ifc, ifc_class="IfcProject", name=project_name
    )
    ifcopenshell.api.unit.assign_unit(
        ifc, length={"is_metric": True, "raw": "MILLIMETRES"}
    )

    model_ctx = ifcopenshell.api.context.add_context(ifc, context_type="Model")
    body_ctx = ifcopenshell.api.context.add_context(
        ifc,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model_ctx,
    )

    site = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcSite", name=site_name)
    building = ifcopenshell.api.root.create_entity(
        ifc, ifc_class="IfcBuilding", name=building_name
    )
    ifcopenshell.api.aggregate.assign_object(
        ifc, products=[site], relating_object=project
    )
    ifcopenshell.api.aggregate.assign_object(
        ifc, products=[building], relating_object=site
    )
    return ifc, site, building, body_ctx


class StoreyManager:
    """Creates IfcBuildingStorey entities on first use and batches containment."""

    def __init__(self, ifc: ifcopenshell.file, building):
        self.ifc = ifc
        self.building = building
        self._storeys: dict[str, object] = {}
        self._contained: dict[int, list] = {}
        self._aggregated: dict[int, list] = {}

    def get_or_create(self, name: str, elevation_mm: float | None = None):
        if name not in self._storeys:
            storey = ifcopenshell.api.root.create_entity(
                self.ifc, ifc_class="IfcBuildingStorey", name=name
            )
            if elevation_mm is not None:
                storey.Elevation = round(elevation_mm, 3)
            ifcopenshell.api.aggregate.assign_object(
                self.ifc, products=[storey], relating_object=self.building
            )
            self._storeys[name] = storey
            print(f"  Created storey: {name}")
        return self._storeys[name]

    def queue_contain(self, storey, element) -> None:
        self._contained.setdefault(storey.id(), []).append(element)

    def queue_aggregate(self, storey, element) -> None:
        self._aggregated.setdefault(storey.id(), []).append(element)

    def flush(self) -> None:
        # Written directly: ifcopenshell.api.spatial.assign_container is quadratic in
        # the product count (5k elements took ~3 min), and its placement rebasing is
        # not needed since every element is placed absolutely.
        for sid, elements in self._contained.items():
            self.ifc.create_entity(
                "IfcRelContainedInSpatialStructure",
                GlobalId=ifcopenshell.guid.new(),
                RelatedElements=elements,
                RelatingStructure=self.ifc.by_id(sid),
            )
        for sid, elements in self._aggregated.items():
            ifcopenshell.api.aggregate.assign_object(
                self.ifc, products=elements, relating_object=self.ifc.by_id(sid)
            )
        self._contained.clear()
        self._aggregated.clear()

    @property
    def count(self) -> int:
        return len(self._storeys)

    @property
    def names(self) -> list[str]:
        return list(self._storeys)
