"""Claude Code hook handlers.

Contract with the harness (kept deliberately tolerant of payload variants):
  * exit 2 + stderr            -> block (fail closed on any internal error in pre-tool-use)
  * exit 0 + JSON on stdout    -> "ask" decisions, warnings, additional context
  * exit 0 + plain stdout      -> context for UserPromptSubmit / SessionStart
Set AGENTIC_HOOK_DEBUG=1 to capture every raw payload to .agentic/debug/<event>.jsonl.
"""
from __future__ import annotations

import getpass
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import policy, secretscan, validate
from .store import Store, iso, iso_us, utcnow

EVENTS = ("pre-tool-use", "post-tool-use", "post-tool-use-failure", "user-prompt-submit", "session-start")
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
LAUNCHER = Path(__file__).resolve().parent.parent / "scripts" / "agentic.py"
MAX_EVIDENCE_CHARS = 200_000
_GATE_CMD = re.compile(r"^\s*/?(?:agentic[:\s-]*)?(?P<verb>approve|deny)\s+(?P<gate>G[12])\b(?P<rest>.*)$",
                       re.IGNORECASE | re.DOTALL)


@dataclass
class HookResult:
    code: int = 0
    out: str = ""
    err: str = ""


def handle(event: str, payload: dict, root, now: datetime | None = None) -> HookResult:
    now = now or utcnow()
    store = Store(root)
    if event not in EVENTS:
        return HookResult(0, err=f"agentic: unknown hook event '{event}'")
    _debug_capture(store, event, payload)
    try:
        cfg = store.config()
        if event == "pre-tool-use":
            return _pre_tool_use(store, cfg, payload, now)
        if event in ("post-tool-use", "post-tool-use-failure"):
            return _record_validation(store, cfg, payload, now, failed=event.endswith("failure"))
        if event == "user-prompt-submit":
            return _user_prompt_submit(store, cfg, payload, now)
        return _session_start(store, cfg, now)
    except Exception as e:  # noqa: BLE001 - a hook must never crash the harness
        msg = f"agentic hook '{event}' failed: {type(e).__name__}: {e}. Run `python {LAUNCHER} doctor`."
        if event == "pre-tool-use":
            return HookResult(2, err=msg + " Blocking because the guard cannot run (fail closed).")
        return HookResult(0, err=msg)


def _debug_capture(store: Store, event: str, payload: dict) -> None:
    import os
    if os.environ.get("AGENTIC_HOOK_DEBUG") != "1":
        return
    try:
        d = store.dir / "debug"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / f"{event}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


# ------------------------------------------------------------ pre-tool-use

def _write_info(tool: str, ti: dict) -> tuple[list[str], str]:
    targets = [ti[k] for k in ("file_path", "notebook_path", "path") if isinstance(ti.get(k), str)]
    pieces = [ti[k] for k in ("content", "new_string", "new_source", "file_text") if isinstance(ti.get(k), str)]
    for edit in ti.get("edits") or []:
        if isinstance(edit, dict):
            if isinstance(edit.get("file_path"), str):
                targets.append(edit["file_path"])
            pieces += [edit[k] for k in ("new_string", "new_text", "file_text") if isinstance(edit.get(k), str)]
    return targets, "\n".join(pieces)


def _pre_tool_use(store: Store, cfg: dict, p: dict, now: datetime) -> HookResult:
    tool = p.get("tool_name") or ""
    ti = p.get("tool_input") or {}
    sid = p.get("session_id") or "local"
    if tool in WRITE_TOOLS:
        targets, text = _write_info(tool, ti)
    elif tool == "Bash":
        targets, text = [], str(ti.get("command", ""))
    else:
        return HookResult()

    if cfg["secret_scan"] != "off" and text:
        found = secretscan.scan_text(text)
        if found:
            summary = ", ".join(f"{f.rule} (line {f.line})" for f in found[:5])
            store.append_event("secret.detected", sid, payload={"tool": tool, "findings": summary,
                                                                "mode": cfg["secret_scan"]})
            if cfg["secret_scan"] == "block":
                return _block(store, sid, tool, policy.deny(
                    "secret", f"possible secret in {'command' if tool == 'Bash' else 'content'}: {summary}. "
                    "Use an environment variable or secret manager; add the marker "
                    f"'{secretscan.ALLOW_MARKER}' on the line only for test fixtures.", hard=True), targets)

    if cfg["enforcement"] == "off":
        return HookResult()
    if tool == "Bash":
        decision = policy.decide_bash(store, cfg, text, now)
    else:
        decision = policy.ALLOW
        for target in targets:
            decision = policy.decide_write(store, cfg, target, now)
            if decision.action != "allow":
                break
    return _apply(store, cfg, sid, tool, decision, targets or [text])


def _apply(store: Store, cfg: dict, sid: str, tool: str, d: policy.Decision, targets) -> HookResult:
    if d.action == "allow":
        return HookResult()
    if d.action == "ask":
        return HookResult(0, out=json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "ask",
            "permissionDecisionReason": f"agentic: {d.reason}"}}))
    if cfg["enforcement"] != "enforce" and not d.hard:
        store.append_event("tool.block", sid, payload={"tool": tool, "rule": d.rule, "reason": d.reason,
                                                       "target": targets[0] if targets else "", "enforced": False})
        return HookResult(0, out=json.dumps({"systemMessage": f"agentic (warn mode, not blocked) [{d.rule}]: {d.reason}"}))
    return _block(store, sid, tool, d, targets)


def _block(store: Store, sid: str, tool: str, d: policy.Decision, targets) -> HookResult:
    store.append_event("tool.block", sid, payload={"tool": tool, "rule": d.rule, "reason": d.reason,
                                                   "target": targets[0] if targets else "", "enforced": True})
    return HookResult(2, err=f"agentic BLOCKED [{d.rule}]: {d.reason}")


# ------------------------------------------------- post-tool-use: validations

def _matches_validation(command: str, known: list[str]) -> str | None:
    """The plan/config validation command this run *fully* represents, or None.

    Only `&&` chains qualify (their exit code is non-zero if any part fails), and every
    non-`cd` part must be exactly one known command. `pytest | tail` or `pytest; true`
    would report the wrong exit code and are not recorded as evidence.
    """
    parts = policy.split_commands(command)
    if any(op not in ("&&", "") for _, op in parts):
        return None
    body = [" ".join(seg.split()) for seg, _ in parts if not re.match(r"^cd(\s|$)", seg)]
    normalized = {" ".join(k.split()): k for k in known}
    if len(body) == 1 and body[0] in normalized:
        return normalized[body[0]]
    return None


def _extract_result(p: dict, failed: bool) -> tuple[int | None, str, bool]:
    """(exit_code or None, output text, interrupted) from whichever fields the payload carries."""
    resp = p.get("tool_response")
    exit_code, output, interrupted = None, "", False
    if isinstance(resp, dict):
        for key in ("exit_code", "exitCode", "returncode", "return_code"):
            if isinstance(resp.get(key), int) and not isinstance(resp.get(key), bool):
                exit_code = resp[key]
                break
        output = "\n".join(str(resp[k]) for k in ("output", "stdout", "stderr") if resp.get(k))
        interrupted = bool(resp.get("interrupted") or resp.get("timed_out"))
    elif isinstance(resp, str):
        output = resp
    interrupted = interrupted or bool(p.get("is_interrupt"))
    if failed:
        error = str(p.get("error") or "")
        output = output or error
        if exit_code is None:
            m = re.search(r"[Ee]xit code[:\s]+(-?\d+)", error)
            exit_code = int(m.group(1)) if m else 1  # fired on failure, so it cannot have been 0
        if exit_code == 0:
            exit_code = 1
    return exit_code, output, interrupted


def _record_validation(store: Store, cfg: dict, p: dict, now: datetime, failed: bool) -> HookResult:
    if p.get("tool_name") != "Bash":
        return HookResult()
    command = str((p.get("tool_input") or {}).get("command", ""))
    plan, _ = store.read_plan()
    known = list(cfg["validation_commands"]) + [c for c in (plan or {}).get("validation", []) if isinstance(c, str)]
    matched = _matches_validation(command, known)
    if matched is None:
        return HookResult()

    exit_code, output, interrupted = _extract_result(p, failed)
    reason = ""
    if interrupted:
        status, reason = "unverified", "command was interrupted or timed out"
    elif exit_code is None:
        if cfg["trust_post_tool_use_success"]:
            status, exit_code = "passed", 0
        else:
            status, reason = "unverified", "hook payload carried no exit code"
    else:
        status = "passed" if exit_code == 0 else "failed"

    vid = f"v-{now.strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:6]}"  # sorts chronologically
    head, dirty = store.git_state()
    store.evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence = store.evidence_dir / f"{vid}.txt"
    evidence.write_text(secretscan.redact(output)[:MAX_EVIDENCE_CHARS], encoding="utf-8")

    doc = {"schema": "validation/2", "id": vid, "command": matched, "cwd": str(p.get("cwd") or store.root),
           "status": status, "summary": f"{matched}: {status}", "git_head": head, "worktree_dirty": dirty}
    if exit_code is not None:
        doc["exit_code"] = exit_code
    if status in ("passed", "failed"):
        doc["evidence_ref"] = f".agentic/evidence/{vid}.txt"
    else:
        doc["reason"] = reason
    problems = validate.schema_errors("validation", doc)
    if problems:
        raise ValueError("internal: recorded validation violates its schema: " + "; ".join(problems))
    store.write_json(store.validations_dir / f"{vid}.json", doc)
    store.append_event("validation.recorded", p.get("session_id") or "local",
                       payload={"id": vid, "command": matched, "status": status})
    note = f"agentic: recorded validation {vid} for `{matched}`: {status}" + (f" ({reason})" if reason else "")
    return HookResult(0, out=json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUseFailure" if failed else "PostToolUse", "additionalContext": note}}))


# ------------------------------------------------- user-prompt-submit: gates

def _user_prompt_submit(store: Store, cfg: dict, p: dict, now: datetime) -> HookResult:
    text = p.get("prompt")
    if not isinstance(text, str):
        text = p.get("user_input") if isinstance(p.get("user_input"), str) else ""
    m = _GATE_CMD.match(text)
    if not m:
        return HookResult()
    return _decide_gate(store, cfg, p.get("session_id") or "local", now,
                        m.group("verb").lower(), m.group("gate").upper(), m.group("rest"))


def _parse_rest(rest: str) -> tuple[list[str], str]:
    """Scopes (`commit push`, `scope=push,deploy`) and free-text comment from the text after the gate."""
    scope, comment = set(), []
    for tok in rest.replace(",", " ").split():
        word = tok.lower().removeprefix("scope=")
        if word in policy.KNOWN_SCOPES:
            scope.add(word)
        elif not tok.lower().startswith("scope="):  # an unknown scope value only ever narrows the grant
            comment.append(tok)
    return sorted(scope, key=policy.KNOWN_SCOPES.index), " ".join(comment)


def _refuse(store: Store, sid: str, gate: str, lines: list[str]) -> HookResult:
    store.append_event("approval.requested", sid, payload={"gate": gate, "refused": lines[:10]})
    body = "\n".join(f"  - {line}" for line in lines)
    return HookResult(2, err=f"agentic: {gate} approval refused; nothing was recorded.\n{body}")


def _decide_gate(store: Store, cfg: dict, sid: str, now: datetime, verb: str, gate: str, rest: str) -> HookResult:
    approver = getpass.getuser()
    allowed = cfg["approvers"].get(gate, [])
    if allowed and approver not in allowed:
        return _refuse(store, sid, gate, [f"user '{approver}' is not a configured {gate} approver"])
    st = policy.plan_state(store, cfg, now)
    if st.status in ("none", "invalid", "understated"):
        return _refuse(store, sid, gate, [st.reason])
    plan = st.plan
    granted = verb == "approve"
    scope, comment = _parse_rest(rest)

    approval = {"schema": "approval/1",
                "id": f"ap-{gate}-{now.strftime('%Y%m%d%H%M%S%f')}-{plan['plan_hash'][:8]}",
                "session_id": sid, "gate": gate, "decision": "granted" if granted else "denied",
                "approver": approver, "plan_hash": plan["plan_hash"], "decided_at": iso_us(now)}
    if comment:
        approval["comment"] = comment
    ttl = cfg["approval_ttl_minutes"].get(gate)
    if granted and ttl:
        approval["expires_at"] = iso(now + timedelta(minutes=ttl))

    if gate == "G2" and granted:
        review, review_err = store.read_review()
        if review is None:
            return _refuse(store, sid, gate, [review_err])
        head, dirty = store.git_state()
        latest: dict[str, dict] = {}
        for v in store.validations():
            if v.get("command") in plan["validation"] and v.get("id", "") > latest.get(v["command"], {}).get("id", ""):
                latest[v["command"]] = v
        approval.update(git_head=head, review_id=review.get("id", ""), scope=scope or ["commit"],
                        validation_ids=sorted(v["id"] for v in latest.values()))
        results = validate.check_approval_docs(("approval", approval), ("plan", plan), ("review", review),
                                               [(v["id"], v) for v in latest.values()], (head, dirty), now)
        failed = [f"{r['check']}: {r['detail']}" if r["detail"] else r["check"] for r in results if not r["ok"]]
        if failed:
            return _refuse(store, sid, gate, failed)

    errors = validate.schema_errors("approval", approval)
    if errors:
        return _refuse(store, sid, gate, errors)
    store.write_json(store.approvals_dir / f"{approval['id']}.json", approval)
    store.append_event("approval.granted" if granted else "approval.denied", sid,
                       payload={"gate": gate, "approval_id": approval["id"], "plan_hash": plan["plan_hash"],
                                "scope": approval.get("scope", [])})
    if granted:
        extra = f" Scope: {', '.join(approval['scope'])}." if "scope" in approval else ""
        msg = (f"agentic: {gate} APPROVED by {approver} for plan {plan['plan_hash'][:12]} "
               f"(tier {plan['tier']}, id {approval['id']}).{extra} Approval is void if the plan changes.")
    else:
        msg = f"agentic: {gate} DENIED by {approver} for plan {plan['plan_hash'][:12]}. Revise the plan and ask again."
    return HookResult(0, out=msg)


# ------------------------------------------------------------ session-start

def _session_start(store: Store, cfg: dict, now: datetime) -> HookResult:
    st = policy.plan_state(store, cfg, now)
    lines = [f"agentic: enforcement={cfg['enforcement']}, secret_scan={cfg['secret_scan']}."]
    if st.plan is None:
        lines.append(f"Plan: {st.status} - {st.reason}")
    else:
        lines.append(f"Plan: tier {st.plan['tier']}, {st.plan['plan_hash'][:12]}, status {st.status}"
                     + (f" - {st.reason}" if st.reason else "."))
    lines.append(f"Workflow: plan before writing (T2/T3 need the user's `/approve G1`); deliver (push/publish/deploy) "
                 f"only after `/approve G2`. Never write .agentic/approvals, validations, events or settings. "
                 f"CLI: python {LAUNCHER} plan new|seal|status, doctor.")
    return HookResult(0, out="\n".join(lines))
