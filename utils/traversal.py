# =============================================================================
# traversal.py
# Walks the nested Speckle Collection tree generically.
#
# Expected structure:
#   Root Collection
#   └── Collection
#       └── Collection
#           └── Object (leaf BIM element)
#
# Collections can nest to any depth. Every non-Collection leaf is yielded.
# =============================================================================

from typing import Generator
from specklepy.objects.base import Base


def is_collection(obj) -> bool:
    """Returns True if this object is a Speckle Collection node (not a leaf element)."""
    speckle_type = getattr(obj, "speckle_type", "") or ""
    return "Collection" in speckle_type


def get_children(obj) -> list:
    """
    Safely get the 'elements' list from a Base/Collection object.
    Handles 'elements', '@elements', and '_elements' variants.
    """
    for key in ["elements", "@elements", "_elements"]:
        try:
            val = obj[key]
            if val is not None:
                return list(val)
        except Exception:
            continue
    return []


def traverse(root: Base) -> Generator[Base, None, None]:
    """
    Walk the full Speckle object tree from the root Base object.
    Yields every non-Collection leaf object found at any depth.
    """
    yield from _walk(root)


def _walk(obj):
    """Recursively walk: descend into Collections, yield leaf objects."""
    if obj is None:
        return

    children = get_children(obj)

    if is_collection(obj):
        for child in children:
            yield from _walk(child)
    else:
        # Leaf object — yield it
        yield obj
        # Also check for nested children (e.g. curtain wall sub-elements)
        for child in children:
            if child is not None and not is_collection(child):
                yield from _walk(child)


# --------------------------------------------------------------------------- #
# Debug helper
# --------------------------------------------------------------------------- #

def print_tree(obj: Base, indent: int = 0, max_depth: int = 5):
    """Print the object tree structure for debugging."""
    if indent > max_depth:
        return

    prefix = "  " * indent
    name = getattr(obj, "name", None) or ""
    speckle_type = getattr(obj, "speckle_type", "") or ""
    children = get_children(obj)
    child_count = f"  ({len(children)} children)" if children else ""

    print(f"{prefix}├─ [{speckle_type}]  name={name!r}{child_count}")

    for child in children[:5]:
        print_tree(child, indent + 1, max_depth)

    if len(children) > 5:
        print(f"{prefix}   ... and {len(children) - 5} more")
