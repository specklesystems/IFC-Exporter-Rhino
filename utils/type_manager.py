"""Element Type Attributes / Property Sets → shared IfcTypeObjects.

Types are keyed by GlobalId, else (type class, Name), and linked to their elements
through IfcRelDefinesByType at flush time.
"""

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.type

from utils.mapper import resolve_class
from utils.properties import ValueCache


class TypeManager:
    def __init__(self, ifc: ifcopenshell.file, values: ValueCache):
        self._ifc = ifc
        self._values = values
        self._cache: dict[str, object] = {}
        self._pending: dict[int, list] = {}

    def assign(self, element, props: dict, ifc_class: str) -> None:
        type_attrs = props.get("Element Type Attributes")
        type_psets = props.get("Element Type Property Sets")
        type_attrs = type_attrs if isinstance(type_attrs, dict) else {}
        type_psets = type_psets if isinstance(type_psets, dict) else {}
        if not type_attrs and not type_psets:
            return

        declared = type_attrs.get("type")
        if isinstance(declared, str) and declared.strip():
            type_class = resolve_class(declared.strip(), "IfcTypeObject")
            attrs, psets = type_attrs, type_psets
            global_id = type_attrs.get("GlobalId")
            key = global_id or f"{type_class}:{type_attrs.get('Name') or ''}"
        else:
            # No declared type class: derive it from the element, and treat the
            # attribute section as further property sets.
            type_class = resolve_class(f"{ifc_class}Type", "IfcTypeObject")
            attrs = {}
            psets = {**type_psets, **type_attrs}
            key = f"{type_class}:{sorted(psets.items(), key=lambda kv: kv[0])!r}"

        if type_class is None:
            return
        if key not in self._cache:
            self._cache[key] = self._create_type(type_class, attrs, psets)
        self._pending.setdefault(self._cache[key].id(), []).append(element)

    def flush(self) -> None:
        for type_id, elements in self._pending.items():
            ifcopenshell.api.type.assign_type(
                self._ifc,
                related_objects=elements,
                relating_type=self._ifc.by_id(type_id),
            )
        self._pending.clear()

    @property
    def count(self) -> int:
        return len(self._cache)

    def _create_type(self, type_class: str, attrs: dict, psets: dict):
        type_obj = ifcopenshell.api.root.create_entity(
            self._ifc, ifc_class=type_class, name=str(attrs.get("Name") or "")
        )
        for attr in ("GlobalId", "Tag", "Description", "ElementType"):
            value = attrs.get(attr)
            if value is not None and hasattr(type_obj, attr):
                try:
                    setattr(type_obj, attr, str(value))
                except Exception:
                    print(f"  Warning: invalid {attr} {value!r} on {type_class}")
        ptype = attrs.get("PredefinedType")
        if ptype and hasattr(type_obj, "PredefinedType"):
            try:
                type_obj.PredefinedType = str(ptype)
            except Exception:
                print(f"  Warning: invalid PredefinedType {ptype!r} on {type_class}")

        for pset_name, pset in psets.items():
            if not isinstance(pset, dict):
                continue
            props = self._values.single_values(pset)
            if props:
                ifc_pset = ifcopenshell.api.pset.add_pset(
                    self._ifc, product=type_obj, name=str(pset_name)
                )
                ifc_pset.HasProperties = props
        return type_obj
