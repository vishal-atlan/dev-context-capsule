"""Strip secrets and tokens before storing a capsule."""

import re

# Patterns that indicate secrets — conservative, prefer false positives over leaks
_SECRET_PATTERNS = [
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|auth[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"),  # JWT
    re.compile(r"(?i)(aws_access_key_id|aws_secret_access_key)\s*[:=]\s*\S+"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),           # OpenAI / Anthropic keys
    re.compile(r"ghp_[A-Za-z0-9]{36}"),           # GitHub PAT
    re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),      # GitLab PAT
    re.compile(r"xox[baprs]-[0-9A-Za-z\-]+"),     # Slack tokens
    re.compile(r"(?<!\w)[0-9a-f]{32,64}(?!\w)"),  # Generic hex secrets (loose)
]

_REPLACEMENT = "[REDACTED]"


def sanitize(text: str) -> str:
    """Replace secret-looking strings with [REDACTED]."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REPLACEMENT, text)
    return text


def is_stale(captured_at_iso: str, max_days: int = 14) -> bool:
    """Return True if a capsule is older than max_days."""
    from datetime import datetime, timezone

    captured = datetime.fromisoformat(captured_at_iso)
    now = datetime.now(timezone.utc)
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    return (now - captured).days > max_days
