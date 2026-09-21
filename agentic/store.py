"""On-disk state for one project: config, plan, approvals, validations, events.

Layout under <root>/.agentic/
  config.json          human-edited policy (protected from agents)
  plan.json            the active plan (agent-written, sealed with a plan_hash)
  plans/               history of sealed plans, by hash
  review.json          the latest review (agent-written; verdict is re-derived on use)
  approvals/*.json     G1/G2 decisions (hook-written from user prompts only)
  validations/*.json   validation results (hook-written from real command runs)
  evidence/*.txt       redacted command output referenced by validations
  events.jsonl         append-only audit log (hook/CLI-written)
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import secretscan

STATE_DIR = ".agentic"
ENFORCEMENT_MODES = ("enforce", "warn", "off")
SECRET_MODES = ("block", "warn", "off")

DEFAULT_CONFIG: dict = {
    "schema_version": 1,
    # enforce: violations are blocked. warn: violations are logged and allowed
    # (integrity rules such as protected paths still block). off: nothing is checked.
    "enforcement": "enforce",
    "secret_scan": "block",
    # Writes to these globs need no plan (e.g. ["**/*.md"] for docs-only edits).
    "unplanned_write_globs": [],
    # Agents may never write these; only humans and hooks may.
    "protected_paths": [
        ".agentic/config.json",
        ".agentic/approvals/**",
        ".agentic/validations/**",
        ".agentic/evidence/**",
        ".agentic/events.jsonl",
        ".claude/settings.json",
        ".claude/settings.local.json",
    ],
    # A plan touching any of these is at least tier T3.
    "sensitive_globs": [
        "**/migrations/**", "**/auth/**", "**/.github/workflows/**", "**/Dockerfile*",
        "**/*.tf", "**/infra/**", "**/.env*",
    ],
    "t1_max_files": 3,
    # Commands recorded as validations even if a plan does not list them.
    "validation_commands": [],
    # Claude Code's Bash PostToolUse payload has no exit code, but the event only fires when the
    # command succeeded (failures fire PostToolUseFailure with "Exit code N"); verified against a
    # live session on 2026-09-20. Set false to record such runs as "unverified" instead.
    "trust_post_tool_use_success": True,
    # Who may grant gates; empty means any local user.
    "approvers": {"G1": [], "G2": []},
    # Minutes until a granted approval expires; null means never.
    "approval_ttl_minutes": {"G1": None, "G2": None},
}


class ConfigError(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_us(dt: datetime) -> str:
    """Microsecond-precision timestamp: orders decisions made within the same second."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def find_root(start: str | os.PathLike | None = None) -> Path:
    """Project root: nearest ancestor of `start` (default: $CLAUDE_PROJECT_DIR, then cwd)
    that already holds .agentic/, else `start` itself. `.claude/` is deliberately not a
    marker: ~/.claude exists for every user and would make the home directory a "project"."""
    origin = Path(start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    for d in [origin, *origin.parents]:
        if (d / STATE_DIR).is_dir():
            return d
    return origin


def _validate_config(cfg: dict) -> None:
    def strs(v):
        return isinstance(v, list) and all(isinstance(x, str) for x in v)

    if cfg["enforcement"] not in ENFORCEMENT_MODES:
        raise ConfigError(f"enforcement must be one of {ENFORCEMENT_MODES}")
    if cfg["secret_scan"] not in SECRET_MODES:
        raise ConfigError(f"secret_scan must be one of {SECRET_MODES}")
    for key in ("unplanned_write_globs", "protected_paths", "sensitive_globs", "validation_commands"):
        if not strs(cfg[key]):
            raise ConfigError(f"{key} must be a list of strings")
    if not isinstance(cfg["trust_post_tool_use_success"], bool):
        raise ConfigError("trust_post_tool_use_success must be true or false")
    if not isinstance(cfg["t1_max_files"], int) or cfg["t1_max_files"] < 0:
        raise ConfigError("t1_max_files must be a non-negative integer")
    for gate in ("G1", "G2"):
        if not strs(cfg["approvers"].get(gate, [])):
            raise ConfigError(f"approvers.{gate} must be a list of strings")
        ttl = cfg["approval_ttl_minutes"].get(gate)
        if ttl is not None and (not isinstance(ttl, (int, float)) or ttl <= 0):
            raise ConfigError(f"approval_ttl_minutes.{gate} must be null or a positive number")


class Store:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).resolve()
        self.dir = self.root / STATE_DIR

    # -- paths
    config_path = property(lambda s: s.dir / "config.json")
    plan_path = property(lambda s: s.dir / "plan.json")
    review_path = property(lambda s: s.dir / "review.json")
    plans_dir = property(lambda s: s.dir / "plans")
    approvals_dir = property(lambda s: s.dir / "approvals")
    validations_dir = property(lambda s: s.dir / "validations")
    evidence_dir = property(lambda s: s.dir / "evidence")
    events_path = property(lambda s: s.dir / "events.jsonl")

    def ensure_dirs(self) -> None:
        for d in (self.dir, self.plans_dir, self.approvals_dir, self.validations_dir, self.evidence_dir):
            d.mkdir(parents=True, exist_ok=True)

    # -- io
    @staticmethod
    def write_json(path: Path, doc) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def read_json(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    # -- config
    def config(self) -> dict:
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        if self.config_path.exists():
            try:
                user = self.read_json(self.config_path)
            except (OSError, json.JSONDecodeError) as e:
                raise ConfigError(f"{self.config_path} unreadable: {e}") from e
            if not isinstance(user, dict):
                raise ConfigError(f"{self.config_path} must contain a JSON object")
            for key, value in user.items():
                if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                    cfg[key].update(value)
                else:
                    cfg[key] = value
        _validate_config(cfg)
        return cfg

    # -- plan / review
    def read_plan(self) -> tuple[dict | None, str | None]:
        """(plan, error). plan is None with error None when no plan exists."""
        if not self.plan_path.exists():
            return None, None
        try:
            plan = self.read_json(self.plan_path)
        except (OSError, json.JSONDecodeError) as e:
            return None, f"plan.json unreadable: {e}"
        if not isinstance(plan, dict):
            return None, "plan.json must contain a JSON object"
        return plan, None

    def read_review(self) -> tuple[dict | None, str | None]:
        if not self.review_path.exists():
            return None, "no review recorded (.agentic/review.json)"
        try:
            doc = self.read_json(self.review_path)
        except (OSError, json.JSONDecodeError) as e:
            return None, f"review.json unreadable: {e}"
        return (doc, None) if isinstance(doc, dict) else (None, "review.json must contain a JSON object")

    def _load_dir(self, d: Path) -> list[dict]:
        docs = []
        for f in sorted(d.glob("*.json")) if d.is_dir() else []:
            try:
                doc = self.read_json(f)
            except (OSError, json.JSONDecodeError):
                continue  # unreadable record is ignored, i.e. never counts as evidence
            if isinstance(doc, dict):
                docs.append(doc)
        return docs

    def approvals(self) -> list[dict]:
        return self._load_dir(self.approvals_dir)

    def validations(self) -> list[dict]:
        return self._load_dir(self.validations_dir)

    # -- events
    def append_event(self, type: str, session_id: str = "local", *, agent: str | None = None,
                     run_id: str | None = None, payload: dict | None = None) -> None:
        if os.environ.get("AGENTIC_NO_EVENTS") == "1":  # used by `doctor` self-tests
            return
        event = {
            "schema": "event/1", "id": uuid.uuid4().hex, "session_id": session_id or "local",
            "trace_id": session_id or "local", "type": type, "ts": iso(utcnow()),
        }
        if agent:
            event["agent"] = agent
        if run_id:
            event["run_id"] = run_id
        if payload:
            event["payload"] = _redact_payload(payload)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self.events_path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass  # auditing must never take the workflow down

    # -- git
    def git_state(self) -> tuple[str, bool]:
        """(HEAD, dirty). ("", False) outside a git repo. `.agentic/` never counts as dirt."""
        def run(*argv):
            return subprocess.run(["git", "-C", str(self.root), *argv], capture_output=True, text=True, timeout=30)
        try:
            head = run("rev-parse", "HEAD")
            if head.returncode != 0:
                return "", False
            status = run("status", "--porcelain", "--", ".", ":(exclude).agentic")
        except (OSError, subprocess.TimeoutExpired):
            return "", False
        return head.stdout.strip(), bool(status.stdout.strip())


def _redact_payload(value):
    if isinstance(value, str):
        return secretscan.redact(value)[:500]
    if isinstance(value, dict):
        return {k: _redact_payload(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_payload(v) for v in value[:50]]
    return value
