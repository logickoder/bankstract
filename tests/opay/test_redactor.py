from pathlib import Path
from typing import Any

from bankstract._pymupdf import new_doc, open_doc
from bankstract.redactors import all_redactors, get


def test_redactor_registered() -> None:
    redactor = get("opay")
    assert redactor.bank == "opay"
    assert "opay" in all_redactors()


def _synthetic_opay_pdf(path: Path) -> Path:
    """Minimal OPay-shape statement using deliberately-fake identifiers.

    No real person, business, or address may appear here — see CLAUDE.md
    directive 3.
    """
    doc: Any = new_doc()
    page: Any = doc.new_page()

    # Bank-info header (kept by the redactor — these are detect() markers).
    page.insert_text((241, 99), "Account Statement", fontsize=10)
    page.insert_text((262, 116), "Generated on 18 Jun 2026 17:49:13", fontsize=8)

    # Account holder block — redactor blanks the row beneath these labels.
    page.insert_text((66, 144), "Account Name", fontsize=8)
    page.insert_text((224, 144), "Account Number", fontsize=8)
    page.insert_text((383, 144), "Address", fontsize=8)
    page.insert_text((66, 154), "FOO BAR QUUX", fontsize=8)
    page.insert_text((224, 154), "1234567890", fontsize=8)
    page.insert_text((383, 154), "1A Placeholder Lane", fontsize=8)

    # Wallet Account Period line (detect marker).
    page.insert_text((66, 210), "Wallet Account", fontsize=8)
    page.insert_text((224, 210), "Period: 01 May 2023 - 17 Jun 2026", fontsize=8)

    # Summary block (detect markers: Debit(₦), Credit(₦), Balance After).
    page.insert_text((66, 240), "Opening Balance Total Debit Debit Count", fontsize=8)
    page.insert_text((66, 252), "100.00 1,000.00 5", fontsize=8)
    page.insert_text((66, 275), "Closing Balance Total Credit Credit Count", fontsize=8)
    page.insert_text((66, 287), "200.00 1,100.00 3", fontsize=8)

    # Column-header row anchors the body sweep.
    page.insert_text((381, 325), "Balance After(", fontsize=8)
    page.insert_text((71, 330), "Trans. Time", fontsize=8)
    page.insert_text((131, 330), "Value Date", fontsize=8)
    page.insert_text((178, 330), "Description", fontsize=8)
    page.insert_text((304, 330), "Debit(₦)", fontsize=8)
    page.insert_text((342, 330), "Credit(₦)", fontsize=8)
    page.insert_text((422, 330), "Channel", fontsize=8)
    page.insert_text((478, 330), "Transaction Reference", fontsize=8)

    # tx row with counterparty names baked into description column.
    page.insert_text((71, 365), "02 May 2023 08:21:07", fontsize=8)
    page.insert_text((131, 365), "02 May 2023", fontsize=8)
    page.insert_text((178, 365), "Transfer from ACME BAR", fontsize=8)
    page.insert_text((178, 375), "QUUX | OPay | 813****706", fontsize=8)
    page.insert_text((304, 365), "--", fontsize=8)
    page.insert_text((342, 365), "1,000.00", fontsize=8)
    page.insert_text((381, 365), "1,100.00", fontsize=8)
    page.insert_text((422, 365), "Mobile", fontsize=8)
    page.insert_text((478, 365), "0902670000000000000001", fontsize=8)

    doc.save(str(path))
    doc.close()
    return path


def test_redactor_round_trip_strips_known_pii(tmp_path: Path) -> None:
    src = _synthetic_opay_pdf(tmp_path / "in.pdf")
    dst = tmp_path / "out.pdf"

    redactor = get("opay")
    result = redactor.redact(src)
    dst.write_bytes(result.data)
    report = result.report
    assert report.bank == "opay"
    assert report.pages == 1
    assert report.redactions > 0

    out: Any = open_doc(dst)
    try:
        text: str = out[0].get_text()
    finally:
        out.close()

    for leak in (
        "FOO",
        "BAR",
        "QUUX",
        "ACME",
        "Placeholder",
        "1234567890",
        "0902670000000000000001",
    ):
        assert leak not in text, f"{leak!r} leaked into redacted output:\n{text}"

    # Detect markers must survive — the parser keys on these for auto-detect.
    # The synthetic font lacks ₦ glyph (pymupdf default helv), so "Debit(₦)"
    # comes through as "Debit(·)" here. The real fixture is rendered with a
    # ₦-supporting font, so this only matters for the synthetic round trip.
    for keep in ("Wallet Account", "Balance After"):
        assert keep in text, f"{keep!r} stripped — would break detect()"
