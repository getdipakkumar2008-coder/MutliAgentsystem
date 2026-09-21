# MutliagentSystem

Implementation of the agentic engineering platform specified in `doc/` (design: `doc/agentic-platform.md`, section 14 has current status and known limits).

@doc/master.md

## Working in this repo

- Tests: `python -m unittest discover -s tests` (run before claiming anything works; needs `pip install -r requirements.txt`).
- CLI: `python scripts/agentic.py {init,uninstall,doctor,plan,status,approvals,validate}`.
- This repo is installed in **warn** mode (`.agentic/config.json`): violations are logged and shown but not blocked, except integrity rules (protected paths, hook forgery), which always block. Only a human edits that file to switch to `enforce`.
- Never install into a home directory or a shared config: `init` requires `--dir <project>` semantics and refuses `~`.

## Conventions

- `agentic/policy.py` stays pure (decisions only); I/O lives in `store.py`, `hooks.py`, `install.py`.
- Hooks must never raise into the harness: `pre-tool-use` fails closed (exit 2), the others log and continue.
- Payload handling is tolerant of variants, but only the shapes recorded in `doc/agentic-platform.md` 14.2 are verified against real Claude Code.
- Every enforcement rule needs a test that fails when the rule is removed.
