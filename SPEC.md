# Dev Context Capsule — Spec

**Status:** v0.1 — in progress  
**Owner:** Vishal  
**Last updated:** 2026-06-12

---

## 1. Problem + Goals

### The pain

You're deep in a bug. You've narrowed it to one file, know the next three steps, have three browser tabs open with relevant docs. Then a meeting hits. Or you switch to a hotfix branch. Or you end the day.

When you return — 2 hours or 2 days later — the mental state is gone. You spend 20–30 minutes re-reading commits, re-opening tabs, re-tracing the path. Every developer does this multiple times a week. Nobody has solved it well.

### What this is

An MCP server that captures your dev context (git state + a note) before you leave a task, and briefs you with a structured "where you left off" summary when you return. Works in Claude Desktop, Cursor, or any MCP client. No database. No cloud. Plain JSON files on disk.

### What this is NOT

- Not a task manager (Jira/Linear exist)
- Not a code summariser (GitHub Copilot exists)
- Not a team tool (v1 is personal only)
- Not a replacement for good commit messages

### Success criteria

| Metric | Target |
|---|---|
| Time to re-load context after returning | < 2 min (vs. 20–30 min today) |
| Setup time for a new user | < 5 min |
| False secret redactions | 0 real secrets leaked in any capsule |
| Capsule usefulness rating (self-eval) | ≥ 4/5 after 2 weeks of daily use |

### Non-goals for v1

- Auto-capturing open browser tabs
- IDE file tracking (beyond git status)
- Real-time sync across machines
- Team-shared capsules

---

## 2. Architecture + Components

### How the 5 learning tracks map onto this project

```
┌─────────────────────────────────────────────────────────┐
│                    MCP CLIENT                           │
│          (Claude Desktop / Cursor / Claude Code)        │
└──────────────────────┬──────────────────────────────────┘
                       │  MCP protocol (stdio)
                       │
┌──────────────────────▼──────────────────────────────────┐
│                   server.py  [MCP — Vishal]             │
│                                                         │
│   ┌─────────────────┐     ┌─────────────────────────┐  │
│   │  Capture Agent  │     │    Restore Agent        │  │
│   │  [Sub-agents —  │     │    [Sub-agents — Rishab] │  │
│   │   Rishab]       │     │                         │  │
│   └────────┬────────┘     └──────────┬──────────────┘  │
│            │                         │                  │
│   ┌────────▼─────────────────────────▼──────────────┐  │
│   │            Guardrails  [Ankit]                  │  │
│   │   • strip secrets before write                  │  │
│   │   • flag stale capsules on read (> 14 days)     │  │
│   │   • warn on capsule overflow (> 20 per branch)  │  │
│   └────────┬─────────────────────────┬──────────────┘  │
│            │                         │                  │
│   ┌────────▼──────────┐   ┌──────────▼──────────────┐  │
│   │  Capsule Store    │   │  RAG / Compare  [Liji]  │  │
│   │  [Memory — Pulkit]│   │  retrieve past sessions │  │
│   │  ~/.dev-capsules/ │   │  surface similar context│  │
│   └───────────────────┘   └─────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │     Git Hooks [Pulkit]  │
          │  post-checkout  ──────► nudge restore on branch switch
          │  pre-push       ──────► nudge capture before PR
          └─────────────────────────┘
```

### Data flow — capture

```
User types: capture_context note="..."
       │
       ▼
run git commands (branch, status, log, diff --stat)
       │
       ▼
Guardrail: strip_secrets()
       │
       ▼
Build capsule dict
       │
       ▼
Write → ~/.dev-capsules/{repo}/{branch}/{timestamp}.json
       │
       ▼
Return confirmation + overflow warning if needed
```

### Data flow — restore

```
User types: restore_context
       │
       ▼
Read current branch from git
       │
       ▼
Load latest JSON from ~/.dev-capsules/{repo}/{branch}/
       │
       ▼
Guardrail: staleness check (> 14 days → flag)
       │
       ▼
Format briefing (branch, note, git state, commits)
       │
       ▼
RAG hint: if older capsules exist → prompt user to run compare_capsules
       │
       ▼
Return markdown briefing
```

### Storage layout

```
~/.dev-capsules/
  {repo-name}/
    {safe-branch-name}/
      20260611_083000.json    ← latest
      20260609_174500.json
      20260607_091200.json
```

### Capsule schema

```json
{
  "timestamp":          "2026-06-11T08:30:00+00:00",
  "branch":             "fix/orders-n-plus-one",
  "repo":               "/Users/vishal/projects/myapp",
  "note":               "narrowed to line 84, next: check eager-load spec",
  "git_status":         " M app/controllers/orders_controller.rb\n M spec/orders_spec.rb",
  "recent_commits":     "a1b2c3d fix: add index migration\n...",
  "staged_diff_stat":   "",
  "unstaged_diff_stat": " app/controllers/orders_controller.rb | 3 +++"
}
```

---

## 3. Full Feature List

### MCP Tools

#### `capture_context(note: str = "")`
- Runs: `git branch --show-current`, `git status --short`, `git log --oneline -5`, `git diff --cached --stat`, `git diff --stat`, `git rev-parse --show-toplevel`
- Applies secret stripping to `git_status`, `staged_diff_stat`, `unstaged_diff_stat`
- Saves JSON to `~/.dev-capsules/{repo}/{branch}/{YYYYMMDD_HHMMSS}.json`
- Returns: confirmation, file saved, changed file count, the note
- Guardrail: if > 20 capsules on branch → warn user to clean up
- Graceful fallback: if not in a git repo → saves with `branch=no-branch`, `repo=unknown-repo`

#### `restore_context(branch: str = "")`
- Default: uses current branch from `git branch --show-current`
- Loads the **most recent** capsule JSON for that branch
- Guardrail: if capsule age > 336h (14 days) → marks as ⚠️ STALE
- Returns: formatted markdown briefing — note, git state, last 5 commits, staged/unstaged stats
- RAG hint: if > 1 capsule exists → suggests `compare_capsules`
- Returns friendly message if no capsule found

#### `list_capsules()`
- Walks all of `~/.dev-capsules/`
- Shows: repo name, branch name, capsule count, last-saved date, last note
- Returns "No capsules saved yet" if directory is empty

#### `compare_capsules(branch: str = "", limit: int = 3)`
- Loads the last `limit` capsules for a branch (newest first)
- Shows per session: timestamp, note, changed file count, last commit
- Use case: "am I going in circles?" — see if the same files keep appearing
- RAG role: surface past attempts so you don't repeat dead ends

### Git Hooks

#### `hooks/post-checkout`
- Fires on branch switch (not file checkout — checks `$3 == 1`)
- Checks if capsules exist for the new branch in `~/.dev-capsules/`
- If yes → prints one-line reminder to run `restore_context`
- Non-blocking, never prevents a checkout

#### `hooks/pre-push`
- Fires before every push
- Prints one-line reminder to run `capture_context` with a note
- Non-blocking, always exits 0

#### `install.sh`
- Must be run from inside a git repo
- Checks for existing hooks — appends rather than overwrites if a hook already exists
- Installs both hooks with `chmod +x`

### Guardrails (Ankit's track)

| Guardrail | Where | Logic |
|---|---|---|
| Secret stripping | `capture_context` | Regex patterns: `api_key=`, `sk-*`, `ghp_*`, `AKIA*`, `xox*` |
| Staleness flag | `restore_context` | Age > 336h (14 days) → adds ⚠️ STALE to briefing |
| Overflow warning | `capture_context` | > 20 capsules on a branch → suggests cleanup |
| Graceful git fallback | all tools | No git repo → uses sensible defaults, doesn't crash |

### Memory (Pulkit's track)

- Storage: plain JSON files, one per capture event
- Keyed by: `repo name / branch name / timestamp`
- Retention: manual — user deletes files when done with a branch
- No database, no migrations, no dependencies beyond Python stdlib + mcp

### RAG (Liji's track — v1 is simple retrieval)

- v1: file-based retrieval — load last N capsules for a branch by filename sort
- v2: keyword search across notes using simple grep-style matching
- v3: embed notes with a local model, retrieve by semantic similarity across branches

---

## 4. Phased Build Plan

### v1 — Core (DONE ✅)

Goal: works end-to-end, usable daily, shareable as a repo.

- [x] `server.py` with 4 MCP tools
- [x] File-based capsule store (`~/.dev-capsules/`)
- [x] Secret stripping guardrail
- [x] Staleness + overflow guardrails
- [x] `post-checkout` and `pre-push` git hooks
- [x] `install.sh`
- [x] README with setup + MCP config snippets
- [x] Smoke tests (all 4 tools register, save/load/strip/stale all verified)

**Demo:** `capture_context note="..."` → switch branch → `restore_context` → briefing appears.

---

### v2 — Smarter (1–2 weeks)

Goal: the briefing gets better; the project becomes measurable.

**Evals (Rishab's track)**
- [ ] Build a small eval set: 20 real capsule→restore pairs, label each briefing as helpful / not helpful / partially helpful
- [ ] Add LLM-as-judge scorer: given a capsule, does the briefing correctly identify the "what you were doing" and "next step"?
- [ ] Track score over time as you tune the restore prompt
- [ ] Gate: a prompt change that regresses the score by > 10% gets flagged before merge

**Richer capture**
- [ ] Add `open_files` field: parse `git diff --name-only` to list which files were actively changed (not just stats)
- [ ] Add `last_error` field: optional — user can paste the last stack trace or error message they were debugging
- [ ] Add `next_steps` field: separate from `note` — forces the user to be explicit about the single next action

**Smarter restore**
- [ ] Show `open_files` in briefing with one-line summaries per file (from `git diff --stat`)
- [ ] If `last_error` is set → surface it prominently in the briefing
- [ ] Cross-branch search: if no capsule on current branch, check if a related branch has one (match by repo + partial branch name)

**RAG v2 (Liji's track)**
- [ ] Keyword search across all capsule notes: `search_capsules(query="N+1")` finds all sessions where you mentioned that term
- [ ] Useful for: "have I hit this before?" — search your own history before Googling

---

### v3 — Team + Atlan variant (1 month+)

Goal: something worth writing up and posting, not just using.

**Team capsules**
- [ ] Optional: commit `.dev-capsules/` to the repo (sanitise first — guardrail runs on export)
- [ ] `share_capsule(branch)` — exports a capsule as a sanitised markdown snippet you can paste into a PR description or Slack
- [ ] Team context: "pick up where Alice left off" on a shared feature branch

**Atlan variant — Metadata Session Capsule**
- [ ] Swap git context for Atlan MCP context: current asset, lineage path, last enrichment run, open issues on the asset
- [ ] `capture_metadata_context(asset_id, note)` — saves where you were in the catalog
- [ ] `restore_metadata_context(asset_id)` — briefs you on the asset state when you left
- [ ] Use case: a data steward working across 40 assets over a week — never lose track of which ones you enriched, which you deferred, and why

**MCP Roots (Vishal's track — advanced)**
- [ ] Wire `roots` so the server only reads/writes capsules inside the current project's directory scope
- [ ] Prevents cross-project capsule pollution when running in a multi-root workspace

**Observability**
- [ ] Add Langfuse tracing: log every `capture_context` and `restore_context` call with latency, capsule size, branch
- [ ] Dashboard: how often do you capture? How often do you restore? Are briefings getting used?

---

## Open questions

| Question | Status |
|---|---|
| Should capsules older than 90 days auto-delete? | Undecided — keep for v1, revisit |
| Should `capture_context` also capture clipboard content? | No — too noisy, privacy risk |
| IDE plugin (VS Code extension) instead of git hooks? | Explore in v3 |
| Should `note` be required, not optional? | Try optional first — see if people leave it blank |

---

## File structure

```
dev-capsule/
  server.py          # MCP server — all 4 tools
  install.sh         # wires hooks into a git repo
  hooks/
    post-checkout    # branch-switch reminder
    pre-push         # pre-push reminder
  SPEC.md            # this file
  README.md          # setup guide
```

Capsules live outside the repo at `~/.dev-capsules/` — never committed by default.
