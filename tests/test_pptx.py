"""
Unit tests for core/pptx_processor.py
"""

import os
import pytest
from pathlib import Path
from core.pptx_processor import PPTXProcessor

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
except ImportError:
    Presentation = None


def test_pptx_processor_init():
    proc = PPTXProcessor(optimization_mode="preservation")
    assert proc.optimization_mode == "preservation"
    assert proc.token_counter is not None


@pytest.mark.skipif(Presentation is None, reason="python-pptx not installed")
def test_pptx_processing_real_file(tmp_path):
    # Create a small valid test PPTX
    pptx_path = tmp_path / "sample_presentation.pptx"
    prs = Presentation()
    slide_layout = prs.slide_layouts[0]  # Title slide
    slide = prs.slides.add_slide(slide_layout)
    title = slide.shapes.title
    subtitle = slide.placeholders[1]
    title.text = "TOKENFORGE Test Slide"
    subtitle.text = "Subtitle describing token optimization features."

    prs.save(str(pptx_path))

    out_dir = tmp_path / "out"
    proc = PPTXProcessor(optimization_mode="balanced")
    result = proc.process(str(pptx_path), str(out_dir))

    assert "source_file" in result
    assert "output_file" in result
    assert "optimized_text" in result
    assert result["pages"] == 1
    assert "TOKENFORGE Test Slide" in result["optimized_text"]
    assert os.path.exists(result["output_file"])

