"""
Unit tests for core/compression_engine.py
"""

import pytest
from core.compression_engine import CompressionEngine
from config import OptimizationMode


def test_compression_modes_init():
    engine_pres = CompressionEngine(OptimizationMode.PRESERVATION)
    engine_bal = CompressionEngine(OptimizationMode.BALANCED)
    engine_max = CompressionEngine(OptimizationMode.MAX_COMPRESSION)
    assert engine_pres.mode == OptimizationMode.PRESERVATION
    assert engine_bal.mode == OptimizationMode.BALANCED
    assert engine_max.mode == OptimizationMode.MAX_COMPRESSION


def test_empty_text_compression():
    engine = CompressionEngine()
    res = engine.optimize("")
    assert res["selected_text"] == ""
    assert res["original_tokens"] == 0


def test_narrative_text_compression():
    engine = CompressionEngine(OptimizationMode.BALANCED)
    verbose_text = """
    Introduction to Systems.
    
    
    This is basically an actually very important application for environment management.
    Furthermore, obviously information is critical for development.
    
    
    - Item 1: First item
    - Item 2: Second item
    """
    res = engine.optimize(verbose_text, content_type="narrative")
    assert "selected_text" in res
    assert res["optimized_tokens"] <= res["original_tokens"]
    assert res["tokens_saved"] >= 0


def test_tabular_text_compression():
    engine = CompressionEngine(OptimizationMode.BALANCED)
    tabular_text = """
    Name\tAge\tRole
    Alice\t30\tEngineer
    Bob\t25\tDesigner
    Charlie\t35\tManager
    """
    res = engine.optimize(tabular_text, content_type="tabular")
    assert res["selected_format"] is not None
    assert len(res["selected_text"]) > 0


def test_max_compression_reduces_tokens():
    engine_max = CompressionEngine(OptimizationMode.MAX_COMPRESSION)
    text = (
        "This application is essentially very important. The configuration information "
        "for the environment management system provides maximum specifications."
    )
    res = engine_max.optimize(text)
    assert res["optimized_tokens"] <= res["original_tokens"]

