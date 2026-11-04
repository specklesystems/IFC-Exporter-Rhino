"""Shared helpers used across the exporter modules."""

from specklepy.objects.models.units import get_scale_factor_from_string

# The IFC file is declared in millimetres; every length is scaled into it.
IFC_LENGTH_UNIT = "mm"


def mm_scale(units: str | None, fallback: float = 1.0) -> float:
    """Return the factor that converts a length in ``units`` to millimetres.

    Unknown, empty or unitless (``"none"``) strings return ``fallback``.
    """
    if not units or units.strip().lower() == "none":
        return fallback
    try:
        return get_scale_factor_from_string(units, IFC_LENGTH_UNIT)
    except Exception:
        return fallback
