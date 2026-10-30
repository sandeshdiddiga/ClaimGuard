"""The hospital lookup through the web API: Tavily and the model are fakes, the key may be unset."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.llm import LLMClient
from app.lookup import SearchHit, SearchUnavailable
from app.store import Store
from tests.test_api import confirm, make_client, model_ids  # noqa: F401  (autouse fixture)

PHONE = "(555) 010-2345"
ADDRESS = "400 Mill Road, Riverbend, OH 45000"
HITS = [SearchHit(title="Billing", url="https://riverbend.example.org/billing",
                  content=f"Billing office {PHONE}. Mail: {ADDRESS}")]


def answer(**fields) -> str:
    base = {"billing_phone": None, "billing_address": None, "billing_page_url": None, "assistance_page_url": None}
    return json.dumps({**base, **fields})


class RoutedOpenAI:
    """Answers by what is asked, so the judge, the letter paragraphs and the lookup can share one fake."""

    def __init__(self, pick_replies: list[str]) -> None:
        self.pick_replies = list(pick_replies)
        self.requests: list[dict] = []
        self.completions = self
        self.chat = self

    def create(self, **kwargs) -> SimpleNamespace:
        self.requests.append(kwargs)
        system = " ".join(str(m["content"]) for m in kwargs["messages"] if m["role"] == "system")
        if "billing_phone" in system:
            reply = self.pick_replies.pop(0)
        elif "decision" in system:
            reply = json.dumps({"decision": "keep", "reason": "Nothing on the bill explains it."})
        else:
            reply = json.dumps({"paragraph": "I am writing about charges on my bill that I would like reviewed."})
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
        )


def make(tmp_path: Path, reference_db_path: Path, *, replies: list | None = None, search="default", **overrides):
    queries: list[str] = []

    def fake_search(query: str) -> list[SearchHit]:
        queries.append(query)
        return HITS

    fake = RoutedOpenAI(replies if replies is not None else [answer(billing_phone=PHONE, billing_address=ADDRESS)])
    client = make_client(
        tmp_path, reference_db_path, offline=False,
        llm_factory=lambda store: LLMClient(sink=store, client=fake),
        search=fake_search if search == "default" else search, **overrides,
    )
    return client, queries, fake


FACILITY = "Riverbend Community Hospital"


def with_facility(tmp_path: Path, case: dict) -> None:
    """Only the vision reader returns a hospital name, and these tests read the PDF text instead."""
    store = Store(tmp_path / "state.db")
    store.update_case(case["id"], facility_name=FACILITY)
    store.close()


def results_case(client: TestClient, tmp_path: Path, sample: str = "clean") -> dict:
    case = client.post(f"/api/cases/sample/{sample}").json()
    with_facility(tmp_path, case)
    confirm(client, case)
    return client.get(f"/api/cases/{case['id']}").json()


def test_a_case_starts_without_a_lookup(tmp_path: Path, reference_db_path: Path) -> None:
    client, queries, _ = make(tmp_path, reference_db_path, replies=[])
    assert results_case(client, tmp_path)["lookup"] is None and queries == []


def test_lookup_searches_the_facility_name_from_the_bill_and_stores_the_result(tmp_path: Path, reference_db_path: Path) -> None:
    client, queries, _ = make(tmp_path, reference_db_path)
    case = results_case(client, tmp_path)
    response = client.post(f"/api/cases/{case['id']}/lookup")
    assert response.status_code == 200
    body = response.json()
    assert body["lookup"]["status"] == "found" and body["lookup"]["phone"] == PHONE
    assert body["lookup"]["verify_note"] == "Found on the web. Verify before sending."
    assert len(queries) == 2 and all("Riverbend Community Hospital" in q for q in queries)
    assert client.get(f"/api/cases/{case['id']}").json()["lookup"]["address"] == ADDRESS


def test_no_patient_data_reaches_the_search(tmp_path: Path, reference_db_path: Path) -> None:
    client, queries, fake = make(tmp_path, reference_db_path)
    case = results_case(client, tmp_path)
    client.post(f"/api/cases/{case['id']}/lookup")
    sent = " ".join(queries) + json.dumps(fake.requests)
    for private in ("Maya", "Dev ", "3400", "G0121", "J2250", case["id"]):
        assert private not in sent


def test_the_lookup_shows_in_the_call_log(tmp_path: Path, reference_db_path: Path) -> None:
    client, _, _ = make(tmp_path, reference_db_path)
    case = results_case(client, tmp_path)
    calls = client.post(f"/api/cases/{case['id']}/lookup").json()["calls"]
    assert [(c["step"], c["model"]) for c in calls] == [
        ("search_web", "tavily"), ("search_web", "tavily"), ("pick_links", "test/writer"),
    ]


def test_with_the_key_unset_the_card_says_so_and_the_rest_works(tmp_path: Path, reference_db_path: Path) -> None:
    client, _, _ = make(tmp_path, reference_db_path, replies=[], search=None)
    case = results_case(client, tmp_path)
    response = client.post(f"/api/cases/{case['id']}/lookup")
    assert response.status_code == 200
    assert response.json()["lookup"]["status"] == "unavailable"
    assert "not set up" in response.json()["lookup"]["message"]
    assert client.post(f"/api/cases/{case['id']}/letters").status_code == 200


def test_a_search_failure_does_not_break_the_case(tmp_path: Path, reference_db_path: Path) -> None:
    def broken(query: str) -> list[SearchHit]:
        raise SearchUnavailable()

    client, _, _ = make(tmp_path, reference_db_path, replies=[], search=broken)
    case = results_case(client, tmp_path)
    assert client.post(f"/api/cases/{case['id']}/lookup").json()["lookup"]["status"] == "unavailable"
    assert client.get(f"/api/cases/{case['id']}").status_code == 200


def test_offline_mode_never_searches(tmp_path: Path, reference_db_path: Path) -> None:
    queries: list[str] = []
    client = make_client(tmp_path, reference_db_path, offline=True, search=lambda q: queries.append(q) or HITS)
    case = results_case(client, tmp_path)
    assert client.post(f"/api/cases/{case['id']}/lookup").json()["lookup"]["status"] == "unavailable"
    assert queries == []


def test_the_demo_name_replaces_the_bills_hospital(tmp_path: Path, reference_db_path: Path) -> None:
    client, queries, _ = make(tmp_path, reference_db_path)
    case = results_case(client, tmp_path)
    body = client.post(f"/api/cases/{case['id']}/lookup", json={"hospital_name": "  Mercy   General Hospital "}).json()
    assert body["lookup"]["hospital_name"] == "Mercy General Hospital"
    assert all("Mercy General Hospital" in q and "Riverbend" not in q for q in queries)


@pytest.mark.parametrize("name", ["x" * 121, "Mercy\nGeneral", "Mercy\x00General"])
def test_a_bad_demo_name_is_rejected_before_any_search(tmp_path: Path, reference_db_path: Path, name: str) -> None:
    client, queries, _ = make(tmp_path, reference_db_path)
    case = results_case(client, tmp_path)
    assert client.post(f"/api/cases/{case['id']}/lookup", json={"hospital_name": name}).status_code == 422
    assert queries == []


def test_lookup_needs_results_first(tmp_path: Path, reference_db_path: Path) -> None:
    client, queries, _ = make(tmp_path, reference_db_path)
    case = client.post("/api/cases/sample/clean").json()
    with_facility(tmp_path, case)
    assert client.post(f"/api/cases/{case['id']}/lookup").status_code == 409
    assert client.post("/api/cases/" + "0" * 32 + "/lookup").status_code == 404
    assert queries == []


def test_lookups_are_rate_limited(tmp_path: Path, reference_db_path: Path) -> None:
    client, _, _ = make(tmp_path, reference_db_path, replies=[answer()] * 5, max_lookups_per_hour=2)
    case = results_case(client, tmp_path)
    codes = [client.post(f"/api/cases/{case['id']}/lookup").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_found_address_fills_the_letters_even_when_they_were_made_first(tmp_path: Path, reference_db_path: Path) -> None:
    client, _, _ = make(tmp_path, reference_db_path)
    case = results_case(client, tmp_path, "maya")
    before = client.post(f"/api/cases/{case['id']}/letters").json()
    assert before and all("[billing office address]" in letter["text"] for letter in before)

    client.post(f"/api/cases/{case['id']}/lookup")
    after = client.post(f"/api/cases/{case['id']}/letters").json()
    assert all(ADDRESS in letter["text"] and "[billing office address]" not in letter["text"] for letter in after)
    assert all("Riverbend Community Hospital, billing office" in letter["text"] for letter in after)


def test_letters_keep_the_placeholder_when_nothing_was_found(tmp_path: Path, reference_db_path: Path) -> None:
    client, _, _ = make(tmp_path, reference_db_path, replies=[answer()])
    case = results_case(client, tmp_path, "maya")
    client.post(f"/api/cases/{case['id']}/lookup")
    letters = client.post(f"/api/cases/{case['id']}/letters").json()
    assert letters and all("[billing office address]" in letter["text"] for letter in letters)


def test_the_call_log_never_holds_the_search_text(tmp_path: Path, reference_db_path: Path) -> None:
    client, _, _ = make(tmp_path, reference_db_path)
    case = results_case(client, tmp_path)
    text = json.dumps(client.post(f"/api/cases/{case['id']}/lookup").json()["calls"])
    assert PHONE not in text and "Riverbend" not in text and "Mill Road" not in text
