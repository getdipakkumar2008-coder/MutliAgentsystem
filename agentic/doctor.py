"""`doctor`: read-only health check of an installation. Never modifies project state."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from . import hooks, install, policy, validate
from .store import ConfigError, Store, utcnow


def _chk(name: str, status: str, detail: str = "") -> dict:
    return {"check": name, "status": status, "detail": detail}


def run_doctor(root) -> list[dict]:
    root = Path(root).resolve()
    store = Store(root)
    out: list[dict] = []
    add = lambda name, status, detail="": out.append(_chk(name, status, detail))  # noqa: E731

    # -- runtime
    add("python >= 3.9", "pass" if sys.version_info >= (3, 9) else "fail", sys.version.split()[0])
    for name in validate.SCHEMA_NAMES:
        try:
            Draft202012Validator.check_schema(validate.load_schema(name))
            add(f"schema {name}", "pass")
        except Exception as e:  # noqa: BLE001
            add(f"schema {name}", "fail", str(e).splitlines()[0])

    # -- state + config
    if not store.dir.is_dir():
        add(".agentic/ exists", "fail", "run: python scripts/agentic.py init")
        return out
    add(".agentic/ exists", "pass")
    try:
        cfg = store.config()
    except ConfigError as e:
        add("config valid", "fail", str(e))
        return out
    add("config valid", "pass")
    add("enforcement mode", "pass" if cfg["enforcement"] == "enforce" else "warn",
        f"{cfg['enforcement']}" + ("" if cfg["enforcement"] == "enforce" else " - gates are not blocking"))
    if cfg["secret_scan"] != "block":
        add("secret scan", "warn", f"secret_scan={cfg['secret_scan']}")

    # -- hooks registered
    settings: dict = {}
    for name in ("settings.json", "settings.local.json"):
        try:
            data = install.read_settings(root / ".claude" / name)
        except install.InstallError as e:
            add(f".claude/{name} valid", "fail", str(e))
            continue
        for event, entries in (data.get("hooks") or {}).items():
            settings.setdefault(event, []).extend(entries if isinstance(entries, list) else [])
    for event, matcher, slug in install.HOOK_SPECS:
        command = next((h.get("command", "") for e in settings.get(event, []) if isinstance(e, dict)
                        for h in e.get("hooks", []) if install.is_managed(h.get("command", ""), slug)), None)
        if command is None:
            add(f"hook {event}/{slug} registered", "fail", "run: python scripts/agentic.py init")
            continue
        m = re.search(r'"([^"]*agentic\.py)"', command)
        launcher = Path(m.group(1).replace("$CLAUDE_PROJECT_DIR", str(root))) if m else None
        if launcher is not None and not launcher.exists():
            add(f"hook {event}/{slug} registered", "fail", f"launcher not found: {launcher}")
        else:
            add(f"hook {event}/{slug} registered", "pass")

    # -- live self-test through the real launcher
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root), "AGENTIC_NO_EVENTS": "1"}

    def call(slug: str, payload: dict):
        return subprocess.run([sys.executable, str(hooks.LAUNCHER), "hook", slug], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=30, cwd=str(root))
    try:
        r = call("session-start", {"cwd": str(root), "session_id": "doctor"})
        ok = r.returncode == 0 and r.stdout.startswith("agentic:")
        add("launcher runs (session-start)", "pass" if ok else "fail", "" if ok else (r.stderr or r.stdout)[:200])
        if cfg["enforcement"] != "off":
            r = call("pre-tool-use", {"cwd": str(root), "session_id": "doctor", "tool_name": "Write",
                                      "tool_input": {"file_path": str(store.approvals_dir / "selftest.json"),
                                                     "content": "{}"}})
            ok = r.returncode == 2
            add("guard blocks writes to protected paths", "pass" if ok else "fail",
                "" if ok else f"expected exit 2, got {r.returncode}: {(r.stderr or r.stdout)[:200]}")
    except (OSError, subprocess.TimeoutExpired) as e:
        add("launcher runs", "fail", str(e))

    # -- event log
    if store.events_path.exists():
        bad = 0
        lines = [ln for ln in store.events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        for ln in lines:
            try:
                bad += bool(validate.schema_errors("event", json.loads(ln)))
            except json.JSONDecodeError:
                bad += 1
        add("event log valid", "pass" if not bad else "warn", f"{len(lines)} events" + (f", {bad} invalid" if bad else ""))

    # -- plan / approvals / validations
    now = utcnow()
    st = policy.plan_state(store, cfg, now)
    status = {"active": "pass", "none": "pass", "needs_g1": "warn"}.get(st.status, "fail")
    add("plan state", status, st.status + (f": {st.reason}" if st.reason else ""))
    head, dirty = store.git_state()
    add("git repository", "pass" if head else "warn",
        f"HEAD {head[:8]}" if head else "not a git repo: approvals cannot be bound to a commit")
    stale = [v["id"] for v in store.validations() if v.get("git_head") != head]
    if stale:
        add("validation evidence current", "warn", f"{len(stale)} recorded against a different commit")

    # -- managed files drift
    manifest = store.dir / "install.json"
    if manifest.exists():
        try:
            managed = json.loads(manifest.read_text(encoding="utf-8")).get("managed_files", {})
        except json.JSONDecodeError:
            add("install manifest", "fail", "install.json is not valid JSON")
            managed = {}
        for rel, digest in managed.items():
            f = root / rel
            if not f.exists():
                add(f"managed file {rel}", "warn", "missing; run init to restore")
            elif hashlib.sha256(f.read_text(encoding="utf-8").encode("utf-8")).hexdigest() != digest:
                add(f"managed file {rel}", "warn", "modified since install (kept as-is)")
    return out
