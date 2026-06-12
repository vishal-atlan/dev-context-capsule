"""MCP server entry point — exposes capsule tools to Claude Code."""

from fastmcp import FastMCP

from capsule.agents.capture import capture_context
from capsule.agents.restore import restore_context
from capsule.memory.store import list_capsules, delete_capsule
from capsule.rag.retriever import search_capsules
from capsule.hooks.install import install_hooks, uninstall_hooks
from capsule.agents.ticket_context import get_ticket_context, get_active_tickets_with_prs

mcp = FastMCP("dev-context-capsule")


@mcp.tool()
async def capture(repo_path: str = ".", note: str = "") -> str:
    """Capture current dev context: git state, open files, recent commits, active task.

    Args:
        repo_path: Path to the git repo (default: current dir).
        note: Optional free-text note to include in the capsule.
    """
    return await capture_context(repo_path=repo_path, note=note)


@mcp.tool()
async def restore(repo_path: str = ".", branch: str = "") -> str:
    """Restore dev context for a branch. Returns a briefing of where you left off.

    Args:
        repo_path: Path to the git repo (default: current dir).
        branch: Branch name (default: current branch).
    """
    return await restore_context(repo_path=repo_path, branch=branch)


@mcp.tool()
async def list_saved(repo_path: str = ".") -> str:
    """List all saved capsules for a repo, newest first."""
    return list_capsules(repo_path=repo_path)


@mcp.tool()
async def search(query: str, repo_path: str = ".") -> str:
    """Search capsules using keyword/semantic search.

    Args:
        query: What you're looking for (e.g. "N+1 query fix", "auth middleware").
        repo_path: Limit search to this repo (default: current dir).
    """
    return search_capsules(query=query, repo_path=repo_path)


@mcp.tool()
async def delete(capsule_id: str) -> str:
    """Delete a capsule by ID.

    Args:
        capsule_id: ID from list_saved output.
    """
    return delete_capsule(capsule_id=capsule_id)


@mcp.tool()
async def ticket_status(ticket_id: str) -> str:
    """Get full context for a ticket: status, where you left off, PR status.

    Answers questions like:
      "Where was I on PROJ-123?"
      "What's left on PROJ-123?"
      "What's the PR status of PROJ-123?"
      "What's pending on PROJ-123?"

    Works with Linear and Jira (set TICKET_PROVIDER=linear or jira).

    Args:
        ticket_id: Ticket identifier (e.g. "PROJ-123") or natural language
                   containing the ticket ID (e.g. "where was I on proj-123").
    """
    return await get_ticket_context(ticket_id)


@mcp.tool()
async def active_tickets() -> str:
    """List all active tickets assigned to me with their PR status.

    Works with Linear and Jira (set TICKET_PROVIDER=linear or jira).
    Answers: "What are all my active tickets with PR status?"
    """
    return await get_active_tickets_with_prs()


@mcp.tool()
async def install(repo_path: str = ".") -> str:
    """Install capsule git hooks into a repo. Zero tracked file changes.

    Creates .git/capsule-hooks/ and overrides core.hooksPath locally.
    Chains existing security/Husky hooks so nothing breaks.

    Args:
        repo_path: Path to the git repo to install hooks into.
    """
    return install_hooks(repo_path=repo_path)


@mcp.tool()
async def uninstall(repo_path: str = ".") -> str:
    """Remove capsule git hooks from a repo and restore original hooksPath.

    Args:
        repo_path: Path to the git repo to remove hooks from.
    """
    return uninstall_hooks(repo_path=repo_path)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
