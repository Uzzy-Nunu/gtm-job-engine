"""Remove contact details before any text is sent to an AI model (PRD §11.1,
CLAUDE.md rule 5).

The free Gemini tier may use prompts to improve Google's products and they may
be read by human reviewers, so job text is cleaned first:
- email addresses
- phone numbers
- social / professional profile links (LinkedIn, X/Twitter, Facebook,
  Instagram, GitHub, Calendly and similar)
- Peace's private notes block, which the AI never needs

Ordinary company and job links are kept, since they help with research.
"""

from __future__ import annotations

import re

NOTES_MARKER = "\n\n--- Notes from Peace ---"

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Profile and personal-contact link hosts. Matches with or without https://.
PROFILE_HOSTS = (
    r"(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|pub|profile)/", r"lnkd\.in/",
    r"(?:www\.)?(?:twitter|x)\.com/", r"(?:www\.)?facebook\.com/", r"fb\.me/",
    r"(?:www\.)?instagram\.com/", r"(?:www\.)?tiktok\.com/@", r"(?:www\.)?github\.com/",
    r"calendly\.com/", r"cal\.com/", r"wa\.me/", r"t\.me/", r"(?:www\.)?threads\.net/@",
)
PROFILE_LINK = re.compile(
    r"(?:https?://)?(?:" + "|".join(PROFILE_HOSTS) + r")[^\s<>\"')\]]*", re.IGNORECASE)

# Phone numbers: international (+234 803 123 4567), US style ((415) 555-0134),
# and long digit runs with separators. Avoids years, salaries and IDs by
# requiring 7+ digits with phone-like grouping.
PHONE = re.compile(
    r"(?<![\w/])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{1,4}\)[\s.-]?)?\d{2,4}(?:[\s.-]\d{2,4}){1,4}(?![\w/])")


def _looks_like_phone(match: str) -> bool:
    digits = re.sub(r"\D", "", match)
    if not 7 <= len(digits) <= 15:
        return False
    if re.fullmatch(r"(19|20)\d{2}[\s.-](19|20)\d{2}", match.strip()):  # year ranges
        return False
    return match.strip().startswith(("+", "(")) or bool(re.search(r"\d[\s.-]\d", match))


def strip_notes(text: str) -> str:
    return (text or "").split(NOTES_MARKER)[0]


def redact(text: str) -> str:
    """Return text with contact details replaced by placeholders."""
    text = strip_notes(text)
    text = PROFILE_LINK.sub("[profile link removed]", text)
    text = EMAIL.sub("[email removed]", text)
    text = PHONE.sub(lambda m: "[phone removed]" if _looks_like_phone(m.group(0)) else m.group(0), text)
    return text
