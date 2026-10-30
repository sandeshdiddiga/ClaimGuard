from app.textguard import has_banned_term, numbers_not_in


def test_banned_terms() -> None:
    for text in ("an illegal markup", "Illegal!", "unlawful billing", "this is fraud", "we will sue", "a lawsuit"):
        assert has_banned_term(text), text
    for text in ("a legal question", "suede shoes", "pursue a correction", "Fine."):
        assert not has_banned_term(text), text


def test_numbers_not_in_compares_values_not_formatting() -> None:
    facts = "billed $1,140.00; owed $410.00; code G0121; 120 days"
    assert numbers_not_in("You owe $410 and $1,140.00 for G0121 within 120 days.", facts) == set()
    assert numbers_not_in("You owe $411.00.", facts) == {"411.00"}
    assert numbers_not_in("No digits here.", facts) == set()
