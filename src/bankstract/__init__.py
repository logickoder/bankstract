"""
bankstract — Nigerian bank PDF/XLSX statement → structured CSV/JSON + redacted bytes.

Public API (semver-stable): everything re-exported below. Anything
imported from a submodule prefixed with `_` is internal.
"""

__version__ = "0.16.1"

from ._api import (
    convert,
    detect,
    list_parsers,
    list_redactors,
    parse,
    reconcile_result,
    redact,
)
from ._progress import ProgressCallback, ProgressEvent, throttle
from .parsers.base import Parser
from .redactors.base import Redactor
from .schema import (
    CheckStatus,
    EmptyStatementError,
    EncryptedSourceError,
    Format,
    LayoutDriftError,
    ParseError,
    ParseResult,
    ReconciliationError,
    ReconciliationReport,
    RedactReport,
    RedactResult,
    StatementMetadata,
    Transaction,
)
from .writers.csv import write_csv
from .writers.json import write_json

__all__ = [
    "CheckStatus",
    "EmptyStatementError",
    "EncryptedSourceError",
    "Format",
    "LayoutDriftError",
    "Parser",
    "ParseError",
    "ParseResult",
    "ProgressCallback",
    "ProgressEvent",
    "ReconciliationError",
    "ReconciliationReport",
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
    "convert",
    "reconcile_result",
    "redact",
    "throttle",
    "write_csv",
    "write_json",
]
