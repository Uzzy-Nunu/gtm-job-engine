"""AI provider layer (PRD §11.1).

One job: send a prompt and get back JSON that matches a schema. Gemini is
the default (free tier in Phase 1); Claude is a config switch. A fake
provider powers dry runs and tests.

Every answer is checked against its JSON schema. An invalid answer is retried
once, then raises LLMError (PRD §11.2). Rate limits and server errors are
retried with backoff; requests are spaced out so the free tier isn't hit too
hard. Callers must redact text first (src/redact.py): this layer never sees
contact details.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Callable

import jsonschema
import requests

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
CLAUDE_URL = "https://api.anthropic.com/v1/messages"


class LLMError(RuntimeError):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def _parse_json(text: str):
    text = (text or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


def _describe(error) -> str:
    """A short reason an answer was rejected, without echoing its content
    (safe for public logs): e.g. "maxItems at fit_reasons", "required at (top)"."""
    if isinstance(error, jsonschema.ValidationError):
        where = "/".join(str(p) for p in error.absolute_path) or "(top)"
        detail = ""
        if error.validator == "required":
            detail = " " + str(error.message).split("'")[1] if "'" in str(error.message) else ""
        return f"{error.validator}{detail} at {where}"
    return "not valid JSON"


def _retry_delay(resp) -> float | None:
    """Seconds to wait, from Retry-After or Gemini's RetryInfo ("13s")."""
    header = resp.headers.get("Retry-After") if resp is not None else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    try:
        for detail in resp.json().get("error", {}).get("details", []):
            delay = detail.get("retryDelay")
            if delay:
                return float(str(delay).rstrip("s"))
    except (ValueError, AttributeError):
        pass
    return None


class BaseProvider:
    name = "base"

    def __init__(self, models: dict, max_retries: int = 3, backoff: float = 20,
                 min_interval: float = 4, sleep: Callable = time.sleep,
                 clock: Callable = time.monotonic, max_wait: float = 90):
        self.models = models
        self.max_retries = max_retries
        self.backoff = backoff
        self.min_interval = min_interval
        self.max_wait = max_wait
        self._sleep = sleep
        self._clock = clock
        self._last = None
        self.calls = 0                         # requests sent, including retries
        self.busy_retries = 0                  # retries after "busy / rate limited" replies
        self.format_problems: list[str] = []  # short, content-free reasons answers were retried
        self.backup_uses = 0                   # answers that came from a backup model
        self._busy_models: set[str] = set()    # models that stayed busy this run: go straight to backup

    # --- public ---------------------------------------------------------
    def generate_json(self, *, system: str, prompt: str, schema: dict, role: str = "fast") -> dict:
        model = self.models.get(role) or self.models.get("fast")
        if not model:
            raise LLMError(f"No model configured for role '{role}' (config.yaml > llm).")
        problem = None
        for attempt in range(2):  # one retry for an invalid answer (PRD §11.2)
            note = "" if problem is None else (
                f"\n\nYour previous answer was invalid ({problem}). Return only JSON matching the schema.")
            raw = self._call_with_backup(role, model, system, prompt + note, schema)
            try:
                data = _parse_json(raw)
                jsonschema.validate(data, schema)
                return data
            except (ValueError, jsonschema.ValidationError) as e:
                problem = str(e).splitlines()[0][:200]
                self.format_problems.append(_describe(e))
        raise LLMError(f"AI returned invalid output twice: {problem}")

    # --- internals ------------------------------------------------------
    def _pace(self):
        if self._last is not None:
            gap = self.min_interval - (self._clock() - self._last)
            if gap > 0:
                self._sleep(gap)
        self._last = self._clock()

    def _call_with_backup(self, role, model, system, prompt, schema) -> str:
        """Use the role's backup model (e.g. draft_backup) if the main one stays busy.
        Once a model has stayed busy, later requests in the same run go straight to the backup."""
        backup = self.models.get(f"{role}_backup")
        if not backup or backup == model:
            return self._call_with_retries(model, system, prompt, schema)
        if model not in self._busy_models:
            try:
                return self._call_with_retries(model, system, prompt, schema)
            except LLMError as e:
                if not e.retryable:
                    raise
                self._busy_models.add(model)
        raw = self._call_with_retries(backup, system, prompt, schema, retries=1)
        self.backup_uses += 1
        return raw

    def _call_with_retries(self, model, system, prompt, schema, retries=None) -> str:
        last = None
        retries = self.max_retries if retries is None else retries
        for attempt in range(retries + 1):
            self._pace()
            self.calls += 1
            try:
                return self._call(model, system, prompt, schema)
            except LLMError as e:
                last = e
                if not e.retryable or attempt == retries:
                    raise
                self.busy_retries += 1
                wait = getattr(e, "wait", None) or self.backoff * (2 ** attempt)
                self._sleep(min(wait, self.max_wait))
        raise last

    def _call(self, model, system, prompt, schema) -> str:  # pragma: no cover
        raise NotImplementedError


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, api_key: str, models: dict, session=None, timeout: int = 60, **kw):
        super().__init__(models, **kw)
        if not api_key:
            raise LLMError("LLM_API_KEY is not set. Add your Gemini key as a GitHub Secret.")
        self.session = session or requests.Session()
        self.session.headers.update({"x-goog-api-key": api_key, "Content-Type": "application/json"})
        self.timeout = timeout
        self.use_schema = True  # switched off if the API rejects the schema field

    def _body(self, system, prompt, schema):
        config = {"responseMimeType": "application/json", "temperature": 0.2}
        if self.use_schema:
            config["responseJsonSchema"] = schema
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": config,
        }

    def _call(self, model, system, prompt, schema) -> str:
        url = GEMINI_URL.format(model=model)
        try:
            resp = self.session.post(url, json=self._body(system, prompt, schema), timeout=self.timeout)
        except requests.RequestException as e:
            raise LLMError(f"Could not reach Gemini: {e}", retryable=True)

        if resp.status_code == 400 and self.use_schema and "responseJsonSchema" in resp.text:
            # Older API surface: fall back to plain JSON mode; we validate ourselves.
            self.use_schema = False
            return self._call(model, system, prompt, schema)
        if resp.status_code in (429, 500, 502, 503, 504):
            err = LLMError(f"Gemini {resp.status_code}: busy or rate-limited", retryable=True)
            err.wait = _retry_delay(resp)
            raise err
        if resp.status_code >= 400:
            raise LLMError(f"Gemini {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no answer")
            raise LLMError(f"Gemini returned no answer ({reason}).")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        if not text:
            raise LLMError(f"Gemini returned an empty answer ({candidates[0].get('finishReason')}).")
        return text


class ClaudeProvider(BaseProvider):
    name = "claude"

    def __init__(self, api_key: str, models: dict, session=None, timeout: int = 60, **kw):
        super().__init__(models, **kw)
        if not api_key:
            raise LLMError("LLM_API_KEY is not set. Add your Claude key as a GitHub Secret.")
        self.session = session or requests.Session()
        self.session.headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01",
                                     "content-type": "application/json"})
        self.timeout = timeout

    def _call(self, model, system, prompt, schema) -> str:
        body = {
            "model": model, "max_tokens": 4096, "temperature": 0.2,
            "system": system + "\n\nReply with only a JSON object matching this JSON Schema:\n"
                      + json.dumps(schema),
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            resp = self.session.post(CLAUDE_URL, json=body, timeout=self.timeout)
        except requests.RequestException as e:
            raise LLMError(f"Could not reach Claude: {e}", retryable=True)
        if resp.status_code in (429, 500, 502, 503, 504, 529):
            err = LLMError(f"Claude {resp.status_code}: busy or rate-limited", retryable=True)
            err.wait = _retry_delay(resp)
            raise err
        if resp.status_code >= 400:
            raise LLMError(f"Claude {resp.status_code}: {resp.text[:300]}")
        return "".join(b.get("text", "") for b in resp.json().get("content", []) if b.get("type") == "text")


class FakeProvider(BaseProvider):
    """For dry runs and tests: answers come from a function, nothing is sent."""
    name = "fake"

    def __init__(self, answer: Callable[[str, str, dict], dict | str], models=None, **kw):
        kw.setdefault("min_interval", 0)
        super().__init__(models or {"fast": "fake-fast", "draft": "fake-draft"}, **kw)
        self.answer = answer
        self.prompts: list[str] = []

    def _call(self, model, system, prompt, schema) -> str:
        self.prompts.append(prompt)
        result = self.answer(system, prompt, schema)
        return result if isinstance(result, str) else json.dumps(result)


def make_llm(config: dict, api_key: str | None = None):
    """Build the provider named in config.yaml (llm.provider)."""
    llm = config.get("llm") or {}
    provider = (llm.get("provider") or "gemini").lower()
    models = {"fast": llm.get("fast_model"), "draft": llm.get("draft_model"),
              "draft_backup": llm.get("draft_backup_model")}
    kw = {"max_retries": int(llm.get("max_retries", 3)),
          "backoff": float(llm.get("retry_backoff_seconds", 20)),
          "min_interval": float(llm.get("min_seconds_between_calls", 4))}
    key = api_key if api_key is not None else os.environ.get("LLM_API_KEY", "").strip()
    if provider == "gemini":
        return GeminiProvider(key, models, **kw)
    if provider == "claude":
        return ClaudeProvider(key, models, **kw)
    raise LLMError(f"Unknown llm.provider '{provider}' in config.yaml (use gemini or claude).")
