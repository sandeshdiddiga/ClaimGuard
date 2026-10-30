"""Upload limits: size, type by content (not just the name), page count, pixel count; nothing leaked."""

import io
import logging
from pathlib import Path

import pytest
from PIL import Image

from app.extract import ExtractionError, extract_bill, extract_eob
from app.uploads import MAX_UPLOAD_BYTES, UploadError, check_upload

ROOT = Path(__file__).resolve().parent.parent
MAYA = ROOT / "samples" / "maya" / "bill.pdf"


def png(path: Path, size: tuple[int, int] = (20, 20)) -> Path:
    Image.new("RGB", size, "white").save(path, format="PNG")
    return path


def test_the_sample_pdf_is_accepted() -> None:
    assert check_upload(MAYA) == "pdf"


def test_a_png_and_a_jpeg_are_accepted(tmp_path: Path) -> None:
    assert check_upload(png(tmp_path / "a.png")) == "png"
    Image.new("RGB", (20, 20)).save(tmp_path / "b.jpg", format="JPEG")
    assert check_upload(tmp_path / "b.jpg") == "jpeg"


def test_a_file_over_the_size_limit_is_rejected(tmp_path: Path) -> None:
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.4\n" + b"0" * MAX_UPLOAD_BYTES)
    with pytest.raises(UploadError, match="larger than"):
        check_upload(big)


def test_an_empty_file_is_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "e.pdf"
    empty.write_bytes(b"")
    with pytest.raises(UploadError, match="empty"):
        check_upload(empty)


@pytest.mark.parametrize("name", ["x.exe", "x.html", "x.svg", "x.txt", "x"])
def test_other_file_types_are_rejected(name: str, tmp_path: Path) -> None:
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4 hello")
    with pytest.raises(UploadError, match="unsupported file type"):
        check_upload(path)


def test_the_content_must_match_the_extension(tmp_path: Path) -> None:
    fake_pdf = tmp_path / "bill.pdf"
    fake_pdf.write_bytes(b"MZ\x90\x00 not a pdf")
    with pytest.raises(UploadError, match="does not match"):
        check_upload(fake_pdf)
    wrong = tmp_path / "bill2.pdf"
    png(wrong)  # a PNG named .pdf
    with pytest.raises(UploadError, match="does not match"):
        check_upload(wrong)


def test_a_corrupt_pdf_is_rejected(tmp_path: Path) -> None:
    broken = tmp_path / "b.pdf"
    broken.write_bytes(b"%PDF-1.4\n garbage")
    with pytest.raises(UploadError, match="could not open"):
        check_upload(broken)


def test_an_image_with_too_many_pixels_is_rejected_before_decoding(tmp_path: Path) -> None:
    huge = png(tmp_path / "huge.png", (9000, 9000))
    with pytest.raises(UploadError, match="too large"):
        check_upload(huge)


def test_a_pdf_with_too_many_pages_is_rejected(tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas

    path = tmp_path / "long.pdf"
    pdf = canvas.Canvas(str(path))
    for _ in range(6):
        pdf.drawString(50, 50, "page")
        pdf.showPage()
    pdf.save()
    with pytest.raises(UploadError, match="pages"):
        check_upload(path)


def test_a_pdf_with_a_giant_page_is_rejected(tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas

    path = tmp_path / "poster.pdf"
    pdf = canvas.Canvas(str(path), pagesize=(20000, 20000))
    pdf.drawString(50, 50, "x")
    pdf.save()
    with pytest.raises(UploadError, match="page size"):
        check_upload(path)


def test_errors_never_contain_the_file_name_or_content(tmp_path: Path) -> None:
    path = tmp_path / "Jane_Doe_account_99887766.pdf"
    path.write_bytes(b"Jane Doe 99887766 not a pdf")
    with pytest.raises(UploadError) as error:
        check_upload(path)
    assert "Jane" not in str(error.value) and "99887766" not in str(error.value)


def test_extraction_refuses_a_bad_upload_before_reading_it(tmp_path: Path) -> None:
    fake = tmp_path / "bill.pdf"
    fake.write_bytes(b"not a pdf at all")
    with pytest.raises(ExtractionError, match="does not match"):
        extract_bill(fake, None, llm=None, case_id="c1")  # type: ignore[arg-type]
    with pytest.raises(ExtractionError, match="does not match"):
        extract_eob(fake, llm=None, case_id="c1")


def test_reading_a_sample_logs_no_document_text(caplog: pytest.LogCaptureFixture, ref) -> None:
    caplog.set_level(logging.DEBUG)
    result = extract_bill(MAYA, ref, llm=None, case_id="c1")
    words = {line.description for line in result.lines}
    for record in caplog.records:
        message = record.getMessage()
        assert not any(word in message for word in words), message


def test_sdk_loggers_that_print_request_bodies_are_kept_quiet() -> None:
    import app.llm  # noqa: F401

    for name in ("openai", "httpx", "httpcore", "pdfminer"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, name


def test_a_very_long_row_is_skipped_not_matched(tmp_path: Path) -> None:
    import time

    from app.extract import MAX_ROW_CHARS, read_with_pdfplumber
    from reportlab.pdfgen import canvas

    path = tmp_path / "wide.pdf"
    pdf = canvas.Canvas(str(path))
    pdf.setFont("Helvetica", 1)
    pdf.drawString(10, 700, "2026-09-14 G0121 x" + " y" * 200 + " 1 $5.00")
    pdf.save()
    started = time.perf_counter()
    assert read_with_pdfplumber(path).lines == []
    assert time.perf_counter() - started < 1
    assert MAX_ROW_CHARS == 300


def test_letters_do_not_fetch_external_resources() -> None:
    try:
        from app.letters.render import Letter, render_pdf
    except OSError:
        pytest.skip("WeasyPrint needs pango")
    html = '<html><body><p>x</p><img src="file:///etc/hosts"><link rel="stylesheet" href="http://127.0.0.1:9/x.css"></body></html>'
    try:
        pdf = render_pdf(Letter(kind="eob_mismatch", title="t", html=html, text="x"))
    except OSError:
        pytest.skip("WeasyPrint needs pango")
    assert pdf.startswith(b"%PDF")  # rendered without loading either resource (a fetch would have been refused and logged)
