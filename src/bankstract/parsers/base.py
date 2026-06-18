from abc import ABC, abstractmethod

from .._pdfplumber import PdfSource
from ..schema import ParseResult


class Parser(ABC):
    bank: str

    @abstractmethod
    def detect(self, source: PdfSource) -> bool: ...

    @abstractmethod
    def parse(self, source: PdfSource) -> ParseResult: ...

    def detect_confidence(self, source: PdfSource) -> float:
        """Override to disambiguate when multiple parsers' detect() may match.
        Default: 1.0 on positive detection, 0.0 otherwise. Callers
        (`bankstract.cli.auto`, `bankstract.detect`) pick the max-scoring
        parser, falling back to None when every score is 0."""
        return 1.0 if self.detect(source) else 0.0
