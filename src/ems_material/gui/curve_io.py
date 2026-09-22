"""CSV helpers shared by the Qt curve editor and headless tests."""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path

from ..errors import ModelValidationError


def parse_curve_csv(text: str) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Parse the first two numeric CSV columns.

    Empty lines and ``#`` comments are ignored.  One non-numeric row before
    the first data row is treated as a header.  Non-numeric rows after data
    has started are rejected so malformed tables are never partially loaded.
    """

    x_values: list[float] = []
    y_values: list[float] = []
    header_skipped = False
    for line_number, row in enumerate(csv.reader(StringIO(text)), start=1):
        if not row or not any(cell.strip() for cell in row):
            continue
        if row[0].lstrip().startswith("#"):
            continue
        if len(row) < 2:
            raise ModelValidationError(
                f"Curve CSV row {line_number} must have at least two columns"
            )
        try:
            x_value = float(row[0].strip())
            y_value = float(row[1].strip())
        except ValueError as error:
            if not x_values and not header_skipped:
                header_skipped = True
                continue
            raise ModelValidationError(
                f"Curve CSV row {line_number} contains a non-numeric value"
            ) from error
        x_values.append(x_value)
        y_values.append(y_value)
    if len(x_values) < 2:
        raise ModelValidationError("A curve CSV requires at least two data rows")
    return tuple(x_values), tuple(y_values)


def load_curve_csv(path: str | Path) -> tuple[tuple[float, ...], tuple[float, ...]]:
    return parse_curve_csv(Path(path).read_text(encoding="utf-8-sig"))
