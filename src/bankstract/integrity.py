"""Tamper signals for a statement. `inspect` runs reconciliation, then checks
the file itself (producer, revisions, fonts, overlays) and the rows (date
order, period). It reports evidence. It never says a statement is forged:
a forger who regenerates the file with the bank's own library and recomputes
every balance passes every check here.

`IntegritySignal.detail` quotes the statement: amounts, covered text, balances.
Show it to the person who owns the statement. Never write it to a log. Log
`code`, `severity`, `page` and `row`, which carry no statement text."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from ._api import SourceLike, normalize_source, parse
from ._isolate import DEFAULT_MEMORY_MB, DEFAULT_TIMEOUT, payload_of, run_isolated, source_of
from ._layout import AMOUNT_TOK
from ._pymupdf import BBox, PdfFill, PdfForensics, PdfSpan, pdf_forensics
from ._source import Source, rewind
from ._xlsx import sniff_format, xlsx_application
from .reconcile import reconcile_result
from .schema import EncryptedSourceError, ParseError, ParseResult, ReconciliationError

Severity = Literal["warn", "error"]
SignalCode = Literal[
    "unparseable",
    "checks_skipped",
    "reconciliation_failed",
    "incremental_update",
    "modified_after_create",
    "unexpected_producer",
    "unexpected_font",
    "font_size_outlier",
    "overlay_over_text",
    "date_out_of_order",
    "date_outside_period",
]


@dataclass(frozen=True)
class IntegritySignal:
    code: SignalCode
    severity: Severity
    # Quotes statement text. Not safe to log. See the module docstring.
    detail: str
    page: int | None = None  # 1-based
    row: int | None = None  # 0-based index into `transactions`


@dataclass(frozen=True)
class IntegrityReport:
    bank: str | None
    format_version: str | None
    signals: tuple[IntegritySignal, ...]

    @property
    def errors(self) -> tuple[IntegritySignal, ...]:
        return tuple(s for s in self.signals if s.severity == "error")

    @property
    def clean(self) -> bool:
        return not self.signals

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank": self.bank,
            "format_version": self.format_version,
            "signals": [asdict(s) for s in self.signals],
            "clean": self.clean,
        }


@dataclass(frozen=True)
class _Baseline:
    """What a bank's own export carries, read from raw statements. `None`
    skips that check for the bank."""

    pdf_producer: re.Pattern[str] | None = None
    pdf_fonts: frozenset[str] | None = None
    xlsx_application: re.Pattern[str] | None = None


# Producers match on the library name only, so a bank bumping iText 5.5.13 to
# 5.5.14 stays clean.
_BASELINES: dict[str, _Baseline] = {
    "fbn": _Baseline(
        pdf_producer=re.compile(r"^iTextSharp"),
        pdf_fonts=frozenset({"Helvetica", "Helvetica-Bold"}),
    ),
    "zenith": _Baseline(
        pdf_producer=re.compile(r"^iText\b"),
        pdf_fonts=frozenset({"Helvetica", "Helvetica-Bold"}),
    ),
    # opay's raw XLSX comes from Go Excelize. A copy re-saved through openpyxl
    # or Excel reads differently.
    "opay": _Baseline(
        pdf_producer=re.compile(r"^OpenPDF"),
        pdf_fonts=frozenset({"Poppins-Regular", "ArialMT"}),
        xlsx_application=re.compile(r"^Go Excelize"),
    ),
    # palmpay writes no producer. Any value means a tool re-saved the file.
    "palmpay": _Baseline(
        pdf_producer=re.compile(r"^$"),
        pdf_fonts=frozenset({"Helvetica", "Roboto-Medium"}),
    ),
}

# Amounts in one table column share a right edge. Fewer spans than this and
# the cluster is a summary block or stray text, not a column.
_MIN_COLUMN_SPANS = 5
_SIZE_TOLERANCE = 0.05
# A fill at or above this opacity dims what it covers past reading. Highlights
# sit below it. No later fill touches any text on the four banks' raw statements,
# so neither threshold is tuned to spare a genuine file.
_OPAQUE = 0.5
# Share of one glyph's box a later fill must cover. Per glyph, not per run: a
# cover that hides one digit leaves the run mostly uncovered.
_COVER_RATIO = 0.1
# Real statements top out near 300 text runs and 200 fills on a page. A crafted
# page can hold millions. Past these bounds a page is skipped and the report
# says so, so a page stuffed to switch the checks off leaves a warning.
_MAX_PAGE_OBJECTS = 2_000
# Span and fill pairs compared across the whole file. Opay's 58 pages
# use about 1.2 million.
_OVERLAY_BUDGET = 20_000_000


def inspect(
    source: SourceLike,
    *,
    bank: str | None = None,
    result: ParseResult | None = None,
    isolate: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    memory_mb: int | None = DEFAULT_MEMORY_MB,
) -> IntegrityReport:
    """Collect integrity signals for `source`. A file the parser rejects is
    itself a signal: `unparseable` is an error and the file checks still run
    when the bank is known. A password-protected file raises
    `EncryptedSourceError`, since nothing in it can be read.

    Pass `result` when you already parsed `source`. It skips the second parse,
    the dominant cost on a large statement. The result must come from this
    same source: the row checks read it, the file checks read `source`, and
    nothing here can tell if they disagree. `bank` must match `result.bank`.

    `isolate=True` runs the whole call in a child process. Use it on files you
    do not trust: a crafted PDF can cost gigabytes inside one mupdf call, which
    nothing in-process can stop. A child that passes `timeout` seconds, runs
    out of memory or dies raises `ResourceLimitError`, never a clean report.
    `memory_mb` is enforced on Linux only. Adds about 0.3s a call."""
    src = normalize_source(source)
    if not isolate:
        return _inspect(src, bank, result)
    return run_isolated(
        _inspect_job, payload_of(src), bank, result, timeout=timeout, memory_mb=memory_mb
    )


def _inspect_job(
    payload: Path | bytes, bank: str | None, result: ParseResult | None
) -> IntegrityReport:
    return _inspect(source_of(payload), bank, result)


def _inspect(src: Source, bank: str | None, result: ParseResult | None) -> IntegrityReport:
    if result is not None and bank is not None and result.bank != bank:
        raise ValueError(
            f"bank {bank!r} does not match the result's bank {result.bank!r}. "
            "The result came from another parser. Pass one of them, or make them agree."
        )
    if result is None:
        try:
            result = parse(src, bank=bank)
        except EncryptedSourceError:
            raise
        except ParseError as exc:
            name = exc.bank or bank
            signals = [
                IntegritySignal(
                    "unparseable",
                    "error",
                    f"{str(exc).rstrip('.')}. A damaged or edited file breaks the parser. "
                    "Ask for the original from the bank.",
                )
            ]
            signals.extend(_file_checked(src, name))
            return IntegrityReport(
                bank=name, format_version=exc.format_version, signals=_ordered(signals)
            )

    signals: list[IntegritySignal] = []
    signals.extend(_reconciliation(result))
    signals.extend(_rows(result))
    signals.extend(_file(src, result.bank))
    return IntegrityReport(
        bank=result.bank, format_version=result.format_version, signals=_ordered(signals)
    )


def _ordered(signals: list[IntegritySignal]) -> tuple[IntegritySignal, ...]:
    return tuple(sorted(signals, key=lambda s: s.severity != "error"))


def _file_checked(source: Source, bank: str | None) -> list[IntegritySignal]:
    # The file already failed to parse, so it may not open here either. Say so:
    # an empty list would read as "checked and clean".
    try:
        return _file(source, bank)
    except (ValueError, RuntimeError):
        return [
            IntegritySignal(
                "checks_skipped",
                "warn",
                "The file would not open for the revision, producer, font and overlay "
                "checks. They did not run. Ask for the original from the bank.",
            )
        ]


def _reconciliation(result: ParseResult) -> list[IntegritySignal]:
    try:
        reconcile_result(result)
    except ReconciliationError as exc:
        # The failing row is where the chain breaks. An edited amount can sit
        # on the row before it.
        return [IntegritySignal("reconciliation_failed", "error", str(exc), row=exc.row_index)]
    return []


def _rows(result: ParseResult) -> list[IntegritySignal]:
    signals: list[IntegritySignal] = []
    # Days, not timestamps: a real opay export lists a transfer and its
    # reversal 15 seconds out of order on the same day.
    days = [t.date.date() for t in result.transactions]
    direction = 0
    for i in range(1, len(days)):
        step = (days[i] > days[i - 1]) - (days[i] < days[i - 1])
        if not step:
            continue
        if not direction:
            direction = step
        elif step != direction:
            signals.append(
                IntegritySignal(
                    "date_out_of_order",
                    "warn",
                    f"row {i} breaks the day order. Rows should run oldest to newest or the reverse.",
                    row=i,
                )
            )
            break

    meta = result.metadata
    if meta and meta.statement_period_start and meta.statement_period_end:
        start, end = meta.statement_period_start.date(), meta.statement_period_end.date()
        outside = [i for i, d in enumerate(days) if not start <= d <= end]
        if outside:
            signals.append(
                IntegritySignal(
                    "date_outside_period",
                    "warn",
                    f"{len(outside)} rows fall outside {start} to {end}. First is row {outside[0]}.",
                    row=outside[0],
                )
            )
    return signals


def _file(source: Source, bank: str | None) -> list[IntegritySignal]:
    # No `bank` skips the baseline comparisons only. Revisions, overlays and
    # sizes need none, and a file that dodges detection must not dodge them.
    rewind(source)
    if sniff_format(source) == "xlsx":
        return _xlsx_signals(source, bank)
    return _pdf_signals(pdf_forensics(source), bank)


def _xlsx_signals(source: Source, bank: str | None) -> list[IntegritySignal]:
    baseline = _BASELINES.get(bank or "")
    expected = baseline.xlsx_application if baseline else None
    application = xlsx_application(source)
    if expected is None or expected.match(application):
        return []
    return [
        IntegritySignal(
            "unexpected_producer",
            "warn",
            f"written by {application!r}, not the {bank} export tool. "
            "A tool re-saved this file. Ask for the original from the bank.",
        )
    ]


def _pdf_signals(forensics: PdfForensics, bank: str | None) -> list[IntegritySignal]:
    signals: list[IntegritySignal] = []

    if forensics.revisions > 1:
        signals.append(
            IntegritySignal(
                "incremental_update",
                "error",
                f"{forensics.revisions} revisions in the file. A bank export has one. "
                "Something appended changes after it was generated.",
            )
        )

    created, modified = forensics.creation_date, forensics.mod_date
    # Date strings read D:YYYYMMDDHHMMSS then a zone. Compare the clock part.
    if created and modified and created[2:16] != modified[2:16]:
        signals.append(
            IntegritySignal(
                "modified_after_create",
                "warn",
                f"created {created!r}, modified {modified!r}. A bank export sets both once.",
            )
        )

    baseline = _BASELINES.get(bank or "") or _Baseline()
    producer = baseline.pdf_producer
    if producer is not None and not producer.match(forensics.producer):
        signals.append(
            IntegritySignal(
                "unexpected_producer",
                "warn",
                f"produced by {forensics.producer!r}, not the {bank} export tool. "
                "A tool re-saved this file. Ask for the original from the bank.",
            )
        )

    allowed = baseline.pdf_fonts
    if allowed is not None:
        extra = sorted(forensics.fonts - allowed)
        if extra:
            signals.append(
                IntegritySignal(
                    "unexpected_font",
                    "warn",
                    f"fonts {extra} are not in a {bank} export. Text was added with another font.",
                )
            )

    covers = [f for f in forensics.fills if _is_cover(f)]
    crowded = {
        page
        for counts in (Counter(s.page for s in forensics.spans), Counter(f.page for f in covers))
        for page, n in counts.items()
        if n > _MAX_PAGE_OBJECTS
    }
    spans = tuple(s for s in forensics.spans if s.page not in crowded)
    covers = [f for f in covers if f.page not in crowded]

    signals.extend(_size_outliers(spans))
    overlays, over_budget = _overlays(spans, covers)
    signals.extend(overlays)
    if forensics.unreadable:
        signals.append(
            IntegritySignal(
                "checks_skipped",
                "warn",
                f"{forensics.unreadable} text runs or fills have coordinates that are not "
                "numbers. The size and overlay checks left them out. Inspect the file by eye.",
            )
        )
    skipped = crowded | over_budget | set(forensics.oversized)
    if skipped:
        signals.append(
            IntegritySignal(
                "checks_skipped",
                "warn",
                f"{len(skipped)} pages hold more text or drawing than the size and overlay "
                "checks will compare. A bank export stays near a few hundred objects a page. "
                "Inspect those pages by eye.",
                page=min(skipped),
            )
        )
    return signals


def _size_outliers(spans: tuple[PdfSpan, ...]) -> list[IntegritySignal]:
    money = [s for s in spans if AMOUNT_TOK.fullmatch(s.text.strip())]
    by_edge: dict[int, list[PdfSpan]] = defaultdict(list)
    for span in money:
        by_edge[round(span.bbox[2])].append(span)
    columns = {k: v for k, v in by_edge.items() if len(v) >= _MIN_COLUMN_SPANS}

    modes = {
        k: Counter(round(s.size, 2) for s in v).most_common(1)[0][0] for k, v in columns.items()
    }
    # Where each column sits on each page. A value typed over a cell is often
    # left-aligned, so its right edge misses the column. Its position doesn't.
    areas: dict[int, list[tuple[int, BBox]]] = defaultdict(list)
    for key, members in columns.items():
        for page in {m.page for m in members}:
            areas[page].append((key, _union([m.bbox for m in members if m.page == page])))

    def column_of(span: PdfSpan) -> int | None:
        edge = round(span.bbox[2])
        if edge in columns:
            return edge
        # A longer value runs past the column's right edge, so test overlap, not
        # the centre. The best overlap wins when neighbouring columns both touch.
        cy = (span.bbox[1] + span.bbox[3]) / 2
        best: int | None = None
        best_overlap = 0.0
        for key, area in areas.get(span.page, ()):
            if not area[1] <= cy <= area[3]:
                continue
            overlap = min(span.bbox[2], area[2]) - max(span.bbox[0], area[0])
            if overlap > best_overlap:
                best, best_overlap = key, overlap
        return best

    signals: list[IntegritySignal] = []
    for span in money:
        key = column_of(span)
        if key is not None and abs(span.size - modes[key]) > _SIZE_TOLERANCE:
            signals.append(
                IntegritySignal(
                    "font_size_outlier",
                    "warn",
                    f"{span.text.strip()!r} is {span.size:g}pt in a column of {modes[key]:g}pt.",
                    page=span.page,
                )
            )
    return signals


def _is_cover(fill: PdfFill) -> bool:
    # Any colour. A forger matches the row background, and on all four banks'
    # raw statements no fill is drawn over earlier text at all.
    return fill.opacity >= _OPAQUE and _area(fill.bbox) > 0


def _overlays(
    spans: tuple[PdfSpan, ...], covers: list[PdfFill]
) -> tuple[list[IntegritySignal], set[int]]:
    """Text a later opaque fill covers, and the pages left out because the
    comparisons would pass `_OVERLAY_BUDGET`."""
    texts: dict[int, list[PdfSpan]] = defaultdict(list)
    for span in spans:
        if span.text.strip():
            texts[span.page].append(span)
    fills: dict[int, list[PdfFill]] = defaultdict(list)
    for fill in covers:
        fills[fill.page].append(fill)

    signals: list[IntegritySignal] = []
    skipped: set[int] = set()
    spent = 0
    for page, page_fills in sorted(fills.items()):
        page_spans = texts.get(page, [])
        cost = len(page_fills) * len(page_spans)
        if spent + cost > _OVERLAY_BUDGET:
            skipped.add(page)
            continue
        spent += cost
        seen: set[int] = set()
        for fill in page_fills:
            for span in page_spans:
                if span.seqno in seen or span.seqno >= fill.seqno:
                    continue
                if _overlap(span.bbox, fill.bbox) > 0 and _hides_a_glyph(span, fill):
                    seen.add(span.seqno)
                    signals.append(
                        IntegritySignal(
                            "overlay_over_text",
                            "error",
                            f"{span.text.strip()!r} sits under a filled box drawn after it. "
                            "The visible value may differ from the one in the file.",
                            page=page,
                        )
                    )
    return signals, skipped


def _hides_a_glyph(span: PdfSpan, fill: PdfFill) -> bool:
    for box in span.glyphs or (span.bbox,):
        area = _area(box)
        if area > 0 and _overlap(box, fill.bbox) >= _COVER_RATIO * area:
            return True
    return False


def _area(b: BBox) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _overlap(a: BBox, b: BBox) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def _union(boxes: list[BBox]) -> BBox:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )
