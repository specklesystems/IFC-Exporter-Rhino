"""Bundle object properties → IFC attributes, property sets and quantity sets.

A bundle object's properties are dotted paths (``properties.Attributes.type``), so
Rhino user strings written flat (``Attributes.type``) and producers that nest
(``{"Attributes": {"type": ...}}``) arrive identically. They are read as one nested
dict with these sections:

  Attributes                 → IFC element attributes (GlobalId, Name, Tag, ...)
  Property Sets              → {pset_name: {prop_name: value}}
  Quantities                 → {qto_name: {qty_name: {name, units, value} | value}}
  Building Storey            → storey name, when the object has no bundle level
  Element Type Attributes    → IfcTypeObject attributes (see type_manager)
  Element Type Property Sets → property sets written on the IfcTypeObject
"""

import uuid
from typing import Any

import ifcopenshell
import ifcopenshell.guid
from specklepy.bundle.model import ModelObject

DEFAULT_STOREY = "Unknown Storey"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def get_properties(obj: ModelObject) -> dict[str, Any]:
    """The object's properties as a nested dict, type-level values underneath."""
    own = obj.properties.to_nested()
    type_level = obj.type_properties.to_nested()
    return _merge(type_level, own) if type_level else own


def _section(props: dict, name: str) -> dict:
    value = props.get(name)
    return value if isinstance(value, dict) else {}


def get_attributes(props: dict) -> dict:
    return _section(props, "Attributes")


def get_element_name(obj: ModelObject, props: dict) -> str:
    """Attributes.Name, then the object's name, then "unnamed"."""
    name = get_attributes(props).get("Name")
    if name not in (None, ""):
        return str(name)
    return obj.name or "unnamed"


def get_storey(obj: ModelObject, props: dict, model_scale: float):
    """Return (storey_name, elevation_mm | None).

    The bundle LEVEL node wins; the "Building Storey" property is the fallback.
    """
    level = obj.level
    if level is not None:
        name = level.name or DEFAULT_STOREY
        try:
            return name, float(level.fields.elevation) * model_scale
        except (TypeError, ValueError):
            return name, None
    storey = props.get("Building Storey")
    if isinstance(storey, str) and storey.strip():
        return storey.strip(), None
    return DEFAULT_STOREY, None


# ---------------------------------------------------------------------------
# IFC values
# ---------------------------------------------------------------------------


class ValueCache:
    """Creates IFC nominal values, reusing identical ones to keep the file small."""

    def __init__(self, ifc: ifcopenshell.file):
        self._ifc = ifc
        self._cache: dict[tuple[str, Any], object] = {}

    def nominal(self, value):
        if isinstance(value, bool):
            key = ("IfcBoolean", value)
        elif isinstance(value, int):
            key = ("IfcInteger", value)
        elif isinstance(value, float):
            key = ("IfcReal", value)
        elif isinstance(value, (list, tuple)):
            key = ("IfcLabel", ", ".join(str(v) for v in value))
        else:
            key = ("IfcLabel", str(value))
        if key not in self._cache:
            self._cache[key] = self._ifc.create_entity(key[0], wrappedValue=key[1])
        return self._cache[key]

    def single_values(self, pset: dict) -> list:
        """IfcPropertySingleValue list for one property set's scalar entries."""
        out = []
        for name, value in pset.items():
            if value is None or isinstance(value, dict):
                continue
            out.append(
                self._ifc.create_entity(
                    "IfcPropertySingleValue",
                    Name=str(name),
                    NominalValue=self.nominal(value),
                )
            )
        return out


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------


class GlobalIds:
    """Hands out unique IFC GlobalIds, deterministic per bundle applicationId.

    A stable id means re-exporting the same version yields the same GlobalIds, so
    downstream IFC tools can diff and track elements across exports.
    """

    def __init__(self):
        self._used: set[str] = set()

    def claim(self, preferred: str | None, application_id: str) -> str:
        for candidate in (preferred, _guid_from_application_id(application_id)):
            if (
                candidate
                and _is_valid_global_id(candidate)
                and candidate not in self._used
            ):
                self._used.add(candidate)
                return candidate
        guid = ifcopenshell.guid.new()
        self._used.add(guid)
        return guid


def _guid_from_application_id(application_id: str) -> str:
    try:
        value = uuid.UUID(application_id)
    except (ValueError, AttributeError, TypeError):
        value = uuid.uuid5(uuid.NAMESPACE_URL, f"speckle:{application_id}")
    return ifcopenshell.guid.compress(value.hex)


def _is_valid_global_id(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 22:
        return False
    try:
        ifcopenshell.guid.expand(value)
        return True
    except Exception:
        return False


def set_element_attributes(element, props: dict) -> None:
    """Copy Tag / ObjectType / Description / PredefinedType from Attributes."""
    attrs = get_attributes(props)
    for attr in ("Tag", "ObjectType", "Description"):
        value = attrs.get(attr)
        if value is not None and hasattr(element, attr):
            setattr(element, attr, str(value))
    ptype = attrs.get("PredefinedType")
    if ptype and hasattr(element, "PredefinedType"):
        try:
            element.PredefinedType = str(ptype)
        except Exception:
            print(f"  Warning: invalid PredefinedType {ptype!r} on {element.is_a()}")


# ---------------------------------------------------------------------------
# Property / quantity sets (shared across elements)
# ---------------------------------------------------------------------------

_UNIT_QTY_MAP = {
    "millimetre": ("IfcQuantityLength", "LengthValue"),
    "millimeter": ("IfcQuantityLength", "LengthValue"),
    "mm": ("IfcQuantityLength", "LengthValue"),
    "centimetre": ("IfcQuantityLength", "LengthValue"),
    "centimeter": ("IfcQuantityLength", "LengthValue"),
    "cm": ("IfcQuantityLength", "LengthValue"),
    "metre": ("IfcQuantityLength", "LengthValue"),
    "meter": ("IfcQuantityLength", "LengthValue"),
    "m": ("IfcQuantityLength", "LengthValue"),
    "foot": ("IfcQuantityLength", "LengthValue"),
    "feet": ("IfcQuantityLength", "LengthValue"),
    "ft": ("IfcQuantityLength", "LengthValue"),
    "inch": ("IfcQuantityLength", "LengthValue"),
    "in": ("IfcQuantityLength", "LengthValue"),
    "square metre": ("IfcQuantityArea", "AreaValue"),
    "square meter": ("IfcQuantityArea", "AreaValue"),
    "square foot": ("IfcQuantityArea", "AreaValue"),
    "m²": ("IfcQuantityArea", "AreaValue"),
    "mm²": ("IfcQuantityArea", "AreaValue"),
    "ft²": ("IfcQuantityArea", "AreaValue"),
    "cubic metre": ("IfcQuantityVolume", "VolumeValue"),
    "cubic meter": ("IfcQuantityVolume", "VolumeValue"),
    "cubic foot": ("IfcQuantityVolume", "VolumeValue"),
    "m³": ("IfcQuantityVolume", "VolumeValue"),
    "mm³": ("IfcQuantityVolume", "VolumeValue"),
    "ft³": ("IfcQuantityVolume", "VolumeValue"),
    "kilogram": ("IfcQuantityWeight", "WeightValue"),
    "kg": ("IfcQuantityWeight", "WeightValue"),
    "pound": ("IfcQuantityWeight", "WeightValue"),
}

# Used when a quantity carries no recognised unit.
_NAME_QTY_MAP = {
    "length": ("IfcQuantityLength", "LengthValue"),
    "width": ("IfcQuantityLength", "LengthValue"),
    "height": ("IfcQuantityLength", "LengthValue"),
    "depth": ("IfcQuantityLength", "LengthValue"),
    "perimeter": ("IfcQuantityLength", "LengthValue"),
    "area": ("IfcQuantityArea", "AreaValue"),
    "volume": ("IfcQuantityVolume", "VolumeValue"),
    "volumn": ("IfcQuantityVolume", "VolumeValue"),
    "weight": ("IfcQuantityWeight", "WeightValue"),
    "mass": ("IfcQuantityWeight", "WeightValue"),
}


def _try_float(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _quantity_entries(qto: dict) -> list[tuple[str, str, float]]:
    """(name, units, value) for every numeric quantity in a quantity set."""
    out = []
    for key, entry in qto.items():
        if isinstance(entry, dict):
            name = str(entry.get("name") or key)
            units = str(entry.get("units") or "").strip().lower()
            value = _try_float(entry.get("value"))
        else:
            name, units, value = str(key), "", _try_float(entry)
        if value is not None:
            out.append((name, units, value))
    return out


def _quantity_class(name: str, units: str) -> tuple[str, str]:
    mapping = _UNIT_QTY_MAP.get(units)
    if mapping:
        return mapping
    lowered = name.lower()
    for keyword, m in _NAME_QTY_MAP.items():
        if keyword in lowered:
            return m
    return ("IfcQuantityCount", "CountValue")


class PropertySetManager:
    """Creates each distinct IfcPropertySet / IfcElementQuantity once and links all
    elements sharing it through one IfcRelDefinesByProperties at flush time."""

    def __init__(self, ifc: ifcopenshell.file, values: ValueCache):
        self._ifc = ifc
        self._values = values
        self._cache: dict[str, object] = {}
        self._pending: dict[int, list] = {}
        self.unique = 0
        self.shared = 0

    def queue(self, element, props: dict) -> None:
        for pset_name, pset in _section(props, "Property Sets").items():
            if isinstance(pset, dict):
                self._queue_pset(element, str(pset_name), pset)
        for qto_name, qto in _section(props, "Quantities").items():
            if isinstance(qto, dict):
                self._queue_qto(element, str(qto_name), qto)

    def _link(self, key: str, element, create) -> None:
        if key in self._cache:
            self.shared += 1
        else:
            entity = create()
            if entity is None:
                return
            self._cache[key] = entity
            self.unique += 1
        self._pending.setdefault(self._cache[key].id(), []).append(element)

    def _queue_pset(self, element, name: str, pset: dict) -> None:
        content = sorted(
            (str(k), repr(v))
            for k, v in pset.items()
            if v is not None and not isinstance(v, dict)
        )
        if not content:
            return

        def create():
            props = self._values.single_values(pset)
            if not props:
                return None
            return self._ifc.create_entity(
                "IfcPropertySet",
                GlobalId=ifcopenshell.guid.new(),
                Name=name,
                HasProperties=props,
            )

        self._link(repr(("pset", name, content)), element, create)

    def _queue_qto(self, element, name: str, qto: dict) -> None:
        entries = _quantity_entries(qto)
        if not entries:
            return

        def create():
            quantities = []
            for qty_name, units, value in entries:
                qty_class, attr = _quantity_class(qty_name, units)
                if qty_class == "IfcQuantityCount":
                    value = int(value)
                quantities.append(
                    self._ifc.create_entity(qty_class, Name=qty_name, **{attr: value})
                )
            return self._ifc.create_entity(
                "IfcElementQuantity",
                GlobalId=ifcopenshell.guid.new(),
                Name=name,
                Quantities=quantities,
            )

        self._link(repr(("qto", name, sorted(entries))), element, create)

    def flush(self) -> None:
        for definition_id, elements in self._pending.items():
            self._ifc.create_entity(
                "IfcRelDefinesByProperties",
                GlobalId=ifcopenshell.guid.new(),
                RelatedObjects=elements,
                RelatingPropertyDefinition=self._ifc.by_id(definition_id),
            )
        self._pending.clear()

    def print_stats(self) -> None:
        print(
            f"  Property sets      : {self.unique} unique / "
            f"{self.unique + self.shared} assigned"
        )
