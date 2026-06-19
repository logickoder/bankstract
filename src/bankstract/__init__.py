"""
bankstract — Nigerian bank PDF/XLSX statement → structured CSV/JSON + redacted bytes.

Public API (semver-stable): everything re-exported below. Anything
imported from a submodule prefixed with `_` is internal.
"""

__version__ = "0.11.0"

from ._api import detect, list_parsers, list_redactors, parse, redact
from .parsers.base import Parser
from .redactors.base import Redactor
from .schema import (
    Format,
    ParseError,
    ParseResult,
    ReconciliationError,
    RedactReport,
    RedactResult,
    StatementMetadata,
    Transaction,
)

__all__ = [
    "Format",
    "Parser",
    "ParseError",
    "ParseResult",
    "ReconciliationError",
    "RedactReport",
    "RedactResult",
    "Redactor",
    "StatementMetadata",
    "Transaction",
    "__version__",
    "detect",
    "list_parsers",
    "list_redactors",
    "parse",
    "redact",
]
