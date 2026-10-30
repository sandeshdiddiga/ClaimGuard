"""The web API end to end, with the fixture reference DB and no network."""

import io
import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.llm import LLMClient
from app.main import create_app
from app.settings import Settings
from tests.fakes import FakeOpenAI

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
TODAY = date(2026, 10, 28)


@pytest.fixture(autouse=True)
def model_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    for role in ("READER", "CLEANER", "JUDGE", "WRITER"):
        monkeypatch.setenv(f"MODEL_{role}", f"test/{role.lower()}")


def make_client(tmp_path: Path, reference_db_path: Path, **overrides) -> TestClient:
    settings = Settings(
        reference_db=reference_db_path, state_db=tmp_path / "state.db", samples_dir=SAMPLES,
        static_dir=overrides.pop("static_dir", None), offline=overrides.pop("offline", True), vision=overrides.pop("vision", False),
        today=lambda: TODAY, **overrides,
    )
    return TestClient(create_app(settings))


@pytest.fixture
def client(tmp_path: Path, reference_db_path: Path) -> TestClient:
    return make_client(tmp_path, reference_db_path)


def upload(client: TestClient, name: str = "maya", **form: str):
    form = {"patient_type": "self_pay", "gfe_total": "3400", **form}
    with (SAMPLES / name / "bill.pdf").open("rb") as bill:
        return client.post("/api/cases", data=form, files={"bill": ("bill.pdf", bill, "application/pdf")})


def confirm(client: TestClient, case: dict):
    body = {"lines": case["lines"], "bill_date": case["bill_date"], "amount_due": case["amount_due"],
            "gfe_total": case["gfe_total"]}
    return client.put(f"/api/cases/{case['id']}/lines", json=body)


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_samples_are_listed(client: TestClient) -> None:
    samples = {s["id"]: s for s in client.get("/api/samples").json()}
    assert set(samples) == {"maya", "dev", "clean"}
    assert samples["maya"]["patient_type"] == "self_pay" and samples["dev"]["patient_type"] == "insured"


def test_a_sample_creates_a_case_ready_to_confirm(client: TestClient) -> None:
    response = client.post("/api/cases/sample/maya")
    assert response.status_code == 201
    case = response.json()
    assert case["stage"] == "confirm" and case["patient_type"] == "self_pay"
    assert case["gfe_total"] == "3400.00" and case["amount_due"] == "7383.00"
    assert [line["code"] for line in case["lines"]] == ["G0121", "J2250", "J2250", "J3010", "J2704", "J2405", "J7120", "A4216"]
    assert case["results"] is None


def test_unknown_sample_is_404(client: TestClient) -> None:
    assert client.post("/api/cases/sample/nope").status_code == 404


def test_uploading_a_bill_reads_the_lines(client: TestClient) -> None:
    response = upload(client)
    assert response.status_code == 201
    assert len(response.json()["lines"]) == 8


def test_confirming_runs_the_checks_and_stores_the_results(client: TestClient) -> None:
    case = client.post("/api/cases/sample/maya").json()
    body = confirm(client, case).json()
    assert body["stage"] == "results"
    assert ("duplicate", "red") in {(f["check"], f["level"]) for f in body["results"]["findings"]}
    assert body["results"]["deadline"] == "2027-02-02"


def test_confirming_runs_the_checks(client: TestClient) -> None:
    case = client.post("/api/cases/sample/maya").json()
    result = confirm(client, case)
    assert result.status_code == 200
    body = result.json()
    assert body["stage"] == "results"
    findings = body["results"]["findings"]
    assert sorted((f["check"], f["level"]) for f in findings if f["level"] != "grey") == [
        ("dose", "red"), ("duplicate", "red"), ("gfe", "red"), ("units", "amber"), ("units", "red"),
    ]
    assert body["results"]["dollars_at_stake"] == "3858.00"
    assert body["results"]["deadline"] == "2027-02-02"


def test_dollars_at_stake_come_from_red_findings_only(client: TestClient) -> None:
    body = confirm(client, client.post("/api/cases/sample/maya").json()).json()
    levels = {f["level"] for f in body["results"]["findings"]}
    assert levels == {"red", "amber", "grey"}
    assert body["results"]["dollars_at_stake"] == "3858.00"  # amber and grey add nothing


def test_editing_a_line_changes_the_findings(client: TestClient) -> None:
    case = client.post("/api/cases/sample/maya").json()
    case["lines"][2]["code"] = "J2405"  # no longer a duplicate of line 2
    body = confirm(client, case).json()
    assert "duplicate" not in {f["check"] for f in body["results"]["findings"]}


def test_a_sample_case_carries_code_classes_and_doses(client: TestClient) -> None:
    case = client.post("/api/cases/sample/maya").json()
    assert {line["code_class"] for line in case["lines"]} == {"hcpcs_level2"}
    midazolam = case["lines"][1]
    assert (midazolam["dose_value"], midazolam["dose_unit"]) == ("2", "MG")
    assert (case["lines"][0]["dose_value"], case["lines"][0]["dose_unit"]) == (None, None)  # the colonoscopy


def test_confirming_re_derives_the_dose_from_an_edited_description(client: TestClient) -> None:
    case = client.post("/api/cases/sample/maya").json()
    case["lines"][1]["description"] = "Rev 0636 Midazolam HCl inj 5 mg"  # the patient corrected the dose
    body = confirm(client, case).json()
    assert (body["lines"][1]["dose_value"], body["lines"][1]["dose_unit"]) == ("5", "MG")


def test_a_dose_the_description_does_not_state_is_dropped_on_confirm(client: TestClient) -> None:
    case = client.post("/api/cases/sample/maya").json()
    case["lines"][0]["dose_value"], case["lines"][0]["dose_unit"] = "9", "MG"  # the colonoscopy has no dose
    body = confirm(client, case).json()
    assert (body["lines"][0]["dose_value"], body["lines"][0]["dose_unit"]) == (None, None)


def test_confirming_re_classifies_codes_and_never_looks_up_a_cpt_shaped_one(client: TestClient) -> None:
    case = client.post("/api/cases/sample/maya").json()
    case["lines"][2]["code"] = "0000F"  # synthetic CPT-shaped value
    case["lines"][3]["code"] = "Z9999"
    body = confirm(client, case).json()
    assert body["lines"][2]["code_class"] == "cpt_shaped"
    assert body["lines"][2]["note"] == "Not checked: CPT codes need an AMA license, which this demo doesn't use."
    assert body["lines"][3]["code_class"] == "unknown_level2"
    assert body["lines"][3]["note"] == "Not in CMS's current HCPCS list."


def test_a_malformed_code_is_rejected(client: TestClient) -> None:
    case = client.post("/api/cases/sample/maya").json()
    case["lines"][0]["code"] = "<script>"
    assert confirm(client, case).status_code == 422


def test_the_clean_sample_has_no_red_or_amber(client: TestClient) -> None:
    case = client.post("/api/cases/sample/clean").json()
    findings = confirm(client, case).json()["results"]["findings"]
    assert {f["level"] for f in findings} <= {"grey"}


def test_an_insured_sample_checks_the_eob(client: TestClient) -> None:
    case = client.post("/api/cases/sample/dev").json()
    body = confirm(client, case).json()
    assert ("eob", "red") in {(f["check"], f["level"]) for f in body["results"]["findings"]}
    assert body["results"]["dollars_at_stake"] == "1050.00"


def test_get_returns_the_case_and_the_call_log(tmp_path: Path, reference_db_path: Path) -> None:
    replies = [json.dumps({"decision": "keep", "reason": "Nothing on the bill explains 30 flushes."})]
    fake = FakeOpenAI(replies)
    client = make_client(
        tmp_path, reference_db_path, llm_factory=lambda store: LLMClient(sink=store, client=fake),
    )
    case = client.post("/api/cases/sample/maya").json()
    confirm(client, case)
    body = client.get(f"/api/cases/{case['id']}").json()
    (call,) = body["calls"]
    assert (call["step"], call["model"], call["ok"]) == ("judge_amber", "test/judge", True)
    assert call["latency_ms"] >= 0 and call["prompt_tokens"] == 11 and call["completion_tokens"] == 7
    amber = [f for f in body["results"]["findings"] if f["level"] == "amber"]
    assert amber and amber[0]["judge_reason"] == "Nothing on the bill explains 30 flushes."


def test_the_call_log_never_holds_document_text(tmp_path: Path, reference_db_path: Path) -> None:
    fake = FakeOpenAI([json.dumps({"decision": "keep", "reason": "ok"})])
    client = make_client(tmp_path, reference_db_path, llm_factory=lambda s: LLMClient(sink=s, client=fake))
    case = client.post("/api/cases/sample/maya").json()
    confirm(client, case)
    text = json.dumps(client.get(f"/api/cases/{case['id']}").json()["calls"])
    assert "Midazolam" not in text and "colonoscopy" not in text and "G0121" not in text


def test_unknown_or_malformed_case_ids_are_404(client: TestClient) -> None:
    assert client.get("/api/cases/" + "0" * 32).status_code == 404
    assert client.get("/api/cases/not-an-id").status_code == 404


def test_letters_need_results_first(client: TestClient) -> None:
    case = client.post("/api/cases/sample/maya").json()
    assert client.post(f"/api/cases/{case['id']}/letters").status_code == 409


def test_letters_are_listed_and_download_as_pdf(client: TestClient) -> None:
    case = client.post("/api/cases/sample/maya").json()
    confirm(client, case)
    letters = client.post(f"/api/cases/{case['id']}/letters").json()
    assert [x["kind"] for x in letters] == ["correction_request", "gfe_dispute"]
    try:
        import weasyprint  # noqa: F401
    except OSError:
        pytest.skip("WeasyPrint needs pango")
    response = client.get(f"/api/cases/{case['id']}/letters/gfe_dispute.pdf")
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert "attachment" in response.headers["content-disposition"]
    assert client.get(f"/api/cases/{case['id']}/letters/other.pdf").status_code == 404


def test_the_page_shown_after_confirming_can_be_reloaded(client: TestClient) -> None:
    case = client.post("/api/cases/sample/maya").json()
    shown = confirm(client, case).json()
    again = client.get(f"/api/cases/{case['id']}").json()
    assert again["stage"] == "results" and again["results"] == shown["results"]


# --- upload limits -------------------------------------------------------------------------------


def test_a_text_file_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/cases", data={"patient_type": "self_pay"}, files={"bill": ("notes.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 415


def test_content_that_does_not_match_the_type_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/cases", data={"patient_type": "self_pay"}, files={"bill": ("bill.pdf", b"MZ not a pdf", "application/pdf")}
    )
    assert response.status_code == 422


def test_an_oversized_upload_is_rejected(tmp_path: Path, reference_db_path: Path) -> None:
    client = make_client(tmp_path, reference_db_path, max_upload_bytes=1000)
    response = upload(client)
    assert response.status_code == 413


def test_errors_do_not_echo_the_file_name(client: TestClient) -> None:
    response = client.post(
        "/api/cases", data={"patient_type": "self_pay"},
        files={"bill": ("Jane_Doe_99887766.pdf", b"not a pdf", "application/pdf")},
    )
    assert "Jane" not in response.text and "99887766" not in response.text


def test_an_image_is_refused_without_the_vision_model(client: TestClient) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (30, 30), "white").save(buffer, format="PNG")
    response = client.post(
        "/api/cases", data={"patient_type": "self_pay"}, files={"bill": ("photo.png", buffer.getvalue(), "image/png")}
    )
    assert response.status_code == 422


def test_bad_form_values_are_rejected(client: TestClient) -> None:
    assert upload(client, patient_type="medicare").status_code == 422
    assert upload(client, gfe_total="-5").status_code == 422
    assert upload(client, gfe_total="abc").status_code == 422


def test_uploads_are_rate_limited(tmp_path: Path, reference_db_path: Path) -> None:
    client = make_client(tmp_path, reference_db_path, max_cases_per_hour=2)
    assert [client.post("/api/cases/sample/clean").status_code for _ in range(3)] == [201, 201, 429]


def test_uploaded_files_are_not_kept(tmp_path: Path, reference_db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path / "scratch"))
    (tmp_path / "scratch").mkdir()
    import tempfile

    tempfile.tempdir = None
    client = make_client(tmp_path, reference_db_path)
    assert upload(client).status_code == 201
    assert list((tmp_path / "scratch").iterdir()) == []


# --- serving the front end -----------------------------------------------------------------------


def test_the_built_front_end_is_served(tmp_path: Path, reference_db_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    client = make_client(tmp_path, reference_db_path, static_dir=dist)
    response = client.get("/")
    assert response.status_code == 200 and "app" in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in response.headers["content-security-policy"]


# --- the summary the results page leads with ----------------------------------------------------------------


def test_results_carry_the_summary_numbers(client: TestClient) -> None:
    body = confirm(client, client.post("/api/cases/sample/maya").json()).json()["results"]
    assert body["likely_error_count"] == 3  # units, duplicate, dose; the Good Faith Estimate is separate
    assert body["dollars_at_stake"] == "3858.00"
    assert body["total_charges"] == "7383.00"
    assert body["gfe_overage"] == "3983.00"


def test_the_clean_bill_still_reports_how_far_over_the_estimate_it_is(client: TestClient) -> None:
    body = confirm(client, client.post("/api/cases/sample/clean").json()).json()["results"]
    assert (body["likely_error_count"], body["dollars_at_stake"]) == (0, "0.00")
    assert body["gfe_overage"] == "339.50"  # under the $400 threshold: no finding, but the patient sees it


def test_an_insured_bill_has_no_estimate_overage(client: TestClient) -> None:
    body = confirm(client, client.post("/api/cases/sample/dev").json()).json()["results"]
    assert body["gfe_overage"] is None
    assert body["likely_error_count"] == 1  # the EOB difference; his dose line is a billing review, not counted


def test_letters_come_with_a_body_to_preview_without_page_styles_or_scripts(client: TestClient) -> None:
    case = client.post("/api/cases/sample/maya").json()
    confirm(client, case)
    letters = client.post(f"/api/cases/{case['id']}/letters").json()
    body = letters[0]["body_html"]
    assert "<table>" in body and "Prepared with ClaimGuard. This is not legal advice." in body
    for banned in ("<style", "<script", "<html", "<head", "<body"):
        assert banned not in body.lower()


def test_a_case_keeps_the_facility_name_from_the_reading(tmp_path: Path, reference_db_path: Path) -> None:
    reading = {"facility_name": "Riverbend Community Hospital", "bill_date": "2026-10-05", "lines": [
        {"service_date": "2026-09-14", "code": "G0121", "description": "Screening colonoscopy", "units": 1, "charge": "2800.00"},
    ]}
    gate = {"is_itemized_bill": True}
    fake = FakeOpenAI([json.dumps(reading), json.dumps(gate)])
    client = make_client(tmp_path, reference_db_path, llm_factory=lambda store: LLMClient(sink=store, client=fake), vision=True)
    case = upload(client).json()
    assert case["facility_name"] == "Riverbend Community Hospital"


# --- the EOB is optional ----------------------------------------------------------------------------

from app.extract import EOB_NOT_ADDED, EOB_UNREADABLE as EOB_NOTE  # noqa: E402


def upload_insured(client: TestClient, eob: Path | None, bill: str = "dev"):
    files = {"bill": ("bill.pdf", (SAMPLES / bill / "bill.pdf").read_bytes(), "application/pdf")}
    if eob is not None:
        files["eob"] = ("eob.pdf", eob.read_bytes(), "application/pdf")
    return client.post("/api/cases", data={"patient_type": "insured"}, files=files)


def checks_of(client: TestClient, case: dict) -> set[str]:
    return {f["check"] for f in confirm(client, case).json()["results"]["findings"]}


def test_an_insured_case_without_an_eob_runs_every_check_but_the_eob_comparison(client: TestClient) -> None:
    response = upload_insured(client, None)
    assert response.status_code == 201
    case = response.json()
    assert case["eob"] is None and case["eob_note"] == EOB_NOT_ADDED and len(case["lines"]) > 0
    assert "eob" not in checks_of(client, case)


def test_an_unreadable_eob_does_not_block_the_case(client: TestClient, tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas

    junk = tmp_path / "junk.pdf"
    page = canvas.Canvas(str(junk))
    page.drawString(72, 720, "Cover letter. Nothing about benefits here.")
    page.save()
    response = upload_insured(client, junk)
    assert response.status_code == 201
    case = response.json()
    assert case["eob"] is None and case["eob_note"] == EOB_NOTE
    assert len(case["lines"]) > 0
    assert "eob" not in checks_of(client, case)


def test_a_bill_in_the_eob_slot_is_named_in_the_note(client: TestClient) -> None:
    response = upload_insured(client, SAMPLES / "dev" / "bill.pdf")
    assert response.status_code == 201
    case = response.json()
    assert case["eob"] is None
    assert case["eob_note"].startswith(EOB_NOTE) and "looks like the hospital bill" in case["eob_note"]
    assert "eob" not in checks_of(client, case)


def test_a_readable_eob_has_no_note_and_is_compared(client: TestClient) -> None:
    case = upload_insured(client, SAMPLES / "dev" / "eob.pdf").json()
    assert case["eob"] is not None and case["eob_note"] is None
    assert "eob" in checks_of(client, case)


def test_the_note_survives_confirming(client: TestClient) -> None:
    case = upload_insured(client, SAMPLES / "dev" / "bill.pdf").json()
    confirm(client, case)
    assert client.get(f"/api/cases/{case['id']}").json()["eob_note"].startswith(EOB_NOTE)


def test_an_eob_sent_with_a_self_pay_case_is_ignored(client: TestClient) -> None:
    files = {
        "bill": ("bill.pdf", (SAMPLES / "dev" / "bill.pdf").read_bytes(), "application/pdf"),
        "eob": ("eob.pdf", (SAMPLES / "dev" / "eob.pdf").read_bytes(), "application/pdf"),
    }
    case = client.post("/api/cases", data={"patient_type": "self_pay"}, files=files).json()
    assert case["eob"] is None and "eob" not in checks_of(client, case)


def test_a_bill_in_the_eob_slot_is_refused_even_when_the_model_reads_plausible_amounts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decimal import Decimal

    from app.extract import EobExtraction

    plausible = EobExtraction(billed=Decimal("3244.00"), allowed=Decimal("3244.00"),
                              patient_responsibility=Decimal("1460.00"), source="vision")
    monkeypatch.setattr("app.cases.extract_eob", lambda *a, **k: plausible)
    case = upload_insured(client, SAMPLES / "dev" / "bill.pdf").json()
    assert case["eob"] is None and "looks like the hospital bill" in case["eob_note"]
