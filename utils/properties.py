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
import ifcopenshell.guid
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

_ifc_value_cache: dict[int, dict] = {}


def _make_ifc_value(ifc, value):
    """Create a cached IFC nominal value entity from a Python value, detecting type.

    Identical values reuse the same IFC entity to reduce file size.
    """
    fid = id(ifc)
    if fid not in _ifc_value_cache:
        _ifc_value_cache[fid] = {}
    cache = _ifc_value_cache[fid]

    if isinstance(value, bool):
        cache_key = ("IfcBoolean", value)
    elif isinstance(value, int):
        cache_key = ("IfcInteger", value)
    elif isinstance(value, float):
        cache_key = ("IfcReal", value)
    elif isinstance(value, list):
        cache_key = ("IfcLabel", ", ".join(str(v) for v in value))
    else:
        cache_key = ("IfcLabel", str(value))

    if cache_key not in cache:
        entity_type, wrapped = cache_key
        cache[cache_key] = ifc.create_entity(entity_type, wrappedValue=wrapped)
    return cache[cache_key]


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
# PropertySetManager — shared property sets across elements
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


def _pset_content_key(pset_name: str, items: list) -> str:
    """Build a hashable key from pset name + sorted property name-value pairs."""
    return repr((pset_name, sorted(items)))


def _qto_content_key(qto_name: str, items: list) -> str:
    """Build a hashable key from qto name + sorted quantity tuples."""
    return repr((qto_name, sorted(items)))


class PropertySetManager:
    """Creates shared IfcPropertySet / IfcElementQuantity entities.

    Instead of creating one pset per element, identical psets are created
    once and linked to all elements that share them via a single
    IfcRelDefinesByProperties (written at flush time).
    """

    def __init__(self, ifc: ifcopenshell.file):
        self._ifc = ifc
        # content_key → IfcPropertySet / IfcElementQuantity entity
        self._pset_cache: dict[str, object] = {}
        # pset entity id → [element, ...]
        self._pending: dict[int, list] = {}
        self._pset_count = 0
        self._shared_count = 0

    def queue_property_sets(self, element, obj):
        """Extract Property Sets from obj and queue shared assignment to element."""
        props = get_properties(obj)
        properties_section = _to_dict(props.get("Property Sets"))
        if not properties_section:
            return

        ifc = self._ifc
        for pset_name, pset_data in properties_section.items():
            pset_dict = _to_dict(pset_data) if not isinstance(pset_data, dict) else pset_data
            if not pset_dict:
                continue

            # Build content items for hashing (skip id and None values)
            content_items = []
            for prop_name, prop_value in pset_dict.items():
                if prop_name == "id" or prop_value is None:
                    continue
                content_items.append((str(prop_name), repr(prop_value)))

            if not content_items:
                continue

            key = _pset_content_key(pset_name, content_items)

            if key not in self._pset_cache:
                # Create the shared IfcPropertySet entity
                ifc_props = []
                for prop_name, prop_value in pset_dict.items():
                    if prop_name == "id" or prop_value is None:
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

                if not ifc_props:
                    continue

                pset = ifc.create_entity(
                    "IfcPropertySet",
                    GlobalId=ifcopenshell.guid.new(),
                    Name=pset_name,
                    HasProperties=ifc_props,
                )
                self._pset_cache[key] = pset
                self._pset_count += 1
            else:
                self._shared_count += 1

            pset = self._pset_cache[key]
            pid = pset.id()
            if pid not in self._pending:
                self._pending[pid] = []
            self._pending[pid].append(element)

    def queue_quantity_sets(self, element, obj):
        """Extract Quantities from obj and queue shared assignment to element."""
        props = get_properties(obj)
        quantities_raw = props.get("Quantities")
        if quantities_raw is None:
            return
        quantities_section = _to_dict(quantities_raw)
        if not quantities_section:
            return

        ifc = self._ifc
        for qto_name, qto_data in quantities_section.items():
            qto_dict = _to_dict(qto_data) if not isinstance(qto_data, dict) else qto_data
            if not qto_dict:
                continue

            # Build content items for hashing
            content_items = []
            for qty_key, qty_entry in qto_dict.items():
                if qty_key == "id":
                    continue
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
                if value is not None:
                    content_items.append((name, units, value))

            if not content_items:
                continue

            key = _qto_content_key(qto_name, content_items)

            if key not in self._pset_cache:
                quantities = []
                for qty_key, qty_entry in qto_dict.items():
                    if qty_key == "id":
                        continue
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
                            qty = ifc.create_entity(
                                "IfcQuantityCount", Name=name, CountValue=int(value)
                            )
                        quantities.append(qty)
                    except Exception as e:
                        print(f"  Warning: quantity {name}: {e}")
                        continue

                if not quantities:
                    continue

                qto = ifc.create_entity(
                    "IfcElementQuantity",
                    GlobalId=ifcopenshell.guid.new(),
                    Name=qto_name,
                    Quantities=quantities,
                )
                self._pset_cache[key] = qto
                self._pset_count += 1
            else:
                self._shared_count += 1

            qto = self._pset_cache[key]
            qid = qto.id()
            if qid not in self._pending:
                self._pending[qid] = []
            self._pending[qid].append(element)

    def flush(self):
        """Write all batched IfcRelDefinesByProperties relationships."""
        ifc = self._ifc
        for pset_id, elements in self._pending.items():
            pset = ifc.by_id(pset_id)
            try:
                ifc.create_entity(
                    "IfcRelDefinesByProperties",
                    GlobalId=ifcopenshell.guid.new(),
                    RelatedObjects=elements,
                    RelatingPropertyDefinition=pset,
                )
            except Exception as e:
                print(f"  Warning: pset rel: {e}")
        self._pending.clear()

    def print_stats(self):
        total = self._pset_count + self._shared_count
        print(f"  Property sets: {self._pset_count} unique / {total} total ({self._shared_count} shared)")


# ---------------------------------------------------------------------------
# Public API — called from main.py
# ---------------------------------------------------------------------------

def write_all_properties(ifc, element, obj, property_manager=None):
    """Write all properties, quantities, and attributes from _properties."""
    set_element_attributes(ifc, element, obj)
    if property_manager:
        property_manager.queue_property_sets(element, obj)
        property_manager.queue_quantity_sets(element, obj)
    else:
        # Fallback: direct per-element creation (no sharing)
        _write_property_sets_direct(ifc, element, obj)
        _write_quantity_sets_direct(ifc, element, obj)


def _write_property_sets_direct(ifc, element, obj):
    """Legacy per-element property set writing (fallback)."""
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
            if prop_name == "id" or prop_value is None:
                continue
            try:
                nominal = _make_ifc_value(ifc, prop_value)
                p = ifc.create_entity("IfcPropertySingleValue", Name=str(prop_name), NominalValue=nominal)
                ifc_props.append(p)
            except Exception:
                continue
        if ifc_props:
            try:
                pset = ifcopenshell.api.run("pset.add_pset", ifc, product=element, name=pset_name)
                pset.HasProperties = ifc_props
            except Exception:
                pass


def _write_quantity_sets_direct(ifc, element, obj):
    """Legacy per-element quantity set writing (fallback)."""
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
                    for keyword, m in _NAME_QTY_MAP.items():
                        if keyword in name.lower():
                            mapping = m
                            break
                if mapping:
                    qty_type, value_attr = mapping
                    qty = ifc.create_entity(qty_type, Name=name, **{value_attr: value})
                else:
                    qty = ifc.create_entity("IfcQuantityCount", Name=name, CountValue=int(value))
                quantities.append(qty)
            except Exception:
                continue
        if quantities:
            try:
                qto = ifcopenshell.api.run("pset.add_qto", ifc, product=element, name=qto_name)
                qto.Quantities = quantities
            except Exception:
                pass
