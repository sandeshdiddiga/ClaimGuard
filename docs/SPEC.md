# ClaimGuard: Build Spec (Zero-AMA version)

ClaimGuard reads a patient's itemized hospital bill (and their insurer's EOB, if they have one), checks every line against public CMS data, explains each problem in plain language, and drafts the letters to fix it. It is built on NVIDIA Nemotron models through Nebius Token Factory for the Nebius x NVIDIA Global AI Hackathon (deadline Oct 30, 2026, 10:00 AM PT).

This version uses **no AMA CPT content anywhere**: not in the database, the code, the tests, the sample documents, the git history or the deployed app. All reference data comes from CMS public-use files covering HCPCS Level II codes (codes that start with a letter).

## 1. The idea

**One question:** "Is this bill right, and if not, what do I send to fix it?"

**The problem, with a source:** the CFPB estimated $88 billion in medical bills on Americans' credit reports, said roughly 20% of US households report medical debt, and described the billing system as one "where mistakes are common" ([CFPB, March 2022](https://www.consumerfinance.gov/about-us/newsroom/cfpb-estimates-88-billion-in-medical-bills-on-credit-reports)). Do not use the unsourced "80% of bills have errors" claim.

**Who it's for:**
- Uninsured and self-pay patients, who pay full charges and can use the federal Good Faith Estimate dispute process.
- Privately insured patients (UnitedHealthcare, Blue Cross Blue Shield and others), who are sometimes billed more than their EOB says they owe.

**What it does not do:** diagnose, give legal advice, call anything "illegal," guess codes, or send anything on the patient's behalf. It explains, flags and drafts; the patient reviews and sends.

## 2. Data and licensing

| Table | Source (CMS public-use file, direct download, no AMA license step) | Kept |
| --- | --- | --- |
| `hcpcs` | [October 2026 Alpha-Numeric HCPCS File](https://www.cms.gov/files/zip/october-2026-alpha-numeric-hcpcs-file.zip) | Level II codes: code, short and long description, effective/termination dates |
| `drug_limits` | [October 2026 Medicare Part B Payment Limit Files](https://www.cms.gov/files/zip/october-2026-medicare-part-b-payment-limit-files-final.zip) | Level II drug codes: code, short description, dosage per billing unit, payment limit per unit |
| `mue` | [Medicare NCCI MUE table, facility outpatient hospital, 2026 Q4](https://www.cms.gov/files/zip/medicare-ncci-2026-q4-facility-outpatient-hospital-services-mue-table.zip) | Level II codes: code, MUE value, MUE adjudication indicator (MAI), rationale |

Rules:
- Ingestion keeps **only codes whose first character is a letter**. A test fails the build if any reference row has a code starting with a digit.
- Raw ZIPs live in `data/raw/` (git-ignored) and can be deleted after ingest.
- Because the built database contains only CMS public data, `data/claimguard.db` is **committed to the repo and shipped in the Docker image**. No private storage, no `REFERENCE_DB_URL`.
- **Cut:** code-pair unbundling (NCCI PTP) and procedure-level Medicare rates (OPPS). Neither has a public source without CPT content. Both go under "What's next: requires an AMA CPT license."
- When a bill line has a CPT-shaped code (5 digits, or 4 digits plus F/T/U), ClaimGuard shows it unchanged, never looks it up, and labels it "Not checked: CPT codes need an AMA license, which this demo doesn't use."

README wording: "This demo includes no AMA CPT content. It uses CMS public-use files covering HCPCS Level II codes. Supporting CPT codes would require a license from the American Medical Association." Do not claim legal compliance.

## 3. Winning each judging criterion

| Criterion | What judges ask | What ClaimGuard shows | Where they see it |
| --- | --- | --- | --- |
| Technological Implementation | How well built; how effectively it uses Token Factory and Nemotron | Four Nemotron models, each with one job; a vision model reads bill photos; Ultra only on hard calls; every call logged (model, latency, tokens); deterministic checks; 300+ tests; an eval scorecard | "How this was checked" panel; README routing table and scorecard; video |
| Design | Complete, coherent product, not a proof of concept | One finished flow a non-expert understands without help: upload, confirm, results, letters. Sample bills one click away. Clear loading, empty and error states. Works on a phone | Live URL; middle of the video |
| Potential Impact | A credible, specific case for a real problem and audience; does the demo solve it | Two patients (self-pay and BCBS-insured), a sourced statistic, dollars in question, a deadline, letters ready to send | First 15 seconds of the video; results summary |
| Quality of the Idea | Creative, non-obvious use of Token Factory and Nemotron; real understanding of the problem | Models read and write, rules decide; dose-versus-billing-unit check (a common, non-obvious drug billing error); Ultra adjudicates only clinical-judgment limits; zero AMA content by design; honest about what isn't checked | README "Why it's built this way"; video |

The single most persuasive artifact is the **eval scorecard**: seeded errors caught, false red flags, extraction accuracy, and routed vs Ultra-for-everything cost and latency, from a real run.

## 4. Demo story: screening colonoscopy

**Maya: uninsured, screening colonoscopy at a hospital outpatient department (must have)**
1. Maya picks "I'm paying myself," enters her Good Faith Estimate, and uploads her itemized bill (PDF or phone photo).
2. ClaimGuard reads every line and shows them back. She corrects one misread number and confirms.
3. Results lead with a summary: likely errors and the dollars involved, how far the bill is over her estimate, and her dispute deadline.
4. Findings (codes chosen from the real data; see the code-selection step):
   - **Likely error:** a sedation drug line charged twice on the same date (duplicate).
   - **Likely error:** a drug line whose billed units don't match the dose written on the bill (e.g. the bill says 2 mg, the code is billed per 1 mg, 20 units billed).
   - **Likely error:** a line billed above CMS's absolute daily maximum (MUE with MAI 1 or 2): the colonoscopy (G0121, MUE 1) billed as 2 units. No drug plausible at a colonoscopy has an MAI 1 or 2 limit.
   - **Worth asking about, reviewed by Ultra:** a line above a CMS daily limit that allows clinical judgment (MAI 3); Ultra explains whether the bill's own text supports the extra units.
   - **Likely error:** total from the hospital at least $400 over her Good Faith Estimate, with the 120-day dispute deadline.
   - **For context:** a drug charge shown as a multiple of Medicare's Part B payment limit for that drug.
   - **For context:** the colonoscopy line (G0121) is a valid HCPCS code; ClaimGuard has no public Medicare rate for it and says so.
5. She downloads two letters: a corrected-bill and billing review request, and a Good Faith Estimate dispute summary.

**Dev: Blue Cross Blue Shield PPO, same kind of visit (must have)**
1. Dev uploads his itemized bill and his EOB.
2. Likely error: the hospital billed more than the EOB's patient responsibility.
3. Units and dose findings are worded "ask for a billing review," because private insurers aren't bound by Medicare's edits.
4. Letter: a rebilling request citing the EOB amount.

**Clean bill (must have):** one sample with no likely errors, to prove ClaimGuard doesn't cry wolf.

**Sample documents:** synthetic PDFs plus one phone-style photo (rendered from a PDF with slight rotation, shadow and noise), invented names and account numbers, a visible "SAMPLE" watermark, only HCPCS Level II codes, and revenue codes shown only inside description text. Each has an `expected_flags.json`.

## 5. What ClaimGuard checks

Every check is plain Python against a cited source. Models read documents, judge amber cases and write explanations; they never compute money or decide a rule outcome.

| Check | Data | Result shown to the user | Wording |
| --- | --- | --- | --- |
| Duplicate charge | The bill itself | Likely error | "This charge appears twice on the same date. Ask the billing office to confirm or remove it." |
| Dose vs billing units (drugs) | `drug_limits` dosage per unit + the dose written on the bill line | Likely error when the mismatch is clear; Worth asking about when the unit needs interpreting (e.g. mL vs mg) | "Your bill says [dose], which is [N] billing units for this drug, but [M] units were charged." |
| Units over CMS daily limit | `mue` value + MAI | MAI 1 or 2: Likely error. MAI 3: Worth asking about, reviewed by Ultra | "CMS normally allows at most [N] units of this per day. [M] were billed." |
| Over the Good Faith Estimate | Estimate the patient enters | Likely error at $400 or more over; uninsured or self-pay only | "You may be able to start a federal billing dispute. Deadline: [date]." |
| Bill above EOB | Insurer's EOB | Likely error | "The hospital billed $[X], but your insurer's EOB says you owe $[Y]." |
| Medicare drug benchmark | `drug_limits` payment limit per unit | For context; never counted in dollars at stake | "Charged [N]× Medicare's payment limit for this drug. Not an error; useful when asking for a discount." |
| Code check | `hcpcs` | For context | Valid Level II: description shown. Unknown letter code: "Not in CMS's current HCPCS list." CPT-shaped: "Not checked (CPT needs an AMA license)." |

**Money rules:**
- "Likely errors" total = sum over affected lines, each line counted once even if several checks flag it (the largest amount wins). Duplicates count the line charge; units and dose findings count only the excess units (charge × excess units ÷ billed units).
- The EOB difference counts in the total as the larger of itself and the line-level amounts (it already contains any duplicate inside the balance), never added to them. For insured patients, line-level units and dose findings add nothing: what the patient owes is set by the EOB.
- The Good Faith Estimate overage is shown separately ("Over your estimate by $X") and never added to the likely-errors total.
- Benchmarks are never counted. One drug benchmark per drug line with a payment limit and a parsed dose; skipped on a line with a dose-mismatch finding (its per-unit price is distorted).

**Domain rules to state in the README and video:**
- Drug codes are billed per a fixed dose (e.g. "per 1 mg"); unit mix-ups are a common, checkable error.
- MUE limits are Medicare's; for insured patients they're a reason to ask, not proof of an error.
- Medicare, Medicaid and TRICARE enrollees can't use the Good Faith Estimate dispute; ask insured or self-pay first.
- Charging more than Medicare is usually legal; it's context, never an "error."

## 6. Model routing

| Step | Model (ID in `app/config.py`) | Output |
| --- | --- | --- |
| Read bill and EOB images or PDFs | Nemotron 3.5 Super VL (`nvidia/Nemotron-3.5-Super-VL`) | Lines: date, code, modifier, description, units, charge; EOB: billed, allowed, patient responsibility |
| Clean codes, extract the dose written in each description, scope gate | Nemotron 3 Nano (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`) | Normalized codes; `{dose_value, dose_unit}` per line or null; allow/redirect |
| Judge amber findings (MAI 3 limits, ambiguous dose units) | Nemotron 3 Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`) | keep or downgrade + one-line reason, JSON |
| Explain findings, draft letters, pick Tavily links | Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`) | Plain-language text from stored evidence only |

Every call goes through `app/llm.py` to Nebius Token Factory and is logged (step, model, latency, tokens, ok). Use the real model names everywhere (README, UI, video).

## 7. Hospital lookup with Tavily (should have)

After the audit, search with Tavily for the hospital on the bill: (1) billing office phone and mailing address, used to address the letters; (2) its financial assistance policy page. Super picks links from the results; any phone number or address must appear verbatim in the search results. Card label: "Found on the web. Verify before sending." The app works with `TAVILY_API_KEY` unset.

## 8. User experience and visual design

Audience: a stressed person holding a confusing bill, often on a phone. Every screen answers "what does this mean for me, and what do I do next?"

**Flow and words:**
- Four steps shown as a simple progress line: Your bill → Check the lines → What we found → Send letters.
- Plain words: "Likely error," "Worth asking about," "For context." Never "red flag," "anomaly," "AI-powered," "insights."
- Results lead with one sentence and two numbers: "We found 3 likely errors totaling $2,210. Your bill is also $4,135 over your estimate. Dispute deadline: Feb 2, 2027."
- Each finding: what we found (one sentence), why it matters, what to do, and "Show the rule" (source link, data row).
- Jargon (Good Faith Estimate, EOB, MUE, HCPCS) gets a short inline explanation the first time it appears.
- Letters: preview on screen, copy and download PDF; "Send these to: [billing office]" when Tavily found it.
- "How this was checked" sits at the bottom, collapsed, for the curious and the judges.

**Visual direction: a careful reviewer's notes on your bill, not an AI app:**
- Light, paper-like background; dark ink text; one accent colour. No gradients, glows, glassmorphism, sparkle icons, emoji, robot imagery or animated "thinking" effects.
- The bill table is the centre of the results page; findings attach to the lines they concern, like margin notes.
- Status colours are muted and always paired with a word and an icon: likely error (deep red), worth asking about (amber), for context (grey-blue). Never colour alone.
- Typography: Public Sans for UI and body, a serif (Source Serif 4) only for the summary headline and letters; tabular figures for every amount.
- Generous spacing, 16px minimum body text, 44px minimum tap targets, visible focus states, WCAG 2.2 AA contrast.
- Loading states say what's happening ("Reading your bill… usually 10–20 seconds"), with a progress line, not a spinner.
- Works at 390px wide: the bill table becomes stacked line cards.
- Footer on every page: "ClaimGuard explains and drafts. It isn't legal or medical advice."

## 9. Evaluation

`python -m eval` runs every sample end to end and writes `eval/results.md`:
- seeded errors caught / expected, false likely-error flags, missed errors
- extraction accuracy per field
- tokens, latency and estimated cost per step and in total

`python -m eval --all-ultra` repeats with Nemotron 3 Ultra for every model step. The README shows both rows. Report the numbers as they are.

## 10. Tech stack and layout

Existing stack stays: Python 3.11 (uv), FastAPI, SQLite, pydantic v2, openai SDK pointed at Token Factory, pdfplumber, Jinja2 + WeasyPrint, pytest; React 18 + Vite + Tailwind + TypeScript in `web/`; Docker + Render.

- `data/claimguard.db`: reference tables only (committed). `data/state.db`: cases, lines, findings, calls, letters (git-ignored).
- Remove `app/refdb.py` download logic and the `REFERENCE_DB_URL` / `REFERENCE_DB_SHA256` variables.
- Remove `app/checks/ncci.py` and the OPPS benchmark; add `units.py`, `dose.py`, `drug_benchmark.py`, `codes.py`.

## 11. Submission checklist

- [ ] Runs on Nebius Token Factory with NVIDIA Nemotron models
- [ ] Track: Best Apps and Agents
- [ ] Public GitHub repo, MIT license visible at the top, history contains no CPT content
- [ ] README: what it does, demo and video links, architecture (Mermaid), routing table, scorecard, why it's built this way, setup, data and licensing, not legal or medical advice, license
- [ ] Working demo URL, sample bills one click away, tested logged out and on a phone
- [ ] Video of 3 minutes or less, public on YouTube
- [ ] Devpost description, feedback on Token Factory and Nemotron, city if you attended a Builders & Brews event
- [ ] Demo kept live and credits topped up through judging

## 12. Demo video script (under 2:55)

| Time | Criterion | On screen | Voice-over |
| --- | --- | --- | --- |
| 0:00–0:15 | Impact | Maya's bill; the CFPB figure | Americans carry $88 billion in medical bills on their credit reports, in a system the CFPB calls one where mistakes are common. |
| 0:15–1:15 | Design | Live: self-pay, upload photo, confirm lines, summary, findings on the bill, letters | Walk through as Maya. Open one "Show the rule." |
| 1:15–1:30 | Impact | Dev's bill vs his BCBS EOB | Insured patients too: billed more than his insurer says he owes. |
| 1:30–2:05 | Technological Implementation | "How this was checked"; architecture | Super VL reads the bill, Nano cleans codes and reads doses, Ultra judges only clinical-judgment limits, Super writes. Every call runs on Token Factory and is logged. |
| 2:05–2:25 | Technological Implementation | Scorecard | Caught [X] of [Y] seeded errors, [Z] false alarms, [N]× cheaper than Ultra for everything. |
| 2:25–2:45 | Quality of the Idea | "Why it's built this way" | Models never do the math. No AMA content: public CMS data only, and it tells you what it can't check. |
| 2:45–2:55 | Close | Repo and URL | Open source, live now. |

## 13. Sources

- [Nebius x NVIDIA Global AI Hackathon](https://nebiusglobalaihackathon.devpost.com/)
- [Nebius Token Factory quickstart](https://docs.tokenfactory.nebius.com/quickstart.md)
- [CFPB: $88 billion in medical bills on credit reports](https://www.consumerfinance.gov/about-us/newsroom/cfpb-estimates-88-billion-in-medical-bills-on-credit-reports)
- [CMS HCPCS quarterly update](https://www.cms.gov/medicare/coding/hcpcsreleasecodesets/hcpcs-quarterly-update.html)
- [CMS ASP pricing files](https://www.cms.gov/medicare/payment/part-b-drugs/asp-pricing-files)
- [CMS Medicare NCCI MUEs](https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-ncci-edits/medicare-ncci-medically-unlikely-edits-mues)
- [CMS: Good Faith Estimate and dispute resolution](https://www.cms.gov/marketplace/technical-assistance-resources/understanding-good-faith-estimate-and-dispute-resolution-process.pdf)
