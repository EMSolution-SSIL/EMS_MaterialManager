"""Optional Qt material manager.

Importing :mod:`ems_material.gui` does not require Qt.  The optional GUI
dependencies are loaded only when ``MaterialManagerWindow`` or ``main`` is
requested.
"""

from __future__ import annotations

from typing import Any

__all__ = ["MaterialManagerWindow", "main"]


def __getattr__(name: str) -> Any:
    if name == "MaterialManagerWindow":
        from .qt import MaterialManagerWindow

        return MaterialManagerWindow
    if name == "main":
        from .app import main

        return main
    raise AttributeError(name)
