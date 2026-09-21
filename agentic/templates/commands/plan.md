---
description: Discover, research and produce a sealed plan, then stop at the approval gate
argument-hint: <what to build or fix>
---
Request: $ARGUMENTS

Follow the master workflow (master.md, if present in this repo) up to the plan gate:

1. **Discover** the repository first. Report concrete paths, commands and existing patterns to mirror.
2. **Research** before adding any dependency or utility (adopt / extend / compose / build).
3. **Plan.** Propose a tier (T0-T3) and create the sealed plan with:
   `{{AGENTIC}} plan new --goal "<goal>" --tier <T0-T3> --file <path>[:add|modify|delete] ... --validate "<exact command>" ...`
   For T2/T3 also pass `--security "<item>"`. For richer plans, write `.agentic/plan.json` yourself and run `{{AGENTIC}} plan seal`.
   The tier can never be lower than what the plan's contents justify; the CLI raises it for you.
4. **Stop.** Do not write project files until the plan is active. For T2/T3, ask the user to type `/approve G1`.

Never write to `.agentic/approvals`, `.agentic/validations`, `.agentic/events.jsonl`, `.agentic/config.json` or `.claude/settings*.json`.
