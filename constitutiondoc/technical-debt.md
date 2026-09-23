# Technical Debt

## 1. Heuristic shell and write detection
`agentic/policy.py` identifies shell writes, destructive commands, and delivery operations using tokenization and regular expressions. This is intentionally practical but not complete. Heredocs, obfuscation, nested shell behavior, and unsupported command forms may evade detection.

**Impact:** safety coverage is best-effort; policy changes must favor conservative behavior and regression tests for bypasses.

## 2. Claude Code coupling
Hook registration and payload handling are shaped around Claude Code events and observed payload fields. Other IDEs or harnesses will require adapters and their own compatibility tests.

**Impact:** portability is a roadmap goal, not a current guarantee.

## 3. Local identity model
Approval identity uses the local OS username and optional string allowlists. There is no SSO, signed approval, role management, or independently verified identity provider.

**Impact:** appropriate for local developer use, insufficient for enterprise-grade non-repudiation or shared-host governance.

## 4. Self-attested review records
The agent writes `.agentic/review.json`, while the validator derives the verdict from its contents. This improves deterministic handling of findings but does not independently prove reviewer identity or completeness.

**Impact:** review is stronger than an informal claim but weaker than an independently orchestrated reviewer with authenticated provenance.

## 5. File-based state
JSON and JSONL are transparent and dependency-light, but they lack database transactions, locking, rich querying, and robust concurrent-writer semantics.

**Impact:** multi-agent or team-scale operation will require explicit locking, single-writer rules, or a database-backed state layer.

## 6. Documentation-to-implementation gap
The design documents describe a broader platform than the current Phase 1 implementation. Budgets, memory, profiles, repair, subagent definitions, orchestration, and evaluation features are described but incomplete or absent.

**Impact:** documentation must clearly distinguish implemented behavior from roadmap intent.

## 7. CI/CD maturity
No GitHub Actions workflow or deployment pipeline is present in the inspected tree. Tests and checks are primarily local commands recorded by hooks.

**Impact:** there is no repository-native automated regression gate unless external CI is configured.

## 8. Operational friction
The safety model intentionally blocks or prompts many normal-looking operations. This supports accountability but can slow development and create pressure to use warn/off modes.

**Impact:** usability improvements must not weaken hard integrity protections.

## 9. Future risk areas
Monitor:
- command-parser bypasses,
- changes to Claude Code payload formats,
- stale evidence and concurrent state changes,
- configuration tampering,
- expansion into autonomous loops without enforced budgets,
- growth of the state model without schema migration tooling.

## Debt policy
Technical debt in this repository should be handled as explicit, reversible work:
- reproduce security gaps with tests,
- document the limitation before changing behavior,
- preserve backward compatibility for existing hooks and state records,
- raise the change tier for policy, authentication, schema, or infrastructure changes,
- never trade away hard safety invariants for convenience.
