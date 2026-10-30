"""Regenerate samples/<name>/bill.pdf (+ eob.pdf for insured samples), expected_flags.json and Maya's phone photo.

Run: python -m samples.generate
Everything comes from samples/definitions.py so the documents and their expected findings cannot drift apart.
The photo is rendered from Maya's PDF with a fixed random seed, so it is the same on every run.
"""

import random
from decimal import Decimal
from pathlib import Path

import pdfplumber
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.schemas import ExpectedSample
from samples.definitions import FACILITY, FACILITY_ADDRESS, PATIENTS, SAMPLES

ROOT = Path(__file__).parent


def money(value: Decimal) -> str:
    return f"${value:,.2f}"


def draw_page(canvas: Canvas, _doc: SimpleDocTemplate) -> None:
    """Banner on every page plus a large diagonal SAMPLE watermark."""
    width, height = letter
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#b00020"))
    canvas.rect(0, height - 0.45 * inch, width, 0.45 * inch, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawCentredString(width / 2, height - 0.29 * inch, "SAMPLE DOCUMENT - FICTIONAL - NOT A REAL BILL")
    canvas.translate(width / 2, height / 2)
    canvas.rotate(35)
    canvas.setFillColor(colors.Color(0.5, 0.5, 0.5, alpha=0.18))
    canvas.setFont("Helvetica-Bold", 130)
    canvas.drawCentredString(0, -40, "SAMPLE")
    canvas.restoreState()


def build_pdf(sample: ExpectedSample, path: Path) -> None:
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, leading=12)
    patient = PATIENTS[sample.sample_id]
    total = sum((item.charge for item in sample.lines), Decimal("0.00"))

    rows = [["Service date", "HCPCS", "Mod", "Description", "Units", "Charge"]]
    rows += [
        [
            item.service_date.isoformat(),
            item.code,
            item.modifier or "",
            item.description,
            str(item.units),
            money(item.charge),
        ]
        for item in sample.lines
    ]
    rows.append(["", "", "", "", "Total charges", money(total)])
    rows.append(["", "", "", "", "Balance due", money(sample.amount_due)])
    table = Table(rows, colWidths=[0.95 * inch, 0.9 * inch, 0.45 * inch, 2.9 * inch, 0.95 * inch, 0.85 * inch])
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
                ("FONT", (4, -2), (-1, -1), "Helvetica-Bold", 9),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
                ("LINEABOVE", (0, -2), (-1, -2), 0.8, colors.black),
                ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
                # No row fills: they would cover the watermark.
                ("LINEBELOW", (0, 1), (-1, -4), 0.25, colors.HexColor("#cccccc")),
            ]
        )
    )

    doc = SimpleDocTemplate(
        str(path), pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.9 * inch, bottomMargin=0.7 * inch,
        title=f"SAMPLE itemized bill - {sample.sample_id}", author="ClaimGuard sample generator",
    )
    doc.build(
        [
            Paragraph(FACILITY.upper(), styles["Title"]),
            Paragraph(f"{FACILITY_ADDRESS} - Hospital Outpatient Department", small),
            Spacer(1, 14),
            Paragraph("<b>ITEMIZED STATEMENT</b>", styles["Heading3"]),
            Paragraph(
                f"Patient: {patient['name']}<br/>Account number: {patient['account']}<br/>"
                f"Payer: {sample.payer}<br/>Statement (bill) date: {sample.bill_date.isoformat()}",
                small,
            ),
            Spacer(1, 14),
            table,
            Spacer(1, 14),
            Paragraph(
                "This is a synthetic sample created to test ClaimGuard. Names, account numbers and "
                "the facility are invented.",
                small,
            ),
        ],
        onFirstPage=draw_page,
        onLaterPages=draw_page,
    )


def build_eob_pdf(sample: ExpectedSample, path: Path) -> None:
    assert sample.eob is not None
    eob = sample.eob
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, leading=12)
    patient = PATIENTS[sample.sample_id]
    rows = [
        ["Amount billed by provider", money(eob.billed)],
        ["Plan discount (not your responsibility)", money(eob.billed - eob.allowed)],
        ["Allowed amount", money(eob.allowed)],
        ["Plan paid", money(eob.plan_paid)],
        ["Patient responsibility", money(eob.patient_responsibility)],
    ]
    table = Table(rows, colWidths=[4.2 * inch, 1.6 * inch])
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
                ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 10),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#cccccc")),
            ]
        )
    )
    doc = SimpleDocTemplate(
        str(path), pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.9 * inch, bottomMargin=0.7 * inch,
        title=f"SAMPLE explanation of benefits - {sample.sample_id}", author="ClaimGuard sample generator",
    )
    doc.build(
        [
            Paragraph(eob.insurer.upper(), styles["Title"]),
            Paragraph("<b>EXPLANATION OF BENEFITS - THIS IS NOT A BILL</b>", styles["Heading3"]),
            Paragraph(
                f"Member: {patient['name']}<br/>Member ID: {patient['member']}<br/>Claim number: {patient['claim']}<br/>"
                f"Provider: {sample.facility_name}<br/>Date of service: {sample.lines[0].service_date.isoformat()}",
                small,
            ),
            Spacer(1, 14),
            table,
            Spacer(1, 14),
            Paragraph(
                "This is a synthetic sample created to test ClaimGuard. Names, claim numbers and the plan "
                "are invented.",
                small,
            ),
        ],
        onFirstPage=draw_page,
        onLaterPages=draw_page,
    )


PHOTO_SEED = 20260914


def _paper_texture(size: tuple[int, int], rng: random.Random) -> Image.Image:
    """Low-contrast fibre noise: random grey values at 1/4 scale, blurred and enlarged."""
    small = (size[0] // 4, size[1] // 4)
    noise = Image.frombytes("L", small, bytes(rng.randint(226, 255) for _ in range(small[0] * small[1])))
    return noise.filter(ImageFilter.GaussianBlur(1.2)).resize(size, Image.BILINEAR)


def _perspective_coefficients(src: list[tuple[float, float]], dst: list[tuple[float, float]]) -> list[float]:
    """Coefficients for Image.transform(PERSPECTIVE), which maps each output point back to an input point."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); rhs.append(u)
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y]); rhs.append(v)
    # Gaussian elimination on the 8x8 system (no numpy needed).
    n = 8
    m = [row + [b] for row, b in zip(rows, rhs)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col:
                factor = m[r][col] / m[col][col]
                m[r] = [a - factor * b for a, b in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def build_photo(pdf_path: Path, out: Path) -> None:
    """A phone-style photo of the printed bill: paper texture, perspective, slight rotation, uneven light."""
    rng = random.Random(PHOTO_SEED)
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0].to_image(resolution=150).original.convert("RGB")
    width, height = page.size

    # Printed on slightly warm paper with fibre texture.
    texture = _paper_texture(page.size, rng)
    paper = Image.merge("RGB", [texture.point(lambda v, k=k: min(255, v + k)) for k in (4, 2, -6)])
    page = ImageChops.multiply(page, paper)  # ink on paper: keeps the light-grey SAMPLE watermark visible

    # Lay the sheet on a darker table, tilted toward the camera (top edge narrower) and rotated a little.
    margin = 140
    canvas_size = (width + 2 * margin, height + 2 * margin)
    table = Image.new("RGB", canvas_size, (92, 84, 74))
    table = Image.blend(table, Image.merge("RGB", [_paper_texture(canvas_size, rng)] * 3), 0.25)
    sheet = Image.new("RGB", canvas_size, (0, 0, 0))
    mask = Image.new("L", canvas_size, 0)
    sheet.paste(page, (margin, margin))
    mask.paste(255, (margin, margin, margin + width, margin + height))
    src = [(margin, margin), (margin + width, margin), (margin + width, margin + height), (margin, margin + height)]
    dst = [(margin + 60, margin + 35), (margin + width - 45, margin + 20), (margin + width + 25, margin + height - 10), (margin - 20, margin + height + 5)]
    coeffs = _perspective_coefficients(src, dst)
    sheet = sheet.transform(canvas_size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    mask = mask.transform(canvas_size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    sheet, mask = sheet.rotate(-2.2, Image.BICUBIC, fillcolor=(0, 0, 0)), mask.rotate(-2.2, Image.BICUBIC)

    # Soft drop shadow under the sheet, then the sheet itself.
    shadow = mask.filter(ImageFilter.GaussianBlur(18)).point(lambda v: v * 0.55)
    table.paste((30, 26, 22), (18, 22), shadow)
    photo = Image.composite(sheet, table, mask)

    # Uneven light: a phone's shadow falling across the lower left corner.
    light = Image.new("L", canvas_size, 0)
    ImageDraw.Draw(light).ellipse((-canvas_size[0] // 2, canvas_size[1] // 2, canvas_size[0] // 2, canvas_size[1] * 3 // 2), fill=70)
    photo = Image.composite(Image.new("RGB", canvas_size, (0, 0, 0)), photo, light.filter(ImageFilter.GaussianBlur(160)))

    photo = photo.filter(ImageFilter.GaussianBlur(0.6)).resize((canvas_size[0] * 2 // 3, canvas_size[1] * 2 // 3), Image.LANCZOS)
    photo.save(out, "JPEG", quality=82, optimize=True)


def main() -> None:
    for sample in SAMPLES:
        folder = ROOT / sample.sample_id
        folder.mkdir(exist_ok=True)
        build_pdf(sample, folder / "bill.pdf")
        if sample.eob:
            build_eob_pdf(sample, folder / "eob.pdf")
        (folder / "expected_flags.json").write_text(sample.model_dump_json(indent=2) + "\n")
        if sample.sample_id == "maya":
            build_photo(folder / "bill.pdf", folder / "bill_photo.jpg")
        print(f"wrote {folder.relative_to(ROOT.parent)}/ bill.pdf{', eob.pdf' if sample.eob else ''}, expected_flags.json")


if __name__ == "__main__":
    main()
