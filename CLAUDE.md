# claude-code-redact

Claude Code hooks that keep secrets away from the model: `redact.py output` (PostToolUse, redacts tool output) and
`redact.py prompt` (UserPromptSubmit, blocks prompts with pasted secrets). Public repository
(MIT): never commit real secrets, personal paths or details about the maintainer's infrastructure; test values are
fake and assembled at runtime.

## Binding conventions

This project follows these conventions:

- **`kanban` trigger** (`~/.claude/CLAUDE.md`) — any Edit/Write to `KANBAN.md` or `KANBAN-done.md` requires the `kanban` skill first. Canonical attributes (markdown-kanban by holooooo).
- **Project memory** — persistent memories in `.claude/memory/` (versioned in git), indexed in `MEMORY.md`. Never in user scope.
- **Verification** — nothing is "done" without evidence (build/tests/verified behaviour).

## Task management (Kanban)

- **`KANBAN.md`** — active board (columns `Backlog` / `In progress` / `Done`).
- **`KANBAN-done.md`** — history. Cards in the board's `Done` column are moved here as they pile up, keeping the main board focused on active work.

## Skill `kanban` — project overrides

- archiveFile: KANBAN-done.md

## Commands / Setup

- Tests: `python -I -m unittest discover -s tests`
- The installed copy lives in `~/.claude/hooks/redact.py`; after changing `redact.py`, copy it there again.
- Standard library only, Python 3.9+. Keep it a single file.
