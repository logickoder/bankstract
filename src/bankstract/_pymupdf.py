"""
Typed facade over pymupdf.

pymupdf ships no stubs, so every `pymupdf.X` access pattern in body code
trips strict type checkers (CLI tools silence this via the project config,
but VS Code Pylance can override it). Funnelling all access through this
module restricts the untyped surface to one file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pymupdf as _pymupdf  # type: ignore[import-untyped]

# cast bypasses pyright's reportAttributeAccessIssue since pymupdf has no stubs.
PDF_REDACT_IMAGE_NONE: Any = cast(Any, _pymupdf).PDF_REDACT_IMAGE_NONE


def open_doc(path: Path) -> Any:
    return _pymupdf.open(str(path))


def rect(x0: float, y0: float, x1: float, y1: float) -> Any:
    return _pymupdf.Rect(x0, y0, x1, y1)


def new_doc() -> Any:
    return _pymupdf.open()
