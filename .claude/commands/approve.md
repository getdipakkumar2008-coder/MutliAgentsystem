---
description: Grant a gate (G1 plan approval or G2 delivery approval). Human-only.
argument-hint: G1 | G2 [commit push open-pr merge publish deploy]
---
The user ran `/approve $ARGUMENTS`. A hook has already processed it before this message reached you;
its result is in the hook context above.

- If the context says the gate was **APPROVED**, restate what was approved (gate, tier, plan hash, scope) and continue the workflow.
- Do not attempt to record an approval yourself. Approvals come only from the user's own prompts.
- G2 scope is explicit: only the actions listed (for example `push`) are approved. Anything else needs a fresh approval.
