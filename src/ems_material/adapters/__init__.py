"""Product adapters supplied by the EMS Material Manager."""

from .emotorsolution import AdapterDiagnostic, DensityResolution, EMotorSolutionMaterialAdapter
from .emotorsolution_project import EMotorSolutionProjectAdapter
from .emsolution import EMSolutionInputAdapter

__all__ = [
    "AdapterDiagnostic",
    "DensityResolution",
    "EMotorSolutionMaterialAdapter",
    "EMotorSolutionProjectAdapter",
    "EMSolutionInputAdapter",
]
