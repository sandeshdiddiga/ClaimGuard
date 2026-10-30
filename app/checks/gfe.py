"""Over the Good Faith Estimate: $400 or more above the estimate, within 120 days of the bill.

Only for self-pay patients. Medicare, Medicaid and TRICARE enrollees are not eligible and are out of scope.
"""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from app.checks import wording
from app.checks.constants import (
    GFE_DISPUTE_THRESHOLD,
    GFE_DISPUTE_URL,
    GFE_DISPUTE_WINDOW_DAYS,
    GFE_SOURCE,
)
from app.findings import Evidence, Finding, charges, evidence_lines
from app.schemas import ExtractedLine


def check_gfe(
    lines: Sequence[ExtractedLine],
    *,
    patient_type: str,
    gfe_total: Decimal | None,
    bill_date: date | None,
    today: date | None = None,
) -> list[Finding]:
    if patient_type != "self_pay" or gfe_total is None or not lines:
        return []
    numbers = list(range(1, len(lines) + 1))
    facility_total = charges(lines, numbers)  # every line on a hospital bill is facility
    overage = facility_total - gfe_total
    if overage < GFE_DISPUTE_THRESHOLD:
        return []

    deadline = bill_date + timedelta(days=GFE_DISPUTE_WINDOW_DAYS) if bill_date else None
    if deadline is None:
        text = wording.GFE_DISPUTE.format(deadline=wording.GFE_DEADLINE_UNKNOWN)
    elif (today or date.today()) > deadline:
        text = wording.GFE_WINDOW_ENDED.format(deadline=wording.date_text(deadline))
    else:
        text = wording.GFE_DISPUTE.format(deadline=wording.date_text(deadline))

    return [
        Finding(
            check="gfe", level="red", wording=text, overage=overage, deadline=deadline,
            evidence=Evidence(
                bill_lines=evidence_lines(lines, numbers),
                rule=(
                    f"Self-pay patients billed ${GFE_DISPUTE_THRESHOLD:.2f} or more over their Good Faith "
                    f"Estimate may start a federal dispute within {GFE_DISPUTE_WINDOW_DAYS} days of the bill."
                ),
                data_row={
                    "facility_total": f"{facility_total:.2f}", "good_faith_estimate": f"{gfe_total:.2f}",
                    "threshold": f"{GFE_DISPUTE_THRESHOLD:.2f}",
                    "bill_date": bill_date.isoformat() if bill_date else None,
                    "window_days": GFE_DISPUTE_WINDOW_DAYS,
                    "deadline": deadline.isoformat() if deadline else None,
                },
                computed={"overage": f"{overage:.2f}"},
                difference=overage, source_name=GFE_SOURCE, source_url=GFE_DISPUTE_URL,
            ),
        )
    ]
