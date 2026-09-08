# Project boundary

This repository contains an unofficial, independently maintained personal
utility. It is not part of Codex, the Codex CLI, or any OpenAI repository.

The repository owns the program source and tests. Runtime Codex state remains
outside this repository under `$CODEX_HOME` (normally `~/.codex`) and must never
be copied into Git. In particular, never commit sessions, memories, SQLite
databases, credentials, authentication files, logs, or compacted user content.

Keep destructive session operations delegated to the installed `codex` CLI.
Do not rewrite resumable rollout JSONL files directly.

Before committing changes, run the focused unit tests and inspect the complete
diff for private session content or machine-specific runtime data.
