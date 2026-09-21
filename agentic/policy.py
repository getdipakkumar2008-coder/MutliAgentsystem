"""Pure policy decisions: may this write / command proceed, given the plan and approvals?

Nothing here performs I/O beyond reading state through a Store, so every rule is unit-testable.
"""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime

from . import validate
from .store import Store

TIER_RANK = {"T0": 0, "T1": 1, "T2": 2, "T3": 3}
KNOWN_SCOPES = ("commit", "push", "open-pr", "merge", "publish", "deploy")


@dataclass(frozen=True)
class Decision:
    action: str          # allow | deny | ask
    reason: str = ""
    rule: str = ""
    hard: bool = False   # integrity rule: still blocks in "warn" enforcement mode


ALLOW = Decision("allow")


def deny(rule: str, reason: str, hard: bool = False) -> Decision:
    return Decision("deny", reason, rule, hard)


def ask(rule: str, reason: str) -> Decision:
    return Decision("ask", reason, rule)


# ------------------------------------------------------------------ paths

def _norm(s: str) -> str:
    s = s.replace("\\", "/")
    return s.lower() if os.name == "nt" else s


def _resolve(root, path: str) -> str:
    """Absolute, symlink-resolved, case-normalised form of `path` (relative paths are under `root`)."""
    if os.name == "nt":
        path = re.sub(r"^/([a-zA-Z])/", r":/", path)  # Git-Bash style /c/x -> c:/x
    joined = path if os.path.isabs(path) else os.path.join(str(root), path)
    return os.path.normcase(os.path.realpath(joined))


def _under(path: str, base: str) -> bool:
    try:
        return os.path.commonpath([base, path]) == base
    except ValueError:
        return False


def rel_to_root(root, path: str) -> str | None:
    """Project-relative POSIX path, or None if `path` is outside the project."""
    root_r = os.path.normcase(os.path.realpath(str(root)))
    abs_r = _resolve(root, path)
    if not _under(abs_r, root_r):
        return None
    return os.path.relpath(abs_r, root_r).replace(os.sep, "/")


PLATFORM_DIR = Path(__file__).resolve().parent.parent


def protected_outside_project(root, target: str) -> str | None:
    """Files outside the project that an agent must not change: the hook code itself and the
    user's global Claude settings. Editing either would silently switch enforcement off."""
    abs_r = _resolve(root, target)
    for sub in ("agentic", "scripts"):
        if _under(abs_r, os.path.normcase(os.path.realpath(PLATFORM_DIR / sub))):
            return f"platform code ({sub}/)"
    for name in ("settings.json", "settings.local.json"):
        if abs_r == os.path.normcase(os.path.realpath(Path.home() / ".claude" / name)):
            return f"global Claude setting ~/.claude/{name}"
    return None


def glob_match(path: str, pattern: str) -> bool:
    """`**` spans directories, `*` and `?` do not cross '/'. A trailing '/' matches a subtree."""
    path, pattern = _norm(path), _norm(pattern)
    if pattern.endswith("/"):
        pattern += "**"
    regex, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            regex += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            regex += ".*"
            i += 2
        elif pattern[i] == "*":
            regex += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            regex += "[^/]"
            i += 1
        else:
            regex += re.escape(pattern[i])
            i += 1
    return re.fullmatch(regex, path) is not None


def matches_any(path: str, patterns) -> bool:
    return any(glob_match(path, p) for p in patterns)


# ------------------------------------------------------------------ tiers

def tier_floor(plan: dict, cfg: dict) -> str:
    """Lowest tier the plan's own contents justify. A plan may claim higher, never lower."""
    files = plan.get("files", [])
    paths = [f["path"] for f in files]
    if any(matches_any(p, cfg["sensitive_globs"]) for p in paths):
        return "T3"
    if plan.get("dependencies") or any(f.get("change") == "delete" for f in files):
        return "T2"
    if len(files) > cfg["t1_max_files"]:
        return "T2"
    return "T0" if len(files) <= 1 else "T1"


@dataclass
class PlanState:
    status: str                  # none | invalid | understated | needs_g1 | active
    reason: str = ""
    plan: dict | None = None
    floor: str = ""
    approval: dict | None = None
    problems: list = field(default_factory=list)


def find_valid_approval(store: Store, gate: str, plan_hash: str, now: datetime) -> dict | None:
    """Latest decision for (gate, plan_hash); returned only if granted and unexpired."""
    candidates = [a for a in store.approvals()
                  if a.get("gate") == gate and a.get("plan_hash") == plan_hash
                  and not validate.schema_errors("approval", a)]
    if not candidates:
        return None
    latest = max(candidates, key=lambda a: (a["decided_at"], a["id"]))
    if latest["decision"] != "granted":
        return None
    if "expires_at" in latest and validate.parse_time(latest["expires_at"]) <= now:
        return None
    return latest


def plan_state(store: Store, cfg: dict, now: datetime) -> PlanState:
    plan, err = store.read_plan()
    if err:
        return PlanState("invalid", err)
    if plan is None:
        return PlanState("none", "no plan: create one with `plan new` or write .agentic/plan.json, then `plan seal`")
    errors = validate.schema_errors("plan", plan)
    if errors:
        return PlanState("invalid", "plan fails its schema: " + "; ".join(errors[:3]), plan, problems=errors)
    if plan["plan_hash"] != validate.compute_plan_hash(plan):
        return PlanState("invalid", "plan_hash is stale (plan edited after sealing): run `plan seal`", plan)
    floor = tier_floor(plan, cfg)
    if TIER_RANK[plan["tier"]] < TIER_RANK[floor]:
        return PlanState("understated", f"plan declares {plan['tier']} but its contents require at least {floor}",
                         plan, floor)
    if TIER_RANK[plan["tier"]] >= TIER_RANK["T2"]:
        approval = find_valid_approval(store, "G1", plan["plan_hash"], now)
        if approval is None:
            return PlanState("needs_g1", f"{plan['tier']} plan needs G1 approval: the user must type `/approve G1`",
                             plan, floor)
        return PlanState("active", "", plan, floor, approval)
    return PlanState("active", "", plan, floor)


# ------------------------------------------------------------------ writes

def decide_write(store: Store, cfg: dict, target: str, now: datetime) -> Decision:
    rel = rel_to_root(store.root, target)
    if rel is None:
        what = protected_outside_project(store.root, target)
        if what:
            return deny("protected-outside", f"{what} is protected: changing it could disable enforcement", hard=True)
        return ALLOW  # other locations outside the project are not policed here
    if matches_any(rel, cfg["protected_paths"]):
        return deny("protected-path", f"{rel} is protected: only the user and hooks may change it", hard=True)
    if matches_any(rel, cfg["unplanned_write_globs"]) or rel == ".agentic" or rel.startswith(".agentic/"):
        return ALLOW
    st = plan_state(store, cfg, now)
    if st.status != "active":
        return deny(f"plan-{st.status}", f"write to {rel} blocked: {st.reason}")
    for f in st.plan["files"]:
        if glob_match(rel, f["path"]):
            return ALLOW
    return deny("out-of-scope", f"{rel} is not in the plan's file scope; add it to the plan (this re-opens "
                                f"approval for {st.plan['tier']}) or choose another file")


# ------------------------------------------------------------------ bash

_READONLY = {"cat", "ls", "dir", "head", "tail", "grep", "rg", "type", "findstr", "wc", "stat", "less", "more",
             "diff", "file", "echo", "printf", "test", "[", "find", "tree", "du", "sort", "jq", "realpath",
             "basename", "dirname", "sha256sum", "md5sum"}
_FIND_MUTATING = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
_WRAPPERS = {"sudo", "time", "nohup", "command", "exec", "nice", "env"}
_DESTRUCTIVE_TEXT = [
    ("pipe-to-shell", re.compile(r"\b(?:curl|wget)\b[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b")),
    ("sql-drop", re.compile(r"(?i)\bdrop\s+(?:table|database|schema)\b|\btruncate\s+table\b")),
    ("disk-wipe", re.compile(r"\bmkfs(?:\.\w+)?\b|\bdd\b[^;&|]*\bof=/dev/")),
    ("chmod-777-root", re.compile(r"\bchmod\s+-R\s+0?777\s+/(?:\s|$)")),
    ("fork-bomb", re.compile(r":\(\)\s*\{\s*:\s*\|\s*:")),
]
_FORGERY = re.compile(r"agentic(?:\.py)?[\"']?\s+hook\b|\b(?:from|import)\s+agentic\b|agentic\.hooks")
_DANGEROUS_RM_TARGETS = {"/", "/*", "~", "~/", "~/*", "$HOME", "${HOME}", "..", "../", "*", ".", "./", ".*"}
_INSTALLERS = {
    "npm": {"install", "i", "add"}, "pnpm": {"install", "i", "add"}, "yarn": {"install", "add"},
    "pip": {"install"}, "pip3": {"install"}, "uv": {"add", "pip"}, "cargo": {"add"}, "go": {"get"},
    "poetry": {"add"}, "gem": {"install"}, "composer": {"require"},
}
_GATED = [  # (argv prefix, scope)
    (("git", "push"), "push"), (("npm", "publish"), "publish"), (("pnpm", "publish"), "publish"),
    (("yarn", "publish"), "publish"), (("cargo", "publish"), "publish"), (("twine", "upload"), "publish"),
    (("docker", "push"), "publish"), (("gh", "release", "create"), "publish"),
    (("gh", "pr", "create"), "open-pr"), (("gh", "pr", "merge"), "merge"),
    (("kubectl", "apply"), "deploy"), (("kubectl", "delete"), "deploy"), (("kubectl", "rollout"), "deploy"),
    (("terraform", "apply"), "deploy"), (("terraform", "destroy"), "deploy"),
    (("helm", "install"), "deploy"), (("helm", "upgrade"), "deploy"), (("helm", "uninstall"), "deploy"),
    (("vercel", "deploy"), "deploy"), (("netlify", "deploy"), "deploy"),
]


def split_commands(command: str) -> list[tuple[str, str]]:
    """Split on unquoted ; && || | and newlines into (segment, operator-that-follows) pairs."""
    pairs, cur, quote, i = [], [], "", 0
    while i < len(command):
        c = command[i]
        if quote:
            cur.append(c)
            if c == quote and command[i - 1] != "\\":
                quote = ""
        elif c in "'\"":
            quote = c
            cur.append(c)
        elif command.startswith("&&", i) or command.startswith("||", i):
            pairs.append(("".join(cur), command[i:i + 2]))
            cur = []
            i += 1
        elif c in ";\n|":
            pairs.append(("".join(cur), ";" if c == "\n" else c))
            cur = []
        else:
            cur.append(c)
        i += 1
    pairs.append(("".join(cur), ""))
    return [(seg.strip(), op) for seg, op in pairs if seg.strip()]


def split_segments(command: str) -> list[str]:
    return [seg for seg, _ in split_commands(command)]


def _tokens(segment: str) -> list[str]:
    try:
        toks = shlex.split(segment, posix=True)
    except ValueError:
        toks = segment.split()
    while toks and (toks[0] in _WRAPPERS or re.fullmatch(r"\w+=\S*", toks[0])):
        toks = toks[1:]
    return toks


def _git_argv(toks: list[str]) -> list[str]:
    """Drop git's global options so ['git','-C','x','push'] becomes ['git','push']."""
    out, i = [toks[0]], 1
    while i < len(toks):
        if toks[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
            i += 2
        elif toks[i].startswith("-") and out == ["git"]:
            i += 1
        else:
            out += toks[i:]
            break
    return out


def _write_targets(segment: str, toks: list[str]) -> list[str]:
    targets = [m.group(1).strip("'\"") for m in re.finditer(
        r"(?:^|[\s\d])>{1,2}(?!&)\s*(\"[^\"]+\"|'[^']+'|[^\s;&|<>]+)", segment)]
    if not toks:
        return [t for t in targets if t != "/dev/null"]
    nonopt = [t for t in toks[1:] if not t.startswith("-")]
    verb = toks[0]
    if verb == "tee":
        targets += nonopt
    elif verb == "sed" and any(t == "--in-place" or re.fullmatch(r"-[a-zA-Z]*i[a-zA-Z.]*", t) for t in toks[1:]):
        targets += nonopt[1:]
    elif verb in ("rm", "touch", "mkdir", "mv"):
        targets += nonopt
    elif verb == "cp" and nonopt:
        targets.append(nonopt[-1])
    return [t for t in targets if t != "/dev/null"]


def _protected_prefixes(cfg: dict) -> list[str]:
    prefixes = []
    for pat in cfg["protected_paths"]:
        p = re.sub(r"[/*]+$", "", _norm(pat))
        if p:
            prefixes.append(p)
    return prefixes


def decide_bash(store: Store, cfg: dict, command: str, now: datetime, _depth: int = 0) -> Decision:
    if _FORGERY.search(command):
        return deny("approval-forgery", "invoking the agentic hooks or package directly is blocked: approvals and "
                    "validations may only come from the user's prompts and real command runs", hard=True)
    for rule, pattern in _DESTRUCTIVE_TEXT:
        if pattern.search(command):
            return deny(rule, f"destructive command pattern blocked ({rule})")

    asks: list[Decision] = []
    gated: list[tuple[str, str]] = []  # (scope, description)
    prefixes = _protected_prefixes(cfg)

    for segment in split_segments(command):
        toks = _tokens(segment)
        if not toks:
            continue
        verb = toks[0].rsplit("/", 1)[-1]

        if verb in ("bash", "sh", "zsh") and "-c" in toks and _depth < 2:
            i = toks.index("-c")
            if i + 1 < len(toks):
                inner = decide_bash(store, cfg, toks[i + 1], now, _depth + 1)
                if inner.action == "deny":
                    return inner
                if inner.action == "ask":
                    asks.append(inner)

        seg_norm = _norm(segment)
        readonly = verb in _READONLY and not (verb == "find" and any(t in _FIND_MUTATING for t in toks))
        if not readonly and any(p in seg_norm for p in prefixes):
            return deny("protected-path", "command touches a protected path (approvals, validations, events, "
                        "config or settings): only the user and hooks may change these", hard=True)

        if verb == "rm":
            recursive = any(t == "--recursive" or (t.startswith("-") and not t.startswith("--") and
                                                   ("r" in t or "R" in t)) for t in toks[1:])
            targets = [t for t in toks[1:] if not t.startswith("-")]
            if recursive:
                if any(t in _DANGEROUS_RM_TARGETS or re.fullmatch(r"/[^/]*/?", t) for t in targets):
                    return deny("rm-rf-dangerous", "recursive delete of a root/home/parent/wildcard target blocked")
                asks.append(ask("rm-recursive", "recursive delete needs your confirmation"))

        for target in _write_targets(segment, toks):
            target = os.path.expanduser(target)
            if "$" in target or "`" in target:
                continue  # cannot be resolved statically; best effort only
            d = decide_write(store, cfg, target, now)
            if d.action == "deny":
                return deny(d.rule, f"{d.reason} (via shell command)", d.hard)

        if verb == "git":
            g = _git_argv(toks)
            sub = g[1] if len(g) > 1 else ""
            rest = g[2:]
            if sub == "push":
                if any(t in ("--force", "-f", "--force-with-lease", "--mirror", "--delete", "-d")
                       or t.startswith("+") for t in rest):
                    return deny("force-push", "force/mirror/delete push blocked")
            elif sub == "reset" and "--hard" in rest:
                asks.append(ask("git-reset-hard", "`git reset --hard` discards work"))
            elif sub == "clean" and any(t.startswith("-") and "f" in t for t in rest):
                asks.append(ask("git-clean", "`git clean -f` deletes untracked files"))
            elif sub in ("checkout", "restore") and ("." in rest or "--" in rest):
                asks.append(ask("git-discard", "this discards uncommitted changes"))
            elif sub == "branch" and any(t in ("-D", "--delete") for t in rest):
                asks.append(ask("git-branch-delete", "branch deletion needs your confirmation"))

        norm_toks = ["git", *(_git_argv(toks)[1:])] if verb == "git" else [verb, *toks[1:]]
        for prefix, scope in _GATED:
            if tuple(norm_toks[:len(prefix)]) == prefix:
                gated.append((scope, " ".join(prefix)))

        if verb in _INSTALLERS or (verb == "python" and "pip" in toks and "install" in toks):
            sub = next((t for t in toks[1:] if not t.startswith("-")), "")
            if verb == "python" or sub in _INSTALLERS.get(verb, set()):
                if not _installs_planned_deps(store, cfg, toks, now):
                    asks.append(ask("install-package", "installing packages needs your approval "
                                    "(list the dependency in an approved plan to skip this prompt)"))

    for scope, what in gated:
        d = _check_delivery(store, cfg, scope, what, now)
        if d is not None:
            return d
    return asks[0] if asks else ALLOW


def _installs_planned_deps(store: Store, cfg: dict, toks: list[str], now: datetime) -> bool:
    st = plan_state(store, cfg, now)
    if st.status != "active" or not st.plan.get("dependencies"):
        return False
    planned = {d["name"].lower() for d in st.plan["dependencies"]}
    args = [t for t in toks[1:] if not t.startswith("-")][1:]
    if not args:
        return False
    return all(re.split(r"[=<>~!@\[]", a, maxsplit=1)[0].lower() in planned for a in args)


def _check_delivery(store: Store, cfg: dict, scope: str, what: str, now: datetime) -> Decision | None:
    """Delivery actions need a valid G2 approval that lists the scope and matches the current commit."""
    st = plan_state(store, cfg, now)
    if st.status != "active":
        return deny("delivery-no-plan", f"`{what}` blocked: {st.reason or 'no active plan'}")
    g2 = find_valid_approval(store, "G2", st.plan["plan_hash"], now)
    if g2 is None:
        return deny("delivery-needs-g2", f"`{what}` needs delivery approval: the user must type "
                    f"`/approve G2 {scope}` after review and validation are complete")
    if scope not in g2["scope"]:
        return deny("delivery-scope", f"`{what}` is not covered by the G2 approval (approved scope: "
                    f"{', '.join(g2['scope'])}); the user must approve `{scope}` explicitly")
    head, dirty = store.git_state()
    if head != g2["git_head"]:
        return deny("delivery-stale", f"`{what}` blocked: HEAD changed since G2 approval "
                    f"({g2['git_head'][:8] or '-'} -> {head[:8] or '-'}); re-run validation and re-approve")
    if dirty:
        return deny("delivery-dirty", f"`{what}` blocked: uncommitted changes since G2 approval")
    return None
