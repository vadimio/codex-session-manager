# Repository protection policy

The JSON files in `.github/rulesets/` describe the intended GitHub rules. Checking
them into Git does not activate them. An administrator must apply them and read
the effective server-side rules back before calling the repository protected.

## Main branch

`main-integrity` applies to the default branch with no bypass actors. It requires
a pull request, resolved review conversations, linear history, and current passing
`test (3.11)`, `test (3.13)`, and `security` checks from the GitHub Actions app.
It blocks force pushes and branch deletion, including for the owner.

`owner-approval` limits updates to the administrator and requires code-owner
review. Its administrator exception works only through pull requests. This is
necessary for a solo maintainer: GitHub does not let an author approve their own
pull request. The owner must review and deliberately merge it; they cannot use
that exception to skip the separate integrity rules or push directly to main.

The owner of this personal repository is its administrator. Adding new write
access, changing ownership, or moving to an organization requires another access
review. Do not grant an automation token administrator privileges merely to
make protected-branch pushes work.

## Tags and workflow execution

`tag-creation` reserves new tags for the administrator. `tag-integrity` prevents
existing tags from being updated or deleted, with no bypass actors. These rules
protect Git refs, not every editable field or asset in a GitHub Release.

Required repository settings:

- Allow only the exact checkout and setup-uv action SHAs used in `tests.yml`; require full SHA pinning
- Give Actions read-only default permissions and prohibit workflow approval of pull requests
- Require approval for workflows from **all external contributors**, not just first-time contributors
- Disable automatic merging; use squash merges
- Enable vulnerability alerts, secret scanning, push protection, and private vulnerability reporting where available
- Keep Actions secrets, write-capable deploy keys, self-hosted runners, and deployment workflows absent unless separately reviewed

When updating an action, review its code and publisher, update the repository's
allowlist, and update the pinned SHA in the workflow. Do not permit all marketplace
actions to avoid this step. Do not execute untrusted pull-request code in a
`pull_request_target` workflow.

## Verification and limits

Read the actual rules under GitHub **Settings → Rules → Rulesets**, the effective
rules for `main`, Actions policy, collaborators, deploy keys, and webhooks. Check
that required status-check names and their app IDs match a successful run.

Rules do not prevent the owner from editing those rules. Owner credentials,
authorized GitHub Apps, SSH keys, and tokens remain part of the trust boundary.
Use a passkey or security key, review account access regularly, and keep recovery
codes offline. CI and scanners are additional checks, not a substitute for review.

On the current GitHub plan, branch rules and external-fork approvals cannot be
activated while this repository is private. Publication must be followed by
applying and verifying these settings; no outside write access should be granted
during that transition.

References: [GitHub rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets),
[fork workflow approvals](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/approve-runs-from-forks).
