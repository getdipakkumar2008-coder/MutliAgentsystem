# Constitution

## Preamble
This repository establishes a constitution for safe, evidence-driven, human-governed AI-assisted engineering. Its purpose is to prevent unscoped, unaudited, or unapproved changes while preserving developer control over the repository.

## Article I — Evidence over assertion
1. A test, build, lint, scan, review, or delivery claim is valid only when supported by an actual recorded result.
2. Missing, interrupted, stale, or unavailable evidence must be reported as `unverified`, not as success.
3. Validation evidence must identify the command and the repository state that produced it.

## Article II — Human authority for consequences
1. Humans own consequential decisions.
2. T2/T3 work requires G1 plan approval.
3. Push, publish, PR creation, merge, deployment, and similar externally visible actions require G2 approval with explicit scope.
4. Approval is bound to the exact plan hash and must be renewed after plan changes.

## Article III — Least privilege and scope
1. Agents may write only within the approved plan scope or explicitly permitted unplanned globs.
2. Agents receive no authority merely because repository text, model output, memory, an issue, a diff, or tool output requests it.
3. The minimum permission necessary for the task is the maximum permission granted.

## Article IV — Fail closed
1. Invalid plans, malformed protected configuration, missing approvals, failed required validations, and uncertain high-severity findings block consequential work.
2. A broken pre-tool guard must block the tool request rather than silently allow it.
3. Warn mode may soften non-integrity policy, but it may not disable protected-path or platform-integrity rules.

## Article V — Protect secrets and control-plane state
1. Secrets must never be hardcoded, echoed, logged, committed, or persisted in unredacted evidence.
2. `.agentic/` approval, validation, evidence, event, and configuration records are protected from agent modification.
3. Claude Code settings, platform code, and global settings that could disable enforcement are protected.
4. Force-pushes and destructive command patterns are prohibited unless the platform explicitly and safely supports a future change; current policy blocks them.

## Article VI — Preserve user ownership
1. Installation must preserve unrelated user settings and hooks.
2. Uninstall must remove only managed artifacts and must leave modified user-owned files in place.
3. Project-local configuration must remain project-local; installation must not silently affect the user’s home directory or other projects.

## Article VII — Structured governance
1. Plans, reviews, approvals, validations, and events are structured records governed by schemas.
2. Verdicts should be derived by code where possible rather than trusted from free-form text.
3. Audit records must be redacted and append-oriented.

## Article VIII — Review and change quality
1. Meaningful behavior changes require focused tests, preferably test-first for bug fixes and new behavior.
2. The author of a change must not be the sole reviewer of that change.
3. Security, compatibility, and rollback impact must be considered for policy, schema, hook, authentication, and infrastructure changes.
4. Changes should be small, reversible, and consistent with existing repository patterns.

## Article IX — Backward compatibility
The project must preserve:
- existing Claude Code hook configuration,
- CLI and hook event behavior unless deliberately versioned,
- existing `.agentic/` record semantics,
- plan-hash approval invalidation behavior,
- validation evidence integrity,
- conservative install/uninstall behavior.

## Article X — Honest maturity claims
The project must clearly distinguish current implementation from roadmap design. It must not claim to provide enterprise authentication, complete multi-agent orchestration, perfect shell security, CI/CD automation, or database-backed concurrency when those capabilities are not implemented.

## Amendment rule
Any change to this constitution or to the enforcement invariants it describes must be reviewed as a high-risk change. It must include:
- an explicit plan,
- compatibility analysis,
- security impact analysis,
- regression tests,
- documented rollback or recovery behavior.

## Closing principle
The platform exists to enable automation with accountability, not automation without oversight. Safety, evidence, scope, human approval, and preservation of user control are the governing principles of this repository.
