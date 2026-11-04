"""Export a locally built bundle and check the IFC that comes out."""

import os
import zipfile
from types import SimpleNamespace

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.element
import ifcopenshell.validate
import pytest

from main import FunctionInputs, automate_function, write_zipped_ifc
from tests import fixture_bundle
from utils.exporter import export_model


@pytest.fixture()
def model(tmp_path):
    m = fixture_bundle.build_in(tmp_path)
    yield m
    m.close()


@pytest.fixture()
def exported(model):
    return export_model(model, "Project", "Site", "Building")


def by_name(ifc, name):
    [element] = [e for e in ifc.by_type("IfcProduct") if e.Name == name]
    return element


def test_file_is_schema_valid(exported, tmp_path):
    ifc, _ = exported
    path = tmp_path / "out.ifc"
    ifc.write(str(path))
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(ifcopenshell.open(str(path)), logger)
    assert logger.statements == []


def test_counts(exported):
    _, stats = exported
    assert stats.exported == 7
    assert stats.instanced == 3
    assert stats.definition_members == 1  # chair-src
    assert stats.without_geometry == 2  # note-1 and the raw-brep-only object
    assert stats.skipped_spatial == 1


def test_classes_come_from_attributes_type(exported):
    ifc, _ = exported
    assert by_name(ifc, "C1").is_a("IfcColumn")
    assert by_name(ifc, "B1").is_a("IfcBeam")
    # Placements without a class of their own take their definition member's.
    assert by_name(ifc, "Chair 1").is_a("IfcFurniture")
    # Unknown classes degrade instead of failing the export.
    assert by_name(ifc, "Unknown").is_a() == "IfcBuildingElementProxy"
    assert not [e for e in ifc.by_type("IfcProduct") if e.Name == "Storey"]


def test_attributes_and_stable_global_ids(exported):
    ifc, _ = exported
    column = by_name(ifc, "C1")
    assert column.Tag == "COL-01"
    assert column.GlobalId == ifcopenshell.guid.compress(
        fixture_bundle.COLUMN_ID.replace("-", "")
    )
    ids = [e.GlobalId for e in ifc.by_type("IfcRoot")]
    assert len(ids) == len(set(ids))


def test_property_and_quantity_sets(exported):
    ifc, _ = exported
    column = by_name(ifc, "C1")
    psets = ifcopenshell.util.element.get_psets(column)
    assert psets["Pset_ColumnCommon"]["IsExternal"] is True
    assert psets["Pset_ColumnCommon"]["Reference"] == "HEB200"
    assert psets["BaseQuantities"]["Height"] == 3000.0
    [qto] = [q for q in ifc.by_type("IfcElementQuantity")]
    assert qto.Quantities[0].is_a("IfcQuantityLength")

    # Identical property sets are created once and shared.
    beam = by_name(ifc, "B1")
    shared = [p for p in ifc.by_type("IfcPropertySet") if p.Name == "Pset_ColumnCommon"]
    assert len(shared) == 1
    assert (
        ifcopenshell.util.element.get_psets(beam)["Pset_ColumnCommon"]["Reference"]
        == "HEB200"
    )


def test_type_object(exported):
    ifc, _ = exported
    column_type = ifcopenshell.util.element.get_type(by_name(ifc, "C1"))
    assert column_type.is_a("IfcColumnType")
    assert column_type.Name == "Steel Column"
    psets = ifcopenshell.util.element.get_psets(column_type)
    assert psets["Pset_ColumnTypeCommon"]["Status"] == "NEW"


def test_storeys_from_levels_then_properties(exported):
    ifc, _ = exported
    storeys = {s.Name: s for s in ifc.by_type("IfcBuildingStorey")}
    assert storeys["Level 1"].Elevation == 3000.0  # 3 m in the mm file
    assert (
        ifcopenshell.util.element.get_container(by_name(ifc, "C1"))
        == storeys["Level 1"]
    )
    assert (
        ifcopenshell.util.element.get_container(by_name(ifc, "B1")) == storeys["Roof"]
    )
    assert (
        ifcopenshell.util.element.get_container(by_name(ifc, "Chair 1"))
        == storeys["Unknown Storey"]
    )


def _faceset_points(element):
    [rep] = element.Representation.Representations
    return [tuple(p) for item in rep.Items for p in item.Coordinates.CoordList]


def test_direct_meshes_are_scaled_to_mm_and_placed_locally(exported):
    ifc, _ = exported
    column = by_name(ifc, "C1")
    origin = column.ObjectPlacement.RelativePlacement.Location.Coordinates
    assert origin == (100.0, 100.0, 0.0)  # bbox centre in X/Y, min Z
    xs = sorted({p[0] for p in _faceset_points(column)})
    assert xs == [-100.0, 100.0]
    zs = sorted({p[2] for p in _faceset_points(column)})
    assert zs == [0.0, 3000.0]

    # The beam mesh declares its own units (mm) and is not rescaled.
    beam_xs = sorted({p[0] for p in _faceset_points(by_name(ifc, "B1"))})
    assert beam_xs == [-3000.0, 3000.0]


def test_instances_share_one_representation_map(exported):
    ifc, stats = exported
    chair_1, chair_2 = by_name(ifc, "Chair 1"), by_name(ifc, "Chair 2")
    [item_1] = chair_1.Representation.Representations[0].Items
    [item_2] = chair_2.Representation.Representations[0].Items
    assert item_1.MappingSource == item_2.MappingSource
    assert item_1.MappingTarget.LocalOrigin.Coordinates == (5000.0, 0.0, 0.0)
    assert item_2.MappingTarget.LocalOrigin.Coordinates == (0.0, 5000.0, 0.0)
    assert tuple(round(c, 6) for c in item_2.MappingTarget.Axis1.DirectionRatios) == (
        0.0,
        1.0,
        0.0,
    )
    assert stats.rep_maps == 2  # chair + table


def test_nested_instances_compose_transforms(exported):
    ifc, _ = exported
    table = by_name(ifc, "Table")
    items = table.Representation.Representations[0].Items
    origins = sorted(i.MappingTarget.LocalOrigin.Coordinates for i in items)
    assert origins == [(10000.0, 10000.0, 0.0), (10200.0, 11000.0, 0.0)]
    chair_map = by_name(ifc, "Chair 1").Representation.Representations[0].Items[0]
    assert chair_map.MappingSource in [i.MappingSource for i in items]


def test_curves_fall_back_to_indexed_polycurves(exported):
    ifc, _ = exported
    [rep] = by_name(ifc, "Edge").Representation.Representations
    assert rep.RepresentationType == "Curve3D"
    assert [i.is_a() for i in rep.Items] == ["IfcIndexedPolyCurve"] * 2


def test_materials_become_surface_styles(exported):
    ifc, _ = exported
    styles = {s.Name: s for s in ifc.by_type("IfcSurfaceStyle")}
    assert set(styles) == {"Steel", "Glass"}
    [rendering] = styles["Glass"].Styles
    assert rendering.Transparency == pytest.approx(0.75)
    styled = {
        si.Item.id(): si.Styles[0].Name
        for si in ifc.by_type("IfcStyledItem")
        if si.Item is not None
    }
    [column_item] = by_name(ifc, "C1").Representation.Representations[0].Items
    assert styled[column_item.id()] == "Steel"


def test_zipped_output(exported, tmp_path):
    ifc, _ = exported
    zip_path = write_zipped_ifc(ifc, "export.ifc", tmp_path)
    with zipfile.ZipFile(zip_path) as zf:
        [name] = zf.namelist()
    assert name.startswith("export_") and name.endswith(".ifc")


class FakeContext:
    def __init__(self, model):
        self._model = model
        self.files = []
        self.status = None
        self.automation_run_data = SimpleNamespace(
            speckle_server_url="https://app.speckle.systems/", project_id="proj123"
        )

    def receive_version_bundle(self):
        return self._model

    def store_file_result(self, path):
        self.files.append(path)
        return "blob42"

    def mark_run_success(self, message):
        self.status = ("success", message)

    def mark_run_failed(self, message):
        self.status = ("failed", message)


def test_automate_function_exports_and_stores_the_zip(model, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    context = FakeContext(model)
    automate_function(
        context,
        FunctionInputs(
            file_name="model",
            IFC_PROJECT_NAME="Project",
            IFC_SITE_NAME="Site",
            IFC_BUILDING_NAME="Building",
        ),
    )
    assert context.status[0] == "success"
    assert context.status[1].endswith(
        "https://app.speckle.systems/api/stream/proj123/blob/blob42"
    )
    [stored] = context.files
    assert stored.suffix == ".zip" and stored.exists()
    assert not os.path.exists(model.directory)  # the received bundle is cleaned up
