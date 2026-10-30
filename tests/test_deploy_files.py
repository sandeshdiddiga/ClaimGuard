"""The container and the Render blueprint: no CMS data, no secrets, runs as a non-root user."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ("NEBIUS_API_KEY", "TAVILY_API_KEY")


def lines(name: str) -> list[str]:
    return [x.strip() for x in (ROOT / name).read_text().splitlines()]


def test_dockerignore_keeps_raw_data_state_and_secrets_out_but_lets_the_reference_db_in() -> None:
    ignored = set(lines(".dockerignore"))
    for pattern in ("data/*", "!data/claimguard.db", ".env", ".git", "tests", "node_modules"):
        assert pattern in ignored, pattern
    assert "data" not in ignored and "*.db" in ignored  # a bare `data` would drop the reference database too


def test_dockerfile_copies_only_the_reference_database_from_data_and_sets_no_secrets() -> None:
    text = (ROOT / "Dockerfile").read_text()
    for line in text.splitlines():
        if line.strip().upper().startswith(("COPY", "ADD")) and re.search(r"\b(data|Data)\b|\.db\b|\.env", line):
            assert "data/claimguard.db" in line and "--from" not in line, line
    for name in (*SECRETS, "REFERENCE_DB_URL", "REFERENCE_DB_SHA256"):
        assert not re.search(rf"^\s*(ENV|ARG)\s+{name}\b", text, re.MULTILINE), name


def test_dockerfile_runs_as_a_non_root_user_with_a_healthcheck() -> None:
    text = (ROOT / "Dockerfile").read_text()
    assert re.search(r"^USER\s+(?!root)\S+", text, re.MULTILINE)
    assert "HEALTHCHECK" in text and "/health" in text
    assert re.search(r"^FROM\s+\S+:(?!latest)\S+", text, re.MULTILINE)  # pinned tags only
    assert "libpango" in text  # letters are PDFs


def test_render_blueprint_needs_only_the_two_keys_and_keeps_them_out_of_the_repo() -> None:
    text = lines("render.yaml")
    assert "healthCheckPath: /health" in text and "runtime: docker" in text
    keys = [x.split()[2] for x in text if x.startswith("- key:")]
    assert keys == list(SECRETS)
    for name in SECRETS:
        at = text.index(next(x for x in text if x.startswith(f"- key: {name}")))
        assert text[at + 1] == "sync: false", name
    assert not any("REFERENCE_DB" in x for x in text)
    assert not any(x.startswith("autoDeploy:") for x in text)  # deprecated: autoDeployTrigger replaces it
