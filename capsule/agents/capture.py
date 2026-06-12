"""Capture agent — reads current dev context and distills it into a capsule.

Two modes (auto-detected from env vars — see capsule/agents/_llm.py):
  LLM mode       — CAPSULE_LLM_PROVIDER set, or ANTHROPIC_API_KEY present.
  Passthrough    — no credentials → template summary saved; full snapshot returned
                   for the MCP client (e.g. Claude Code) to interpret in-conversation.
"""

import json
from pathlib import Path

from capsule.mcp_tools.git_reader import read_git_state
from capsule.mcp_tools.ticket_reader import read_ticket_from_branch
from capsule.mcp_tools.vscode_reader import read_open_files
from capsule.mcp_tools.claude_session_reader import read_claude_sessions
from capsule.guardrails.sanitizer import sanitize
from capsule.memory.store import save_capsule, get_branch_history
from capsule.agents._llm import make_client, llm_call

_SYSTEM = """You are a dev context capture agent. Given a snapshot of the developer's current state,
produce a concise briefing capsule — 3-5 sentences — that captures:
1. What they were working on / trying to fix (use the ticket title and status if present)
2. What they had found or narrowed down so far
3. The concrete next step they were about to take

Rules:
- Be specific: name files, functions, line numbers, error messages, and hypotheses when the diff or changed files reveal them.
- If a ticket is present, lead with it: "Working on [TICKET-ID]: [title] ([status])."
- If ticket comments are present, use them — comments are the team's live conversation about the issue; they often contain the most specific diagnostic clues.
- If previous_sessions are present, treat them as memory of prior work on this branch. Acknowledge what progressed since the last session. Do NOT re-summarize what was already captured — only extend it with what changed.
- If diff content is present, reference specific code changes by function or variable name when they clarify what was being done.
- If claude_sessions are present, they show what the developer was asking their AI assistant about during this work. The recent_prompts reveal the intent and questions being explored — use them to understand context even when git changes look minimal.
- Write it as if briefing the developer when they return tomorrow.
- Do NOT use bullet points — write flowing sentences.
- Output ONLY the briefing text, nothing else."""


def _template_summary(git, note: str, ticket=None) -> str:
    """Rule-based summary used in passthrough mode."""
    changed = git.staged_files + git.unstaged_files + git.untracked_files
    files_str = ", ".join(changed[:5]) + (" …" if len(changed) > 5 else "") if changed else "no changed files"
    latest = git.recent_commits[0]["message"] if git.recent_commits else "no commits yet"
    note_str = f" Note: {note}." if note else ""
    ticket_str = f" Ticket: {ticket.identifier} — {ticket.title} ({ticket.status})." if ticket else ""
    return (
        f"On branch `{git.branch}` in {git.repo_name}.{ticket_str}{note_str} "
        f"Changed files: {files_str}. "
        f"Latest commit: \"{latest}\"."
    )


async def capture_context(repo_path: str = ".", note: str = "") -> str:
    try:
        git = read_git_state(repo_path)
    except Exception as e:
        return f"Could not read git state: {e}"

    abs_repo_path = str(Path(repo_path).resolve())
    ticket = await read_ticket_from_branch(git.branch)

    # ── Enrichments ──────────────────────────────────────────────────────────
    # Previous sessions on this branch — give the LLM memory of prior work
    previous_sessions = get_branch_history(abs_repo_path, git.branch, limit=3)

    # Recent Claude Code sessions — what was the developer discussing with Claude?
    # Covers VS Code extension, terminal CLI, and Desktop app (all share ~/.claude/projects/)
    claude_sessions = read_claude_sessions(repo_path, max_age_hours=48)

    snapshot = {
        "branch": git.branch,
        "recent_commits": git.recent_commits,
        "staged_files": git.staged_files,
        "unstaged_files": git.unstaged_files,
        "untracked_files": git.untracked_files,
        "stash_count": git.stash_count,
        "diff_summary": git.diff_summary,        # actual code changes, capped at 2000 chars
        "open_files": read_open_files(repo_path),
        "note": note,
        "ticket": ticket.to_dict() if ticket else None,     # includes comments field
        "previous_sessions": previous_sessions,  # last 3 summaries for this branch
        "claude_sessions": claude_sessions,       # recent Claude Code AI conversations
    }

    client, model, provider = make_client()

    if client:
        # ── LLM mode ────────────────────────────────────────────────────────────
        snapshot_text = sanitize(json.dumps(snapshot, indent=2))
        summary = sanitize(llm_call(
            client, model, provider, _SYSTEM,
            f"Capture the dev context from this snapshot:\n\n{snapshot_text}",
            max_tokens=800,
        ))
        capsule_id = save_capsule(
            repo_path=abs_repo_path, branch=git.branch,
            repo_name=git.repo_name, summary=summary, raw=snapshot,
        )
        return f"Capsule [{capsule_id}] saved for branch `{git.branch}`.\n\n{summary}"

    else:
        # ── Passthrough mode ────────────────────────────────────────────────────
        summary = sanitize(_template_summary(git, note, ticket))
        capsule_id = save_capsule(
            repo_path=abs_repo_path, branch=git.branch,
            repo_name=git.repo_name, summary=summary, raw=snapshot,
        )

        changed = git.staged_files + git.unstaged_files + git.untracked_files
        commits_md = "\n".join(
            f"  - `{c['sha']}` {c['message']} ({c['author']}, {c['timestamp'][:10]})"
            for c in git.recent_commits
        )
        files_md = "\n".join(f"  - {f}" for f in changed) if changed else "  (none)"
        note_md = f"\n**Note:** {note}" if note else ""
        ticket_md = f"\n\n**Ticket:**\n  {ticket.to_markdown()}" if ticket else ""

        return (
            f"## Dev Context Snapshot — `{git.branch}` [{capsule_id}]\n"
            f"**Repo:** {git.repo_name}{note_md}{ticket_md}\n\n"
            f"**Recent commits:**\n{commits_md}\n\n"
            f"**Changed files:**\n{files_md}\n\n"
            f"**Stashes:** {git.stash_count}\n\n"
            f"---\n"
            f"_Capsule [{capsule_id}] saved. Summarize the above to brief yourself on what you were working on._"
        )
