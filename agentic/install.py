"""`init`: wire the hooks into a project's Claude Code settings and create its state directory.

Principles from the architecture doc: resolve before mutating, preview before applying
(--dry-run), track ownership, preserve user files, stay idempotent.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from pathlib import Path

from . import hooks
from .store import DEFAULT_CONFIG, Store, iso, utcnow

# (Claude Code event, matcher or None, agentic hook name)
HOOK_SPECS = [
    ("PreToolUse", "Write|Edit|MultiEdit|NotebookEdit|Bash", "pre-tool-use"),
    ("PostToolUse", "Bash", "post-tool-use"),
    ("PostToolUseFailure", "Bash", "post-tool-use-failure"),
    ("UserPromptSubmit", None, "user-prompt-submit"),
    ("SessionStart", None, "session-start"),
]
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "commands"
HOOK_TIMEOUT_SECONDS = 15


class InstallError(Exception):
    pass


def launcher_ref(root: Path) -> str:
    """Quoted launcher path: project-relative via $CLAUDE_PROJECT_DIR when inside the project."""
    try:
        rel = hooks.LAUNCHER.resolve().relative_to(root.resolve())
        return f'"$CLAUDE_PROJECT_DIR/{rel.as_posix()}"'
    except ValueError:
        return f'"{hooks.LAUNCHER.as_posix()}"'


def hook_command(root: Path, slug: str, python: str) -> str:
    return f"{python} {launcher_ref(root)} hook {slug}"


def is_managed(command: str, slug: str) -> bool:
    return re.search(rf"agentic\.py\"?\s+hook\s+{re.escape(slug)}\b", command or "") is not None


def merge_settings(settings: dict, root: Path, python: str) -> tuple[dict, list[str]]:
    """Return (new settings, human-readable changes). User entries are never touched."""
    new = copy.deepcopy(settings)
    changes: list[str] = []
    hooks_cfg = new.setdefault("hooks", {})
    if not isinstance(hooks_cfg, dict):
        raise InstallError("settings 'hooks' must be an object")
    for event, matcher, slug in HOOK_SPECS:
        entries = hooks_cfg.setdefault(event, [])
        command = hook_command(root, slug, python)
        found = next(((e, h) for e in entries if isinstance(e, dict)
                      for h in e.get("hooks", []) if is_managed(h.get("command", ""), slug)), None)
        if found is None:
            entry = {"hooks": [{"type": "command", "command": command, "timeout": HOOK_TIMEOUT_SECONDS}]}
            if matcher:
                entry = {"matcher": matcher, **entry}
            entries.append(entry)
            changes.append(f"add {event} hook '{slug}'")
            continue
        entry, hook = found
        if hook.get("command") != command or entry.get("matcher") != matcher:
            hook["command"] = command
            hook.setdefault("type", "command")
            hook.setdefault("timeout", HOOK_TIMEOUT_SECONDS)
            if matcher:
                entry["matcher"] = matcher
            else:
                entry.pop("matcher", None)
            changes.append(f"update {event} hook '{slug}'")
    return new, changes


def read_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise InstallError(f"{path} is not valid JSON ({e}); fix it first, nothing was changed") from e
    if not isinstance(data, dict):
        raise InstallError(f"{path} must contain a JSON object; nothing was changed")
    return data


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def install(root, *, local: bool = False, enforcement: str = "enforce", python: str = "python",
            dry_run: bool = False) -> list[str]:
    """Apply (or, with dry_run, only describe) the installation. Returns the list of actions."""
    root = Path(root).resolve()
    if root == Path.home().resolve() or (root / ".claude").resolve() == (Path.home() / ".claude").resolve():
        raise InstallError(f"refusing to install into {root}: that would apply hooks to every Claude Code "
                           "session on this machine. Pass --dir <project> to install into one project.")
    store = Store(root)
    actions: list[str] = []
    settings_path = root / ".claude" / ("settings.local.json" if local else "settings.json")

    merged, changes = merge_settings(read_settings(settings_path), root, python)
    actions += [f"{settings_path.relative_to(root).as_posix()}: {c}" for c in changes]

    if not store.config_path.exists():
        actions.append(f".agentic/config.json: create (enforcement={enforcement})")
    templates = sorted(TEMPLATE_DIR.glob("*.md"))
    managed_files: dict[str, str] = {}
    command_writes: list[tuple[Path, str]] = []
    for tpl in templates:
        target = root / ".claude" / "commands" / tpl.name
        body = tpl.read_text(encoding="utf-8").replace("{{AGENTIC}}", f"{python} {launcher_ref(root)}")
        if target.exists():
            if _sha(target.read_text(encoding="utf-8")) != _sha(body):
                actions.append(f".claude/commands/{tpl.name}: exists and differs; left untouched")
            managed_files[f".claude/commands/{tpl.name}"] = _sha(body)
            continue
        actions.append(f".claude/commands/{tpl.name}: create")
        command_writes.append((target, body))
        managed_files[f".claude/commands/{tpl.name}"] = _sha(body)

    if dry_run:
        return actions or ["nothing to do (already installed)"]

    store.ensure_dirs()
    if not store.config_path.exists():
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["enforcement"] = enforcement
        store.write_json(store.config_path, cfg)
    gitignore = store.dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("evidence/\nevents.jsonl\ndebug/\n", encoding="utf-8")
    if changes:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    for target, body in command_writes:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    store.write_json(store.dir / "install.json", {
        "version": 1, "installed_at": iso(utcnow()), "settings": settings_path.relative_to(root).as_posix(),
        "hooks": [slug for _, _, slug in HOOK_SPECS], "managed_files": managed_files, "python": python})
    store.append_event("stage.enter", "local", payload={"stage": "install", "actions": actions[:20]})
    return actions or ["nothing to do (already installed)"]


def uninstall(root, *, local: bool = False, purge_state: bool = False, dry_run: bool = False) -> list[str]:
    """Remove what `install` added and nothing else.

    Only hook entries recognised as managed are removed (user hooks stay), command files are
    removed only if unchanged since install, and `.agentic/` state (plans, approvals, audit log)
    is kept unless `purge_state` is set.
    """
    root = Path(root).resolve()
    store = Store(root)
    actions: list[str] = []
    settings_path = root / ".claude" / ("settings.local.json" if local else "settings.json")
    rel_settings = settings_path.relative_to(root).as_posix()

    settings = read_settings(settings_path)
    cleaned = copy.deepcopy(settings)
    for event, entries in list((cleaned.get("hooks") or {}).items()):
        kept = []
        for entry in entries if isinstance(entries, list) else []:
            hooks_kept = [h for h in entry.get("hooks", [])
                          if not any(is_managed(h.get("command", ""), slug) for _, _, slug in HOOK_SPECS)]
            if len(hooks_kept) != len(entry.get("hooks", [])):
                actions.append(f"{rel_settings}: remove managed {event} hook")
            if hooks_kept:
                kept.append({**entry, "hooks": hooks_kept})
            elif not entry.get("hooks"):
                kept.append(entry)  # not ours: an entry that never had hooks
        if kept:
            cleaned["hooks"][event] = kept
        else:
            del cleaned["hooks"][event]
    if "hooks" in cleaned and not cleaned["hooks"]:
        del cleaned["hooks"]

    manifest_path = store.dir / "install.json"
    managed: dict = {}
    if manifest_path.exists():
        try:
            managed = json.loads(manifest_path.read_text(encoding="utf-8")).get("managed_files", {})
        except json.JSONDecodeError:
            actions.append(".agentic/install.json unreadable: command files left in place")
    removable = []
    for rel, digest in managed.items():
        f = root / rel
        if not f.exists():
            continue
        if _sha(f.read_text(encoding="utf-8")) == digest:
            actions.append(f"{rel}: remove")
            removable.append(f)
        else:
            actions.append(f"{rel}: modified since install; left in place")
    if purge_state and store.dir.exists():
        actions.append(".agentic/: remove (plans, approvals, validations, audit log)")

    if dry_run:
        return actions or ["nothing to remove"]
    if cleaned != settings:
        if cleaned:
            settings_path.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
        else:
            settings_path.unlink()
    for f in removable:
        f.unlink()
    for d in (root / ".claude" / "commands", root / ".claude"):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    if purge_state and store.dir.exists():
        shutil.rmtree(store.dir)
    elif manifest_path.exists():
        manifest_path.unlink()
        store.append_event("stage.exit", "local", payload={"stage": "uninstall"})
    return actions or ["nothing to remove"]
