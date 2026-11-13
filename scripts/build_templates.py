"""Build the ATS-safe Word templates in templates/.

The templates hold page setup and text styles only (no content), so the
renderer in src/render_docx.py controls structure and order (PRD §12).

ATS rules applied here:
- single column, one section, no headers or footers
- standard fonts, no tables, text boxes, images or icons
- section headings use the built-in "Heading 1" style so parsers can find them

Run:  python scripts/build_templates.py
"""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"

FONT = "Calibri"
BLACK = RGBColor(0, 0, 0)


def _set_font(style, size, bold=False, italic=False):
    font = style.font
    font.name = FONT
    font.size = Pt(size)
    font.bold = bold
    font.italic = italic
    font.color.rgb = BLACK
    # Make sure East Asian fallback also uses the same font
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(attr), FONT)


def _spacing(style, before=0, after=0, line=1.0):
    pf = style.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line


def _get_or_add_style(doc, name, base="Normal"):
    from docx.enum.style import WD_STYLE_TYPE

    styles = doc.styles
    if name in [s.name for s in styles]:
        return styles[name]
    style = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    style.base_style = styles[base]
    style.quick_style = True
    return style


def _page_setup(doc, margin_in=0.7):
    section = doc.sections[0]
    section.page_width = Inches(8.27)   # A4
    section.page_height = Inches(11.69)
    for side in ("left_margin", "right_margin"):
        setattr(section, side, Inches(margin_in))
    section.top_margin = Inches(0.6)
    section.bottom_margin = Inches(0.6)
    section.header_distance = Inches(0.3)
    section.footer_distance = Inches(0.3)
    section.different_first_page_header_footer = False


def _clear_body(doc):
    body = doc.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def build_cv_template(path: Path) -> None:
    doc = Document()
    _page_setup(doc)

    normal = doc.styles["Normal"]
    _set_font(normal, 10.5)
    _spacing(normal, after=2, line=1.05)

    name = _get_or_add_style(doc, "CV Name")
    _set_font(name, 18, bold=True)
    _spacing(name, after=2)
    name.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT

    contact = _get_or_add_style(doc, "CV Contact")
    _set_font(contact, 10)
    _spacing(contact, after=6)

    heading = doc.styles["Heading 1"]
    _set_font(heading, 11.5, bold=True)
    _spacing(heading, before=8, after=3)
    heading.paragraph_format.keep_with_next = True

    role = _get_or_add_style(doc, "CV Role")
    _set_font(role, 10.5, bold=True)
    _spacing(role, before=4, after=1)
    role.paragraph_format.keep_with_next = True

    meta = _get_or_add_style(doc, "CV Role Meta")
    _set_font(meta, 10, italic=True)
    _spacing(meta, after=2)
    meta.paragraph_format.keep_with_next = True

    bullet = _get_or_add_style(doc, "CV Bullet")
    _set_font(bullet, 10.5)
    _spacing(bullet, after=1)
    # hanging indent so wrapped lines align after the hyphen
    bullet.paragraph_format.left_indent = Inches(0.18)
    bullet.paragraph_format.first_line_indent = Inches(-0.18)

    _clear_body(doc)
    doc.core_properties.title = "CV"
    doc.core_properties.author = ""
    doc.core_properties.comments = ""
    doc.save(path)


def build_cover_letter_template(path: Path) -> None:
    doc = Document()
    _page_setup(doc, margin_in=1.0)

    normal = doc.styles["Normal"]
    _set_font(normal, 11)
    _spacing(normal, after=8, line=1.15)

    name = _get_or_add_style(doc, "CL Name")
    _set_font(name, 14, bold=True)
    _spacing(name, after=2)

    contact = _get_or_add_style(doc, "CL Contact")
    _set_font(contact, 10)
    _spacing(contact, after=14)

    _clear_body(doc)
    doc.core_properties.title = "Cover Letter"
    doc.core_properties.author = ""
    doc.core_properties.comments = ""
    doc.save(path)


def main() -> None:
    TEMPLATES.mkdir(exist_ok=True)
    build_cv_template(TEMPLATES / "cv_template.docx")
    build_cover_letter_template(TEMPLATES / "cover_letter_template.docx")
    print("Templates written to", TEMPLATES)


if __name__ == "__main__":
    main()
