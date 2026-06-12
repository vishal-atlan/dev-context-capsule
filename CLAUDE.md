# dev-context-capsule

MCP server that auto-captures dev context mid-task and restores it when you return.

## Stack
- Python 3.11+, FastMCP, Anthropic SDK, openai SDK (litellm provider), httpx
- SQLite storage at `~/.capsule/capsules.db`
- TF-IDF RAG via scikit-learn
- Companion VS Code extension at `vscode-extension/` (pure JS, no compilation)

## Commands
```bash
uv venv && uv pip install -e ".[dev]"   # install
uv pip install -e ".[litellm]"          # add if using LiteLLM/OpenAI-compatible proxy
uv pip install -e ".[bedrock]"          # add if using AWS Bedrock
pytest                                  # run tests (10 tests)
capsule                                 # run MCP server (stdio)
ruff check capsule/                     # lint
```

## Architecture
```
capsule/
  server.py              # MCP tool definitions (entry point) — 9 tools
  agents/
    _llm.py              # LLM client factory: anthropic / bedrock / litellm — env-driven, zero hardcoding
    capture.py           # Capture: git + ticket + vscode → sanitize → LLM → store
    restore.py           # Restore: latest capsule + current state → LLM → briefing
    ticket_context.py    # Aggregates ticket + PRs + capsules for a ticket ID
  mcp_tools/
    git_reader.py            # GitPython: branch, commits, staged/unstaged files + diff_summary (2000 chars)
    ticket_reader.py         # Router: shared TicketInfo (+ comments field) + provider dispatch
    linear_reader.py         # Linear GraphQL provider — fetches comments alongside ticket fields
    jira_reader.py           # Jira REST API provider
    github_reader.py         # gh CLI: PRs across repos matching a ticket ID (GITHUB_REPOS env)
    vscode_reader.py         # Reads ~/.capsule/vscode-open-files.json from VS Code extension
    claude_session_reader.py # Reads ~/.claude/projects/ — last-prompt entries from recent sessions
  memory/
    store.py             # SQLite CRUD: save, get_latest, list, delete (CAPSULE_DB_PATH override)
  rag/
    retriever.py         # TF-IDF search over all capsules
  guardrails/
    sanitizer.py         # Regex secret stripping + stale detection
  hooks/
    install.py           # Safe hook installer — chains existing hooks, zero tracked changes
vscode-extension/        # Companion VS Code extension
  extension.js           # Writes open tabs to ~/.capsule/vscode-open-files.json on tab change
  package.json
```

## LLM providers (CAPSULE_LLM_PROVIDER)
- `anthropic` — direct API, uses `ANTHROPIC_API_KEY`
- `bedrock` — AWS Bedrock, uses `AWS_*` env vars; region prefix auto-derived
- `litellm` — any OpenAI-compatible proxy, uses `CAPSULE_LITELLM_BASE_URL` + `CAPSULE_LITELLM_API_KEY`
- (unset) — passthrough mode: returns structured markdown for Claude Code to interpret

## Capture signal sources (6 total, all optional — fail silently)
1. Git state — branch, commits, staged/unstaged files, unified diff (git_reader.py)
2. Open files in VS Code — via companion extension + vscode_reader.py
3. Linked ticket — title, status, comments from Linear/Jira (ticket_reader.py)
4. Claude Code sessions — recent prompts from ~/.claude/projects/ (claude_session_reader.py)
5. Previous capsules — last 3 summaries for this branch from SQLite (store.get_branch_history)
6. User note — free-text passed at capture time

## Key invariants
- Secrets are stripped before LLM calls AND before storage (guardrails/sanitizer.py)
- Capsules older than 14 days are flagged [STALE] on list/restore
- Storage key = abs(repo_path) + branch — stable across cwd changes
- Hook installer writes to `.git/capsule-hooks/` only — never tracked, never committed
- Adding a new ticket provider: add `{provider}_reader.py` + one branch in `ticket_reader.py`
- Claude session path encoding: replace all non-alphanumeric chars with `-`, collapse consecutive dashes
