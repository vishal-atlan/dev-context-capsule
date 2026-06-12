"""Fetch GitHub PRs associated with a ticket ID across repos.

Uses the `gh` CLI (already authenticated) — no extra token needed.

Configure repos to search via the GITHUB_REPOS env var (comma-separated):
  export GITHUB_REPOS="org/repo-a,org/repo-b,org/repo-c"
"""

import json
import os
import subprocess
from dataclasses import dataclass


def _get_repos() -> list[str]:
    env = os.environ.get("GITHUB_REPOS", "")
    return [r.strip() for r in env.split(",") if r.strip()]


@dataclass
class PRInfo:
    repo: str
    number: int
    title: str
    url: str
    state: str          # OPEN / MERGED / CLOSED
    branch: str
    author: str
    created_at: str
    merged_at: str | None

    def to_markdown(self) -> str:
        state_icon = {"OPEN": "🟡", "MERGED": "✅", "CLOSED": "🔴"}.get(self.state, "⚪")
        merged = f" — merged {self.merged_at[:10]}" if self.merged_at else ""
        return (
            f"{state_icon} **[{self.repo}#{self.number}]({self.url})** — {self.title}\n"
            f"   Branch: `{self.branch}` | {self.state}{merged} | by {self.author}"
        )


def _gh_pr_list(repo: str, ticket_id: str) -> list[PRInfo]:
    """Fetch PRs from one repo where branch or title contains the ticket ID."""
    try:
        result = subprocess.run(
            [
                "gh", "pr", "list",
                "--repo", repo,
                "--state", "all",
                "--limit", "10",
                "--json", "number,title,url,state,headRefName,author,createdAt,mergedAt",
                "--search", ticket_id.lower(),
            ],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
        prs = json.loads(result.stdout or "[]")
    except Exception:
        return []

    found = []
    ticket_lower = ticket_id.lower()
    for pr in prs:
        branch = pr.get("headRefName", "")
        title = pr.get("title", "")
        if ticket_lower not in branch.lower() and ticket_lower not in title.lower():
            continue
        found.append(PRInfo(
            repo=repo,
            number=pr["number"],
            title=title,
            url=pr["url"],
            state=pr.get("state", "UNKNOWN"),
            branch=branch,
            author=(pr.get("author") or {}).get("login", "unknown"),
            created_at=pr.get("createdAt", ""),
            merged_at=pr.get("mergedAt"),
        ))
    return found


def get_prs_for_ticket(ticket_id: str, repos: list[str] | None = None) -> list[PRInfo]:
    """Search configured repos for PRs associated with this ticket ID.

    Pass repos explicitly, or set GITHUB_REPOS env var (comma-separated owner/repo pairs).
    Returns empty list if neither is configured.
    """
    repos = repos or _get_repos()
    results = []
    for repo in repos:
        results.extend(_gh_pr_list(repo, ticket_id))
    return results
