# Constraints

## Product constraints
- This is a local engineering-control platform, not a web application.
- There is no frontend framework, HTTP server, hosted database, or remote API implementation.
- The primary interface is a Python CLI plus Claude Code hooks.

## Runtime constraints
- Python is the only implementation language identified in the repository.
- `jsonschema` is the only external package declared in `requirements.txt`.
- Git is required for reliable HEAD and working-tree checks used by delivery gates.
- State is persisted as files under `.agentic/`; there is no transaction-capable database.
- Hook behavior depends on the Claude Code event and payload contract.

## Safety constraints
The following are protected from agent writes:
- `.agentic/config.json`
- `.agentic/approvals/**`
- `.agentic/validations/**`
- `.agentic/evidence/**`
- `.agentic/events.jsonl`
- `.claude/settings.json`
- `.claude/settings.local.json`

The platform also protects its own `agentic/` and `scripts/` code from outside-project modification and rejects installation into the home directory.

## Approval constraints
- T2 and T3 plans require G1 approval.
- Delivery actions require G2 approval with explicit scope.
- Approval is bound to `plan_hash`.
- A changed plan or changed HEAD invalidates the prior decision.
- G2 requires an acceptable review, current successful validations, a clean tree, and matching delivery scope.

## Security constraints
- Secret values must not be logged, committed, or included in evidence unredacted.
- Destructive command patterns, force-pushes, hook forgery, and writes to protected state are blocked.
- Warn mode may relax soft policy decisions but must not relax integrity protections.

## Compatibility constraints
- Existing user Claude settings and hooks must be preserved.
- Installation and uninstallation must be idempotent and conservative.
- Project-local state must not become global state.
- Existing CLI and hook event names should remain stable unless a migration plan is provided.
- Validation status semantics (`passed`, `failed`, `skipped`, `unverified`) must remain truthful.

## Known practical constraints
- Shell parsing is heuristic and cannot guarantee detection of every obfuscated or indirect write.
- Local OS identity is not equivalent to enterprise authentication.
- File-based records do not provide multi-writer transactions.
- The current repository does not contain CI/CD workflows, so local validation is the primary evidence path.
- Several documented roadmap capabilities are not implemented yet: budgets, memory lifecycle, profiles, repair, evaluation harness, and full multi-agent orchestration.
