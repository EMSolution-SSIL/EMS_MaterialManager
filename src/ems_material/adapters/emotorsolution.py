"""Read-only bridge from eMotorSolution assignments to canonical materials."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..errors import MaterialNotFoundError, PropertyNotFoundError, UnitConversionError
from ..manager import MaterialManager
from ..model import ScalarProperty


@dataclass(frozen=True, slots=True)
class AdapterDiagnostic:
    code: str
    message: str
    severity: str
    source_path: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "source_path": self.source_path,
        }


@dataclass(frozen=True, slots=True)
class DensityResolution:
    assignment: str
    material_id: str | None
    density_kg_m3: float | None
    source: str | None
    diagnostics: tuple[AdapterDiagnostic, ...] = ()


class EMotorSolutionMaterialAdapter:
    """Resolve legacy name assignments or canonical IDs for BOM use.

    Explicit mappings win. A canonical ID or unique exact material name is then
    resolved from the library. The legacy callback is used only when no library
    material was configured, preserving old projects without silently masking a
    missing density in an explicitly mapped canonical material.
    """

    def __init__(
        self,
        library: MaterialManager,
        *,
        name_to_id: Mapping[str, str] | None = None,
        legacy_density_provider: Callable[[str], float | None] | None = None,
    ) -> None:
        self.library = library
        self.name_to_id = dict(name_to_id or {})
        self.legacy_density_provider = legacy_density_provider

    def _resolve_id(self, assignment: str) -> str | None:
        if assignment in self.name_to_id:
            return self.name_to_id[assignment]
        if ":" in assignment:
            try:
                return self.library.get(assignment).material_id
            except MaterialNotFoundError:
                return None
        exact = tuple(
            material for material in self.library.list() if material.name == assignment
        )
        return exact[0].material_id if len(exact) == 1 else None

    def density_for_assignment(
        self,
        assignment: str | None,
        *,
        source_path: str = "",
    ) -> DensityResolution:
        assignment_text = assignment or ""
        material_id = self._resolve_id(assignment_text)
        if material_id is None:
            if self.legacy_density_provider is not None:
                density = self.legacy_density_provider(assignment_text)
                if density is not None:
                    return DensityResolution(
                        assignment=assignment_text,
                        material_id=None,
                        density_kg_m3=float(density),
                        source="legacy",
                    )
            return DensityResolution(
                assignment=assignment_text,
                material_id=None,
                density_kg_m3=None,
                source=None,
                diagnostics=(
                    AdapterDiagnostic(
                        "material_not_found",
                        f"Material assignment {assignment!r} was not resolved",
                        "error",
                        source_path,
                    ),
                ),
            )
        material = self.library.get(material_id)
        try:
            density = material.get_property("general.density")
        except PropertyNotFoundError:
            return DensityResolution(
                assignment_text,
                material_id,
                None,
                "library",
                (
                    AdapterDiagnostic(
                        "density_unavailable",
                        f"Manufacturing density is not set for {material_id!r}",
                        "warning",
                        source_path,
                    ),
                ),
            )
        if not isinstance(density, ScalarProperty):
            return self._invalid_density(assignment_text, material_id, source_path)
        try:
            value = density.to_unit("kg/m^3")
        except UnitConversionError:
            return self._invalid_density(assignment_text, material_id, source_path)
        if value <= 0:
            return self._invalid_density(assignment_text, material_id, source_path)
        return DensityResolution(assignment_text, material_id, value, "library")

    def density_and_diagnostics(
        self,
        assignment: str | None,
        source_path: str = "",
        *,
        diagnostic_factory: Callable[..., Any] = AdapterDiagnostic,
    ) -> tuple[float | None, tuple[Any, ...]]:
        """Return the tuple shape consumed by eMotorSolution BOM providers.

        ``diagnostic_factory`` lets the product supply its existing
        ``BOMDiagnostic`` type without importing eMotorSolution into the common
        package. The callable receives code, message, severity and source path.
        """

        resolution = self.density_for_assignment(
            assignment, source_path=source_path
        )
        diagnostics = tuple(
            diagnostic_factory(
                diagnostic.code,
                diagnostic.message,
                diagnostic.severity,
                diagnostic.source_path,
            )
            for diagnostic in resolution.diagnostics
        )
        return resolution.density_kg_m3, diagnostics

    @staticmethod
    def _invalid_density(
        assignment: str,
        material_id: str,
        source_path: str,
    ) -> DensityResolution:
        return DensityResolution(
            assignment,
            material_id,
            None,
            "library",
            (
                AdapterDiagnostic(
                    "density_invalid",
                    f"Manufacturing density is invalid for {material_id!r}",
                    "warning",
                    source_path,
                ),
            ),
        )
