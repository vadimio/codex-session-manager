# Development

The repository contains application code, tests, documentation, and synthetic screenshot fixtures. Keep real Codex sessions, memories, databases, logs, credentials, and conversation exports outside Git.

## Run the checks

From the repository root:

```bash
uv run --locked pytest -q
uv run --locked ruff check .
uv lock --script codex_session_manager.py --check
python3 scripts/check_repository.py
```

The optional native-Codex tests create synthetic histories in isolated temporary homes. They test rewind and restarted history reads without model generation or changes to real sessions:

```bash
CODEX_MAN_INTEGRATION=1 uv run --locked pytest -q
```

CI tests Python 3.11 and 3.13. Native-Codex tests are opt-in because CI has no installed Codex. Backend modules use the `session_` prefix; terminal UI modules use `ui_`. See [the implementation review](../REVIEW.md) for current limitations and earlier findings.

## Reproduce the screenshots

```bash
uv run --locked python scripts/screenshots.py
```

This runs the real Textual app at 150 columns by 40 rows and saves four SVG screenshots under `docs/screenshots/`. GitHub can display the SVGs directly, and their text remains sharp when enlarged.

All names, paths, messages, memory files, session states, and sizes are fictional. The script uses an isolated temporary directory, fixes dates and the display timezone, and blocks subprocess launches. It never reads the user's Codex home, calls Codex, or creates the large payload files represented by the demo sizes. Only rendered screenshots are retained.

Review all four images after changing the UI or fixtures. Do not replace them with screenshots of real sessions, even if only the visible text appears harmless.

## Report a problem

Include the `codex-man --version` and `codex --version` output, Linux distribution, terminal size, and a minimal reproduction. Remove private prompts, paths, IDs, and credentials from screenshots and error messages. Do not upload a whole Codex home or raw session file.

## Before a public release

- Check that license descriptions match the actual terms: business use is allowed, but sale or resale of the software requires written permission
- Review the full Git history, not only the latest files, for credentials, private conversations, personal paths, and linked private projects
- Check README links, installation from a fresh checkout, tests, and all screenshots
- Confirm supported Codex versions and describe untested platforms honestly
- Change repository visibility only after the owner approves publication

Do not rewrite history or publish runtime data as part of documentation work.

See the [contribution guide](../CONTRIBUTING.md) for submitting changes and the
[repository protection policy](repository-security.md) for the branch, tag, and
workflow settings maintainers must apply and verify on GitHub.
