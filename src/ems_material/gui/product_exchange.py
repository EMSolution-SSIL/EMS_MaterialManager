"""Small Qt entry points embedded by product GUIs."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from qtpy.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QWidget

from ..adapters import EMotorSolutionProjectAdapter
from ..manager import MaterialManager

LIBRARY_ROOT_ENV = "EMS_MATERIAL_MANAGER_ROOT"
SETTINGS_PATH_ENV = "EMS_MATERIAL_MANAGER_SETTINGS_PATH"
SETTINGS_SCHEMA = "ems_material_product_exchange_settings"
SETTINGS_VERSION = "1.0"
EMOTOR_PREFERENCE_KEY = "Paths/material_manager_root"


def product_exchange_settings_path() -> Path:
    """Return the per-user location for product-integration preferences.

    The path is intentionally outside a project file: a machine-specific
    library location must not be serialized into an eMotorSolution project.
    ``SETTINGS_PATH_ENV`` is available for managed deployments and tests.
    """
    configured = os.environ.get(SETTINGS_PATH_ENV)
    if configured:
        return Path(configured).expanduser()
    app_data = Path(os.environ.get("APPDATA") or Path.home())
    return app_data / "EMSolution" / "ems_material_product_exchange.json"


def remembered_library_root(*, settings_path: str | Path | None = None) -> Path | None:
    """Return a valid previously selected Material Manager root, if any."""
    path = (
        Path(settings_path)
        if settings_path is not None
        else product_exchange_settings_path()
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(data, Mapping)
        or data.get("schema") != SETTINGS_SCHEMA
        or data.get("schema_version") != SETTINGS_VERSION
        or not isinstance(data.get("library_root"), str)
    ):
        return None
    root = Path(data["library_root"]).expanduser()
    return root if root.is_dir() else None


def remember_library_root(
    root: str | Path, *, settings_path: str | Path | None = None
) -> Path:
    """Atomically save a valid selected root for later product-GUI actions."""
    root_path = Path(root).expanduser()
    if not root_path.is_dir():
        raise ValueError(f"Material Manager root does not exist: {root_path}")
    path = (
        Path(settings_path)
        if settings_path is not None
        else product_exchange_settings_path()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "schema": SETTINGS_SCHEMA,
            "schema_version": SETTINGS_VERSION,
            "library_root": str(root_path.resolve()),
        },
        indent=2,
        ensure_ascii=False,
    )
    temporary_name: str | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(f"{payload}\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
        raise
    return root_path


def _preference_library_root(parent: QWidget | None) -> Path | None:
    """Read the optional eMotorSolution preference without importing its GUI."""
    settings = getattr(parent, "settings", None)
    value = getattr(settings, "value", None)
    if not callable(value):
        return None
    try:
        configured = value(EMOTOR_PREFERENCE_KEY, "")
    except (AttributeError, TypeError):
        return None
    if not configured:
        return None
    root = Path(str(configured)).expanduser()
    return root if root.is_dir() else None


def _remember_preference_library_root(parent: QWidget | None, root: Path) -> None:
    """Keep an eMotorSolution Preferences path aligned when available."""
    settings = getattr(parent, "settings", None)
    set_value = getattr(settings, "setValue", None)
    if not callable(set_value):
        return
    set_value(EMOTOR_PREFERENCE_KEY, str(root.resolve()))
    sync = getattr(settings, "sync", None)
    if callable(sync):
        sync()


def choose_library_root(
    parent: QWidget | None = None,
    *,
    settings_path: str | Path | None = None,
) -> Path | None:
    """Resolve root from environment, remembered preference, or one-time picker."""
    configured = os.environ.get(LIBRARY_ROOT_ENV)
    if configured:
        path = Path(configured).expanduser()
        if path.is_dir():
            return path
    preference = _preference_library_root(parent)
    if preference is not None:
        remember_library_root(preference, settings_path=settings_path)
        return preference
    remembered = remembered_library_root(settings_path=settings_path)
    if remembered is not None:
        _remember_preference_library_root(parent, remembered)
        return remembered
    selected = QFileDialog.getExistingDirectory(
        parent,
        "Select EMS Material Manager root",
        configured or "",
    )
    if not selected:
        return None
    root = remember_library_root(selected, settings_path=settings_path)
    _remember_preference_library_root(parent, root)
    return root


def _open_library(
    parent: QWidget | None, library_root: str | Path | None
) -> MaterialManager | None:
    root = (
        Path(library_root) if library_root is not None else choose_library_root(parent)
    )
    if root is None:
        return None
    return MaterialManager(root)


def select_emotorsolution_material(
    parent: QWidget | None = None,
    *,
    library_root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Select a master and return an editable eMotorSolution snapshot."""

    library = _open_library(parent, library_root)
    if library is None:
        return None
    materials = library.list()
    if not materials:
        QMessageBox.information(
            parent, "EMS Material Manager", "No materials are available."
        )
        return None
    labels = [
        f"{material.name}  [{material.family}]  ({material.material_id})"
        for material in materials
    ]
    label, accepted = QInputDialog.getItem(
        parent,
        "Import from material manager",
        "Material",
        labels,
        0,
        False,
    )
    if not accepted:
        return None
    material = materials[labels.index(label)]
    return EMotorSolutionProjectAdapter().export_material(material).embedded_payload()


def register_emotorsolution_material(
    parent: QWidget | None,
    payload: Mapping[str, Any],
    *,
    library_root: str | Path | None = None,
) -> Any | None:
    """Register an eMotorSolution material snapshot as a new User master."""

    library = _open_library(parent, library_root)
    if library is None:
        return None
    default_name = str(payload.get("name") or "Imported material")
    name, accepted = QInputDialog.getText(
        parent,
        "Export to material manager",
        "New User material name",
        text=default_name,
    )
    if not accepted or not name.strip():
        return None
    types = library.material_type_catalog.types
    labels = [f"{item.label} ({item.family})" for item in types]
    family_label, accepted = QInputDialog.getItem(
        parent,
        "Export to material manager",
        "Material type",
        labels,
        0,
        False,
    )
    if not accepted:
        return None
    family = types[labels.index(family_label)].family
    author, accepted = QInputDialog.getText(
        parent,
        "Export to material manager",
        "Author",
        text="eMotorSolution",
    )
    if not accepted or not author.strip():
        return None
    material = EMotorSolutionProjectAdapter().register_payload(
        library,
        payload,
        author=author.strip(),
        family=family,
        name=name.strip(),
        source_reference="eMotorSolution project material",
    )
    QMessageBox.information(
        parent,
        "EMS Material Manager",
        f"Registered {material.name!r} in User.",
    )
    return material
