# =============================================================================
# properties.py
# Generically clones all properties from a Speckle object into IFC entities.
#
# Source structure (from _properties / properties):
#   Attributes              → IFC element attributes (GlobalId, Name, Tag, etc.)
#   Property Sets            → dict of {pset_name: {prop_name: value}}
#   Quantities              → dict of {qto_name: {qty_name: {name, units, value}}}
#   Building Storey         → string, used for storey assignment
#   Element Type Attributes → used by type_manager to create IfcTypeObject
#   Element Type Property Sets → psets written on the IfcTypeObject
# =============================================================================

import ifcopenshell
import ifcopenshell.api
from specklepy.objects.base import Base
from utils.helpers import _get


# ---------------------------------------------------------------------------
# Safe access helpers
# ---------------------------------------------------------------------------

def _to_dict(obj) -> dict:
    """Convert a Speckle Base object or dict to a plain dict."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "get_dynamic_member_names"):
        result = {}
        try:
            for n in obj.get_dynamic_member_names():
                try:
                    result[n] = obj[n]
                except Exception:
                    pass
        except Exception:
            pass
        return result
    if hasattr(obj, "items"):
        try:
            return dict(obj.items())
        except Exception:
            pass
    return {}


# ---------------------------------------------------------------------------
# Property extraction from Speckle object
# ---------------------------------------------------------------------------

def _unflatten_dot_keys(flat: dict) -> dict:
    """Convert flat dot-notation keys into a nested dict.

    Example:
        {"Attributes.Name": "X", "Quantities.BaseQuantities.Gross Weight.value": "15"}
        → {"Attributes": {"Name": "X"}, "Quantities": {"BaseQuantities": {"Gross Weight": {"value": "15"}}}}

    Keys without dots are kept as-is. If a dict already contains nested
    dicts (i.e. non-flat), it is returned unchanged.
    """
    # Quick check: if any value is already a dict/Base, assume nested — skip
    if any(isinstance(v, dict) or hasattr(v, "get_dynamic_member_names") for v in flat.values()):
        return flat

    nested: dict = {}
    for dotted_key, value in flat.items():
        parts = dotted_key.split(".")
        d = nested
        for part in parts[:-1]:
            d = d.setdefault(part, {})
        d[parts[-1]] = value
    return nested


def get_properties(obj) -> dict:
    """Get the _properties / properties dict from a Speckle object.

    Handles both nested property dicts (ArchiCAD-style) and flat
    dot-notation dicts (Rhino/Speckle-style) by unflattening on the fly.
    """
    for key in ["_properties", "properties", "@properties"]:
        val = _get(obj, key)
        if val is not None:
            props = _to_dict(val)
            return _unflatten_dot_keys(props) if props else props
    return {}


def get_building_storey(obj) -> str:
    """Extract Building Storey name from properties."""
    props = get_properties(obj)
    storey = props.get("Building Storey")
    if storey and isinstance(storey, str):
        return storey.strip()
    return "Unknown Storey"


def get_attributes(obj) -> dict:
    """Get Attributes dict from properties."""
    props = get_properties(obj)
    return _to_dict(props.get("Attributes")) or {}


def get_element_name(obj) -> str:
    """Get element name from Attributes, falling back to object name."""
    attrs = get_attributes(obj)
    name = attrs.get("Name")
    if name:
        return str(name)
    # Fallback to object-level name fields
    for key in ["name", "_name"]:
        val = _get(obj, key)
        if val and isinstance(val, str):
            return val
    return "unnamed"


# ---------------------------------------------------------------------------
# IFC value creation
# ---------------------------------------------------------------------------

def _make_ifc_value(ifc, value):
    """Create an IFC nominal value entity from a Python value, detecting type."""
    if isinstance(value, bool):
        return ifc.create_entity("IfcBoolean", wrappedValue=value)
    if isinstance(value, int):
        return ifc.create_entity("IfcInteger", wrappedValue=value)
    if isinstance(value, float):
        return ifc.create_entity("IfcReal", wrappedValue=value)
    if isinstance(value, list):
        return ifc.create_entity("IfcLabel", wrappedValue=", ".join(str(v) for v in value))
    return ifc.create_entity("IfcLabel", wrappedValue=str(value))


# ---------------------------------------------------------------------------
# Unit → IFC quantity type mapping
# ---------------------------------------------------------------------------

_UNIT_QTY_MAP = {
    "millimetre":   ("IfcQuantityLength", "LengthValue"),
    "millimeter":   ("IfcQuantityLength", "LengthValue"),
    "centimetre":   ("IfcQuantityLength", "LengthValue"),
    "centimeter":   ("IfcQuantityLength", "LengthValue"),
    "metre":        ("IfcQuantityLength", "LengthValue"),
    "meter":        ("IfcQuantityLength", "LengthValue"),
    "foot":         ("IfcQuantityLength", "LengthValue"),
    "feet":         ("IfcQuantityLength", "LengthValue"),
    "inch":         ("IfcQuantityLength", "LengthValue"),
    "square metre": ("IfcQuantityArea", "AreaValue"),
    "square meter": ("IfcQuantityArea", "AreaValue"),
    "square foot":  ("IfcQuantityArea", "AreaValue"),
    "cubic metre":  ("IfcQuantityVolume", "VolumeValue"),
    "cubic meter":  ("IfcQuantityVolume", "VolumeValue"),
    "cubic foot":   ("IfcQuantityVolume", "VolumeValue"),
    "kilogram":     ("IfcQuantityWeight", "WeightValue"),
    "pound":        ("IfcQuantityWeight", "WeightValue"),
    "degree":       ("IfcQuantityCount", "CountValue"),
}

# Name keyword → IFC quantity type (used when no units are provided)
_NAME_QTY_MAP = {
    "length":    ("IfcQuantityLength", "LengthValue"),
    "width":     ("IfcQuantityLength", "LengthValue"),
    "height":    ("IfcQuantityLength", "LengthValue"),
    "depth":     ("IfcQuantityLength", "LengthValue"),
    "perimeter": ("IfcQuantityLength", "LengthValue"),
    "area":      ("IfcQuantityArea",   "AreaValue"),
    "volume":    ("IfcQuantityVolume", "VolumeValue"),
    "volumn":    ("IfcQuantityVolume", "VolumeValue"),  # common typo
    "weight":    ("IfcQuantityWeight", "WeightValue"),
    "mass":      ("IfcQuantityWeight", "WeightValue"),
}


# ---------------------------------------------------------------------------
# Set IFC element attributes from _properties.Attributes
# ---------------------------------------------------------------------------

def set_element_attributes(ifc, element, obj):
    """Set IFC element attributes from _properties.Attributes."""
    attrs = get_attributes(obj)
    if not attrs:
        return

    for ifc_attr in ["GlobalId", "Name", "Tag", "ObjectType", "Description"]:
        val = attrs.get(ifc_attr)
        if val is not None:
            try:
                setattr(element, ifc_attr, str(val))
            except Exception:
                pass

    # PredefinedType requires special handling (enum value)
    ptype = attrs.get("PredefinedType")
    if ptype:
        try:
            element.PredefinedType = str(ptype)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Write property sets from _properties.Property Sets
# ---------------------------------------------------------------------------

def write_property_sets(ifc, element, obj):
    """Write all property sets from _properties.Property Sets."""
    props = get_properties(obj)
    properties_section = _to_dict(props.get("Property Sets"))
    if not properties_section:
        return

    for pset_name, pset_data in properties_section.items():
        pset_dict = _to_dict(pset_data) if not isinstance(pset_data, dict) else pset_data
        if not pset_dict:
            continue

        ifc_props = []
        for prop_name, prop_value in pset_dict.items():
            if prop_name == "id":
                continue
            if prop_value is None:
                continue
            try:
                nominal = _make_ifc_value(ifc, prop_value)
                p = ifc.create_entity(
                    "IfcPropertySingleValue",
                    Name=str(prop_name),
                    NominalValue=nominal,
                )
                ifc_props.append(p)
            except Exception:
                continue

        if ifc_props:
            try:
                pset = ifcopenshell.api.run(
                    "pset.add_pset", ifc, product=element, name=pset_name
                )
                pset.HasProperties = ifc_props
            except Exception as e:
                print(f"  Warning: {pset_name}: {e}")


# ---------------------------------------------------------------------------
# Write quantity sets from _properties.Quantities
# ---------------------------------------------------------------------------

def _try_float(value):
    """Try to convert a value to float. Returns None on failure."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def write_quantity_sets(ifc, element, obj):
    """Write all quantity sets from _properties.Quantities."""
    props = get_properties(obj)
    quantities_raw = props.get("Quantities")
    if quantities_raw is None:
        return
    quantities_section = _to_dict(quantities_raw)
    if not quantities_section:
        return

    for qto_name, qto_data in quantities_section.items():
        qto_dict = _to_dict(qto_data) if not isinstance(qto_data, dict) else qto_data
        if not qto_dict:
            continue

        quantities = []
        for qty_key, qty_entry in qto_dict.items():
            if qty_key == "id":
                continue

            # Quantity entries can be:
            #   - {name, units, value} dicts (ArchiCAD / IFC-native)
            #   - plain numbers or numeric strings (Grasshopper)
            if isinstance(qty_entry, dict):
                name = qty_entry.get("name", qty_key)
                units = (qty_entry.get("units") or "").strip().lower()
                value = _try_float(qty_entry.get("value"))
            else:
                value = _try_float(qty_entry)
                if value is None:
                    continue
                name = qty_key
                units = ""

            if value is None:
                continue

            try:
                mapping = _UNIT_QTY_MAP.get(units)
                if not mapping:
                    # Infer quantity type from name keywords
                    name_lower = name.lower()
                    for keyword, m in _NAME_QTY_MAP.items():
                        if keyword in name_lower:
                            mapping = m
                            break
                if mapping:
                    qty_type, value_attr = mapping
                    qty = ifc.create_entity(
                        qty_type, Name=name, **{value_attr: value}
                    )
                else:
                    # CountValue requires int
                    qty = ifc.create_entity(
                        "IfcQuantityCount", Name=name, CountValue=int(value)
                    )
                quantities.append(qty)
            except Exception as e:
                print(f"  Warning: quantity {name}: {e}")
                continue

        if quantities:
            try:
                qto = ifcopenshell.api.run(
                    "pset.add_qto", ifc, product=element, name=qto_name
                )
                qto.Quantities = quantities
            except Exception as e:
                print(f"  Warning: {qto_name}: {e}")


# ---------------------------------------------------------------------------
# Public API — called from main.py
# ---------------------------------------------------------------------------

def write_all_properties(ifc, element, obj):
    """Write all properties, quantities, and attributes from _properties."""
    set_element_attributes(ifc, element, obj)
    write_property_sets(ifc, element, obj)
    write_quantity_sets(ifc, element, obj)
