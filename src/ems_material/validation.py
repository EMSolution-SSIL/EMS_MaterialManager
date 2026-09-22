"""Use-case requirement profiles for sparse canonical material records."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import PropertyNotFoundError, UnitConversionError
from .model import Material, ScalarProperty
from .units import unit_dimension


@dataclass(frozen=True, slots=True)
class MaterialValidationResult:
    valid: bool
    profile: str
    missing_required: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()


def validate_material(material: Material, profile: str) -> MaterialValidationResult:
    """Validate a material for a named use case without failing material load."""

    if profile != "manufacturing_bom":
        return MaterialValidationResult(
            valid=False,
            profile=profile,
            unsupported=(f"Unknown requirement profile: {profile}",),
        )

    path = "general.density"
    try:
        density = material.get_property(path)
    except PropertyNotFoundError:
        return MaterialValidationResult(
            valid=False,
            profile=profile,
            missing_required=(path,),
        )
    if not isinstance(density, ScalarProperty):
        return MaterialValidationResult(
            valid=False,
            profile=profile,
            unsupported=(f"{path} must be a scalar property",),
        )
    try:
        dimension = unit_dimension(density.unit)
    except UnitConversionError as error:
        return MaterialValidationResult(
            valid=False,
            profile=profile,
            unsupported=(str(error),),
        )
    if dimension != "density":
        return MaterialValidationResult(
            valid=False,
            profile=profile,
            unsupported=(f"{path} has incompatible unit {density.unit!r}",),
        )
    if density.value <= 0:
        return MaterialValidationResult(
            valid=False,
            profile=profile,
            warnings=(f"{path} must be positive",),
        )
    return MaterialValidationResult(valid=True, profile=profile)
