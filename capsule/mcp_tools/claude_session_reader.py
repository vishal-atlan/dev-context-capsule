"""Read recent Claude Code session context for a repo.

Claude Code (VS Code extension, terminal CLI, and Desktop app) all share the
same session storage at ~/.claude/projects/{encoded-path}/*.jsonl. This reader
extracts the last few user prompts and the session title from recent files —
giving the capture agent visibility into what the developer was discussing with
Claude when this capture was triggered.

The encoded path is the absolute repo path with '/' replaced by '-':
  /Users/vishal/Documents/GitHub/heracles  →  -Users-vishal-Documents-GitHub-heracles
"""

import json
import re
import time
from pathlib import Path

_CLAUDE_BASE = Path.home() / ".claude" / "projects"
_MAX_PROMPT_LEN = 200   # chars per prompt kept
_SKIP_PREFIXES = ("[Request interrupted", "<")  # noisy entries


def _dir_name(abs_path: str) -> str:
    """Encode an absolute path to Claude Code's project directory name.

    Claude Code replaces every non-alphanumeric character (/, ., spaces, etc.)
    with a dash, then collapses consecutive dashes.

    /Users/vishal.kumar/Documents/GitHub/heracles
      → -Users-vishal-kumar-Documents-GitHub-heracles
    """
    encoded = re.sub(r'[^A-Za-z0-9]', '-', abs_path.rstrip("/"))
    return re.sub(r'-+', '-', encoded)


def _read_session(jsonl_path: Path, max_prompts: int = 5) -> dict | None:
    """Extract title + recent user prompts from one JSONL session file."""
    title = ""
    prompts = []
    try:
        for line in jsonl_path.read_text(errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = entry.get("type", "")
            if t == "ai-title":
                title = entry.get("aiTitle", "")
            elif t == "last-prompt":
                p = entry.get("lastPrompt", "").strip()
                if p and not p.startswith(_SKIP_PREFIXES):
                    prompts.append(p[:_MAX_PROMPT_LEN])
    except Exception:
        return None

    prompts = prompts[-max_prompts:]
    if not prompts and not title:
        return None
    return {"session_id": jsonl_path.stem[:8], "title": title, "recent_prompts": prompts}


def read_claude_sessions(repo_path: str, max_age_hours: int = 48, max_sessions: int = 3) -> list[dict]:
    """Return recent Claude Code sessions for the given repo.

    Checks both the repo-specific project dir and the parent dir (sessions opened
    from the parent directory are common when switching between repos).
    Returns at most max_sessions entries, sorted newest first.
    """
    if not _CLAUDE_BASE.exists():
        return []

    abs_path = str(Path(repo_path).resolve()).rstrip("/")
    dirs_to_check = [
        _CLAUDE_BASE / _dir_name(abs_path),
        _CLAUDE_BASE / _dir_name(str(Path(abs_path).parent)),
    ]

    cutoff = time.time() - (max_age_hours * 3600)
    candidates: list[Path] = []
    for d in dirs_to_check:
        if d.exists():
            candidates.extend(f for f in d.glob("*.jsonl") if f.stat().st_mtime >= cutoff)

    candidates.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    results = []
    for f in candidates:
        ctx = _read_session(f)
        if ctx and ctx["recent_prompts"]:
            results.append(ctx)
            if len(results) >= max_sessions:
                break
    return results
