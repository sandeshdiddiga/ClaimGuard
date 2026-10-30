"""Letters are templates filled from stored findings; Super writes only the explanatory paragraph."""

import json
import re
import sqlite3

import pytest

from app.findings import Finding
from app.letters.render import FOOTER, Recipient, build_letters, render_pdf
from app.llm import LLMClient
from app.textguard import has_banned_term
from tests.builders import sample_audit
from tests.fakes import FakeOpenAI, ListSink

FIGURE = re.compile(r"\$[\d,]+(?:\.\d+)?")


@pytest.fixture(autouse=True)
def model_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    for role in ("READER", "CLEANER", "JUDGE", "WRITER"):
        monkeypatch.setenv(f"MODEL_{role}", f"test/{role.lower()}")


def llm_with(replies: list) -> tuple[LLMClient, FakeOpenAI, ListSink]:
    fake, sink = FakeOpenAI(replies), ListSink()
    return LLMClient(sink=sink, client=fake), fake, sink


def paragraph(text: str) -> str:
    return json.dumps({"paragraph": text})


def money_in(findings: list[Finding]) -> set[str]:
    """Every dollar amount the stored findings contain, as the letters print them."""
    values = set()
    for f in findings:
        for line in f.evidence.bill_lines:
            values.add(line.charge)
        for amount in (f.dollars_at_stake, f.overage, f.amount_billed, f.patient_responsibility, f.evidence.difference):
            if amount is not None:
                values.add(amount)
        for key in ("facility_total", "good_faith_estimate", "threshold"):
            if key in f.evidence.data_row:
                from decimal import Decimal

                values.add(Decimal(str(f.evidence.data_row[key])))
    return {f"${v:,.2f}" for v in values}


def figures(text: str) -> set[str]:
    return {f"${float(x.lstrip('$').replace(',', '')):,.2f}" for x in FIGURE.findall(text)}


def kinds(letters) -> list[str]:
    return [letter.kind for letter in letters]


def test_maya_gets_the_billing_review_and_the_gfe_letters(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("maya", ref)
    letters = build_letters(result.findings, facility_name=sample.facility_name, llm=None, case_id="c1")
    assert kinds(letters) == ["correction_request", "gfe_dispute"]


def test_dev_gets_the_eob_letter_only(ref: sqlite3.Connection) -> None:
    """His dose finding is a billing-review item (insured): shown to him, not put in a correction letter."""
    sample, _, result = sample_audit("dev", ref)
    assert any(f.check == "dose" and f.billing_review for f in result.findings)
    letters = build_letters(result.findings, facility_name=sample.facility_name, llm=None, case_id="c1")
    assert kinds(letters) == ["eob_mismatch"]


def test_the_clean_bill_gets_no_letters(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("clean", ref)
    assert build_letters(result.findings, facility_name=sample.facility_name, llm=None, case_id="c1") == []


@pytest.mark.parametrize("name", ["maya", "dev"])
def test_every_letter_ends_with_the_exact_footer(name: str, ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit(name, ref)
    for letter in build_letters(result.findings, facility_name=sample.facility_name, llm=None, case_id="c1"):
        assert letter.text.rstrip().endswith("Prepared with ClaimGuard. This is not legal advice.")
    assert FOOTER == "Prepared with ClaimGuard. This is not legal advice."


@pytest.mark.parametrize("name", ["maya", "dev"])
def test_letters_contain_no_dollar_figure_that_is_not_in_the_findings(name: str, ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit(name, ref)
    letters = build_letters(result.findings, facility_name=sample.facility_name, llm=None, case_id="c1")
    allowed = money_in(result.findings)
    for letter in letters:
        found = figures(letter.text)
        assert found, letter.kind
        assert found <= allowed, (letter.kind, found - allowed)


def test_a_paragraph_with_an_invented_amount_is_replaced(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("maya", ref)
    llm, _, _ = llm_with([paragraph("You were overcharged $9,999.00 here."), paragraph("Fine, no figures."),
                          paragraph("You were overcharged $9,999.00 here."), paragraph("Fine, no figures.")])
    letters = build_letters(result.findings, facility_name=sample.facility_name, llm=llm, case_id="c1")
    for letter in letters:
        assert "9,999" not in letter.text
    assert figures(" ".join(l.text for l in letters)) <= money_in(result.findings)


def test_a_number_the_findings_do_not_contain_is_replaced(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("maya", ref)
    llm, _, _ = llm_with([paragraph("Sixty-one of your 4242 days have passed."), paragraph("Plain words only.")] * 2)
    letters = build_letters(result.findings, facility_name=sample.facility_name, llm=llm, case_id="c1")
    assert all("4242" not in letter.text for letter in letters)


def test_a_valid_paragraph_from_super_is_used(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("dev", ref)
    llm, _, _ = llm_with([paragraph("I am writing about my balance, which looks higher than my EOB shows.")])
    (letter,) = build_letters(result.findings, facility_name=sample.facility_name, llm=llm, case_id="c1")
    assert "looks higher than my EOB shows" in letter.text


def test_super_gets_only_the_stored_facts(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("dev", ref)
    llm, fake, sink = llm_with([paragraph("About my balance.")])
    build_letters(result.findings, facility_name=sample.facility_name, llm=llm, case_id="c1")
    sent = json.dumps(fake.completions.requests[0]["messages"])
    assert "1,460.00" in sent and "410.00" in sent
    (_, record), = sink.records
    assert record.step == "draft_letter"


def test_an_unusable_super_reply_falls_back_to_the_template_text(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("dev", ref)
    llm, _, _ = llm_with(["nope", "nope"])
    (letter,) = build_letters(result.findings, facility_name=sample.facility_name, llm=llm, case_id="c1")
    assert "$1,460.00" in letter.text and "$410.00" in letter.text


@pytest.mark.parametrize("bad", ["That is an illegal charge.", "We will sue you.", "This is fraud."])
def test_banned_words_from_super_are_replaced(bad: str, ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("dev", ref)
    llm, _, _ = llm_with([paragraph(bad)])
    (letter,) = build_letters(result.findings, facility_name=sample.facility_name, llm=llm, case_id="c1")
    assert bad not in letter.text


@pytest.mark.parametrize("name", ["maya", "dev"])
def test_no_letter_contains_the_word_illegal(name: str, ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit(name, ref)
    for letter in build_letters(result.findings, facility_name=sample.facility_name, llm=None, case_id="c1"):
        assert not has_banned_term(letter.html)
        assert "illegal" not in letter.html.lower()


def test_the_coding_letter_lists_flagged_lines_with_reasons(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("maya", ref)
    letters = build_letters(result.findings, facility_name=sample.facility_name, llm=None, case_id="c1")
    text = letters[0].text
    for code in ("G0121", "J2250", "J2704", "A4216"):  # units, duplicate, dose, units (worth asking about)
        assert code in text
    assert "Ask the billing office to confirm or remove it." in text
    assert "coding review" not in text and "billing review" in text
    assert "corrected itemized bill" in text and "billing hold" in text
    assert "[account number]" in text  # the patient fills it in; it is never extracted


def test_the_gfe_letter_has_estimate_billed_difference_and_deadline(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("maya", ref)
    text = build_letters(result.findings, facility_name=sample.facility_name, llm=None, case_id="c1")[1].text
    for needle in ("$3,400.00", "$7,383.00", "$3,983.00", "February 2, 2027", "October 5, 2026", "120"):
        assert needle in text
    assert "Good Faith Estimate" in text and "attach" in text.lower()


def test_the_facility_name_is_escaped(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("dev", ref)
    (letter,) = build_letters(result.findings, facility_name="<script>x</script>", llm=None, case_id="c1")
    assert "<script>" not in letter.html


def test_a_letter_renders_as_a_pdf_with_the_footer(ref: sqlite3.Connection) -> None:
    try:
        import weasyprint  # noqa: F401
    except OSError:
        pytest.skip("WeasyPrint needs pango: brew install pango, and DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib")
    import io

    import pdfplumber

    sample, _, result = sample_audit("dev", ref)
    (letter,) = build_letters(result.findings, facility_name=sample.facility_name, llm=None, case_id="c1")
    pdf = render_pdf(letter)
    assert pdf.startswith(b"%PDF")
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        assert "Prepared with ClaimGuard. This is not legal advice." in "\n".join(p.extract_text() or "" for p in doc.pages)


# --- the new findings in the letters ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["maya", "dev", "clean"])
def test_no_letter_shows_a_dollar_figure_the_findings_do_not_contain(name: str, ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit(name, ref)
    allowed = money_in(result.findings)
    for llm in (None, llm_with([paragraph("I am writing about my bill, which looks different from what I expected.")] * 3)[0]):
        for letter in build_letters(result.findings, facility_name=sample.facility_name, llm=llm, case_id="c1"):
            assert figures(letter.text) <= allowed, (letter.kind, figures(letter.text) - allowed)


def test_every_amount_in_the_correction_letter_is_a_finding_amount(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("maya", ref)
    (letter, _) = build_letters(result.findings, facility_name=sample.facility_name, llm=None, case_id="c1")
    assert {"$5,600.00", "$68.00", "$1,100.00", "$255.00"} <= figures(letter.text)  # the flagged lines' charges
    assert "$2,800.00" in letter.text and "$990.00" in letter.text  # the amounts in question (excess units)


def test_the_correction_letter_explains_each_finding_with_its_units_and_limit(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("maya", ref)
    text = build_letters(result.findings, facility_name=sample.facility_name, llm=None, case_id="c1")[0].text
    assert "CMS normally allows at most 1 units of this per day. 2 were billed." in text
    assert "Your bill says 200 mg, which is 20 billing units for this drug, but 200 units were charged." in text
    assert "CMS normally allows at most 25 units of this per day. 30 were billed." in text
    assert "I would like this reviewed." in text  # the worth-asking-about line
    assert "Units" in text  # the table shows units billed


def test_the_correction_letter_never_says_a_charge_is_wrong_or_names_a_benchmark(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("maya", ref)
    text = build_letters(result.findings, facility_name=sample.facility_name, llm=None, case_id="c1")[0].text.lower()
    for banned in ("medicare's payment limit", "× ", "overcharg", "coding review", "unbundl"):
        assert banned not in text, banned
    assert "source: cms medicare ncci mue table" in text  # the MUE table is cited by its name, with its URL


def test_the_super_facts_for_the_correction_letter_carry_units_and_the_wording(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("maya", ref)
    llm, fake, _ = llm_with([paragraph("About my bill."), paragraph("About my estimate.")])
    build_letters(result.findings, facility_name=sample.facility_name, llm=llm, case_id="c1")
    first = json.dumps(fake.completions.requests[0]["messages"])
    assert "200 units were charged" in first and "30 were billed" in first and "units 30" in first


# --- addressing the letters --------------------------------------------------------------------------------------


def letters_for(name: str, ref, **kwargs):
    sample, _, result = sample_audit(name, ref)
    return build_letters(result.findings, facility_name=sample.facility_name, llm=None, case_id="c1", **kwargs)


def test_without_a_lookup_the_billing_office_is_left_blank_to_fill_in(ref: sqlite3.Connection) -> None:
    for letter in letters_for("maya", ref):
        assert "To: Riverbend Community Hospital" in letter.text
        assert "[billing office address]" in letter.text


def test_a_lookup_result_addresses_every_letter(ref: sqlite3.Connection) -> None:
    recipient = Recipient(name="Riverbend Community Hospital Billing Office", address="2100 Riverside Drive, Millbrook")
    letters = letters_for("maya", ref, recipient=recipient)
    assert len(letters) == 2
    for letter in letters:
        assert "To: Riverbend Community Hospital Billing Office" in letter.text
        assert "2100 Riverside Drive, Millbrook" in letter.text
        assert "[billing office address]" not in letter.text


def test_a_lookup_with_no_address_keeps_the_blank_for_it(ref: sqlite3.Connection) -> None:
    letters = letters_for("dev", ref, recipient=Recipient(name="Riverbend Billing", address=None))
    assert "To: Riverbend Billing" in letters[0].text and "[billing office address]" in letters[0].text


def test_the_recipient_is_escaped_and_kept_to_one_short_line(ref: sqlite3.Connection) -> None:
    hostile = Recipient(name="<script>alert(1)</script>", address="Line one\nLine two " + "x" * 500)
    (letter,) = letters_for("dev", ref, recipient=hostile)
    assert "<script>" not in letter.html
    assert "\n" not in hostile.address and len(hostile.address) <= 200


def test_a_lookup_adds_no_figure_to_a_letter(ref: sqlite3.Connection) -> None:
    sample, _, result = sample_audit("maya", ref)
    recipient = Recipient(name="Riverbend Billing", address="2100 Riverside Drive, Millbrook")
    for letter in build_letters(result.findings, facility_name=None, llm=None, case_id="c1", recipient=recipient):
        assert figures(letter.text) <= money_in(result.findings)


# --- nothing we write says "illegal" -----------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["maya", "dev", "clean"])
def test_no_finding_letter_or_redirect_contains_illegal(name: str, ref: sqlite3.Connection) -> None:
    from app.safety import REDIRECTS

    sample, _, result = sample_audit(name, ref)
    texts = [REDIRECTS[key] for key in REDIRECTS]
    for finding in result.findings:
        texts += [finding.wording, finding.evidence.rule, *map(str, finding.evidence.data_row.values())]
    for letter in letters_for(name, ref, recipient=Recipient(name="Billing Office", address="1 Main St")):
        texts += [letter.html, letter.text, letter.title]
    for text in texts:
        assert not has_banned_term(text), text
        assert "illegal" not in text.lower(), text
