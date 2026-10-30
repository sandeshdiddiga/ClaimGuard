"""The exact wording shown for each finding, from the "What ClaimGuard checks" table in docs/SPEC.md section 5.

tests/test_wording_matches_spec.py requires the table wording to appear in the spec verbatim and lists the few
texts for cases the table does not cover. Never say "illegal"; never accuse.
"""

from datetime import date
from decimal import Decimal

DUPLICATE = "This charge appears twice on the same date. Ask the billing office to confirm or remove it."
DOSE = "Your bill says {dose}, which is {expected} billing units for this drug, but {billed} units were charged."
UNITS = "CMS normally allows at most {limit} units of this per day. {billed} were billed."
GFE_DISPUTE = "You may be able to start a federal billing dispute. Deadline: {deadline}."
EOB_MISMATCH = "The hospital billed ${billed}, but your insurer's EOB says you owe ${owed}."
DRUG_BENCHMARK = "Charged {multiple}× Medicare's payment limit for this drug. Not an error; useful when asking for a discount."
CODE_UNKNOWN = "Not in CMS's current HCPCS list."
CODE_NOT_CHECKED = "Not checked (CPT needs an AMA license)."
# Appended to units and dose findings for insured patients (SPEC section 4: worded "ask for a billing review").
BILLING_REVIEW = "Ask for a billing review."

# Not in the spec table.
# A dose in a unit that needs interpreting (mL for a drug billed per mg), or not a whole number of units.
DOSE_NEEDS_INTERPRETING = (
    "Your bill says {dose}, but this drug is billed per {per_unit}, so the number of billing units can't be "
    "worked out from the bill alone. {billed} units were charged."
)
# "Valid Level II: description shown"; SPEC section 4: ClaimGuard has no public Medicare rate for it and says so.
CODE_VALID = "{code}: {description}. ClaimGuard has no public Medicare rate for this code."
# The bill date is unknown, or the 120 days have already passed.
GFE_DEADLINE_UNKNOWN = "120 days from the date on your bill"
GFE_WINDOW_ENDED = "The 120-day window to start a federal billing dispute ended on {deadline}."

UNIT_TEXT = {"MG": "mg", "MCG": "mcg", "GM": "g", "ML": "mL", "CC": "cc", "UNITS": "units", "UNIT": "unit", "IU": "IU"}


def date_text(day: date) -> str:
    return f"{day:%B} {day.day}, {day.year}"


def money_text(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def dose_text(value: Decimal, unit: str) -> str:
    """200 MG -> "200 mg"; 0.1 MG -> "0.1 mg"; 1000 ML -> "1000 mL"."""
    number = format(value.normalize(), "f")
    return f"{number} {UNIT_TEXT.get(unit, unit.lower())}"
