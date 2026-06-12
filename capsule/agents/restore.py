"""Restore agent — reconstructs mental state from the most recent capsule.

Two modes (auto-detected from env vars — see capsule/agents/_llm.py):
  LLM mode       — CAPSULE_LLM_PROVIDER set, or ANTHROPIC_API_KEY present.
  Passthrough    — no credentials → saved capsule + current diff returned as structured
                   markdown for the MCP client (e.g. Claude Code) to interpret.
"""

import json
from pathlib import Path

from capsule.mcp_tools.git_reader import read_git_state
from capsule.guardrails.sanitizer import is_stale
from capsule.memory.store import get_latest_capsule
from capsule.rag.retriever import search_capsules
from capsule.agents._llm import make_client, llm_call

_SYSTEM = """You are a dev context restore agent. The developer is returning to a task after being away.
Given their saved capsule and current git state, produce a warm-up briefing that:
1. Reminds them exactly where they left off (be specific: files, functions, error messages)
2. Notes any changes since the capsule was saved (new commits, changed files)
3. Gives them one clear first action to resume immediately

Keep it tight — max 5 sentences. Write as if you're a colleague saying "Welcome back, here's where we are."
Do NOT use bullet points. Output ONLY the briefing."""


async def restore_context(repo_path: str = ".", branch: str = "") -> str:
    try:
        git = read_git_state(repo_path)
    except Exception as e:
        return f"Could not read git state: {e}"

    target_branch = branch or git.branch
    abs_repo_path = str(Path(repo_path).resolve())

    capsule = get_latest_capsule(repo_path=abs_repo_path, branch=target_branch)
    if not capsule:
        similar = search_capsules(query=target_branch, repo_path=abs_repo_path, top_k=1)
        return (
            f"No capsule found for branch `{target_branch}`.\n\n"
            f"Most similar saved context:\n{similar}"
        )

    stale_warning = ""
    if is_stale(capsule["captured_at"]):
        stale_warning = "\n\n> WARNING: This capsule is older than 2 weeks — context may be stale."

    current = {
        "branch": git.branch,
        "recent_commits": git.recent_commits,
        "staged_files": git.staged_files,
        "unstaged_files": git.unstaged_files,
    }

    client, model, provider = make_client()

    if client:
        # ── LLM mode ────────────────────────────────────────────────────────────
        prompt = (
            f"Saved capsule (captured {capsule['captured_at'][:16]}):\n{capsule['summary']}\n\n"
            f"Raw snapshot at capture:\n{capsule['raw_json']}\n\n"
            f"Current git state:\n{json.dumps(current, indent=2)}"
        )
        briefing = llm_call(client, model, provider, _SYSTEM, prompt)
        return f"CONTEXT RESTORED — branch `{target_branch}`{stale_warning}\n\n{briefing}"

    else:
        # ── Passthrough mode ────────────────────────────────────────────────────
        raw = json.loads(capsule["raw_json"])

        saved_shas = {c["sha"] for c in raw.get("recent_commits", [])}
        new_commits = [c for c in current["recent_commits"] if c["sha"] not in saved_shas]
        new_commits_md = (
            "\n".join(f"  - `{c['sha']}` {c['message']}" for c in new_commits)
            if new_commits else "  (none)"
        )

        current_changed = current["staged_files"] + current["unstaged_files"]
        current_files_md = "\n".join(f"  - {f}" for f in current_changed) if current_changed else "  (none)"

        return (
            f"## Context Restore — `{target_branch}`{stale_warning}\n\n"
            f"**Captured:** {capsule['captured_at'][:16]}\n\n"
            f"### What you saved\n{capsule['summary']}\n\n"
            f"### New commits since capture\n{new_commits_md}\n\n"
            f"### Currently changed files\n{current_files_md}\n\n"
            f"---\n"
            f"_Based on the above, brief yourself: where did you leave off, "
            f"what changed, and what's the first thing to do now?_"
        )
