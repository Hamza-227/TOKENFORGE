"""End-to-end regression tests for the bugs fixed in v1.1."""
import shutil
from pathlib import Path

import pytest

from core.dispatcher import process_document
from core.ocr_engine import OCREngine
from core.validation_engine import ValidationEngine
from utils.file_utils import collect_files_from_folder


def test_ocr_engine_has_processor_api():
    ocr = OCREngine()
    assert hasattr(ocr, "extract_text") and hasattr(ocr, "ocr_image_bytes")


def test_duplicate_stems_do_not_overwrite(tmp_path):
    (tmp_path / "a").mkdir()
    for ext in (".txt", ".csv"):
        (tmp_path / "a" / f"report{ext}").write_text("a,b\n1,2\n3,4\n")
    out = tmp_path / "out"
    reg: dict = {}
    r1 = process_document(tmp_path / "a" / "report.txt", out, out / "assets", "balanced", reg)
    r2 = process_document(tmp_path / "a" / "report.csv", out, out / "assets", "balanced", reg)
    assert r1["output_file"] != r2["output_file"]
    assert Path(r1["output_file"]).exists() and Path(r2["output_file"]).exists()


def test_never_larger_than_source_for_text(tmp_path):
    f = tmp_path / "n.txt"
    f.write_text("Summary:\nRevenue was 1,500 in 2026.\n\nDetails:\nCosts were 900.\n" * 3)
    r = process_document(f, tmp_path / "o", None, "balanced")
    assert r["optimized_tokens"] <= r["original_tokens"]


def test_csv_numbers_never_rounded(tmp_path):
    f = tmp_path / "d.csv"
    f.write_text("x,y\n1234567.891,2\n0.000123,3\n")
    r = process_document(f, tmp_path / "o", None, "max_compression")
    assert "1234567.891" in r["optimized_text"] and "0.000123" in r["optimized_text"]


def test_hidden_parent_folder_still_scanned(tmp_path):
    hidden = tmp_path / ".docs"
    hidden.mkdir()
    (hidden / "a.txt").write_text("hello")
    assert len(collect_files_from_folder(hidden)) == 1


def test_validation_empty_output_scores_zero():
    res = ValidationEngine().validate("Some real content here.", "", "balanced")
    assert res["status"] == "fail" and res["preservation_score"] == 0


def test_number_formats_are_equivalent():
    v = ValidationEngine()
    res = v.validate("Total $1,500,000 grew 12.0%", "Total 1500000 grew 12%", "balanced")
    assert res["details"]["numbers_missing"] == 0


def test_docx_keeps_table_in_place(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("BEFORE")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "h1"; t.cell(0, 1).text = "h2"; t.cell(1, 0).text = "v1"; t.cell(1, 1).text = "v2"
    d.add_paragraph("AFTER")
    f = tmp_path / "t.docx"; d.save(f)
    text = process_document(f, tmp_path / "o", None, "balanced")["optimized_text"]
    assert text.index("BEFORE") < text.index("h1") < text.index("AFTER")
