"""Read the master CV and hand out only the sections each AI step needs
(PRD §12 "Master CV storage", CLAUDE.md rules 1 and 5).

The master CV is never in the repo. It comes from:
  - the MASTER_CV environment variable (GitHub Secret) in scheduled runs, or
  - a local file named by MASTER_CV_PATH (outside the repo) for local runs.

The CONTACT section is never returned, and every section handed out is passed
through redact() as a second safety net. Never print CV content: GitHub
Actions logs on a public repo are public.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from src.redact import redact

# Sections the Qualify step needs to judge fit (headings start with these).
QUALIFY_SECTIONS = ("TARGET TITLES", "CORE SKILLS", "TOOLS & TECHNOLOGIES")
NEVER_SHARE = ("CONTACT",)


class MasterCVError(RuntimeError):
    pass


def load_text() -> str:
    text = os.environ.get("MASTER_CV", "")
    if not text.strip():
        path = os.environ.get("MASTER_CV_PATH", "").strip()
        if path:
            p = Path(path)
            if not p.exists():
                raise MasterCVError(f"MASTER_CV_PATH points to a missing file: {p.name}")
            text = p.read_text(encoding="utf-8")
    if not text.strip():
        raise MasterCVError("Master CV not found. Add it as the MASTER_CV GitHub Secret "
                            "(or set MASTER_CV_PATH for local runs).")
    return text


def sections(text: str) -> dict[str, str]:
    """'## HEADING' -> body text, in order. Headings are upper-cased."""
    found: dict[str, str] = {}
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE)
    if len(parts) == 1:
        # No "## " markers: the text was probably copied from a formatted
        # preview. Fall back to headings written in capitals ("CORE SKILLS").
        parts = re.split(r"^(" + _CAPS_HEADING + r")[ \t]*$", text, flags=re.MULTILINE)
        parts = [p for i, p in enumerate(parts) if i % 2 == 0 or p is not None]
    for i in range(1, len(parts), 2):
        heading = parts[i].strip().upper()
        found[heading] = parts[i + 1].strip().strip("-").strip()
    return found


# A line whose text before any "(" or "[" is ALL CAPS, e.g.
# "CORE SKILLS (grouped; ...)" or "CONTACT  [inserted by code]".
_CAPS_HEADING = r"[A-Z][A-Z0-9&/' -]{2,}[A-Z](?:[ \t]*[(\[][^\n]*)?"  # one line only


def pick(text: str, wanted: tuple[str, ...]) -> str:
    """The wanted sections only, redacted, as one block for a prompt."""
    chosen = []
    for heading, body in sections(text).items():
        if heading.startswith(NEVER_SHARE):
            continue
        if heading.startswith(wanted):
            chosen.append(f"## {heading}\n{redact(body)}")
    if not chosen:
        raise MasterCVError(f"Master CV has none of these sections: {', '.join(wanted)}")
    return "\n\n".join(chosen)


def qualify_profile(text: str | None = None) -> str:
    """Target titles, core skills and tools, plus an experience overview (role
    titles, dates and bullets, no employer names) so the AI can judge seniority
    and real experience, not just keyword lists (decision 24 Nov 2026)."""
    text = text if text is not None else load_text()
    profile = pick(text, QUALIFY_SECTIONS)
    try:
        from src.cv_model import experience_overview, parse_master_cv
        cv = parse_master_cv(text)
        if cv.roles:
            profile += "\n\n" + experience_overview(cv)
    except Exception:  # noqa: BLE001 - an odd CV layout still leaves the skills profile
        pass
    return profile
