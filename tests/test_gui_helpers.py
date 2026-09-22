from __future__ import annotations

import unittest

from ems_material import ModelValidationError
from ems_material.gui.curve_io import parse_curve_csv
from ems_material.gui.app import build_parser


class CurveCsvTests(unittest.TestCase):
    def test_parses_header_bom_comments_and_two_columns(self) -> None:
        x_values, y_values = parse_curve_csv(
            "\ufeffH [A/m],B [T],note\n# measured\n0,0,origin\n100,0.5,p1\n"
        )
        self.assertEqual(x_values, (0.0, 100.0))
        self.assertEqual(y_values, (0.0, 0.5))

    def test_rejects_non_numeric_row_after_data(self) -> None:
        with self.assertRaisesRegex(ModelValidationError, "row 2"):
            parse_curve_csv("0,0\nbad,1\n")

    def test_rejects_single_point(self) -> None:
        with self.assertRaisesRegex(ModelValidationError, "at least two"):
            parse_curve_csv("0,0\n")


class AppParserTests(unittest.TestCase):
    def test_admin_reference_edit_flag_is_explicit_and_off_by_default(self) -> None:
        parser = build_parser()

        self.assertFalse(parser.parse_args([]).admin_edit_reference)
        self.assertTrue(
            parser.parse_args(["--admin-edit-reference"]).admin_edit_reference
        )


if __name__ == "__main__":
    unittest.main()
