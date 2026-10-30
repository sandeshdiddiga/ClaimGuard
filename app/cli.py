"""Command line entry points.  Usage: python -m app.cli extract|eob|audit <file> ..."""

import argparse
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv

from app.audit import run_checks
from app.judge import judge_amber
from app.letters.render import build_letters, render_pdf
from app.extract import ExtractionError, extract_bill, extract_eob
from app.llm import LLMClient
from app.refdb import open_reference
from app.store import Store

DEFAULT_REFERENCE_DB = Path("data/claimguard.db")
DEFAULT_STATE_DB = Path("data/state.db")


def cmd_extract(args: argparse.Namespace) -> int:
    ref = open_reference(args.reference_db)
    store = Store(args.state_db)
    case_id = store.create_case("self_pay")
    llm = None if args.offline else LLMClient(sink=store)
    try:
        result = extract_bill(args.file, ref, llm=llm, case_id=case_id)
    except ExtractionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"read with {result.source}; bill date {result.bill_date}; balance due {result.amount_due}")
    for number, line in enumerate(result.lines, start=1):
        flag = "" if line.status == "ok" else f"  [{line.status}: {line.note}]"
        print(f"{number:>2}  {line.service_date}  {line.code:<6} {line.units:>3}  {line.charge:>10}  {line.description}{flag}")
    store.save_lines(case_id, result.lines)
    for call in store.calls(case_id):
        print(f"call {call.step:<12} {call.model}  {call.latency_ms} ms  tokens {call.prompt_tokens}/{call.completion_tokens}  ok={call.ok}")
    return 0


def cmd_eob(args: argparse.Namespace) -> int:
    store = Store(args.state_db)
    case_id = store.create_case("insured")
    llm = None if args.offline else LLMClient(sink=store)
    try:
        eob = extract_eob(args.file, llm=llm, case_id=case_id)
    except ExtractionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"read with {eob.source}: billed {eob.billed}, allowed {eob.allowed}, patient responsibility {eob.patient_responsibility}")
    for call in store.calls(case_id):
        print(f"call {call.step:<12} {call.model}  {call.latency_ms} ms  tokens {call.prompt_tokens}/{call.completion_tokens}  ok={call.ok}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Read the bill (no model calls: pdfplumber) and print every finding with its evidence."""
    ref = open_reference(args.reference_db)
    try:
        bill = extract_bill(args.file, ref, llm=None, case_id="cli")
        eob = extract_eob(args.eob, llm=None, case_id="cli") if args.eob else None
        gfe = Decimal(args.gfe) if args.gfe else None
    except (ExtractionError, InvalidOperation) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    patient_type = "insured" if args.insured else "self_pay"
    result = run_checks(
        bill.lines, ref=ref, patient_type=patient_type, gfe_total=gfe, bill_date=bill.bill_date,
        amount_due=bill.amount_due, eob=eob,
    )
    for finding in result.findings:
        where = f" lines {finding.line_numbers}" if finding.line_numbers else ""
        print(f"[{finding.level.upper():<5}] {finding.check}{where}: {finding.wording}")
        evidence = finding.evidence
        print(f"          rule: {evidence.rule}")
        print(f"          data: {evidence.data_row}")
        if evidence.difference is not None:
            print(f"          difference: ${evidence.difference:,.2f}")
        print(f"          source: {evidence.source_name}{' ' + evidence.source_url if evidence.source_url else ''}")
    print(f"dollars at stake (red findings only): ${result.dollars_at_stake:,.2f}")
    if result.deadline:
        print(f"dispute deadline: {result.deadline.isoformat()}")
    return 0


def cmd_letters(args: argparse.Namespace) -> int:
    """Audit a bill, let Ultra review amber flags, and write the letters (HTML and PDF) to --out."""
    ref = open_reference(args.reference_db)
    store = Store(args.state_db)
    patient_type = "insured" if args.insured else "self_pay"
    case_id = store.create_case(patient_type)
    llm = None if args.offline else LLMClient(sink=store)
    try:
        bill = extract_bill(args.file, ref, llm=None, case_id=case_id)
        eob = extract_eob(args.eob, llm=None, case_id=case_id) if args.eob else None
        gfe = Decimal(args.gfe) if args.gfe else None
    except (ExtractionError, InvalidOperation) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    result = run_checks(
        bill.lines, ref=ref, patient_type=patient_type, gfe_total=gfe, bill_date=bill.bill_date,
        amount_due=bill.amount_due, eob=eob,
    )
    findings = judge_amber(llm, case_id, result.findings) if llm else result.findings
    for finding in findings:
        if finding.judge_decision:
            print(f"Ultra on {finding.codes}: {finding.judge_decision} ({finding.judge_reason})")
    args.out.mkdir(parents=True, exist_ok=True)
    for letter in build_letters(findings, facility_name=None, llm=llm, case_id=case_id):
        (args.out / f"{letter.kind}.html").write_text(letter.html)
        try:
            (args.out / f"{letter.kind}.pdf").write_bytes(render_pdf(letter))
        except OSError:
            print("PDF skipped: WeasyPrint needs pango (see README)", file=sys.stderr)
        print(f"wrote {args.out / letter.kind}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("--reference-db", type=Path, default=Path(os.environ.get("REFERENCE_DB_PATH", DEFAULT_REFERENCE_DB)))
    parser.add_argument("--state-db", type=Path, default=DEFAULT_STATE_DB)
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract", help="read a bill into lines")
    extract.add_argument("file", type=Path)
    extract.add_argument("--offline", action="store_true", help="pdfplumber only; no model calls")
    extract.set_defaults(func=cmd_extract)
    eob = sub.add_parser("eob", help="read an Explanation of Benefits")
    eob.add_argument("file", type=Path)
    eob.add_argument("--offline", action="store_true", help="pdfplumber only; no model calls")
    eob.set_defaults(func=cmd_eob)
    audit = sub.add_parser("audit", help="run every check on a bill (no model calls)")
    audit.add_argument("file", type=Path)
    kind = audit.add_mutually_exclusive_group(required=True)
    kind.add_argument("--self-pay", action="store_true")
    kind.add_argument("--insured", action="store_true")
    audit.add_argument("--gfe", help="the patient's Good Faith Estimate total (self-pay)")
    audit.add_argument("--eob", type=Path, help="the insurer's EOB (insured)")
    audit.set_defaults(func=cmd_audit)
    letters = sub.add_parser("letters", help="audit a bill and write the dispute letters")
    letters.add_argument("file", type=Path)
    kind2 = letters.add_mutually_exclusive_group(required=True)
    kind2.add_argument("--self-pay", action="store_true")
    kind2.add_argument("--insured", action="store_true")
    letters.add_argument("--gfe")
    letters.add_argument("--eob", type=Path)
    letters.add_argument("--out", type=Path, default=Path("data/letters"))
    letters.add_argument("--offline", action="store_true", help="no model calls: skip Ultra, use template text")
    letters.set_defaults(func=cmd_letters)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
