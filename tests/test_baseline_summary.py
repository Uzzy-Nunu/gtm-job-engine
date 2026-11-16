"""Tests for scripts/baseline_summary.py using made-up data."""

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("baseline_summary", ROOT / "scripts" / "baseline_summary.py")
bs = importlib.util.module_from_spec(spec)
sys.modules["baseline_summary"] = bs
spec.loader.exec_module(bs)

SAMPLE = ROOT / "tests" / "fixtures" / "sample_baseline.csv"
TEMPLATE = ROOT / "templates" / "baseline_timing_template.csv"
HEADER = TEMPLATE.read_text(encoding="utf-8").strip()


def test_template_has_every_step_column():
    columns = HEADER.split(",")
    for col in bs.STEPS:
        assert col in columns
    assert "company" in columns


def test_sample_summary_numbers():
    s = bs.summarise(bs.load_rows(SAMPLE))
    assert s["count"] == 5
    # row totals: 104, 88, 101, 116, 78 -> mean 97.4, median 101
    assert s["avg_total"] == pytest.approx(97.4)
    assert s["median_total"] == 101
    assert (s["min_total"], s["max_total"]) == (78, 116)
    assert sum(step["share"] for step in s["steps"].values()) == pytest.approx(100)
    assert s["steps"]["cv_min"]["avg"] == pytest.approx(28)


def test_markdown_has_no_company_or_role_names():
    md = bs.to_markdown(bs.summarise(bs.load_rows(SAMPLE)), today=date(2026, 11, 18))
    for private in ("Example Corp", "Sample Labs", "Placeholder Inc", "GTM Engineer", "Fictional AI"):
        assert private not in md
    assert "**97**" in md
    assert "Tailor the CV" in md


def _sheet(tmp_path, *rows):
    path = tmp_path / "sheet.csv"
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return path


def test_blank_template_is_reported_clearly(tmp_path):
    with pytest.raises(bs.SheetError, match="no filled-in"):
        bs.load_rows(_sheet(tmp_path))


def test_non_number_is_reported_with_row(tmp_path):
    path = _sheet(tmp_path, "2026-11-16,Role,Co,LinkedIn Post,ten,1,1,1,1,1,1,1,4,")
    with pytest.raises(bs.SheetError, match="Row 2: 'find_min'"):
        bs.load_rows(path)


@pytest.mark.parametrize("text,minutes", [
    ("12", 12), ("12.5", 12.5), ("3:30", 3.5), ("13:43.35", 13 + 43.35 / 60), ("1:05:30", 65.5),
])
def test_parse_minutes_accepts_stopwatch_formats(text, minutes):
    assert bs.parse_minutes(text) == pytest.approx(minutes)


def test_hours_slip_is_caught(tmp_path):
    path = _sheet(tmp_path, "2026-11-16,Role,Co,LinkedIn Post,5,5,5,5,30:00:00,5,5,5,4,")
    with pytest.raises(bs.SheetError, match="30.0 hours"):
        bs.load_rows(path)


def test_empty_cell_must_be_zero(tmp_path):
    path = _sheet(tmp_path, "2026-11-16,Role,Co,LinkedIn Post,5,,1,1,1,1,1,1,4,")
    with pytest.raises(bs.SheetError, match="use 0"):
        bs.load_rows(path)


def test_single_application_is_allowed_and_labelled(tmp_path, monkeypatch):
    out = tmp_path / "baseline.md"
    monkeypatch.setattr(bs, "OUTPUT", out)
    path = _sheet(tmp_path, "2026-11-16,Zebra Role,Quokka Corp,LinkedIn Post,5,5,5,5,5,5,5,5,4,")
    assert bs.main([str(path), "--write"]) == 0
    md = out.read_text(encoding="utf-8")
    assert "1 real application." in md
    assert "Small sample" in md
    assert "Total for the application | **40**" in md
    assert "Median" not in md
    assert "Quokka" not in md and "Zebra" not in md  # no company or role names


def test_write_with_five_rows(tmp_path, monkeypatch):
    out = tmp_path / "baseline.md"
    monkeypatch.setattr(bs, "OUTPUT", out)
    monkeypatch.setattr(bs, "ROOT", tmp_path)
    assert bs.main([str(SAMPLE), "--write"]) == 0
    md = out.read_text(encoding="utf-8")
    assert "Manual baseline" in md and "Small sample" not in md
