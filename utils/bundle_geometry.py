"""Resolve the renderable geometry of a bundle object.

Direct geometry comes from the object's DISPLAY edges (SOLID only when there is no
display geometry), instanced geometry from its DISPLAY_INSTANCE placements, with
nested definitions walked and their transforms composed. Only SGEO blobs are kept:
raw host solids (e.g. Rhino 3dm breps) cannot be read here.
"""

from dataclasses import dataclass, field

from specklepy.bundle.model import (
    GeometryRole,
    Model,
    ModelGeometry,
    ModelObject,
    parse_transform,
)

IDENTITY = (
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
)
NESTING_GUARD = 32


@dataclass
class Placement:
    """One placed definition: its geometries share one composed world transform."""

    instance_k: int
    definition_k: int
    transform: tuple[float, ...]
    units: str | None
    geometries: list[ModelGeometry]


@dataclass
class ObjectGeometry:
    direct: list[ModelGeometry] = field(default_factory=list)
    placements: list[Placement] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.direct or self.placements)


def resolve(model: Model, obj: ModelObject) -> ObjectGeometry:
    """Collect an object's direct and instanced SGEO geometry."""
    # ModelObject.geometries scans every DISPLAY_INSTANCE edge per object, which is
    # quadratic on block-heavy models; the relation index is walked here instead.
    rels = model.bundle.relations
    result = ObjectGeometry()

    has_direct = bool(rels.display_by_object(obj.k)) or obj.k in rels.solid_by_object
    instance_ks = model.index.instances_by_object.get(obj.k, [])
    if not has_direct and not instance_ks:
        return result

    geometries = model.geometries
    for edge in rels.display_by_object(obj.k):
        g = geometries.get(edge.dst)
        if g is not None and g.is_sgeo:
            result.direct.append(
                ModelGeometry(model, obj, edge.dst, g, GeometryRole.DISPLAY, edge.ord)
            )
    if not result.direct:
        for i, solid_k in enumerate(rels.solid_by_object.get(obj.k, [])):
            g = geometries.get(solid_k)
            if g is not None and g.is_sgeo:
                result.direct.append(
                    ModelGeometry(model, obj, solid_k, g, GeometryRole.SOLID, i)
                )

    for instance_k in instance_ks:
        top = model.bundle.nodes.get(instance_k)
        units = top.units if top is not None else None
        _walk(model, obj, instance_k, None, units, 0, result.placements)
    return result


def _walk(
    model: Model,
    obj: ModelObject,
    instance_k: int,
    parent: tuple[float, ...] | None,
    units: str | None,
    depth: int,
    into: list[Placement],
) -> None:
    node = model.bundle.nodes.get(instance_k)
    if depth > NESTING_GUARD or node is None or node.def_ref is None:
        return
    transform = _compose(parent, parse_transform(node.transform))
    definition_k = node.def_ref
    rels = model.bundle.relations
    geometry_ks = rels.defines_by_definition.get(definition_k, [])
    ords = rels.defines_ord_by_definition.get(definition_k) or [0] * len(geometry_ks)

    geometries = []
    for geometry_k, ord in zip(geometry_ks, ords):
        g = model.geometries.get(geometry_k)
        if g is not None and g.is_sgeo:
            geometries.append(
                ModelGeometry(
                    model,
                    obj,
                    geometry_k,
                    g,
                    GeometryRole.DISPLAY,
                    ord,
                    list(transform),
                    instance_k,
                )
            )
    if geometries:
        into.append(Placement(instance_k, definition_k, transform, units, geometries))

    for nested_k in rels.defines_instance_by_definition.get(definition_k, []):
        _walk(model, obj, nested_k, transform, units, depth + 1, into)


def _compose(
    parent: tuple[float, ...] | None, child: list[float] | None
) -> tuple[float, ...]:
    if child is None:
        return parent or IDENTITY
    if parent is None:
        return tuple(child)
    return tuple(
        sum(parent[row * 4 + i] * child[i * 4 + col] for i in range(4))
        for row in range(4)
        for col in range(4)
    )
