# Security

This tool can inspect private conversations and change local Codex state. Treat
the installed source and dependencies as trusted code, and back up important
history before destructive operations.

## Report a vulnerability privately

Use the repository's **Security → Report a vulnerability** option when available.
Do not post credentials, raw sessions, memories, or exploitable private details in
a public issue. If private reporting is unavailable, open an issue requesting a
private contact channel without including the vulnerability details.

Include the affected version, a minimal synthetic reproduction, and the expected
security boundary. Never upload your whole Codex home. Only the latest version
is maintained; fixes are not backported to older releases.

## Review contributed code before running it

Anyone can propose a change in a fork. A pull request is not an endorsed release.
Do not install an unreviewed fork or run its tests against your real Codex home.
Approve fork workflows only after inspecting the code and workflow changes.

The CODEOWNERS file requests maintainer review for every file, including itself.
Server-side repository rules are needed to enforce reviews; the file alone does
not block a merge. CI uses GitHub-hosted runners, read-only repository permissions,
SHA-pinned actions, and a checksum-verified secret scanner. It does not deploy or
publish packages, and passing tests does not prove that code is harmless.

The standalone launcher uses `codex_session_manager.py.lock`; development uses
`uv.lock`. Both record dependency versions and artifact hashes. Run `install.py`
after upgrading so symlinked commands have the companion lock link. Do not ignore
a warning from `uv` that a lockfile is missing. A lock makes downloads repeatable;
it does not prove a dependency is free of vulnerabilities or malicious code.

Repository controls cannot prevent a compromised owner account from changing
settings. Maintainers should enable passkeys or security-key-backed two-factor
authentication, keep recovery codes offline, and review authorized apps, tokens,
and SSH keys. Use repository-scoped credentials for automation and never give
untrusted code an owner token.
