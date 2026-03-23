# Speckle → IFC 4.3 Exporter (Rhino)

A [Speckle Automate](https://automate.speckle.dev/) function that converts Speckle models (from Rhino and other authoring tools) into IFC 4.3 files.

🚫 **BLOCKER:** fIles that are bigger than 100MB are failing to upload because automate uses the /api/streams/:streamId/blobs endpoint (proxied through our server, which has a 100MB request size limit imposed by cloudflare) - we havea ticket to resolve this TBD.

## How It Works

1. **Receives** a Speckle model version via Speckle Automate.
2. **Traverses** the nested Collection tree to find all BIM elements.
3. **Classifies** each element into its IFC type (e.g. `IfcColumn`, `IfcWall`) using the `Attributes.type` property.
4. **Exports geometry** — meshes, instances (block definitions), and curves — into IFC representations.
5. **Clones properties** — attributes, property sets, and quantities — from the Speckle object onto the IFC entity.
6. **Writes** the resulting `.ifc` file.

## Supported Property Formats

The exporter handles two property formats:

### Nested (ArchiCAD / IFC-native)
Properties are stored as nested dicts under `_properties`:
```
_properties:
  Attributes:
    Name: "MyColumn"
    type: "IfcColumn"
  Property Sets:
    Pset_ColumnCommon:
      IsExternal: true
  Quantities:
    BaseQuantities:
      Height: {name: "Height", units: "millimetre", value: 3000}
```

### Flat Dot-Notation (Rhino / Speckle)
Properties are stored as flat key-value pairs with dot-separated paths under `properties`:
```
properties:
  Attributes.Name: "600S162-43-50"
  Attributes.type: "IfcColumn"
  Attributes.GlobalId: "yOTS1rnOhBKW4JIfec29TS"
  Quantities.BaseQuantities.Gross Weight.value: "15.452"
  Quantities.BaseQuantities.Member Length.value: "118.938"
```

The exporter automatically detects the format and unflattens dot-notation keys into the nested structure before processing.

## Function Inputs

| Input | Description |
|---|---|
| `file_name` | Output IFC filename (timestamp is appended) |
| `IFC_PROJECT_NAME` | Name for the IfcProject entity |
| `IFC_SITE_NAME` | Name for the IfcSite entity |
| `IFC_BUILDING_NAME` | Name for the IfcBuilding entity |

## Project Structure

```
main.py                 # Automate entry point — traversal, export loop, IFC writing
utils/
  traversal.py          # Walks the Speckle Collection tree
  mapper.py             # Maps Speckle objects → IFC entity classes
  properties.py         # Extracts & writes attributes, property sets, quantities
  geometry.py           # Mesh → IFC geometry conversion
  instances.py          # Block instance / definition handling
  curves.py             # Curve geometry (Polycurve, Line, Arc)
  writer.py             # IFC scaffold creation, storey management
  type_manager.py       # IfcTypeObject creation & assignment
  materials.py          # Material mapping
  helpers.py            # Shared utilities (_get, unit scales)
  receiver.py           # Speckle server connection & data retrieval
```

## Getting Started

## Using with Speckle Automate

1. Go to the Automations tab in your project
2. Click New Automation
3. Select your function from the library
4. Configure function inputs and parameters
5. Choose a Speckle model to trigger the automation
6. Name your automation and click Create

## Resources

- [SpecklePy SDK](https://speckle.guide/dev/python.html)
- [Speckle Automate](https://docs.speckle.systems/developers/automate/introduction)
- [IFC 4.3 Documentation](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/)
