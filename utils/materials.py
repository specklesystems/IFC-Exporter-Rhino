"""Bundle MATERIAL / COLOR nodes → IfcSurfaceStyle, created on first use.

Styles are only created when assigned to geometry, so the file never carries
orphaned IfcSurfaceStyle instances (IFC105).
"""

import ifcopenshell
import ifcopenshell.api.style
from specklepy.bundle.model import ModelGeometry


def _argb_channels(argb: int) -> tuple[float, float, float, float]:
    """Unpack a (signed) packed ARGB int to normalised (A, R, G, B)."""
    unsigned = argb & 0xFFFFFFFF
    return (
        ((unsigned >> 24) & 0xFF) / 255.0,
        ((unsigned >> 16) & 0xFF) / 255.0,
        ((unsigned >> 8) & 0xFF) / 255.0,
        (unsigned & 0xFF) / 255.0,
    )


class MaterialManager:
    def __init__(self, ifc: ifcopenshell.file):
        self._ifc = ifc
        self._styles: dict[tuple[str, int], object] = {}
        self.applied = 0
        self.missed = 0

    def style_for(self, geometry: ModelGeometry):
        """Return the IfcSurfaceStyle for a geometry's resolved appearance, or None.

        The bundle's render material wins; a display colour is the fallback.
        """
        material = geometry.effective_material
        if material is not None:
            key = ("material", material.k)
            if key not in self._styles:
                fields = material.fields
                _, r, g, b = _argb_channels(fields.argb)
                transparency = max(0.0, min(1.0, 1.0 - float(fields.opacity)))
                self._styles[key] = self._create_style(
                    fields.name or material.name or "Material", (r, g, b), transparency
                )
            return self._styles[key]

        color = geometry.effective_color
        if color is not None:
            key = ("color", color.k)
            if key not in self._styles:
                a, r, g, b = _argb_channels(color.fields.argb)
                # A zero alpha byte means an RGB-only colour, not a fully clear one.
                transparency = 0.0 if a == 0 else 1.0 - a
                self._styles[key] = self._create_style(
                    f"Color #{color.fields.argb & 0xFFFFFF:06X}",
                    (r, g, b),
                    transparency,
                )
            return self._styles[key]
        return None

    def apply(self, item, style) -> None:
        """Assign a style to an IFC geometry item (no-op when style is None)."""
        if style is None:
            self.missed += 1
            return
        ifcopenshell.api.style.assign_item_style(self._ifc, item=item, style=style)
        self.applied += 1

    def _create_style(self, name: str, rgb: tuple[float, float, float], transparency):
        style = ifcopenshell.api.style.add_style(self._ifc, name=name)
        ifcopenshell.api.style.add_surface_style(
            self._ifc,
            style=style,
            ifc_class="IfcSurfaceStyleRendering",
            attributes={
                "SurfaceColour": {
                    "Name": None,
                    "Red": rgb[0],
                    "Green": rgb[1],
                    "Blue": rgb[2],
                },
                "Transparency": transparency,
                "ReflectanceMethod": "NOTDEFINED",
            },
        )
        return style

    @property
    def count(self) -> int:
        return len(self._styles)

    def print_stats(self) -> None:
        print(
            f"  Styles             : {self.count} "
            f"(applied {self.applied}, unstyled items {self.missed})"
        )
