# Speckle → IFC 4.3 Exporter (Rhino)

## 🚧 Project Status: WIP
Hey there! This project is still under active development, so expect changes, bugs, and incomplete features.
If you have any questions or suggestions, don’t hesitate to reach out at: **nikos@speckle.systems**

A [Speckle Automate](https://docs.speckle.systems/developers/automate/introduction) function that converts Speckle models (built for Rhino, works on any bundle) into IFC4X3 files.

> ⚠️ **Note on Model Uploads**
>
> Large models (greater than 200MB) may fail to upload due to current file size limitations. The team is actively working on resolving this issue.

## How It Works

1. **Receives** the triggering version as a Speckle bundle (`AutomationContext.receive_version_bundle`, specklepy 2026.9+).
2. **Walks** every bundle object. Definition members are exported through the objects that place them, not on their own.
3. **Classifies** each object into its IFC class (e.g. `IfcColumn`, `IfcWall`) from `Attributes.type`. A name that is not an instantiable IFC4X3 product falls back to `IfcBuildingElementProxy`.
4. **Exports geometry**: direct meshes, placed definitions (block instances, nested ones included) and, when an object has no surfaces, curves.
5. **Writes properties**: attributes, property sets, quantities and type objects from the object's properties.
6. **Writes** the `.ifc` file, compressed as a `.zip`, attaches it to the run and ends the run's status message with the zip's download link.

> ℹ️ The function reads **bundle versions only** (the speckle-next storage format). A version without a bundle fails the run with a message saying so.

## Performance Optimizations

- **Shared definition geometry**: each block definition becomes one `IfcRepresentationMap`, referenced by an `IfcMappedItem` per placement. The producer already deduplicates bundle geometry by content, so identical definitions share too.
- **Shared property sets**: identical `IfcPropertySet` / `IfcElementQuantity` entities are created once and linked through batched `IfcRelDefinesByProperties`.
- **Batched relationships**: spatial containment and type assignments are written in bulk at the end.
- **Vertex deduplication and rounding**: near-coincident vertices are merged (0.01 mm), coordinates are rounded to 3 decimals, and degenerate faces are dropped (GEM111).
- **Entity reuse**: `IfcDirection` and nominal values are cached and reused across the file.
- **Lazy styles**: `IfcSurfaceStyle` entities are only created when assigned to geometry (no orphans, IFC105).
- **ZIP compression** of the output.

## Properties

Bundle properties are dotted paths, so Rhino user strings written flat and producers that nest arrive the same way:

```
Attributes.type: "IfcColumn"                   Attributes:
Attributes.Name: "C1"                            type: "IfcColumn"
Attributes.GlobalId: "yOTS1rnOhBKW4JIfec29TS"    Name: "C1"
Property Sets.Pset_ColumnCommon.IsExternal       Property Sets:
Quantities.BaseQuantities.Height.value             Pset_ColumnCommon: {IsExternal: true}
Quantities.BaseQuantities.Height.units           Quantities:
                                                   BaseQuantities:
                                                     Height: {name: Height, units: millimetre, value: 3000}
```

| Section | Becomes |
|---|---|
| `Attributes` | `GlobalId`, `Name`, `Tag`, `ObjectType`, `Description`, `PredefinedType`; `type` picks the IFC class |
| `Property Sets` | one `IfcPropertySet` per set |
| `Quantities` | one `IfcElementQuantity` per set; the quantity class comes from `units`, else from the name |
| `Element Type Attributes` / `Element Type Property Sets` | a shared `IfcTypeObject` (`type` picks its class, e.g. `IfcColumnType`) |
| `Building Storey` | the storey, when the object has no bundle level |

Type-level bundle properties are read underneath the object's own. Objects without `Attributes.GlobalId` get a GlobalId derived from their applicationId, so re-exporting a version keeps the same ids.

## Storeys

Objects on a bundle level go into an `IfcBuildingStorey` of that name and elevation. Otherwise the `Building Storey` property names the storey, and everything else lands in `Unknown Storey`.

## Geometry

- **Meshes** become one `IfcPolygonalFaceSet` each, so every mesh carries its own style. The element is placed at its bounding-box centre (X/Y) and minimum Z.
- **Placed definitions** become `IfcMappedItem`s with an `IfcCartesianTransformationOperator3DnonUniform` carrying the composed 4x4 transform (explicit Axis3, so mirrored and non-orthogonal placements keep their orientation). A placed object with no IFC class of its own takes its definition member's.
- **Curves** (line, arc, circle, polyline, polycurve, NURBS via its display polyline) become `IfcIndexedPolyCurve`s, used only when the object has no surface geometry.
- **Materials**: the bundle render material (colour and opacity) becomes the `IfcSurfaceStyle`; a display colour is the fallback.
- Every length is scaled to millimetres from the geometry's (or the model's) units. Raw host solids such as Rhino breps cannot be read here and are skipped; their display meshes are exported.

## Function Inputs

| Input | Description |
|---|---|
| `file_name` | Output IFC filename (timestamp is appended) |
| `IFC_PROJECT_NAME` | Name for the IfcProject entity |
| `IFC_SITE_NAME` | Name for the IfcSite entity |
| `IFC_BUILDING_NAME` | Name for the IfcBuilding entity |

## Project Structure

```
main.py                 # Automate entry point: receive bundle, export, zip, attach + link
utils/
  exporter.py           # The export loop over bundle objects
  bundle_geometry.py    # Resolves an object's direct and placed (instanced) geometry
  geometry.py           # Meshes, mapped items and curves → IFC representations
  instances.py          # Placement transforms → IFC transformation operators
  curves.py             # Curves → IfcIndexedPolyCurve
  mapper.py             # Attributes.type → IFC class (validated against IFC4X3)
  properties.py         # Attributes, property sets, quantities, GlobalIds, storeys
  type_manager.py       # IfcTypeObject creation and assignment
  materials.py          # Bundle materials / colours → IfcSurfaceStyle
  writer.py             # IFC scaffold and storey management
  receiver.py           # Receive a version outside Automate (local debugging)
  helpers.py            # Unit scaling
tests/
  fixture_bundle.py     # Builds a Rhino-shaped bundle locally
  test_exporter.py      # Exports it and checks the IFC (schema-validated)
  test_function.py      # End to end against a server (skipped without credentials)
```

## Development

With [mise](https://mise.jdx.dev): `mise run install`, then `mise run test`, `mise run lint` and `mise run fmt`. Without it: Python 3.13, `pip install .[dev]`, `pytest`.

The exporter tests build a bundle with specklepy's `BundleBuilder` and need no server. To run the server integration test or `utils/receiver.py`, copy `.env.example` to `.env` and fill it in.

## Getting Started

### Using with Speckle Automate

1. Go to the Automations tab in your project
2. Click New Automation
3. Select your function from the library
4. Configure function inputs and parameters
5. Choose a Speckle model to trigger the automation
6. Name your automation and click Create

## Resources

- [SpecklePy SDK](https://github.com/specklesystems/specklepy)
- [Speckle Automate](https://docs.speckle.systems/developers/automate/introduction)
- [IFC 4.3 Documentation](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/)
