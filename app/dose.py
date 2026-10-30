"""The dose written on a bill line, e.g. "Midazolam HCl inj 2 mg" -> 2 MG.

Nano reads it from the description (app/safety.py); this module is the check on its answer. A dose is kept
only if the description states it, so a model can never invent one. With no model (or no usable answer) a
description that states exactly one dose still gives it, from the text alone.
"""

import re
from decimal import Decimal

UNIT_ALIASES = {"UG": "MCG", "G": "GM"}

# number, optional space, unit. Not a concentration (mg/mL), and not part of a longer number.
DOSE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?|\.\d+)\s*(mg|mcg|ug|gm|g|ml|cc|iu|units?)\b(?!\s*/)",
    re.IGNORECASE,
)

Dose = tuple[Decimal, str]


def normalize_unit(raw: str) -> str:
    unit = raw.strip().upper()
    return UNIT_ALIASES.get(unit, unit)


def dose_candidates(description: str) -> list[Dose]:
    """Every "<number> <unit>" the description states, in order, without repeats."""
    found: list[Dose] = []
    for match in DOSE.finditer(description):
        dose = (Decimal(match.group(1).replace(",", "")), normalize_unit(match.group(2)))
        if dose not in found:
            found.append(dose)
    return found


def settle_dose(
    description: str, value: Decimal | None, unit: str | None
) -> tuple[Decimal, str] | tuple[None, None]:
    """The proposed dose if the description states it; else the one dose it states; else nothing."""
    candidates = dose_candidates(description)
    if value is not None and unit:
        proposed = (value, normalize_unit(unit))
        for candidate in candidates:
            if candidate == proposed:
                return candidate
    if len(candidates) == 1:
        return candidates[0]
    return None, None
