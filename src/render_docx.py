"""Render a tailored CV as an ATS-safe .docx (PRD §12).

The AI decides *what* goes in (bullet selection and wording). This module
decides *how* it looks: fixed section order, standard capitalised headings,
hyphen bullets, `Mon YYYY - Mon YYYY` dates, single column, no tables,
images, headers or footers.

Name and contact details are inserted here by code. They are never sent to
or returned by the AI.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parents[1]
CV_TEMPLATE = ROOT / "templates" / "cv_template.docx"

# Fixed order of sections (PRD §12). Empty sections are skipped.
SECTION_ORDER = [
    ("summary", "PROFESSIONAL SUMMARY"),
    ("core_skills", "CORE SKILLS"),
    ("tools", "TOOLS & TECHNOLOGIES"),
    ("experience", "PROFESSIONAL EXPERIENCE"),
    ("projects", "PROJECTS"),
    ("education", "EDUCATION"),
    ("certifications", "CERTIFICATIONS"),
    ("languages", "LANGUAGES"),
]

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Characters that look fine in Word but turn into junk in some ATS parsers
# or when pasted into a plain-text box.
_PLAIN_TEXT_MAP = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-",
    "•": "-", "●": "-", "▪": "-", "‣": "-",
    "…": "...", " ": " ", "​": "",
}


def plain(text: str) -> str:
    """Make text plain-text safe: straight quotes, hyphens, single spaces."""
    for bad, good in _PLAIN_TEXT_MAP.items():
        text = text.replace(bad, good)
    return re.sub(r"[ \t]+", " ", text).strip()


def format_month(value: str | date | None) -> str:
    """'2023-01' -> 'Jan 2023'. None / 'present' -> 'Present'."""
    if value is None:
        return "Present"
    if isinstance(value, date):
        return f"{MONTHS[value.month - 1]} {value.year}"
    text = str(value).strip()
    if text.lower() in {"present", "current", "now", ""}:
        return "Present"
    match = re.fullmatch(r"(\d{4})-(\d{1,2})", text)
    if not match:
        raise ValueError(f"Date must be YYYY-MM or 'present', got {value!r}")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"Bad month in {value!r}")
    return f"{MONTHS[month - 1]} {year}"


def date_range(start, end) -> str:
    return f"{format_month(start)} - {format_month(end)}"


def contact_line(contact: dict, location_label: str = "Remote") -> str:
    """Location is always shown as 'Remote' with no country (CLAUDE.md rule 6)."""
    parts = [location_label]
    for key in ("email", "phone", "linkedin", "portfolio"):
        if contact.get(key):
            parts.append(plain(contact[key]))
    return " | ".join(parts)


def _bullet(doc, text: str) -> None:
    doc.add_paragraph("- " + plain(text).lstrip("-* ").strip(), style="CV Bullet")


def render_cv(cv: dict, out_path: Path, template: Path = CV_TEMPLATE,
              location_label: str = "Remote") -> Path:
    """Render tailored CV data to a .docx file.

    Expected keys: name, contact{email, linkedin, ...}, summary, core_skills[],
    tools[], experience[{title, company, start, end, bullets[]}],
    projects[{name, bullets[]}], education[{degree, school, start, end}],
    certifications[], languages[].
    """
    doc = Document(str(template))

    doc.add_paragraph(plain(cv["name"]), style="CV Name")
    doc.add_paragraph(contact_line(cv.get("contact", {}), location_label),
                      style="CV Contact")

    for key, heading in SECTION_ORDER:
        content = cv.get(key)
        if not content:
            continue
        doc.add_paragraph(heading, style="Heading 1")

        if key == "summary":
            doc.add_paragraph(plain(content))

        elif key in ("core_skills", "tools", "languages"):
            # One plain line, comma separated: parses cleanly and saves space
            doc.add_paragraph(", ".join(plain(x) for x in content))

        elif key == "certifications":
            for item in content:
                _bullet(doc, item)

        elif key == "experience":
            for role in content:
                doc.add_paragraph(
                    f"{plain(role['title'])} - {plain(role['company'])}",
                    style="CV Role")
                doc.add_paragraph(date_range(role.get("start"), role.get("end")),
                                  style="CV Role Meta")
                for b in role.get("bullets", []):
                    _bullet(doc, b)

        elif key == "projects":
            for project in content:
                doc.add_paragraph(plain(project["name"]), style="CV Role")
                for b in project.get("bullets", []):
                    _bullet(doc, b)

        elif key == "education":
            for edu in content:
                doc.add_paragraph(
                    f"{plain(edu['degree'])} - {plain(edu['school'])}",
                    style="CV Role")
                if edu.get("start") or edu.get("end"):
                    doc.add_paragraph(date_range(edu.get("start"), edu.get("end")),
                                      style="CV Role Meta")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path


def docx_to_text(path: Path) -> str:
    """What an ATS (or Notepad after copy-paste) would see."""
    return "\n".join(p.text for p in Document(str(path)).paragraphs)
