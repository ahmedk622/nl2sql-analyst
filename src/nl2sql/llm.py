"""Thin, provider-agnostic LLM client (OpenAI-compatible REST) with retries and call logging."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import requests


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    model: str = ""


class ChatModel(Protocol):
    """Anything with this method can drive the pipeline (real client or a test fake)."""

    def chat(self, messages: list[dict], purpose: str = "generate", **kw) -> LLMResponse: ...


class LLMClient:
    def __init__(self, provider: str, api_key: str, model: str, base_url: str,
                 log_path: Path | None = None, timeout: int = 60, max_retries: int = 3):
        self.provider, self.api_key, self.model = provider, api_key, model
        self.base_url = base_url.rstrip("/")
        self.log_path, self.timeout, self.max_retries = log_path, timeout, max_retries

    def chat(self, messages: list[dict], purpose: str = "generate",
             temperature: float = 0.0, max_tokens: int = 3000) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {"model": self.model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens}
        if "gpt-oss" in self.model:
            body["reasoning_effort"] = "low"
        last_err = ""
        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            try:
                r = requests.post(url, headers=headers, json=body, timeout=self.timeout)
            except requests.RequestException as e:
                last_err = f"network error: {e}"
                time.sleep(2 ** attempt)
                continue
            latency = int((time.perf_counter() - started) * 1000)
            if r.status_code == 200:
                data = r.json()
                usage = data.get("usage") or {}
                resp = LLMResponse(
                    text=(data["choices"][0]["message"]["content"] or "").strip(),
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    latency_ms=latency, model=self.model,
                )
                self._log(purpose, resp, attempt)
                return resp
            if r.status_code in (401, 403):
                raise LLMError(f"Authentication failed ({r.status_code}). Check LLM_API_KEY / LLM_PROVIDER.")
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                wait = float(r.headers.get("retry-after", 2 ** attempt))
                time.sleep(min(wait, 20))
                continue
            raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
        raise LLMError(f"LLM request failed after retries ({last_err})")

    def _log(self, purpose: str, resp: LLMResponse, retries: int) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "provider": self.provider, "model": resp.model, "purpose": purpose,
               "prompt_tokens": resp.prompt_tokens, "completion_tokens": resp.completion_tokens,
               "latency_ms": resp.latency_ms, "retries": retries}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
