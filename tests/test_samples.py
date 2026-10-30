"""The sample bills and their expected findings must be internally consistent and match the CMS data.

Every expected finding is re-derived here from the reference database (MUE limits, dosages, payment limits)
with plain arithmetic, independently of app/checks/, so the expected files are a real oracle for the checks
and the eval. It runs against the hand-written fixture and, when built, the real database.
"""

import re
import sqlite3
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pdfplumber
import pytest

from app.refdb import open_reference
from app.schemas import ExpectedFlag, ExpectedSample
from app.uploads import check_upload
from samples import generate
from samples.definitions import SAMPLES

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "samples"
REAL_DB = ROOT / "data" / "claimguard.db"
NAMES = [sample.sample_id for sample in SAMPLES]
GFE_THRESHOLD = Decimal("400.00")
GFE_WINDOW_DAYS = 120
ZERO = Decimal("0.00")
CPT_SHAPED = re.compile(r"(?<![\w$.,])(?:\d{5}|\d{4}[FTU])(?!\w|\.\d)")
LEVEL_II = re.compile(r"[A-Z]\d{4}")
# Dose units to a base unit within one family: mass in mg, volume in mL. Anything else is not convertible.
TO_BASE = {"MG": ("mass", Decimal(1)), "MCG": ("mass", Decimal("0.001")), "GM": ("mass", Decimal(1000)),
           "G": ("mass", Decimal(1000)), "ML": ("volume", Decimal(1)), "CC": ("volume", Decimal(1))}


@pytest.fixture(params=["fixture", "real"])
def ref(request: pytest.FixtureRequest, reference_db_path: Path):
    if request.param == "real" and not REAL_DB.exists():
        pytest.skip("run `python -m ingest` first")
    conn = open_reference(reference_db_path if request.param == "fixture" else REAL_DB)
    yield conn
    conn.close()


def load(name: str) -> ExpectedSample:
    return ExpectedSample.model_validate_json((SAMPLES_DIR / name / "expected_flags.json").read_text())


def unrotated_text(path: Path) -> str:
    """Text without the diagonal watermark (pdfplumber calls any non-90-degree rotation 'upright')."""
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0].filter(
            lambda obj: obj.get("object_type") != "char" or abs(obj["matrix"][1]) < 0.01
        )
        return page.extract_text()


# --- the oracle: expected findings from the reference data, by hand ---------------------------------------


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def excess_share(charge: Decimal, billed: int, allowed: int) -> Decimal:
    return money(charge * (billed - allowed) / billed)


def derive(sample: ExpectedSample, conn: sqlite3.Connection) -> tuple[list[ExpectedFlag], Decimal]:
    """Expected findings and the likely-error total, from docs/SPEC.md section 5 and the reference rows."""
    lines = sample.lines
    insured = sample.patient_type == "insured"
    flags: list[ExpectedFlag] = []
    counted: dict[int, Decimal] = defaultdict(lambda: ZERO)  # line number -> amount, each line once

    def drug(code: str):
        return conn.execute("SELECT dose_value, dose_unit, payment_limit FROM drug_limits WHERE code = ?", (code,)).fetchone()

    # Duplicate: same date, code, units and modifier; the repeats count.
    groups: dict[tuple, list[int]] = defaultdict(list)
    for n, item in enumerate(lines, start=1):
        groups[(item.service_date, item.code, item.units, item.modifier)].append(n)
    for (_, code, _, _), numbers in groups.items():
        if len(numbers) > 1:
            amount = sum((lines[n - 1].charge for n in numbers[1:]), ZERO)
            flags.append(ExpectedFlag(check="duplicate", level="red", codes=[code], line_numbers=numbers, dollars_at_stake=amount))
            for n in numbers[1:]:
                counted[n] = max(counted[n], lines[n - 1].charge)

    # Units against the MUE: MAI 1 per line, MAI 2 and 3 per code per day. MAI 1/2 is a likely error
    # (self-pay); MAI 3, or any MUE for an insured patient, is worth asking about. An MUE of 0 is no limit.
    # The excess units are taken from the last line(s) of the group, each at its own unit charge.
    groups_by: dict[tuple, list[int]] = defaultdict(list)
    for n, item in enumerate(lines, start=1):
        if not LEVEL_II.fullmatch(item.code):
            continue
        row = conn.execute("SELECT mue_value, mai FROM mue WHERE code = ?", (item.code,)).fetchone()
        if row is None or row[0] == 0:
            continue
        key = (item.code, n) if row[1] == 1 or item.service_date is None else (item.code, item.service_date)
        groups_by[key].append(n)
    for (code, _), numbers in groups_by.items():
        row = conn.execute("SELECT mue_value, mai FROM mue WHERE code = ?", (code,)).fetchone()
        billed = sum(lines[n - 1].units for n in numbers)
        if billed <= row[0]:
            continue
        red = row[1] in (1, 2) and not insured
        amount = ZERO
        if red:
            remaining = billed - row[0]
            for n in reversed(numbers):
                take = min(remaining, lines[n - 1].units)
                if take == 0:
                    break
                share = excess_share(lines[n - 1].charge, lines[n - 1].units, lines[n - 1].units - take)
                counted[n] = max(counted[n], share)
                amount += share
                remaining -= take
        flags.append(ExpectedFlag(
            check="units", level="red" if red else "amber", codes=[code], line_numbers=numbers,
            mue_value=row[0], mai=row[1], dollars_at_stake=amount,
        ))

    # Dose: the dose written on the line divided by the dose per billing unit must equal the billed units.
    # A dose that cannot be converted, or is not a whole number of units, is worth asking about.
    mismatched: set[int] = set()
    for n, item in enumerate(lines, start=1):
        row = drug(item.code) if LEVEL_II.fullmatch(item.code) else None
        if row is None or row[0] is None or item.dose_value is None:
            continue
        written, per_unit = TO_BASE.get(item.dose_unit), TO_BASE.get(row[1])
        expected = None
        if written is not None and per_unit is not None and written[0] == per_unit[0]:
            expected = item.dose_value * written[1] / (Decimal(row[0]) * per_unit[1])
        if expected is None or expected != expected.to_integral_value():
            mismatched.add(n)
            flags.append(ExpectedFlag(check="dose", level="amber", codes=[item.code], line_numbers=[n]))
            continue
        if int(expected) == item.units:
            continue
        mismatched.add(n)
        amount = ZERO
        if not insured and item.units > expected:
            amount = excess_share(item.charge, item.units, int(expected))
            counted[n] = max(counted[n], amount)
        flags.append(ExpectedFlag(
            check="dose", level="red", codes=[item.code], line_numbers=[n], expected_units=int(expected),
            dollars_at_stake=amount,
        ))

    # Drug benchmark: charge per unit / payment limit, once per code, never on a dose-mismatch line.
    by_code: dict[str, list[int]] = defaultdict(list)
    for n, item in enumerate(lines, start=1):
        by_code[item.code].append(n)
    for code, numbers in by_code.items():
        row = drug(code) if LEVEL_II.fullmatch(code) else None
        numbers = [n for n in numbers if n not in mismatched]
        if row is None or row[0] is None or row[2] is None or not numbers:
            continue
        first = lines[numbers[0] - 1]
        multiple = (first.charge / first.units / Decimal(row[2])).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        flags.append(ExpectedFlag(check="drug_benchmark", level="grey", codes=[code], line_numbers=numbers, multiple=multiple))

    # Code check: a live Level II code with no Medicare drug limit gets "valid, no public rate" context.
    for code, numbers in by_code.items():
        if CPT_SHAPED.fullmatch(code):  # shown, never looked up
            flags.append(ExpectedFlag(check="code", level="grey", codes=[code], line_numbers=numbers, code_status="not_checked"))
            continue
        if not LEVEL_II.fullmatch(code) or drug(code) is not None:
            continue
        live = conn.execute("SELECT 1 FROM hcpcs WHERE code = ? AND termination_date IS NULL", (code,)).fetchone()
        flags.append(ExpectedFlag(
            check="code", level="grey", codes=[code], line_numbers=numbers,
            code_status="valid_no_rate" if live else "unknown",
        ))

    # Good Faith Estimate: self-pay only, $400 or more over, 120 days from the bill date. Never counted.
    if not insured and sample.gfe_total is not None:
        overage = sum((i.charge for i in lines), ZERO) - sample.gfe_total
        if overage >= GFE_THRESHOLD:
            flags.append(ExpectedFlag(
                check="gfe", level="red", overage=overage,
                deadline=sample.bill_date + timedelta(days=GFE_WINDOW_DAYS),
            ))

    # EOB: the bill's balance due above the EOB's patient responsibility. Counted.
    eob_amount = ZERO
    if sample.eob is not None and sample.amount_due > sample.eob.patient_responsibility:
        eob_amount = sample.amount_due - sample.eob.patient_responsibility
        flags.append(ExpectedFlag(
            check="eob", level="red", amount_billed=sample.amount_due,
            patient_responsibility=sample.eob.patient_responsibility, dollars_at_stake=eob_amount,
        ))

    return flags, sum(counted.values(), ZERO) + eob_amount


def key(flag: ExpectedFlag) -> tuple:
    return (flag.check, flag.level, flag.codes, flag.line_numbers)


@pytest.mark.parametrize("name", NAMES)
def test_expected_flags_match_the_reference_data(name: str, ref: sqlite3.Connection) -> None:
    sample = load(name)
    flags, _ = derive(sample, ref)
    assert sorted(flags, key=key) == sorted(sample.flags, key=key)


@pytest.mark.parametrize("name", NAMES)
def test_likely_error_total_counts_each_line_once(name: str, ref: sqlite3.Connection) -> None:
    sample = load(name)
    _, total = derive(sample, ref)
    assert sample.likely_error_total == total


@pytest.mark.parametrize("name", NAMES)
def test_gfe_overage_and_deadline_are_recorded_separately(name: str) -> None:
    sample = load(name)
    gfe = [f for f in sample.flags if f.check == "gfe"]
    if gfe:
        assert (sample.gfe_overage, sample.deadline) == (gfe[0].overage, gfe[0].deadline)
        assert gfe[0].dollars_at_stake == ZERO  # shown, never added
    else:
        assert sample.gfe_overage is None and sample.deadline is None


@pytest.mark.parametrize("name", NAMES)
def test_only_red_findings_carry_dollars(name: str) -> None:
    assert all(f.dollars_at_stake == ZERO for f in load(name).flags if f.level != "red")


# --- the documents ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_expected_json_is_valid_and_up_to_date(name: str) -> None:
    committed = (SAMPLES_DIR / name / "expected_flags.json").read_text()
    assert committed == load(name).model_dump_json(indent=2) + "\n"
    sample = next(s for s in SAMPLES if s.sample_id == name)
    assert committed == sample.model_dump_json(indent=2) + "\n", "run `python -m samples.generate`"


@pytest.mark.parametrize("name", NAMES)
def test_pdf_is_visibly_marked_as_sample(name: str) -> None:
    with pdfplumber.open(SAMPLES_DIR / name / "bill.pdf") as pdf:
        chars = pdf.pages[0].chars
    banner = "".join(c["text"] for c in chars if abs(c["matrix"][1]) < 0.01)
    assert "SAMPLE DOCUMENT - FICTIONAL - NOT A REAL BILL" in banner
    watermark = [c for c in chars if abs(c["matrix"][1]) >= 0.01]
    assert "".join(c["text"] for c in watermark) == "SAMPLE"
    assert all(c["size"] > 100 for c in watermark)


@pytest.mark.parametrize("name", NAMES)
def test_every_expected_line_is_readable_from_the_pdf_text(name: str) -> None:
    rows = unrotated_text(SAMPLES_DIR / name / "bill.pdf").splitlines()
    for item in load(name).lines:
        wanted = [item.service_date.isoformat(), item.code, item.description, f"${item.charge:,.2f}"]
        assert any(all(part in row for part in wanted) for row in rows), (item.code, item.charge)


@pytest.mark.parametrize("name", NAMES)
def test_only_level_ii_codes_and_no_cpt_shaped_text_anywhere(name: str) -> None:
    sample = load(name)
    assert all(re.fullmatch(r"[A-Z]\d{4}", item.code) for item in sample.lines)
    texts = [(SAMPLES_DIR / name / "expected_flags.json").read_text(), unrotated_text(SAMPLES_DIR / name / "bill.pdf")]
    if (SAMPLES_DIR / name / "eob.pdf").exists():
        texts.append(unrotated_text(SAMPLES_DIR / name / "eob.pdf"))
    for text in texts:
        assert not CPT_SHAPED.search(text), CPT_SHAPED.search(text)


def test_sample_source_files_have_no_cpt_shaped_text() -> None:
    for path in (SAMPLES_DIR / "definitions.py", SAMPLES_DIR / "generate.py"):
        assert not CPT_SHAPED.search(path.read_text()), path.name


@pytest.mark.parametrize("name", NAMES)
def test_revenue_codes_appear_only_inside_the_description(name: str) -> None:
    for item in load(name).lines:
        assert re.match(r"Rev \d{4} \S", item.description), item.description
    header = unrotated_text(SAMPLES_DIR / name / "bill.pdf").splitlines()
    assert not any("Revenue" in row or "Rev code" in row for row in header)


@pytest.mark.parametrize("name", NAMES)
def test_drug_lines_state_their_dose_and_it_matches_the_expected_dose(name: str, ref: sqlite3.Connection) -> None:
    unit_text = {"MG": "mg", "MCG": "mcg", "ML": "mL"}
    for item in load(name).lines:
        is_drug = ref.execute("SELECT 1 FROM drug_limits WHERE code = ?", (item.code,)).fetchone() is not None
        if is_drug:
            assert item.dose_value is not None, item.code
        if item.dose_value is not None:
            assert item.description.endswith(f" {item.dose_value} {unit_text[item.dose_unit]}"), item.description


@pytest.mark.parametrize("name", NAMES)
def test_account_and_names_are_marked_invented(name: str) -> None:
    text = unrotated_text(SAMPLES_DIR / name / "bill.pdf")
    assert "Account number: SAMPLE-" in text
    assert "invented" in text
    assert "Riverbend Community Hospital".upper() in text


@pytest.mark.parametrize("name", NAMES)
def test_line_descriptions_are_not_cms_descriptors(name: str) -> None:
    if not REAL_DB.exists():
        pytest.skip("run `python -m ingest` first")
    conn = sqlite3.connect(REAL_DB)
    descriptors = {
        row[0].lower()
        for table, column in (("hcpcs", "short_description"), ("hcpcs", "long_description"), ("drug_limits", "short_description"))
        for row in conn.execute(f"SELECT {column} FROM {table}")
    }
    conn.close()
    assert not {item.description.lower() for item in load(name).lines} & descriptors


@pytest.mark.parametrize("name", NAMES)
def test_every_flag_references_real_lines_with_its_codes(name: str) -> None:
    sample = load(name)
    for flag in sample.flags:
        if flag.check in {"gfe", "eob"}:
            assert flag.line_numbers == [] and flag.codes == []  # account-level
            continue
        assert flag.line_numbers, flag
        assert {sample.lines[n - 1].code for n in flag.line_numbers} == set(flag.codes)


def test_maya_seeds_every_case_the_demo_needs() -> None:
    kinds = {(f.check, f.level) for f in load("maya").flags}
    assert {
        ("duplicate", "red"), ("dose", "red"), ("units", "red"), ("units", "amber"), ("gfe", "red"),
        ("drug_benchmark", "grey"), ("code", "grey"),
    } <= kinds
    assert {f.mai for f in load("maya").flags if f.check == "units"} == {2, 3}


def test_clean_control_has_no_likely_errors_or_questions() -> None:
    clean = load("clean")
    assert {f.level for f in clean.flags} == {"grey"}
    assert clean.likely_error_total == ZERO
    overage = sum((i.charge for i in clean.lines), ZERO) - clean.gfe_total
    assert ZERO < overage < GFE_THRESHOLD  # over the estimate, but under the dispute threshold


def test_generator_reproduces_the_committed_pdf_text(tmp_path: Path) -> None:
    for sample in SAMPLES:
        out = tmp_path / f"{sample.sample_id}.pdf"
        generate.build_pdf(sample, out)
        assert unrotated_text(out) == unrotated_text(SAMPLES_DIR / sample.sample_id / "bill.pdf")


def test_dev_is_insured_with_an_eob_that_the_bill_exceeds() -> None:
    dev = load("dev")
    assert dev.patient_type == "insured" and dev.eob is not None and dev.gfe_total is None
    eob_flags = [f for f in dev.flags if f.check == "eob"]
    assert len(eob_flags) == 1 and eob_flags[0].dollars_at_stake == dev.amount_due - dev.eob.patient_responsibility
    assert dev.likely_error_total == eob_flags[0].dollars_at_stake  # line findings add nothing when insured
    assert any(f.check == "dose" for f in dev.flags)  # shown, worded as a billing review


def test_eob_figures_are_internally_consistent() -> None:
    dev = load("dev")
    eob = dev.eob
    assert eob.billed == sum((i.charge for i in dev.lines), ZERO)  # the EOB covers the same claim
    assert eob.allowed - eob.plan_paid == eob.patient_responsibility
    assert dev.amount_due == eob.allowed  # the hospital asks for the allowed amount, ignoring the plan payment


@pytest.mark.parametrize("name", [n for n in NAMES if n != "dev"])
def test_self_pay_balance_due_is_the_whole_bill(name: str) -> None:
    sample = load(name)
    assert sample.amount_due == sum((i.charge for i in sample.lines), ZERO)
    assert sample.eob is None and not (SAMPLES_DIR / name / "eob.pdf").exists()


def test_balance_due_is_readable_from_every_bill() -> None:
    for name in NAMES:
        assert f"Balance due ${load(name).amount_due:,.2f}" in unrotated_text(SAMPLES_DIR / name / "bill.pdf")


def test_eob_pdf_is_marked_sample_from_a_fictional_plan_and_shows_the_figures() -> None:
    path = SAMPLES_DIR / "dev" / "eob.pdf"
    with pdfplumber.open(path) as pdf:
        watermark = "".join(c["text"] for c in pdf.pages[0].chars if abs(c["matrix"][1]) >= 0.01)
    assert watermark == "SAMPLE"
    text = unrotated_text(path)
    eob = load("dev").eob
    for label, value in [
        ("Amount billed by provider", eob.billed), ("Allowed amount", eob.allowed),
        ("Plan paid", eob.plan_paid), ("Patient responsibility", eob.patient_responsibility),
    ]:
        assert f"{label} ${value:,.2f}" in text
    assert "THIS IS NOT A BILL" in text and "(SAMPLE PLAN)" in text
    assert "BLUE CROSS" not in text.upper() and "BLUE SHIELD" not in text.upper()  # no real insurer's brand


# --- Maya's phone photo ----------------------------------------------------------------------------------

PHOTO = SAMPLES_DIR / "maya" / "bill_photo.jpg"


def test_photo_is_a_jpeg_the_upload_path_accepts() -> None:
    assert PHOTO.read_bytes()[:3] == b"\xff\xd8\xff"
    assert check_upload(PHOTO) == "jpeg"
    assert PHOTO.stat().st_size < 2 * 1024 * 1024


def test_photo_is_regenerated_identically(tmp_path: Path) -> None:
    out = tmp_path / "photo.jpg"
    generate.build_photo(SAMPLES_DIR / "maya" / "bill.pdf", out)
    assert out.read_bytes() == PHOTO.read_bytes()
