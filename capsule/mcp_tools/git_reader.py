"""Read git state from the current repo at capture time."""

from pathlib import Path
from dataclasses import dataclass

import git


@dataclass
class GitSnapshot:
    branch: str
    repo_name: str
    recent_commits: list[dict]      # last 5 commits: sha, message, author, timestamp
    staged_files: list[str]
    unstaged_files: list[str]
    untracked_files: list[str]
    stash_count: int
    diff_summary: str = ""          # capped unified diff of staged + unstaged changes


def read_git_state(repo_path: str = ".") -> GitSnapshot:
    repo = git.Repo(repo_path, search_parent_directories=True)

    branch = repo.active_branch.name if not repo.head.is_detached else repo.head.commit.hexsha[:8]
    repo_name = Path(repo.working_dir).name

    recent_commits = [
        {
            "sha": c.hexsha[:8],
            "message": c.message.strip().splitlines()[0],
            "author": c.author.name,
            "timestamp": c.committed_datetime.isoformat(),
        }
        for c in repo.iter_commits(max_count=5)
    ]

    diff_staged = repo.index.diff("HEAD") if repo.head.is_valid() else []
    diff_unstaged = repo.index.diff(None)

    # Build a compact diff summary — staged first, then unstaged, capped at 2000 chars total
    diff_parts = []
    try:
        staged_text = repo.git.diff("--cached")
        if staged_text:
            diff_parts.append(f"[staged diff]\n{staged_text}")
    except Exception:
        pass
    try:
        unstaged_text = repo.git.diff()
        if unstaged_text:
            diff_parts.append(f"[unstaged diff]\n{unstaged_text}")
    except Exception:
        pass
    raw_diff = "\n".join(diff_parts)
    diff_summary = raw_diff[:2000] + ("\n…(truncated)" if len(raw_diff) > 2000 else "")

    return GitSnapshot(
        branch=branch,
        repo_name=repo_name,
        recent_commits=recent_commits,
        staged_files=[d.a_path for d in diff_staged],
        unstaged_files=[d.a_path for d in diff_unstaged],
        untracked_files=repo.untracked_files,
        stash_count=len(repo.git.stash("list").splitlines()) if repo.git.stash("list") else 0,
        diff_summary=diff_summary,
    )
