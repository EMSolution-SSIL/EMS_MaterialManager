"""Non-destructive data-contract audit for canonical materials."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from .material_types import DEFAULT_MATERIAL_TYPE_CATALOG, MaterialTypeCatalog
from .model import Material
from .property_catalog import (
    DEFAULT_PROPERTY_CATALOG,
    PropertyCatalog,
)


AuditSeverity = Literal["ERROR", "WARNING", "INFO"]


@dataclass(frozen=True, slots=True)
class MaterialAuditIssue:
    material_id: str
    severity: AuditSeverity
    code: str
    path: str
    message: str


def audit_material(
    material: Material,
    *,
    property_catalog: PropertyCatalog = DEFAULT_PROPERTY_CATALOG,
    material_types: MaterialTypeCatalog = DEFAULT_MATERIAL_TYPE_CATALOG,
) -> tuple[MaterialAuditIssue, ...]:
    """Return catalog and completeness findings without modifying *material*."""

    issues: list[MaterialAuditIssue] = []
    present: set[str] = set()
    for domain, properties in material.properties.items():
        for name, prop in properties.items():
            path = f"{domain}.{name}"
            definition = property_catalog.property_definition(path)
            if definition is None:
                continue
            present.add(definition.path.casefold())
            try:
                property_catalog.validate_property(path, prop)
            except Exception as error:
                issues.append(
                    MaterialAuditIssue(
                        material.material_id,
                        "ERROR",
                        "INVALID_CATALOG_VALUE",
                        path,
                        str(error),
                    )
                )
            family = material_types.resolve_family(material.identity.family)
            if not property_catalog.applies_to_family(definition, family):
                issues.append(
                    MaterialAuditIssue(
                        material.material_id,
                        "WARNING",
                        "FAMILY_MISMATCH",
                        path,
                        f"Property is intended for {', '.join(definition.applicable_families)}",
                    )
                )
            if definition.note_recommended and not prop.note:
                issues.append(
                    MaterialAuditIssue(
                        material.material_id,
                        "WARNING",
                        "NOTE_RECOMMENDED",
                        path,
                        definition.note_guidance,
                    )
                )

    thickness_path = "manufacturing.sheet_thickness"
    if (
        material_types.resolve_family(material.identity.family).casefold()
        == "electrical_steel"
        and thickness_path.casefold() not in present
    ):
        issues.append(
            MaterialAuditIssue(
                material.material_id,
                "INFO",
                "OPTIONAL_PROPERTY_MISSING",
                thickness_path,
                "Sheet thickness is optional but useful for EMSolution input.",
            )
        )

    for subcategory, mode, expected in (
        ("iron_loss_isotropy", "isotropy", 2),
        ("iron_loss_anisotropy", "anisotropy", 5),
    ):
        paths = {
            definition.path.casefold()
            for definition in property_catalog.definitions
            if definition.category == "magnetic"
            and definition.subcategory == subcategory
        }
        count = len(paths & present)
        if 0 < count < expected:
            issues.append(
                MaterialAuditIssue(
                    material.material_id,
                    "WARNING",
                    "INCOMPLETE_IRON_LOSS_SET",
                    f"electromagnetic.iron_loss.{mode}",
                    f"{mode} requires {expected} coefficients; {count} are set.",
                )
            )

    complex_sets = (
        (
            "complex relative permeability (isotropy)",
            (
                "electromagnetic.complex_relative_permeability_real",
                "electromagnetic.complex_relative_permeability_imaginary",
            ),
        ),
        (
            "complex relative permeability (anisotropy)",
            tuple(
                f"electromagnetic.complex_relative_permeability_{part}_{axis}"
                for part in ("real", "imaginary")
                for axis in ("x", "y", "z")
            ),
        ),
        (
            "complex relative permittivity (isotropy)",
            (
                "electrical.complex_relative_permittivity_real",
                "electrical.complex_relative_permittivity_imaginary",
            ),
        ),
        (
            "complex relative permittivity (anisotropy)",
            tuple(
                f"electrical.complex_relative_permittivity_{part}_{axis}"
                for part in ("real", "imaginary")
                for axis in ("x", "y", "z")
            ),
        ),
    )
    for label, paths in complex_sets:
        folded = {path.casefold() for path in paths}
        count = len(folded & present)
        if 0 < count < len(paths):
            issues.append(
                MaterialAuditIssue(
                    material.material_id,
                    "WARNING",
                    "INCOMPLETE_COMPLEX_PROPERTY_SET",
                    paths[0].rsplit("_", 1)[0],
                    f"{label} requires all {len(paths)} components; {count} are set.",
                )
            )

    anisotropic_paths = {
        f"electromagnetic.{name}_{axis}".casefold()
        for name in ("BH_curve", "relative_permeability")
        for axis in ("x", "y", "z")
    }
    if present & anisotropic_paths:
        isotropic_mu = "electromagnetic.relative_permeability" in present
        missing_axes = [
            axis.upper()
            for axis in ("x", "y", "z")
            if not isotropic_mu
            and f"electromagnetic.BH_curve_{axis}".casefold() not in present
            and f"electromagnetic.relative_permeability_{axis}".casefold()
            not in present
        ]
        if missing_axes:
            issues.append(
                MaterialAuditIssue(
                    material.material_id,
                    "WARNING",
                    "INCOMPLETE_ANISOTROPIC_MAGNETIC_SET",
                    "electromagnetic.BH_curve_xyz",
                    "Each direction requires a B-H curve or relative permeability; "
                    f"missing {', '.join(missing_axes)}.",
                )
            )

    family = material_types.resolve_family(material.identity.family)
    template = material_types.template_for(family)
    if template is not None:
        for item in template.properties:
            if item.requirement != "required" or item.path.casefold() in present:
                continue
            profile_text = (
                f" for {', '.join(item.profiles)}" if item.profiles else ""
            )
            issues.append(
                MaterialAuditIssue(
                    material.material_id,
                    "WARNING",
                    "REQUIRED_TEMPLATE_PROPERTY_MISSING",
                    item.path,
                    f"Required by the {family} template{profile_text}.",
                )
            )
    return tuple(issues)


def audit_materials(
    materials: Iterable[Material],
    *,
    property_catalog: PropertyCatalog = DEFAULT_PROPERTY_CATALOG,
    material_types: MaterialTypeCatalog = DEFAULT_MATERIAL_TYPE_CATALOG,
) -> tuple[MaterialAuditIssue, ...]:
    return tuple(
        issue
        for material in materials
        for issue in audit_material(
            material,
            property_catalog=property_catalog,
            material_types=material_types,
        )
    )
