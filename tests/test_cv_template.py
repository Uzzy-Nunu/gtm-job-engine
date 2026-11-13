"""Checks that the CV template and renderer follow the ATS rules (PRD §12)."""

import re
from pathlib import Path

import pytest
import yaml
from docx import Document
from docx.oxml.ns import qn

from src.render_docx import (CV_TEMPLATE, SECTION_ORDER, contact_line,
                             date_range, docx_to_text, format_month, plain,
                             render_cv)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "sample_tailored_cv.yaml"
COVER_TEMPLATE = ROOT / "templates" / "cover_letter_template.docx"

DATE_RANGE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4} - "
    r"((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}|Present)$")

# Rough capacity of one A4 page at 10.5pt with these margins.
CHARS_PER_LINE = 105
LINES_PER_PAGE = 58


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    cv = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    out = tmp_path_factory.mktemp("cv") / "sample_cv.docx"
    render_cv(cv, out)
    return out


def _assert_ats_safe_structure(path: Path):
    doc = Document(str(path))
    xml = doc.element.xml
    assert len(doc.tables) == 0, "no tables"
    assert len(doc.inline_shapes) == 0, "no images"
    for tag in ("w:drawing", "w:pict", "w:txbxContent", "mc:AlternateContent"):
        assert f"<{tag}" not in xml, f"no {tag} (images / text boxes)"
    assert len(doc.sections) == 1, "one section only"
    section = doc.sections[0]
    cols = section._sectPr.find(qn("w:cols"))
    if cols is not None and cols.get(qn("w:num")):
        assert cols.get(qn("w:num")) == "1", "single column"
    for part in (section.header, section.footer):
        assert all(not p.text.strip() for p in part.paragraphs), "no header/footer text"
        assert not part.tables


@pytest.mark.parametrize("template", [CV_TEMPLATE, COVER_TEMPLATE])
def test_templates_exist_and_are_ats_safe(template):
    assert template.exists(), "run: python scripts/build_templates.py"
    _assert_ats_safe_structure(template)


def test_rendered_cv_is_ats_safe(rendered):
    _assert_ats_safe_structure(rendered)


def test_headings_are_standard_capitalised_and_in_order(rendered):
    doc = Document(str(rendered))
    headings = [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]
    expected = [h for _, h in SECTION_ORDER]
    assert headings == expected
    assert all(h == h.upper() for h in headings)


def test_bullets_are_plain_hyphens(rendered):
    doc = Document(str(rendered))
    bullets = [p.text for p in doc.paragraphs if p.style.name == "CV Bullet"]
    assert bullets, "sample has bullets"
    assert all(b.startswith("- ") for b in bullets)
    # no Word auto-numbering / list formatting
    assert "<w:numPr" not in doc.element.xml


def test_dates_use_mon_yyyy_format(rendered):
    doc = Document(str(rendered))
    dates = [p.text for p in doc.paragraphs if p.style.name == "CV Role Meta"]
    assert dates
    for d in dates:
        assert DATE_RANGE.match(d), d


def test_contact_line_shows_remote_without_country(rendered):
    doc = Document(str(rendered))
    line = doc.paragraphs[1].text
    assert line.startswith("Remote | ")
    assert "Nigeria" not in line and "based" not in line.lower()


def test_plain_text_paste_is_clean(rendered):
    text = docx_to_text(rendered)
    # Only characters that survive a paste into Notepad / an ATS text box
    bad = sorted({c for c in text if not (c.isascii() and (c.isprintable() or c == "\n"))})
    assert not bad, f"non-plain characters found: {bad}"
    assert "\t" not in text


def test_sample_fits_in_two_pages(rendered):
    text = docx_to_text(rendered)
    lines = sum(max(1, -(-len(line) // CHARS_PER_LINE)) for line in text.splitlines())
    assert lines <= 2 * LINES_PER_PAGE, f"about {lines} lines, too long for 2 pages"


def test_format_month():
    assert format_month("2023-01") == "Jan 2023"
    assert format_month("present") == "Present"
    assert format_month(None) == "Present"
    assert date_range("2021-1", "2023-12") == "Jan 2021 - Dec 2023"
    with pytest.raises(ValueError):
        format_month("January 2023")


def test_plain_replaces_smart_characters():
    assert plain("“Growth” – it’s • done…") == \
        '"Growth" - it\'s - done...'


def test_contact_line_skips_missing_fields():
    assert contact_line({"email": "a@example.com"}) == "Remote | a@example.com"
