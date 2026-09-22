"""Public exception types for the EMS Material Manager."""

from __future__ import annotations

from collections.abc import Sequence


class MaterialManagerError(Exception):
    """Base class for errors raised by the material manager."""


class MaterialParseError(MaterialManagerError):
    """Raised when a material document is not valid JSON."""


class SchemaValidationError(MaterialManagerError):
    """Raised when a material document does not satisfy Canonical JSON v1."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = tuple(issues)
        super().__init__("Material schema validation failed: " + "; ".join(self.issues))


class ModelValidationError(MaterialManagerError):
    """Raised when values are structurally valid but semantically invalid."""


class PropertyNotFoundError(MaterialManagerError, KeyError):
    """Raised when a material does not define the requested property path."""


class UnitConversionError(MaterialManagerError, ValueError):
    """Raised for unknown units or conversions between different dimensions."""


class LegacyImportError(MaterialManagerError, ValueError):
    """Raised when a legacy record cannot be translated without guessing."""


class OpenDataImportError(MaterialManagerError, ValueError):
    """Raised when an open-data manifest or import recipe is not reproducible."""


class MaterialNotFoundError(MaterialManagerError, KeyError):
    """Raised when a repository does not contain a material ID."""


class MaterialAlreadyExistsError(MaterialManagerError):
    """Raised when create would overwrite an existing material ID."""


class MaterialConflictError(MaterialManagerError):
    """Raised when an optimistic version check detects a stale update."""


class ReadOnlyMaterialError(MaterialManagerError):
    """Raised when attempting to mutate a non-user material."""


class RepositoryCorruptionError(MaterialManagerError):
    """Raised when stored identity and file identity disagree."""


class GuiDependencyError(MaterialManagerError, RuntimeError):
    """Raised when optional GUI dependencies are unavailable."""


class ManagerConfigurationError(MaterialManagerError, ValueError):
    """Raised when a library or source configuration is invalid."""
