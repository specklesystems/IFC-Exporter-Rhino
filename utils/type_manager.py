# =============================================================================
# type_manager.py
# Creates and caches IfcTypeObjects from Element Type Attributes and links
# element instances to them via IfcRelDefinesByType.
#
# Type info comes from _properties:
#   Element Type Attributes   → type class, Name, GlobalId, Tag, PredefinedType
#   Element Type Property Sets → psets written on the type object
#
# Type objects are SHARED — keyed by GlobalId or (type_class, Name).
# =============================================================================

import ifcopenshell
import ifcopenshell.api
from specklepy.objects.base import Base
from utils.properties import get_properties, _to_dict, _make_ifc_value


class TypeManager:
    """
    Creates IfcTypeObjects on demand and caches them.
    Call assign(element, obj) for each exported element.
    """

    def __init__(self, ifc: ifcopenshell.file):
        self._ifc = ifc
        self._cache: dict[str, object] = {}      # cache_key → IfcTypeObject
        self._pending: dict[int, list] = {}       # type_obj.id() → [element, ...]

    def assign(self, element, obj: Base, ifc_class: str = ""):
        """Create or retrieve cached type object and queue the assignment."""
        props = get_properties(obj)
        type_attrs = _to_dict(props.get("Element Type Attributes"))
        type_psets = _to_dict(props.get("Element Type Property Sets"))

        if not type_attrs and not type_psets:
            return

        # Determine type class and cache key
        type_class = None
        if type_attrs:
            type_class = type_attrs.get("type")

        if type_class:
            # Format A: Element Type Attributes has explicit type info
            global_id = type_attrs.get("GlobalId")
            name = type_attrs.get("Name") or ""
            cache_key = global_id if global_id else f"{type_class}:{name}"

            if cache_key not in self._cache:
                type_obj = self._create_type(type_class, type_attrs, type_psets)
                self._cache[cache_key] = type_obj
        else:
            # Format B: No explicit type class — derive from element IFC class
            type_class = ifc_class + "Type" if ifc_class else None
            if not type_class:
                return

            # Merge: if type_attrs has no 'type' key, it contains psets directly
            merged_psets = type_psets.copy() if type_psets else {}
            if type_attrs:
                merged_psets.update(type_attrs)

            cache_key = f"{type_class}:{repr(sorted(merged_psets.items()))}"

            if cache_key not in self._cache:
                type_obj = self._create_type(type_class, {}, merged_psets)
                self._cache[cache_key] = type_obj

        type_obj = self._cache[cache_key]
        type_id = type_obj.id()

        if type_id not in self._pending:
            self._pending[type_id] = []
        self._pending[type_id].append(element)

    def flush(self):
        """Write all IfcRelDefinesByType relationships."""
        for type_id, elements in self._pending.items():
            type_obj = self._ifc.by_id(type_id)
            ifcopenshell.api.run(
                "type.assign_type", self._ifc,
                related_objects=elements,
                relating_type=type_obj,
            )
        self._pending.clear()
        print(f"   Type objects created: {len(self._cache)}")

    def _create_type(self, type_class: str, type_attrs: dict, type_psets: dict):
        """Instantiate the IfcTypeObject with attributes and property sets."""
        ifc = self._ifc
        name = type_attrs.get("Name") or ""

        type_obj = ifcopenshell.api.run(
            "root.create_entity", ifc,
            ifc_class=type_class,
            name=name,
        )

        # Set standard attributes
        for attr in ["GlobalId", "Tag", "Description", "ElementType"]:
            val = type_attrs.get(attr)
            if val is not None:
                try:
                    setattr(type_obj, attr, str(val))
                except Exception:
                    pass

        # PredefinedType (enum)
        ptype = type_attrs.get("PredefinedType")
        if ptype:
            try:
                type_obj.PredefinedType = str(ptype)
            except Exception:
                pass

        # Write type-level property sets
        if type_psets:
            for pset_name, pset_data in type_psets.items():
                pset_dict = _to_dict(pset_data) if not isinstance(pset_data, dict) else pset_data
                if not pset_dict:
                    continue
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
                if ifc_props:
                    try:
                        pset = ifcopenshell.api.run(
                            "pset.add_pset", ifc, product=type_obj, name=pset_name
                        )
                        pset.HasProperties = ifc_props
                    except Exception:
                        pass

        return type_obj
