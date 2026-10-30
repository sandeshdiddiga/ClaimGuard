# Token Factory and Nemotron feedback

Dated friction points (what I tried, what happened, what I'd change). Top three suggestions go at the end.

## 2026-10-28

**`GET /v1/models` returned 401 with the API key from `.env`.**
- Tried: `openai.OpenAI(base_url="https://api.tokenfactory.nebius.com/v1/", api_key=...).models.list()`
  as in the quickstart.
- Happened: `AuthenticationError: Error code: 401`, no further detail in the exception shown.
- Cause: not yet known (key value, key permissions, or project/endpoint mismatch). Not diagnosed.
- Would change: an error body that says whether the key is unknown, revoked, or lacks access to the model
  list, so the cause is clear without trial and error.

## 2026-10-28: 401 resolved, model IDs
- Token Factory listed five Nemotron models. Only `Nemotron-3.5-Super-VL` accepts images, so it reads documents; the name "Nano 2 VL" in our plan has no match in the list.
- Live run: the three sample bills and Dev's EOB were read correctly by the vision model (4 live tests pass, about 2 minutes in total, so the vision step is slow).

## 2026-10-28: judge, letters, scope gate
- Ultra, Super and Nano all follow "reply with only a JSON object" on the first try with the schema in a system message; no retries seen in the live run (Ultra judge, 10 Nano redirects, two Super paragraphs: about 25 s in total).
- Super's first draft told the hospital the pairs "should not be billed separately", stronger than our wording. Fixed in the prompt ("appear", "were flagged for review") and by rejecting any number the findings lack.
- The openai SDK and pdfminer both log request or page text at DEBUG. We silence them in code; a way to turn off body logging in the SDK would help.

## 2026-10-28: model IDs are hard to guess
- Token Factory's four Nemotron IDs use three different casings and naming styles: `nvidia/Nemotron-3.5-Super-VL`,
  `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, `nvidia/Nemotron-3-Ultra-550b-a55b` and `nvidia/nemotron-3-super-120b-a12b`.
  I couldn't derive one from another or from the marketing names ("Nano 2 VL" in my plan matched nothing).
- Would change: one naming pattern, plus short stable aliases (for example `nemotron-3-ultra`) that point at the current ID.

## 2026-10-30: reading latency
- Reading a bill with the vision model averaged 7.4 s per document in the eval; end to end, creating a case on the
  deployed app took 37 to 70 s (first request after a cold start included). Most of that is the reading step plus code
  cleaning, so the UI said "usually 10 to 20 seconds" until I measured it and changed the text.
- Would change: documented typical latency per model, and a way to see time to first token so a progress bar can be honest.

## 2026-10-30: Nano was slower than Ultra on the same job
- Eval, code-cleaning step, same four samples: Nemotron 3 Nano used 6,182 output tokens over 55.6 s in total (13.9 s per
  call); Nemotron 3 Ultra used 3,889 output tokens over 12.2 s (3.1 s per call). The prompt asks for a short JSON answer.
- I can't tell from the response why the smaller model writes more (hidden reasoning, longer JSON, or both).
- Would change: a documented parameter to cap or switch off reasoning, and reasoning tokens reported separately in `usage`.

## 2026-10-30: Ultra doesn't accept images
- Running the all-Ultra comparison, the reading step had to stay on `Nemotron-3.5-Super-VL`: Token Factory lists Ultra as
  text only. I found this from the `modality` field of `GET /v1/models`, which was useful; the same response also has
  `pricing`, which let the eval compute cost from logged tokens.
- Would change: list supported parameters (JSON mode, image input, max output) in the same response, and say in the model
  docs which Nemotron models take images.

## 2026-10-30: PDFs
- I found no documented PDF input for the vision model, so the app renders each PDF page to a PNG and sends images. That
  works, but it costs time and tokens and discards the text layer a text PDF already has (pdfplumber is the fallback).
- Would change: say in the docs whether PDFs can be sent directly, and give a recommended image size and page count.

## Top three suggestions
1. **Predictable model naming and capability metadata.** One ID style with stable aliases, and `GET /v1/models` listing
   image input, JSON/structured output and maximum output tokens next to `pricing` and `modality`. This is the part
   that cost me trial and error (IDs, which model reads images, which model supports what).
2. **A control for reasoning length, with reasoning tokens in `usage`.** In my eval the smaller model (Nano) was slower
   and wrote more tokens than the larger one (Ultra) on a short structured task. A switch to cap or disable reasoning, and
   a separate count, would let developers route by real cost and latency.
3. **Better errors and quieter SDK logging.** A 401 should say whether the key is unknown, revoked or lacks model-list
   access (my first call gave only "Error code: 401"), and a documented way to turn off request-body logging in the `openai`
   SDK, because bills are sensitive documents and the default DEBUG logging includes request text.
