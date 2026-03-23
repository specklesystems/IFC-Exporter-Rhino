# =============================================================================
# mapper.py
# Maps Speckle objects → IFC entity classes.
#
# Reads the IFC class from _properties.Attributes.type
# Falls back to IfcBuildingElementProxy if not present.
# =============================================================================

from utils.properties import get_attributes


def classify(obj) -> str:
    """
    Determine the IFC class for a Speckle object.
    Reads from _properties.Attributes.type. Falls back to IfcBuildingElementProxy.
    """
    attrs = get_attributes(obj)
    ifc_type = attrs.get("type")
    if ifc_type and isinstance(ifc_type, str):
        return ifc_type.strip()
    return "IfcBuildingElementProxy"
