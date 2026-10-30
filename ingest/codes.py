"""Which codes ingestion keeps: HCPCS Level II only, meaning the code starts with a letter."""

import re

LEVEL_II = re.compile(r"[A-Z][0-9A-Z]{4}")

# A CPT-shaped token: 5 digits, or 4 digits plus F, T or U. Descriptions are scrubbed of these so the
# reference data holds no CPT code, even when a Level II description mentions one. CMS lowercases some long
# descriptions, so F and T match in either case; a lowercase u is a unit ("per 1000u"), so only U counts.
CPT_SHAPED = re.compile(r"(?<![\w$.,])(?:\d{5}|\d{4}[FTft]|\d{4}U)(?!\w|\.\d)")


def clean_code(raw: str) -> str:
    return raw.strip().upper()


def is_level_ii(code: str) -> bool:
    return bool(LEVEL_II.fullmatch(code))


def redact_cpt_codes(text: str) -> str:
    return CPT_SHAPED.sub("[CPT code]", text)
