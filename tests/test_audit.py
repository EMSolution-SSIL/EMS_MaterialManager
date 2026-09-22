from __future__ import annotations

from datetime import datetime, timezone
import unittest

from ems_material import (
    Axis,
    CurveProperty,
    Material,
    MaterialIdentity,
    Provenance,
    ScalarProperty,
    VersionMetadata,
    audit_material,
)


def electrical_steel(properties: dict) -> Material:
    return Material(
        material_id="test:audit_steel",
        material_version="1.0.0",
        identity=MaterialIdentity("Audit steel", "electrical_steel"),
        properties=properties,
        provenance=Provenance("USER_INPUT"),
        version_metadata=VersionMetadata(
            "tester", datetime.now(timezone.utc).isoformat(), "audit test"
        ),
    )


class MaterialAuditTests(unittest.TestCase):
    def test_reports_optional_thickness_and_iron_loss_note(self) -> None:
        material = electrical_steel(
            {
                "electromagnetic": {
                    "iron_loss_ke": ScalarProperty(1.0e-4, "W/kg/T^2/Hz^2")
                }
            }
        )

        issues = audit_material(material)
        codes = {issue.code for issue in issues}

        self.assertIn("OPTIONAL_PROPERTY_MISSING", codes)
        self.assertIn("NOTE_RECOMMENDED", codes)
        self.assertIn("INCOMPLETE_IRON_LOSS_SET", codes)

    def test_complete_noted_isotropic_set_and_thickness_have_no_findings(self) -> None:
        note = "Representative B=1.5 T, 50 Hz"
        material = electrical_steel(
            {
                "manufacturing": {
                    "sheet_thickness": ScalarProperty(0.35, "mm")
                },
                "general": {"density": ScalarProperty(7650.0, "kg/m^3")},
                "electromagnetic": {
                    "BH_curve": CurveProperty(
                        Axis("H", "A/m", (0.0, 100.0)),
                        Axis("B", "T", (0.0, 1.0)),
                    ),
                    "iron_loss_ke": ScalarProperty(
                        1.0e-4, "W/kg/T^2/Hz^2", note=note
                    ),
                    "iron_loss_kh": ScalarProperty(
                        1.0e-2, "W/kg/T^2/Hz", note=note
                    ),
                },
            }
        )

        self.assertEqual(audit_material(material), ())

    def test_incomplete_complex_pair_is_reported(self) -> None:
        material = electrical_steel(
            {
                "electromagnetic": {
                    "complex_relative_permeability_real": ScalarProperty(
                        202.0, "1", note="1 kHz, 20 degC"
                    )
                }
            }
        )

        issues = audit_material(material)

        self.assertIn(
            "INCOMPLETE_COMPLEX_PROPERTY_SET",
            {issue.code for issue in issues},
        )

    def test_partial_directional_bh_requires_curve_or_mu_for_every_axis(self) -> None:
        material = electrical_steel(
            {
                "electromagnetic": {
                    "BH_curve_x": CurveProperty(
                        Axis("H", "A/m", (0.0, 100.0)),
                        Axis("B", "T", (0.0, 1.0)),
                    )
                }
            }
        )

        issues = audit_material(material)

        matching = [
            issue
            for issue in issues
            if issue.code == "INCOMPLETE_ANISOTROPIC_MAGNETIC_SET"
        ]
        self.assertEqual(len(matching), 1)
        self.assertIn("Y, Z", matching[0].message)


if __name__ == "__main__":
    unittest.main()
