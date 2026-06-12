"""Tests for secret sanitizer."""

from capsule.guardrails.sanitizer import sanitize


def test_strips_jwt():
    text = "token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.abc123def456ghi789"
    assert "[REDACTED]" in sanitize(text)


def test_strips_bearer():
    text = "Authorization: Bearer abc123tokenvalue"
    assert "[REDACTED]" in sanitize(text)


def test_strips_api_key():
    text = "api_key=supersecretvalue123"
    assert "[REDACTED]" in sanitize(text)


def test_leaves_normal_text_intact():
    text = "Fixing the N+1 query in orders API. Narrowed to eager-load on line 84."
    result = sanitize(text)
    assert "N+1" in result
    assert "orders API" in result
