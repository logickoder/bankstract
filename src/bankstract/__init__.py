"""
bankstract — Nigerian bank PDF statement → structured CSV/JSON.

Public API (semver-stable): everything re-exported below. Anything
imported from a submodule prefixed with `_` is internal.
"""

__version__ = "0.5.0"

from ._api import detect, list_parsers, parse
from .parsers.base import Parser
from .schema import (
    ParseError,
    ParseResult,
    ReconciliationError,
    StatementMetadata,
    Transaction,
)

__all__ = [
    "Parser",
    "ParseError",
    "ParseResult",
    "ReconciliationError",
    "StatementMetadata",
    "Transaction",
    "__version__",
    "detect",
    "list_parsers",
    "parse",
]
