"""Runtime settings for the web app. Tests build their own; production reads the environment."""

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from app.llm import LLMClient
from app.lookup import SearchFn, tavily_from_key
from app.store import Store

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    reference_db: Path
    state_db: Path
    samples_dir: Path
    static_dir: Path | None = None
    offline: bool = False  # no model calls at all (pdfplumber reading, template letters)
    vision: bool = True  # read documents with the vision model when models are on
    llm_factory: Callable[[Store], LLMClient] | None = None  # tests inject a fake client here
    search: SearchFn | None = None  # hospital lookup; None (no TAVILY_API_KEY) turns it off
    today: Callable[[], date] = field(default=date.today)
    max_upload_bytes: int = 10 * 1024 * 1024
    max_cases_per_hour: int = 30
    max_lookups_per_hour: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        dist = ROOT / "web" / "dist"
        return cls(
            reference_db=Path(os.environ.get("REFERENCE_DB_PATH", ROOT / "data" / "claimguard.db")),
            state_db=Path(os.environ.get("STATE_DB_PATH", ROOT / "data" / "state.db")),
            samples_dir=ROOT / "samples",
            static_dir=dist if dist.exists() else None,
            offline=os.environ.get("CLAIMGUARD_OFFLINE") == "1",
            search=tavily_from_key(os.environ.get("TAVILY_API_KEY")),
        )
