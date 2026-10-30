# ClaimGuard web app. The image ships data/claimguard.db: the CMS public-use Level II reference tables (HCPCS,
# Part B payment limits, MUE), nothing else. Runtime settings: NEBIUS_API_KEY, optionally TAVILY_API_KEY.

# --- 1. front end ---------------------------------------------------------------------------------
FROM node:20-alpine3.20 AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/index.html web/tsconfig.json web/vite.config.ts ./
COPY web/src ./src
RUN npm run build

# --- 2. python dependencies -----------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS deps
WORKDIR /app
RUN pip install --no-cache-dir uv==0.9.5
ENV UV_PROJECT_ENVIRONMENT=/app/.venv UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --- 3. runtime -----------------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime
# WeasyPrint draws the letter PDFs with pango.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --system --uid 10001 --home-dir /app appuser
WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
COPY app ./app
COPY samples ./samples
COPY --from=web /web/dist ./web/dist
# The reference database is read-only (the app opens it with mode=ro); the app writes its case state beside it.
COPY data/claimguard.db ./data/claimguard.db
RUN chown appuser:appuser /app/data && chmod 444 /app/data/claimguard.db
USER appuser
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=4)"]
CMD ["sh", "-c", "exec python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'"]
