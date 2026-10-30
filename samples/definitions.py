"""Synthetic sample bills and the findings the checks must produce for them.

Everything here is invented: names, account numbers, the hospital, the insurance plan, the charges. Codes are
real HCPCS Level II codes (no CPT) so the CMS public-use data applies; revenue codes appear only inside the
description text, and descriptions are our own words. The facts behind each finding, from the October 2026
CMS files in data/claimguard.db (re-derived independently in tests/test_samples.py):

    G0121  screening colonoscopy, average risk        MUE 1     MAI 2    no drug limit (code check: no rate)
    J2250  midazolam, per 1 mg                         MUE 30    MAI 3    limit $0.167 per unit
    J3010  fentanyl citrate, per 0.1 mg                MUE 100   MAI 3    limit $1.362 per unit
    J2704  propofol, per 10 mg                         MUE 400   MAI 3    limit $0.093 per unit
    J2405  ondansetron, per 1 mg                       MUE 64    MAI 3    limit $0.084 per unit
    J7120  lactated Ringer's, up to 1000 cc            MUE 20    MAI 3    limit $2.369 per unit
    A4216  saline/water flush, 10 ml                   MUE 25    MAI 3    no drug limit (code check: no rate)

Money rules (docs/SPEC.md section 5): the likely-error total counts each line once (largest amount wins).
Duplicates count the line charge; units and dose findings count only the excess units. The EOB difference
counts; for insured patients line-level units and dose findings add nothing. The Good Faith Estimate overage is
shown separately. Benchmarks never count, and a line with a dose-mismatch finding gets no benchmark.
"""

from datetime import date
from decimal import Decimal

from app.schemas import ExpectedEob, ExpectedFlag, ExpectedLine, ExpectedSample

D = Decimal


def line(
    service_date: date, code: str, description: str, charge: str, units: int = 1,
    dose: tuple[str, str] | None = None,
) -> ExpectedLine:
    return ExpectedLine(
        service_date=service_date, code=code, description=description, units=units, charge=D(charge),
        dose_value=D(dose[0]) if dose else None, dose_unit=dose[1] if dose else None,
    )


SELF_PAY = "Self-pay (no insurance)"
PLAN = "Bluestone Health PPO (sample plan)"
FACILITY = "Riverbend Community Hospital"
FACILITY_ADDRESS = "2100 Riverside Drive, Millbrook, Example State"

# Maya: self-pay, screening colonoscopy at the hospital outpatient department. Seeded problems: the colonoscopy
# billed as 2 units (MUE 1, MAI 2), midazolam charged twice, propofol billed per mg instead of per 10 mg, 30
# flushes against an MUE of 25 (MAI 3, for Ultra), and a total far above her Good Faith Estimate.
MAYA_DATE = date(2026, 9, 14)
MAYA = ExpectedSample(
    sample_id="maya",
    description="Self-pay screening colonoscopy with five seeded problems plus Medicare drug-price context",
    patient_type="self_pay",
    facility_name=FACILITY,
    bill_date=date(2026, 10, 5),
    payer=SELF_PAY,
    amount_due=D("7383.00"),  # self-pay: the whole bill
    gfe_total=D("3400.00"),
    lines=[
        line(MAYA_DATE, "G0121", "Rev 0750 Screening colonoscopy, average risk", "5600.00", units=2),
        line(MAYA_DATE, "J2250", "Rev 0636 Midazolam HCl inj 2 mg", "68.00", units=2, dose=("2", "MG")),
        line(MAYA_DATE, "J2250", "Rev 0636 Midazolam HCl inj 2 mg", "68.00", units=2, dose=("2", "MG")),
        line(MAYA_DATE, "J3010", "Rev 0636 Fentanyl citrate inj 100 mcg", "54.00", dose=("100", "MCG")),
        line(MAYA_DATE, "J2704", "Rev 0636 Propofol inj 200 mg", "1100.00", units=200, dose=("200", "MG")),
        line(MAYA_DATE, "J2405", "Rev 0636 Ondansetron inj 4 mg", "96.00", units=4, dose=("4", "MG")),
        line(MAYA_DATE, "J7120", "Rev 0258 Lactated Ringer's IV 1000 mL", "142.00", dose=("1000", "ML")),
        line(MAYA_DATE, "A4216", "Rev 0270 Saline flush syringe 10 mL", "255.00", units=30, dose=("10", "ML")),
    ],
    flags=[
        ExpectedFlag(
            # 2 units against a limit of 1 with no clinical exception: the excess unit is half the line.
            check="units", level="red", codes=["G0121"], line_numbers=[1], mue_value=1, mai=2,
            dollars_at_stake=D("2800.00"),
        ),
        ExpectedFlag(
            check="duplicate", level="red", codes=["J2250"], line_numbers=[2, 3],
            dollars_at_stake=D("68.00"),  # the second occurrence
        ),
        ExpectedFlag(
            # 200 mg at 10 mg per unit is 20 units; 200 were billed. 180 of 200 units: 1,100.00 x 0.9.
            check="dose", level="red", codes=["J2704"], line_numbers=[5], expected_units=20,
            dollars_at_stake=D("990.00"),
        ),
        ExpectedFlag(
            # 30 units against 25, but MAI 3 allows clinical judgment: Ultra reviews; not counted.
            check="units", level="amber", codes=["A4216"], line_numbers=[8], mue_value=25, mai=3,
        ),
        ExpectedFlag(
            # 7,383.00 billed vs 3,400.00 estimate. 120 days after the 2026-10-05 bill date.
            check="gfe", level="red", overage=D("3983.00"), deadline=date(2027, 2, 2),
        ),
        ExpectedFlag(check="drug_benchmark", level="grey", codes=["J2250"], line_numbers=[2, 3], multiple=D("203.6")),
        ExpectedFlag(check="drug_benchmark", level="grey", codes=["J3010"], line_numbers=[4], multiple=D("39.6")),
        ExpectedFlag(check="drug_benchmark", level="grey", codes=["J2405"], line_numbers=[6], multiple=D("285.7")),
        ExpectedFlag(check="drug_benchmark", level="grey", codes=["J7120"], line_numbers=[7], multiple=D("59.9")),
        ExpectedFlag(check="code", level="grey", codes=["G0121"], line_numbers=[1], code_status="valid_no_rate"),
        ExpectedFlag(check="code", level="grey", codes=["A4216"], line_numbers=[8], code_status="valid_no_rate"),
    ],
    likely_error_total=D("3858.00"),  # 2,800.00 + 68.00 + 990.00
    gfe_overage=D("3983.00"),
    deadline=date(2027, 2, 2),
)

# Control: nothing wrong. Billed 3,089.50 vs a 2,750.00 estimate: $339.50 over, below the $400 threshold.
CLEAN_DATE = date(2026, 9, 22)
CLEAN = ExpectedSample(
    sample_id="clean",
    description="Self-pay control bill: no likely errors; $339.50 over the estimate is under the $400 threshold",
    patient_type="self_pay",
    facility_name=FACILITY,
    bill_date=date(2026, 10, 8),
    payer=SELF_PAY,
    amount_due=D("3089.50"),
    gfe_total=D("2750.00"),
    lines=[
        line(CLEAN_DATE, "G0121", "Rev 0750 Screening colonoscopy, average risk", "2800.00"),
        line(CLEAN_DATE, "J2250", "Rev 0636 Midazolam HCl inj 2 mg", "68.00", units=2, dose=("2", "MG")),
        line(CLEAN_DATE, "J3010", "Rev 0636 Fentanyl citrate inj 100 mcg", "54.00", dose=("100", "MCG")),
        line(CLEAN_DATE, "J7120", "Rev 0258 Lactated Ringer's IV 1000 mL", "142.00", dose=("1000", "ML")),
        line(CLEAN_DATE, "A4216", "Rev 0270 Saline flush syringe 10 mL", "25.50", units=3, dose=("10", "ML")),
    ],
    flags=[
        ExpectedFlag(check="drug_benchmark", level="grey", codes=["J2250"], line_numbers=[2], multiple=D("203.6")),
        ExpectedFlag(check="drug_benchmark", level="grey", codes=["J3010"], line_numbers=[3], multiple=D("39.6")),
        ExpectedFlag(check="drug_benchmark", level="grey", codes=["J7120"], line_numbers=[4], multiple=D("59.9")),
        ExpectedFlag(check="code", level="grey", codes=["G0121"], line_numbers=[1], code_status="valid_no_rate"),
        ExpectedFlag(check="code", level="grey", codes=["A4216"], line_numbers=[5], code_status="valid_no_rate"),
    ],
    likely_error_total=D("0.00"),
)

# Dev: insured (PPO), the same kind of visit. The hospital asks him for 1,460.00, the full allowed amount, but
# his EOB says the plan paid 1,050.00 and he owes 410.00. Ondansetron 4 mg is billed as 8 units: a dose
# finding worded "ask for a billing review" that adds nothing, because the EOB sets what he owes.
DEV_DATE = date(2026, 9, 30)
DEV = ExpectedSample(
    sample_id="dev",
    description="Insured colonoscopy: the bill asks for 1,050.00 more than the EOB says the patient owes",
    patient_type="insured",
    facility_name=FACILITY,
    bill_date=date(2026, 10, 12),
    payer=PLAN,
    amount_due=D("1460.00"),
    eob=ExpectedEob(
        insurer=PLAN, billed=D("3244.00"), allowed=D("1460.00"), plan_paid=D("1050.00"),
        patient_responsibility=D("410.00"),
    ),
    lines=[
        line(DEV_DATE, "G0121", "Rev 0750 Screening colonoscopy, average risk", "2800.00"),
        line(DEV_DATE, "J2704", "Rev 0636 Propofol inj 200 mg", "110.00", units=20, dose=("200", "MG")),
        line(DEV_DATE, "J2405", "Rev 0636 Ondansetron inj 4 mg", "192.00", units=8, dose=("4", "MG")),
        line(DEV_DATE, "J7120", "Rev 0258 Lactated Ringer's IV 1000 mL", "142.00", dose=("1000", "ML")),
    ],
    flags=[
        ExpectedFlag(
            check="eob", level="red", amount_billed=D("1460.00"), patient_responsibility=D("410.00"),
            dollars_at_stake=D("1050.00"),
        ),
        ExpectedFlag(check="dose", level="red", codes=["J2405"], line_numbers=[3], expected_units=4),
        ExpectedFlag(check="drug_benchmark", level="grey", codes=["J2704"], line_numbers=[2], multiple=D("59.1")),
        ExpectedFlag(check="drug_benchmark", level="grey", codes=["J7120"], line_numbers=[4], multiple=D("59.9")),
        ExpectedFlag(check="code", level="grey", codes=["G0121"], line_numbers=[1], code_status="valid_no_rate"),
    ],
    likely_error_total=D("1050.00"),
)

# Document header details that are not part of the scored lines.
PATIENTS = {
    "maya": {"name": "Maya Okafor", "account": "SAMPLE-0042-7731"},
    "clean": {"name": "Jordan Ellis", "account": "SAMPLE-0057-1204"},
    "dev": {"name": "Dev Raman", "account": "SAMPLE-0063-9910", "claim": "SAMPLE-CLM-551020", "member": "SAMPLE-BHX-448210"},
}

SAMPLES = [MAYA, DEV, CLEAN]
