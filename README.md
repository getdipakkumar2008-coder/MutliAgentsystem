# Agentic Engineering Platform (Phase 1)

Makes an AI coding session **accountable**: work happens inside an approved plan, approvals come only from the human, delivery needs evidence, and every claim ("tests pass") is backed by a recorded run. Built as hooks for [Claude Code](https://claude.com/claude-code); design in [`doc/`](doc/agentic-platform.md).

## Quick start

```bash
pip install -r requirements.txt                       # jsonschema
python scripts/agentic.py init --dir /path/to/project --dry-run   # preview
python scripts/agentic.py init --dir /path/to/project             # install (use --enforcement warn to trial it)
python scripts/agentic.py doctor --dir /path/to/project           # verify, including a live guard self-test
```

`init` merges hooks into the project's `.claude/settings.json` (your entries are preserved), adds `/plan /approve /doctor /status` commands, and creates `.agentic/`. `uninstall` reverses it (`--purge-state` also deletes plans, approvals and the audit log). It refuses to touch your home directory.

## The workflow it enforces

1. **Plan** (`/plan <request>`): the agent proposes a tier and seals a plan (`plan new` / `plan seal`). The tier can't be lower than the plan's contents justify (more than 3 files, deletions or new dependencies → T2; migrations, auth, CI, Dockerfiles, `.env` → T3).
2. **G1**: for T2/T3 the agent's writes stay blocked until *you* type `/approve G1`. Editing the plan afterwards voids the approval.
3. **Implement**: writes must fall inside the plan's `files`. Validation commands listed in the plan are recorded when they actually run (exit codes from the harness, output redacted).
4. **G2**: `/approve G2 push` (scope is explicit) is refused unless the review is `APPROVE`, every planned validation passed on the current commit, and the tree is clean.
5. **Deliver**: `git push`, `npm publish`, `gh pr create`, `terraform apply`... are blocked unless G2 covers that exact action and HEAD hasn't moved.

Always blocked: force-push, `rm -rf` of roots/home/wildcards, `curl | sh`, SQL `DROP`, secrets in writes or commands, and any write to approvals, validations, the audit log, config, Claude settings, or the hook code itself. Package installs, `git reset --hard`, and recursive deletes prompt you.

Approval and denial happen in your own prompt: `/approve G1`, `/deny G1`, `/approve G2 commit push`.

## CLI

| Command | Purpose |
|---|---|
| `init` / `uninstall` | install or remove hooks, commands, state (`--dry-run`, `--json`, `--local`) |
| `doctor` | read-only health check (hooks registered, launcher runs, guard works, log valid, evidence current) |
| `plan new / seal / status` | create or seal a plan; show gates and validations |
| `approvals` | list recorded decisions |
| `validate schema / plan-hash / review / check-approval` | contract validator used by the hooks |

Modes (`.agentic/config.json`, human-edited): `enforce` (default), `warn` (log, don't block soft rules), `off`.

## Layout

```
agentic/      package: store, policy (pure), hooks, secretscan, validate, install, doctor, cli
scripts/      agentic.py launcher (what hooks call)
schemas/      JSON Schemas: plan, review, validation, approval, memory, event
tests/        126 tests, incl. real git repos and the real launcher
doc/          design, master prompt
olddoc/       the original documents this replaced
```

## Honest limits

Best-effort shell parsing (heredocs, `python -c`, obfuscation can slip past the *scope* check); reviews are written by the agent and only their verdict is re-derived; approver identity is the OS user; only Windows + Claude Code 2.1.278 were tested live. Full list and verified payload facts: [`doc/agentic-platform.md` §14](doc/agentic-platform.md).

```bash
python -m unittest discover -s tests   # run the tests
```
