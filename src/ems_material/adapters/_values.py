"""Shared canonical value helpers for product adapters."""

from __future__ import annotations

from collections.abc import Iterable

from ..errors import PropertyNotFoundError
from ..model import CurveProperty, Material, ScalarProperty


def scalar_value(material: Material, path: str, unit: str) -> float | None:
    try:
        value = material.get_property(path)
    except PropertyNotFoundError:
        return None
    if not isinstance(value, ScalarProperty):
        raise TypeError(f"{path} must be a scalar property")
    return value.to_unit(unit)


def curve_points(
    material: Material,
    path: str,
    *,
    x_unit: str = "A/m",
    y_unit: str = "T",
) -> list[list[float]] | None:
    try:
        value = material.get_property(path)
    except PropertyNotFoundError:
        return None
    if not isinstance(value, CurveProperty):
        raise TypeError(f"{path} must be a curve property")
    return [[x, y] for x, y in zip(value.x.to_unit(x_unit), value.y.to_unit(y_unit))]


def require_values(values: Iterable[tuple[str, float | None]]) -> dict[str, float]:
    result: dict[str, float] = {}
    missing: list[str] = []
    for name, value in values:
        if value is None:
            missing.append(name)
        else:
            result[name] = value
    if missing:
        raise ValueError(f"Required properties are not set: {', '.join(missing)}")
    return result
