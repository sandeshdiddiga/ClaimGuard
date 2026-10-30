# Deploying ClaimGuard

The image ships `data/claimguard.db`: the CMS public-use Level II reference tables (HCPCS, Part B payment limits,
MUE) and nothing else. It builds the web front end, installs the Python dependencies and runs as a non-root user.
It needs one secret, `NEBIUS_API_KEY`, and optionally `TAVILY_API_KEY` (without it the hospital lookup is off).

`/health` returns 200 only when the reference database opens read-only and a smoke query works: one row from each
table read back through the same functions the checks use, and no code that starts with a digit. Otherwise 503.

## Deploy from GitHub to Render

1. Check what you are about to publish: `git ls-files | grep -E '\.db$'` must list only `data/claimguard.db` and
   `tests/fixtures/reference.db`; `git ls-files | grep -E '^\.env'` must list only `.env.example`.
2. Push `main` to GitHub (see the README or `git push -u origin main`).
3. Render dashboard, New, Blueprint, connect GitHub, choose the repo and the `main` branch. Render reads `render.yaml`.
4. When asked for the two secret values, enter `NEBIUS_API_KEY`. Leave `TAVILY_API_KEY` empty if you do not want the
   lookup. Render prompts for them only on the first creation; later, add or change them under the service's
   Environment tab.
5. Click Apply. Watch the build log (front end, dependencies, runtime image), then the deploy.
6. Open `https://<service>.onrender.com/health`: `{"status":"ok"}`. Then open the home page and try the three samples.

The free plan sleeps after a period of idle time, and the next visit wakes it (a slow first load). Case data lives on
the instance's own disk and is lost on every redeploy or restart, which is fine for a demo.

## Run the image locally

```bash
docker build -t claimguard .
docker run --rm -p 8000:8000 -e NEBIUS_API_KEY=<key> claimguard
curl localhost:8000/health
```
