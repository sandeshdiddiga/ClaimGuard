# ClaimGuard: Devpost submission text

Live demo: https://claimguard-snxl.onrender.com | Video: `<VIDEO_URL>` | Code: https://github.com/sandeshdiddiga/ClaimGuard

## Inspiration
The CFPB estimated $88 billion in medical bills on Americans' credit reports and called the billing system one "where mistakes are common." Checking an itemized hospital bill by hand means knowing billing codes, Medicare's per-day limits and each drug's billing unit, and then writing a letter that the billing office will take seriously. Almost nobody can do that. We wanted one answer to one question: is this bill right, and if not, what do I send to fix it?

## What it does
You upload an itemized hospital bill (a PDF or a phone photo) and, if you're insured, your insurer's Explanation of Benefits. ClaimGuard reads every line, lets you confirm what it read, then checks each line against public CMS data: duplicate charges, drug doses against billing units, units over Medicare's daily limits, the Good Faith Estimate for self-pay patients, and the bill against the EOB. Results come in three plain levels (Likely error, Worth asking about, For context) with the rule and source behind each one. It then drafts the letters: a correction request, a Good Faith Estimate dispute summary or an EOB rebilling request. You review and send them yourself. It never sends anything, and it isn't legal or medical advice.

On our sample bills it finds the planted errors (12 of 12), flags nothing on the clean bill, and adds up the dollars correctly.

## How we built it
- **Models read and write; rules decide.** Every dollar and every Likely error comes from pure Python in `app/checks/`, each check tied to a CMS source. The models never compute money or decide an outcome.
- **Four Nemotron models, each with one job**, all through Nebius Token Factory with one client:
  - Nemotron 3.5 Super VL reads the bill and EOB images and PDFs.
  - Nemotron 3 Nano cleans codes, extracts doses and gates scope.
  - Nemotron 3 Ultra reviews only the "worth asking about" cases that CMS says need clinical judgment. It can keep a flag or downgrade it, never raise one or change an amount.
  - Nemotron 3 Super writes explanations and letter paragraphs, and picks hospital links from a Tavily search.
- **Zero AMA content.** Reference data is three CMS public-use files (HCPCS Level II, Part B payment limits, MUE table), loaded only for codes that start with a letter. A CPT-shaped code on a bill is shown unchanged and labelled "Not checked".
- **Stack:** Python 3.11, FastAPI, SQLite, pydantic, a React + Vite + Tailwind front end, Docker, Render. Every model call is logged (step, model, latency, tokens) without document text, and a "How this was checked" panel shows it.

## Challenges
- **Keeping models away from money.** A reader that gets one digit wrong would change a "likely error" total. Lines are confirmed by the patient, doses must appear in the line's own description, letter text is rejected if it contains a number the findings lack, and a model-read EOB is refused when its amounts don't add up or when the file looks like the bill itself.
- **No false accusations.** Charging above Medicare is usually legal, and Medicare's limits don't bind private insurers. Benchmarks are context only, insured patients get "ask for a billing review" wording, and the Good Faith Estimate overage is never added to the likely-error total.
- **Staying clean of CPT.** We purged CPT codes and descriptions from the data, code, tests, samples and docs, found and fixed a case-sensitivity bug in the ingest scrubber, and rebuilt the history so none of it ships.
- **Speed.** Reading a bill takes about 30 to 60 seconds end to end, longer on the first request to a sleeping free instance. We measured it and made the on-screen estimate honest.

## Accomplishments that we're proud of
Scorecard from the live eval on four sample bills (Maya as a PDF and as a photo, Dev with an EOB, and a clean bill), run through the real pipeline with no human corrections:
- 12 of 12 seeded errors caught, 0 missed, **0 false Likely-error flags**.
- Likely-error totals correct on 4 of 4 samples (for example $3,858.00 for Maya and $1,050.00 for Dev).
- Extraction accuracy **215 of 215 fields (100%)**, including the phone-style photo.
- 16 model calls, none failed, for about **$0.022** in estimated cost and 117 seconds of wall-clock time across all four samples.
- The same run with Nemotron 3 Ultra on every step it can run on was 2.1× the cost ($0.046) and faster (71 seconds) with the same results. We route to the cheapest model that does each job, and it holds up.

These are made-up samples written alongside the checks, so this shows the pipeline works as designed, not accuracy on real bills.

## What we learned
- Splitting the work works: a small model for cleanup, a vision model for reading, a large model only where judgment is needed, and plain code for everything that has to be right.
- A model that sounds certain is the risk. Guards that check its output against the source text (the dose in the description, the phone number in the search result, the numbers in the findings) mattered more than prompt wording.
- Honest wording is a feature. "Worth asking about" and "For context" kept the tool from accusing anyone.
- Small friction points added up on Token Factory (model naming, which model takes images, reasoning length). We logged them in `docs/feedback.md`.

## What's next
Requires an AMA CPT license: CPT code support, code-pair unbundling and procedure-level Medicare rates. Also appeals of denied claims. This demo includes no AMA CPT content; it uses CMS public-use files covering HCPCS Level II codes.
