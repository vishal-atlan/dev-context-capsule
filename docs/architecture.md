# Architecture — dev-context-capsule

## The Problem

Context switching is one of the most expensive things a developer does. The cost isn't the switch itself — it's the **re-ramp**: spending 20-40 minutes reconstructing the mental state you had before you were interrupted. This problem compounds when:

- You're debugging something non-trivial (the mental state has layers)
- You switch to a hotfix branch and lose the thread on the main branch
- You pick up someone else's stale PR and have no idea where they left off

The goal of this system is to make context restoration **instant** — the same way `git stash` restores code state, this restores mental state.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        Developer                            │
└────────────────────────┬────────────────┬───────────────────┘
                         │                │
              Git Events │          Manual│calls via
         (hooks fire)    │         Claude │Code / CLI
                         ▼                ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         MCP Server (server.py)                        │
│  capture · restore · list_saved · search · delete · ticket_status ·  │
│  active_tickets · install · uninstall                                 │
└──────────────┬───────────────────────────────┬───────────────────────┘
               │                          │
    ┌──────────▼──────────┐    ┌──────────▼──────────┐
    │   Capture Agent     │    │   Restore Agent     │
    │  agents/capture.py  │    │  agents/restore.py  │
    └────────┬────────────┘    └─────────┬───────────┘
             │                           │
    ┌────────▼────────────────────────────▼──────────┐
    │               Support Layer                     │
    │                                                 │
    │  ┌────────────────┐   ┌──────────────────────┐ │
    │  │  Git Reader    │   │   Sanitizer          │ │
    │  │ (GitPython)    │   │   (guardrails)       │ │
    │  └────────────────┘   └──────────────────────┘ │
    │                                                 │
    │  ┌────────────────┐   ┌──────────────────────┐ │
    │  │  Ticket Reader │   │   VS Code Reader     │ │
    │  │  (Linear/Jira) │   │   (open files)       │ │
    │  │  + comments    │   └──────────────────────┘ │
    │  └────────────────┘                            │
    │                                                 │
    │  ┌────────────────┐   ┌──────────────────────┐ │
    │  │ Claude Session │   │   SQLite Store       │ │
    │  │ Reader         │   │   (memory/ + history)│ │
    │  │ (~/.claude/)   │   └──────────────────────┘ │
    │  └────────────────┘                            │
    │                                                 │
    │  ┌────────────────┐                            │
    │  │  TF-IDF        │                            │
    │  │  Retriever     │                            │
    │  │  (rag/)        │                            │
    │  └────────────────┘                            │
    └─────────────────────────────────────────────────┘
                             │
                    ┌────────▼──────────────┐
                    │   LLM Client (_llm.py) │
                    │  anthropic / bedrock / │
                    │  any OpenAI-compat.    │
                    └────────────────────────┘
```

---

## Components

### MCP Server (`capsule/server.py`)

Entry point and tool registry. Uses [FastMCP](https://github.com/jlowin/fastmcp) to expose nine tools over the MCP protocol (stdio transport):

| Tool | Description |
|------|-------------|
| `capture` | Trigger a capture for a repo path |
| `restore` | Get a warm-up briefing for a branch |
| `list_saved` | List all capsules for a repo |
| `search` | Keyword search across capsules |
| `delete` | Remove a capsule by ID |
| `ticket_status` | Full context for a ticket: status, PRs across repos, saved capsules |
| `active_tickets` | All your assigned in-progress tickets with PR status |
| `install` | Install git hooks into a repo |
| `uninstall` | Remove git hooks from a repo |

Claude Code (or any MCP client) connects to this server and calls tools conversationally.

---

### LLM Client Factory (`capsule/agents/_llm.py`)

Selects and initialises the LLM client from env vars. Zero hardcoding — switching providers requires no code changes.

| Env var | Purpose |
|---------|---------|
| `CAPSULE_LLM_PROVIDER` | `anthropic` \| `bedrock` \| `litellm` (auto-detected if unset) |
| `CAPSULE_MODEL` | Override model for any provider |
| `ANTHROPIC_API_KEY` | Direct Anthropic API |
| `AWS_*` | Bedrock credentials; region prefix auto-derived |
| `CAPSULE_LITELLM_BASE_URL` / `CAPSULE_LITELLM_API_KEY` | Any OpenAI-compatible proxy |

Returns `(client, model, provider)`. `client=None` signals passthrough mode.

---

### Capture Agent (`capsule/agents/capture.py`)

Responsible for turning the current git state into a stored capsule.

**Steps:**
1. Call `GitReader` to snapshot the repo — branch, commits, staged/unstaged files, **plus the actual unified diff** (capped at 2000 chars)
2. Call `TicketReader` to enrich with ticket title, status, and **last 5 comments** from branch name
3. Call `VSCodeReader` to include currently open files
4. Call `ClaudeSessionReader` to fetch **recent user prompts** from active Claude Code sessions (covers VS Code extension, terminal CLI, and Desktop — all share `~/.claude/projects/`)
5. Call `Store.get_branch_history()` to fetch the **last 3 capsule summaries** for this branch (session memory)
6. Serialize the combined snapshot to JSON
7. Run through `Sanitizer` to strip secrets
8. Send sanitized snapshot to LLM via `_llm.py` — 6 signal sources, single call
9. Receive 3-5 sentence summary that continues the narrative from prior sessions
10. Sanitize LLM output (second pass)
11. Save to SQLite via `Store`

**System prompt design:**
The prompt instructs the LLM to produce a briefing that captures:
- What was being worked on / attempted
- What had been found or narrowed down
- The concrete next step

The prompt explicitly forbids bullet points (forces prose, which reads more naturally on restore).

---

### Restore Agent (`capsule/agents/restore.py`)

Responsible for reconstructing mental state on return.

**Steps:**
1. Resolve branch name (current branch if not specified)
2. Fetch latest capsule for that branch from SQLite
3. If no capsule: fall back to RAG search for the branch name
4. Snapshot current git state via `GitReader`
5. Send both (saved capsule + current state) to Claude
6. Claude generates warm-up briefing noting what changed since capture
7. Prepend stale warning if capsule > 14 days old

**The key insight:** The restore agent doesn't just replay the capsule — it *compares* saved vs current state, so it can say "2 commits landed since you left, but none touch the files you were working on."

---

### Git Reader (`capsule/mcp_tools/git_reader.py`)

Thin wrapper over [GitPython](https://gitpython.readthedocs.io/). Captures:

| Field | How |
|-------|-----|
| `branch` | `repo.active_branch.name` |
| `repo_name` | `Path(repo.working_dir).name` |
| `recent_commits` | `repo.iter_commits(max_count=5)` — sha, message, author, timestamp |
| `staged_files` | `repo.index.diff("HEAD")` |
| `unstaged_files` | `repo.index.diff(None)` |
| `untracked_files` | `repo.untracked_files` |
| `stash_count` | `git stash list` line count |
| `diff_summary` | `repo.git.diff("--cached")` + `repo.git.diff()` — unified diff text, capped at 2000 chars |

`diff_summary` gives the LLM the actual changed code, not just filenames. It can then reference specific functions or variable names in the briefing instead of saying "you changed `handler/scimGroup.go`."

Returns a typed `GitSnapshot` dataclass.

---

### Sanitizer (`capsule/guardrails/sanitizer.py`)

Applied **twice** — once before the LLM call, once on the LLM output.

Strips via regex:
- JWTs (`eyJ...eyJ...sig`)
- Bearer tokens
- `password=`, `api_key=`, `secret=`, `token=` patterns
- AWS credentials
- GitHub PATs (`ghp_...`)
- GitLab PATs (`glpat-...`)
- Slack tokens (`xox*-...`)
- OpenAI / Anthropic keys (`sk-...`)
- Generic 32-64 char hex strings (loose — some false positives acceptable)

Also exposes `is_stale(captured_at_iso, max_days=14)` for flagging old capsules.

---

### SQLite Store (`capsule/memory/store.py`)

Single SQLite file at `~/.capsule/capsules.db`. Schema:

```sql
CREATE TABLE capsules (
    id          TEXT PRIMARY KEY,    -- 8-char UUID prefix
    repo_name   TEXT NOT NULL,       -- e.g. "heracles"
    repo_path   TEXT NOT NULL,       -- abs path, stable storage key
    branch      TEXT NOT NULL,       -- e.g. "fix/scim-409"
    captured_at TEXT NOT NULL,       -- ISO 8601 UTC
    summary     TEXT NOT NULL,       -- the distilled capsule text
    raw_json    TEXT NOT NULL        -- full GitSnapshot as JSON
);

CREATE INDEX idx_branch ON capsules(repo_path, branch);
```

Operations: `save_capsule`, `get_latest_capsule`, `list_capsules`, `get_all_capsules`, `delete_capsule`.

---

### TF-IDF Retriever (`capsule/rag/retriever.py`)

Builds a TF-IDF matrix over `branch + summary` text for all capsules. Uses `sklearn.feature_extraction.text.TfidfVectorizer` + cosine similarity.

Used in two cases:
1. Explicit `search` tool call from the user
2. Fallback in `restore` when no capsule exists for the exact branch — searches for the closest match

Returns top-k results above a 0.01 cosine similarity threshold.

**Upgrade path:** Replace with sentence embeddings (e.g. `sentence-transformers`) + FAISS for better semantic recall. The interface is the same — swap the implementation inside `retriever.py`.

---

### Ticket Reader (`capsule/mcp_tools/ticket_reader.py`)

Routes ticket lookups to Linear or Jira based on `TICKET_PROVIDER` env var (default: `linear`). Parses the ticket ID from the branch name (e.g. `fix/GOVFOUN-532-block-deletion` → `GOVFOUN-532`) and fetches title, status, description, and **last 5 comments** (newest first, capped at 300 chars each).

Comments are where the real debugging conversation lives — teammates posting stack traces, hypotheses, findings. Including them means the LLM can reference specifics that never appear in git history.

Returns a `TicketInfo` dataclass (with `comments: list[str]`) used by the capture agent and the `ticket_status` / `active_tickets` tools. Jira support is present but does not yet fetch comments (falls back to empty list).

---

### VS Code Reader (`capsule/mcp_tools/vscode_reader.py`)

Reads `~/.capsule/vscode-open-files.json`, written continuously by the companion VS Code extension (`vscode-extension/`). Filters the file list to paths within the current repo. Silent no-op if the file doesn't exist (VS Code not open or extension not installed).

---

### Claude Session Reader (`capsule/mcp_tools/claude_session_reader.py`)

Reads recent Claude Code session context from `~/.claude/projects/`. Claude Code (VS Code extension, terminal CLI, and Desktop app) all write sessions to the same directory, so one reader covers all three surfaces.

**How path encoding works:**

Claude Code encodes the working directory as the project directory name by replacing every non-alphanumeric character with `-` and collapsing consecutive dashes:

```
/Users/vishal.kumar/Documents/GitHub/heracles
  →  -Users-vishal-kumar-Documents-GitHub-heracles
```

The reader checks both the repo-specific directory and its parent (sessions opened from `~/Documents/GitHub/` are common when switching between repos).

**What it reads:**

Each session JSONL file contains many entry types. The reader extracts two:
- `ai-title` — the AI-generated session title (e.g. "Fix SCIM group deletion bug")
- `last-prompt` — the actual text the developer typed, updated on every user turn

It returns the last 5 prompts per session, up to 3 sessions, from files modified within the last 48 hours. Interrupted/system entries are skipped.

**Why this matters:**

Git state tells you *what changed*. Claude session prompts tell you *what you were trying to figure out* — even when the code is clean (exploratory research, reading files, asking questions). The two signals together give a much richer picture of mental state at capture time.

---

### SQLite Store — Session History (`capsule/memory/store.py`)

In addition to basic CRUD, the store exposes `get_branch_history(repo_path, branch, limit=3)` which returns the last N capsule summaries for a branch. This is fed into every new capture as `previous_sessions`, giving the LLM memory across work sessions:

- Session 1: "Narrowed the 409 to a stale externalId mismatch."
- Session 2: "Found the externalId is case-sensitive in MapGroup. Added the comparison fix."
- Session 3 (new capture): Instead of re-summarizing from scratch, the LLM writes: "Since confirming the case-insensitive fix in MapGroup, you've moved on to writing the integration test — the test scaffold is in place but the mock SCIM payload is still missing."

---

### Git Hooks (`capsule/hooks/install.py`)

Installs two hooks into any target repo's `.git/capsule-hooks/` (inside `.git/`, never committed):

**`post-checkout`** — fires on branch switch, triggers `capsule restore` in the background.

**`pre-push`** — fires before every push, triggers `capsule capture` in the background.

Chains existing hooks (Husky, secguard, etc.) before running capsule. Overrides `core.hooksPath` in `.git/config` only — zero tracked file changes.

---

## Integration: Claude Code as MCP Client

```
Developer
   │
   │ (conversation in Claude Code)
   ▼
Claude Code ──► MCP Protocol (stdio) ──► capsule MCP server
                                               │
                                         tool: capture / restore
                                               │
                                         Capture or Restore Agent
                                               │
                                         Claude API (nested call)
                                               │
                                         Briefing returned to conversation
```

The nested Claude API call is intentional: the MCP server uses Claude to *distill* and *interpret* raw git data into human-readable context. The outer Claude (in Claude Code) handles the conversation; the inner Claude handles the summarization/restoration.

---

## Storage Layout

```
~/.capsule/
├── capsules.db                  # all capsules, all repos, all branches
└── vscode-open-files.json       # written by VS Code extension, read at capture time

/path/to/repo/.git/capsule-hooks/   # never tracked or committed
├── post-checkout                    # auto-restore on branch switch
└── pre-push                         # auto-capture on push
```

Nothing is written to the project directory — the capsule DB is user-local and never committed.

---

## What's Missing for Production Use

### Encryption at rest
The SQLite DB is plaintext. For repos containing sensitive notes, add [SQLCipher](https://www.zetetic.net/sqlcipher/) via `pysqlcipher3`. Key from env var.

### IDE close hook
The VS Code extension currently writes open files passively on tab change. A close/deactivation hook that triggers `capsule capture` automatically when switching away from VS Code would remove the last manual step.

### Team capsules
Push capsules to a shared backend (Postgres, Supabase, etc.) keyed by `(org, repo, branch)`. Enables the handoff use case: "pick up where Alice left off on this branch."
