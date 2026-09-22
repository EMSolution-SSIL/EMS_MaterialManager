"""Selection of the magnetic constitutive property used by analysis clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .errors import ModelValidationError, PropertyNotFoundError
from .model import CurveProperty, Material, ScalarProperty


BH_CURVE_PATH = "electromagnetic.BH_curve"
RELATIVE_PERMEABILITY_PATH = "electromagnetic.relative_permeability"
MagneticCharacteristicKind = Literal["bh_curve", "relative_permeability"]


@dataclass(frozen=True, slots=True)
class MagneticCharacteristic:
    """Resolved magnetic input and the rule that selected it."""

    kind: MagneticCharacteristicKind
    path: str
    value: CurveProperty | ScalarProperty


def resolve_magnetic_characteristic(material: Material) -> MagneticCharacteristic:
    """Return the B-H curve, or linear relative permeability when no curve exists.

    A present but invalid/wrongly typed B-H property is an error. It must never be
    silently replaced by the linear fallback because that could conceal bad data.
    """

    if material.has_property(BH_CURVE_PATH):
        value = material.get_property(BH_CURVE_PATH)
        if not isinstance(value, CurveProperty):
            raise ModelValidationError(
                f"{BH_CURVE_PATH} must be a curve for material {material.material_id!r}"
            )
        return MagneticCharacteristic("bh_curve", BH_CURVE_PATH, value)

    if material.has_property(RELATIVE_PERMEABILITY_PATH):
        value = material.get_property(RELATIVE_PERMEABILITY_PATH)
        if not isinstance(value, ScalarProperty):
            raise ModelValidationError(
                f"{RELATIVE_PERMEABILITY_PATH} must be a scalar for material "
                f"{material.material_id!r}"
            )
        return MagneticCharacteristic(
            "relative_permeability", RELATIVE_PERMEABILITY_PATH, value
        )

    raise PropertyNotFoundError(
        f"Material {material.material_id!r} defines neither {BH_CURVE_PATH!r} "
        f"nor {RELATIVE_PERMEABILITY_PATH!r}"
    )
