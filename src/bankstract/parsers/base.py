from abc import ABC, abstractmethod
from pathlib import Path

from ..schema import ParseResult


class Parser(ABC):
    bank: str

    @abstractmethod
    def detect(self, pdf_path: Path) -> bool: ...

    @abstractmethod
    def parse(self, pdf_path: Path) -> ParseResult: ...
