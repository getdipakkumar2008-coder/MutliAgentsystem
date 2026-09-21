"""Tests for hooks.py: the enforcement behavior the harness actually sees."""
import json
import os
import unittest
from datetime import timedelta
from unittest import mock

import support
from support import bash, events, pre, prompt, ran, seal, write
from agentic import hooks, validate

from test_validate import make_review


class PreToolUse(unittest.TestCase):
    def test_write_without_plan_blocks_with_exit_2_and_logs(self):
        store = support.new_project(self)
        r = write(store, "src/a.py")
        self.assertEqual(r.code, 2)
        self.assertIn("BLOCKED [plan-none]", r.err)
        self.assertEqual([(e["type"], e["payload"]["rule"]) for e in events(store)], [("tool.block", "plan-none")])

    def test_planned_write_and_non_write_tools_pass_silently(self):
        store = support.new_project(self)
        seal(store)
        for r in (write(store, "src/a.py"), pre(store, "Read", file_path="x"), pre(store, "Glob", pattern="*")):
            self.assertEqual((r.code, r.out, r.err), (0, "", ""))

    def test_edit_and_multiedit_and_notebook_are_covered(self):
        store = support.new_project(self)
        seal(store)
        self.assertEqual(pre(store, "Edit", file_path=str(store.root / "src/b.py"), new_string="y").code, 2)
        self.assertEqual(pre(store, "NotebookEdit", notebook_path=str(store.root / "n.ipynb"), new_source="y").code, 2)
        multi = pre(store, "MultiEdit", file_path=str(store.root / "src/a.py"), edits=[{"old_string": "a", "new_string": "b"}])
        self.assertEqual(multi.code, 0)

    def test_secret_blocks_and_never_echoes_the_value(self):
        store = support.new_project(self)
        seal(store)
        secret = "AKIA" + "ABCDEFGHIJKLMNOP"
        for r in (write(store, "src/a.py", f"k = '{secret}'"), bash(store, f"export KEY={secret}")):
            self.assertEqual(r.code, 2)
            self.assertIn("aws-access-key", r.err)
        blob = json.dumps(events(store)) + r.err
        self.assertNotIn(secret, blob)

    def test_secret_scan_modes(self):
        secret = "AKIA" + "ABCDEFGHIJKLMNOP"
        warn = support.new_project(self, secret_scan="warn")
        seal(warn)
        self.assertEqual(write(warn, "src/a.py", f"k='{secret}'").code, 0)
        self.assertIn("secret.detected", [e["type"] for e in events(warn)])
        off = support.new_project(self, secret_scan="off")
        seal(off)
        self.assertEqual(write(off, "src/a.py", f"k='{secret}'").code, 0)

    def test_warn_mode_allows_soft_rules_but_not_integrity_rules(self):
        store = support.new_project(self, enforcement="warn")
        r = write(store, "src/a.py")  # no plan: soft rule
        self.assertEqual(r.code, 0)
        self.assertIn("warn mode", json.loads(r.out)["systemMessage"])
        self.assertFalse(events(store)[-1]["payload"]["enforced"])
        self.assertEqual(write(store, ".agentic/approvals/x.json").code, 2)  # protected path: hard
        self.assertEqual(bash(store, "python scripts/agentic.py hook session-start").code, 2)  # forgery: hard

    def test_off_mode_skips_gates(self):
        store = support.new_project(self, enforcement="off")
        self.assertEqual(write(store, "src/a.py").code, 0)
        self.assertEqual(bash(store, "git push --force").code, 0)

    def test_ask_is_a_json_permission_decision_with_exit_0(self):
        store = support.new_project(self)
        r = bash(store, "git reset --hard")
        self.assertEqual(r.code, 0)
        out = json.loads(r.out)["hookSpecificOutput"]
        self.assertEqual((out["hookEventName"], out["permissionDecision"]), ("PreToolUse", "ask"))

    def test_fail_closed_on_broken_config_but_not_for_other_hooks(self):
        store = support.new_project(self)
        store.config_path.write_text("{not json")
        r = write(store, "src/a.py")
        self.assertEqual(r.code, 2)
        self.assertIn("fail closed", r.err)
        self.assertEqual(hooks.handle("session-start", {}, store.root).code, 0)
        self.assertEqual(ran(store, "pytest").code, 0)

    def test_debug_capture_only_when_enabled(self):
        store = support.new_project(self)
        write(store, "src/a.py")
        self.assertFalse((store.dir / "debug").exists())
        with mock.patch.dict(os.environ, {"AGENTIC_HOOK_DEBUG": "1"}):
            write(store, "src/a.py")
        self.assertTrue((store.dir / "debug" / "pre-tool-use.jsonl").exists())


class ValidationRecorder(unittest.TestCase):
    def setUp(self):
        self.store = support.new_project(self)
        seal(self.store, validation=("python -m pytest -q", "ruff check ."))

    def recorded(self):
        return sorted(self.store.validations(), key=lambda v: v["id"])

    def test_pass_and_fail_are_recorded_as_valid_contracts_with_evidence(self):
        ran(self.store, "python -m pytest -q", exit_code=0, output="3 passed")
        ran(self.store, "ruff check .", exit_code=1, output="E501 line too long")
        good, bad = self.recorded()[0], self.recorded()[1]
        self.assertEqual([(v["command"], v["status"]) for v in (good, bad)],
                         [("python -m pytest -q", "passed"), ("ruff check .", "failed")])
        for v in (good, bad):
            self.assertEqual(validate.schema_errors("validation", v), [])
            self.assertTrue((self.store.root / v["evidence_ref"]).exists())
        self.assertEqual(bad["exit_code"], 1)

    def test_failure_event_records_failed_with_parsed_exit_code(self):
        ran(self.store, "python -m pytest -q", exit_code=5, output="boom", event="post-tool-use-failure")
        v = self.recorded()[0]
        self.assertEqual((v["status"], v["exit_code"]), ("failed", 5))

    def test_real_claude_code_success_payload_has_no_exit_code_and_counts_as_passed(self):
        """Verified live (Claude Code 2.1.278): PostToolUse fires only on success and omits the exit code."""
        real = {"stdout": "3 passed", "stderr": "", "interrupted": False, "isImage": False, "noOutputExpected": False}
        ran(self.store, "python -m pytest -q", extra={"tool_response": real})
        v = self.recorded()[0]
        self.assertEqual((v["status"], v["exit_code"]), ("passed", 0))
        self.assertEqual(validate.schema_errors("validation", v), [])

    def test_real_claude_code_failure_payload(self):
        """Verified live: failures fire PostToolUseFailure with error 'Exit code N' and no tool_response."""
        hooks.handle("post-tool-use-failure", {
            "session_id": "t", "cwd": str(self.store.root), "tool_name": "Bash", "tool_response": None,
            "tool_input": {"command": "python -m pytest -q"}, "error": "Exit code 3", "is_interrupt": False},
            self.store.root)
        v = self.recorded()[0]
        self.assertEqual((v["status"], v["exit_code"]), ("failed", 3))

    def test_interrupted_failure_is_unverified_not_failed(self):
        hooks.handle("post-tool-use-failure", {
            "session_id": "t", "tool_name": "Bash", "tool_input": {"command": "python -m pytest -q"},
            "error": "Command interrupted", "is_interrupt": True}, self.store.root)
        self.assertEqual(self.recorded()[0]["status"], "unverified")

    def test_distrusting_config_records_missing_exit_code_as_unverified(self):
        strict = support.new_project(self, trust_post_tool_use_success=False)
        seal(strict)
        ran(strict, "pytest", exit_code=None)
        v = strict.validations()[0]
        self.assertEqual(v["status"], "unverified")
        self.assertEqual(validate.schema_errors("validation", v), [])

    def test_interrupted_run_is_unverified(self):
        ran(self.store, "python -m pytest -q", extra={"tool_response": {"output": "", "exit_code": 0, "interrupted": True}})
        self.assertEqual(self.recorded()[0]["status"], "unverified")

    def test_only_faithful_commands_count(self):
        for cmd in ("python -m pytest -q | tail -3", "python -m pytest -q; true", "python -m pytest -q || true",
                    "python -m pytest -q tests/one_test.py", "echo python -m pytest -q", "ls"):
            ran(self.store, cmd)
        self.assertEqual(self.recorded(), [])
        ran(self.store, "cd sub && python -m pytest -q")
        ran(self.store, "python   -m pytest   -q")  # whitespace-normalized
        self.assertEqual([v["command"] for v in self.recorded()], ["python -m pytest -q"] * 2)

    def test_output_is_redacted_in_evidence(self):
        secret = "AKIA" + "ABCDEFGHIJKLMNOP"
        ran(self.store, "python -m pytest -q", output=f"key={secret}")
        text = (self.store.root / self.recorded()[0]["evidence_ref"]).read_text()
        self.assertNotIn(secret, text)
        self.assertIn("REDACTED", text)

    def test_records_head_and_ignores_agentic_dir_dirt(self):
        store = support.new_project(self, use_git=True)
        seal(store)
        ran(store, "pytest")
        v = store.validations()[0]
        self.assertEqual((v["git_head"], v["worktree_dirty"]), (support.git(store.root, "rev-parse", "HEAD"), False))
        (store.root / "dirty.txt").write_text("x")
        ran(store, "pytest")
        self.assertTrue(max(store.validations(), key=lambda v: v["id"])["worktree_dirty"])


class Gates(unittest.TestCase):
    def setUp(self):
        self.store = support.new_project(self)
        self.now = support.now_utc()

    def test_approve_requires_a_valid_plan(self):
        r = prompt(self.store, "/approve G1", self.now)
        self.assertEqual(r.code, 2)
        self.assertIn("no plan", r.err)
        support.seal(self.store, tier="T1", files=tuple(f"s/{i}.py" for i in range(6)))  # understated
        self.assertIn("at least T2", prompt(self.store, "/approve G1", self.now).err)
        self.assertEqual(self.store.approvals(), [])

    def test_g1_approval_is_recorded_bound_and_logged(self):
        plan = seal(self.store, tier="T2")
        r = prompt(self.store, "/approve G1 looks good", self.now)
        self.assertEqual(r.code, 0)
        self.assertIn("G1 APPROVED", r.out)
        (a,) = self.store.approvals()
        self.assertEqual((a["gate"], a["decision"], a["plan_hash"], a["comment"]), ("G1", "granted", plan["plan_hash"], "looks good"))
        self.assertEqual(validate.schema_errors("approval", a), [])
        self.assertIn("approval.granted", [e["type"] for e in events(self.store)])

    def test_prompt_matching_is_anchored(self):
        seal(self.store, tier="T2")
        for text in ("please approve G1 when ready", "I do not approve G1", "approve G3", "hello", ""):
            self.assertEqual(prompt(self.store, text, self.now), hooks.HookResult(), text)
        for i, text in enumerate(("/approve G1", "approve g1", "  /agentic:approve G1", "APPROVE G1\nthanks")):
            self.assertEqual(prompt(self.store, text, self.now + timedelta(seconds=i)).code, 0, text)
        self.assertEqual(len(self.store.approvals()), 4)

    def test_user_input_field_variant_is_accepted(self):
        seal(self.store, tier="T2")
        r = hooks.handle("user-prompt-submit", {"session_id": "t", "user_input": "/approve G1"}, self.store.root, self.now)
        self.assertEqual(r.code, 0)
        self.assertEqual(len(self.store.approvals()), 1)

    def test_deny_then_reapprove_latest_wins_even_within_one_second(self):
        seal(self.store, tier="T2")
        prompt(self.store, "/approve G1", self.now)
        prompt(self.store, "/deny G1", self.now + timedelta(microseconds=10))
        self.assertEqual(write(self.store, "src/a.py").code, 2)
        prompt(self.store, "/approve G1", self.now + timedelta(microseconds=20))
        self.assertEqual(write(self.store, "src/a.py").code, 0)

    def test_approval_expires_by_ttl(self):
        store = support.new_project(self, approval_ttl_minutes={"G1": 30})
        seal(store, tier="T2")
        prompt(store, "/approve G1", self.now)
        self.assertEqual(write(store, "src/a.py", now=self.now + timedelta(minutes=29)).code, 0)
        self.assertEqual(write(store, "src/a.py", now=self.now + timedelta(minutes=31)).code, 2)

    def test_only_configured_approvers(self):
        store = support.new_project(self, approvers={"G1": ["someone-else"]})
        seal(store, tier="T2")
        r = prompt(store, "/approve G1")
        self.assertEqual(r.code, 2)
        self.assertIn("not a configured G1 approver", r.err)


class DeliveryGate(unittest.TestCase):
    """G2 end to end on a real git repo: evidence, scope, and staleness."""

    def setUp(self):
        self.store = support.new_project(self, use_git=True)
        self.plan = seal(self.store, validation=("pytest",))
        self.now = support.now_utc()

    def evidence(self, exit_code=0, review=True):
        ran(self.store, "pytest", exit_code=exit_code)
        if review:
            self.store.write_json(self.store.review_path, make_review())

    def test_refused_without_review_validation_or_with_failures(self):
        r = prompt(self.store, "/approve G2 push", self.now)
        self.assertIn("no review recorded", r.err)
        self.store.write_json(self.store.review_path, make_review())
        r = prompt(self.store, "/approve G2 push", self.now)
        self.assertIn("plan validation covered: pytest", r.err)
        self.evidence(exit_code=1)
        r = prompt(self.store, "/approve G2 push", self.now)
        self.assertEqual(r.code, 2)
        self.assertIn("validation", r.err)
        self.assertEqual(self.store.approvals(), [])

    def test_refused_for_blocking_review(self):
        self.evidence()
        self.store.write_json(self.store.review_path, make_review([{
            "id": "f1", "severity": "HIGH", "file": "a.py", "evidence": "e", "impact": "i", "fix": "x",
            "verification": "confirmed", "blocking": True}]))
        r = prompt(self.store, "/approve G2 push", self.now)
        self.assertIn("review verdict is APPROVE", r.err)

    def test_refused_when_tree_dirty_or_evidence_from_older_commit(self):
        self.evidence()
        (self.store.root / "new.txt").write_text("x")
        self.assertIn("tree is clean", prompt(self.store, "/approve G2 push", self.now).err)
        support.git(self.store.root, "add", "new.txt")
        support.git(self.store.root, "commit", "-qm", "more")
        self.assertIn("approved commit", prompt(self.store, "/approve G2 push", self.now).err)

    def test_g2_scope_gates_delivery_commands(self):
        self.evidence()
        r = prompt(self.store, "/approve G2 push", self.now)
        self.assertEqual(r.code, 0, r.err)
        (g2,) = [a for a in self.store.approvals() if a["gate"] == "G2"]
        self.assertEqual(g2["scope"], ["push"])
        self.assertEqual(bash(self.store, "git push origin main").code, 0)          # in scope: falls through
        blocked = bash(self.store, "npm publish")
        self.assertEqual(blocked.code, 2)
        self.assertIn("not covered", blocked.err)
        self.assertEqual(bash(self.store, "git push --force").code, 2)              # never allowed

    def test_default_scope_is_commit_only(self):
        self.evidence()
        prompt(self.store, "/approve G2", self.now)
        self.assertEqual(self.store.approvals()[0]["scope"], ["commit"])
        self.assertEqual(bash(self.store, "git push").code, 2)

    def test_new_commit_or_dirty_tree_after_approval_blocks_delivery(self):
        self.evidence()
        prompt(self.store, "/approve G2 push", self.now)
        (self.store.root / "late.txt").write_text("x")
        self.assertIn("uncommitted changes", bash(self.store, "git push").err)
        support.git(self.store.root, "add", "late.txt")
        support.git(self.store.root, "commit", "-qm", "late")
        self.assertIn("HEAD changed", bash(self.store, "git push").err)

    def test_plan_change_voids_g2(self):
        self.evidence()
        prompt(self.store, "/approve G2 push", self.now)
        plan = self.store.read_plan()[0]
        plan["scope"].append("x")
        self.store.write_json(self.store.plan_path, plan)
        self.assertEqual(bash(self.store, "git push").code, 2)


class SessionStart(unittest.TestCase):
    def test_reports_mode_and_plan_state(self):
        store = support.new_project(self)
        out = hooks.handle("session-start", {}, store.root).out
        self.assertIn("enforcement=enforce", out)
        self.assertIn("Plan: none", out)
        seal(store, tier="T2")
        self.assertIn("needs_g1", hooks.handle("session-start", {}, store.root).out)

    def test_unknown_event_is_harmless(self):
        self.assertEqual(hooks.handle("nope", {}, support.new_project(self).root).code, 0)


if __name__ == "__main__":
    unittest.main()
