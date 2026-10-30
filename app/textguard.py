"""Checks on text a model wrote. Models write words only: no new numbers, no accusations, no legal claims."""

import re
from decimal import Decimal, InvalidOperation

BANNED = re.compile(r"\b(?:illegal\w*|unlawful\w*|fraud\w*|lawsuit\w*|sue|sues|sued|suing)\b", re.IGNORECASE)
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def has_banned_term(text: str) -> bool:
    return BANNED.search(text) is not None


def _values(text: str) -> dict[Decimal, str]:
    found = {}
    for token in NUMBER.findall(text):
        plain = token.replace(",", "")
        try:
            found[Decimal(plain)] = plain
        except InvalidOperation:
            continue
    return found


def numbers_not_in(text: str, facts: str) -> set[str]:
    """Numbers in `text` (amounts, dates, codes, counts) that the `facts` do not contain, compared by value."""
    allowed = set(_values(facts))
    return {plain for value, plain in _values(text).items() if value not in allowed}
