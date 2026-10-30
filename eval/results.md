# ClaimGuard eval

Every sample (maya, maya-photo, dev, clean) goes through the real pipeline on Nebius Token Factory: read, confirm the lines exactly as read (no human corrections), run the checks, review amber findings, write the letters. Expected results come from each `samples/*/expected_flags.json`, which is derived from the CMS data independently of the check code. `maya-photo` is Maya's bill as a phone-style photo, scored against the same expected lines. The hospital web lookup is not part of this eval.

## Scorecard

|  | Routed (default) | Ultra for every step |
| --- | --- | --- |
| Seeded errors caught / expected | 12 / 12 | 12 / 12 |
| Amber flags Ultra moved to context | 0 | 0 |
| Missed errors | 0 | 0 |
| False Likely-error flags | 0 | 0 |
| Likely-error totals correct | 4 / 4 samples | 4 / 4 samples |
| Extraction accuracy (all fields) | 215/215 (100%) | 215/215 (100%) |
| Model calls (failed) | 16 (0) | 16 (0) |
| Tokens in / out | 18,779 / 21,119 | 18,779 / 19,331 |
| Model latency, all calls added up | 116.6 s | 70.8 s |
| Wall-clock time, all samples | 117 s | 71 s |
| Estimated cost | $0.0220 | $0.0461 |
| Cost compared with routed | 1.0× | 2.1× |

**Routed (default)**, finished 2026-10-30T13:18:49Z. 

**Ultra for every step**, finished 2026-10-30T13:20:02Z. The reading step stayed on Nemotron 3.5 Super VL: Nemotron 3 Ultra did not accept an image (Token Factory lists it as text only). Every other model step ran on Ultra.

## Findings by sample

### Routed (default)

| Sample | Errors caught | Moved to context | Missed | False Likely errors | Context notes | Likely-error total | Deadline right |
| --- | --- | --- | --- | --- | --- | --- | --- |
| maya | 5 / 5 | 0 | 0 | 0 | 6 / 6 | $3858.00 (expected $3858.00) | yes |
| maya-photo | 5 / 5 | 0 | 0 | 0 | 6 / 6 | $3858.00 (expected $3858.00) | yes |
| dev | 2 / 2 | 0 | 0 | 0 | 3 / 3 | $1050.00 (expected $1050.00) | yes |
| clean | 0 / 0 | 0 | 0 | 0 | 5 / 5 | $0.00 (expected $0.00) | yes |

**Missed:** none

**False Likely-error flags:** none

**Other findings nobody expected:** none

### Ultra for every step

| Sample | Errors caught | Moved to context | Missed | False Likely errors | Context notes | Likely-error total | Deadline right |
| --- | --- | --- | --- | --- | --- | --- | --- |
| maya | 5 / 5 | 0 | 0 | 0 | 6 / 6 | $3858.00 (expected $3858.00) | yes |
| maya-photo | 5 / 5 | 0 | 0 | 0 | 6 / 6 | $3858.00 (expected $3858.00) | yes |
| dev | 2 / 2 | 0 | 0 | 0 | 3 / 3 | $1050.00 (expected $1050.00) | yes |
| clean | 0 / 0 | 0 | 0 | 0 | 5 / 5 | $0.00 (expected $0.00) | yes |

**Missed:** none

**False Likely-error flags:** none

**Other findings nobody expected:** none

## Extraction accuracy

Per field, over every line (and the bill header and EOB) of every sample. A line the reader missed counts every one of its fields wrong. The dose fields also count a dose invented where the bill states none.

| Field | Routed (default) | Ultra for every step |
| --- | --- | --- |
| service_date | 25/25 (100%) | 25/25 (100%) |
| code | 25/25 (100%) | 25/25 (100%) |
| modifier | 25/25 (100%) | 25/25 (100%) |
| description | 25/25 (100%) | 25/25 (100%) |
| units | 25/25 (100%) | 25/25 (100%) |
| charge | 25/25 (100%) | 25/25 (100%) |
| dose_value | 25/25 (100%) | 25/25 (100%) |
| dose_unit | 25/25 (100%) | 25/25 (100%) |
| facility_name | 4/4 (100%) | 4/4 (100%) |
| bill_date | 4/4 (100%) | 4/4 (100%) |
| amount_due | 4/4 (100%) | 4/4 (100%) |
| eob_billed | 1/1 (100%) | 1/1 (100%) |
| eob_allowed | 1/1 (100%) | 1/1 (100%) |
| eob_patient_responsibility | 1/1 (100%) | 1/1 (100%) |

### By sample: Routed (default)

| Sample | Document | Lines read / expected | Fields correct |
| --- | --- | --- | --- |
| maya | bill.pdf | 8 / 8 | 67/67 (100%) |
| maya-photo | bill_photo.jpg | 8 / 8 | 67/67 (100%) |
| dev | bill.pdf | 4 / 4 | 38/38 (100%) |
| clean | bill.pdf | 5 / 5 | 43/43 (100%) |

### By sample: Ultra for every step

| Sample | Document | Lines read / expected | Fields correct |
| --- | --- | --- | --- |
| maya | bill.pdf | 8 / 8 | 67/67 (100%) |
| maya-photo | bill_photo.jpg | 8 / 8 | 67/67 (100%) |
| dev | bill.pdf | 4 / 4 | 38/38 (100%) |
| clean | bill.pdf | 5 / 5 | 43/43 (100%) |

## Cost and latency by step

### Routed (default)

| Step | Model | Calls (failed) | Tokens in / out | Latency, added up | Mean per call | Estimated cost |
| --- | --- | --- | --- | --- | --- | --- |
| read_document | Nemotron 3.5 Super VL | 5 (0) | 13,028 / 10,612 | 37.0 s | 7.4 s | $0.0135 |
| clean_codes | Nemotron 3 Nano | 4 (0) | 3,350 / 6,182 | 55.6 s | 13.9 s | $0.0017 |
| judge_amber | Nemotron 3 Ultra | 2 (0) | 666 / 866 | 3.7 s | 1.9 s | $0.0033 |
| draft_letter | Nemotron 3 Super | 5 (0) | 1,735 / 3,459 | 20.2 s | 4.0 s | $0.0036 |
| **Total** |  | 16 (0) | 18,779 / 21,119 | 116.6 s |  | $0.0220 |

### Ultra for every step

| Step | Model | Calls (failed) | Tokens in / out | Latency, added up | Mean per call | Estimated cost |
| --- | --- | --- | --- | --- | --- | --- |
| read_document | Nemotron 3.5 Super VL | 5 (0) | 13,028 / 10,262 | 40.2 s | 8.0 s | $0.0131 |
| clean_codes | Nemotron 3 Ultra | 4 (0) | 3,350 / 3,889 | 12.2 s | 3.1 s | $0.0150 |
| judge_amber | Nemotron 3 Ultra | 2 (0) | 666 / 964 | 4.4 s | 2.2 s | $0.0036 |
| draft_letter | Nemotron 3 Ultra | 5 (0) | 1,735 / 4,216 | 14.0 s | 2.8 s | $0.0144 |
| **Total** |  | 16 (0) | 18,779 / 19,331 | 70.8 s |  | $0.0461 |

## Prices used

These are estimates: list prices times the token counts in the call log, with no cached-token discount, so a real bill can be lower. Source: Nebius Token Factory GET /v1/models, pricing.prompt and pricing.completion, read 2026-10-30.

| Model | Model ID | Input, per million tokens | Output, per million tokens |
| --- | --- | --- | --- |
| Nemotron 3.5 Super VL | `nvidia/Nemotron-3.5-Super-VL` | $0.30 | $0.90 |
| Nemotron 3 Nano | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | $0.06 | $0.24 |
| Nemotron 3 Ultra | `nvidia/Nemotron-3-Ultra-550b-a55b` | $1.00 | $3.00 |
| Nemotron 3 Super | `nvidia/nemotron-3-super-120b-a12b` | $0.30 | $0.90 |

## How to reproduce

`python -m eval` runs the routed pipeline and `python -m eval --all-ultra` repeats it with Nemotron 3 Ultra on every step that can run on it. Each run is saved in `eval/runs/` and this file is rebuilt from both. Both need `NEBIUS_API_KEY` and spend Token Factory credit. Model outputs vary between runs, so numbers will differ slightly.
