from .base import Redactor
from .base import RedactReport as RedactReport

_REGISTRY: dict[str, Redactor] = {}


def register(redactor: Redactor) -> Redactor:
    key = redactor.bank.lower()
    if key in _REGISTRY:
        raise ValueError(f"redactor already registered for bank '{key}'")
    _REGISTRY[key] = redactor
    return redactor


def get(bank: str) -> Redactor:
    try:
        return _REGISTRY[bank.lower()]
    except KeyError as exc:
        raise KeyError(f"no redactor registered for bank '{bank}'") from exc


def all_redactors() -> dict[str, Redactor]:
    return dict(_REGISTRY)


from . import fbn as fbn  # noqa: E402
from . import opay as opay  # noqa: E402
from . import palmpay as palmpay  # noqa: E402
from . import zenith as zenith  # noqa: E402
