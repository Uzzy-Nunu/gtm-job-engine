"""Minimal HubSpot REST client.

Authenticates with a HubSpot Service Key (Bearer token) read from the
HUBSPOT_TOKEN environment variable. Retries on rate limits and server errors,
and raises HubSpotError with HubSpot's own message so failures are loud and
readable.
"""

from __future__ import annotations

import json as _json
import os
import time
from pathlib import Path

import requests

BASE_URL = "https://api.hubapi.com"
# Files API: the classic path first, then the dated one HubSpot documents now.
FILE_UPLOAD_PATHS = ("/files/v3/files", "/files/2026-09/files")
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class HubSpotError(RuntimeError):
    def __init__(self, status: int, message: str, category: str = "",
                 path: str = ""):
        self.status = status
        self.category = category
        self.path = path
        super().__init__(f"HubSpot {status} {category} on {path}: {message}".strip())

    @property
    def not_found(self) -> bool:
        return self.status == 404


def load_dotenv(path: Path) -> None:
    """Load KEY=value lines from a local .env file (git-ignored), if present."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class HubSpotClient:
    def __init__(self, token: str | None = None, max_retries: int = 4,
                 timeout: int = 30):
        token = token or os.environ.get("HUBSPOT_TOKEN", "").strip()
        if not token:
            raise SystemExit(
                "HUBSPOT_TOKEN is not set. Add it as a GitHub Secret (or to a "
                "local .env file, which git ignores). Never paste it into code.")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        self.max_retries = max_retries
        self.timeout = timeout

    def request(self, method: str, path: str, *, params=None, json=None, files=None, data=None):
        url = BASE_URL + path
        # Multipart uploads set their own Content-Type (None removes the JSON default).
        headers = {"Content-Type": None} if files else None
        for attempt in range(self.max_retries + 1):
            resp = self.session.request(method, url, params=params, json=json, files=files, data=data,
                                        headers=headers, timeout=self.timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self.max_retries:
                    wait = float(resp.headers.get("Retry-After", 2 ** attempt * 2))
                    time.sleep(wait)
                    continue
            if resp.status_code >= 400:
                try:
                    body = resp.json()
                except ValueError:
                    body = {"message": resp.text[:300]}
                message = body.get("message", "")
                ctx = body.get("context") or {}
                if body.get("category") == "MISSING_SCOPES" or "requiredGranularScopes" in ctx:
                    message += f" | required scopes: {ctx}"
                raise HubSpotError(resp.status_code, message,
                                   body.get("category", ""), path)
            if resp.status_code == 204 or not resp.content:
                return None
            return resp.json()
        raise HubSpotError(429, "gave up after retries", "RATE_LIMITS", path)

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, json):
        return self.request("POST", path, json=json)

    def patch(self, path, json):
        return self.request("PATCH", path, json=json)

    def put(self, path, json=None):
        return self.request("PUT", path, json=json)

    def upload(self, filename: str, content: bytes, folder_path: str, access: str = "PRIVATE") -> dict:
        """Upload one file to the HubSpot file manager. Returns its record (id, url, ...)."""
        files = {"file": (filename, content, DOCX_TYPE)}
        data = {"options": _json.dumps({"access": access}), "folderPath": folder_path, "fileName": filename}
        last = None
        for path in FILE_UPLOAD_PATHS:
            try:
                return self.request("POST", path, files=files, data=data)
            except HubSpotError as e:
                if e.status != 404:
                    raise
                last = e
        raise last

    def delete(self, path, params=None):
        return self.request("DELETE", path, params=params)
