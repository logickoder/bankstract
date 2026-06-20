"""
bankstract — Nigerian bank PDF/XLSX statement → structured CSV/JSON + redacted bytes.

Public API (semver-stable): everything re-exported below. Anything
imported from a submodule prefixed with `_` is internal.
"""

__version__ = "0.13.0"

from ._api import detect, list_parsers, list_redactors, parse, parse_to, redact
from .parsers.base import Parser
from .redactors.base import Redactor
from .schema import (
    EmptyStatementError,
    EncryptedSourceError,
    Format,
    LayoutDriftError,
    ParseError,
    ParseResult,
    ReconciliationError,
    RedactReport,
    RedactResult,
    StatementMetadata,
    Transaction,
)
from .writers.csv import write_csv
from .writers.json import write_json

__all__ = [
    "EmptyStatementError",
    "EncryptedSourceError",
    "Format",
    "LayoutDriftError",
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
    "parse_to",
    "redact",
    "write_csv",
    "write_json",
]
