# User guide

Return to the [introduction and screenshots](../README.md). This guide covers
terminal controls, session lifecycle, memory editing, and scripting.

## Quick start

```bash
codex-man
```

See [installation](../README.md#get-started) if the command is not installed.
Rewind was verified against Codex 0.153.4. Run the executable directly: its inline
`uv` metadata supplies the pinned Textual dependency without modifying system Python.

The suggested checkout is `~/projects/codex-session-manager`. The `codex-man`
executable in `~/.local/bin` is only a symlink, keeping this project separate
from Codex's runtime state in `~/.codex`. The longer
`codex-session-manager` command may be retained as a compatibility alias. The
script honors `$CODEX_HOME` when your runtime state lives somewhere else.

Program location and runtime-data location are intentionally independent:

- Source, tests, and documentation live in this repository.
- Codex sessions, databases, memories, and `config.toml` remain under
  `$CODEX_HOME`, which defaults to `~/.codex`.
- `--codex-home PATH` selects another runtime tree for one invocation. The
  selected path is also passed to delegated Codex archive, delete, rename, and
  resume operations.

No arguments opens the full-screen session browser. It scales to the current
terminal and updates when the SSH terminal is resized. The table, preview, and
full documents scroll independently.

## Full-screen controls

- Arrow keys, Page Up/Down, mouse click, and wheel navigate the session table.
- `/` focuses live search. The selectors filter by state and sort by last use,
  size, creation date, or name.
- The table includes the session directory relative to your home folder. Long
  paths keep their trailing components, for example `…/projects/website`.
- `Enter` opens **Summary**: metadata plus larger beginning/end excerpts. `V`
  (or `T`) opens **Full conversation**: every human message and Codex final
  answer in a compact scrollable viewer. Each message begins with a local
  `MM/DD/YY HH:MM >` timestamp; human messages use a lighter background and
  Codex final answers use black. Intermediate commentary, reasoning, and tool
  activity are omitted. These are deliberately different actions and labels.
- `W` opens the rewind picker, also available from Full conversation.
- `R` renames, `A` archives/restores, `C` (Export) makes a verified compact Markdown
  archive, and `D` deletes. **Resume safe** (green, `S`) explicitly starts with
  the workspace-write sandbox and on-request approvals. **Resume unrestricted**
  (red, `U`) disables both sandbox and approvals and requires a warning
  confirmation.
- `M` opens the memory browser. **Overview** initially shows only the summary,
  registry, and raw extraction layers. Use the selector to inspect Evidence,
  Corrections, or All files. **How memory works** (`F1`) explains the layers and
  all three memory controls. Select a file and press `Enter`, `V`, or **Full
  file** to read it in the scrollable viewer.
- `:` opens a command bar. For example: `:sort size`, `:filter archived`,
  `:search website`, `:rename NEW NAME`, `:compact`, and `:help`.
- `Ctrl+P` opens Textual's command palette; `Ctrl+R` refreshes Codex state; `Q`
  exits.

Inside either full-screen viewer, use Up/Down, Page Up/Page Down, Home/End, the
mouse wheel, or the Top/Bottom buttons. `Esc` returns to the browser.

On a short terminal, the preview collapses so the table and actions remain
usable. On a narrow terminal, filters reflow. Keyboard commands remain available
even when a button is beyond the horizontally scrollable action bar.

## Rewind a conversation

Select a session and press **W**, or click **Rewind…**. The picker lists its
exchanges and shows only your messages and final answers in a scrollable preview.
Search by words from either side of the conversation.

- **Keep through selected** keeps that entire exchange and removes all later exchanges
- **Remove from selected** removes that exchange and everything later
- The confirmation identifies the session, counts retained/removed exchanges,
  and shows the last retained and first removed input

An exchange is one Codex turn, which can contain multiple steered user messages.
The cutoff is before or after the whole exchange; it cannot split a single answer
or keep only part of a turn. Close LIVE sessions first, and restore archived sessions
before rewinding them. If the history changes after you open the picker, the action
is rejected and you must choose again.

The same session ID resumes with the retained conversation. Files already changed,
external actions, and existing global memories are unaffected. **Rewind is not
secure erasure or disk cleanup**: legacy sessions retain a rollback marker, and
paginated sessions may retain older rollout files. There is no undo button.

The manager delegates changes to the installed Codex app-server: `thread/revert`
for paginated sessions and `thread/rollback` for legacy sessions. The latter is
deprecated upstream. Unsupported versions report an error; the manager never
falls back to editing a resumable JSONL file. Legacy histories without reliable
turn boundaries or with multiple human inputs per turn are refused.

The retained turn IDs are verified after the operation. Reading paginated content
also checks Codex's effective turn list, because older SQLite projections can
still contain removed turns.

The one-shot commands remain available for scripting and diagnostics:

```bash
# Newest first, with two messages from each end
codex-man list

# Put the disk hogs first; 0 means no result limit
codex-man list --sort size --limit 0
codex-man stats

# Search names, IDs, first prompts, working directories, and source types
codex-man list --search website

# More edge context, or the complete user/final-only conversation
codex-man show SESSION --count 8
codex-man show SESSION --all

# Set the actual name Codex shows (not a manager-only alias)
codex-man rename SESSION "Website - checkout redesign"

# Reversible picker cleanup
codex-man archive SESSION
codex-man unarchive SESSION

# Permanent; asks you to type the complete UUID
codex-man delete SESSION
```

Replace `SESSION` with a full UUID, a unique UUID prefix, or a unique saved name.
Rewind currently uses the interactive picker; there is no one-shot rewind command.

## What the states mean

- `LIVE`: Codex currently holds the thread-writer lock. Close it in Codex first;
  the manager refuses archive, delete, export, rewind, and another resume
- `ACTIVE`: stored in the normal session inventory and available to resume.
- `ARCHIVED`: hidden from ordinary active lists, but still stored and restorable.
- `UNINDEXED`: a rollout file exists but the current SQLite index has no row for
  it. Inspect this before taking action.

`GIANT` means at least 1 GiB and `HUGE` means at least 100 MiB. `OLD` means the
session has not been used for at least 180 days. These are review flags, not an
automatic recommendation to delete.

Archive does **not** reclaim disk space. Current Codex archive/delete behavior
can include spawned descendant sessions, so read the target carefully.

Sizes report selected rollout files, not all storage associated with a session.
Databases, exports, and superseded history files are not included in these totals.

## Preserve the decisions, remove the payload bulk

Never hand-trim a resumable Codex JSONL file. Modern Codex also has SQLite
metadata and history offsets; rewriting JSONL can make resume/index state
inconsistent.

Instead, make a compact archive:

```bash
codex-man compact SESSION
```

This extracts readable human inputs and assistant final answers, records metadata and the original
SHA-256, and writes verified Markdown under
`~/.codex/compact_session_archives/`. Tool calls, tool results, reasoning,
commentary, environment context, and embedded objects are excluded.

The original remains resumable and unchanged. After reviewing the Markdown,
you can run normal `delete`, or deliberately combine the steps:

```bash
codex-man compact SESSION --delete-source
```

The combined form writes and verifies the compact archive first, then requires
the permanent-delete confirmation. The Markdown is historical reference, not a
resumable Codex session.

Exports never overwrite an existing file, including the original rollout. Default
filenames are unique. Verification compares the entire saved document with the
generated text. If extraction skips oversized records or finds malformed message
records, `--delete-source` refuses deletion and asks for manual review.

## Memory inventory and editing

The manager reads the memory directory under the selected Codex home, not a
separate store per repository. Cross-project entries are therefore expected. The memory
browser hides the evidence list in its default Overview so this global store
does not initially look like an undifferentiated file dump.

The Project / source column extracts `cwd:` from evidence summaries when present.
It is a provenance hint, not an isolation boundary. The app cannot show exactly
which memories influenced a particular answer.

```bash
codex-man memory list
codex-man memory show summary
codex-man memory show durable
codex-man memory show raw
```

The aliases map to:

- `summary` -> `~/.codex/memories/memory_summary.md`, the small cross-chat summary.
- `durable`/`registry` -> `MEMORY.md`, the searchable durable registry.
- `raw` -> `raw_memories.md`, extracted source material.
- `rollout_summaries/` -> evidence summaries behind registry entries.

The preferred way to correct stale or irrelevant memory is:

```bash
codex-man memory correct \
  "The old service endpoint is stale; use the checked-in deployment docs."
```

That creates a user-authored correction under
`memories/extensions/ad_hoc/notes/`. With no text, it opens `$VISUAL`, `$EDITOR`,
or `nano`.

Creating a note does not trigger or verify memory regeneration. This app records
the requested correction; when it is consumed depends on the Codex memory workflow.

Direct editing is available but deliberately explicit because Codex treats the
main files as generated state and may overwrite them:

```bash
codex-man memory edit durable --direct
```

The manager creates a timestamped backup before opening the editor. Relative
paths such as `rollout_summaries/example.md` are accepted but cannot escape the
memory directory.

Memory injection and generation are separate controls:

```bash
codex-man memory config
codex-man memory set use off
codex-man memory set generate off
codex-man memory set exclude-external on
```

Each config write preserves a timestamped backup if the config file already exists.
Use `/memories` inside an interactive Codex chat for per-chat controls.

- **Use in future chats** controls whether stored memory may be injected into
  later chats.
- **Learn from new chats** controls whether eligible new chats may become memory
  inputs. Turning it off does not delete existing memory.
- **Exclude web/MCP learning** prevents chats using external context from being
  used for future memory generation.
- **ON (default)** or **OFF (default)** means the setting is not explicit in
  `config.toml`; the UI shows the individual setting's built-in default. Use
  and Learn default ON, while Exclude web/MCP defaults OFF. Clicking the control
  writes an explicit ON or OFF.

These toggles do not enable the separate `[features] memories` flag. An ON label
for Use or Learn is not proof that memory generation is enabled. Check the
**Memory feature** value in the browser. OpenAI documents local memory as opt-in,
generated in the background, and distinct from ChatGPT web memory. Consult
[the official memory guide](https://learn.chatgpt.com/docs/customization/memories)
for enablement and current availability.

Official references:

- [Codex commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli): in-chat controls
- [Local memory](https://learn.chatgpt.com/docs/customization/memories): storage, generation, and settings
- [Codex app-server](https://learn.chatgpt.com/docs/app-server): native session operations

## Development

See [development](development.md) for tests, screenshot reproduction, and privacy
checks, and [the implementation review](../REVIEW.md) for known limitations.
