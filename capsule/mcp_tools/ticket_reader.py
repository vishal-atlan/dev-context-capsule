"""Ticket reader router — shared types and provider dispatch.

Set TICKET_PROVIDER=linear (default) or jira.

Linear config:  LINEAR_API_KEY
Jira config:    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
"""

import os
import re
from dataclasses import dataclass, field

_TICKET_RE = re.compile(r'([A-Za-z]{2,10}-\d+)')
_NON_FEATURE_BRANCHES = frozenset(
    {"main", "master", "develop", "staging", "beta", "release", "HEAD"}
)


@dataclass
class TicketInfo:
    identifier: str
    title: str
    status: str
    assignee: str
    priority: str
    labels: list[str] = field(default_factory=list)
    description: str = ""
    url: str = ""
    comments: list[str] = field(default_factory=list)   # recent comments, newest first

    def to_dict(self) -> dict:
        return {
            "identifier": self.identifier,
            "title": self.title,
            "status": self.status,
            "assignee": self.assignee,
            "priority": self.priority,
            "labels": self.labels,
            "description": self.description,
            "url": self.url,
            "comments": self.comments,
        }

    def to_markdown(self) -> str:
        labels_str = ", ".join(self.labels) if self.labels else "none"
        desc = f"\n  > {self.description}" if self.description else ""
        url_part = f"[{self.identifier}]({self.url})" if self.url else self.identifier
        comments_md = ""
        if self.comments:
            formatted = "\n".join(f"  - {c}" for c in self.comments)
            comments_md = f"\n  **Recent comments:**\n{formatted}"
        return (
            f"**{url_part}** — {self.title}\n"
            f"  Status: {self.status} | Assignee: {self.assignee} | "
            f"Priority: {self.priority} | Labels: {labels_str}{desc}{comments_md}"
        )


def parse_ticket_id(branch: str) -> str | None:
    """Extract a ticket identifier from a branch name.

    Works for both Linear (GOVFOUN-532) and Jira (PROJ-123) — same format.
    Returns None for non-feature branches (main, develop, etc.).

    Examples:
      vishalk/govfoun-532-beta  → GOVFOUN-532
      fix/PROJ-278-auth         → PROJ-278
      feat/delete-user-ttl      → None
      main                      → None
    """
    if branch in _NON_FEATURE_BRANCHES:
        return None
    match = _TICKET_RE.search(branch)
    return match.group(1).upper() if match else None


def _provider() -> str:
    return os.environ.get("TICKET_PROVIDER", "linear").lower()


async def fetch_ticket_by_id(identifier: str) -> TicketInfo | None:
    """Fetch a ticket by its identifier (e.g. GOVFOUN-532, PROJ-123)."""
    if _provider() == "jira":
        from capsule.mcp_tools.jira_reader import fetch_ticket_by_id as _fetch
    else:
        from capsule.mcp_tools.linear_reader import fetch_ticket_by_id as _fetch
    return await _fetch(identifier)


async def fetch_active_tickets() -> list[TicketInfo]:
    """Fetch active tickets assigned to the current user."""
    if _provider() == "jira":
        from capsule.mcp_tools.jira_reader import fetch_active_tickets as _fetch
    else:
        from capsule.mcp_tools.linear_reader import fetch_active_tickets as _fetch
    return await _fetch()


async def read_ticket_from_branch(branch: str) -> TicketInfo | None:
    """Parse a branch name for a ticket ID and fetch it from the configured provider."""
    if _provider() == "jira":
        from capsule.mcp_tools.jira_reader import read_ticket_from_branch as _fetch
    else:
        from capsule.mcp_tools.linear_reader import read_ticket_from_branch as _fetch
    return await _fetch(branch)
