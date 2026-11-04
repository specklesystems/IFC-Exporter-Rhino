"""Builds one Rhino-shaped bundle that exercises every export path, and reads it
back as the Model that Automate's ``receive_version_bundle`` would return."""

import math
import os

from specklepy.bundle import BundleBuilder, Producer
from specklepy.bundle.bundle_reader import read_bundle
from specklepy.bundle.model import Model
from specklepy.bundle.spec import Level, Material
from specklepy.objects.geometry import Line, Point, Polyline
from specklepy.objects.geometry.mesh import Mesh

PRODUCER = Producer("ifc-exporter-tests", "1.0")
COLUMN_ID = "6f1c2b8e-3c0e-4f0a-9b8a-2a6d7c1e5f10"


def box(dx: float, dy: float, dz: float, units: str = "m") -> Mesh:
    v = [
        (0, 0, 0), (dx, 0, 0), (dx, dy, 0), (0, dy, 0),
        (0, 0, dz), (dx, 0, dz), (dx, dy, dz), (0, dy, dz),
    ]  # fmt: skip
    quads = [
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ]  # fmt: skip
    return Mesh(
        vertices=[c for p in v for c in p],
        faces=[x for q in quads for x in (4, *q)],
        units=units,
    )


def translation(x: float, y: float, z: float, rot_z_deg: float = 0.0) -> list[float]:
    c, s = math.cos(math.radians(rot_z_deg)), math.sin(math.radians(rot_z_deg))
    return [c, -s, 0, x, s, c, 0, y, 0, 0, 1, z, 0, 0, 0, 1]


def build(directory: str) -> Model:
    with BundleBuilder(PRODUCER, "m", directory) as b:
        steel = b.get_or_add_material(
            "steel",
            Material(
                argb=-8355712, opacity=1.0, metalness=1.0, roughness=0.4, name="Steel"
            ),
        )
        glass = b.get_or_add_material(
            "glass",
            Material(
                argb=-16744256, opacity=0.25, metalness=0.0, roughness=0.0, name="Glass"
            ),
        )
        level_1 = b.get_or_add_level("L1", Level(elevation=3.0, name="Level 1"))
        layer = b.get_or_add_container_path(["Structure"], subtype="Layer")

        # Rhino user strings arrive flat and dotted.
        column = b.get_or_add_object(COLUMN_ID)
        column.set_properties(
            {
                "Attributes.type": "IfcColumn",
                "Attributes.Name": "C1",
                "Attributes.Tag": "COL-01",
                "Property Sets.Pset_ColumnCommon.IsExternal": True,
                "Property Sets.Pset_ColumnCommon.Reference": "HEB200",
                "Quantities.BaseQuantities.Height.name": "Height",
                "Quantities.BaseQuantities.Height.units": "millimetre",
                "Quantities.BaseQuantities.Height.value": "3000",
                "Element Type Attributes.type": "IfcColumnType",
                "Element Type Attributes.Name": "Steel Column",
                "Element Type Property Sets.Pset_ColumnTypeCommon.Status": "NEW",
            },
            name="Column object",
        )
        column.collection = layer
        column.level = level_1
        column.add_geometry(box(0.2, 0.2, 3.0)).material = steel

        # Nested sections, and a mesh in its own units.
        beam = b.get_or_add_object("beam-1")
        beam.set_properties(
            {
                "Attributes": {"type": "IfcBeam"},
                "Property Sets": {
                    "Pset_ColumnCommon": {"IsExternal": True, "Reference": "HEB200"}
                },
                "Building Storey": "Roof",
            },
            name="B1",
        )
        beam.collection = layer
        beam.add_geometry(box(6000, 200, 300, units="mm"))

        # A block: one member object (the definition source) and two placements.
        chair = b.get_or_add_definition("chair", "Chair")
        chair_src = b.get_or_add_object("chair-src")
        chair_src.set_properties({"Attributes": {"type": "IfcFurniture"}}, name="Chair")
        [chair_geo] = chair.add_member(chair_src, [box(0.5, 0.5, 0.9)])
        chair_geo.material = glass
        for i, t in enumerate(
            [translation(5, 0, 0), translation(0, 5, 0, rot_z_deg=90)]
        ):
            placed = b.get_or_add_object(f"chair-{i + 1}")
            placed.set_properties({}, name=f"Chair {i + 1}")
            placed.place(chair, t)

        # Nested instancing: a table definition that places the chair.
        table = b.get_or_add_definition("table", "Table")
        table.add_geometry(box(1.2, 0.8, 0.75)).material = steel
        table.place_nested(chair, translation(0.2, 1.0, 0))
        table_obj = b.get_or_add_object("table-1")
        table_obj.set_properties({}, name="Table")
        table_obj.place(table, translation(10, 10, 0))

        # Curves only.
        edge = b.get_or_add_object("edge-1")
        edge.set_properties(
            {"Attributes": {"type": "IfcBuildingElementProxy"}}, name="Edge"
        )
        edge.add_geometry(Polyline(value=[0, 0, 0, 1, 0, 0, 1, 1, 0], units="m"))
        edge.add_geometry(
            Line(
                start=Point(x=0, y=0, z=1, units="m"),
                end=Point(x=1, y=0, z=1, units="m"),
                units="m",
            )
        )

        # Things that must not become elements, or must degrade.
        b.get_or_add_object("note-1").set_properties(
            {"Comment": "no geometry"}, name="Note"
        )
        storey_obj = b.get_or_add_object("storey-1")
        storey_obj.set_properties(
            {"Attributes": {"type": "IfcBuildingStorey"}}, name="Storey"
        )
        storey_obj.add_geometry(box(1, 1, 1))
        unknown = b.get_or_add_object("unknown-1")
        unknown.set_properties({"Attributes": {"type": "IfcNotAThing"}}, name="Unknown")
        unknown.add_geometry(box(1, 1, 1))
        solid_only = b.get_or_add_object("solid-1")
        solid_only.set_properties({}, name="Raw brep")
        solid_only.add_raw_geometry(b"3dm-brep-bytes", "3dm")

        files = b.build()
    return Model(
        "project", "model", "version", directory, files.files, read_bundle(directory)
    )


def build_in(tmp_path) -> Model:
    directory = os.path.join(str(tmp_path), "bundle")
    os.makedirs(directory, exist_ok=True)
    return build(directory)
