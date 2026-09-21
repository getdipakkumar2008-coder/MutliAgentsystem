# Universal Agentic Application Development Architecture

## 1. Architecture Overview

The system is organized as a reusable agentic engineering platform around a project repository.

```mermaid
flowchart TD
    User[Developer / Operator] --> Interface[CLI / IDE Plugin / Chat Interface]

    Interface --> Router[Command and Workflow Router]

    Router --> Discovery[Repository Discovery]
    Router --> Research[Research Engine]
    Router --> Planner[Planning Engine]
    Router --> Executor[Implementation Executor]
    Router --> Reviewer[Review Engine]
    Router --> Validator[Validation Engine]
    Router --> Memory[Memory and Session Store]

    Discovery --> Repo[Application Repository]
    Research --> Sources[Official Docs / Packages / MCP / GitHub]
    Planner --> PlanGate[Human Approval Gate]

    PlanGate --> Executor
    Executor --> Tools[File / Shell / Git / Test Tools]
    Tools --> Hooks[Pre/Post Tool Hooks]

    Hooks --> Safety[Security and Safety Guards]
    Hooks --> Quality[Quality Checks]
    Hooks --> Context[Context and Session Management]

    Executor --> Tests[Test Suite]
    Reviewer --> Security[Security Review]
    Reviewer --> CodeReview[Code Review]
    Reviewer --> TestReview[Test Coverage Review]

    Validator --> Tests
    Validator --> Build[Build and Type Checks]
    Validator --> Lint[Lint and Formatting]
    Validator --> Scan[Security and Dependency Scans]

    Reviewer --> ReviewGate[Delivery Approval Gate]
    Validator --> ReviewGate

    ReviewGate --> Delivery[PR / Release / Deployment]
    Delivery --> Memory
    Context --> Memory
```

## 2. Layered Architecture

```text
┌──────────────────────────────────────────────────────────┐
│                     User Interfaces                       │
│          CLI · IDE Plugin · Chat · Dashboard              │
├──────────────────────────────────────────────────────────┤
│                 Commands and Workflows                    │
│       plan · implement · review · verify · release        │
├──────────────────────────────────────────────────────────┤
│                    Agent Runtime                          │
│    routing · delegation · parallelism · barriers           │
├──────────────────────────────────────────────────────────┤
│                    Safety Layer                            │
│    approvals · trust boundaries · secret protection        │
├──────────────────────────────────────────────────────────┤
│                  Hook and Quality Layer                    │
│   pre-tool · post-tool · session · compaction · audits     │
├──────────────────────────────────────────────────────────┤
│                  Knowledge Layer                          │
│   agents · skills · rules · prompts · templates · schemas  │
├──────────────────────────────────────────────────────────┤
│                    State Layer                             │
│ sessions · memory · install state · work items · metrics  │
├──────────────────────────────────────────────────────────┤
│                  Project Integration Layer                 │
│ filesystem · git · package manager · tests · CI · MCP      │
└──────────────────────────────────────────────────────────┘
```

## 3. Main Runtime Flow

```mermaid
sequenceDiagram
    participant U as User
    participant R as Router
    participant D as Discovery
    participant P as Planner
    participant G as Approval Gate
    participant E as Executor
    participant H as Hooks
    participant V as Validator
    participant C as Reviewer
    participant M as Memory

    U->>R: Submit task
    R->>D: Inspect repository
    D-->>R: Repository evidence
    R->>P: Create grounded plan
    P-->>U: Requirements, risks, plan
    U->>G: Approve or modify plan
    G->>E: Begin implementation
    E->>H: Request tool operation
    H-->>E: Allow, warn, or block
    E->>V: Run focused validation
    V-->>E: Test and build results
    E->>C: Request fresh-context review
    C-->>G: Blocking and advisory findings
    G->>U: Request delivery approval
    U->>M: Preserve decisions and evidence
```

## 4. Repository-Centric Component Model

```text
project/
├── app/ or src/             Application implementation
├── tests/                   Unit, integration, and E2E tests
├── agents/                 Specialized agent instructions
├── skills/                 Reusable workflows and domain knowledge
├── commands/               User-facing workflow entry points
├── rules/                  General and stack-specific standards
├── hooks/                  Lifecycle and tool-use automation
├── scripts/                Installation, validation, maintenance, and CLI utilities
├── schemas/                Input, output, configuration, and state validation
├── manifests/              Profiles, modules, and install components
├── docs/                   Architecture, operations, security, and user documentation
├── examples/               Reference configurations and templates
└── .github/                CI, issue templates, PR workflows, and automation
```

## 5. Agent Execution Architecture

Agents should communicate through explicit contracts rather than free-form hidden state.

```mermaid
flowchart LR
    Task[Task Request] --> Coordinator[Coordinator]
    Coordinator --> Explorer[Explorer]
    Coordinator --> Researcher[Researcher]
    Coordinator --> Architect[Architect]

    Explorer --> Evidence[Evidence Packet]
    Researcher --> Evidence
    Architect --> Design[Design Recommendation]

    Evidence --> Planner[Planner]
    Design --> Planner
    Planner --> ApprovedPlan[Approved Plan]

    ApprovedPlan --> TDD[TDD Implementer]
    TDD --> BuildResolver[Build Resolver]
    TDD --> TestAnalyst[Test Analyst]

    TDD --> Diff[Working Diff]
    Diff --> QualityReviewer[Quality Reviewer]
    Diff --> LanguageReviewer[Language Reviewer]
    Diff --> SecurityReviewer[Security Reviewer]

    QualityReviewer --> Dedup[Finding Deduplication]
    LanguageReviewer --> Dedup
    SecurityReviewer --> Dedup

    Dedup --> Adversarial[Adversarial Verification]
    Adversarial --> FinalGate[Final Delivery Gate]
```

## 6. Trust and Security Boundaries

```mermaid
flowchart TD
    External[External Content] --> Boundary[Input Boundary]
    Boundary --> Validation[Schema / Format Validation]
    Validation --> Sanitization[Sanitization / Normalization]
    Sanitization --> Policy[Policy and Authorization Check]
    Policy --> Execution[Controlled Execution]

    Secrets[Secrets and Credentials] --> Vault[Environment / Secret Manager]
    Vault --> Runtime[Runtime Injection]
    Runtime --> Execution

    Execution --> Logs[Redacted Structured Logs]
    Execution --> Audit[Audit Trail]
```

External content includes:

- User-provided text
- Repository files
- GitHub issues and pull requests
- Diffs
- Retrieved web pages
- MCP responses
- Model output
- Memory records
- Generated plans

None of these should override system instructions or execute automatically without validation.

## 7. State and Memory Architecture

```mermaid
erDiagram
    SESSION ||--o{ EVENT : contains
    SESSION ||--o{ MEMORY_RECORD : produces
    SESSION ||--o{ VALIDATION_RESULT : records
    SESSION ||--o{ WORK_ITEM : tracks
    INSTALLATION ||--o{ MANAGED_FILE : owns

    SESSION {
        string id
        string project_id
        string branch
        string status
        datetime started_at
        datetime updated_at
    }

    EVENT {
        string id
        string session_id
        string type
        string payload
        datetime created_at
    }

    MEMORY_RECORD {
        string id
        string scope
        string kind
        string title
        string body
        string provenance
        float confidence
        datetime created_at
    }

    VALIDATION_RESULT {
        string id
        string session_id
        string command
        string status
        int exit_code
        string evidence
    }

    WORK_ITEM {
        string id
        string source
        string external_id
        string status
        string title
    }

    INSTALLATION {
        string id
        string target
        string profile
        string state
    }

    MANAGED_FILE {
        string path
        string owner
        string checksum
        string status
    }
```

## 8. Installation Architecture

```mermaid
flowchart TD
    Request[Install Request] --> Parser[Argument / Config Parser]
    Parser --> Resolver[Profile and Module Resolver]
    Resolver --> Target[Target Adapter]
    Target --> Planner[Install Plan]
    Planner --> DryRun{Dry Run?}

    DryRun -->|Yes| Preview[Print Plan / JSON]
    DryRun -->|No| Ownership[Ownership and Conflict Check]
    Ownership --> Apply[Apply File Operations]
    Apply --> State[Write Install State]
    State --> Health[Health Projection]
    Health --> Result[Install Result]
```

Installation principles:

- Resolve before mutating.
- Preview before applying.
- Track ownership.
- Preserve unrelated user files.
- Detect drift.
- Repair only managed files.
- Uninstall conservatively.
- Keep operations idempotent.

## 9. Hook Architecture

```mermaid
flowchart LR
    ToolRequest[Tool Request] --> Pre[PreToolUse]
    Pre --> Decision{Allow?}
    Decision -->|No| Block[Block with Reason]
    Decision -->|Yes| Tool[Execute Tool]
    Tool --> Post[PostToolUse]
    Post --> Checks[Focused Quality Checks]
    Checks --> Session[Session State]
    
    Start[Session Start] --> Restore[Restore Context]
    Compact[Pre-Compact] --> Save[Save State]
    Stop[Stop] --> Summary[Summary / Learning / Cost]
    End[Session End] --> Cleanup[Cleanup Marker]
```

Hooks should have:

- Stable identifiers
- Explicit matchers
- Timeout limits
- Profile controls
- Disabled-hook overrides
- Structured logs
- Safe failure behavior
- Independent tests

## 10. Validation and Delivery Architecture

```mermaid
flowchart TD
    Change[Code Change] --> Unit[Unit Tests]
    Change --> Integration[Integration Tests]
    Change --> E2E[E2E Tests]
    Change --> Types[Type Checks]
    Change --> Lint[Lint / Format]
    Change --> Security[Security Scan]
    Change --> Package[Build / Package]

    Unit --> Evidence[Validation Evidence]
    Integration --> Evidence
    E2E --> Evidence
    Types --> Evidence
    Lint --> Evidence
    Security --> Evidence
    Package --> Evidence

    Evidence --> Review[Fresh Context Review]
    Review --> Gate{Approval Gate}
    Gate -->|Approved| Deliver[PR / Release / Deploy]
    Gate -->|Rejected| Fix[Return to Implementation]
    Fix --> Change
```

## 11. Failure Handling

The architecture must fail safely.

Required behaviors:

- Failed agents are reported.
- Missing reviewers are marked unverified.
- Security failures block delivery.
- Invalid inputs fail before mutation.
- Partial installs record state and warnings.
- External action requires approval.
- Autonomous loops have time, cost, and iteration limits.
- Uncertain high-severity findings remain blocking.
- Unsupported platforms produce explicit warnings.
- Tests that cannot run are not reported as passing.

## 12. Recommended Deployment Modes

### Local Developer Mode

- CLI
- Local hooks
- Local memory
- Project-local configuration
- No external writes by default

### Team Mode

- Shared rules
- Shared skills
- CI validation
- Centralized documentation
- Optional shared memory and work-item integrations

### Enterprise Mode

- Managed installation
- Stronger audit logging
- Secret manager integration
- Policy enforcement
- Approval workflows
- Isolated execution
- Cost and usage reporting

## 13. Architectural Principles

1. The repository is the source of truth.
2. Skills are canonical; commands are convenience wrappers.
3. Plans precede complex implementation.
4. Tests provide behavioral evidence.
5. Reviews happen from a fresh context.
6. Security checks fail closed.
7. User-owned configuration is preserved.
8. External actions require approval.
9. Memory is durable but untrusted.
10. Autonomous work is bounded and observable.
11. Adapters should reuse core workflows instead of copying them.
12. Every important operation should support preview, validation, and recovery.