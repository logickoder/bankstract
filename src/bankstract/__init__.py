"""
bankstract — Nigerian bank PDF/XLSX statement → structured CSV/JSON + redacted bytes.

Public API (semver-stable): everything re-exported below. Anything
imported from a submodule prefixed with `_` is internal.
"""

__version__ = "0.18.2"

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
from .integrity import IntegrityReport, IntegritySignal, inspect
from .parsers.base import Parser
from .redactors.base import Redactor
from .schema import (
    CheckStatus,
    EmptyStatementError,
    EncryptedSourceError,
    Format,
    LayoutDriftError,
    OutputFormat,
    ParseError,
    ParseResult,
    ReconciledParseResult,
    ReconciliationError,
    ReconciliationReport,
    RedactReport,
    RedactResult,
    ResourceLimitError,
    StatementMetadata,
    Transaction,
)
from .writers.csv import write_csv
from .writers.json import write_json
from .writers.serialize import serialize

__all__ = [
    "CheckStatus",
    "EmptyStatementError",
    "EncryptedSourceError",
    "Format",
    "IntegrityReport",
    "IntegritySignal",
    "LayoutDriftError",
    "OutputFormat",
    "Parser",
    "ParseError",
    "ParseResult",
    "ReconciledParseResult",
    "ProgressCallback",
    "ProgressEvent",
    "ReconciliationError",
    "ReconciliationReport",
    "RedactReport",
    "RedactResult",
    "Redactor",
    "ResourceLimitError",
    "StatementMetadata",
    "Transaction",
    "__version__",
    "detect",
    "inspect",
    "list_parsers",
    "list_redactors",
    "parse",
    "convert",
    "reconcile_result",
    "redact",
    "serialize",
    "throttle",
    "write_csv",
    "write_json",
]
