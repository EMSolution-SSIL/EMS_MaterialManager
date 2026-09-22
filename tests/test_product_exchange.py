"""Tests for persistent Material Manager root selection in product GUIs."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ems_material.gui.product_exchange import (
    EMOTOR_PREFERENCE_KEY,
    LIBRARY_ROOT_ENV,
    choose_library_root,
    remember_library_root,
    remembered_library_root,
)


class ProductExchangeSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.library_root = self.root / "materials"
        self.library_root.mkdir()
        self.settings_path = self.root / "settings" / "product_exchange.json"

    def test_remembered_root_is_reused_without_a_picker(self) -> None:
        remember_library_root(self.library_root, settings_path=self.settings_path)

        with (
            patch.dict(os.environ, {LIBRARY_ROOT_ENV: ""}, clear=False),
            patch(
                "ems_material.gui.product_exchange.QFileDialog.getExistingDirectory"
            ) as picker,
        ):
            selected = choose_library_root(settings_path=self.settings_path)

        self.assertEqual(selected.resolve(), self.library_root.resolve())
        picker.assert_not_called()
        self.assertEqual(
            remembered_library_root(settings_path=self.settings_path).resolve(),
            self.library_root.resolve(),
        )

    def test_environment_root_overrides_remembered_preference(self) -> None:
        remembered = self.root / "remembered"
        configured = self.root / "configured"
        remembered.mkdir()
        configured.mkdir()
        remember_library_root(remembered, settings_path=self.settings_path)

        with patch.dict(os.environ, {LIBRARY_ROOT_ENV: str(configured)}, clear=False):
            selected = choose_library_root(settings_path=self.settings_path)

        self.assertEqual(selected.resolve(), configured.resolve())

    def test_first_picker_selection_is_remembered(self) -> None:
        with (
            patch.dict(os.environ, {LIBRARY_ROOT_ENV: ""}, clear=False),
            patch(
                "ems_material.gui.product_exchange.QFileDialog.getExistingDirectory",
                return_value=str(self.library_root),
            ),
        ):
            selected = choose_library_root(settings_path=self.settings_path)

        self.assertEqual(selected.resolve(), self.library_root.resolve())
        self.assertEqual(
            remembered_library_root(settings_path=self.settings_path).resolve(),
            self.library_root.resolve(),
        )

    def test_emotorsolution_preference_overrides_remembered_path(self) -> None:
        remembered = self.root / "remembered"
        configured = self.root / "configured"
        remembered.mkdir()
        configured.mkdir()
        remember_library_root(remembered, settings_path=self.settings_path)

        class Settings:
            def value(self, key: str, default: str) -> str:
                return str(configured) if key == EMOTOR_PREFERENCE_KEY else default

        class Parent:
            settings = Settings()

        with (
            patch.dict(os.environ, {LIBRARY_ROOT_ENV: ""}, clear=False),
            patch(
                "ems_material.gui.product_exchange.QFileDialog.getExistingDirectory"
            ) as picker,
        ):
            selected = choose_library_root(Parent(), settings_path=self.settings_path)

        self.assertEqual(selected.resolve(), configured.resolve())
        picker.assert_not_called()
        self.assertEqual(
            remembered_library_root(settings_path=self.settings_path).resolve(),
            configured.resolve(),
        )

    def test_first_picker_selection_updates_emotorsolution_preference(self) -> None:
        stored: dict[str, str] = {}

        class Settings:
            def value(self, _key: str, default: str) -> str:
                return default

            def setValue(self, key: str, value: str) -> None:
                stored[key] = value

            def sync(self) -> None:
                stored["synced"] = "yes"

        class Parent:
            settings = Settings()

        with (
            patch.dict(os.environ, {LIBRARY_ROOT_ENV: ""}, clear=False),
            patch(
                "ems_material.gui.product_exchange.QFileDialog.getExistingDirectory",
                return_value=str(self.library_root),
            ),
        ):
            choose_library_root(Parent(), settings_path=self.settings_path)

        self.assertEqual(
            Path(stored[EMOTOR_PREFERENCE_KEY]).resolve(), self.library_root.resolve()
        )
        self.assertEqual(stored["synced"], "yes")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
