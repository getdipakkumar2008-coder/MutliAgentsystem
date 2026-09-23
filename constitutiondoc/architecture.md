# Architecture

## Overview
The system is a repository-centric control plane composed of a Python runtime, Claude Code hooks, a policy engine, structured validation records, and human approval gates.

## Layers

1. **Interface layer**
   - `scripts/agentic.py` launcher
   - `agentic/cli.py` command-line interface
   - human prompt commands such as `/approve G1` and `/approve G2`
   - Claude Code lifecycle/tool events

2. **Control layer**
   - `agentic/hooks.py` dispatches hook events and applies enforcement.
   - `agentic/validate.py` validates schemas, hashes, reviews, and approvals.
   - `agentic/doctor.py` performs health checks.

3. **Policy layer**
   - `agentic/policy.py` contains pure, testable decisions for file writes, shell commands, plan tiers, approval state, and delivery scope.

4. **State layer**
   - `agentic/store.py` manages project root discovery, JSON records, redacted events, and git state.
   - `.agentic/` stores configuration, plans, approvals, validations, evidence, and audit events.

5. **Integration layer**
   - filesystem and git
   - Claude Code settings and hook payloads
   - Python command execution

## Runtime flow

1. The user or coding agent starts a session.
2. `SessionStart` reports enforcement and plan state.
3. `PreToolUse` inspects writes and Bash commands.
4. Policy checks scope, protected paths, secrets, destructive patterns, package installation, and delivery commands.
5. Allowed tools execute; `PostToolUse` or `PostToolUseFailure` records matching validation evidence.
6. `UserPromptSubmit` handles human approval and denial commands.
7. G2 approval checks review, validations, current HEAD, clean tree, and requested delivery scope.
8. Delivery commands such as push, publish, PR creation, or deployment are allowed only when the corresponding G2 scope is valid.

## State model
The runtime uses these records:
- `.agentic/config.json` – human-editable policy configuration
- `.agentic/plan.json` – active sealed plan
- `.agentic/plans/*.json` – plan history
- `.agentic/review.json` – latest review record
- `.agentic/approvals/*.json` – G1/G2 decisions
- `.agentic/validations/*.json` – validation contracts
- `.agentic/evidence/*.txt` – redacted command output
- `.agentic/events.jsonl` – append-only redacted audit log

## Trust boundaries
Repository text, model output, tool output, web content, issue/PR content, diffs, and memory are treated as data rather than authority. The enforcement boundary validates records, protects configuration, redacts secrets, and requires human approval for consequential actions.

## Installation architecture
`agentic/install.py` follows a resolve/preview/apply model:
- read current settings,
- merge managed hooks without removing user hooks,
- support dry-run output,
- create only managed state and command files,
- record managed-file hashes,
- uninstall only files and hook entries recognized as managed.

## Failure behavior
- Pre-tool enforcement fails closed if the guard cannot run.
- Invalid or stale plans block writes.
- Missing or invalid approvals block T2/T3 work and delivery.
- Unverified or failed validation cannot satisfy G2.
- Protected paths and force-push/destructive patterns remain hard-blocked.
- Non-critical post hooks report errors without taking down the harness.

## Architectural principles
- Policy decisions should remain pure and unit-testable.
- Side effects belong in explicit boundary modules.
- Human approval must precede externally visible or irreversible actions.
- Evidence must be bound to the repository state that produced it.
- User-owned configuration must be preserved.
- The implementation should remain local-first until a stronger shared-state model is deliberately introduced.
