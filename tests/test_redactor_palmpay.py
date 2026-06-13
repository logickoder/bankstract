from pathlib import Path
from typing import Any

from bankstract._layout import Word, group_by_baseline
from bankstract._pymupdf import new_doc, open_doc
from bankstract.redactors import all_redactors, get
from bankstract.redactors.palmpay import (
    ANCHOR_PHRASES,
    HEADER_CHROME,
    NARRATION_PHRASES,
    _narration_span,
)


def test_redactor_registered() -> None:
    redactor = get("palmpay")
    assert redactor.bank == "palmpay"
    assert "palmpay" in all_redactors()


def test_narration_phrases_normalized_lowercase() -> None:
    for phrase in NARRATION_PHRASES:
        assert phrase == phrase.lower()
    assert "cashbox interest" in NARRATION_PHRASES
    assert "stamp duty" in NARRATION_PHRASES
    assert "card payment-web" in NARRATION_PHRASES


def test_header_chrome_includes_replacement_tokens() -> None:
    for tok in ("REDACTED", "PARTY", "TEST", "USER"):
        assert tok in HEADER_CHROME


def test_anchor_phrases_are_lowercase_comparable() -> None:
    for anchor in ANCHOR_PHRASES:
        assert anchor.split()


def _w(x0: float, top: float, x1: float, text: str) -> Word:
    return Word(text=text, x0=x0, top=top, x1=x1, bottom=top + 10)


def test_narration_span_single_row_transaction() -> None:
    from bankstract._layout import classify

    row = [
        _w(10, 100, 60, "06/13/2026"),
        _w(65, 100, 105, "06:38:19"),
        _w(110, 100, 125, "AM"),
        _w(140, 100, 175, "CashBox"),
        _w(180, 100, 215, "Interest"),
        _w(300, 100, 330, "+3.79"),
        _w(400, 100, 470, "u835z3qh9b90y"),
    ]
    classes = [classify(w.text) for w in row]
    span = _narration_span(classes)
    assert span is not None
    assert span == (3, 5)
    assert [w.text for w in row[span[0] : span[1]]] == ["CashBox", "Interest"]


def test_narration_span_returns_none_for_continuation() -> None:
    from bankstract._layout import classify

    row = [_w(140, 120, 175, "ACME"), _w(180, 120, 200, "CORP")]
    classes = [classify(w.text) for w in row]
    assert _narration_span(classes) is None


def test_group_by_baseline_merges_close_y_baselines() -> None:
    # PalmPay's date (top=259.9) and narration (top=262.5) sit ~2.6pt apart but
    # render on the same visual row. Grouping must merge them.
    words = [
        Word(text="06/13/2026", x0=10, top=259.9, x1=60, bottom=270.0),
        Word(text="CashBox", x0=140, top=262.5, x1=175, bottom=270.5),
        Word(text="Interest", x0=180, top=262.5, x1=215, bottom=270.5),
    ]
    rows = group_by_baseline(words, tol=4.0)
    assert len(rows) == 1
    assert [w.text for w in rows[0]] == ["06/13/2026", "CashBox", "Interest"]


def _synthetic_palmpay_pdf(path: Path) -> Path:
    """Synthetic statement using deliberately-fake placeholder identifiers.

    No real person, business, or address may appear in test data — even if it
    would only be redacted out, having it in the repo is a privacy hit by
    itself (charter directive 3).
    """
    doc: Any = new_doc()
    page: Any = doc.new_page()
    page.insert_text((50, 50), "Name", fontsize=10)
    page.insert_text((100, 50), "FOO", fontsize=10)
    page.insert_text((50, 70), "Phone Number 081 1111 2222", fontsize=10)
    page.insert_text((50, 90), "Address 1A Placeholder Lane", fontsize=10)

    page.insert_text(
        (50, 130), "06/13/2026 06:38:19 AM CashBox Interest +3.79 u835z3qh9b90y", fontsize=10
    )
    page.insert_text(
        (50, 150), "06/12/2026 07:35:09 PM Send to ACME CORP -1000.00 abc1234567xyz", fontsize=10
    )
    page.insert_text(
        (50, 170), "06/11/2026 07:00:00 PM Card Payment-WEB -4100.00 w135y916f200", fontsize=10
    )
    page.insert_text((140, 190), "Send to BAR", fontsize=10)
    page.insert_text(
        (50, 210), "06/10/2026 06:00:00 PM -50000.00 z999a888b777", fontsize=10
    )
    page.insert_text((140, 230), "QUUX LTD", fontsize=10)
    doc.save(str(path))
    doc.close()
    return path


def test_redactor_round_trip_strips_known_pii(tmp_path: Path) -> None:
    src = _synthetic_palmpay_pdf(tmp_path / "in.pdf")
    dst = tmp_path / "out.pdf"

    redactor = get("palmpay")
    report = redactor.redact(src, dst)
    assert report.bank == "palmpay"
    assert report.pages == 1
    assert report.redactions > 0

    out: Any = open_doc(dst)
    try:
        text: str = out[0].get_text()
    finally:
        out.close()

    for leak in ("FOO", "ACME", "CORP", "Placeholder", "1111", "2222", "BAR", "QUUX"):
        assert leak not in text, f"{leak!r} leaked into redacted output:\n{text}"

    for kept in ("CashBox", "Interest", "Card", "Payment-WEB", "Send to"):
        assert kept in text, f"{kept!r} missing from redacted output:\n{text}"
