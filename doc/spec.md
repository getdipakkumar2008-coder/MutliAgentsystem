# Universal Agentic Application Development Specification

## 1. Purpose

This specification defines a reusable operating model for an AI-assisted software development system inspired by ECC.

The system should help developers and coding agents:

- Understand unfamiliar repositories
- Research before coding
- Plan complex work
- Delegate specialized tasks
- Enforce test-driven development
- Apply security and quality gates
- Persist useful memory
- Coordinate multiple agents
- Support multiple development harnesses
- Provide safe installation and lifecycle management
- Produce verifiable delivery evidence

## 2. Goals

### Primary Goals

- Improve correctness of generated code.
- Reduce repeated prompt engineering.
- Standardize development workflows.
- Make agent behavior observable and auditable.
- Preserve human approval for consequential actions.
- Reduce context-window waste.
- Encourage research before custom implementation.
- Detect security and quality issues early.
- Support repeatable cross-project adoption.

### Secondary Goals

- Support multiple programming languages.
- Support multiple AI coding tools.
- Allow selective installation.
- Enable project-specific customization.
- Provide reusable workflows and domain knowledge.
- Support local and self-hosted model configurations.

## 3. Non-Goals

The system must not:

- Replace human ownership of production decisions.
- Automatically deploy to production without approval.
- Automatically publish external content without approval.
- Treat generated text as trusted instructions.
- Guarantee that generated code is secure without verification.
- Claim that tests passed when they were not executed.
- Hide failed agents, failed validators, or incomplete review stages.
- Overwrite user configuration without ownership checks.

## 4. Core Components

### 4.1 Agents

Agents are specialized instruction sets for focused work.

Required agent categories:

- Repository explorer
- Researcher
- Planner
- Architect
- TDD implementer
- Build-error resolver
- Code reviewer
- Security reviewer
- Test analyst
- Documentation updater
- Refactoring specialist
- E2E tester
- Release validator
- Autonomous-loop operator

Each agent should define:

- Name
- Purpose
- Activation conditions
- Allowed tools
- Input contract
- Output contract
- Safety constraints
- Validation requirements
- Failure behavior

### 4.2 Skills

Skills are reusable workflows or domain-specific knowledge modules.

Example skill categories:

- TDD
- Security review
- API design
- Database migrations
- Frontend patterns
- Backend patterns
- Deployment
- Docker
- Research
- Documentation lookup
- Context management
- Memory management
- Evaluation
- Orchestration
- Language-specific development

Skills should be loaded on demand rather than inserted into every context.

### 4.3 Commands

Commands are convenient entry points for common workflows.

Recommended commands:

```text
/plan
/code-review
/build-fix
/security-scan
/test-coverage
/refactor-clean
/update-docs
/save-session
/resume-session
/learn
/evolve
/loop-start
/loop-status
/doctor
/repair
/uninstall
```

Commands should remain thin wrappers around canonical skills and scripts.

### 4.4 Rules

Rules define broad standards that should apply consistently.

Rule layers:

```text
common/
language/
framework/
project/
```

Common rules should cover:

- Coding style
- Testing
- Git workflow
- Security
- Error handling
- Performance
- Agent delegation
- Hook behavior
- Documentation

Specific rules may override common rules where language or framework idioms require it.

### 4.5 Hooks

Hooks are event-driven quality and lifecycle controls.

Supported lifecycle events should include:

- Pre-tool use
- Post-tool use
- Tool failure
- Session start
- Session stop
- Session end
- Before context compaction

Hooks may:

- Block an unsafe operation
- Emit a warning
- Run a focused validator
- Save session state
- Record a summary
- Detect quality issues
- Trigger background analysis

Hooks must distinguish blocking and non-blocking behavior.

### 4.6 Memory

Memory should provide a durable, inspectable knowledge layer.

Memory types:

- Decision
- Fact
- Lesson
- Context
- Preference
- Runbook
- Handoff
- Evaluation result

Each memory record should support:

```text
id
scope
kind
title
body
source
created_at
updated_at
related_files
related_sessions
confidence
```

Memory must be treated as untrusted context until validated against current repository state.

### 4.7 Installation System

The installation system should support:

- Profiles
- Modules
- Components
- Target adapters
- Dry runs
- JSON output
- Ownership tracking
- Drift detection
- Repair
- Upgrade
- Uninstall
- User-file preservation

Recommended profiles:

```text
minimal
core
developer
security
research
full
```

### 4.8 Orchestration

Orchestration should support:

- Sequential workflows
- Parallel investigation
- Review barriers
- Adversarial verification
- Bounded autonomous loops
- Worktree isolation
- Session tracking
- Human approval gates

## 5. Workflow Contracts

### 5.1 Plan Contract

Input:

```json
{
  "request": "string",
  "repository": "string",
  "constraints": ["string"],
  "approval_required": true
}
```

Output:

```json
{
  "requirements": [],
  "scope": [],
  "non_goals": [],
  "files": [],
  "phases": [],
  "risks": [],
  "validation": [],
  "acceptance": []
}
```

### 5.2 Review Contract

Input:

```json
{
  "diff": "unified diff",
  "language": "optional",
  "changed_files": []
}
```

Output:

```json
{
  "verdict": "APPROVE | CHANGES_REQUESTED",
  "incomplete": false,
  "blocking": [],
  "advisory": [],
  "stats": {
    "dimensions": 0,
    "failed": 0,
    "raw": 0,
    "unique": 0,
    "confirmed": 0,
    "unverified": 0,
    "refuted": 0
  }
}
```

### 5.3 Validation Contract

Every validation result should include:

```json
{
  "command": "string",
  "status": "passed | failed | skipped | unverified",
  "exit_code": 0,
  "summary": "string",
  "evidence": "string"
}
```

## 6. Quality Requirements

The system should enforce:

- Meaningful test coverage
- Explicit error handling
- Secure input validation
- No hardcoded secrets
- Reproducible commands
- Deterministic validation where possible
- Fresh-context code review
- Documentation updates
- Safe migration practices
- Clear failure reporting

## 7. Operational Requirements

The system should:

- Work on Linux, macOS, and Windows where practical.
- Respect the project's package manager.
- Avoid destructive commands by default.
- Provide dry-run support.
- Preserve user-owned files.
- Support environment-based configuration.
- Avoid echoing sensitive input.
- Produce human-readable and machine-readable output.
- Keep autonomous loops bounded by time, cost, and iteration limits.

## 8. Acceptance Criteria

The implementation is acceptable when:

- A new repository can be inspected systematically.
- A complex feature produces a grounded plan.
- The plan can be approved before implementation.
- New behavior is implemented using tests-first development.
- Failed checks are visible.
- Security review can block delivery.
- Agents can run independently without corrupting shared state.
- Sessions can preserve useful context.
- Installation can be previewed, applied, repaired, and removed safely.
- Delivery reports contain factual validation evidence.