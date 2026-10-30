from datetime import date
from decimal import Decimal

import pytest

from app.llm import CallRecord
from app.schemas import ExtractedLine
from app.store import Store


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_calls_round_trip_in_order(store: Store) -> None:
    case_id = store.create_case("self_pay", Decimal("3100.00"))
    other = store.create_case("self_pay")
    store.record_call(case_id, CallRecord("read_document", "m1", 1200, 900, 150, True))
    store.record_call(case_id, CallRecord("clean_codes", "m2", 300, 80, 20, False, "invalid_json"))
    store.record_call(other, CallRecord("explain", "m3", 5, None, None, True))
    assert store.calls(case_id) == [
        CallRecord("read_document", "m1", 1200, 900, 150, True),
        CallRecord("clean_codes", "m2", 300, 80, 20, False, "invalid_json"),
    ]


def test_lines_keep_exact_decimals(store: Store) -> None:
    case_id = store.create_case("self_pay")
    lines = [
        ExtractedLine(service_date=date(2026, 9, 14), code="G0121", description="colonoscopy", units=1, charge=Decimal("1980.10")),
        ExtractedLine(code="A9579", description="contrast", units=15, charge=Decimal("0.07"), status="corrected", note="x"),
    ]
    store.save_lines(case_id, lines)
    assert store.lines(case_id) == lines
    assert store.lines(case_id)[1].charge == Decimal("0.07")


def test_saving_lines_again_replaces_them(store: Store) -> None:
    case_id = store.create_case("self_pay")
    line = ExtractedLine(code="G0121", description="a", charge=Decimal("1"))
    store.save_lines(case_id, [line, line])
    store.save_lines(case_id, [line])
    assert len(store.lines(case_id)) == 1


def test_patient_type_is_constrained(store: Store) -> None:
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        store.create_case("medicare")


def test_dose_and_code_class_round_trip(store: Store) -> None:
    case_id = store.create_case("self_pay")
    lines = [
        ExtractedLine(code="J2250", charge=Decimal("68.00"), description="Midazolam 2 mg", units=2,
                      dose_value=Decimal("2"), dose_unit="MG", code_class="hcpcs_level2"),
        ExtractedLine(code="00000", charge=Decimal("10.00"), code_class="cpt_shaped"),
        ExtractedLine(code="G0121", charge=Decimal("10.00")),  # not classified yet
    ]
    store.save_lines(case_id, lines)
    assert store.lines(case_id) == lines
    assert store.lines(case_id)[0].dose_value == Decimal("2")
