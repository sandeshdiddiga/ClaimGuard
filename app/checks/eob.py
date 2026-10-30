"""Bill above EOB: the hospital asks for more than the insurer's EOB says the patient owes."""

from decimal import Decimal

from app.checks import wording
from app.checks.constants import EOB_SOURCE
from app.findings import Evidence, Finding
from app.schemas import EobReading


def check_eob(amount_due: Decimal | None, eob: EobReading | None) -> list[Finding]:
    if amount_due is None or eob is None or amount_due <= eob.patient_responsibility:
        return []
    difference = amount_due - eob.patient_responsibility
    return [
        Finding(
            check="eob", level="red", dollars_at_stake=difference, amount_billed=amount_due,
            patient_responsibility=eob.patient_responsibility,
            wording=wording.EOB_MISMATCH.format(
                billed=wording.money_text(amount_due), owed=wording.money_text(eob.patient_responsibility)
            ),
            evidence=Evidence(
                rule="The balance the hospital asks the patient to pay is above the patient responsibility on the EOB.",
                data_row={
                    "eob_billed": f"{eob.billed:.2f}", "eob_allowed": f"{eob.allowed:.2f}",
                    "eob_patient_responsibility": f"{eob.patient_responsibility:.2f}",
                    "bill_balance_due": f"{amount_due:.2f}",
                },
                computed={"difference": f"{difference:.2f}"},
                difference=difference, source_name=EOB_SOURCE,
            ),
        )
    ]
