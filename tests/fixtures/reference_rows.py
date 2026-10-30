"""Hand-written reference rows for tests.

Descriptions are our own words. The new tables hold only the Level II codes the tests and demo need; the
numbers (dosage, payment limit, MUE) mirror the October 2026 CMS public-use files so the same assertions hold
against the real database.
"""

from decimal import Decimal

from ingest.parse_drug_limits import DrugLimitRow
from ingest.parse_hcpcs import HcpcsRow
from ingest.parse_mue import MueRow

HCPCS_ROWS = [
    HcpcsRow("A4216", "flush solution", "Sterile flush or diluent solution, 10 mL", "20030101", "20030101", None),
    HcpcsRow("A4927", "exam gloves", "Exam gloves, per box of 100", "19960101", "19970101", None),
    HcpcsRow("A9579", "MRI contrast agent", "Contrast agent for magnetic resonance imaging, per mL", "20080101", "20080101", None),
    HcpcsRow("G0121", "colonoscopy screening", "Screening colonoscopy for a patient at average risk", "19980101", "20240101", None),
    HcpcsRow("J0716", "antitoxin injection", "Injection of an antitoxin, per billing unit", "19960101", "19970101", None),
    HcpcsRow("J1170", "retired pain injection", "Retired code for a pain injection", "19960101", "19970101", "20240930"),
    HcpcsRow("J1100", "steroid injection", "Injection of a steroid, per 1 mg", "19960101", "19970101", None),
    HcpcsRow("J2250", "sedative injection", "Injection of a sedative, per 1 mg", "19960101", "19970101", None),
    HcpcsRow("J2405", "anti-nausea injection", "Injection of an anti-nausea drug, per 1 mg", "19960101", "19970101", None),
    HcpcsRow("J2704", "anesthetic injection", "Injection of an anesthetic, per 10 mg", "20240101", "20240101", None),
    HcpcsRow("J3010", "opioid injection", "Injection of an opioid pain reliever, per 0.1 mg", "19960101", "19970101", None),
    HcpcsRow("J7120", "IV fluid infusion", "Balanced salt IV fluid, up to 1000 cc", "19960101", "19970101", None),
    HcpcsRow("J9029", "bladder instillation drug", "Drug instilled into the bladder, one treatment dose", "20230101", "20230101", None),
    HcpcsRow("Q9967", "imaging contrast", "Contrast material for imaging, per 1 mL", "20180101", "20180101", None),
]

DRUG_ROWS = [
    DrugLimitRow("J1100", "steroid injection", "1 MG", Decimal("1"), "MG", Decimal("0.099")),
    DrugLimitRow("J2250", "sedative injection", "1 MG", Decimal("1"), "MG", Decimal("0.167")),
    DrugLimitRow("J2405", "anti-nausea injection", "1 MG", Decimal("1"), "MG", Decimal("0.084")),
    DrugLimitRow("J2704", "anesthetic injection", "10 MG", Decimal("10"), "MG", Decimal("0.093")),
    DrugLimitRow("J3010", "opioid injection", "0.1 MG", Decimal("0.1"), "MG", Decimal("1.362")),
    DrugLimitRow("J7120", "IV fluid infusion", "1000 CC", Decimal("1000"), "CC", Decimal("2.369")),
    DrugLimitRow("J9029", "bladder instillation drug", "PER THERAPEUTIC DOSE", None, None, Decimal("65200.563")),
    DrugLimitRow("Q9967", "imaging contrast", "1 ML", Decimal("1"), "ML", Decimal("0.186")),
]

MUE_ROWS = [
    MueRow("A4216", 25, 3, "Clinical: CMS Workgroup"),
    MueRow("A4927", 0, 3, "CMS Policy"),  # an MUE of 0: no limit to compare against
    MueRow("A9579", 100, 3, "Prescribing Information"),
    MueRow("G0121", 1, 2, "Anatomic Consideration"),
    MueRow("J0716", 4, 1, "Clinical: Data"),
    MueRow("J1100", 120, 3, "Clinical: Data"),
    MueRow("J2250", 30, 3, "Clinical: Data"),
    MueRow("J2405", 64, 3, "Prescribing Information"),
    MueRow("J2704", 400, 3, "Clinical: Data"),
    MueRow("J3010", 100, 3, "Clinical: CMS Workgroup"),
    MueRow("J7120", 20, 3, "Clinical: Data"),
    MueRow("Q9967", 300, 3, "Prescribing Information"),
]
