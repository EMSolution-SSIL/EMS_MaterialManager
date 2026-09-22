"""End-to-end headless example for the EMS Material Manager PoC."""

from __future__ import annotations

from pathlib import Path
import tempfile

from ems_material import Axis, CurveProperty, MaterialManager, ScalarProperty
from ems_material.adapters import EMotorSolutionMaterialAdapter
from ems_material.gui.curve_io import load_curve_csv


HERE = Path(__file__).resolve().parent


def main() -> None:
    with tempfile.TemporaryDirectory() as root:
        library = MaterialManager(root)
        h_values, b_values = load_curve_csv(HERE / "bh_curve.csv")
        material = library.create(
            material_id="user:demo_steel",
            name="Demo Steel",
            family="electrical_steel",
            author="example",
            properties={
                "general": {"density": ScalarProperty(7.65, "g/cm^3")},
                "electromagnetic": {
                    "BH_curve": CurveProperty(
                        Axis("H", "A/m", h_values),
                        Axis("B", "T", b_values),
                    )
                },
            },
        )
        print(library.validate(material.material_id, "manufacturing_bom"))

        adapter = EMotorSolutionMaterialAdapter(
            library, name_to_id={"50A350": material.material_id}
        )
        density, diagnostics = adapter.density_and_diagnostics(
            "50A350", "stator.lamination"
        )
        print(f"density={density} kg/m^3, diagnostics={diagnostics}")

        destination = Path(root) / "exported.material.json"
        library.export_json(material.material_id, destination)
        print(destination.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
