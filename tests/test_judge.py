"""Ultra sees amber units and dose findings only, answers keep or downgrade, and can change nothing else."""

import json
import sqlite3
from decimal import Decimal

import pytest

from app.findings import Finding, total_dollars_at_stake
from app.judge import judge_amber
from app.llm import LLMClient
from tests.builders import sample_audit
from tests.fakes import FakeOpenAI, ListSink


@pytest.fixture(autouse=True)
def model_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    for role in ("READER", "CLEANER", "JUDGE", "WRITER"):
        monkeypatch.setenv(f"MODEL_{role}", f"test/{role.lower()}")


def maya(ref: sqlite3.Connection):
    """Maya's sample: one amber finding (30 flushes against a limit of 25, MAI 3) among reds and greys."""
    _, lines, result = sample_audit("maya", ref)
    return lines, result.findings


def llm_with(replies: list) -> tuple[LLMClient, FakeOpenAI, ListSink]:
    fake, sink = FakeOpenAI(replies), ListSink()
    return LLMClient(sink=sink, client=fake), fake, sink


def verdict(decision: str, reason: str = "The bill states several flushes during a long procedure.") -> str:
    return json.dumps({"decision": decision, "reason": reason})


def amber(findings: list[Finding]) -> Finding:
    (found,) = [f for f in findings if f.check in {"units", "dose"} and f.level == "amber"]
    return found


def test_a_downgrade_turns_the_amber_finding_grey_with_the_reason(ref: sqlite3.Connection) -> None:
    _, findings = maya(ref)
    llm, _, _ = llm_with([verdict("downgrade")])
    judged = judge_amber(llm, "c1", findings)
    result = [f for f in judged if f.check == "units" and f.codes == amber(findings).codes][0]
    assert result.level == "grey"
    assert (result.judge_decision, result.judge_reason) == ("downgrade", "The bill states several flushes during a long procedure.")


def test_keep_leaves_the_finding_amber_with_the_reason(ref: sqlite3.Connection) -> None:
    _, findings = maya(ref)
    llm, _, _ = llm_with([verdict("keep", "Nothing on the bill explains 30 flushes.")])
    result = amber(judge_amber(llm, "c1", findings))
    assert (result.level, result.judge_decision) == ("amber", "keep")
    assert result.judge_reason == "Nothing on the bill explains 30 flushes."


def test_red_and_grey_findings_are_never_sent_or_changed(ref: sqlite3.Connection) -> None:
    _, findings = maya(ref)
    llm, fake, _ = llm_with([verdict("downgrade")])
    judged = judge_amber(llm, "c1", findings)
    assert len(fake.completions.requests) == 1  # one amber finding, nothing else
    for before, after in zip(findings, judged):
        if before.level != "amber":
            assert after == before


def test_no_amber_findings_means_no_model_call(ref: sqlite3.Connection) -> None:
    _, findings = maya(ref)
    reds = [f for f in findings if f.level != "amber"]
    llm, fake, _ = llm_with([])
    assert judge_amber(llm, "c1", reds) == reds
    assert fake.completions.requests == []


def test_dollars_at_stake_are_identical_before_and_after(ref: sqlite3.Connection) -> None:
    lines, findings = maya(ref)
    llm, _, _ = llm_with([verdict("downgrade")])
    judged = judge_amber(llm, "c1", findings)
    assert total_dollars_at_stake(judged, lines) == total_dollars_at_stake(findings, lines) == Decimal("3858.00")
    assert [f.dollars_at_stake for f in judged] == [f.dollars_at_stake for f in findings]


def test_the_prompt_has_only_the_code_descriptions_units_and_limit(ref: sqlite3.Connection) -> None:
    _, findings = maya(ref)
    llm, fake, _ = llm_with([verdict("keep")])
    judge_amber(llm, "c1", findings)
    sent = json.dumps(fake.completions.requests[0]["messages"])
    target = amber(findings)
    assert "A4216" in sent and "limit 25" in sent and "30 units" in sent and "MAI 3" in sent
    for line in target.evidence.bill_lines:
        assert line.description in sent
        assert str(line.charge) not in sent
        assert line.service_date.isoformat() not in sent
    # nothing from the other findings: their charges and codes stay out
    assert "G0121" not in sent and "J2704" not in sent and "J2250" not in sent


def test_the_model_cannot_raise_a_flag(ref: sqlite3.Connection) -> None:
    _, findings = maya(ref)
    llm, _, _ = llm_with([verdict("upgrade"), verdict("red")])
    result = amber(judge_amber(llm, "c1", findings))
    assert (result.level, result.judge_decision) == ("amber", None)


def test_a_failed_call_leaves_the_finding_amber(ref: sqlite3.Connection) -> None:
    _, findings = maya(ref)
    llm, _, _ = llm_with([RuntimeError("boom")])
    result = amber(judge_amber(llm, "c1", findings))
    assert (result.level, result.judge_decision, result.judge_reason) == ("amber", None, None)


def test_a_reason_with_a_banned_word_is_rejected(ref: sqlite3.Connection) -> None:
    _, findings = maya(ref)
    llm, _, _ = llm_with([verdict("downgrade", "This is an illegal markup.")] * 2)
    result = amber(judge_amber(llm, "c1", findings))
    assert (result.level, result.judge_decision) == ("amber", None)


def test_the_reason_is_one_line(ref: sqlite3.Connection) -> None:
    _, findings = maya(ref)
    llm, _, _ = llm_with([verdict("keep", "First line.\nSecond line that goes on.")])
    assert amber(judge_amber(llm, "c1", findings)).judge_reason == "First line."


def test_the_call_is_logged_to_the_judge_step_without_content(ref: sqlite3.Connection) -> None:
    _, findings = maya(ref)
    llm, _, sink = llm_with([verdict("keep")])
    judge_amber(llm, "c1", findings)
    (case_id, record), = sink.records
    assert (case_id, record.step, record.model, record.ok) == ("c1", "judge_amber", "test/judge", True)


def test_an_amber_dose_finding_is_judged_too(ref: sqlite3.Connection) -> None:
    from datetime import date

    from app.audit import run_checks
    from tests.builders import bill_line

    lines = [bill_line("J2250", "50.00", units=3, description="Rev 0636 Midazolam HCl inj 2 mL", dose=("2", "ML"))]
    findings = run_checks(lines, ref=ref, patient_type="self_pay", today=date(2026, 10, 28)).findings
    llm, fake, _ = llm_with([verdict("keep", "The bill gives a volume, not milligrams.")])
    (dose,) = [f for f in judge_amber(llm, "c1", findings) if f.check == "dose"]
    assert (dose.level, dose.judge_decision) == ("amber", "keep")
    sent = json.dumps(fake.completions.requests[0]["messages"])
    assert "Rev 0636 Midazolam HCl inj 2 mL" in sent and "per 1 mg" in sent and "50.00" not in sent


# --- what Ultra is sent, and what it can never change ---------------------------------------------------------


def lines_for(*specs):
    from tests.builders import bill_line

    return [bill_line(code, charge, units=units, description=text, dose=dose) for code, charge, units, text, dose in specs]


def audit_lines(lines, ref, patient_type="self_pay"):
    from datetime import date

    from app.audit import run_checks

    return run_checks(lines, ref=ref, patient_type=patient_type, today=date(2026, 10, 28)).findings


def test_a_units_finding_is_sent_with_code_hcpcs_description_dose_units_and_limit(ref: sqlite3.Connection) -> None:
    lines = lines_for(("A4216", "255.00", 30, "Rev 0270 Saline flush syringe 10 mL", ("10", "ML")))
    llm, fake, _ = llm_with([verdict("keep")])
    judge_amber(llm, "c1", audit_lines(lines, ref))
    sent = json.dumps(fake.completions.requests[0]["messages"])
    for needle in (
        "A4216", "Sterile flush or diluent solution, 10 mL",  # code and the CMS HCPCS description
        "Rev 0270 Saline flush syringe 10 mL", "dose 10 mL",  # the bill's text and the dose written on it
        "30 units", "limit 25", "MAI 3",
    ):
        assert needle in sent, needle
    assert "255.00" not in sent and "2026-09-14" not in sent  # no charges or dates


def test_a_dose_finding_is_sent_with_the_hcpcs_description_dose_and_units(ref: sqlite3.Connection) -> None:
    lines = lines_for(("J2250", "50.00", 3, "Rev 0636 Midazolam HCl inj 2 mL", ("2", "ML")))
    llm, fake, _ = llm_with([verdict("keep", "The bill gives a volume, not milligrams.")])
    judge_amber(llm, "c1", audit_lines(lines, ref))
    sent = json.dumps(fake.completions.requests[0]["messages"])
    for needle in ("J2250", "Injection of a sedative, per 1 mg", "dose 2 mL", "billed per 1 mg", "3 units"):
        assert needle in sent, needle
    assert "50.00" not in sent


def test_only_worth_asking_about_findings_are_sent(ref: sqlite3.Connection) -> None:
    """MAI 3 units and dose findings that need interpreting go to Ultra. Nothing else does."""
    lines = lines_for(
        ("G0121", "5600.00", 2, "Rev 0750 Screening colonoscopy", None),  # MAI 2 over the limit: a likely error
        ("J2704", "1100.00", 200, "Rev 0636 Propofol inj 200 mg", ("200", "MG")),  # clear dose mismatch: red
        ("J2250", "50.00", 3, "Rev 0636 Midazolam inj 2 mL", ("2", "ML")),  # dose needs interpreting: amber
        ("A4216", "255.00", 30, "Rev 0270 Saline flush syringe 10 mL", ("10", "ML")),  # MAI 3: amber
    )
    findings = audit_lines(lines, ref)
    llm, fake, _ = llm_with([verdict("keep"), verdict("keep")])
    judged = judge_amber(llm, "c1", findings)
    assert len(fake.completions.requests) == 2
    assert {f.check for f in judged if f.judge_decision} == {"units", "dose"}
    assert {(f.check, f.codes[0]) for f in judged if f.judge_decision} == {("dose", "J2250"), ("units", "A4216")}


def test_an_insured_patients_absolute_limit_is_a_billing_review_not_a_judgment_call(ref: sqlite3.Connection) -> None:
    lines = lines_for(("G0121", "5600.00", 2, "Rev 0750 Screening colonoscopy", None))
    findings = audit_lines(lines, ref, patient_type="insured")
    assert [(f.check, f.level, f.mai) for f in findings if f.check == "units"] == [("units", "amber", 2)]
    llm, fake, _ = llm_with([])
    assert judge_amber(llm, "c1", findings) == findings
    assert fake.completions.requests == []  # MAI 2 is an absolute limit; only MAI 3 is a judgment call


def test_ultra_cannot_change_a_likely_error_or_any_amount(ref: sqlite3.Connection) -> None:
    lines = lines_for(
        ("G0121", "5600.00", 2, "Rev 0750 Screening colonoscopy", None),
        ("J2704", "1100.00", 200, "Rev 0636 Propofol inj 200 mg", ("200", "MG")),
        ("J2250", "68.00", 2, "Rev 0636 Midazolam inj 2 mg", ("2", "MG")),
        ("J2250", "68.00", 2, "Rev 0636 Midazolam inj 2 mg", ("2", "MG")),
        ("A4216", "255.00", 30, "Rev 0270 Saline flush syringe 10 mL", ("10", "ML")),
    )
    findings = audit_lines(lines, ref)
    for decision in ("keep", "downgrade"):
        llm, _, _ = llm_with([verdict(decision)])
        judged = judge_amber(llm, "c1", findings)
        assert len(judged) == len(findings)
        for before, after in zip(findings, judged):
            if before.level == "red":
                assert after == before  # untouched, field for field
            elif before.level == "amber":
                # only the verdict and, on a downgrade, the level may differ; wording, evidence and money may not
                assert after.model_dump(exclude={"level", "judge_decision", "judge_reason"}) == before.model_dump(
                    exclude={"level", "judge_decision", "judge_reason"}
                )
        assert total_dollars_at_stake(judged, lines) == total_dollars_at_stake(findings, lines) == Decimal("3858.00")


def test_a_reply_that_names_an_amount_or_a_new_level_changes_nothing(ref: sqlite3.Connection) -> None:
    lines = lines_for(("A4216", "255.00", 30, "Rev 0270 Saline flush syringe 10 mL", ("10", "ML")))
    findings = audit_lines(lines, ref)
    bad = json.dumps({"decision": "keep", "reason": "ok", "level": "red", "dollars_at_stake": "999.00"})
    llm, _, _ = llm_with([bad])
    (units,) = [f for f in judge_amber(llm, "c1", findings) if f.check == "units"]
    assert (units.level, units.dollars_at_stake, units.counted) == ("amber", Decimal("0.00"), {})
