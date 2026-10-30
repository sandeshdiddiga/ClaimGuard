# ClaimGuard: locked decisions

Plan: [docs/SPEC.md](docs/SPEC.md) (Zero-AMA). Read the SPEC before a new area. These decisions are locked; do not re-litigate.

ClaimGuard checks an itemized hospital bill (plus EOB if insured) against public CMS data and drafts dispute
letters. Nebius x NVIDIA hackathon; deadline Oct 30, 2026, 10:00 AM PT.

## Stack
- Python 3.11 (uv), FastAPI, SQLite, pydantic v2, pytest; React + Vite + Tailwind + TypeScript in `web/`; Docker + Render.

## Zero AMA content
- Reference data comes only from the three CMS public-use files in SPEC section 2: HCPCS alpha-numeric file,
  Part B payment limit files, NCCI MUE facility outpatient table.
- Ingestion keeps only codes whose first character is a letter. A test fails the build if any reference row
  starts with a digit.
- No CPT codes (5 digits, or 4 digits plus F/T/U) and no CPT descriptions anywhere: code, tests, samples, docs,
  fixtures or git history. Samples use only Level II codes; revenue codes appear only inside description text.
- A CPT-shaped code on a bill is shown unchanged and never looked up. Label: "Not checked: CPT codes need an AMA
  license, which this demo doesn't use."
- Cut (do not build): NCCI PTP unbundling and OPPS rates; list under "What's next: requires an AMA CPT license."
  README licensing wording is in SPEC section 2; do not claim legal compliance.

## Models
- Every call goes through the single client in `app/llm.py` (`openai` SDK, Nebius Token Factory,
  `https://api.tokenfactory.nebius.com/v1/`). No other client, no direct HTTP to a model.
- IDs live only in `app/config.py` with the routing table; never hardcode one elsewhere.
- Routing: Nemotron 3.5 Super VL reads documents. Nemotron 3 Nano cleans codes, extracts doses and gates scope.
  Nemotron 3 Ultra judges amber findings only. Nemotron 3 Super explains, drafts letters and picks Tavily links.
- Every call is logged to the case (step, model, latency, tokens, ok). Never log document text or personal details.
  The "How this was checked" panel and the eval read this log. Use the real model names in README, UI and video.

## Rules of the domain
- Models never compute money or decide rule outcomes. Checks are pure Python in `app/checks/`, each against a cited
  source. Models read documents, judge amber cases and write text. Ultra may only keep or downgrade.
- Ask insured or self-pay before the Good Faith Estimate check. Insured: units and dose findings are worded
  "ask for a billing review" (private insurers are not bound by Medicare's edits).
- Good Faith Estimate constants: $400 or more over, 120-day deadline; constants with a source link.

## Money (benchmarks are "For context": charging above Medicare is usually legal)
- Likely-error total counts each affected line once, even if several checks flag it.
- The Good Faith Estimate overage is shown separately, never added to that total. Benchmarks are never counted.

## Wording
- Result levels: "Likely error", "Worth asking about", "For context". Never "red flag", "anomaly", "AI-powered",
  "insights" in the UI or copy. Never "illegal". No legal or medical advice; never claim to send anything.
- Use the fixed wording per check from SPEC section 5; do not improvise accusatory text.
- Every letter ends with "This is not legal advice." (existing footer: "Prepared with ClaimGuard. This is not legal advice.")
- Cite the CFPB $88B figure only; never the "80% of bills have errors" claim.

## Data and privacy
- `data/claimguard.db` holds reference tables only and is committed and shipped in the image. No `REFERENCE_DB_URL`
  or `REFERENCE_DB_SHA256`. `data/state.db` (cases, lines, findings, calls, letters) is git-ignored.
- Raw ZIPs live in `data/raw/` (git-ignored). Only synthetic SAMPLE-watermarked documents in `samples/`, each with
  an `expected_flags.json`; no real patient data. Never commit API keys (`.env` is git-ignored).

## UI (SPEC section 8)
- Four steps: Your bill, Check the lines, What we found, Send letters. Results lead with one sentence and two numbers.
- Paper-like light theme, one accent, no gradients, emoji or sparkle icons. Status colour always paired with a word
  and an icon. Public Sans body, Source Serif 4 for the headline and letters, tabular figures.
- 16px minimum text, 44px tap targets, AA contrast, works at 390px. Footer: "ClaimGuard explains and drafts.
  It isn't legal or medical advice." "How this was checked" sits collapsed at the bottom.

## Scope and process
- Cut entirely: CareRoute mode, hospital price-file ingestion, Nebius Serverless Job, geographic rate adjustment,
  appeals of denied claims, Medicaid and Medicare-enrollee bills.
- Tavily lookup is Should: search the hospital name only, never patient data; the app works with the key unset.
- Maya (self-pay) works end to end before Dev (BCBS + EOB). Eval must show 0 false likely-error flags on the samples
  before the video. Log each Token Factory or Nemotron friction point in `docs/feedback.md` as it happens.
