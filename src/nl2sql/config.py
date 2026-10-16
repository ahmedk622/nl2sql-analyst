"""Central settings, loaded from environment variables / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

# Both providers expose an OpenAI-compatible /chat/completions endpoint.
PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
    },
}


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    llm_provider: str
    llm_api_key: str
    llm_model: str
    llm_base_url: str
    max_rows: int
    max_repairs: int
    log_path: Path

    @property
    def db_url(self) -> URL:
        return URL.create(
            "mysql+pymysql",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_api_key) and self.llm_api_key != "paste_your_key_here"


def load_settings() -> Settings:
    provider = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError(f"LLM_PROVIDER must be one of {sorted(PROVIDERS)}, got {provider!r}")
    spec = PROVIDERS[provider]
    return Settings(
        db_host=os.getenv("DB_HOST", "127.0.0.1"),
        db_port=int(os.getenv("DB_PORT", "3306")),
        db_name=os.getenv("DB_NAME", "analytics_demo"),
        db_user=os.getenv("DB_USER", "analyst_ro"),
        db_password=os.getenv("DB_PASSWORD", ""),
        llm_provider=provider,
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        llm_model=os.getenv("LLM_MODEL", spec["model"]),
        llm_base_url=spec["base_url"],
        max_rows=int(os.getenv("MAX_ROWS", "500")),
        max_repairs=int(os.getenv("MAX_REPAIRS", "2")),
        log_path=ROOT / "logs" / "llm_calls.jsonl",
    )
