"""Command line entry point: `python scripts/agentic.py <command>`."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import doctor, hooks, install, policy, validate
from .store import ConfigError, Store, find_root, iso, utcnow


# ------------------------------------------------------------------ plans

def seal_plan(store: Store, plan: dict) -> list[dict]:
    """Write the plan with a fresh plan_hash, archive it, and log creation/invalidation."""
    cfg = store.config()
    old, _ = store.read_plan()
    old_hash = old.get("plan_hash") if isinstance(old, dict) else None
    plan["plan_hash"] = validate.compute_plan_hash(plan)
    store.write_json(store.plan_path, plan)
    store.write_json(store.plans_dir / f"{plan['plan_hash'][:12]}.json", plan)
    store.append_event("plan.created", payload={"tier": plan.get("tier"), "plan_hash": plan["plan_hash"]})
    if old_hash and old_hash != plan["plan_hash"]:
        store.append_event("plan.invalidated", payload={"previous_plan_hash": old_hash})
    results = validate.schema_result(".agentic/plan.json", "plan", plan)
    if all(r["ok"] for r in results):
        floor = policy.tier_floor(plan, cfg)
        ok = policy.TIER_RANK[plan["tier"]] >= policy.TIER_RANK[floor]
        results.append(validate.result("tier justified by plan contents", ok,
                                       "" if ok else f"declares {plan['tier']}, contents require >= {floor}"))
    results.insert(0, validate.result("plan sealed", True, plan["plan_hash"]))
    return results


def cmd_plan_new(args, store: Store) -> list[dict]:
    cfg = store.config()
    files = []
    for spec in args.file:
        path, _, change = spec.partition(":")
        files.append({"path": path.replace("\\", "/"), "change": change or "modify"})
    validations = args.validate or cfg["validation_commands"]
    plan = {
        "schema": "plan/2", "tier": args.tier, "requirements": [args.goal], "scope": [args.goal],
        "non_goals": args.non_goal or [], "files": files,
        "phases": [{"id": "p1", "goal": args.goal, "tests_first": args.test_first or []}],
        "risks": [], "rollback": args.rollback or "git revert the change",
        "validation": validations, "acceptance": args.acceptance or [args.goal + " (verified by the validation commands)"],
        "plan_hash": "0" * 64,
    }
    if args.security:
        plan["security_plan"] = args.security
    if args.dep:
        plan["dependencies"] = []
        for spec in args.dep:
            name, decision, rationale = (spec.split(":", 2) + ["adopt", "planned dependency"])[:3]
            plan["dependencies"].append({"name": name, "decision": decision, "rationale": rationale})
    floor = policy.tier_floor(plan, cfg)
    notice = []
    if policy.TIER_RANK[plan["tier"]] < policy.TIER_RANK[floor]:
        notice.append(validate.result("tier raised", True, f"{plan['tier']} -> {floor} (plan contents require it)"))
        plan["tier"] = floor
    return notice + seal_plan(store, plan)


def cmd_plan_seal(args, store: Store) -> list[dict]:
    plan, err = store.read_plan()
    if plan is None:
        raise validate.CliError(err or "no plan at .agentic/plan.json")
    return seal_plan(store, plan)


def plan_status(store: Store) -> dict:
    cfg, now = store.config(), utcnow()
    st = policy.plan_state(store, cfg, now)
    info = {"status": st.status, "reason": st.reason, "enforcement": cfg["enforcement"]}
    if st.plan:
        info.update(tier=st.plan.get("tier"), tier_floor=st.floor, plan_hash=st.plan.get("plan_hash"),
                    files=[f["path"] for f in st.plan.get("files", []) if isinstance(f, dict) and "path" in f])
        if st.status in ("active", "needs_g1"):
            for gate in ("G1", "G2"):
                a = policy.find_valid_approval(store, gate, st.plan["plan_hash"], now)
                info[gate] = {"id": a["id"], "scope": a.get("scope", [])} if a else None
    info["validations"] = [{"id": v.get("id"), "command": v.get("command"), "status": v.get("status")}
                           for v in store.validations()][-10:]
    return info


# ------------------------------------------------------------------ output

def print_results(results: list[dict], as_json: bool) -> int:
    ok = all(r["ok"] for r in results)
    if as_json:
        print(json.dumps({"ok": ok, "results": results}, indent=2))
    else:
        for r in results:
            print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['check']}" + (f"  -- {r['detail']}" if r["detail"] else ""))
    return 0 if ok else 1


def cmd_doctor(args, store: Store) -> int:
    results = doctor.run_doctor(store.root)
    if args.json:
        print(json.dumps({"ok": all(r["status"] != "fail" for r in results), "results": results}, indent=2))
    else:
        for r in results:
            print(f"{r['status'].upper():4}  {r['check']}" + (f"  -- {r['detail']}" if r["detail"] else ""))
        fails = sum(r["status"] == "fail" for r in results)
        warns = sum(r["status"] == "warn" for r in results)
        print(f"\n{'UNHEALTHY' if fails else 'HEALTHY'}: {fails} failed, {warns} warnings")
    return 1 if any(r["status"] == "fail" for r in results) else 0


# ------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", help="project root (default: $CLAUDE_PROJECT_DIR, else nearest .agentic/.claude)")
    common.add_argument("--json", action="store_true", help="machine-readable output")

    p = argparse.ArgumentParser(prog="agentic", description="Agentic engineering platform CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", parents=[common], help="install hooks, commands and state into a project")
    s.add_argument("--local", action="store_true", help="write hooks to .claude/settings.local.json")
    s.add_argument("--enforcement", choices=("enforce", "warn", "off"), default="enforce")
    s.add_argument("--python", default="python", help="interpreter name used in hook commands")
    s.add_argument("--dry-run", action="store_true")

    s = sub.add_parser("uninstall", parents=[common], help="remove hooks and commands added by init")
    s.add_argument("--local", action="store_true", help="target .claude/settings.local.json")
    s.add_argument("--purge-state", action="store_true", help="also delete .agentic/ (plans, approvals, audit log)")
    s.add_argument("--dry-run", action="store_true")

    sub.add_parser("doctor", parents=[common], help="read-only health check")

    s = sub.add_parser("plan", parents=[common], help="create, seal or inspect the active plan")
    ps = s.add_subparsers(dest="plan_cmd", required=True)
    n = ps.add_parser("new", parents=[common], help="create and seal a plan")
    n.add_argument("--goal", required=True)
    n.add_argument("--tier", choices=("T0", "T1", "T2", "T3"), default="T1")
    n.add_argument("--file", action="append", default=[], metavar="PATH[:add|modify|delete]")
    n.add_argument("--validate", action="append", metavar="CMD", help="validation command (repeatable)")
    n.add_argument("--acceptance", action="append")
    n.add_argument("--security", action="append", help="security plan item (required for T2/T3)")
    n.add_argument("--dep", action="append", metavar="NAME[:DECISION[:WHY]]")
    n.add_argument("--non-goal", action="append")
    n.add_argument("--test-first", action="append")
    n.add_argument("--rollback")
    ps.add_parser("seal", parents=[common], help="recompute plan_hash of .agentic/plan.json")
    ps.add_parser("status", parents=[common], help="show plan, gates and recent validations")

    sub.add_parser("status", parents=[common], help="alias for `plan status`")
    sub.add_parser("approvals", parents=[common], help="list recorded approvals")

    s = sub.add_parser("validate", add_help=False, help="contract validator (see `validate --help`)")
    s.add_argument("rest", nargs=argparse.REMAINDER)

    s = sub.add_parser("hook", help="Claude Code hook entry point (reads the payload on stdin)")
    s.add_argument("event", choices=hooks.EVENTS)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "validate":  # pass everything through untouched, including --help
        return validate.main(argv[1:])
    args = build_parser().parse_args(argv)

    if args.cmd == "hook":
        return run_hook(args.event)
    try:
        root = Path(args.dir).resolve() if args.dir and args.cmd == "init" else (
            Path.cwd().resolve() if args.cmd == "init" else find_root(args.dir))
        store = Store(root)
        if args.cmd == "init":
            actions = install.install(root, local=args.local, enforcement=args.enforcement,
                                      python=args.python, dry_run=args.dry_run)
            if args.json:
                print(json.dumps({"dry_run": args.dry_run, "root": str(root), "actions": actions}, indent=2))
            else:
                print(("DRY RUN - nothing written. " if args.dry_run else "Installed. ") + f"Root: {root}")
                print("\n".join(f"  {a}" for a in actions))
            return 0
        if args.cmd == "uninstall":
            root = Path(args.dir).resolve() if args.dir else Path.cwd().resolve()
            actions = install.uninstall(root, local=args.local, purge_state=args.purge_state, dry_run=args.dry_run)
            if args.json:
                print(json.dumps({"dry_run": args.dry_run, "root": str(root), "actions": actions}, indent=2))
            else:
                print(("DRY RUN - nothing changed. " if args.dry_run else "Uninstalled. ") + f"Root: {root}")
                print("\n".join(f"  {a}" for a in actions))
            return 0
        if args.cmd == "doctor":
            return cmd_doctor(args, store)
        if args.cmd in ("status",) or (args.cmd == "plan" and args.plan_cmd == "status"):
            info = plan_status(store)
            print(json.dumps(info, indent=2) if args.json else _format_status(info))
            return 0
        if args.cmd == "plan":
            fn = cmd_plan_new if args.plan_cmd == "new" else cmd_plan_seal
            return print_results(fn(args, store), args.json)
        if args.cmd == "approvals":
            rows = sorted(store.approvals(), key=lambda a: a.get("decided_at", ""))
            if args.json:
                print(json.dumps(rows, indent=2))
            for a in ([] if args.json else rows):
                print(f"{a.get('decided_at')}  {a.get('gate')}  {a.get('decision'):7}  plan {str(a.get('plan_hash'))[:12]}"
                      f"  by {a.get('approver')}  scope={','.join(a.get('scope', [])) or '-'}")
            if not rows and not args.json:
                print("no approvals recorded")
            return 0
    except (validate.CliError, ConfigError, install.InstallError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 2


def _format_status(info: dict) -> str:
    lines = [f"enforcement: {info['enforcement']}", f"plan: {info['status']}" + (f" - {info['reason']}" if info["reason"] else "")]
    if "tier" in info:
        lines.append(f"tier: {info['tier']} (floor {info['tier_floor']})  hash: {str(info['plan_hash'])[:12]}")
        lines.append("files: " + (", ".join(info["files"]) or "-"))
    for gate in ("G1", "G2"):
        if gate in info:
            a = info[gate]
            lines.append(f"{gate}: " + (f"granted ({a['id']}" + (f", scope {','.join(a['scope'])}" if a["scope"] else "") + ")"
                                       if a else "not granted"))
    for v in info["validations"]:
        lines.append(f"validation {v['id']}: {v['status']}  {v['command']}")
    return "\n".join(lines)


def run_hook(event: str) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            raise ValueError("payload is not a JSON object")
    except ValueError as e:
        msg = f"agentic hook '{event}': unreadable payload ({e})"
        if event == "pre-tool-use":
            print(msg + "; blocking (fail closed)", file=sys.stderr)
            return 2
        print(msg, file=sys.stderr)
        return 0
    root = find_root(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd"))
    result = hooks.handle(event, payload, root)
    if result.out:
        print(result.out)
    if result.err:
        print(result.err, file=sys.stderr)
    return result.code
