"""Shared helpers for building throwaway projects in tests."""
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agentic import cli, hooks
from agentic.store import Store

HEAD_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def git(root: Path, *argv: str) -> str:
    import os
    return subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True, check=True,
                          env={**os.environ, **HEAD_ENV}).stdout.strip()


def new_project(case: unittest.TestCase, *, use_git: bool = False, **config) -> Store:
    """A temp project with .agentic/ and a config; cleaned up after the test."""
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    if use_git:
        git(root, "init", "-q")
        (root / "README.md").write_text("x")
        git(root, "add", "README.md")
        git(root, "commit", "-qm", "init")
    store = Store(root)
    store.ensure_dirs()
    if config:
        store.write_json(store.config_path, config)
    return store


def seal(store: Store, *, tier="T1", files=("src/a.py",), validation=("pytest",), **over) -> dict:
    plan = {
        "schema": "plan/2", "tier": tier, "requirements": ["r"], "scope": ["s"], "non_goals": [],
        "files": [{"path": f, "change": "modify"} for f in files],
        "phases": [{"id": "p1", "goal": "g", "tests_first": []}], "risks": [], "rollback": "git revert it",
        "validation": list(validation), "acceptance": ["a"], "plan_hash": "0" * 64,
    }
    if tier in ("T2", "T3"):
        plan["security_plan"] = ["validate inputs"]
    plan.update(over)
    cli.seal_plan(store, plan)
    return store.read_plan()[0]


def pre(store: Store, tool: str, now=None, **tool_input) -> hooks.HookResult:
    return hooks.handle("pre-tool-use", {"session_id": "t", "tool_name": tool, "tool_input": tool_input},
                        store.root, now)


def write(store: Store, rel: str, content: str = "x = 1", now=None) -> hooks.HookResult:
    return pre(store, "Write", now, file_path=str(store.root / rel), content=content)


def bash(store: Store, command: str, now=None) -> hooks.HookResult:
    return pre(store, "Bash", now, command=command)


def prompt(store: Store, text: str, now=None) -> hooks.HookResult:
    return hooks.handle("user-prompt-submit", {"session_id": "t", "prompt": text}, store.root, now)


def ran(store: Store, command: str, *, exit_code=0, output="ok", event="post-tool-use", extra=None, now=None):
    """Simulate the harness reporting that `command` finished."""
    payload = {"session_id": "t", "cwd": str(store.root), "tool_name": "Bash", "tool_input": {"command": command}}
    if event == "post-tool-use":
        payload["tool_response"] = {"output": output, "exit_code": exit_code} if exit_code is not None else {"output": output}
    else:
        payload["error"] = f"Exit code {exit_code}\n{output}"
    payload.update(extra or {})
    return hooks.handle(event, payload, store.root, now)


def events(store: Store) -> list[dict]:
    if not store.events_path.exists():
        return []
    return [json.loads(line) for line in store.events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
