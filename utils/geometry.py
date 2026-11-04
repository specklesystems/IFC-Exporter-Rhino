"""Bundle geometry → IFC shape representations.

- Direct meshes → IfcPolygonalFaceSet (one per mesh, so each carries its own
  style), placed at the bounding-box centre / minimum Z of the object.
- Placed definitions → one IfcRepresentationMap per (definition, styling), reused by
  an IfcMappedItem per placement.
- Curves are only used when an object (or definition) has no surface geometry.

All coordinates are written in millimetres.
"""

from collections.abc import Sequence

import ifcopenshell
from specklepy.bundle import sgeo
from specklepy.bundle.model import Model, ModelGeometry

from utils.bundle_geometry import ObjectGeometry, Placement
from utils.curves import build_ifc_curve, curve_kind, extract_curve
from utils.helpers import mm_scale
from utils.instances import TransformBuilder
from utils.materials import MaterialManager

# Vertices closer than this (mm) are merged; faces collapsing onto a merged vertex
# are dropped (GEM111).
VERTEX_MERGE_TOL = 0.01
_INV_TOL = 1.0 / VERTEX_MERGE_TOL


def decode_faces(faces: Sequence[int]) -> list[list[int]]:
    """Decode Speckle's ``[n, i0, ..., n, i0, ...]`` face list into index groups.

    n=0 → triangle and n=1 → quad (legacy encodings); n≥3 → n-gon.
    """
    decoded = []
    i, total = 0, len(faces)
    while i < total:
        n = int(faces[i])
        if n == 0:
            n = 3
        elif n == 1:
            n = 4
        end = i + 1 + n
        if end > total:
            break
        decoded.append([int(v) for v in faces[i + 1 : end]])
        i = end
    return decoded


def build_faceset(ifc, verts: Sequence[float], face_groups: list[list[int]]):
    """Build one IfcPolygonalFaceSet from flat mm vertices and face index groups.

    Vertices are de-duplicated on the merge grid; degenerate faces are skipped.
    Returns None when nothing valid remains.
    """
    snap_to_idx: dict[tuple[int, int, int], int] = {}
    points: list[list[float]] = []
    faces: list[list[int]] = []
    n_verts = len(verts) // 3

    for indices in face_groups:
        remapped, seen, ok = [], set(), True
        for i in indices:
            if i < 0 or i >= n_verts:
                ok = False
                break
            x, y, z = verts[i * 3], verts[i * 3 + 1], verts[i * 3 + 2]
            key = (round(x * _INV_TOL), round(y * _INV_TOL), round(z * _INV_TOL))
            if key in seen:
                ok = False
                break
            seen.add(key)
            idx = snap_to_idx.get(key)
            if idx is None:
                idx = len(points)
                snap_to_idx[key] = idx
                points.append([round(x, 3), round(y, 3), round(z, 3)])
            remapped.append(idx + 1)
        if ok and len(remapped) >= 3:
            faces.append(remapped)

    if not faces:
        return None
    point_list = ifc.createIfcCartesianPointList3D(points)
    ifc_faces = [ifc.createIfcIndexedPolygonalFace(f) for f in faces]
    return ifc.createIfcPolygonalFaceSet(point_list, None, ifc_faces, None)


def _bounds_origin(point_sets) -> tuple[float, float, float] | None:
    """X/Y bounding-box centre and minimum Z over flat [x, y, z, ...] lists."""
    xmin = ymin = zmin = float("inf")
    xmax = ymax = float("-inf")
    found = False
    for flat in point_sets:
        for i in range(0, len(flat) - 2, 3):
            x, y, z = flat[i], flat[i + 1], flat[i + 2]
            xmin, xmax = min(xmin, x), max(xmax, x)
            ymin, ymax = min(ymin, y), max(ymax, y)
            zmin = min(zmin, z)
            found = True
    if not found:
        return None
    return (xmin + xmax) / 2.0, (ymin + ymax) / 2.0, zmin


class GeometryConverter:
    """Converts one bundle Model's geometry into one IFC file, caching shared work."""

    def __init__(
        self,
        ifc: ifcopenshell.file,
        body_context,
        model: Model,
        materials: MaterialManager,
    ):
        self._ifc = ifc
        self._ctx = body_context
        self._model_scale = mm_scale(model.units)
        self._materials = materials
        self._transforms = TransformBuilder(ifc)
        self._decoded: dict[int, tuple[str, object] | None] = {}
        self._rep_maps: dict[tuple, object] = {}
        self._origin = ifc.createIfcCartesianPoint([0.0, 0.0, 0.0])
        self._z = ifc.createIfcDirection([0.0, 0.0, 1.0])
        self._x = ifc.createIfcDirection([1.0, 0.0, 0.0])
        self._world = None
        self.rep_maps_created = 0
        self.mapped_items = 0

    # ── public ───────────────────────────────────────────────────────────────

    def representation(self, source: ObjectGeometry):
        """Return (IfcShapeRepresentation, IfcLocalPlacement) or (None, None)."""
        surfaces = [
            (g, d) for g in source.direct if (d := self._decode(g))[0] == "mesh"
        ]
        mapped = [
            item
            for p in source.placements
            if (item := self._mapped_item(p)) is not None
        ]

        if surfaces and not mapped:
            origin = _bounds_origin(d[1][0] for _, d in surfaces)
            items = self._mesh_items(surfaces, origin)
            if items:
                return self._shape("Tessellation", items), self._placement(origin)

        if mapped or surfaces:
            if surfaces:
                origin = _bounds_origin(d[1][0] for _, d in surfaces)
                items = self._mesh_items(surfaces, origin)
                if items:
                    rep_map = self._new_rep_map("Tessellation", items)
                    op = self._transforms.operator(
                        (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1), 1.0, origin
                    )
                    mapped.append(self._ifc.createIfcMappedItem(rep_map, op))
            if mapped:
                self.mapped_items += len(mapped)
                return self._shape(
                    "MappedRepresentation", mapped
                ), self._world_placement()

        curves = [(g, d) for g in source.direct if (d := self._decode(g))[0] == "curve"]
        if curves:
            extracted = [
                (g, pts, segs)
                for g, d in curves
                for pts, segs in [extract_curve(d[1], self._model_scale)]
                if pts
            ]
            origin = _bounds_origin(
                [c for p in pts for c in p] for _, pts, _ in extracted
            )
            if origin is not None:
                items = []
                for g, pts, segs in extracted:
                    offset = [
                        [x - origin[0], y - origin[1], z - origin[2]] for x, y, z in pts
                    ]
                    curve = build_ifc_curve(self._ifc, offset, segs)
                    if curve is not None:
                        self._materials.apply(curve, self._materials.style_for(g))
                        items.append(curve)
                if items:
                    return self._shape("Curve3D", items), self._placement(origin)

        return None, None

    # ── decoding ─────────────────────────────────────────────────────────────

    def _decode(
        self, geometry: ModelGeometry
    ) -> tuple[str, object] | tuple[None, None]:
        """Decode once per geometry: ("mesh", (verts_mm, faces)) or ("curve", Base)."""
        if geometry.k in self._decoded:
            return self._decoded[geometry.k] or (None, None)
        result = None
        try:
            header = sgeo.decode_header(geometry.content)
            if header.primitive is sgeo.PrimitiveType.MESH:
                mesh = geometry.decode_mesh()
                scale = mm_scale(mesh.units, self._model_scale)
                verts = [v * scale for v in mesh.vertices]
                faces = decode_faces(mesh.faces)
                if verts and faces:
                    result = ("mesh", (verts, faces))
            else:
                decoded = geometry.decode()
                if curve_kind(decoded):
                    result = ("curve", decoded)
        except sgeo.SgeoDecodeError as e:
            print(f"  Warning: geometry {geometry.k} could not be decoded: {e}")
        self._decoded[geometry.k] = result
        return result or (None, None)

    # ── builders ─────────────────────────────────────────────────────────────

    def _mesh_items(self, surfaces, origin) -> list:
        ox, oy, oz = origin or (0.0, 0.0, 0.0)
        items = []
        for g, (_, (verts, faces)) in surfaces:
            if ox or oy or oz:
                local = [0.0] * len(verts)
                for i in range(0, len(verts) - 2, 3):
                    local[i] = verts[i] - ox
                    local[i + 1] = verts[i + 1] - oy
                    local[i + 2] = verts[i + 2] - oz
            else:
                local = verts
            faceset = build_faceset(self._ifc, local, faces)
            if faceset is not None:
                self._materials.apply(faceset, self._materials.style_for(g))
                items.append(faceset)
        return items

    def _mapped_item(self, placement: Placement):
        styles = tuple(
            id(s) if (s := self._materials.style_for(g)) is not None else None
            for g in placement.geometries
        )
        key = (placement.definition_k, styles)
        if key not in self._rep_maps:
            self._rep_maps[key] = self._definition_rep_map(placement)
        rep_map = self._rep_maps[key]
        if rep_map is None:
            return None
        op = self._transforms.operator(
            placement.transform, mm_scale(placement.units, self._model_scale)
        )
        if op is None:
            return None
        return self._ifc.createIfcMappedItem(rep_map, op)

    def _definition_rep_map(self, placement: Placement):
        decoded = [(g, self._decode(g)) for g in placement.geometries]
        surfaces = [(g, d) for g, d in decoded if d[0] == "mesh"]
        if surfaces:
            items = self._mesh_items(surfaces, None)
            return self._new_rep_map("Tessellation", items) if items else None

        items = []
        for g, d in decoded:
            if d[0] != "curve":
                continue
            pts, segs = extract_curve(d[1], self._model_scale)
            curve = build_ifc_curve(self._ifc, pts, segs)
            if curve is not None:
                self._materials.apply(curve, self._materials.style_for(g))
                items.append(curve)
        return self._new_rep_map("Curve3D", items) if items else None

    def _new_rep_map(self, rep_type: str, items: list):
        mapping_origin = self._ifc.createIfcAxis2Placement3D(self._origin, None, None)
        self.rep_maps_created += 1
        return self._ifc.createIfcRepresentationMap(
            mapping_origin, self._shape(rep_type, items)
        )

    def _shape(self, rep_type: str, items: list):
        return self._ifc.createIfcShapeRepresentation(
            ContextOfItems=self._ctx,
            RepresentationIdentifier="Body",
            RepresentationType=rep_type,
            Items=items,
        )

    def _placement(self, origin):
        x, y, z = origin or (0.0, 0.0, 0.0)
        point = self._ifc.createIfcCartesianPoint(
            [round(x, 3), round(y, 3), round(z, 3)]
        )
        a2p = self._ifc.createIfcAxis2Placement3D(point, self._z, self._x)
        return self._ifc.createIfcLocalPlacement(
            PlacementRelTo=None, RelativePlacement=a2p
        )

    def _world_placement(self):
        """Shared identity placement for elements placed by their MappedItems."""
        if self._world is None:
            a2p = self._ifc.createIfcAxis2Placement3D(self._origin, None, None)
            self._world = self._ifc.createIfcLocalPlacement(
                PlacementRelTo=None, RelativePlacement=a2p
            )
        return self._world
