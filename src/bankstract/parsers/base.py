from abc import ABC, abstractmethod

from .._source import Source
from ..schema import Format, ParseResult


class Parser(ABC):
    bank: str

    # Formats the parser knows how to handle. Default PDF-only — banks that
    # also expose XLSX (OPay, Kuda, Stanbic, …) override with both. CLI +
    # lib API skip parsers whose `supported_formats` doesn't include the
    # sniffed input format.
    supported_formats: tuple[Format, ...] = ("pdf",)

    @abstractmethod
    def detect(self, source: Source) -> bool: ...

    @abstractmethod
    def parse(self, source: Source) -> ParseResult: ...

    def detect_confidence(self, source: Source) -> float:
        """Override to disambiguate when multiple parsers' detect() may match.
        Default: 1.0 on positive detection, 0.0 otherwise. Callers
        (`bankstract.cli.auto`, `bankstract.detect`) pick the max-scoring
        parser, falling back to None when every score is 0."""
        return 1.0 if self.detect(source) else 0.0
