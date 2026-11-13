"""Render the made-up sample CV so you can open it and do the paste test.

Run:  python scripts/render_sample_cv.py
Writes output/sample_cv.docx and output/sample_cv.txt (output/ is git-ignored).
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.render_docx import docx_to_text, render_cv  # noqa: E402

cv = yaml.safe_load((ROOT / "tests/fixtures/sample_tailored_cv.yaml").read_text(encoding="utf-8"))
docx_path = render_cv(cv, ROOT / "output" / "sample_cv.docx")
txt_path = docx_path.with_suffix(".txt")
txt_path.write_text(docx_to_text(docx_path), encoding="utf-8")
print("Wrote", docx_path)
print("Wrote", txt_path)
