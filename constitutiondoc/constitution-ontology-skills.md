# Constitution, Ontology, and Skills

## Purpose

This document explains how the constitution, ontology, and skills relate to one another in the MutliAgentSystem project.

Together, they provide three different forms of control:

1. **Constitution** — defines authority, safety, and non-negotiable rules.
2. **Ontology** — defines the concepts, entities, roles, relationships, and vocabulary used by the platform.
3. **Skills** — define reusable procedures for performing engineering work.

They must not be treated as interchangeable. A skill may explain how to perform an operation, but it cannot grant permission to perform that operation. The ontology may describe an approval, plan, agent, or validation, but it does not decide whether an action is allowed. The constitution provides the governing constraints under which the ontology and skills operate.

## 1. Constitution

The constitution is the highest-level governance document for the platform. It defines principles and invariants that must remain true regardless of which agent, skill, repository, model, or tool is being used.

The current constitutional material is documented in:

- `constitutiondoc/constitution.md`
- `constitutiondoc/constraints.md`
- `constitutiondoc/system-overview.md`
- `doc/master.md`

The constitution defines:

- human authority over consequential actions;
- required plan and delivery approvals;
- protected paths;
- least-privilege rules;
- fail-closed behavior;
- secret protection;
- validation and evidence requirements;
- independent review;
- backward compatibility requirements;
- safe installation and uninstallation;
- honest reporting of limitations.

For example, it requires T2/T3 plan approval, binds approval to the exact `plan_hash`, prevents writes outside approved scope, protects secrets, and rejects missing or invalid evidence.

The constitution answers:

> Is this action permitted, and under what conditions?

It does not primarily describe the detailed steps for completing every task.

## 2. Ontology

The ontology is the conceptual model of the platform. It defines the important objects, roles, states, relationships, and meanings used by agents, skills, hooks, validators, schemas, and documentation.

Important platform concepts include:

| Concept | Meaning |
|---|---|
| Agent | A specialized actor that performs or reviews engineering work |
| Skill | A reusable workflow or domain-knowledge module |
| Command | A user-facing entry point for starting a workflow |
| Plan | A structured description of intended work |
| Plan hash | An identifier binding approvals to a specific plan |
| Approval | Human authorization for a defined action or scope |
| Validation | Evidence that a command or check was actually executed |
| Review | An independent assessment of a proposed change |
| Event | An append-oriented record of a significant platform action |
| Evidence | Recorded support for a claim, decision, or result |
| Protected path | A file or directory that agents may not modify |
| Delivery action | An externally visible action such as push, publish, merge, or deploy |

The ontology describes relationships such as:

```text
User requests Task
Task produces Plan
Plan may require Approval
Approval is bound to Plan Hash
Agent executes Plan
Agent uses Skill
Hooks control Tool Operation
Validation produces Evidence
Reviewer evaluates Work
Delivery Action requires Delivery Approval
Events record significant transitions
```

In this project, the ontology does not need to be a database or a separate class hierarchy. It may be represented through JSON schemas, policy decisions, CLI commands, hook payloads, approval records, validation records, event records, and documentation.

The ontology answers:

> What concepts exist, and how are they related?

## 3. Skills

A skill is a reusable workflow or domain-specific knowledge module. Skills are loaded on demand rather than inserted into every agent context.

Examples include:

- TDD;
- security review;
- API design;
- database migration;
- documentation lookup;
- research;
- context and memory management;
- orchestration;
- language-specific development.

A skill should define:

- purpose;
- activation conditions;
- required inputs;
- expected outputs;
- workflow steps;
- allowed tools;
- validation requirements;
- safety constraints;
- failure behavior;
- relevant ontology concepts.

A TDD skill, for example, may instruct an agent to inspect existing tests, write a failing test, implement the smallest change, run focused and broad tests, and report failures honestly.

The skill defines the procedure. The constitution still controls whether the agent may modify files, install dependencies, change protected configuration, push, publish, or perform another consequential action.

The skill answers:

> How should this task be performed?

## 4. How They Relate

The relationship can be summarized as:

```text
Constitution
    ↓ governs
Ontology
    ↓ structures
Skills
    ↓ guide
Agent execution
    ↓ produces
Plans, changes, reviews, validations, and evidence
```

This is a separation of concerns, not a permission chain.

### Constitution governs the ontology

The constitution protects the meaning and integrity of important concepts. For example:

- approvals must remain bound to `plan_hash`;
- validation status must remain truthful;
- protected paths must remain protected;
- events must not expose secrets;
- delivery must not proceed without required evidence.

### Ontology organizes skills

The ontology gives skills a shared vocabulary. A security-review skill should use consistent meanings for findings, severity, evidence, validation, review, approval, protected paths, and delivery scope.

### Skills operationalize the ontology

Skills turn concepts into procedures. A validation skill runs required commands and records results. A review skill requests an independent assessment. A delivery skill verifies the delivery gates before requesting G2 approval.

## 5. Execution Order

Agents should apply the layers in this order:

### Step 1: Apply the constitution

Determine whether the action is allowed, whether it affects protected paths, whether it is destructive or externally visible, and whether approval is required.

### Step 2: Interpret the ontology

Identify whether the work involves a plan, review, validation, approval, evidence, or delivery action. Determine the required scope and records.

### Step 3: Select and execute skills

Choose the smallest appropriate skill or set of skills, such as planning, implementation, testing, security review, or documentation.

### Step 4: Produce structured results

The skill should produce plans, changes, reviews, validations, evidence, events, approval requests, and final reports using the project’s shared terminology and schemas.

### Step 5: Reapply the constitution

Before consequential execution, verify that the result still satisfies constitutional rules. A new risk, changed scope, changed plan, or changed repository state may require renewed approval.

## 6. Example: Adding a Feature

For a new feature:

1. The constitution requires repository inspection, approved scope, tests, and appropriate review and approval.
2. The ontology identifies the task, plan, plan hash, agent, skill, change, validation evidence, review, and possible delivery action.
3. The agent loads repository-exploration, planning, TDD, security-review, and documentation skills as needed.
4. The result records the plan, scope, skills used, validation commands and results, review status, and delivery status.

A skill may say that a completed branch should be pushed, but that instruction does not authorize a push. Policy and approval requirements still apply.

## 7. Design Rules

1. **Keep governance separate from procedure.** Constitutional rules belong in the constitution and policy layer; procedural instructions belong in skills.
2. **Use ontology terms consistently.** Schemas, code, documentation, hooks, and skills should use the same meanings for plan, approval, validation, review, evidence, scope, delivery, and event.
3. **Keep skills composable.** Skills should work together without redefining core concepts.
4. **Keep skills bounded.** Every skill should state what it may change, which tools it may use, required validation, and failure behavior.
5. **Loading a skill is not authorization.** Skill content is guidance, not permission.
6. **Treat governance changes as high risk.** Changes to the constitution, ontology, schemas, policy rules, hooks, or approval semantics require an explicit plan, compatibility and security analysis, regression tests, independent review, and rollback documentation.

## 8. Recommended Structure

As the platform evolves, the concepts may be organized as follows:

```text
constitutiondoc/
├── constitution.md
├── constraints.md
├── system-overview.md
├── constitution-ontology-skills.md
└── ontology.md

skills/
├── planning/
├── tdd/
├── security-review/
├── documentation/
└── delivery-validation/

schemas/
├── plan.schema.json
├── approval.schema.json
├── review.schema.json
├── validation.schema.json
└── event.schema.json
```

The constitution remains the authoritative source for governance. The ontology explains meanings and relationships. Skills implement repeatable procedures without weakening either layer.

## 9. Summary

| Layer | Main question | Primary responsibility |
|---|---|---|
| Constitution | What must always be true? | Governance rules and invariants |
| Ontology | What concepts exist and how are they related? | Shared vocabulary and relationships |
| Skill | How should a task be performed? | Reusable workflow and domain guidance |

The correct relationship is:

```text
Constitution sets boundaries.
Ontology defines meaning.
Skills provide procedures.
Policy enforces boundaries.
Agents execute skills.
Schemas and events preserve structured evidence.
```

In short:

> The constitution governs behavior, the ontology explains the system, and skills teach agents how to work within that governed system.
