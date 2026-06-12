"""Ticket context aggregator — answers questions like:
  "Where was I on GOVFOUN-532?"
  "What's left on GOVFOUN-532?"
  "What's the PR status of GOVFOUN-532?"
  "What are all my active tickets with PR status?"

Combines: Linear ticket details + saved capsules + GitHub PRs.
Works in passthrough mode (no API key) — returns structured markdown
for Claude Code to interpret. With LINEAR_API_KEY: includes ticket details.
"""

import re

from capsule.mcp_tools.ticket_reader import fetch_ticket_by_id, fetch_active_tickets
from capsule.mcp_tools.github_reader import get_prs_for_ticket
from capsule.memory.store import get_all_capsules
from capsule.guardrails.sanitizer import is_stale

_TICKET_RE = re.compile(r'([A-Za-z]{2,10}-\d+)', re.IGNORECASE)


def _extract_ticket_id(query: str) -> str | None:
    """Extract ticket ID from a natural language query or bare identifier."""
    match = _TICKET_RE.search(query)
    return match.group(1).upper() if match else None


def _capsules_for_ticket(ticket_id: str) -> list[dict]:
    """Find all saved capsules whose branch contains this ticket ID."""
    all_capsules = get_all_capsules()
    ticket_lower = ticket_id.lower()
    return [
        c for c in all_capsules
        if ticket_lower in c["branch"].lower()
    ]


async def get_ticket_context(ticket_id_or_query: str) -> str:
    """Full context for a ticket: Linear status + capsule history + PR status."""
    ticket_id = _extract_ticket_id(ticket_id_or_query)
    if not ticket_id:
        return f"Could not find a ticket ID in: `{ticket_id_or_query}`"

    # Fetch all three data sources concurrently-ish (sequential is fine — all fast)
    ticket = await fetch_ticket_by_id(ticket_id)
    capsules = _capsules_for_ticket(ticket_id)
    prs = get_prs_for_ticket(ticket_id)

    sections = [f"# Context — {ticket_id}\n"]

    # ── Linear ticket ──────────────────────────────────────────────────────────
    if ticket:
        sections.append(
            f"## Ticket\n"
            f"{ticket.to_markdown()}\n"
        )
    else:
        sections.append(
            "## Ticket\n"
            "_Ticket provider not configured or ticket not found. "
            "Set `TICKET_PROVIDER` (linear/jira) and the matching API credentials — "
            "see README configuration section._\n"
        )

    # ── GitHub PRs ─────────────────────────────────────────────────────────────
    if prs:
        open_prs = [p for p in prs if p.state == "OPEN"]
        merged_prs = [p for p in prs if p.state == "MERGED"]
        closed_prs = [p for p in prs if p.state == "CLOSED"]

        pr_lines = []
        for pr in open_prs + merged_prs + closed_prs:
            pr_lines.append(f"- {pr.to_markdown()}")

        sections.append(
            f"## Pull Requests ({len(prs)} total — "
            f"{len(open_prs)} open, {len(merged_prs)} merged, {len(closed_prs)} closed)\n"
            + "\n".join(pr_lines) + "\n"
        )
    else:
        sections.append(
            f"## Pull Requests\n"
            f"_No PRs found across searched repos. "
            f"Either not raised yet or branch name differs from `{ticket_id.lower()}`._\n"
        )

    # ── Saved capsules ─────────────────────────────────────────────────────────
    if capsules:
        caps_by_repo: dict[str, list[dict]] = {}
        for c in sorted(capsules, key=lambda x: x["captured_at"], reverse=True):
            caps_by_repo.setdefault(c["repo_name"], []).append(c)

        cap_lines = []
        for repo, repo_caps in caps_by_repo.items():
            latest = repo_caps[0]
            stale = " [STALE]" if is_stale(latest["captured_at"]) else ""
            cap_lines.append(
                f"**{repo}** (branch: `{latest['branch']}`){stale}\n"
                f"> {latest['summary']}\n"
                f"_Captured: {latest['captured_at'][:16]}_"
            )

        sections.append(
            f"## Where You Left Off ({len(capsules)} capsule{'s' if len(capsules) > 1 else ''})\n"
            + "\n\n".join(cap_lines) + "\n"
        )
    else:
        sections.append(
            f"## Where You Left Off\n"
            f"_No capsules saved for branches matching `{ticket_id.lower()}`. "
            f"Run `capture` in a relevant repo to save your context._\n"
        )

    # ── What's left prompt ────────────────────────────────────────────────────
    sections.append(
        f"---\n"
        f"_Based on the above: summarize what's done, what's in review, "
        f"and what's the immediate next action on {ticket_id}._"
    )

    return "\n".join(sections)


async def get_active_tickets_with_prs() -> str:
    """List all active Linear tickets assigned to me, with their PR status."""
    tickets = await fetch_active_tickets()

    if not tickets:
        msg = "No active tickets found."
        import os
        provider = os.environ.get("TICKET_PROVIDER", "linear")
        if provider == "linear" and not os.environ.get("LINEAR_API_KEY"):
            msg += "\n\n_`LINEAR_API_KEY` not set — set it to fetch tickets from Linear._"
        elif provider == "jira" and not all(os.environ.get(k) for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN")):
            msg += "\n\n_Jira credentials incomplete — set `JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN`._"
        return msg

    lines = [f"# Active Tickets ({len(tickets)})\n"]

    for ticket in tickets:
        prs = get_prs_for_ticket(ticket.identifier)
        open_prs = [p for p in prs if p.state == "OPEN"]
        merged_prs = [p for p in prs if p.state == "MERGED"]

        pr_summary = "no PRs"
        if open_prs:
            pr_summary = f"{len(open_prs)} open PR{'s' if len(open_prs) > 1 else ''}"
        elif merged_prs:
            pr_summary = f"✅ {len(merged_prs)} merged — awaiting ticket close"

        capsules = _capsules_for_ticket(ticket.identifier)
        capsule_note = f" | {len(capsules)} capsule{'s' if len(capsules) > 1 else ''} saved" if capsules else ""

        lines.append(
            f"### [{ticket.identifier}]({ticket.url}) — {ticket.title}\n"
            f"Status: **{ticket.status}** | Priority: {ticket.priority} | PRs: {pr_summary}{capsule_note}\n"
        )

    return "\n".join(lines)
