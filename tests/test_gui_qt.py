from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import QApplication, QAbstractItemView, QDialog
except ImportError:  # pragma: no cover - optional dependency in core-only CI
    QApplication = None  # type: ignore[assignment]

from ems_material import Axis, CurveProperty, MaterialManager, ScalarProperty


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(QApplication is None, "Qt GUI dependencies are not installed")
class MaterialManagerQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.library = MaterialManager(Path(self.temp_dir.name))
        self.material = self.library.create(
            name="GUI steel",
            family="electrical_steel",
            author="tester",
            material_id="user:gui_steel",
            properties={
                "general": {
                    "density": ScalarProperty(
                        7.65, "g/cm^3", note="Nominal value at room temperature"
                    )
                },
                "electromagnetic": {
                    "bh_curve": CurveProperty(
                        Axis("H", "A/m", (0.0, 100.0, 200.0)),
                        Axis("B", "T", (0.0, 0.8, 1.1)),
                        note="Reference B-H curve",
                    )
                },
            },
        )

    @staticmethod
    def property_rows(window) -> dict[str, tuple[str, str, str, str, str]]:
        rows: dict[str, tuple[str, str, str, str, str]] = {}
        pending = [
            window.property_tree.topLevelItem(index)
            for index in range(window.property_tree.topLevelItemCount())
        ]
        while pending:
            item = pending.pop()
            pending.extend(item.child(index) for index in range(item.childCount()))
            if item.data(0, Qt.ItemDataRole.UserRole + 1) == "property":
                path = item.data(0, Qt.ItemDataRole.UserRole)
                rows[path] = tuple(item.text(column) for column in range(1, 6))
        return rows

    @staticmethod
    def property_item(window, path: str):
        pending = [
            window.property_tree.topLevelItem(index)
            for index in range(window.property_tree.topLevelItemCount())
        ]
        while pending:
            item = pending.pop()
            if item.data(0, Qt.ItemDataRole.UserRole) == path:
                return item
            pending.extend(item.child(index) for index in range(item.childCount()))
        raise AssertionError(f"Property row not found: {path}")

    def test_window_displays_and_saves_scalar_curve_and_metadata(self) -> None:
        from ems_material.gui.qt import MaterialManagerWindow

        window = MaterialManagerWindow(self.library)
        self.addCleanup(window.close)
        self.assertEqual(len(window._material_items), 1)
        rows = self.property_rows(window)
        self.assertEqual(sum(row[3] == "Set" for row in rows.values()), 2)
        self.assertEqual(
            rows["general.density"],
            (
                "scalar",
                "7.65",
                "g/cm^3",
                "Set",
                "Nominal value at room temperature",
            ),
        )
        self.assertEqual(
            rows["electromagnetic.electrical_conductivity"][3],
            "Recommended — not set",
        )
        self.assertIn("READY", window.validation_label.text())
        self.assertFalse(window.save_button.isEnabled())
        self.assertEqual(window.edit_material_button.text(), "Edit Material")
        window._toggle_edit_mode()
        self.assertTrue(window.save_button.isEnabled())
        window.name_edit.setText("GUI steel revised")
        window.material_version_edit.setText("1.0.1")
        window.change_note_edit.setText("GUI smoke test")
        window._save_material()
        reloaded = self.library.get("user:gui_steel")
        self.assertEqual(reloaded.name, "GUI steel revised")
        self.assertEqual(reloaded.material_version, "1.0.1")
        self.assertEqual(
            reloaded.get_property("electromagnetic.bh_curve").x.unit, "A/m"
        )

    def test_curve_dialog_keeps_axis_names_units_and_points(self) -> None:
        from ems_material.gui.qt import CurveEditorDialog

        original = self.material.get_property("electromagnetic.bh_curve")
        curve = CurveProperty(
            original.x,
            original.y,
            {"x_scale": "log"},
            note="Representative curve",
        )
        dialog = CurveEditorDialog(path="electromagnetic.bh_curve", prop=curve)
        self.addCleanup(dialog.close)
        path, result = dialog.result_value()
        self.assertEqual(path, "electromagnetic.bh_curve")
        self.assertEqual(result.x.name, "H")
        self.assertEqual(result.x.unit, "A/m")
        self.assertEqual(result.y.name, "B")
        self.assertEqual(result.y.unit, "T")
        self.assertEqual(result.x.values, (0.0, 100.0, 200.0))
        self.assertEqual(result.display, {"x_scale": "log", "y_scale": "linear"})
        self.assertEqual(result.note, "Representative curve")
        self.assertEqual(dialog.axes.get_xscale(), "log")

    def test_reference_curve_dialog_is_viewable_but_read_only(self) -> None:
        from ems_material.gui.qt import CurveEditorDialog

        curve = self.material.get_property("electromagnetic.bh_curve")
        dialog = CurveEditorDialog(
            path="electromagnetic.bh_curve", prop=curve, read_only=True
        )
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.windowTitle(), "View 1D Curve")
        self.assertEqual(
            dialog.table.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.assertIsNotNone(dialog.canvas)
        self.assertEqual(len(dialog.axes.lines[0].get_xdata()), 3)

    def test_scalar_dialog_builds_density_with_unit(self) -> None:
        from ems_material.gui.qt import ScalarEditorDialog

        dialog = ScalarEditorDialog()
        self.addCleanup(dialog.close)
        dialog.path_edit.setText("general.density")
        dialog.value_edit.setText("7.8")
        dialog.unit_edit.setText("g/cm^3")
        dialog.note_edit.setPlainText("Representative density")
        path, result = dialog.result_value()
        self.assertEqual(path, "general.density")
        self.assertEqual(result.to_unit("kg/m^3"), 7800.0)
        self.assertEqual(result.note, "Representative density")

    def test_window_displays_migrated_synthetic_steel_curve(self) -> None:
        from ems_material.gui.qt import MaterialManagerWindow

        result = self.library.import_legacy_json(
            ROOT / "tests" / "fixtures" / "legacy_synthetic_steel.json",
            material_id="legacy:synthetic_steel",
            family="electrical_steel",
            author="migration-test",
            updated_at="2026-09-12T00:00:00+09:00",
            source_type="REFERENCE",
        )
        window = MaterialManagerWindow(self.library)
        self.addCleanup(window.close)
        window.reload_materials(select_id=result.material.material_id)
        rows = self.property_rows(window)
        self.assertEqual(
            rows["electromagnetic.BH_curve"],
            ("curve", "4 points", "A/m → T", "Set", ""),
        )
        self.assertEqual(window.source_type_label.text(), "REFERENCE")
        self.assertFalse(window.save_button.isEnabled())
        self.assertFalse(window.delete_button.isEnabled())
        self.assertTrue(window.duplicate_button.isEnabled())
        self.assertEqual(window.edit_material_button.text(), "Edit as User Copy")

        with patch("ems_material.gui.qt.NewMaterialDialog") as dialog_class:
            dialog = dialog_class.return_value
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.values.return_value = (
                "50A350 working copy",
                "electrical_steel",
                "tester",
            )
            window._toggle_edit_mode()

        self.assertTrue(window._editing)
        self.assertTrue(window.save_button.isEnabled())
        self.assertEqual(window._draft.provenance.source_type, "USER_INPUT")
        self.assertEqual(window._draft.parent_ref, "legacy:synthetic_steel@1.0.0")

    def test_property_catalog_is_grouped_and_menu_actions_are_available(self) -> None:
        from ems_material.gui.qt import MaterialManagerWindow

        window = MaterialManagerWindow(self.library)
        self.addCleanup(window.close)
        categories = [
            window.property_tree.topLevelItem(index).text(0)
            for index in range(window.property_tree.topLevelItemCount())
        ]
        self.assertEqual(
            categories,
            [
                "Electric Property",
                "Magnetic Property",
                "Manufacturing",
                "Thermal",
                "Mechanical",
            ],
        )
        self.assertTrue(
            all(
                window.property_tree.topLevelItem(index).isExpanded()
                for index in range(window.property_tree.topLevelItemCount())
            )
        )
        electric = next(
            window.property_tree.topLevelItem(index)
            for index in range(window.property_tree.topLevelItemCount())
            if window.property_tree.topLevelItem(index).text(0) == "Electric Property"
        )
        magnetic = next(
            window.property_tree.topLevelItem(index)
            for index in range(window.property_tree.topLevelItemCount())
            if window.property_tree.topLevelItem(index).text(0) == "Magnetic Property"
        )
        electric_labels = [
            electric.child(index).text(0) for index in range(electric.childCount())
        ]
        magnetic_labels = [
            magnetic.child(index).text(0) for index in range(magnetic.childCount())
        ]
        self.assertLess(
            electric_labels.index("Relative Permittivity"),
            electric_labels.index("Complex Relative Permittivity / Isotropy"),
        )
        for base_label in (
            "Relative Permeability",
            "B-H Curve",
            "Iron Loss / Isotropy",
        ):
            for optional_label in (
                "B-H Curve / Anisotropy",
                "Iron Loss / Anisotropy",
                "Complex Relative Permeability / Isotropy",
                "Complex Relative Permeability / Anisotropy",
            ):
                self.assertLess(
                    magnetic_labels.index(base_label),
                    magnetic_labels.index(optional_label),
                    f"{base_label} should precede {optional_label}",
                )
        for parent, label in (
            (electric, "Complex Relative Permittivity / Isotropy"),
            (electric, "Complex Relative Permittivity / Anisotropy"),
            (magnetic, "Complex Relative Permeability / Isotropy"),
            (magnetic, "Complex Relative Permeability / Anisotropy"),
        ):
            complex_group = next(
                parent.child(index)
                for index in range(parent.childCount())
                if parent.child(index).text(0) == label
            )
            self.assertFalse(complex_group.isExpanded(), label)
        iron_loss_isotropy = next(
            magnetic.child(index)
            for index in range(magnetic.childCount())
            if magnetic.child(index).text(0) == "Iron Loss / Isotropy"
        )
        iron_loss_anisotropy = next(
            magnetic.child(index)
            for index in range(magnetic.childCount())
            if magnetic.child(index).text(0) == "Iron Loss / Anisotropy"
        )
        bh_anisotropy = next(
            magnetic.child(index)
            for index in range(magnetic.childCount())
            if magnetic.child(index).text(0) == "B-H Curve / Anisotropy"
        )
        self.assertTrue(iron_loss_isotropy.isExpanded())
        self.assertFalse(bh_anisotropy.isExpanded())
        self.assertFalse(iron_loss_anisotropy.isExpanded())
        self.assertEqual(
            [
                iron_loss_isotropy.child(index).text(0)
                for index in range(iron_loss_isotropy.childCount())
            ],
            ["Ke", "Kh"],
        )
        self.assertEqual(
            [
                iron_loss_anisotropy.child(index).text(0)
                for index in range(iron_loss_anisotropy.childCount())
            ],
            ["Ke_X", "Ke_Y", "Kh_X", "Kh_Y", "Kh_Z"],
        )
        rows = self.property_rows(window)
        self.assertIn("electrical.relative_permittivity", rows)
        self.assertIn("electromagnetic.BH_curve_x", rows)
        self.assertIn("electromagnetic.complex_relative_permeability_real", rows)
        self.assertIn("electrical.complex_relative_permittivity_imaginary", rows)
        self.assertIn("manufacturing.sheet_thickness", rows)
        self.assertEqual(window.menuBar().actions()[0].text(), "&File")
        self.assertEqual(window.menuBar().actions()[1].text(), "&Edit")
        self.assertEqual(window.menuBar().actions()[2].text(), "&Properties")
        self.assertEqual(window.menuBar().actions()[3].text(), "&Help")
        self.assertEqual(window.help_button.text(), "Help")
        with patch("ems_material.gui.qt.MarkdownViewerDialog") as dialog_class:
            window.help_action.trigger()
            dialog_class.assert_called_once()
            dialog_class.return_value.exec.assert_called_once()
        window.edit_material_action.trigger()
        self.assertTrue(window._editing)
        self.assertTrue(window.save_action.isEnabled())

    def test_iron_loss_note_is_displayed_and_recommended_when_missing(self) -> None:
        from ems_material.gui.qt import MaterialManagerWindow

        window = MaterialManagerWindow(self.library)
        self.addCleanup(window.close)
        window._toggle_edit_mode()
        path = "electromagnetic.iron_loss_ke"
        window._draft = window._draft.with_property(
            path, ScalarProperty(1.0e-4, "W/kg/T^2/Hz^2")
        )
        window._refresh_properties()
        self.assertEqual(self.property_rows(window)[path][3], "Set — note recommended")

        window._draft = window._draft.with_property(
            path,
            ScalarProperty(
                1.0e-4,
                "W/kg/T^2/Hz^2",
                note="Representative B=1.5 T, 50 Hz",
            ),
        )
        window._refresh_properties()
        self.assertEqual(self.property_rows(window)[path][3], "Set")
        self.assertEqual(
            self.property_rows(window)[path][4], "Representative B=1.5 T, 50 Hz"
        )

    def test_unset_catalog_property_can_be_configured(self) -> None:
        from ems_material.gui.qt import MaterialManagerWindow, ScalarEditorDialog

        window = MaterialManagerWindow(self.library)
        self.addCleanup(window.close)
        window._toggle_edit_mode()
        path = "electromagnetic.electrical_conductivity"
        window.property_tree.setCurrentItem(self.property_item(window, path))
        self.assertEqual(window.edit_property_button.text(), "Set Property")
        with (
            patch.object(
                ScalarEditorDialog, "exec", return_value=QDialog.DialogCode.Accepted
            ),
            patch.object(
                ScalarEditorDialog,
                "result_value",
                return_value=(path, ScalarProperty(1.5e6, "S/m")),
            ),
        ):
            window._edit_property()

        value = window._draft.get_property(path)
        self.assertEqual(value.value, 1.5e6)
        self.assertEqual(self.property_rows(window)[path][3], "Set")

    def test_catalog_property_rejects_incompatible_unit_in_gui(self) -> None:
        from ems_material.gui.qt import MaterialManagerWindow, ScalarEditorDialog

        window = MaterialManagerWindow(self.library)
        self.addCleanup(window.close)
        window._toggle_edit_mode()
        path = "manufacturing.sheet_thickness"
        window.property_tree.setCurrentItem(self.property_item(window, path))
        with (
            patch.object(
                ScalarEditorDialog, "exec", return_value=QDialog.DialogCode.Accepted
            ),
            patch.object(
                ScalarEditorDialog,
                "result_value",
                return_value=(path, ScalarProperty(1.0, "kg/m^3")),
            ),
            patch("ems_material.gui.qt.QMessageBox.warning") as warning,
        ):
            window._edit_property()

        self.assertFalse(window._draft.has_property(path))
        warning.assert_called_once()

    def test_new_material_dialog_uses_configured_type_dropdown(self) -> None:
        from ems_material.gui.qt import NewMaterialDialog

        dialog = NewMaterialDialog(material_types=self.library.material_type_catalog)
        self.addCleanup(dialog.close)
        labels = [
            dialog.family_combo.itemText(index)
            for index in range(dialog.family_combo.count())
        ]
        self.assertIn("Electrical Steel Sheet", labels)
        self.assertIn("Permanent Magnet", labels)
        self.assertIn("Conductor", labels)
        self.assertIn("Electrical Insulation", labels)
        dialog.name_edit.setText("NdFeB")
        dialog.author_edit.setText("tester")
        dialog.set_family("magnet")
        self.assertEqual(dialog.values(), ("NdFeB", "permanent_magnet", "tester"))

    def test_conductor_template_hides_steel_and_magnet_properties(self) -> None:
        from ems_material.gui.qt import MaterialManagerWindow

        conductor = self.library.create_from_template(
            name="Copper", family="coil_conductor", author="tester"
        )
        window = MaterialManagerWindow(self.library)
        self.addCleanup(window.close)
        window.reload_materials(select_id=conductor.material_id)
        rows = self.property_rows(window)
        self.assertEqual(conductor.identity.family, "conductor")
        self.assertIn("electromagnetic.electrical_conductivity", rows)
        self.assertIn("electrical.resistance_temperature_coefficient", rows)
        self.assertNotIn("manufacturing.sheet_thickness", rows)
        self.assertNotIn("electromagnetic.BH_curve", rows)
        self.assertNotIn("electromagnetic.remanent_flux_density", rows)

    def test_magnet_and_insulation_templates_show_distinct_properties(self) -> None:
        from ems_material.gui.qt import MaterialManagerWindow

        magnet = self.library.create_from_template(
            name="NdFeB", family="permanent_magnet", author="tester"
        )
        insulation = self.library.create_from_template(
            name="PET", family="electrical_insulator", author="tester"
        )
        window = MaterialManagerWindow(self.library)
        self.addCleanup(window.close)

        window.reload_materials(select_id=magnet.material_id)
        magnet_rows = self.property_rows(window)
        self.assertIn("electromagnetic.remanent_flux_density", magnet_rows)
        self.assertIn("electromagnetic.coercive_field_strength", magnet_rows)
        self.assertNotIn("manufacturing.sheet_thickness", magnet_rows)
        self.assertNotIn("electrical.dielectric_strength", magnet_rows)

        window.reload_materials(select_id=insulation.material_id)
        insulation_rows = self.property_rows(window)
        self.assertIn("electrical.dielectric_strength", insulation_rows)
        self.assertIn("electrical.relative_permittivity", insulation_rows)
        self.assertNotIn("electromagnetic.BH_curve", insulation_rows)
        self.assertNotIn("electromagnetic.remanent_flux_density", insulation_rows)

    def test_admin_mode_directly_edits_reference_without_enabling_delete(self) -> None:
        from ems_material.gui.qt import MaterialManagerWindow

        library = MaterialManager(ROOT / "materials", allow_reference_updates=True)
        window = MaterialManagerWindow(library)
        self.addCleanup(window.close)
        window.reload_materials(select_id="example:test_steel")

        self.assertIn("[ADMIN]", window.windowTitle())
        self.assertEqual(window.edit_material_button.text(), "Edit Material (Admin)")
        self.assertFalse(window.delete_button.isEnabled())
        window._toggle_edit_mode()
        self.assertTrue(window._editing)
        self.assertEqual(window._draft.material_id, "example:test_steel")
        self.assertEqual(window._draft.provenance.source_type, "REFERENCE")
        self.assertTrue(window.save_button.isEnabled())
        self.assertFalse(window.delete_button.isEnabled())

    def test_markdown_help_viewer_renders_content(self) -> None:
        from ems_material.gui.qt import MarkdownViewerDialog

        dialog = MarkdownViewerDialog("# Material Help\n\n- Start here")
        self.addCleanup(dialog.close)
        self.assertIn("Material Help", dialog.viewer.toPlainText())
        self.assertIn("Start here", dialog.viewer.toPlainText())

    def test_window_displays_configured_source_label(self) -> None:
        from ems_material.gui.qt import MaterialManagerWindow

        window = MaterialManagerWindow(MaterialManager(ROOT / "materials"))
        self.addCleanup(window.close)
        self.assertEqual(len(window._material_items), 1)
        self.assertEqual(window.material_tree.columnCount(), 1)
        self.assertEqual(
            window.material_tree.headerItem().text(0),
            "Source / family / material",
        )
        self.assertEqual(
            [
                window.material_tree.topLevelItem(index).text(0)
                for index in range(window.material_tree.topLevelItemCount())
            ],
            ["User", "Examples"],
        )
        self.assertIn("example:test_steel", window._material_items)
        self.assertEqual(
            window._material_items["example:test_steel"].data(0, Qt.ItemDataRole.UserRole),
            "example:test_steel",
        )
        self.assertFalse(window.save_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
