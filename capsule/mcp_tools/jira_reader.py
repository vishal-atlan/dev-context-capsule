"""Jira ticket reader.

Required env vars (when TICKET_PROVIDER=jira):
  JIRA_BASE_URL    — e.g. https://yourcompany.atlassian.net
  JIRA_EMAIL       — your Atlassian account email
  JIRA_API_TOKEN   — from id.atlassian.com/manage-profile/security/api-tokens
"""

import base64
import os
from typing import Any

import httpx

from capsule.mcp_tools.ticket_reader import TicketInfo, parse_ticket_id


def _auth_headers() -> dict[str, str] | None:
    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    if not email or not token:
        return None
    creds = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}


def _base_url() -> str | None:
    url = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    return url or None


def _parse_issue(issue: dict[str, Any], base_url: str) -> TicketInfo:
    fields = issue.get("fields", {})
    raw_desc = fields.get("description") or ""
    # Jira API v2 returns plain text; v3 returns ADF objects — handle both
    desc_text = raw_desc if isinstance(raw_desc, str) else ""
    desc = desc_text[:500] + ("…" if len(desc_text) > 500 else "")

    return TicketInfo(
        identifier=issue["key"],
        title=fields.get("summary", ""),
        status=(fields.get("status") or {}).get("name", "Unknown"),
        assignee=(fields.get("assignee") or {}).get("displayName", "Unassigned"),
        priority=(fields.get("priority") or {}).get("name", "No priority"),
        labels=fields.get("labels", []),
        description=desc,
        url=f"{base_url}/browse/{issue['key']}",
    )


async def fetch_ticket_by_id(identifier: str) -> TicketInfo | None:
    headers = _auth_headers()
    base_url = _base_url()
    if not headers or not base_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{base_url}/rest/api/2/issue/{identifier.upper()}",
                headers=headers,
                params={"fields": "summary,status,assignee,priority,labels,description"},
            )
            resp.raise_for_status()
            return _parse_issue(resp.json(), base_url)
    except Exception:
        return None


async def fetch_active_tickets() -> list[TicketInfo]:
    headers = _auth_headers()
    base_url = _base_url()
    if not headers or not base_url:
        return []
    try:
        jql = 'assignee = currentUser() AND status in ("In Progress", "To Do") ORDER BY updated DESC'
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{base_url}/rest/api/2/search",
                headers=headers,
                params={
                    "jql": jql,
                    "maxResults": 20,
                    "fields": "summary,status,assignee,priority,labels,description",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return [_parse_issue(issue, base_url) for issue in data.get("issues", [])]
    except Exception:
        return []


async def read_ticket_from_branch(branch: str) -> TicketInfo | None:
    identifier = parse_ticket_id(branch)
    if not identifier:
        return None
    return await fetch_ticket_by_id(identifier)
