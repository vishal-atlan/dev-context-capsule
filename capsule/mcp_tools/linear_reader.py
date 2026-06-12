"""Linear ticket reader.

Required env var (when TICKET_PROVIDER=linear, the default):
  LINEAR_API_KEY — Personal API key from linear.app/settings/api
"""

import os

import httpx

from capsule.mcp_tools.ticket_reader import TicketInfo, parse_ticket_id

LINEAR_API_URL = "https://api.linear.app/graphql"

_QUERY = """
query IssueByIdentifier($identifier: String!) {
  issue(id: $identifier) {
    identifier
    title
    state { name }
    assignee { name }
    priorityLabel
    labels { nodes { name } }
    description
    url
    comments(last: 5) {
      nodes {
        body
        user { name }
        createdAt
      }
    }
  }
}
"""

_ACTIVE_TICKETS_QUERY = """
query MyActiveIssues {
  viewer {
    assignedIssues(
      filter: {
        state: { type: { in: ["started", "unstarted"] } }
      }
      orderBy: updatedAt
      first: 20
    ) {
      nodes {
        identifier
        title
        state { name }
        priority
        priorityLabel
        labels { nodes { name } }
        url
        updatedAt
      }
    }
  }
}
"""


async def _fetch_ticket(identifier: str, api_key: str) -> TicketInfo | None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            LINEAR_API_URL,
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            json={"query": _QUERY, "variables": {"identifier": identifier}},
        )
        resp.raise_for_status()
        data = resp.json()

    issue = (data.get("data") or {}).get("issue")
    if not issue:
        return None

    raw_desc = issue.get("description") or ""
    desc = raw_desc[:600] + ("…" if len(raw_desc) > 600 else "")

    # Comments — newest first (Linear returns oldest first with `last: 5`)
    raw_comments = list(reversed((issue.get("comments") or {}).get("nodes", [])))
    comments = []
    for c in raw_comments:
        author = (c.get("user") or {}).get("name", "unknown")
        body = (c.get("body") or "").strip()
        body_short = body[:300] + ("…" if len(body) > 300 else "")
        date = (c.get("createdAt") or "")[:10]
        if body_short:
            comments.append(f"[{date}] {author}: {body_short}")

    return TicketInfo(
        identifier=issue["identifier"],
        title=issue["title"],
        status=(issue.get("state") or {}).get("name", "Unknown"),
        assignee=(issue.get("assignee") or {}).get("name", "Unassigned"),
        priority=issue.get("priorityLabel", "No priority"),
        labels=[n["name"] for n in (issue.get("labels") or {}).get("nodes", [])],
        description=desc,
        url=issue.get("url", ""),
        comments=comments,
    )


async def fetch_ticket_by_id(identifier: str) -> TicketInfo | None:
    """Fetch a Linear ticket directly by identifier (e.g. PROJ-532)."""
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        return None
    try:
        return await _fetch_ticket(identifier.upper(), api_key)
    except Exception:
        return None


async def fetch_active_tickets() -> list[TicketInfo]:
    """Fetch all Linear tickets assigned to the current user that are in-progress or todo."""
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        return []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                LINEAR_API_URL,
                headers={"Authorization": api_key, "Content-Type": "application/json"},
                json={"query": _ACTIVE_TICKETS_QUERY},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    nodes = (
        (data.get("data") or {})
        .get("viewer", {})
        .get("assignedIssues", {})
        .get("nodes", [])
    )

    return [
        TicketInfo(
            identifier=issue["identifier"],
            title=issue["title"],
            status=(issue.get("state") or {}).get("name", "Unknown"),
            assignee="me",
            priority=issue.get("priorityLabel", "No priority"),
            labels=[n["name"] for n in (issue.get("labels") or {}).get("nodes", [])],
            url=issue.get("url", ""),
        )
        for issue in nodes
    ]


async def read_ticket_from_branch(branch: str) -> TicketInfo | None:
    """Parse branch → ticket ID → fetch from Linear. Returns None on any failure."""
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        return None
    identifier = parse_ticket_id(branch)
    if not identifier:
        return None
    try:
        return await _fetch_ticket(identifier, api_key)
    except Exception:
        return None
