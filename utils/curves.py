"""Decoded SGEO curves → IfcIndexedPolyCurve.

Supported: Line, Arc, Circle, Polyline, Polycurve (of those) and NURBS Curve (via
its display polyline). Points are scaled to millimetres and de-duplicated on a
0.01 mm grid.
"""

import math

from utils.helpers import mm_scale

CURVE_TYPES = {"Line", "Arc", "Circle", "Polyline", "Polycurve", "Curve"}


def curve_kind(geometry) -> str | None:
    """Return the short type name of a decoded curve, or None if unsupported."""
    kind = type(geometry).__name__
    return kind if kind in CURVE_TYPES else None


class _PointList:
    def __init__(self):
        self.points: list[list[float]] = []
        self._index: dict[tuple[int, int, int], int] = {}

    def add(self, x: float, y: float, z: float) -> int:
        """Add a point (mm) and return its 1-based index."""
        key = (round(x * 100), round(y * 100), round(z * 100))
        idx = self._index.get(key)
        if idx is None:
            self.points.append([round(x, 3), round(y, 3), round(z, 3)])
            idx = len(self.points)
            self._index[key] = idx
        return idx


def _xyz(point, scale: float) -> tuple[float, float, float]:
    return (
        float(point.x) * scale,
        float(point.y) * scale,
        float(point.z) * scale,
    )


def _add_segments(curve, scale: float, pts: _PointList, segments: list) -> None:
    kind = curve_kind(curve)
    scale = mm_scale(getattr(curve, "units", None), scale)

    if kind == "Line":
        i = pts.add(*_xyz(curve.start, scale))
        j = pts.add(*_xyz(curve.end, scale))
        if i != j:
            segments.append(("line", [i, j]))

    elif kind == "Arc":
        i = pts.add(*_xyz(curve.startPoint, scale))
        m = pts.add(*_xyz(curve.midPoint, scale))
        j = pts.add(*_xyz(curve.endPoint, scale))
        if len({i, m, j}) == 3:
            segments.append(("arc", [i, m, j]))

    elif kind == "Circle":
        plane = curve.plane
        r = float(curve.radius)
        o, xd, yd = plane.origin, plane.xdir, plane.ydir

        def on_circle(angle: float) -> int:
            c, s = math.cos(angle) * r, math.sin(angle) * r
            return pts.add(
                (o.x + xd.x * c + yd.x * s) * scale,
                (o.y + xd.y * c + yd.y * s) * scale,
                (o.z + xd.z * c + yd.z * s) * scale,
            )

        p0, p1, p2, p3 = (on_circle(a * math.pi / 2) for a in range(4))
        if len({p0, p1, p2, p3}) == 4:
            segments.append(("arc", [p0, p1, p2]))
            segments.append(("arc", [p2, p3, p0]))

    elif kind == "Polyline":
        values = list(curve.value or [])
        indices = [
            pts.add(
                float(values[i]) * scale,
                float(values[i + 1]) * scale,
                float(values[i + 2]) * scale,
            )
            for i in range(0, len(values) - 2, 3)
        ]
        if getattr(curve, "closed", False) and len(indices) > 2:
            indices.append(indices[0])
        deduped = [
            idx for n, idx in enumerate(indices) if n == 0 or idx != indices[n - 1]
        ]
        if len(deduped) >= 2:
            segments.append(("line", deduped))

    elif kind == "Polycurve":
        for segment in curve.segments or []:
            if segment is not None:
                _add_segments(segment, scale, pts, segments)

    elif kind == "Curve":
        display = getattr(curve, "displayValue", None)
        if display is not None:
            _add_segments(display, scale, pts, segments)


def extract_curve(curve, scale: float) -> tuple[list, list]:
    """Return (points_mm, segments) for a decoded curve, or ([], [])."""
    pts = _PointList()
    segments: list = []
    _add_segments(curve, scale, pts, segments)
    if not segments:
        return [], []
    return pts.points, segments


def build_ifc_curve(ifc, points: list, segments: list):
    """Build an IfcIndexedPolyCurve from points and ("line"|"arc", indices) segments."""
    if not points or not segments:
        return None
    point_list = ifc.createIfcCartesianPointList3D(points)
    ifc_segments = [
        ifc.create_entity("IfcArcIndex", indices)
        if kind == "arc"
        else ifc.create_entity("IfcLineIndex", indices)
        for kind, indices in segments
    ]
    return ifc.createIfcIndexedPolyCurve(
        Points=point_list, Segments=ifc_segments, SelfIntersect=False
    )
