from .base import Parser

_REGISTRY: dict[str, Parser] = {}


def register(parser: Parser) -> Parser:
    key = parser.bank.lower()
    if key in _REGISTRY:
        raise ValueError(f"parser already registered for bank '{key}'")
    _REGISTRY[key] = parser
    return parser


def get(bank: str) -> Parser:
    try:
        return _REGISTRY[bank.lower()]
    except KeyError as exc:
        raise KeyError(f"no parser registered for bank '{bank}'") from exc


def all_parsers() -> dict[str, Parser]:
    return dict(_REGISTRY)


from . import fbn as fbn  # noqa: E402
from . import palmpay as palmpay  # noqa: E402
