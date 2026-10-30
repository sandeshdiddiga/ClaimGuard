from decimal import Decimal

from app.checks.eob import check_eob
from app.schemas import EobReading

WORDING = "The hospital billed $1,140.00, but your insurer's EOB says you owe $410.00."


def eob(responsibility: str = "410.00") -> EobReading:
    return EobReading(billed=Decimal("2265.00"), allowed=Decimal("1140.00"), patient_responsibility=Decimal(responsibility))


def test_bill_above_eob_is_red_with_the_spec_wording() -> None:
    (finding,) = check_eob(Decimal("1140.00"), eob())
    assert (finding.check, finding.level) == ("eob", "red")
    assert finding.amount_billed == Decimal("1140.00")
    assert finding.patient_responsibility == Decimal("410.00")
    assert finding.wording == WORDING


def test_the_difference_is_the_dollars_at_stake() -> None:
    (finding,) = check_eob(Decimal("1140.00"), eob())
    assert finding.dollars_at_stake == Decimal("730.00")
    assert finding.evidence.difference == Decimal("730.00")
    assert finding.counted == {}  # account-level, not tied to a line
    assert finding.evidence.computed == {"difference": "730.00"}


def test_evidence_has_the_eob_figures_and_source() -> None:
    (finding,) = check_eob(Decimal("1140.00"), eob())
    assert finding.evidence.data_row == {
        "eob_billed": "2265.00", "eob_allowed": "1140.00", "eob_patient_responsibility": "410.00",
        "bill_balance_due": "1140.00",
    }
    assert finding.evidence.source_url is None
    assert finding.evidence.source_name == "Your insurer's Explanation of Benefits"


def test_one_cent_over_is_flagged_and_equal_is_not() -> None:
    assert check_eob(Decimal("410.01"), eob()) != []
    assert check_eob(Decimal("410.00"), eob()) == []


def test_bill_below_the_eob_is_not_flagged() -> None:
    assert check_eob(Decimal("300.00"), eob()) == []


def test_without_a_balance_due_or_an_eob_there_is_nothing_to_compare() -> None:
    assert check_eob(None, eob()) == []
    assert check_eob(Decimal("1140.00"), None) == []
