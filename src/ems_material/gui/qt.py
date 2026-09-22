"""Qt widgets for the product-independent Material Manager PoC."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

try:
    from qtpy.QtCore import Qt
    from qtpy.QtGui import QAction, QColor, QBrush
    from qtpy.QtWidgets import (
        QAbstractItemView,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QTextBrowser,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as error:  # pragma: no cover - depends on installation
    from ..errors import GuiDependencyError

    raise GuiDependencyError(
        "Material Manager requires the 'gui' extra: "
        "pip install ems-material-manager[gui]"
    ) from error

from ..errors import PropertyNotFoundError
from ..adapters import EMSolutionInputAdapter
from ..exchange import ExportSelection
from ..manager import MaterialManager
from ..material_types import DEFAULT_MATERIAL_TYPE_CATALOG, MaterialTypeCatalog
from ..model import (
    Axis,
    CurveProperty,
    Material,
    MaterialIdentity,
    Provenance,
    ScalarProperty,
    VersionMetadata,
)
from ..property_catalog import PropertyDefinition
from .curve_io import load_curve_csv


_DEFAULT_COLLAPSED_PROPERTY_SUBCATEGORIES = frozenset(
    {
        "bh_anisotropy",
        "iron_loss_anisotropy",
        "complex_permittivity_isotropy",
        "complex_permittivity_anisotropy",
        "complex_permeability_isotropy",
        "complex_permeability_anisotropy",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScalarEditorDialog(QDialog):
    """Edit a scalar property and its canonical unit."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        path: str = "general.density",
        prop: ScalarProperty | None = None,
        read_only: bool = False,
        default_unit: str = "kg/m^3",
        lock_path: bool = False,
        note_placeholder: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            "View Scalar Property" if read_only else "Edit Scalar Property"
        )
        self.path_edit = QLineEdit(path)
        self.value_edit = QLineEdit("" if prop is None else f"{prop.value:g}")
        self.unit_edit = QLineEdit(default_unit if prop is None else prop.unit)
        self.note_edit = QPlainTextEdit("" if prop is None else (prop.note or ""))
        self._conditions = {} if prop is None else prop.conditions
        self._source = None if prop is None else prop.source
        self._valid_ranges = {} if prop is None else prop.valid_ranges
        self.note_edit.setPlaceholderText(note_placeholder)
        self.note_edit.setMaximumHeight(72)
        form = QFormLayout()
        form.addRow("Property path", self.path_edit)
        form.addRow("Value", self.value_edit)
        form.addRow("Unit", self.unit_edit)
        form.addRow("Note", self.note_edit)
        for edit in (self.path_edit, self.value_edit, self.unit_edit):
            edit.setReadOnly(read_only)
        self.note_edit.setReadOnly(read_only)
        self.path_edit.setReadOnly(read_only or lock_path)
        if read_only:
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(self.reject)
        else:
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok
                | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.setLayout(form)

    def result_value(self) -> tuple[str, ScalarProperty]:
        path = self.path_edit.text().strip()
        if "." not in path:
            raise ValueError("Property path must be '<domain>.<name>'")
        return path, ScalarProperty(
            value=float(self.value_edit.text()),
            unit=self.unit_edit.text().strip(),
            note=self.note_edit.toPlainText().strip() or None,
            conditions=self._conditions,
            source=self._source,
            valid_ranges=self._valid_ranges,
        )

    def accept(self) -> None:
        try:
            self.result_value()
        except Exception as error:
            QMessageBox.warning(self, "Invalid scalar", str(error))
            return
        super().accept()


class CurveEditorDialog(QDialog):
    """Table, CSV import and plot editor for one-dimensional properties."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        path: str = "electromagnetic.BH_curve",
        prop: CurveProperty | None = None,
        read_only: bool = False,
        material_name: str | None = None,
        x_name: str = "H",
        x_unit: str = "A/m",
        y_name: str = "B",
        y_unit: str = "T",
        lock_path: bool = False,
        note_placeholder: str = "",
    ) -> None:
        super().__init__(parent)
        self.material_name = material_name
        action = "View" if read_only else "Edit"
        self.setWindowTitle(
            f"{material_name} — {action} 1D Curve"
            if material_name
            else f"{action} 1D Curve"
        )
        self.resize(850, 600)
        self.path_edit = QLineEdit(path)
        self.x_name_edit = QLineEdit(prop.x.name if prop else x_name)
        self.x_unit_edit = QLineEdit(prop.x.unit if prop else x_unit)
        self.y_name_edit = QLineEdit(prop.y.name if prop else y_name)
        self.y_unit_edit = QLineEdit(prop.y.unit if prop else y_unit)
        self.note_edit = QPlainTextEdit("" if prop is None else (prop.note or ""))
        self._conditions = {} if prop is None else prop.conditions
        self._source = None if prop is None else prop.source
        self._valid_ranges = {} if prop is None else prop.valid_ranges
        self.note_edit.setPlaceholderText(note_placeholder)
        self.note_edit.setMaximumHeight(72)
        self.x_scale_combo = QComboBox()
        self.y_scale_combo = QComboBox()
        self.x_scale_combo.addItems(("linear", "log"))
        self.y_scale_combo.addItems(("linear", "log"))
        self.x_scale_combo.setCurrentText(
            prop.display.get("x_scale", "linear") if prop else "linear"
        )
        self.y_scale_combo.setCurrentText(
            prop.display.get("y_scale", "linear") if prop else "linear"
        )
        for edit in (
            self.x_name_edit,
            self.x_unit_edit,
            self.y_name_edit,
            self.y_unit_edit,
        ):
            edit.textChanged.connect(self._redraw)
        self.x_scale_combo.currentTextChanged.connect(self._redraw)
        self.y_scale_combo.currentTextChanged.connect(self._redraw)

        metadata = QGridLayout()
        metadata.addWidget(QLabel("Property path"), 0, 0)
        metadata.addWidget(self.path_edit, 0, 1, 1, 3)
        metadata.addWidget(QLabel("X name"), 1, 0)
        metadata.addWidget(self.x_name_edit, 1, 1)
        metadata.addWidget(QLabel("X unit"), 1, 2)
        metadata.addWidget(self.x_unit_edit, 1, 3)
        metadata.addWidget(QLabel("Y name"), 2, 0)
        metadata.addWidget(self.y_name_edit, 2, 1)
        metadata.addWidget(QLabel("Y unit"), 2, 2)
        metadata.addWidget(self.y_unit_edit, 2, 3)
        metadata.addWidget(QLabel("X scale"), 3, 0)
        metadata.addWidget(self.x_scale_combo, 3, 1)
        metadata.addWidget(QLabel("Y scale"), 3, 2)
        metadata.addWidget(self.y_scale_combo, 3, 3)
        metadata.addWidget(QLabel("Note"), 4, 0)
        metadata.addWidget(self.note_edit, 4, 1, 1, 3)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(("X", "Y"))
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.itemChanged.connect(self._redraw)
        if read_only:
            self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        self.canvas = None
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure

            figure = Figure(figsize=(4, 3), tight_layout=True)
            self.axes = figure.add_subplot(111)
            self.canvas = FigureCanvasQTAgg(figure)
        except ImportError:  # pragma: no cover - covered by optional dependency
            self.axes = None

        import_button = QPushButton("Import CSV")
        add_button = QPushButton("Add Row")
        remove_button = QPushButton("Remove Row")
        import_button.clicked.connect(self._import_csv)
        add_button.clicked.connect(lambda: self._append_row("", ""))
        remove_button.clicked.connect(self._remove_rows)
        tools = QHBoxLayout()
        tools.addWidget(import_button)
        tools.addWidget(add_button)
        tools.addWidget(remove_button)
        tools.addStretch()
        for widget in (
            self.path_edit,
            self.x_name_edit,
            self.x_unit_edit,
            self.y_name_edit,
            self.y_unit_edit,
        ):
            widget.setReadOnly(read_only)
        self.path_edit.setReadOnly(read_only or lock_path)
        self.note_edit.setReadOnly(read_only)
        import_button.setEnabled(not read_only)
        add_button.setEnabled(not read_only)
        remove_button.setEnabled(not read_only)

        if prop:
            self.set_values(prop.x.values, prop.y.values)
        else:
            self.set_values((0.0, 1.0), (0.0, 1.0))

        if read_only:
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(self.reject)
        else:
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok
                | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)

        body = QVBoxLayout(self)
        body.addLayout(metadata)
        body.addLayout(tools)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        if self.canvas is not None:
            splitter.addWidget(self.canvas)
        body.addWidget(splitter, 1)
        body.addWidget(buttons)
        self._redraw()

    def _append_row(self, x_value: str, y_value: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(x_value))
        self.table.setItem(row, 1, QTableWidgetItem(y_value))

    def set_values(
        self, x_values: tuple[float, ...], y_values: tuple[float, ...]
    ) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for x_value, y_value in zip(x_values, y_values):
            self._append_row(f"{x_value:g}", f"{y_value:g}")
        self.table.blockSignals(False)
        self._redraw()

    def _remove_rows(self) -> None:
        rows = sorted(
            {index.row() for index in self.table.selectedIndexes()}, reverse=True
        )
        for row in rows:
            self.table.removeRow(row)
        self._redraw()

    def _import_csv(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import curve CSV", "", "CSV files (*.csv);;All files (*)"
        )
        if not filename:
            return
        try:
            x_values, y_values = load_curve_csv(filename)
            self.set_values(x_values, y_values)
        except Exception as error:
            QMessageBox.warning(self, "CSV import failed", str(error))

    def result_value(self) -> tuple[str, CurveProperty]:
        path = self.path_edit.text().strip()
        if "." not in path:
            raise ValueError("Property path must be '<domain>.<name>'")
        x_values: list[float] = []
        y_values: list[float] = []
        for row in range(self.table.rowCount()):
            x_item, y_item = self.table.item(row, 0), self.table.item(row, 1)
            if x_item is None or y_item is None:
                raise ValueError(f"Row {row + 1} is incomplete")
            x_values.append(float(x_item.text()))
            y_values.append(float(y_item.text()))
        return path, CurveProperty(
            x=Axis(
                self.x_name_edit.text().strip(),
                self.x_unit_edit.text().strip(),
                tuple(x_values),
            ),
            y=Axis(
                self.y_name_edit.text().strip(),
                self.y_unit_edit.text().strip(),
                tuple(y_values),
            ),
            display={
                "x_scale": self.x_scale_combo.currentText(),
                "y_scale": self.y_scale_combo.currentText(),
            },
            note=self.note_edit.toPlainText().strip() or None,
            conditions=self._conditions,
            source=self._source,
            valid_ranges=self._valid_ranges,
        )

    def _redraw(self, *_args: object) -> None:
        if self.canvas is None or self.axes is None:
            return
        x_values: list[float] = []
        y_values: list[float] = []
        try:
            for row in range(self.table.rowCount()):
                x_values.append(float(self.table.item(row, 0).text()))
                y_values.append(float(self.table.item(row, 1).text()))
        except (AttributeError, ValueError):
            return
        self.axes.clear()
        self.axes.plot(
            x_values,
            y_values,
            marker="o",
            label=self.material_name,
            color="#1676b8",
        )
        self.axes.set_xscale(self.x_scale_combo.currentText())
        self.axes.set_yscale(self.y_scale_combo.currentText())
        self.axes.set_xlabel(f"{self.x_name_edit.text()} [{self.x_unit_edit.text()}]")
        self.axes.set_ylabel(f"{self.y_name_edit.text()} [{self.y_unit_edit.text()}]")
        self.axes.grid(True)
        if self.material_name:
            self.axes.legend()
        self.canvas.draw_idle()

    def accept(self) -> None:
        try:
            self.result_value()
        except Exception as error:
            QMessageBox.warning(self, "Invalid curve", str(error))
            return
        super().accept()


class NewMaterialDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        material_types: MaterialTypeCatalog | None = None,
    ) -> None:
        super().__init__(parent)
        self.material_types = material_types or DEFAULT_MATERIAL_TYPE_CATALOG
        self.setWindowTitle("New User Material")
        self.name_edit = QLineEdit()
        self.family_combo = QComboBox()
        self.family_combo.setEditable(self.material_types.allow_custom_family)
        for material_type in self.material_types.types:
            self.family_combo.addItem(material_type.label, material_type.family)
            index = self.family_combo.count() - 1
            self.family_combo.setItemData(
                index, material_type.description, Qt.ItemDataRole.ToolTipRole
            )
        self.type_description = QLabel()
        self.type_description.setWordWrap(True)
        self.family_combo.currentIndexChanged.connect(self._update_type_description)
        self.author_edit = QLineEdit()
        form = QFormLayout(self)
        form.addRow("Name", self.name_edit)
        form.addRow("Material Type", self.family_combo)
        form.addRow("Description", self.type_description)
        form.addRow("Author", self.author_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._update_type_description()

    def _update_type_description(self, _index: int = -1) -> None:
        current = self.family_combo.currentIndex()
        text = self.family_combo.currentText().strip()
        data = self.family_combo.itemData(current)
        family = (
            str(data)
            if data is not None and text == self.family_combo.itemText(current)
            else text
        )
        material_type = self.material_types.material_type(family)
        self.type_description.setText(
            material_type.description if material_type else "Custom material family"
        )

    def values(self) -> tuple[str, str, str]:
        name = self.name_edit.text().strip()
        author = self.author_edit.text().strip()
        family_text = self.family_combo.currentText().strip()
        current = self.family_combo.currentIndex()
        family_data = self.family_combo.itemData(current)
        family = (
            str(family_data)
            if family_data is not None
            and family_text == self.family_combo.itemText(current)
            else family_text
        )
        values = (name, self.material_types.resolve_family(family), author)
        if not all(values):
            raise ValueError("Name, material type and author are required")
        return values

    def set_family(self, family: str) -> None:
        canonical = self.material_types.resolve_family(family)
        index = self.family_combo.findData(canonical)
        if index >= 0:
            self.family_combo.setCurrentIndex(index)
        else:
            self.family_combo.setCurrentText(family)

    def accept(self) -> None:
        try:
            self.values()
        except ValueError as error:
            QMessageBox.warning(self, "Invalid material", str(error))
            return
        super().accept()


class MarkdownViewerDialog(QDialog):
    """Read-only Markdown help viewer using Qt's built-in renderer."""

    def __init__(
        self,
        markdown: str,
        *,
        title: str = "EMS Material Manager Help",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(920, 680)

        self.viewer = QTextBrowser()
        self.viewer.setOpenExternalLinks(True)
        self.viewer.setMarkdown(markdown)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.viewer)
        layout.addWidget(buttons)


class MaterialManagerWindow(QMainWindow):
    """Common user-material browser/editor backed only by MaterialManager."""

    def __init__(self, library: MaterialManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.library = library
        self._draft: Material | None = None
        self._loaded_version: str | None = None
        self._editing = False
        self._material_items: dict[str, QTreeWidgetItem] = {}
        title = "EMS Material Manager"
        if self.library.admin_reference_updates:
            title += " [ADMIN]"
        self.setWindowTitle(title)
        self.resize(1200, 760)
        self.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid #9aa7b2; "
            "border-radius: 5px; margin-top: 8px; padding-top: 8px; }"
            "QGroupBox::title { color: #145a7a; subcontrol-origin: margin; "
            "left: 8px; padding: 0 4px; }"
            "QPushButton { padding: 5px 10px; }"
            "QPushButton:enabled { background-color: #e7f2f8; border: 1px solid "
            "#73a6bf; border-radius: 4px; }"
            "QPushButton:enabled:hover { background-color: #cfe8f4; }"
        )

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search name, ID, manufacturer, tag...")
        self.material_tree = QTreeWidget()
        self.material_tree.setColumnCount(1)
        self.material_tree.setHeaderLabel("Source / family / material")
        self.material_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.material_tree.setAlternatingRowColors(True)
        self.material_tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.search_edit.textChanged.connect(self.reload_materials)
        self.material_tree.currentItemChanged.connect(self._load_selected)

        self.new_button = QPushButton("New")
        self.refresh_button = QPushButton("Refresh")
        self.duplicate_button = QPushButton("Duplicate")
        self.delete_button = QPushButton("Delete")
        self.import_button = QPushButton("Import")
        self.export_button = QPushButton("Export")
        self.new_button.clicked.connect(self._new_material)
        self.refresh_button.clicked.connect(self.reload_materials)
        self.duplicate_button.clicked.connect(self._duplicate_material)
        self.delete_button.clicked.connect(self._delete_material)
        self.import_button.clicked.connect(self._import_material)
        self.export_button.clicked.connect(self._export_material)
        left_buttons = QGridLayout()
        for index, button in enumerate(
            (
                self.new_button,
                self.refresh_button,
                self.duplicate_button,
                self.delete_button,
                self.import_button,
                self.export_button,
            )
        ):
            left_buttons.addWidget(button, index // 3, index % 3)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self.search_edit)
        left_layout.addWidget(self.material_tree, 1)
        left_layout.addLayout(left_buttons)

        self.id_label = QLabel("—")
        self.name_edit = QLineEdit()
        self.family_edit = QLineEdit()
        self.manufacturer_edit = QLineEdit()
        self.grade_edit = QLineEdit()
        self.description_edit = QLineEdit()
        identity_form = QFormLayout()
        identity_form.addRow("Material ID", self.id_label)
        identity_form.addRow("Name", self.name_edit)
        identity_form.addRow("Family", self.family_edit)
        identity_form.addRow("Manufacturer", self.manufacturer_edit)
        identity_form.addRow("Grade", self.grade_edit)
        identity_form.addRow("Description", self.description_edit)
        identity_group = QGroupBox("Identity")
        identity_group.setLayout(identity_form)

        self.material_version_edit = QLineEdit()
        self.author_edit = QLineEdit()
        self.change_note_edit = QLineEdit()
        version_form = QFormLayout()
        version_form.addRow("Material version", self.material_version_edit)
        version_form.addRow("Author", self.author_edit)
        version_form.addRow("Change note", self.change_note_edit)
        version_group = QGroupBox("Version")
        version_group.setLayout(version_form)

        self.source_type_label = QLabel("—")
        self.reference_edit = QLineEdit()
        self.provenance_date_edit = QLineEdit()
        self.provenance_notes_edit = QLineEdit()
        provenance_form = QFormLayout()
        provenance_form.addRow("Source type", self.source_type_label)
        provenance_form.addRow("Reference", self.reference_edit)
        provenance_form.addRow("Date", self.provenance_date_edit)
        provenance_form.addRow("Notes", self.provenance_notes_edit)
        provenance_group = QGroupBox("Provenance")
        provenance_group.setLayout(provenance_form)

        self.property_tree = QTreeWidget()
        self.property_tree.setColumnCount(6)
        self.property_tree.setHeaderLabels(
            ("Property", "Type", "Value / points", "Unit", "Status", "Note")
        )
        self.property_tree.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.property_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.property_tree.setAlternatingRowColors(True)
        self.property_tree.itemDoubleClicked.connect(lambda *_: self._edit_property())
        self.property_tree.currentItemChanged.connect(
            lambda *_: self._update_property_actions()
        )
        self.property_tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, 5):
            self.property_tree.header().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.property_tree.header().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        # Kept as an alias for product-side code that still locates this widget
        # through the original attribute name.
        self.property_table = self.property_tree
        self.add_scalar_button = QPushButton("Add Custom Scalar")
        self.add_curve_button = QPushButton("Add Custom Curve")
        self.edit_property_button = QPushButton("View Property")
        self.remove_property_button = QPushButton("Clear Property")
        self.add_scalar_button.clicked.connect(self._add_scalar)
        self.add_curve_button.clicked.connect(self._add_curve)
        self.edit_property_button.clicked.connect(self._edit_property)
        self.remove_property_button.clicked.connect(self._remove_property)
        property_tools = QHBoxLayout()
        for button in (
            self.add_scalar_button,
            self.add_curve_button,
            self.edit_property_button,
            self.remove_property_button,
        ):
            property_tools.addWidget(button)
        property_tools.addStretch()
        property_group = QGroupBox("Properties")
        property_layout = QVBoxLayout(property_group)
        property_layout.addWidget(self.property_tree)
        property_layout.addLayout(property_tools)

        self.validation_label = QLabel("No material selected")
        self.validation_label.setWordWrap(True)
        self.edit_material_button = QPushButton("Edit Material")
        self.edit_material_button.clicked.connect(self._toggle_edit_mode)
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self._save_material)
        self._create_menus()
        bottom = QHBoxLayout()
        bottom.addWidget(self.validation_label, 1)
        bottom.addWidget(self.edit_material_button)
        bottom.addWidget(self.save_button)

        top = QHBoxLayout()
        top.addWidget(identity_group, 2)
        top.addWidget(version_group, 1)
        top.addWidget(provenance_group, 1)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        if self.library.admin_reference_updates:
            admin_label = QLabel(
                "ADMIN MODE — reference-source materials can be updated directly; "
                "deletion remains disabled."
            )
            admin_label.setStyleSheet(
                "background:#f6a800; color:#2b2100; font-weight:bold; "
                "padding:6px; border-radius:3px;"
            )
            right_layout.addWidget(admin_label)
        right_layout.addLayout(top)
        right_layout.addWidget(property_group, 1)
        right_layout.addLayout(bottom)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        self.reload_materials()

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self.new_action = QAction("&New User Material", self)
        self.new_action.setShortcut("Ctrl+N")
        self.new_action.triggered.connect(self._new_material)
        file_menu.addAction(self.new_action)
        self.import_action = QAction("&Import Material...", self)
        self.import_action.triggered.connect(self._import_material)
        file_menu.addAction(self.import_action)
        self.export_action = QAction("&Export Material...", self)
        self.export_action.triggered.connect(self._export_material)
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        self.import_emsolution_action = QAction(
            "Import from EMSolution input.json...", self
        )
        self.import_emsolution_action.triggered.connect(
            self._import_emsolution_material
        )
        file_menu.addAction(self.import_emsolution_action)
        self.export_emsolution_action = QAction(
            "Export to EMSolution input.json...", self
        )
        self.export_emsolution_action.triggered.connect(
            self._export_emsolution_material
        )
        file_menu.addAction(self.export_emsolution_action)
        file_menu.addSeparator()
        self.refresh_action = QAction("&Refresh", self)
        self.refresh_action.setShortcut("F5")
        self.refresh_action.triggered.connect(self.reload_materials)
        file_menu.addAction(self.refresh_action)
        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        edit_menu = self.menuBar().addMenu("&Edit")
        self.edit_material_action = QAction("Edit Material", self)
        self.edit_material_action.triggered.connect(self._toggle_edit_mode)
        edit_menu.addAction(self.edit_material_action)
        self.save_action = QAction("&Save Material", self)
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.triggered.connect(self._save_material)
        edit_menu.addAction(self.save_action)
        self.duplicate_action = QAction("&Duplicate Material...", self)
        self.duplicate_action.triggered.connect(self._duplicate_material)
        edit_menu.addAction(self.duplicate_action)
        self.delete_action = QAction("&Delete Material", self)
        self.delete_action.triggered.connect(self._delete_material)
        edit_menu.addAction(self.delete_action)

        property_menu = self.menuBar().addMenu("&Properties")
        self.edit_property_action = QAction("View Property", self)
        self.edit_property_action.triggered.connect(self._edit_property)
        property_menu.addAction(self.edit_property_action)
        self.clear_property_action = QAction("Clear Property", self)
        self.clear_property_action.triggered.connect(self._remove_property)
        property_menu.addAction(self.clear_property_action)
        property_menu.addSeparator()
        self.add_scalar_action = QAction("Add Custom Scalar...", self)
        self.add_scalar_action.triggered.connect(self._add_scalar)
        property_menu.addAction(self.add_scalar_action)
        self.add_curve_action = QAction("Add Custom Curve...", self)
        self.add_curve_action.triggered.connect(self._add_curve)
        property_menu.addAction(self.add_curve_action)
        property_menu.addSeparator()
        expand_action = QAction("Expand All Categories", self)
        expand_action.triggered.connect(self.property_tree.expandAll)
        property_menu.addAction(expand_action)
        collapse_action = QAction("Collapse All Categories", self)
        collapse_action.triggered.connect(self.property_tree.collapseAll)
        property_menu.addAction(collapse_action)

        help_menu = self.menuBar().addMenu("&Help")
        self.help_action = QAction("Open &README...", self)
        self.help_action.setShortcut("F1")
        self.help_action.triggered.connect(self._show_help)
        help_menu.addAction(self.help_action)

        self.help_button = QPushButton("Help")
        self.help_button.setToolTip("Open the Material Manager README")
        self.help_button.clicked.connect(self._show_help)
        self.statusBar().addPermanentWidget(self.help_button)

    @staticmethod
    def _help_markdown() -> str:
        """Load the project README without requiring an extra Markdown package."""
        module_path = Path(__file__).resolve()
        candidates = (
            module_path.parents[3] / "README.md",
            Path.cwd() / "README.md",
        )
        for path in candidates:
            if path.is_file():
                return path.read_text(encoding="utf-8")
        return (
            "# EMS Material Manager\n\n"
            "The packaged README could not be found. Open the project README "
            "from the installed source tree for the full user guide and "
            "EMSolution API reference."
        )

    def _show_help(self) -> None:
        MarkdownViewerDialog(self._help_markdown(), parent=self).exec()

    def reload_materials(self, *_args: object, select_id: str | None = None) -> None:
        if select_id is None and self._draft is not None:
            select_id = self._draft.material_id
        query = self.search_edit.text().strip()
        try:
            materials = (
                self.library.search(text=query) if query else self.library.list()
            )
            source_names = self.library.list_sources()
        except Exception as error:
            self.material_tree.blockSignals(True)
            self.material_tree.clear()
            self.material_tree.blockSignals(False)
            self._draft = None
            self._loaded_version = None
            self._clear_form()
            self.validation_label.setText(f"Library configuration error — {error}")
            return
        self.material_tree.blockSignals(True)
        self.material_tree.clear()
        self._material_items = {}
        source_colors = ("#d9edf7", "#dff0d8", "#fff2cc", "#eadcf8")
        source_items: dict[str, QTreeWidgetItem] = {}
        family_items: dict[tuple[str, str], QTreeWidgetItem] = {}
        for index, source_name in enumerate(source_names):
            source_item = QTreeWidgetItem((source_name,))
            source_item.setBackground(
                0, QBrush(QColor(source_colors[index % len(source_colors)]))
            )
            source_font = source_item.font(0)
            source_font.setBold(True)
            source_item.setFont(0, source_font)
            self.material_tree.addTopLevelItem(source_item)
            source_items[source_name] = source_item
        first_material_item: QTreeWidgetItem | None = None
        for material in materials:
            source = self.library.source_for(material.material_id) or "Materials"
            source_item = source_items.get(source)
            if source_item is None:
                source_item = QTreeWidgetItem((source,))
                self.material_tree.addTopLevelItem(source_item)
                source_items[source] = source_item
            family_key = (source, material.family)
            family_item = family_items.get(family_key)
            if family_item is None:
                family_item = QTreeWidgetItem((material.family,))
                family_item.setForeground(0, QBrush(QColor("#4b6472")))
                source_item.addChild(family_item)
                family_items[family_key] = family_item
            item = QTreeWidgetItem((material.name,))
            item.setData(0, Qt.ItemDataRole.UserRole, material.material_id)
            family_item.addChild(item)
            self._material_items[material.material_id] = item
            if first_material_item is None:
                first_material_item = item
        self.material_tree.expandAll()
        selected_item = self._material_items.get(select_id or "")
        self.material_tree.blockSignals(False)
        if selected_item is not None:
            self.material_tree.setCurrentItem(selected_item)
        elif first_material_item is not None:
            self.material_tree.setCurrentItem(first_material_item)
        else:
            self._draft = None
            self._loaded_version = None
            self._clear_form()

    def _load_selected(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        if current is None:
            return
        material_id = current.data(0, Qt.ItemDataRole.UserRole)
        if not material_id:
            return
        self._draft = self.library.get(material_id)
        self._loaded_version = self._draft.material_version
        self._populate_form(self._draft)

    def _populate_form(self, material: Material) -> None:
        identity = material.identity
        self.id_label.setText(material.material_id)
        self.name_edit.setText(identity.name)
        self.family_edit.setText(identity.family)
        self.manufacturer_edit.setText(identity.manufacturer or "")
        self.grade_edit.setText(identity.grade or "")
        self.description_edit.setText(identity.description or "")
        self.material_version_edit.setText(material.material_version)
        self.author_edit.setText(material.version_metadata.author)
        self.change_note_edit.setText(material.version_metadata.change_note)
        provenance = material.provenance
        self.source_type_label.setText(provenance.source_type)
        self.reference_edit.setText(provenance.reference or "")
        self.provenance_date_edit.setText(provenance.date or "")
        self.provenance_notes_edit.setText(provenance.notes or "")
        self._editing = False
        self._refresh_properties()
        self._refresh_validation()
        self._update_edit_controls()

    def _update_edit_controls(self) -> None:
        has_material = self._draft is not None
        writable = has_material and self.library.is_writable(self._draft.material_id)
        deletable = has_material and self.library.is_deletable(self._draft.material_id)
        editable = bool(writable and self._editing)
        for widget in (
            self.name_edit,
            self.family_edit,
            self.manufacturer_edit,
            self.grade_edit,
            self.description_edit,
            self.material_version_edit,
            self.author_edit,
            self.change_note_edit,
            self.reference_edit,
            self.provenance_date_edit,
            self.provenance_notes_edit,
        ):
            widget.setEnabled(editable)
        self.property_tree.setEnabled(has_material)
        for button in (
            self.add_scalar_button,
            self.add_curve_button,
            self.save_button,
        ):
            button.setEnabled(editable)
        self.add_scalar_action.setEnabled(editable)
        self.add_curve_action.setEnabled(editable)
        self.save_action.setEnabled(editable)
        self.delete_button.setEnabled(bool(deletable))
        self.delete_action.setEnabled(bool(deletable))
        self.duplicate_button.setEnabled(has_material)
        self.duplicate_action.setEnabled(has_material)
        self.export_button.setEnabled(has_material)
        self.export_action.setEnabled(has_material)
        self.export_emsolution_action.setEnabled(has_material)
        self.edit_material_button.setEnabled(has_material)
        if not has_material:
            self.edit_material_button.setText("Edit Material")
        elif self._editing:
            self.edit_material_button.setText("Cancel Edit")
        elif writable:
            if self._draft.provenance.source_type == "USER_INPUT":
                self.edit_material_button.setText("Edit Material")
            else:
                self.edit_material_button.setText("Edit Material (Admin)")
        else:
            self.edit_material_button.setText("Edit as User Copy")
        self.edit_material_action.setEnabled(has_material)
        self.edit_material_action.setText(self.edit_material_button.text())
        self._update_property_actions()

    def _update_property_actions(self) -> None:
        path = self._selected_property_path()
        has_selection = self._draft is not None and path is not None
        editable = bool(
            has_selection
            and self._editing
            and self.library.is_writable(self._draft.material_id)
        )
        exists = bool(has_selection and self._property_exists(path))
        if editable:
            label = "Edit Property" if exists else "Set Property"
        else:
            label = "View Property"
        self.edit_property_button.setText(label)
        self.edit_property_action.setText(label)
        self.edit_property_button.setEnabled(
            bool(has_selection and (exists or editable))
        )
        self.edit_property_action.setEnabled(
            bool(has_selection and (exists or editable))
        )
        self.remove_property_button.setEnabled(bool(editable and exists))
        self.clear_property_action.setEnabled(bool(editable and exists))

    def _toggle_edit_mode(self) -> None:
        if self._draft is None:
            return
        if self._editing:
            material_id = self._draft.material_id
            self._draft = self.library.get(material_id)
            self._loaded_version = self._draft.material_version
            self._populate_form(self._draft)
            self.statusBar().showMessage("Changes discarded", 3000)
            return
        if self.library.is_writable(self._draft.material_id):
            self._editing = True
            self._update_edit_controls()
            self.statusBar().showMessage("Edit mode", 3000)
            return
        self._duplicate_for_edit()

    def _duplicate_for_edit(self) -> None:
        if self._draft is None:
            return
        dialog = NewMaterialDialog(self, self.library.material_type_catalog)
        dialog.setWindowTitle("Create Editable User Copy")
        dialog.name_edit.setText(f"{self._draft.name} copy")
        dialog.set_family(self._draft.family)
        dialog.family_combo.setEnabled(False)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            name, _family, author = dialog.values()
            material = self.library.duplicate(
                self._draft.material_id,
                new_name=name,
                author=author,
                change_note="Editable copy of reference material",
            )
            self.reload_materials(select_id=material.material_id)
            self._editing = True
            self._update_edit_controls()
        except Exception as error:
            QMessageBox.warning(self, "Create editable copy failed", str(error))

    def _clear_form(self) -> None:
        self._editing = False
        self.id_label.setText("—")
        self.source_type_label.setText("—")
        for edit in (
            self.name_edit,
            self.family_edit,
            self.manufacturer_edit,
            self.grade_edit,
            self.description_edit,
            self.material_version_edit,
            self.author_edit,
            self.change_note_edit,
            self.reference_edit,
            self.provenance_date_edit,
            self.provenance_notes_edit,
        ):
            edit.clear()
        self.property_tree.clear()
        self.validation_label.setText("No material selected")
        self.validation_label.setStyleSheet("")
        for button in (
            self.duplicate_button,
            self.delete_button,
            self.add_scalar_button,
            self.add_curve_button,
            self.edit_property_button,
            self.remove_property_button,
            self.edit_material_button,
            self.save_button,
        ):
            button.setEnabled(False)
        for action in (
            self.export_action,
            self.export_emsolution_action,
            self.edit_material_action,
            self.save_action,
            self.duplicate_action,
            self.delete_action,
            self.edit_property_action,
            self.clear_property_action,
            self.add_scalar_action,
            self.add_curve_action,
        ):
            action.setEnabled(False)

    def _refresh_properties(self) -> None:
        initial_tree = self.property_tree.topLevelItemCount() == 0
        collapsed: set[str] = set()

        def remember_collapsed(item: QTreeWidgetItem) -> None:
            if item.childCount() and not item.isExpanded():
                key = item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(key, str):
                    collapsed.add(key)
            for index in range(item.childCount()):
                remember_collapsed(item.child(index))

        for index in range(self.property_tree.topLevelItemCount()):
            remember_collapsed(self.property_tree.topLevelItem(index))
        self.property_tree.clear()
        if self._draft is None:
            return

        existing: dict[str, tuple[str, ScalarProperty | CurveProperty]] = {}
        for domain, values in sorted(self._draft.properties.items()):
            for name, prop in sorted(values.items()):
                path = f"{domain}.{name}"
                existing[path.casefold()] = (path, prop)

        property_catalog = self.library.property_catalog
        material_types = self.library.material_type_catalog
        canonical_family = material_types.resolve_family(self._draft.identity.family)
        template = material_types.template_for(canonical_family)
        template_paths = (
            {item.path.casefold() for item in template.properties}
            if template is not None
            else None
        )

        category_items: dict[str, QTreeWidgetItem] = {}
        for category in property_catalog.categories:
            item = QTreeWidgetItem((category.label, "", "", "", ""))
            item.setData(0, Qt.ItemDataRole.UserRole, category.key)
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            color = QBrush(QColor(category.color))
            for column in range(self.property_tree.columnCount()):
                item.setBackground(column, color)
            self.property_tree.addTopLevelItem(item)
            item.setExpanded(category.key not in collapsed)
            category_items[category.key] = item

        subcategory_items: dict[tuple[str, str], QTreeWidgetItem] = {}
        for subcategory in property_catalog.subcategories:
            key = f"subcategory:{subcategory.category}:{subcategory.key}"
            item = QTreeWidgetItem((subcategory.label, "", "", "", ""))
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            color = QBrush(QColor(subcategory.color))
            for column in range(self.property_tree.columnCount()):
                item.setBackground(column, color)
            subcategory_items[(subcategory.category, subcategory.key)] = item

        consumed: set[str] = set()
        first_property_item: QTreeWidgetItem | None = None
        first_existing_item: QTreeWidgetItem | None = None
        for definition in property_catalog.definitions:
            candidates = (definition.path, *definition.aliases)
            matched = next(
                (
                    existing[candidate.casefold()]
                    for candidate in candidates
                    if candidate.casefold() in existing
                ),
                None,
            )
            if matched is None:
                if template_paths is not None:
                    if definition.path.casefold() not in template_paths:
                        continue
                elif not property_catalog.applies_to_family(
                    definition, canonical_family
                ):
                    continue
            if matched is None:
                path, prop = definition.path, None
            else:
                path, prop = matched
                consumed.add(path.casefold())
            template_property = material_types.template_property(
                canonical_family, definition.path
            )
            requirement = template_property.requirement if template_property else None
            child = self._property_item(definition, path, prop, requirement=requirement)
            parent = category_items[definition.category]
            if definition.subcategory is not None:
                parent = subcategory_items[
                    (definition.category, definition.subcategory)
                ]
            parent.addChild(child)
            if first_property_item is None:
                first_property_item = child
            if prop is not None and first_existing_item is None:
                first_existing_item = child

        # Direct properties are the base (isotropic) inputs.  Append catalog
        # subcategories afterwards so optional anisotropic/complex groups read
        # as refinements, while retaining the externally configured group order.
        for subcategory in property_catalog.subcategories:
            item = subcategory_items[(subcategory.category, subcategory.key)]
            if item.childCount() > 0:
                category_items[subcategory.category].addChild(item)
                key = f"subcategory:{subcategory.category}:{subcategory.key}"
                default_collapsed = (
                    initial_tree
                    and subcategory.key in _DEFAULT_COLLAPSED_PROPERTY_SUBCATEGORIES
                )
                item.setExpanded(key not in collapsed and not default_collapsed)

        custom_categories: dict[str, QTreeWidgetItem] = {}
        for folded_path, (path, prop) in existing.items():
            if folded_path in consumed:
                continue
            domain = path.split(".", 1)[0]
            key = f"custom:{domain}"
            parent = custom_categories.get(key)
            if parent is None:
                parent = QTreeWidgetItem((f"Other / {domain}", "", "", "", ""))
                parent.setData(0, Qt.ItemDataRole.UserRole, key)
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                for column in range(self.property_tree.columnCount()):
                    parent.setBackground(column, QBrush(QColor("#e7e7e7")))
                self.property_tree.addTopLevelItem(parent)
                parent.setExpanded(key not in collapsed)
                custom_categories[key] = parent
            definition = property_catalog.property_definition(path)
            label = definition.label if definition else path.split(".", 1)[1]
            child = self._property_item(definition, path, prop, label=label)
            parent.addChild(child)
            if first_property_item is None:
                first_property_item = child
            if first_existing_item is None:
                first_existing_item = child

        for item in tuple(category_items.values()):
            if item.childCount() == 0:
                index = self.property_tree.indexOfTopLevelItem(item)
                if index >= 0:
                    self.property_tree.takeTopLevelItem(index)

        selected_item = first_existing_item or first_property_item
        if selected_item is not None:
            self.property_tree.setCurrentItem(selected_item)
        self._update_property_actions()

    def _property_item(
        self,
        definition: PropertyDefinition | None,
        path: str,
        prop: ScalarProperty | CurveProperty | None,
        *,
        label: str | None = None,
        requirement: str | None = None,
    ) -> QTreeWidgetItem:
        if prop is None:
            kind = definition.kind if definition else ""
            summary = "—"
            unit = definition.unit if definition and definition.kind == "scalar" else ""
            if definition and definition.kind == "curve":
                unit = f"{definition.x_unit} → {definition.y_unit}"
            required = requirement == "required" or (
                requirement is None
                and bool(definition and definition.required_profiles)
            )
            if required:
                status = "Required — not set"
            elif requirement == "recommended":
                status = "Recommended — not set"
            else:
                status = "Not set"
            note = ""
        elif isinstance(prop, ScalarProperty):
            kind, summary, unit, status = "scalar", f"{prop.value:g}", prop.unit, "Set"
            note = prop.note or ""
        else:
            kind = "curve"
            summary = f"{len(prop.x.values)} points"
            unit = f"{prop.x.unit} → {prop.y.unit}"
            status = "Set"
            note = prop.note or ""
        if (
            prop is not None
            and definition is not None
            and definition.note_recommended
            and not note
        ):
            status = "Set — note recommended"
        item = QTreeWidgetItem(
            (
                label or (definition.label if definition else path),
                kind,
                summary,
                unit,
                status,
                note,
            )
        )
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, "property")
        tooltip = path
        if definition and definition.description:
            tooltip += f"\n{definition.description}"
        if definition and definition.required_profiles:
            tooltip += "\nRequired for: " + ", ".join(definition.required_profiles)
        if definition and definition.note_guidance:
            tooltip += "\nNote: " + definition.note_guidance
        if note:
            tooltip += "\nRecorded note: " + note
        for column in range(self.property_tree.columnCount()):
            item.setToolTip(column, tooltip)
        if prop is None:
            foreground = QColor(
                "#a02020" if status.startswith("Required") else "#777777"
            )
            for column in range(self.property_tree.columnCount()):
                item.setForeground(column, QBrush(foreground))
        elif status.endswith("note recommended"):
            item.setForeground(4, QBrush(QColor("#9a6700")))
        return item

    def _refresh_validation(self) -> None:
        if self._draft is None:
            return
        result = (
            self.library.validate(self._draft.material_id, "manufacturing_bom")
            if self._draft == self.library.get(self._draft.material_id)
            else None
        )
        if result is None:
            try:
                from ..validation import validate_material

                result = validate_material(self._draft, "manufacturing_bom")
            except Exception as error:
                self.validation_label.setText(f"Validation error: {error}")
                return
        if result.valid:
            self.validation_label.setText("Manufacturing BOM: READY")
            self.validation_label.setStyleSheet(
                "background:#dff0d8; color:#2f6b2f; padding:5px; border-radius:3px;"
            )
        else:
            details = result.missing_required + result.warnings + result.unsupported
            self.validation_label.setText(
                "Manufacturing BOM: INCOMPLETE — " + "; ".join(details)
            )
            self.validation_label.setStyleSheet(
                "background:#fff2cc; color:#7a5b00; padding:5px; border-radius:3px;"
            )

    def _selected_property_path(self) -> str | None:
        item = self.property_tree.currentItem()
        if item is None:
            return None
        if item.data(0, Qt.ItemDataRole.UserRole + 1) != "property":
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _property_exists(self, path: str | None) -> bool:
        if self._draft is None or path is None:
            return False
        try:
            self._draft.get_property(path)
        except PropertyNotFoundError:
            return False
        return True

    def _edit_with_dialog(
        self, factory: Callable[[], ScalarEditorDialog | CurveEditorDialog]
    ) -> None:
        if self._draft is None or not self._editing:
            return
        dialog = factory()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        path, value = dialog.result_value()
        try:
            self._draft = self._draft.with_property(
                path, value, catalog=self.library.property_catalog
            )
        except Exception as error:
            QMessageBox.warning(self, "Invalid property", str(error))
            return
        self._refresh_properties()
        self._refresh_validation()

    def _add_scalar(self) -> None:
        self._edit_with_dialog(lambda: ScalarEditorDialog(self))

    def _add_curve(self) -> None:
        self._edit_with_dialog(lambda: CurveEditorDialog(self))

    def _edit_property(self) -> None:
        if self._draft is None:
            return
        path = self._selected_property_path()
        if path is None:
            return
        try:
            prop = self._draft.get_property(path)
        except PropertyNotFoundError:
            prop = None
        definition = self.library.property_catalog.property_definition(path)
        if prop is None:
            if not self._editing or definition is None:
                return
            if definition.kind == "scalar":
                self._edit_with_dialog(
                    lambda: ScalarEditorDialog(
                        self,
                        path=definition.path,
                        default_unit=definition.unit,
                        lock_path=True,
                        note_placeholder=definition.note_guidance,
                    )
                )
            else:
                self._edit_with_dialog(
                    lambda: CurveEditorDialog(
                        self,
                        path=definition.path,
                        material_name=self._draft.name,
                        x_name=definition.x_name,
                        x_unit=definition.x_unit,
                        y_name=definition.y_name,
                        y_unit=definition.y_unit,
                        lock_path=True,
                        note_placeholder=definition.note_guidance,
                    )
                )
            return
        if not self._editing:
            if isinstance(prop, ScalarProperty):
                ScalarEditorDialog(
                    self,
                    path=path,
                    prop=prop,
                    read_only=True,
                    note_placeholder=(definition.note_guidance if definition else ""),
                ).exec()
            else:
                CurveEditorDialog(
                    self,
                    path=path,
                    prop=prop,
                    read_only=True,
                    material_name=self._draft.name,
                    note_placeholder=(definition.note_guidance if definition else ""),
                ).exec()
            return
        if isinstance(prop, ScalarProperty):
            self._edit_with_dialog(
                lambda: ScalarEditorDialog(
                    self,
                    path=path,
                    prop=prop,
                    lock_path=definition is not None,
                    note_placeholder=(definition.note_guidance if definition else ""),
                )
            )
        else:
            self._edit_with_dialog(
                lambda: CurveEditorDialog(
                    self,
                    path=path,
                    prop=prop,
                    material_name=self._draft.name,
                    lock_path=definition is not None,
                    note_placeholder=(definition.note_guidance if definition else ""),
                )
            )

    def _remove_property(self) -> None:
        if self._draft is None or not self._editing:
            return
        path = self._selected_property_path()
        if path is None or not self._property_exists(path):
            return
        self._draft = self._draft.without_property(path)
        self._refresh_properties()
        self._refresh_validation()

    @staticmethod
    def _optional(text: str) -> str | None:
        value = text.strip()
        return value or None

    def _form_material(self) -> Material:
        if self._draft is None:
            raise ValueError("No material selected")
        identity = MaterialIdentity(
            name=self.name_edit.text().strip(),
            family=self.family_edit.text().strip(),
            manufacturer=self._optional(self.manufacturer_edit.text()),
            grade=self._optional(self.grade_edit.text()),
            description=self._optional(self.description_edit.text()),
            aliases=self._draft.identity.aliases,
            tags=self._draft.identity.tags,
        )
        provenance = Provenance(
            source_type=self._draft.provenance.source_type,
            reference=self._optional(self.reference_edit.text()),
            date=self._optional(self.provenance_date_edit.text()),
            notes=self._optional(self.provenance_notes_edit.text()),
            license=self._draft.provenance.license,
            license_url=self._draft.provenance.license_url,
            attribution=self._draft.provenance.attribution,
            source_manifest=self._draft.provenance.source_manifest,
        )
        metadata = VersionMetadata(
            author=self.author_edit.text().strip(),
            updated_at=_now(),
            change_note=self.change_note_edit.text().strip(),
        )
        return replace(
            self._draft,
            material_version=self.material_version_edit.text().strip(),
            identity=identity,
            provenance=provenance,
            version_metadata=metadata,
        )

    def _save_material(self) -> None:
        if self._draft is None or not self._editing:
            return
        try:
            material = self._form_material()
            self._draft = self.library.update(
                material, expected_version=self._loaded_version
            )
            self._loaded_version = self._draft.material_version
            self.reload_materials(select_id=self._draft.material_id)
            self.statusBar().showMessage("Material saved", 3000)
        except Exception as error:
            QMessageBox.warning(self, "Save failed", str(error))

    def _new_material(self) -> None:
        dialog = NewMaterialDialog(self, self.library.material_type_catalog)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            name, family, author = dialog.values()
            material = self.library.create_from_template(
                name=name, family=family, author=author
            )
            self.reload_materials(select_id=material.material_id)
            self._editing = True
            self._update_edit_controls()
        except Exception as error:
            QMessageBox.warning(self, "Create failed", str(error))

    def _duplicate_material(self) -> None:
        if self._draft is None:
            return
        dialog = NewMaterialDialog(self, self.library.material_type_catalog)
        dialog.name_edit.setText(f"{self._draft.name} copy")
        dialog.set_family(self._draft.identity.family)
        dialog.family_combo.setEnabled(False)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            name, _family, author = dialog.values()
            material = self.library.duplicate(
                self._draft.material_id, new_name=name, author=author
            )
            self.reload_materials(select_id=material.material_id)
            self._editing = True
            self._update_edit_controls()
        except Exception as error:
            QMessageBox.warning(self, "Duplicate failed", str(error))

    def _delete_material(self) -> None:
        if self._draft is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete material",
            f"Delete {self._draft.name!r}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.library.delete(self._draft.material_id)
            self._draft = None
            self._loaded_version = None
            self.reload_materials()
        except Exception as error:
            QMessageBox.warning(self, "Delete failed", str(error))

    def _import_material(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import canonical material", "", "Material JSON (*.json)"
        )
        if not filename:
            return
        try:
            material = self.library.import_json(filename)
            self.reload_materials(select_id=material.material_id)
        except Exception as error:
            QMessageBox.warning(self, "Import failed", str(error))

    def _export_material(self) -> None:
        if self._draft is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export canonical material",
            f"{self._draft.material_id.replace(':', '_')}.material.json",
            "Material JSON (*.json)",
        )
        if not filename:
            return
        try:
            self.library.export_json(self._draft.material_id, Path(filename))
            self.statusBar().showMessage("Material exported", 3000)
        except Exception as error:
            QMessageBox.warning(self, "Export failed", str(error))

    def _import_emsolution_material(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Import from EMSolution input.json",
            "",
            "EMSolution input JSON (*.json)",
        )
        if not filename:
            return
        try:
            adapter = EMSolutionInputAdapter()
            names = adapter.list_material_names(adapter.load_document(filename))
            if not names:
                raise ValueError(
                    "No 3D element material is registered in this input.json"
                )
            selected, accepted = QInputDialog.getItem(
                self,
                "Import from EMSolution input.json",
                "Material",
                list(names),
                0,
                False,
            )
            if not accepted:
                return
            dialog = NewMaterialDialog(self, self.library.material_type_catalog)
            dialog.setWindowTitle("Register EMSolution Material in User")
            dialog.name_edit.setText(selected)
            dialog.author_edit.setText("EMSolution Import")
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            new_name, family, author = dialog.values()
            material = adapter.register_from_file(
                self.library,
                filename,
                selected,
                family=family,
                author=author,
                new_name=new_name,
            )
            self.reload_materials(select_id=material.material_id)
            self.statusBar().showMessage("EMSolution material registered in User", 4000)
        except Exception as error:
            QMessageBox.warning(self, "EMSolution import failed", str(error))

    def _export_emsolution_material(self) -> None:
        if self._draft is None:
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select EMSolution input.json to update",
            "",
            "EMSolution input JSON (*.json)",
        )
        if not filename:
            return
        permeability, accepted = QInputDialog.getItem(
            self,
            "EMSolution export options",
            "Magnetic representation",
            ["auto", "linear", "bh_isotropy", "bh_anisotropy"],
            0,
            False,
        )
        if not accepted:
            return
        iron_loss, accepted = QInputDialog.getItem(
            self,
            "EMSolution export options",
            "Iron-loss representation",
            ["auto", "none", "isotropy", "anisotropy"],
            0,
            False,
        )
        if not accepted:
            return
        try:
            snapshot = EMSolutionInputAdapter().apply_to_file(
                filename,
                self._draft,
                selection=ExportSelection(
                    permeability=permeability,
                    iron_loss=iron_loss,
                ),
            )
            self.statusBar().showMessage(
                f"Exported snapshot; lineage saved for {snapshot.origin.material_id}",
                5000,
            )
        except Exception as error:
            QMessageBox.warning(self, "EMSolution export failed", str(error))
