import math
import re
import time
import tracemalloc
import zipfile
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from bankstract._pymupdf import (  # pyright: ignore[reportPrivateUsage]
    PdfFill,
    PdfForensics,
    PdfSpan,
    _finite,
    _revisions,
    new_doc,
    open_doc,
    pdf_forensics,
)
from bankstract._xlsx import xlsx_application
from bankstract.integrity import (  # pyright: ignore[reportPrivateUsage]
    IntegrityReport,
    _overlays,
    _pdf_signals,
    _rows,
    _size_outliers,
    inspect,
)
from bankstract.schema import EncryptedSourceError

from ._fixtures import fixture_params, parsed
from ._forge import (
    OPAY_XLSX,
    ZENITH,
    append_revision,
    balance_span,
    column_span,
    retype,
    sample,
)

# The redactor rewrites fonts and the xlsx writer, so a committed sample can't
# carry its bank's file signature. Raw `_local` files are the authentic baseline.
_REDACTION_ARTIFACTS = {"unexpected_font", "unexpected_producer"}


def _codes(report: IntegrityReport) -> set[str]:
    return {s.code for s in report.signals}


@pytest.mark.parametrize(("bank", "path"), fixture_params())
def test_fixtures_raise_no_errors(bank: str, path: Path) -> None:
    report = inspect(path, bank=bank, result=parsed(bank, path))
    assert not report.errors, report.errors
    if "_local" in path.parts:
        assert report.clean, report.signals
    else:
        assert _codes(report) <= _REDACTION_ARTIFACTS, report.signals


def _forge(
    tmp_path: Path,
    edit: Callable[[Any, Path], None],
    *,
    bank: str = "zenith",
    reparse: bool = False,
) -> IntegrityReport:
    """Forge a copy of `bank`'s sample. A forgery that leaves the rows alone
    reuses the sample's cached parse. One that changes them sets `reparse`."""
    path = sample(bank)
    out = tmp_path / "forged.pdf"
    doc: Any = open_doc(path)
    try:
        edit(doc, out)
    finally:
        doc.close()
    return inspect(out, bank=bank, result=None if reparse else parsed(bank, path))


def _set_metadata(**fields: str) -> Callable[[Any, Path], None]:
    def edit(doc: Any, out: Path) -> None:
        doc.set_metadata({**doc.metadata, **fields})
        doc.save(str(out))

    return edit


def test_incremental_save_is_an_error(tmp_path: Path) -> None:
    report = _forge(tmp_path, lambda _doc, out: append_revision(ZENITH, out))
    assert "incremental_update" in _codes(report)
    assert report.errors


def test_foreign_producer_warns(tmp_path: Path) -> None:
    report = _forge(tmp_path, _set_metadata(producer="Microsoft Word"))
    assert _codes(report) == {"unexpected_producer"}


def test_white_box_over_amount_is_an_error(tmp_path: Path) -> None:
    def edit(doc: Any, out: Path) -> None:
        retype(doc, balance_span(), cover=True)
        doc.save(str(out))

    report = _forge(tmp_path, edit, reparse=True)
    assert "overlay_over_text" in _codes(report)
    assert "reconciliation_failed" in _codes(report)


def _retyped(**kwargs: Any) -> Callable[[Any, Path], None]:
    def edit(doc: Any, out: Path) -> None:
        retype(doc, balance_span(), **kwargs)
        doc.save(str(out))

    return edit


def test_retyped_amount_breaks_the_balance_chain(tmp_path: Path) -> None:
    # Same font, same size, original text removed. No file signal is left, so
    # reconciliation is the only check that fires.
    report = _forge(tmp_path, _retyped(), reparse=True)
    assert _codes(report) == {"reconciliation_failed"}
    failure = next(s for s in report.signals if s.code == "reconciliation_failed")
    assert failure.row is not None


def test_retyped_amount_in_another_size_warns(tmp_path: Path) -> None:
    report = _forge(tmp_path, _retyped(fontsize=9), reparse=True)
    outliers = [s for s in report.signals if s.code == "font_size_outlier"]
    assert [s.detail for s in outliers] == ["'9,999.00' is 9pt in a column of 7pt."]


def test_retyped_palmpay_credit_in_another_size_warns(tmp_path: Path) -> None:
    # Palmpay prints credits with a leading +. A check that matched only plain
    # amounts skipped every one of them.
    span = column_span(sample("palmpay"), prefix="+")

    def edit(doc: Any, out: Path) -> None:
        retype(doc, span, fontsize=10)
        doc.save(str(out))

    report = _forge(tmp_path, edit, bank="palmpay")
    outliers = [s for s in report.signals if s.code == "font_size_outlier"]
    assert [s.detail for s in outliers] == ["'9,999.00' is 10pt in a column of 8pt."]


def test_retyped_opay_amount_in_another_size_warns(tmp_path: Path) -> None:
    # Opay's columns are narrow right-edge buckets. A longer value typed from the
    # original's left edge ends past the column, so its centre falls outside it.
    span = column_span(sample("opay"), prefix="")

    def edit(doc: Any, out: Path) -> None:
        retype(doc, span, fontsize=span.size * 2)
        doc.save(str(out))

    report = _forge(tmp_path, edit, bank="opay")
    outliers = [s for s in report.signals if s.code == "font_size_outlier"]
    assert [s.detail for s in outliers] == [f"'9,999.00' is 9pt in a column of {span.size:g}pt."]


def test_amount_font_outside_the_bank_baseline_warns(tmp_path: Path) -> None:
    report = _forge(tmp_path, _retyped(fontname="tiro"), reparse=True)
    assert "unexpected_font" in _codes(report)


def test_summary_block_is_not_a_column() -> None:
    # A lone larger amount outside any table column is a total, not an edit.
    doc: Any = new_doc()
    page: Any = doc.new_page()
    for i in range(6):
        page.insert_text((400, 100 + i * 12), f"{i + 1},000.00", fontsize=7)
    page.insert_text((60, 40), "5,000.00", fontsize=11)
    forensics = pdf_forensics(BytesIO(doc.tobytes()))
    doc.close()
    assert _size_outliers(forensics.spans) == []


def test_openpyxl_resave_of_opay_xlsx_warns() -> None:
    # The committed sample went through the redactor, which writes with
    # openpyxl. A real export reads "Go Excelize".
    report = inspect(OPAY_XLSX, bank="opay")
    assert _codes(report) == {"unexpected_producer"}


def _with_dates(bank: str, path: Path, dates: list[datetime]) -> Any:
    result = parsed(bank, path)
    txs = [
        t.model_copy(update={"date": d}) for t, d in zip(result.transactions, dates, strict=False)
    ]
    return replace(result, transactions=txs[: len(dates)])


def test_day_order_break_warns() -> None:
    base = datetime(2026, 5, 1)
    days = [0, 1, 2, 1, 3]
    result = _with_dates("zenith", ZENITH, [base + timedelta(days=d) for d in days])
    signals = [s for s in _rows(result) if s.code == "date_out_of_order"]
    assert [s.row for s in signals] == [3]


@pytest.mark.parametrize("order", [[0, 1, 2, 3], [3, 2, 1, 0]])
def test_either_direction_is_fine(order: list[int]) -> None:
    base = datetime(2026, 5, 1)
    result = _with_dates("zenith", ZENITH, [base + timedelta(days=d) for d in order])
    assert [s for s in _rows(result) if s.code == "date_out_of_order"] == []


def test_same_day_reversal_is_fine() -> None:
    # A real opay export lists a transfer and its reversal 15 seconds apart.
    day = datetime(2026, 6, 6)
    stamps = [day.replace(hour=18, minute=13, second=5), day.replace(hour=18, minute=12, second=50)]
    result = _with_dates("zenith", ZENITH, stamps)
    assert [s for s in _rows(result) if s.code == "date_out_of_order"] == []


def test_row_outside_statement_period_warns() -> None:
    result = parsed("zenith", ZENITH)
    meta = result.metadata
    assert meta is not None
    assert meta.statement_period_start and meta.statement_period_end
    late = result.transactions[0].model_copy(
        update={"date": meta.statement_period_end + timedelta(days=30)}
    )
    forged = replace(result, transactions=[late, *result.transactions[1:]])
    signals = [s for s in _rows(forged) if s.code == "date_outside_period"]
    assert [s.row for s in signals] == [0]


def _blank_pdf(tmp_path: Path) -> Path:
    doc: Any = new_doc()
    doc.new_page().insert_text((60, 60), "FOO BAR", fontsize=10)
    out = tmp_path / "blank.pdf"
    doc.save(str(out))
    doc.close()
    return out


def test_unparseable_with_known_bank_still_runs_file_checks(tmp_path: Path) -> None:
    report = inspect(_blank_pdf(tmp_path), bank="zenith")
    assert report.bank == "zenith"
    assert {"unparseable", "unexpected_producer"} <= _codes(report)
    assert report.signals[0].code == "unparseable"
    assert report.signals[0].severity == "error"


def test_unparseable_without_a_bank_reports_only_the_failure(tmp_path: Path) -> None:
    report = inspect(_blank_pdf(tmp_path))
    assert report.bank is None
    assert _codes(report) == {"unparseable"}


def test_file_checks_run_without_a_detected_bank(tmp_path: Path) -> None:
    # Revisions, overlays and sizes need no baseline. A file that dodges
    # detection must not dodge them too.
    forged = tmp_path / "forged.pdf"
    append_revision(_blank_pdf(tmp_path), forged)
    report = inspect(forged)
    assert report.bank is None
    assert {"unparseable", "incremental_update"} <= _codes(report)


def test_unreadable_objects_are_reported_not_dropped() -> None:
    forensics = PdfForensics("", "", "", 1, (), (), unreadable=3)
    signals = _pdf_signals(forensics, None)
    assert [(s.code, s.severity, s.page) for s in signals] == [("checks_skipped", "warn", None)]
    assert "3" in signals[0].detail


def test_non_finite_coordinates_are_not_finite() -> None:
    assert not _finite((0.0, 0.0, math.inf, 1.0))
    assert not _finite((math.nan, 0.0, 1.0, 1.0))
    assert _finite((0.0, 0.0, 1.0, 1.0))


def test_file_that_will_not_open_for_the_file_checks_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_source: Any) -> None:
        raise RuntimeError("cannot open")

    monkeypatch.setattr("bankstract.integrity.pdf_forensics", fail)
    report = inspect(_blank_pdf(tmp_path), bank="zenith")
    assert _codes(report) == {"unparseable", "checks_skipped"}


def test_encrypted_source_still_raises(tmp_path: Path) -> None:
    doc: Any = new_doc()
    doc.new_page()
    out = tmp_path / "locked.pdf"
    doc.save(str(out), encryption=3, user_pw="x", owner_pw="y")
    doc.close()
    with pytest.raises(EncryptedSourceError):
        inspect(out, bank="zenith")


def test_modified_date_differing_from_created_warns(tmp_path: Path) -> None:
    report = _forge(tmp_path, _set_metadata(modDate="D:20260620101010+01'00'"))
    assert _codes(report) == {"modified_after_create"}


# Every bank's PDF baseline has to fire on a forged copy of its own sample. The
# redactor leaves producers alone on these four, so the forgeries are real.
BANKS = ("fbn", "opay", "palmpay", "zenith")


@pytest.mark.parametrize("bank", BANKS)
def test_every_bank_flags_a_foreign_producer(tmp_path: Path, bank: str) -> None:
    report = _forge(tmp_path, _set_metadata(producer="Microsoft Word"), bank=bank)
    flagged = [s for s in report.signals if s.code == "unexpected_producer"]
    assert len(flagged) == 1
    assert "Microsoft Word" in flagged[0].detail


@pytest.mark.parametrize(
    ("bank", "producer"),
    [("fbn", "iTextSharp 5.9.0"), ("zenith", "iText 2.1.8 by 1T3XT"), ("opay", "OpenPDF 2.1.0")],
)
def test_producer_version_bump_stays_clean(tmp_path: Path, bank: str, producer: str) -> None:
    report = _forge(tmp_path, _set_metadata(producer=producer), bank=bank)
    assert "unexpected_producer" not in _codes(report)


@pytest.mark.parametrize("bank", BANKS)
def test_every_bank_flags_an_incremental_save(tmp_path: Path, bank: str) -> None:
    report = _forge(tmp_path, lambda _doc, out: append_revision(sample(bank), out), bank=bank)
    assert "incremental_update" in _codes(report)
    assert report.errors


@pytest.mark.parametrize("bank", BANKS)
def test_every_bank_flags_a_font_outside_its_baseline(tmp_path: Path, bank: str) -> None:
    def edit(doc: Any, out: Path) -> None:
        doc[0].insert_text((20, 20), "x", fontsize=6, fontname="tiro")
        doc.save(str(out))

    report = _forge(tmp_path, edit, bank=bank)
    flagged = [s for s in report.signals if s.code == "unexpected_font"]
    assert len(flagged) == 1
    assert "Times-Roman" in flagged[0].detail


@pytest.mark.parametrize("bank", BANKS)
def test_every_bank_flags_a_white_box_over_text(tmp_path: Path, bank: str) -> None:
    # Cover the last text run on page 1 so the box lands after it in draw order.
    target = [s for s in pdf_forensics(sample(bank)).spans if s.page == 1 and s.text.strip()][-1]

    def edit(doc: Any, out: Path) -> None:
        doc[0].draw_rect(target.bbox, color=None, fill=(1, 1, 1))
        doc.save(str(out))

    report = _forge(tmp_path, edit, bank=bank)
    covered = [s for s in report.signals if s.code == "overlay_over_text"]
    assert any(target.text.strip() in s.detail for s in covered), report.signals
    assert report.errors


def _opay_xlsx_written_by(tmp_path: Path, application: str) -> Path:
    out = tmp_path / "statement.xlsx"
    with zipfile.ZipFile(OPAY_XLSX) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "docProps/app.xml":
                data = re.sub(
                    rb"<Application>[^<]*</Application>",
                    f"<Application>{application}</Application>".encode(),
                    data,
                )
            dst.writestr(item, data)
    return out


def test_opay_xlsx_from_its_own_writer_is_clean(tmp_path: Path) -> None:
    report = inspect(_opay_xlsx_written_by(tmp_path, "Go Excelize"), bank="opay")
    assert report.clean, report.signals


@pytest.mark.parametrize("application", ["Microsoft Excel", "LibreOffice"])
def test_opay_xlsx_from_another_writer_warns(tmp_path: Path, application: str) -> None:
    report = inspect(_opay_xlsx_written_by(tmp_path, application), bank="opay")
    flagged = [s for s in report.signals if s.code == "unexpected_producer"]
    assert len(flagged) == 1
    assert application in flagged[0].detail


def test_opay_xlsx_writer_version_bump_stays_clean(tmp_path: Path) -> None:
    report = inspect(_opay_xlsx_written_by(tmp_path, "Go Excelize 2.9.0"), bank="opay")
    assert report.clean, report.signals


def test_stray_eof_text_is_not_a_revision(tmp_path: Path) -> None:
    # "%%EOF" can sit in a string. A revision is a `startxref <offset>` section.
    doc: Any = new_doc()
    doc.new_page()
    doc.set_metadata({"title": "report %%EOF end"})
    out = tmp_path / "stray.pdf"
    doc.save(str(out), deflate=False, garbage=0)
    doc.close()
    assert out.read_bytes().count(b"%%EOF") == 2
    assert pdf_forensics(out).revisions == 1


def test_embedded_uncompressed_pdf_counts_as_a_revision_on_purpose(tmp_path: Path) -> None:
    # Known false positive, kept deliberately. Excluding sections inside a stream
    # body would trust the file's `/Length`. A forger can wrap a real final tail
    # in a fake stream, and a reader finds that tail from the end of the file.
    doc: Any = new_doc()
    doc.new_page()
    inner = ZENITH.read_bytes()
    doc.embfile_add("inner.pdf", inner)
    # pymupdf deflates attachments. Store this one as is.
    stream = next(
        x
        for x in range(1, doc.xref_length())
        if doc.xref_is_stream(x) and doc.xref_stream(x)[:5] == b"%PDF-"
    )
    doc.update_stream(stream, inner, compress=False)
    out = tmp_path / "carrier.pdf"
    doc.save(str(out), deflate=False, garbage=0)
    doc.close()
    assert _revisions(out.read_bytes()) == 2


def test_forged_tail_inside_a_fake_stream_is_still_counted() -> None:
    # The evasion the test above guards against.
    fake_stream = b"99 0 obj\n<< /Length 100000 >>\nstream\n"
    forged_tail = b"xref\n0 1\n0000000000 65535 f \ntrailer\n<< /Size 2 >>\nstartxref\n116\n%%EOF\n"
    assert _revisions(_LINEARIZED_BASE + fake_stream + forged_tail) == 2


def test_revision_written_without_prev_is_still_counted(tmp_path: Path) -> None:
    # A forger who appends a full xref and drops `/Prev` hides the old one from a
    # chain walk. The section is still in the file.
    forged = tmp_path / "forged.pdf"
    append_revision(ZENITH, forged)
    raw = forged.read_bytes()
    assert re.search(rb"/Prev\s+\d+", raw)
    assert _revisions(re.sub(rb"/Prev\s+\d+", b"", raw)) == 2


# A one-revision file for the forged-tail test.
_LINEARIZED_BASE = (
    b"%PDF-1.4\n2 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"xref\n0 1\n0000000000 65535 f \ntrailer\n<< /Size 2 >>\n"
    b"startxref\n20\n%%EOF\n"
)

# Shaped like a real linearized file: `/Linearized` in the first 1024 bytes, a
# first-page section at the top (`startxref 0`) and the main one at the end.
_LINEARIZED = (
    b"%PDF-1.4\n1 0 obj\n<< /Linearized 1 /L 600 /N 1 >>\nendobj\n"
    b"xref\n0 1\n0000000000 65535 f \ntrailer\n<< /Size 2 /Prev 400 >>\n"
    b"startxref\n0\n%%EOF\n"
    b"2 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"xref\n0 1\n0000000000 65535 f \ntrailer\n<< /Size 2 >>\n"
    b"startxref\n116\n%%EOF\n"
)


def test_linearized_file_is_one_revision() -> None:
    assert _revisions(_LINEARIZED) == 1


def test_update_appended_to_a_linearized_file_is_a_second_revision() -> None:
    update = (
        b"3 0 obj\n<< /Type /Page >>\nendobj\n"
        b"xref\n0 1\n0000000000 65535 f \ntrailer\n<< /Size 4 /Prev 400 >>\n"
        b"startxref\n500\n%%EOF\n"
    )
    assert _revisions(_LINEARIZED + update) == 2


def test_forged_linearized_marker_does_not_hide_a_revision(tmp_path: Path) -> None:
    # Only the section a linearized file writes at the top is discounted. A
    # comment that says "/Linearized" is not that section.
    forged = tmp_path / "forged.pdf"
    append_revision(ZENITH, forged)
    raw = forged.read_bytes()
    assert _revisions(raw) == 2
    header_end = raw.index(b"\n") + 1
    marked = raw[:header_end] + b"% /Linearized\n" + raw[header_end:]
    assert _revisions(marked) == 2
    # Adding the top section too nets out: one extra keyword, one discount.
    both = raw[:header_end] + b"% /Linearized\n% startxref 0\n" + raw[header_end:]
    assert _revisions(both) == 2


def test_comment_between_startxref_and_offset_is_still_counted() -> None:
    # PDF treats a comment as whitespace, so a reader still finds this section.
    commented = b"startxref %c\n116\n%%EOF\n"
    assert _revisions(_LINEARIZED_BASE + commented) == 2


def test_revision_without_eof_marker_is_still_counted(tmp_path: Path) -> None:
    # A reader finds the last `startxref`. A forger can drop the marker after it.
    forged = tmp_path / "forged.pdf"
    append_revision(ZENITH, forged)
    data = forged.read_bytes()
    head, _, tail = data.rpartition(b"%%EOF")
    forged.write_bytes(head + tail)
    assert forged.read_bytes().count(b"%%EOF") == 1
    assert pdf_forensics(forged).revisions == 2


@pytest.mark.parametrize(
    "inner",
    [
        "Go Excelize",
        "<![CDATA[Go Excelize]]>",
        "&#71;o Excelize",
        "Go&#32;Excelize",
        "<![CDATA[Go ]]>Excelize",
    ],
)
def test_application_value_is_decoded(tmp_path: Path, inner: str) -> None:
    out = tmp_path / "decoded.xlsx"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(
            "docProps/app.xml", f"<Properties><Application>{inner}</Application></Properties>"
        )
    assert xlsx_application(out) == "Go Excelize"


def test_cdata_content_is_not_unescaped(tmp_path: Path) -> None:
    out = tmp_path / "literal.xlsx"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("docProps/app.xml", "<Application><![CDATA[A &amp; B]]></Application>")
    assert xlsx_application(out) == "A &amp; B"


def test_entity_declarations_are_not_expanded(tmp_path: Path) -> None:
    bomb = '<!DOCTYPE x [<!ENTITY a "' + "A" * 1000 + '">]><Application>&a;&a;&a;</Application>'
    out = tmp_path / "entity.xlsx"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("docProps/app.xml", bomb)
    assert xlsx_application(out) == "&a;&a;&a;"


def test_huge_white_box_costs_nothing_and_is_still_flagged() -> None:
    # A box this size put billions of cells in the old grid and exhausted memory.
    span = PdfSpan(1, "9,999.00", "Helvetica", 7.0, (100.0, 100.0, 140.0, 108.0), 1)
    fill = PdfFill(1, (-1e9, -1e9, 1e9, 1e9), 1.0, 2)
    start = time.perf_counter()
    signals, skipped = _overlays((span,), [fill])
    assert time.perf_counter() - start < 1
    assert [s.code for s in signals] == ["overlay_over_text"]
    assert skipped == set()


def _cover_last_run(
    tmp_path: Path, fill: tuple[float, float, float] = (1, 1, 1), opacity: float = 1.0
) -> IntegrityReport:
    target = [s for s in pdf_forensics(ZENITH).spans if s.page == 1 and s.text.strip()][-1]

    def edit(doc: Any, out: Path) -> None:
        doc[0].draw_rect(target.bbox, color=None, fill=fill, fill_opacity=opacity)
        doc.save(str(out))

    return _forge(tmp_path, edit)


@pytest.mark.parametrize(
    "fill",
    [(1, 1, 1), (0.94, 0.94, 0.94), (0.9, 0.9, 0.9), (0.98, 0.96, 0.9), (0, 0, 0)],
    ids=["white", "off-white", "light-grey", "cream", "black"],
)
def test_a_cover_of_any_colour_is_an_error(
    tmp_path: Path, fill: tuple[float, float, float]
) -> None:
    # A forger matches the row background. Only white used to be flagged.
    report = _cover_last_run(tmp_path, fill)
    assert "overlay_over_text" in _codes(report)
    assert report.errors


def _cover_glyph(
    tmp_path: Path, which: str, opacity: float = 1.0, fill: tuple[float, float, float] = (1, 1, 1)
) -> IntegrityReport:
    """Cover part of one amount: its first glyph, its left 40%, or all of it."""
    span = balance_span()
    x0, y0, x1, y1 = span.bbox
    width = x1 - x0
    right = {"first": x0 + width / 9 + 0.2, "left40": x0 + 0.4 * width, "all": x1 + 1}[which]

    def edit(doc: Any, out: Path) -> None:
        doc[span.page - 1].draw_rect(
            (x0 - 0.2, y0, right, y1), color=None, fill=fill, fill_opacity=opacity
        )
        doc.save(str(out))

    return _forge(tmp_path, edit)


@pytest.mark.parametrize("which", ["first", "left40", "all"])
def test_covering_part_of_an_amount_is_an_error(tmp_path: Path, which: str) -> None:
    # Hide one digit and type another over it. The run is mostly uncovered.
    assert "overlay_over_text" in _codes(_cover_glyph(tmp_path, which))


@pytest.mark.parametrize("opacity", [0.89, 0.7, 0.55])
def test_a_nearly_opaque_cover_is_an_error(tmp_path: Path, opacity: float) -> None:
    assert "overlay_over_text" in _codes(_cover_glyph(tmp_path, "all", opacity, (0.95, 0.95, 0.95)))


def test_a_translucent_highlight_is_not_a_cover(tmp_path: Path) -> None:
    assert "overlay_over_text" not in _codes(_cover_last_run(tmp_path, (1, 1, 0), 0.3))


def test_page_past_the_object_cap_is_skipped_and_said_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A page stuffed with junk must not switch the checks off in silence.
    assert "overlay_over_text" in _codes(_cover_last_run(tmp_path))
    monkeypatch.setattr("bankstract.integrity._MAX_PAGE_OBJECTS", 50)
    report = _cover_last_run(tmp_path)
    assert "overlay_over_text" not in _codes(report)
    skipped = [s for s in report.signals if s.code == "checks_skipped"]
    assert [(s.severity, s.page) for s in skipped] == [("warn", 1)]


def test_overlay_work_past_the_budget_is_skipped_and_said_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("bankstract.integrity._OVERLAY_BUDGET", 10)
    report = _cover_last_run(tmp_path)
    assert "overlay_over_text" not in _codes(report)
    assert [s.page for s in report.signals if s.code == "checks_skipped"] == [1]


def test_oversized_app_part_is_not_inflated_whole(tmp_path: Path) -> None:
    # 20MB of zeros deflates to about 20KB. Reading the part whole and slicing
    # afterwards would inflate all of it first.
    bomb = tmp_path / "bomb.xlsx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "docProps/app.xml", b"<Application>Go Excelize</Application>" + b"0" * 20_000_000
        )

    tracemalloc.start()
    try:
        application = xlsx_application(bomb)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert application == "Go Excelize"
    assert peak < 5_000_000


def test_result_skips_the_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("parse() ran although a result was passed")

    expected = inspect(ZENITH, bank="zenith")
    monkeypatch.setattr("bankstract.integrity.parse", fail)
    reused = inspect(ZENITH, result=parsed("zenith", ZENITH))
    assert reused == expected


def test_result_still_gets_file_checks(tmp_path: Path) -> None:
    # The row checks read the result. The file checks read the source.
    forged = tmp_path / "forged.pdf"
    append_revision(ZENITH, forged)
    report = inspect(forged, result=parsed("zenith", ZENITH))
    assert _codes(report) == {"incremental_update"}


def test_result_with_another_bank_is_rejected() -> None:
    with pytest.raises(ValueError, match="does not match the result's bank"):
        inspect(ZENITH, bank="fbn", result=parsed("zenith", ZENITH))


def test_result_with_a_matching_bank_is_accepted() -> None:
    assert inspect(ZENITH, bank="zenith", result=parsed("zenith", ZENITH)).clean


def test_to_dict_carries_clean() -> None:
    report = inspect(ZENITH, bank="zenith", result=parsed("zenith", ZENITH))
    assert report.to_dict() == {
        "bank": "zenith",
        "format_version": report.format_version,
        "signals": [],
        "clean": True,
    }
