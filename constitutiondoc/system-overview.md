# System Overview

## Scope
`getdipakkumar2008-coder/MutliAgentsystem` is a Python-based agentic engineering platform, not a conventional web or mobile application. It provides CLI commands, Claude Code hooks, policy enforcement, approval gates, validation evidence, secret scanning, and audit logging around AI-assisted repository changes.

## Technology inventory

| Area | Finding | Evidence |
|---|---|---|
| Frontend | No browser or GUI frontend. The interface is CLI- and prompt-driven. | `scripts/agentic.py`, `agentic/cli.py`, `.claude/settings.json` |
| Backend | Python package implementing CLI, hooks, policy, validation, installation, doctor checks, storage, and secret scanning. | `agentic/` |
| Database | No relational or hosted database. State is stored as JSON and JSONL under `.agentic/`; git supplies commit and working-tree state. | `agentic/store.py` |
| APIs | No HTTP or public service API. Integration is through CLI commands, Claude Code hook events, and JSON-schema contracts. | `agentic/hooks.py`, `schemas/` |
| Infrastructure | Local Python runtime, project-local `.agentic/` state, Claude Code hook configuration, filesystem, and git. | `.agentic/`, `.claude/settings.json`, `requirements.txt` |
| CI/CD | No `.github/workflows/` or deployment pipeline is present in the inspected tree. Validation is primarily local and command-driven. | repository tree, `.agentic/config.json` |
| Testing | Python standard-library `unittest`; validation command is `python -m unittest discover -s tests`. | `tests/`, `README.md`, `.agentic/config.json` |
| Authentication | No application authentication. Approval identity is the local OS user via `getpass.getuser()` and optional approver allowlists. | `agentic/hooks.py`, `agentic/store.py` |

## Important dependencies
- `jsonschema>=4.18` is the only external dependency in `requirements.txt`.
- The remainder uses Python standard-library modules.
- Internal dependencies of greatest importance are `policy.py`, `hooks.py`, `validate.py`, and `store.py`.

## Architectural patterns
- Layered separation between CLI/hooks, pure policy, validation, and persistence.
- Fail-closed enforcement for protected paths, malformed configuration, dangerous operations, and missing approvals.
- Human-in-the-loop governance through G1 plan approval and G2 delivery approval.
- Schema-first contracts for plans, reviews, approvals, validations, and events.
- Git-centric delivery gating using plan hashes, HEAD, and clean-tree checks.
- Local-first, repository-centric persistence with JSON artifacts and an append-only event log.

## Technical debt and legacy
The repository is a Phase 1 implementation of a broader agentic platform. Known debt includes heuristic shell parsing, Claude Code-specific payload assumptions, local-only identity, self-attested review records, file-based state without database transactions, and documented but unimplemented features such as budgets, memory workflows, profiles, repair, and full multi-agent orchestration.

The `doc/` files are living design and roadmap artifacts. They describe a broader target architecture than the currently implemented runtime, so documentation and implementation should be treated as staged rather than fully equivalent.

## Backward compatibility requirements
- Preserve existing user entries in `.claude/settings.json` during installation.
- Keep `.agentic/` state project-local and isolated.
- Do not install into the home directory or shared global Claude configuration.
- Keep install/uninstall idempotent and conservative.
- Preserve approval binding to the exact `plan_hash`.
- Keep validation evidence tied to the relevant git HEAD and dirty-tree state.
- Do not silently weaken protected-path, secret, or delivery-gate behavior.

## Summary
This repository is best understood as a local control plane for safe AI-assisted software engineering. It has no traditional frontend, service backend, application database, or remote API; its core product is policy, evidence, approvals, and enforcement around repository changes.
