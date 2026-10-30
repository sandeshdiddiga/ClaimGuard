"""Ultra reviews "worth asking about" findings only: keep the flag or downgrade it to grey, with a one-line reason.

Those are units above a CMS limit that allows clinical judgment (MAI 3) and a written dose that needs
interpreting against the drug's billing unit (`reviewable`). Ultra sees the code, its CMS description, the dose
text, the units and the limit, nothing else (no charges, dates or personal details). It can never touch a
likely error, raise a flag or change an amount: only `level` (amber to grey) and the verdict fields can change.
An unusable or failed answer leaves the finding amber.
"""

from typing import Literal

from pydantic import BaseModel

from app.checks import wording
from app.config import Step
from app.findings import Finding
from app.llm import LLMClient, LLMError
from app.textguard import has_banned_term

MAX_REASON = 200

SYSTEM = (
    "You review one line on a hospital bill that was marked 'worth asking about'. Either the units billed are "
    "above a CMS daily limit that allows clinical judgment (MUE adjudication indicator 3), or the dose written "
    "on the line needs interpreting against the drug's billing unit. Using only the code, the CMS figures, the "
    "units and the bill's own descriptions given, answer 'downgrade' if the bill's text explains it, or 'keep' "
    "if the patient should ask the billing office. Give a one-line reason. You do not decide money, you give "
    "no medical or legal advice, and you never accuse anyone."
)


class Verdict(BaseModel):
    decision: Literal["keep", "downgrade"]
    reason: str


def reviewable(finding: Finding) -> bool:
    """Worth asking about, and a judgment call: units over an MAI 3 limit, or a dose that needs interpreting.

    Everything else is never sent: a likely error is not Ultra's to soften, and an insured patient's MAI 1 or 2
    finding is a billing-review item, not a clinical judgment."""
    if finding.level != "amber":
        return False
    return (finding.check == "units" and finding.mai == 3) or (finding.check == "dose" and finding.expected_units is None)


def _line(line) -> str:
    dose = f", dose {wording.dose_text(line.dose_value, line.dose_unit)}" if line.dose_value is not None and line.dose_unit else ""
    return f"- {line.units} units, modifier {line.modifier or 'none'}, bill description: {line.description}{dose}"


def _describe(finding: Finding) -> str:
    """Only the code, its CMS description, the units, the CMS figures and the bill's own text. No money, dates or names."""
    data, computed = finding.evidence.data_row, finding.evidence.computed
    described = f"Code {finding.codes[0]} (HCPCS description: {data.get('hcpcs_description') or 'not available'})."
    if finding.check == "units":
        head = (
            f"Units over a CMS limit. {described} CMS limit {finding.mue_value} units per day (MAI {finding.mai}); "
            f"{computed['billed_units']} units billed."
        )
    else:
        head = (
            f"A dose that needs interpreting. {described} The drug is billed per {computed['dose_per_unit']}; "
            f"the line states {computed['stated_dose']}; {computed['billed_units']} units billed."
        )
    return head + "\nBill lines:\n" + "\n".join(_line(line) for line in finding.evidence.bill_lines)


def _one_line(reason: str) -> str:
    first = next((part.strip() for part in reason.splitlines() if part.strip()), "")
    return first[:MAX_REASON]


def judge_amber(llm: LLMClient, case_id: str, findings: list[Finding]) -> list[Finding]:
    judged = []
    for finding in findings:
        if not reviewable(finding):
            judged.append(finding)
            continue
        try:
            verdict = llm.complete_json(
                Step.JUDGE_AMBER,
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _describe(finding)}],
                Verdict,
                case_id=case_id,
            )
        except LLMError:
            judged.append(finding)
            continue
        reason = _one_line(verdict.reason)
        if not reason or has_banned_term(reason):
            judged.append(finding)
            continue
        update: dict = {"judge_decision": verdict.decision, "judge_reason": reason}
        if verdict.decision == "downgrade":
            update["level"] = "grey"
        judged.append(finding.model_copy(update=update))
    return judged
