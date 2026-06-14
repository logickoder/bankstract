from pathlib import Path
from typing import Any

from bankstract._pymupdf import new_doc, open_doc
from bankstract.redactors import all_redactors, get


def test_redactor_registered() -> None:
    redactor = get("zenith")
    assert redactor.bank == "zenith"
    assert "zenith" in all_redactors()


def _synthetic_zenith_pdf(path: Path) -> Path:
    """Minimal Zenith-shape statement using deliberately-fake identifiers.

    No real person, business, or address may appear here — see CLAUDE.md
    directive 3.
    """
    doc: Any = new_doc()
    page: Any = doc.new_page()

    # Bank-info header (kept by the redactor — it's the detect() marker).
    page.insert_text((240, 50), "ZENITH BANK PLC", fontsize=10)

    # Account info header (label-anchored redaction).
    page.insert_text((50, 90), "ACCOUNT NAME: FOO BAR", fontsize=10)
    page.insert_text((50, 110), "1A Placeholder Lane", fontsize=10)
    page.insert_text((50, 130), "QUUX CITY", fontsize=10)
    page.insert_text((50, 150), "NA NA", fontsize=10)
    page.insert_text((250, 110), "CURRENCY: NGN", fontsize=10)
    page.insert_text((250, 130), "ACCOUNT No.: 1234567890", fontsize=10)

    # Column header — anchors the body sweep.
    page.insert_text((50, 200), "DATE", fontsize=10)
    page.insert_text((111, 200), "DESCRIPTION", fontsize=10)
    page.insert_text((260, 200), "DEBIT", fontsize=10)
    page.insert_text((335, 200), "CREDIT", fontsize=10)
    page.insert_text((410, 200), "VALUE DATE", fontsize=10)
    page.insert_text((470, 200), "BALANCE", fontsize=10)

    # tx rows with counterparty names baked into the description.
    page.insert_text((50, 230), "01/01/2026", fontsize=10)
    page.insert_text((111, 230), "NIP CR ACME CORP /TEST", fontsize=10)
    page.insert_text((321, 230), "0.00", fontsize=10)
    page.insert_text((382, 230), "1,000.00", fontsize=10)
    page.insert_text((413, 230), "01/01/2026", fontsize=10)
    page.insert_text((508, 230), "1,000.00", fontsize=10)

    doc.save(str(path))
    doc.close()
    return path


def test_redactor_round_trip_strips_known_pii(tmp_path: Path) -> None:
    src = _synthetic_zenith_pdf(tmp_path / "in.pdf")
    dst = tmp_path / "out.pdf"

    redactor = get("zenith")
    report = redactor.redact(src, dst)
    assert report.bank == "zenith"
    assert report.pages == 1
    assert report.redactions > 0

    out: Any = open_doc(dst)
    try:
        text: str = out[0].get_text()
    finally:
        out.close()

    for leak in ("FOO", "BAR", "ACME", "CORP", "QUUX", "Placeholder", "1234567890"):
        assert leak not in text, f"{leak!r} leaked into redacted output:\n{text}"

    # Bank identifier must survive — the parser keys on it for auto-detect.
    assert "ZENITH BANK" in text
