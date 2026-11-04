"""Bundle placement transforms → IfcCartesianTransformationOperator3DnonUniform.

Instanced geometry is written once per definition as an IfcRepresentationMap and
referenced by an IfcMappedItem per placement (see geometry.GeometryConverter).
"""

import math


class TransformBuilder:
    """Creates transformation operators, reusing IfcDirection entities."""

    def __init__(self, ifc):
        self._ifc = ifc
        self._directions: dict[tuple[float, float, float], object] = {}

    def direction(self, dx: float, dy: float, dz: float):
        key = (round(dx, 6), round(dy, 6), round(dz, 6))
        if key not in self._directions:
            self._directions[key] = self._ifc.createIfcDirection(list(key))
        return self._directions[key]

    def operator(self, t, translation_scale: float, offset=(0.0, 0.0, 0.0)):
        """Convert a row-major 4x4 matrix into a transformation operator.

        t: 16 floats ``[r00,r01,r02,tx, r10,r11,r12,ty, r20,r21,r22,tz, 0,0,0,1]``.
        translation_scale: factor taking the translation to millimetres.
        offset: extra translation (mm) added after scaling.

        The operator's axes are the matrix COLUMNS (where local X/Y/Z land). Axis3
        is always explicit so mirrored and non-orthogonal placements keep their
        orientation. Returns None for a degenerate matrix.
        """
        axes = [
            (float(t[0]), float(t[4]), float(t[8])),
            (float(t[1]), float(t[5]), float(t[9])),
            (float(t[2]), float(t[6]), float(t[10])),
        ]
        scales = [math.sqrt(x * x + y * y + z * z) for x, y, z in axes]
        if min(scales) < 1e-10:
            return None
        d1, d2, d3 = (
            self.direction(x / s, y / s, z / s) for (x, y, z), s in zip(axes, scales)
        )
        origin = self._ifc.createIfcCartesianPoint(
            [
                round(float(t[3]) * translation_scale + offset[0], 3),
                round(float(t[7]) * translation_scale + offset[1], 3),
                round(float(t[11]) * translation_scale + offset[2], 3),
            ]
        )
        s1, s2, s3 = (round(s, 6) for s in scales)
        return self._ifc.createIfcCartesianTransformationOperator3DnonUniform(
            d1, d2, origin, s1, d3, s2, s3
        )
