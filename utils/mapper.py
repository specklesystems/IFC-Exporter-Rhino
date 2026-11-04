"""Map bundle object properties to an IFC entity class."""

import ifcopenshell
import ifcopenshell.ifcopenshell_wrapper as wrapper

PROXY = "IfcBuildingElementProxy"
SCHEMA = "IFC4X3"

_schema = wrapper.schema_by_name(ifcopenshell.file(schema=SCHEMA).schema_identifier)
_valid: dict[tuple[str, str], str | None] = {}


def resolve_class(name: str, root: str = "IfcProduct") -> str | None:
    """The schema's spelling of an instantiable subclass of ``root``, or None."""
    if (name, root) not in _valid:
        try:
            decl = _schema.declaration_by_name(name)
        except (RuntimeError, ValueError):
            decl = None
        resolved = None
        if decl is not None and hasattr(decl, "is_abstract") and not decl.is_abstract():
            cursor = decl
            while cursor is not None:
                if cursor.name() == root:
                    resolved = decl.name()
                    break
                cursor = cursor.supertype()
        _valid[(name, root)] = resolved
    return _valid[(name, root)]


def classify(props: dict, warned: set[str] | None = None) -> str:
    """The IFC class from ``Attributes.type``; IfcBuildingElementProxy if absent or
    not an instantiable IFC4X3 product (warned once per unknown name)."""
    attrs = props.get("Attributes")
    ifc_type = attrs.get("type") if isinstance(attrs, dict) else None
    if not isinstance(ifc_type, str) or not ifc_type.strip():
        return PROXY
    resolved = resolve_class(ifc_type.strip())
    if resolved is None:
        if warned is not None and ifc_type not in warned:
            warned.add(ifc_type)
            print(
                f"  Warning: {ifc_type!r} is not an IFC4X3 product class; using {PROXY}"
            )
        return PROXY
    return resolved
