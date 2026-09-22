"""Small, explicit unit registry used by Canonical JSON v1.

The registry deliberately does not evaluate expressions. Product adapters may
resolve product-specific expressions before constructing canonical properties.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real

from .errors import UnitConversionError


@dataclass(frozen=True, slots=True)
class UnitSpec:
    dimension: str
    canonical: str
    scale_to_canonical: float = 1.0
    offset_to_canonical: float = 0.0


def _linear(dimension: str, canonical: str, **units: float) -> dict[str, UnitSpec]:
    result = {canonical: UnitSpec(dimension, canonical)}
    result.update(
        {
            name: UnitSpec(dimension, canonical, scale)
            for name, scale in units.items()
        }
    )
    return result


_UNIT_SPECS: dict[str, UnitSpec] = {
    "1": UnitSpec("dimensionless", "1"),
    **_linear(
        "density",
        "kg/m^3",
        **{
            "kg/m3": 1.0,
            "kg/dm^3": 1_000.0,
            "kg/dm3": 1_000.0,
            "kg/cm^3": 1_000_000.0,
            "kg/cm3": 1_000_000.0,
            "g/m^3": 0.001,
            "g/m3": 0.001,
            "g/cm^3": 1_000.0,
            "g/cm3": 1_000.0,
        },
    ),
    **_linear(
        "electrical_conductivity",
        "S/m",
        **{"S/cm": 100.0, "S/mm": 1_000.0, "S/um": 1_000_000.0},
    ),
    **_linear(
        "electrical_resistivity",
        "Ohm*m",
        **{"mOhm*m": 1e-3, "uOhm*m": 1e-6, "nOhm*m": 1e-9},
    ),
    **_linear(
        "electric_field_strength",
        "V/m",
        **{"kV/m": 1e3, "MV/m": 1e6, "kV/mm": 1e6},
    ),
    **_linear(
        "inverse_temperature",
        "1/K",
        **{"1/degC": 1.0},
    ),
    **_linear(
        "magnetic_field_strength",
        "A/m",
        **{"kA/m": 1e3, "MA/m": 1e6, "GA/m": 1e9},
    ),
    **_linear(
        "magnetic_flux_density",
        "T",
        **{"mT": 1e-3, "uT": 1e-6, "G": 1e-4},
    ),
    **_linear(
        "pressure",
        "Pa",
        **{"kPa": 1e3, "MPa": 1e6, "GPa": 1e9},
    ),
    **_linear(
        "length",
        "m",
        **{"dm": 1e-1, "cm": 1e-2, "mm": 1e-3, "um": 1e-6},
    ),
    **_linear(
        "frequency",
        "Hz",
        **{"mHz": 1e-3, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9},
    ),
    **_linear(
        "thermal_conductivity",
        "W/(m*K)",
        **{"W/m/K": 1.0},
    ),
    **_linear(
        "specific_heat",
        "J/(kg*K)",
        **{"kJ/(kg*K)": 1e3},
    ),
    **_linear(
        "eddy_current_loss_coefficient",
        "W/kg/T^2/Hz^2",
        **{
            "mW/kg/T^2/Hz^2": 1e-3,
            "uW/kg/T^2/Hz^2": 1e-6,
            "nW/kg/T^2/Hz^2": 1e-9,
        },
    ),
    **_linear(
        "hysteresis_loss_coefficient",
        "W/kg/T^2/Hz",
        **{
            "mW/kg/T^2/Hz": 1e-3,
            "uW/kg/T^2/Hz": 1e-6,
            "nW/kg/T^2/Hz": 1e-9,
        },
    ),
    "K": UnitSpec("temperature", "K"),
    "degC": UnitSpec("temperature", "K", 1.0, 273.15),
}

_ALIASES = {
    "Ω*m": "Ohm*m",
    "Ω·m": "Ohm*m",
    "µOhm*m": "uOhm*m",
    "µT": "uT",
    "μT": "uT",
    "µm": "um",
    "μm": "um",
}


def normalize_unit(unit: str) -> str:
    """Return the registered spelling for a unit alias."""

    if not isinstance(unit, str) or not unit.strip():
        raise UnitConversionError("Unit must be a non-empty string")
    normalized = _ALIASES.get(unit.strip(), unit.strip())
    if normalized not in _UNIT_SPECS:
        raise UnitConversionError(f"Unsupported unit: {unit!r}")
    return normalized


def canonical_unit(unit: str) -> str:
    """Return the canonical SI-oriented unit for *unit*."""

    return _UNIT_SPECS[normalize_unit(unit)].canonical


def unit_dimension(unit: str) -> str:
    """Return the physical dimension associated with *unit*."""

    return _UNIT_SPECS[normalize_unit(unit)].dimension


def convert_value(value: float, from_unit: str, to_unit: str) -> float:
    """Convert a finite real value between units of the same dimension."""

    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(float(value)):
        raise UnitConversionError("Only finite real values can be converted")
    source = _UNIT_SPECS[normalize_unit(from_unit)]
    target = _UNIT_SPECS[normalize_unit(to_unit)]
    if source.dimension != target.dimension:
        raise UnitConversionError(
            f"Cannot convert {from_unit!r} ({source.dimension}) to "
            f"{to_unit!r} ({target.dimension})"
        )
    canonical_value = float(value) * source.scale_to_canonical + source.offset_to_canonical
    return (canonical_value - target.offset_to_canonical) / target.scale_to_canonical


def supported_units() -> tuple[str, ...]:
    """Return all accepted unit spellings in deterministic order."""

    return tuple(sorted((*_UNIT_SPECS, *_ALIASES)))
