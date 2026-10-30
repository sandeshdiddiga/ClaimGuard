"""Case workflow behind the API: read the documents, store the lines, run the checks, write the letters."""

import json
import re
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.api_models import CallView, CaseView, ConfirmRequest, LetterView, ResultsView, SampleView
from app.audit import run_checks
from app.config import ConfigError
from app.extract import (
    EOB_LOOKS_LIKE_BILL, EOB_NOT_ADDED, EOB_UNREADABLE, eob_slot_holds_the_bill, extract_bill, extract_eob,
    settle_line,
)
from app.findings import Finding, charges, total_dollars_at_stake
from app.judge import judge_amber
from app.letters.render import Letter, Recipient, build_letters
from app.llm import LLMClient
from app.lookup import HospitalLookup, lookup_hospital
from app.schemas import EobReading, ExpectedSample
from app.settings import Settings
from app.store import Store

CASE_ID = re.compile(r"^[0-9a-f]{32}$")
SAMPLE_TITLES = {
    "maya": "Maya: self-pay colonoscopy bill with several problems",
    "dev": "Dev: insured, bill and EOB",
    "clean": "A clean bill: nothing to flag",
}


def letter_body(html: str) -> str:
    """The letter's <body> contents for the on-screen preview: no page styles, head or scripts. The letter is our
    own Jinja2 template with every value autoescaped, so this is markup we wrote, not markup from the bill."""
    match = re.search(r"<body>(.*)</body>", html, re.DOTALL)
    return match.group(1).strip() if match else ""


class NotFound(LookupError):
    pass


class NotReady(RuntimeError):
    pass


def money(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(Decimal("0.01"))


class CaseService:
    def __init__(self, settings: Settings, store: Store, ref: sqlite3.Connection) -> None:
        self.settings, self.store, self.ref = settings, store, ref

    def _llm(self) -> LLMClient | None:
        if self.settings.llm_factory:
            return self.settings.llm_factory(self.store)
        return None if self.settings.offline else LLMClient(sink=self.store)

    # --- samples ----------------------------------------------------------------------------------

    def _expected(self, name: str) -> ExpectedSample:
        path = self.settings.samples_dir / name / "expected_flags.json"
        if not re.fullmatch(r"[a-z]+", name) or not path.is_file():
            raise NotFound(name)
        return ExpectedSample.model_validate_json(path.read_text())

    def samples(self) -> list[SampleView]:
        found = []
        for name in SAMPLE_TITLES:
            if (self.settings.samples_dir / name / "expected_flags.json").is_file():
                sample = self._expected(name)
                found.append(
                    SampleView(
                        id=name, title=SAMPLE_TITLES[name], patient_type=sample.patient_type,
                        gfe_total=money(sample.gfe_total), has_eob=sample.eob is not None,
                    )
                )
        return found

    def create_from_sample(self, name: str) -> str:
        sample = self._expected(name)
        folder = self.settings.samples_dir / name
        eob = folder / "eob.pdf"
        return self.create(sample.patient_type, sample.gfe_total, folder / "bill.pdf", eob if eob.is_file() else None)

    # --- reading ----------------------------------------------------------------------------------

    def create(self, patient_type: str, gfe_total: Decimal | None, bill: Path, eob: Path | None) -> str:
        case_id = self.store.create_case(patient_type, money(gfe_total))
        llm = self._llm() if self.settings.vision else None
        reading = extract_bill(bill, self.ref, llm=llm, case_id=case_id)
        eob_reading, eob_note = None, None
        if eob and patient_type != "insured":
            eob = None  # the EOB comparison is for insured patients only
        if patient_type == "insured" and eob is None:
            eob_note = EOB_NOT_ADDED
        if eob and eob_slot_holds_the_bill(eob, reading.lines):
            eob_note = EOB_LOOKS_LIKE_BILL  # checked first: a model can read a bill's totals as an EOB's amounts
        elif eob:
            try:
                eob_reading = extract_eob(eob, llm=llm, case_id=case_id)
            except ConfigError:
                raise
            except Exception:  # noqa: BLE001 - any failure reading the optional EOB must not lose the bill
                eob_note = EOB_UNREADABLE  # The EOB is optional: keep the bill, skip the comparison and say why.
        self.store.save_lines(case_id, reading.lines)
        self.store.update_case(
            case_id,
            bill_date=reading.bill_date.isoformat() if reading.bill_date else None,
            amount_due=None if reading.amount_due is None else str(reading.amount_due),
            facility_name=reading.facility_name,
            read_with=reading.source,
            eob_json=eob_reading.model_dump_json() if eob_reading else None,
            eob_note=eob_note,
        )
        return case_id

    # --- checking ---------------------------------------------------------------------------------

    def _require(self, case_id: str) -> dict[str, str | None]:
        case = self.store.get_case(case_id) if CASE_ID.match(case_id) else None
        if case is None:
            raise NotFound(case_id)
        return case

    def confirm(self, case_id: str, request: ConfirmRequest) -> None:
        case = self._require(case_id)
        lines = [settle_line(line, self.ref) for line in request.lines]
        self.store.save_lines(case_id, lines)
        self.store.update_case(
            case_id,
            bill_date=request.bill_date.isoformat() if request.bill_date else None,
            amount_due=None if request.amount_due is None else str(request.amount_due),
            gfe_total=None if request.gfe_total is None else str(money(request.gfe_total)),
        )
        eob = EobReading.model_validate_json(case["eob_json"]) if case["eob_json"] and case["patient_type"] == "insured" else None
        result = run_checks(
            lines, ref=self.ref, patient_type=case["patient_type"] or "self_pay",
            gfe_total=money(request.gfe_total), bill_date=request.bill_date,
            amount_due=request.amount_due, eob=eob, today=self.settings.today(),
        )
        findings = result.findings
        llm = self._llm()
        if llm is not None:
            try:
                findings = judge_amber(llm, case_id, findings)
            except ConfigError:
                pass  # no key or model: amber flags stay amber
        self.store.save_findings(case_id, [f.model_dump_json() for f in findings])
        self.store.save_letters(case_id, {})
        self.store.update_case(case_id, stage="results")

    # --- views ------------------------------------------------------------------------------------

    def view(self, case_id: str) -> CaseView:
        case = self._require(case_id)
        lines = self.store.lines(case_id)
        results = None
        if case["stage"] == "results":
            findings = [Finding.model_validate_json(body) for body in self.store.findings(case_id)]
            deadline = next((f.deadline for f in findings if f.check == "gfe" and f.deadline), None)
            total = charges(lines, list(range(1, len(lines) + 1)))
            gfe = money(Decimal(case["gfe_total"])) if case["gfe_total"] else None
            results = ResultsView(
                findings=findings, dollars_at_stake=total_dollars_at_stake(findings, lines), deadline=deadline,
                likely_error_count=sum(
                    1 for f in findings if f.level == "red" and f.check != "gfe" and not f.billing_review
                ),
                total_charges=total,
                gfe_overage=total - gfe if gfe is not None and case["patient_type"] == "self_pay" else None,
            )
        return CaseView(
            id=case_id, patient_type=case["patient_type"], stage=case["stage"] or "confirm",
            read_with=case["read_with"], facility_name=case["facility_name"],
            bill_date=case["bill_date"], amount_due=case["amount_due"], gfe_total=case["gfe_total"],
            eob=EobReading.model_validate_json(case["eob_json"]) if case["eob_json"] else None,
            eob_note=case["eob_note"], lines=lines, results=results, lookup=self._stored_lookup(case),
            calls=[
                CallView(step=c.step, model=c.model, latency_ms=c.latency_ms, prompt_tokens=c.prompt_tokens,
                         completion_tokens=c.completion_tokens, ok=c.ok)
                for c in self.store.calls(case_id)
            ],
        )

    # --- hospital lookup --------------------------------------------------------------------------

    @staticmethod
    def _stored_lookup(case: dict[str, str | None]) -> HospitalLookup | None:
        return HospitalLookup.model_validate_json(case["lookup_json"]) if case["lookup_json"] else None

    def lookup(self, case_id: str, hospital_name: str | None = None) -> None:
        """Search the web for the hospital (the name on the bill, or the demo name), keep the result with the
        case and drop any letters already written so the next ones carry the address. Only the name is sent."""
        case = self._require(case_id)
        if case["stage"] != "results":
            raise NotReady("check the bill first")
        result = lookup_hospital(
            hospital_name or case["facility_name"] or "",
            search=None if self.settings.offline else self.settings.search,
            llm=self._llm(), case_id=case_id, sink=self.store,
        )
        self.store.update_case(case_id, lookup_json=result.model_dump_json())
        self.store.save_letters(case_id, {})

    # --- letters ----------------------------------------------------------------------------------

    def letters(self, case_id: str) -> list[Letter]:
        case = self._require(case_id)
        if case["stage"] != "results":
            raise NotReady("confirm the bill lines first")
        stored = self.store.letters(case_id)
        if not stored:
            findings = [Finding.model_validate_json(body) for body in self.store.findings(case_id)]
            found = self._stored_lookup(case)
            recipient: Recipient | None = found.recipient() if found else None
            try:
                built = build_letters(
                    findings, facility_name=case["facility_name"], llm=self._llm(), case_id=case_id,
                    today=self.settings.today(), recipient=recipient,
                )
            except ConfigError:
                built = build_letters(findings, facility_name=case["facility_name"], llm=None, case_id=case_id,
                                      today=self.settings.today(), recipient=recipient)
            self.store.save_letters(case_id, {letter.kind: letter.model_dump_json() for letter in built})
            stored = self.store.letters(case_id)
        return [Letter.model_validate_json(body) for body in stored.values()]

    def letter(self, case_id: str, kind: str) -> Letter:
        for letter in self.letters(case_id):
            if letter.kind == kind:
                return letter
        raise NotFound(kind)

    @staticmethod
    def letter_views(case_id: str, letters: list[Letter]) -> list[LetterView]:
        return [
            LetterView(kind=x.kind, title=x.title, text=x.text, body_html=letter_body(x.html),
                       pdf_url=f"/api/cases/{case_id}/letters/{x.kind}.pdf")
            for x in letters
        ]
