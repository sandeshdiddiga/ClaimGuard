"""Read a bill into lines: vision model first, pdfplumber as the fallback, then clean the codes.

Order of trust for codes: deterministic normalization, then OCR-confusion repair, then Nano. A Level II code
is only accepted when it exists in the HCPCS table; anything else is left for the patient to confirm. CPT-shaped
codes are shown unchanged and never looked up (app/codes.py). Doses are read by Nano from the description and
kept only when the description states them (app/dose.py).
"""

import io
import re
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

import pdfplumber
from PIL import Image
from pydantic import BaseModel

from app.codes import NOT_CHECKED_NOTE, class_note, classify_code, normalize_code, repair_level2
from app.config import Step
from app.dose import settle_dose
from app.llm import LLMClient, LLMError, image_part
from app.safety import review_lines
from app.schemas import BillReading, EobReading, ExtractedLine
from app.uploads import MAX_PAGES, UploadError, check_upload

MAX_IMAGE_SIDE = 2000
MAX_ROW_CHARS = 300
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

READ_PROMPT = (
    "Read this itemized hospital bill. Return every charge line with: service_date (YYYY-MM-DD), code "
    "(exactly as printed: letters and digits), modifier (or null), description, units, charge (a number, no currency "
    "symbol). Also return facility_name, bill_date (statement date, YYYY-MM-DD) and amount_due (the "
    "balance due from the patient) if printed. Do not include the patient's name, address, account "
    "number or any other personal detail. Do not total, correct or interpret anything: copy what is printed."
)

EOB_PROMPT = (
    "Read this insurer's Explanation of Benefits. Return billed (the amount billed by the provider), "
    "allowed (the plan's allowed amount, also called plan allowed) and patient_responsibility (what the member "
    "owes: also labelled patient or member responsibility, your share, you owe or what you owe), as numbers "
    "with no currency symbol, plus insurer_name if printed. Do not include the member's name, member ID, "
    "claim number or any other personal detail. Copy what is printed; do not calculate."
)


class ExtractionError(RuntimeError):
    pass


def validate_file(path: Path) -> None:
    """Size, type, content and page limits (app/uploads.py), before any parser or model sees the file."""
    try:
        check_upload(path)
    except UploadError as error:
        raise ExtractionError(str(error)) from None


class NotABillError(ExtractionError):
    pass


class Extraction(BaseModel):
    lines: list[ExtractedLine]
    facility_name: str | None = None  # the hospital named on the bill, when the reader found it
    bill_date: date | None = None
    amount_due: Decimal | None = None
    source: Literal["vision", "pdfplumber"]


class EobExtraction(EobReading):
    source: Literal["vision", "pdfplumber"]


# --- code cleanup -----------------------------------------------------------------------------------


def resolve_codes(lines: list[ExtractedLine], ref: sqlite3.Connection) -> tuple[list[ExtractedLine], list[int]]:
    """Deterministic pass. Returns the lines and the indexes still unresolved (for Nano)."""
    resolved: list[ExtractedLine] = []
    unresolved: list[int] = []
    for index, line in enumerate(lines):
        code = normalize_code(line.code)
        code_class = classify_code(ref, code)
        status, note = "ok", line.note
        fixed = repair_level2(code) if code_class in ("unknown_level2", "missing") else None
        if fixed and classify_code(ref, fixed) == "hcpcs_level2":
            code, code_class, status, note = fixed, "hcpcs_level2", "corrected", f"read as {line.code!r}"
        elif code_class == "cpt_shaped":
            note = NOT_CHECKED_NOTE  # shown unchanged, never looked up
        elif code_class != "hcpcs_level2":
            status, note = "needs_review", class_note(code_class)
            unresolved.append(index)
        resolved.append(line.model_copy(update={"code": code, "status": status, "note": note, "code_class": code_class}))
    return resolved, unresolved


def apply_nano(
    lines: list[ExtractedLine], unresolved: list[int], cleaned: dict[int, tuple[str, bool]], ref: sqlite3.Connection
) -> list[ExtractedLine]:
    """Accept Nano's suggestion for unresolved lines only, and only if the code is in the HCPCS table.

    A CPT-shaped suggestion is never accepted: those codes are not looked up."""
    out = list(lines)
    for index in unresolved:
        suggestion, readable = cleaned.get(index, ("", False))
        code = normalize_code(suggestion)
        if readable and classify_code(ref, code) == "hcpcs_level2":
            out[index] = out[index].model_copy(
                update={"code": code, "status": "corrected", "note": f"read as {lines[index].code!r}",
                        "code_class": "hcpcs_level2"}
            )
    return out


def apply_doses(
    lines: list[ExtractedLine], proposed: dict[int, tuple[Decimal | None, str | None]]
) -> list[ExtractedLine]:
    """Attach each line's dose. Nano's answer is kept only if the description states it (app/dose.py)."""
    out = []
    for index, line in enumerate(lines):
        value, unit = settle_dose(line.description, *proposed.get(index, (None, None)))
        out.append(line.model_copy(update={"dose_value": value, "dose_unit": unit}))
    return out


def settle_line(line: ExtractedLine, ref: sqlite3.Connection) -> ExtractedLine:
    """A line as the patient confirmed it: re-classify the code and re-check the dose against the description,
    both deterministic, so an edit to either is reflected without calling a model."""
    code = normalize_code(line.code)
    code_class = classify_code(ref, code)
    kept = line.note if code_class == "hcpcs_level2" and line.note and line.note.startswith("read as") else None
    value, unit = settle_dose(line.description, line.dose_value, line.dose_unit)
    return line.model_copy(
        update={"code": code, "code_class": code_class, "status": "ok", "note": class_note(code_class) or kept,
                "dose_value": value, "dose_unit": unit}
    )


# --- reading documents ------------------------------------------------------------------------------


def to_page_images(path: Path) -> list[bytes]:
    """PNG bytes for each page (PDF) or the image itself, capped in size."""
    if path.suffix.lower() == ".pdf":
        with pdfplumber.open(path) as pdf:
            images = [page.to_image(resolution=150).original for page in pdf.pages[:MAX_PAGES]]
    elif path.suffix.lower() in IMAGE_SUFFIXES:
        images = [Image.open(path)]
    else:
        raise ExtractionError(f"unsupported file type: {path.suffix or 'none'}")
    pages = []
    for image in images:
        image = image.convert("RGB")
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        pages.append(buffer.getvalue())
    return pages


def read_with_vision(llm: LLMClient, case_id: str, path: Path) -> BillReading:
    content = [{"type": "text", "text": READ_PROMPT}, *(image_part(png) for png in to_page_images(path))]
    return llm.complete_json(
        Step.READ_DOCUMENT, [{"role": "user", "content": content}], BillReading, case_id=case_id
    )


ROW = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<code>[0-9A-Z]{5})\s+(?:(?P<mod>[A-Z0-9]{2})\s+)?"
    r"(?P<desc>.+?)\s+(?P<units>\d+)\s+\$(?P<charge>[\d,]+\.\d{2})$"
)
BILL_DATE = re.compile(r"bill\)? date:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)


BALANCE_DUE = re.compile(r"^Balance due\s+\$([\d,]+\.\d{2})$", re.MULTILINE)


def unrotated_text(path: Path) -> str:
    """Page text without rotated characters. A diagonal watermark otherwise leaks letters into the rows
    (pdfplumber reports any non-90-degree rotation as 'upright')."""
    with pdfplumber.open(path) as pdf:
        return "\n".join(
            page.filter(
                lambda obj: obj.get("object_type") != "char" or abs(obj["matrix"][1]) < 0.01
            ).extract_text()
            or ""
            for page in pdf.pages[:MAX_PAGES]
        )


def read_with_pdfplumber(path: Path) -> BillReading:
    """Offline fallback for text PDFs laid out like our samples."""
    text = unrotated_text(path)
    lines = []
    for row in text.splitlines():
        row = row.strip()
        if len(row) > MAX_ROW_CHARS:  # no real bill row is this long; long runs make the regex quadratic
            continue
        match = ROW.match(row)
        if not match:
            continue
        try:
            lines.append(
                ExtractedLine(
                    service_date=match["date"], code=match["code"], modifier=match["mod"],
                    description=match["desc"], units=int(match["units"]), charge=Decimal(match["charge"].replace(",", "")),
                )
            )
        except (InvalidOperation, ValueError):
            continue
    bill, balance = BILL_DATE.search(text), BALANCE_DUE.search(text)
    return BillReading(
        bill_date=bill.group(1) if bill else None,
        amount_due=Decimal(balance.group(1).replace(",", "")) if balance else None,
        lines=lines,
    )


# Insurers label the same three amounts in different words. Each pattern wants the label alone at the start
# of a line and one dollar amount at the end, so a bill row can never match.
EOB_AMOUNTS = {
    "billed": r"Amount billed(?: by provider)?|Billed amount|Total billed",
    "allowed": r"Allowed amount|Plan allowed(?: amount)?",
    "patient_responsibility": (
        r"Patient responsibility|Member responsibility|Your share|(?:Amount )?you owe|What you owe"
    ),
}
EOB_PATTERNS = {
    key: re.compile(rf"^(?:{labels})\s*:?\s+\$([\d,]+\.\d{{2}})$", re.MULTILINE | re.IGNORECASE)
    for key, labels in EOB_AMOUNTS.items()
}

EOB_UNREADABLE = (
    "We couldn't read the amounts on your EOB, so we skipped the EOB comparison. "
    "Make sure it's your insurer's Explanation of Benefits, not the hospital bill."
)
EOB_NOT_ADDED = (
    "You didn't add an EOB, so we skipped the EOB comparison. "
    "Add your insurer's Explanation of Benefits to check what the hospital asks you to pay against it."
)
EOB_LOOKS_LIKE_BILL = EOB_UNREADABLE + " The file in the EOB slot looks like the hospital bill: it has the same lines and codes."


def read_eob_with_pdfplumber(path: Path) -> EobReading:
    text = unrotated_text(path)
    amounts: dict[str, Decimal] = {}
    for key, pattern in EOB_PATTERNS.items():
        values = {Decimal(m.replace(",", "")) for m in pattern.findall(text)}
        if len(values) != 1:  # none, or the label repeats with different amounts (per-claim shares): do not guess
            raise ExtractionError("no amounts found: this does not look like an EOB")
        amounts[key] = values.pop()
    return EobReading(**amounts)


def check_eob_amounts(reading: EobReading) -> None:
    """The amounts must be consistent (billed >= allowed >= patient responsibility >= 0). A model reading a
    hospital bill as an EOB, or mixing up labels, fails this, and a Likely error is never built on it."""
    if not (reading.billed >= reading.allowed >= reading.patient_responsibility >= 0):
        raise ExtractionError("the amounts do not look like an EOB")


def eob_slot_holds_the_bill(path: Path, bill_lines: list[ExtractedLine]) -> bool:
    """True when a PDF in the EOB slot has charge rows whose codes are on the bill. Text PDFs only; a photo
    cannot be checked without a model call, so it is never reported as the bill."""
    if path.suffix.lower() != ".pdf":
        return False
    try:
        rows = read_with_pdfplumber(path).lines
    except Exception:
        return False
    codes = {line.code for line in bill_lines}
    shared = {row.code for row in rows} & codes
    return bool(codes) and len(shared) * 2 >= len(codes)  # most of the bill's codes, not one chance match


def read_eob_with_vision(llm: LLMClient, case_id: str, path: Path) -> EobReading:
    content = [{"type": "text", "text": EOB_PROMPT}, *(image_part(png) for png in to_page_images(path))]
    return llm.complete_json(
        Step.READ_DOCUMENT, [{"role": "user", "content": content}], EobReading, case_id=case_id
    )


# --- orchestration ----------------------------------------------------------------------------------


def extract_bill(
    path: Path,
    ref: sqlite3.Connection,
    *,
    llm: LLMClient | None,
    case_id: str,
) -> Extraction:
    """Vision first (when `llm` is given), pdfplumber for PDFs if that fails, then the Nano gate."""
    if path.suffix.lower() not in {".pdf", *IMAGE_SUFFIXES}:
        raise ExtractionError(f"unsupported file type: {path.suffix or 'none'}")
    validate_file(path)
    reading: BillReading | None = None
    source: Literal["vision", "pdfplumber"] = "vision"
    if llm is not None:
        try:
            reading = read_with_vision(llm, case_id, path)
        except LLMError:
            if path.suffix.lower() != ".pdf":
                raise ExtractionError("could not read this image; try a PDF or a clearer photo") from None
    if reading is None:
        if path.suffix.lower() != ".pdf":
            raise ExtractionError("reading photos needs the vision model")
        reading, source = read_with_pdfplumber(path), "pdfplumber"
    if not reading.lines:
        raise ExtractionError("no charge lines found in this document")

    lines, unresolved = resolve_codes(reading.lines, ref)
    proposed: dict[int, tuple[Decimal | None, str | None]] = {}
    if llm is not None:
        gate = review_lines(llm, case_id, lines, unresolved)
        if not gate.is_itemized_bill:
            raise NotABillError(gate.reason or "this does not look like an itemized bill")
        lines = apply_nano(lines, unresolved, {c.index: (c.code, c.readable) for c in gate.lines}, ref)
        proposed = {d.index: (d.dose_value, d.dose_unit) for d in gate.doses}
    lines = apply_doses(lines, proposed)
    facility = " ".join((reading.facility_name or "").split())[:120] or None
    return Extraction(
        lines=lines, facility_name=facility, bill_date=reading.bill_date, amount_due=reading.amount_due, source=source
    )


def extract_eob(path: Path, *, llm: LLMClient | None, case_id: str) -> EobExtraction:
    """Vision first (when `llm` is given), pdfplumber for PDFs if that fails."""
    if path.suffix.lower() not in {".pdf", *IMAGE_SUFFIXES}:
        raise ExtractionError(f"unsupported file type: {path.suffix or 'none'}")
    validate_file(path)
    if llm is not None:
        try:
            reading = read_eob_with_vision(llm, case_id, path)
            check_eob_amounts(reading)
            return EobExtraction(**reading.model_dump(), source="vision")
        except LLMError:
            if path.suffix.lower() != ".pdf":
                raise ExtractionError("could not read this image; try a PDF or a clearer photo") from None
    if path.suffix.lower() != ".pdf":
        raise ExtractionError("reading photos needs the vision model")
    reading = read_eob_with_pdfplumber(path)
    check_eob_amounts(reading)
    return EobExtraction(**reading.model_dump(), source="pdfplumber")
