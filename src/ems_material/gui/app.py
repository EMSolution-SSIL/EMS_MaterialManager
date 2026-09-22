"""Command-line entry point for the common Material Manager."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from ..errors import GuiDependencyError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EMS common Material Manager")
    parser.add_argument(
        "--library-root",
        type=Path,
        default=Path.home() / ".ems" / "materials",
        help="Directory containing user .material.json files",
    )
    parser.add_argument(
        "--admin-edit-reference",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from qtpy.QtWidgets import QApplication
    except ImportError as error:  # pragma: no cover - depends on installation
        raise GuiDependencyError(
            "Material Manager requires the 'gui' extra: "
            "pip install ems-material-manager[gui]"
        ) from error

    from ..manager import MaterialManager
    from .qt import MaterialManagerWindow

    app = QApplication.instance() or QApplication(sys.argv)
    window = MaterialManagerWindow(
        MaterialManager(
            args.library_root,
            allow_reference_updates=args.admin_edit_reference,
        )
    )
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
