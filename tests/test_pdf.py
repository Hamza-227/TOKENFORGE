"""
Unit tests for core/pdf_processor.py
"""

import os
import pytest
from pathlib import Path
from core.pdf_processor import PDFProcessor

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None


def test_pdf_processor_init():
    proc = PDFProcessor(optimization_mode="balanced")
    assert proc.optimization_mode == "balanced"
    assert proc.token_counter is not None


@pytest.mark.skipif(fitz is None, reason="PyMuPDF not installed")
def test_pdf_processing_real_file(tmp_path):
    # Create a small valid test PDF
    pdf_path = tmp_path / "sample_test.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(
        fitz.Point(50, 72),
        "TOKENFORGE PDF Test Document\n\nThis is a sample paragraph with data: 42 units.",
        fontsize=12,
    )
    doc.save(str(pdf_path))
    doc.close()

    out_dir = tmp_path / "out"
    proc = PDFProcessor(optimization_mode="balanced")
    result = proc.process(str(pdf_path), str(out_dir))

    assert "source_file" in result
    assert "output_file" in result
    assert "optimized_text" in result
    assert result["pages"] == 1
    assert result["original_tokens"] > 0
    assert result["optimized_tokens"] > 0
    assert os.path.exists(result["output_file"])

