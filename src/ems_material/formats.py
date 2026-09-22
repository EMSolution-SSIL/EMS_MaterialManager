"""Load versioned external format profiles bundled with the package."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


def load_format_profile(filename: str) -> dict[str, Any]:
    resource = files("ems_material").joinpath("format_profiles", filename)
    return json.loads(resource.read_text(encoding="utf-8"))
