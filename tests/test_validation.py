"""
Unit tests for core/validation_engine.py
"""

import pytest
from core.validation_engine import ValidationEngine


def test_validation_init():
    val = ValidationEngine()
    assert val is not None


def test_validation_exact_match():
    val = ValidationEngine()
    text = "The quarterly revenue was $1,500,000 across 35 stores with 99.4% uptime."
    res = val.validate(text, text, mode="preservation")
    assert res["status"] == "pass"
    assert res["preservation_score"] >= 0.95
    assert res["tokens_saved"] == 0


def test_validation_preserves_numbers():
    val = ValidationEngine()
    orig = "System CPU 45%, RAM 16GB, 128 nodes active at port 8080."
    opt = "# System Status\n- CPU: 45%\n- RAM: 16GB\n- Nodes: 128\n- Port: 8080"
    res = val.validate(orig, opt, mode="balanced")
    assert res["status"] in ("pass", "warning")
    assert res["preservation_score"] >= 0.80


def test_validation_flags_empty_output():
    val = ValidationEngine()
    orig = "Important critical document content with lots of text."
    opt = ""
    res = val.validate(orig, opt, mode="balanced")
    assert res["status"] == "fail"
    assert res["preservation_score"] < 0.5


def test_validation_checks_entities():
    val = ValidationEngine()
    orig = "Contact us at support@example.com or visit https://tokenforge.local"
    opt = "Contact support@example.com or https://tokenforge.local"
    res = val.validate(orig, opt, mode="balanced")
    assert res["status"] == "pass"

