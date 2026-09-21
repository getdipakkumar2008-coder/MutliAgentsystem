#!/usr/bin/env python3
"""Validator CLI for the agentic engineering platform contracts.

Checks that JSON Schema alone cannot express: derived review verdicts, plan
hashes, and approval bindings. Requires Python 3.9+ and `jsonschema`.

Commands
  schema          Validate documents against their schema (auto-detected from
                  the "schema" field; .jsonl files are validated line by line).
  plan-hash       Verify plan_hash, or set it with --write.
  review          Verify verdict/blocking/stats are derived correctly, or fix
                  them with --write.
  check-approval  Verify a G1/G2 approval against the plan, review and
                  validation evidence (and optionally the live git tree).

Exit codes: 0 all checks passed, 1 a check failed, 2 usage or I/O error.
Add --json after the command for machine-readable output.

Canonical plan hash: SHA-256 over the UTF-8 JSON of the plan without
`plan_hash`, keys sorted, separators (",", ":"), non-ASCII left unescaped.
Plans should not contain floats, whose text form differs across languages.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
SCHEMA_NAMES = ("plan", "review", "validation", "memory", "event", "approval")
BLOCKING_SEVERITIES = {"CRITICAL", "HIGH"}


class CliError(Exception):
    """Usage or I/O problem (exit code 2)."""


# ---------------------------------------------------------------- helpers

def load_json(path: str | Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise CliError(f"cannot read {path}: {e.strerror or e}") from e
    except json.JSONDecodeError as e:
        raise CliError(f"{path} is not valid JSON: {e}") from e


def write_json(path: str | Path, doc) -> None:
    Path(path).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_schema(name: str) -> dict:
    if name not in SCHEMA_NAMES:
        raise CliError(f"unknown schema '{name}' (expected one of: {', '.join(SCHEMA_NAMES)})")
    return load_json(SCHEMA_DIR / f"{name}.schema.json")


def schema_errors(name: str, doc) -> list[str]:
    validator = Draft202012Validator(load_schema(name), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(doc), key=lambda e: [str(p) for p in e.absolute_path])
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


def detect_schema(doc) -> str:
    tag = doc.get("schema") if isinstance(doc, dict) else None
    if not isinstance(tag, str) or tag.split("/")[0] not in SCHEMA_NAMES:
        raise CliError('cannot detect schema: missing or unknown "schema" field (use --schema)')
    return tag.split("/")[0]


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def result(check: str, ok: bool, detail: str = "") -> dict:
    return {"check": check, "ok": ok, "detail": detail}


def schema_result(label: str, name: str, doc) -> list[dict]:
    errors = schema_errors(name, doc)
    if not errors:
        return [result(f"{label}: schema {name}", True)]
    return [result(f"{label}: schema {name}", False, e) for e in errors]


# ------------------------------------------------------------ plan hash

def compute_plan_hash(plan: dict) -> str:
    body = {k: v for k, v in plan.items() if k != "plan_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cmd_plan_hash(args) -> list[dict]:
    plan = load_json(args.file)
    if not isinstance(plan, dict):
        raise CliError("plan must be a JSON object")
    computed = compute_plan_hash(plan)
    if args.write:
        plan["plan_hash"] = computed
        write_json(args.file, plan)
        return [result("plan_hash written", True, computed)] + schema_result(args.file, "plan", plan)
    stored = plan.get("plan_hash")
    if stored is None:
        return [result("plan_hash present", False, f"missing; run with --write (would be {computed})")]
    return [result("plan_hash matches content", stored == computed,
                   "" if stored == computed else f"stored {stored}, computed {computed}")] \
        + schema_result(args.file, "plan", plan)


# --------------------------------------------------------------- review

def derive_review(review: dict) -> dict:
    """Return the fields of a review that must be computed, not asserted."""
    findings = review["findings"]
    blocking = {
        f["id"]: f["severity"] in BLOCKING_SEVERITIES and f["verification"] != "refuted"
        for f in findings
    }
    if any(r["status"] != "ok" for r in review["reviewers"]):
        verdict = "INCOMPLETE"
    elif any(blocking.values()):
        verdict = "CHANGES_REQUESTED"
    else:
        verdict = "APPROVE"
    counts = Counter(f["verification"] for f in findings)
    stats = {
        "raw": max(review["stats"]["raw"], len(findings)),  # pre-dedup count is not derivable
        "unique": len(findings),
        "confirmed": counts["confirmed"],
        "unverified": counts["unverified"],
        "refuted": counts["refuted"],
    }
    return {"verdict": verdict, "blocking": blocking, "stats": stats}


def review_mismatches(review: dict) -> list[str]:
    try:
        ids = [f["id"] for f in review["findings"]]
        derived = derive_review(review)
    except (KeyError, TypeError) as e:
        return [f"cannot derive: malformed review (missing {e})"]
    problems = [f"duplicate finding id '{i}'" for i, n in Counter(ids).items() if n > 1]
    if review["verdict"] != derived["verdict"]:
        problems.append(f"verdict is {review['verdict']}, derived {derived['verdict']}")
    for f in review["findings"]:
        want = derived["blocking"][f["id"]]
        if f["blocking"] != want:
            problems.append(f"finding {f['id']}: blocking is {f['blocking']}, derived {want}")
    for key, want in derived["stats"].items():
        if review["stats"][key] != want:
            problems.append(f"stats.{key} is {review['stats'][key]}, derived {want}")
    return problems


def apply_derivation(review: dict) -> None:
    derived = derive_review(review)
    review["verdict"] = derived["verdict"]
    for f in review["findings"]:
        f["blocking"] = derived["blocking"][f["id"]]
    review["stats"] = derived["stats"]


def cmd_review(args) -> list[dict]:
    review = load_json(args.file)
    if not isinstance(review, dict):
        raise CliError("review must be a JSON object")
    if args.write:
        try:
            apply_derivation(review)
        except (KeyError, TypeError) as e:
            raise CliError(f"cannot derive: malformed review (missing {e})") from e
        write_json(args.file, review)
        out = [result("derived fields written", True, review["verdict"])]
        return out + schema_result(args.file, "review", review)
    out = schema_result(args.file, "review", review)
    problems = review_mismatches(review)
    if problems:
        out += [result("derived fields consistent", False, p) for p in problems]
    else:
        out.append(result("derived fields consistent", True, review.get("verdict", "")))
    return out


# ------------------------------------------------------------- approval

def git(repo: str, *argv: str) -> str:
    try:
        proc = subprocess.run(["git", "-C", repo, *argv], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CliError(f"git failed: {e}") from e
    if proc.returncode != 0:
        raise CliError(f"git {' '.join(argv)} failed in {repo}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def repo_head_state(repo: str) -> tuple[str, bool]:
    """(HEAD commit, dirty?) of a repo. `.agentic/` state files never count as dirt."""
    head = git(repo, "rev-parse", "HEAD")
    dirty = bool(git(repo, "status", "--porcelain", "--", ".", ":(exclude).agentic"))
    return head, dirty


def cmd_check_approval(args) -> list[dict]:
    approval = load_json(args.file)
    plan = load_json(args.plan)
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    review = (args.review, load_json(args.review)) if args.review else None
    validations = [(p, load_json(p)) for p in args.validation or []]
    repo_state = repo_head_state(args.repo) if args.repo else None
    return check_approval_docs((args.file, approval), (args.plan, plan), review, validations, repo_state, now)


def check_approval_docs(approval_l, plan_l, review_l, validations_l, repo_state, now) -> list[dict]:
    """Core approval check over already-loaded documents.

    Each *_l is a (label, document) pair (validations_l is a list of them); labels only
    name the document in results. repo_state is (HEAD, dirty) or None to skip live checks.
    """
    (a_label, approval), (p_label, plan) = approval_l, plan_l
    out = schema_result(a_label, "approval", approval) + schema_result(p_label, "plan", plan)
    if not all(r["ok"] for r in out):
        return out  # fail closed: do not reason over malformed documents

    out.append(result("gate granted", approval["decision"] == "granted", f"decision={approval['decision']}"))
    computed = compute_plan_hash(plan)
    out.append(result("plan content matches its plan_hash", plan["plan_hash"] == computed))
    out.append(result("approval bound to current plan", approval["plan_hash"] == computed,
                      "" if approval["plan_hash"] == computed
                      else "plan changed since approval; approval is invalidated"))
    if "expires_at" in approval:
        out.append(result("approval not expired", parse_time(approval["expires_at"]) > now,
                          f"expires_at={approval['expires_at']}"))

    if approval["gate"] == "G2" and approval["decision"] == "granted":
        out += check_g2_evidence(approval, plan, review_l, validations_l, repo_state)
    return out


def check_g2_evidence(approval: dict, plan: dict, review_l, validations_l, repo_state) -> list[dict]:
    out: list[dict] = []
    if review_l is None:
        out.append(result("review supplied", False, "G2 requires --review"))
    else:
        r_label, review = review_l
        rs = schema_result(r_label, "review", review)
        out += rs
        if all(r["ok"] for r in rs):
            problems = review_mismatches(review)
            out.append(result("review derived fields consistent", not problems, "; ".join(problems)))
            out.append(result("review verdict is APPROVE", review["verdict"] == "APPROVE",
                              f"verdict={review['verdict']}"))
            out.append(result("approval references this review", review["id"] == approval["review_id"],
                              f"approval.review_id={approval['review_id']}, review.id={review['id']}"))

    validations: dict[str, dict] = {}
    for label, doc in validations_l:
        vs = schema_result(label, "validation", doc)
        out += vs
        if all(r["ok"] for r in vs):
            validations[doc["id"]] = doc

    for vid in approval["validation_ids"]:
        v = validations.get(vid)
        if v is None:
            out.append(result(f"validation {vid} supplied", False, "pass its file with --validation"))
            continue
        out.append(result(f"validation {vid} passed", v["status"] == "passed",
                          f"{v['command']!r} status={v['status']}"))
        out.append(result(f"validation {vid} ran on approved commit", v["git_head"] == approval["git_head"],
                          f"validation.git_head={v['git_head']!r}, approval.git_head={approval['git_head']!r}"))
        out.append(result(f"validation {vid} ran on a clean tree", v["worktree_dirty"] is False))

    passed = {v["command"] for vid, v in validations.items()
              if vid in approval["validation_ids"] and v["status"] == "passed"}
    for cmd in plan["validation"]:
        out.append(result(f"plan validation covered: {cmd}", cmd in passed,
                          "" if cmd in passed else "no passed validation with this exact command"))

    if repo_state is not None:
        head, dirty = repo_state
        out.append(result("repo HEAD equals approved commit", head == approval["git_head"],
                          f"HEAD={head}, approved={approval['git_head']}"))
        out.append(result("repo tree is clean", not dirty))
    return out


# ------------------------------------------------------------------ schema

def cmd_schema(args) -> list[dict]:
    out: list[dict] = []
    for path in args.files:
        if Path(path).suffix == ".jsonl":
            try:
                lines = Path(path).read_text(encoding="utf-8").splitlines()
            except OSError as e:
                raise CliError(f"cannot read {path}: {e.strerror or e}") from e
            for n, line in enumerate(lines, 1):
                if not line.strip():
                    continue
                try:
                    doc = json.loads(line)
                except json.JSONDecodeError as e:
                    out.append(result(f"{path}:{n}: parse", False, str(e)))
                    continue
                out += schema_result(f"{path}:{n}", args.schema or detect_schema(doc), doc)
        else:
            doc = load_json(path)
            out += schema_result(path, args.schema or detect_schema(doc), doc)
    return out


# --------------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")

    p = argparse.ArgumentParser(prog="validate", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("schema", parents=[common], help="validate documents against their schema")
    s.add_argument("files", nargs="+")
    s.add_argument("--schema", choices=SCHEMA_NAMES, help="override auto-detection")
    s.set_defaults(fn=cmd_schema)

    s = sub.add_parser("plan-hash", parents=[common], help="verify or set plan_hash")
    s.add_argument("file")
    s.add_argument("--write", action="store_true", help="store the computed hash in the file")
    s.set_defaults(fn=cmd_plan_hash)

    s = sub.add_parser("review", parents=[common], help="verify or fix derived review fields")
    s.add_argument("file")
    s.add_argument("--write", action="store_true", help="rewrite verdict, blocking flags and stats")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("check-approval", parents=[common], help="verify an approval against its evidence")
    s.add_argument("file", help="approval JSON")
    s.add_argument("--plan", required=True, help="plan JSON the approval refers to")
    s.add_argument("--review", help="review JSON (required for G2)")
    s.add_argument("--validation", action="append", metavar="FILE",
                   help="validation JSON; repeat for each (required for G2)")
    s.add_argument("--repo", help="also check this git repo's HEAD and cleanliness (G2)")
    s.add_argument("--now", help="ISO-8601 time to evaluate expiry against (default: now)")
    s.set_defaults(fn=cmd_check_approval)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        results = args.fn(args)
    except CliError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    ok = all(r["ok"] for r in results)
    if args.json:
        print(json.dumps({"ok": ok, "results": results}, indent=2))
    else:
        for r in results:
            line = f"{'PASS' if r['ok'] else 'FAIL'}  {r['check']}"
            print(f"{line}  -- {r['detail']}" if r["detail"] else line)
        print("\nOK" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
