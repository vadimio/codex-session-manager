# Review — 2026-09-07

The tool had a usable terminal interface, but the previous eight tests did not
cover the operations most likely to damage or misrepresent a session. The largest
risks were silent history failures, stale writer-state checks, and weak export
verification. Adding rewind also exposed stale SQLite history after a native revert.

## UX

| Finding | Implemented change |
|---|---|
| No way to choose where a conversation should end | Searchable rewind picker with scrollable user/final-only preview, explicit before/after choices, and retained/removed counts |
| “Compact” suggests the source becomes smaller | Main button renamed Export; confirmation explains that the original stays |
| Memory help/full-file buttons look selected by default | Neutral navigation buttons |
| Memory search misses the displayed project column | Search includes project/source text |
| Name sorting is backwards | Names default to A–Z and the direction indicator follows the actual sort |
| Large summaries can block keyboard input | Summary reading runs in a worker; rapid selection changes debounce previews |
| Confirmations can clip their buttons in short terminals | Confirmation body scrolls while action buttons remain reachable |
| Runtime failures need clear outcomes | Missing/corrupt history and invalid configuration produce errors instead of empty results or invented defaults |

## Functionality

| Finding | Implemented change |
|---|---|
| Paginated projections retain removed turns | Filter conversation reads against Codex's effective turn IDs |
| Legacy viewers ignore rollback markers | Apply rollback markers during full reconstruction; label large file-edge previews approximate and suppress endpoints when a rollback appears in the tail |
| Repeated user messages disappear | Preserve legitimate repetitions and prefer response/event records per turn |
| Explicitly marked event commentary can leak into conversation | Filter it out |
| Export can overwrite any supplied path, even the source | Atomic create-if-absent; unique default output names |
| Export verification checks only two strings | Compare the full saved document and reject changed-source or incomplete export-then-delete paths |
| Destructive operations trust the inventory's old LIVE flag | Recheck writer locks before acting and after confirmations |
| Cancelling an async worker does not stop its underlying mutation thread | Serialize UI mutations and block ordinary quit/resume during an operation |
| Resume can silently fall back to the launch directory | Refuse missing saved project directories; also refuse already-LIVE sessions |
| Invalid TOML looks like default memory settings | Show the error, disable toggles, validate edited TOML before writing |
| Backup names can collide within one second | Include microseconds; preserve existing file permissions on atomic replacement |
| State statistics overlap | Count each displayed state once |

## Code and delivery

| Finding | Implemented change |
|---|---|
| Two roughly 1,600-line files mix unrelated responsibilities | Separate inventory, history, actions, memory, parsing, RPC, rewind, UI screens, and styles; source modules stay below 500 lines |
| Blocking `readline()` can outlive the RPC timeout; stderr can fill its pipe | Buffered nonblocking reads, stderr draining, response-size limit, explicit deadlines, process cleanup, and rejection of unsolicited approval requests |
| Local launcher setup is manual | Idempotent `install.py` refuses to replace an unrelated executable |
| Dependencies and lint depend on the surrounding workspace | Repository-owned configuration and `uv.lock`; CI uses the lockfile |
| CI misses newly added test files and only checks two source files | Discover the complete suite, lint all modules, and test Python 3.11/3.13 |

Validation includes the existing UI navigation/scrolling test, rewind selection
and cancellation, writer locks, export path protection, malformed configuration,
legacy rollback/repetition, fragmented RPC responses, timeouts, and disposable
installed-Codex integration tests for legacy and paginated rewind, including
rewinding to an empty conversation and checking it after an app-server restart.

## Remaining limitations

- Rewind operates at whole-exchange boundaries. It does not undo workspace changes,
  external effects, or learned memories, and it does not erase older physical files.
- Legacy rollback is deprecated upstream. Ambiguous legacy boundaries are rejected.
- Large legacy file-edge previews are approximate; use Full conversation for
  reconstructed history. A full legacy scan still takes time proportional to file size.
- Full conversation currently mounts every meaningful message; very long textual
  chats need incremental rendering. The rewind picker supports search, but the
  general full-conversation and full-memory viewers still lack in-document search.
- Inventory sizes describe the selected rollout files, not all bytes retained by
  Codex across SQLite, backups, exports, or superseded rollout segments. A dedicated
  storage audit remains necessary before claiming disk space reclaimed.
- The reader still depends on Codex's local SQLite schema and installed app-server
  protocol. Version errors are surfaced; future Codex releases can require updates.
