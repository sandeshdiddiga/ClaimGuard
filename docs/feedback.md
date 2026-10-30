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
