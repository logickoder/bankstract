from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RedactReport:
    bank: str
    pages: int = 0
    redactions: int = 0
    audit: list[tuple[int, list[str]]] = field(default_factory=list)


class Redactor(ABC):
    bank: str

    @abstractmethod
    def redact(self, src: Path, dst: Path) -> RedactReport: ...
