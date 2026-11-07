"""
Unit tests for core/token_counter.py
"""

import pytest
from core.token_counter import (
    TokenCounter,
    quick_token_count,
    format_token_count,
)


def test_token_counter_initialization():
    tc = TokenCounter()
    assert tc.get_encoding_name() is not None


def test_token_counter_empty_text():
    tc = TokenCounter()
    assert tc.count("") == 0
    assert tc.count(None) == 0
    assert tc.count_tokens("") == 0


def test_token_counter_sample_text():
    tc = TokenCounter()
    text = "TOKENFORGE is a local document optimization tool for LLMs."
    count = tc.count(text)
    assert count > 0
    assert isinstance(count, int)


def test_compare_representations():
    tc = TokenCounter()
    reps = {
        "short": "Short summary.",
        "long": "This is a much longer and more verbose text description with additional tokens and explanations.",
    }
    comparison = tc.compare_representations(reps)
    assert "short" in comparison
    assert "long" in comparison
    assert comparison["short"]["tokens"] < comparison["long"]["tokens"]
    assert "_sorted" in comparison


def test_estimate_cost_savings():
    tc = TokenCounter()
    savings = tc.estimate_cost_savings(1000, 600)
    assert savings["tokens_saved"] == 400
    assert savings["reduction_percentage"] == 40.0


def test_format_token_count():
    assert "500" in format_token_count(500)
    assert "K tokens" in format_token_count(15000)
    assert "M tokens" in format_token_count(2500000)

