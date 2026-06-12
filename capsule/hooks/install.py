"""Install capsule git hooks into a target repo without touching tracked files.

Strategy:
  1. Detect the repo's current core.hooksPath (default, Husky, secguard, etc.)
  2. Create .git/capsule-hooks/ — inside .git/, so NEVER tracked or committed
  3. Write wrapper scripts that:
       a. Chain the ORIGINAL hook (so existing security/Husky hooks still run)
       b. Run capsule capture/restore in background
  4. Override core.hooksPath locally to .git/capsule-hooks/
     (stored in .git/config — never committed)

Result: zero changes to any tracked file in the target repo.
"""

import shutil
import stat
import subprocess
from pathlib import Path

# Hooks we install — (hook_name, trigger_action)
_HOOKS = [
    ("post-checkout", "restore"),   # branch switch → restore context
    ("pre-push", "capture"),        # before push → capture context
]


def _git(repo_path: Path, *args) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def _make_wrapper(original_hook_path: str | None, action: str, capsule_bin: str, hook_name: str) -> str:
    """Build a wrapper script that chains the original hook then runs capsule."""

    original_block = ""
    if original_hook_path:
        original_block = f"""\
# ── Original hook ──────────────────────────────────────────────
if [ -f "{original_hook_path}" ]; then
    "{original_hook_path}" "$@"
    _EXIT=$?
    [ $_EXIT -ne 0 ] && exit $_EXIT
fi
"""

    if action == "restore":
        capsule_block = f"""\
# ── dev-context-capsule: restore context on branch switch ──────
IS_BRANCH_SWITCH="${{3:-0}}"
if [ "$IS_BRANCH_SWITCH" = "1" ]; then
    "{capsule_bin}" restore . 2>/dev/null &
fi
"""
    else:
        capsule_block = f"""\
# ── dev-context-capsule: capture context before push ───────────
"{capsule_bin}" capture . 2>/dev/null &
"""

    return f"#!/usr/bin/env bash\n{original_block}\n{capsule_block}"


def install_hooks(repo_path: str = ".") -> str:
    repo = Path(repo_path).resolve()
    git_dir = repo / ".git"

    if not git_dir.exists():
        return f"No .git directory found at {repo}. Is this a git repo?"

    # Resolve capsule binary — use the one on PATH, else the venv sibling
    capsule_bin = shutil.which("capsule")
    if not capsule_bin:
        # Fall back to the venv in the dev-context-capsule repo
        fallback = Path(__file__).parents[3] / ".venv" / "bin" / "capsule"
        capsule_bin = str(fallback) if fallback.exists() else "capsule"

    # Detect current hooksPath
    current_hooks_path = _git(repo, "config", "core.hooksPath") or ".git/hooks"

    # Resolve original hook directory to absolute path
    if current_hooks_path.startswith(".git/") or current_hooks_path == ".git/hooks":
        original_dir = git_dir / current_hooks_path[len(".git/"):]
    elif Path(current_hooks_path).is_absolute():
        original_dir = Path(current_hooks_path)
    else:
        original_dir = repo / current_hooks_path

    # Create .git/capsule-hooks/ (never tracked)
    capsule_hooks_dir = git_dir / "capsule-hooks"
    capsule_hooks_dir.mkdir(exist_ok=True)

    installed = []
    for hook_name, action in _HOOKS:
        original_hook = original_dir / hook_name
        original_path = str(original_hook) if original_hook.exists() else None

        # For Husky: also check .husky/_/<hook_name> shim
        if not original_path and (repo / ".husky" / "_" / hook_name).exists():
            original_path = str(repo / ".husky" / "_" / hook_name)

        wrapper = _make_wrapper(original_path, action, capsule_bin, hook_name)
        hook_file = capsule_hooks_dir / hook_name

        if hook_file.exists() and "dev-context-capsule" in hook_file.read_text():
            continue  # already installed

        hook_file.write_text(wrapper)
        hook_file.chmod(hook_file.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        installed.append(hook_name)

    # Override hooksPath locally → stored in .git/config, never committed
    _git(repo, "config", "--local", "core.hooksPath", ".git/capsule-hooks")

    if not installed:
        return (
            f"Hooks already installed in {repo.name}/.git/capsule-hooks/\n"
            f"core.hooksPath → .git/capsule-hooks (local, not committed)"
        )

    chained = [h for h, _ in _HOOKS if (original_dir / h).exists() or (repo / ".husky" / "_" / h).exists()]
    return (
        f"Installed hooks in {repo.name}/.git/capsule-hooks/: {', '.join(installed)}\n"
        f"core.hooksPath → .git/capsule-hooks (local, not committed)\n"
        f"Original hooks chained: {', '.join(chained) or 'none found'}\n"
        f"Capsule binary: {capsule_bin}\n"
        f"Zero tracked file changes."
    )


def uninstall_hooks(repo_path: str = ".") -> str:
    """Remove capsule hooks and restore previous hooksPath."""
    repo = Path(repo_path).resolve()
    capsule_hooks_dir = repo / ".git" / "capsule-hooks"

    if capsule_hooks_dir.exists():
        shutil.rmtree(capsule_hooks_dir)

    # Remove our local hooksPath override (restores to whatever was set before)
    subprocess.run(
        ["git", "-C", str(repo), "config", "--local", "--unset", "core.hooksPath"],
        capture_output=True,
    )
    return f"Removed capsule hooks from {repo.name}. Original hook chain restored."


if __name__ == "__main__":
    import sys
    # Usage: python -m capsule.hooks.install [path]
    #        python -m capsule.hooks.install uninstall [path]
    if len(sys.argv) > 1 and sys.argv[1] == "uninstall":
        print(uninstall_hooks(sys.argv[2] if len(sys.argv) > 2 else "."))
    else:
        print(install_hooks(sys.argv[1] if len(sys.argv) > 1 else "."))
