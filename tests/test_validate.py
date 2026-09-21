"""Tests for validate.py. Run: python -m unittest discover -s doc/tools/tests -v"""
import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentic import validate  # noqa: E402

TS = "2026-09-20T10:00:00Z"
HEAD = "b" * 40


def make_plan(**over):
    plan = {
        "schema": "plan/2", "tier": "T2", "requirements": ["r"], "scope": [], "non_goals": [],
        "files": [], "phases": [{"id": "p1", "goal": "g", "tests_first": []}], "risks": [],
        "security_plan": ["s"], "rollback": "", "validation": ["pytest", "ruff check"],
        "acceptance": ["a"], "plan_hash": "0" * 64,
    }
    plan.update(over)
    plan["plan_hash"] = validate.compute_plan_hash(plan)
    return plan


def make_finding(**over):
    f = {"id": "f1", "severity": "HIGH", "file": "a.py", "evidence": "e", "impact": "i", "fix": "x",
         "verification": "confirmed", "blocking": True}
    f.update(over)
    return f


def make_review(findings=None, reviewers=None, **over):
    findings = [] if findings is None else findings
    review = {
        "schema": "review/2", "id": "rev1", "verdict": "APPROVE",
        "reviewers": reviewers or [{"agent": "quality", "run_id": "r1", "status": "ok"}],
        "findings": findings, "stats": {"raw": 0, "unique": 0, "confirmed": 0, "unverified": 0, "refuted": 0},
    }
    review.update(over)
    validate.apply_derivation(review)
    review.update({k: v for k, v in over.items() if k != "stats"})  # let tests force wrong values
    return review


def make_validation(vid, command, **over):
    v = {"schema": "validation/2", "id": vid, "command": command, "status": "passed", "exit_code": 0,
         "evidence_ref": "logs/" + vid, "summary": "", "git_head": HEAD, "worktree_dirty": False}
    v.update(over)
    return v


def make_approval(plan, **over):
    a = {"schema": "approval/1", "id": "ap1", "session_id": "s", "gate": "G2", "decision": "granted",
         "approver": "lead", "plan_hash": plan["plan_hash"], "git_head": HEAD, "review_id": "rev1",
         "validation_ids": ["v1", "v2"], "scope": ["commit"], "decided_at": TS}
    a.update(over)
    return a


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def put(self, name, doc):
        path = self.dir / name
        path.write_text(json.dumps(doc), encoding="utf-8")
        return str(path)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = validate.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class SchemaCommand(Base):
    def test_valid_docs_autodetected(self):
        plan = make_plan()
        code, out, _ = self.run_cli("schema", self.put("p.json", plan), self.put("r.json", make_review()))
        self.assertEqual(code, 0, out)

    def test_invalid_doc_fails(self):
        plan = make_plan()
        del plan["acceptance"]
        code, out, _ = self.run_cli("schema", self.put("p.json", plan))
        self.assertEqual(code, 1)
        self.assertIn("acceptance", out)

    def test_missing_schema_field_is_usage_error(self):
        code, _, err = self.run_cli("schema", self.put("x.json", {"hello": 1}))
        self.assertEqual(code, 2)
        self.assertIn("cannot detect schema", err)

    def test_missing_file_is_usage_error(self):
        code, _, err = self.run_cli("schema", str(self.dir / "nope.json"))
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)

    def test_jsonl_events_validated_per_line(self):
        good = {"schema": "event/1", "id": "e1", "session_id": "s", "trace_id": "t", "type": "tool.block", "ts": TS}
        bad = dict(good, type="nope")
        path = self.dir / "events.jsonl"
        path.write_text(json.dumps(good) + "\n\n" + json.dumps(bad) + "\n{broken\n", encoding="utf-8")
        code, out, _ = self.run_cli("schema", str(path))
        self.assertEqual(code, 1)
        self.assertIn("events.jsonl:3", out)
        self.assertIn("events.jsonl:4", out)
        self.assertNotIn("FAIL  " + str(path) + ":1", out)

    def test_json_output_flag(self):
        code, out, _ = self.run_cli("schema", self.put("p.json", make_plan()), "--json")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])


class PlanHash(Base):
    def test_verify_ok(self):
        code, _, _ = self.run_cli("plan-hash", self.put("p.json", make_plan()))
        self.assertEqual(code, 0)

    def test_tamper_detected(self):
        plan = make_plan()
        plan["scope"] = ["sneaky new scope"]
        code, out, _ = self.run_cli("plan-hash", self.put("p.json", plan))
        self.assertEqual(code, 1)
        self.assertIn("stored", out)

    def test_hash_ignores_key_order(self):
        plan = make_plan()
        shuffled = dict(reversed(list(plan.items())))
        self.assertEqual(validate.compute_plan_hash(plan), validate.compute_plan_hash(shuffled))

    def test_write_sets_hash(self):
        plan = make_plan()
        plan["plan_hash"] = "f" * 64
        path = self.put("p.json", plan)
        code, _, _ = self.run_cli("plan-hash", path, "--write")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(Path(path).read_text())["plan_hash"], validate.compute_plan_hash(plan))

    def test_missing_hash_reported(self):
        plan = make_plan()
        del plan["plan_hash"]
        code, out, _ = self.run_cli("plan-hash", self.put("p.json", plan))
        self.assertEqual(code, 1)
        self.assertIn("missing", out)


class ReviewDerivation(Base):
    def test_clean_review_approves(self):
        self.assertEqual(self.run_cli("review", self.put("r.json", make_review()))[0], 0)

    def test_blocking_high_requests_changes(self):
        review = make_review([make_finding()])
        self.assertEqual(review["verdict"], "CHANGES_REQUESTED")
        self.assertEqual(self.run_cli("review", self.put("r.json", review))[0], 0)

    def test_unverified_high_is_blocking(self):
        review = make_review([make_finding(verification="unverified")])
        self.assertTrue(review["findings"][0]["blocking"])
        self.assertEqual(review["verdict"], "CHANGES_REQUESTED")

    def test_refuted_high_not_blocking(self):
        review = make_review([make_finding(verification="refuted")])
        self.assertFalse(review["findings"][0]["blocking"])
        self.assertEqual(review["verdict"], "APPROVE")

    def test_medium_confirmed_not_blocking(self):
        self.assertEqual(make_review([make_finding(severity="MEDIUM")])["verdict"], "APPROVE")

    def test_failed_reviewer_is_incomplete_even_with_no_findings(self):
        review = make_review(reviewers=[{"agent": "sec", "run_id": "r", "status": "timeout"}])
        self.assertEqual(review["verdict"], "INCOMPLETE")

    def test_incomplete_beats_changes_requested(self):
        review = make_review([make_finding()], reviewers=[{"agent": "sec", "run_id": "r", "status": "failed"}])
        self.assertEqual(review["verdict"], "INCOMPLETE")

    def test_asserted_approve_over_blocking_finding_rejected(self):
        review = make_review([make_finding()], verdict="APPROVE")
        code, out, _ = self.run_cli("review", self.put("r.json", review))
        self.assertEqual(code, 1)
        self.assertIn("derived CHANGES_REQUESTED", out)

    def test_wrong_stats_rejected(self):
        review = make_review([make_finding()])
        review["stats"]["confirmed"] = 0
        code, out, _ = self.run_cli("review", self.put("r.json", review))
        self.assertEqual(code, 1)
        self.assertIn("stats.confirmed", out)

    def test_duplicate_finding_ids_rejected(self):
        review = make_review([make_finding(), make_finding()])
        code, out, _ = self.run_cli("review", self.put("r.json", review))
        self.assertEqual(code, 1)
        self.assertIn("duplicate finding id", out)

    def test_write_repairs_lying_review(self):
        review = make_review([make_finding()])
        review.update(verdict="APPROVE")
        review["findings"][0]["blocking"] = False
        path = self.put("r.json", review)
        self.assertEqual(self.run_cli("review", path)[0], 1)
        self.assertEqual(self.run_cli("review", path, "--write")[0], 0)
        fixed = json.loads(Path(path).read_text())
        self.assertEqual(fixed["verdict"], "CHANGES_REQUESTED")
        self.assertTrue(fixed["findings"][0]["blocking"])
        self.assertEqual(self.run_cli("review", path)[0], 0)

    def test_raw_count_preserved_when_larger_than_unique(self):
        review = make_review([make_finding()])
        review["stats"]["raw"] = 5
        self.assertEqual(self.run_cli("review", self.put("r.json", review))[0], 0)


class CheckApproval(Base):
    def setUp(self):
        super().setUp()
        self.plan = make_plan()
        self.review = make_review()
        self.v1 = make_validation("v1", "pytest")
        self.v2 = make_validation("v2", "ruff check")
        self.approval = make_approval(self.plan)

    def check(self, approval=None, plan=None, review=None, validations=None, extra=()):
        argv = ["check-approval", self.put("a.json", approval or self.approval),
                "--plan", self.put("p.json", plan or self.plan),
                "--review", self.put("r.json", review or self.review)]
        for i, v in enumerate(validations if validations is not None else [self.v1, self.v2]):
            argv += ["--validation", self.put(f"v{i}.json", v)]
        return self.run_cli(*argv, *extra)

    def test_fully_bound_g2_passes(self):
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)

    def test_g1_needs_only_plan(self):
        approval = {"schema": "approval/1", "id": "a", "session_id": "s", "gate": "G1", "decision": "granted",
                    "approver": "lead", "plan_hash": self.plan["plan_hash"], "decided_at": TS}
        code, out, _ = self.run_cli("check-approval", self.put("a.json", approval), "--plan", self.put("p.json", self.plan))
        self.assertEqual(code, 0, out)

    def test_plan_edited_after_approval_invalidates(self):
        edited = make_plan(scope=["extra"])
        code, out, _ = self.check(plan=edited)
        self.assertEqual(code, 1)
        self.assertIn("plan changed since approval", out)

    def test_stale_plan_hash_field_detected(self):
        edited = copy.deepcopy(self.plan)
        edited["scope"] = ["extra"]  # content changed, plan_hash field left stale
        code, out, _ = self.check(approval=make_approval(edited), plan=edited)
        self.assertEqual(code, 1)
        self.assertIn("plan content matches its plan_hash", out)

    def test_denied_gate_fails(self):
        code, out, _ = self.check(approval=make_approval(self.plan, decision="denied"))
        self.assertEqual(code, 1)
        self.assertIn("gate granted", out)

    def test_expired_approval_fails(self):
        approval = make_approval(self.plan, expires_at="2026-09-20T11:00:00Z")
        self.assertEqual(self.check(approval=approval, extra=("--now", "2026-09-20T10:30:00Z"))[0], 0)
        code, out, _ = self.check(approval=approval, extra=("--now", "2026-09-20T12:00:00Z"))
        self.assertEqual(code, 1)
        self.assertIn("not expired", out)

    def test_blocking_review_fails(self):
        code, out, _ = self.check(review=make_review([make_finding()]))
        self.assertEqual(code, 1)
        self.assertIn("verdict is APPROVE", out)

    def test_incomplete_review_fails(self):
        review = make_review(reviewers=[{"agent": "sec", "run_id": "r", "status": "failed"}])
        self.assertEqual(self.check(review=review)[0], 1)

    def test_review_id_mismatch_fails(self):
        code, out, _ = self.check(review=make_review(id="other"))
        self.assertEqual(code, 1)
        self.assertIn("references this review", out)

    def test_failed_validation_fails(self):
        bad = make_validation("v1", "pytest", status="failed", exit_code=1)
        code, out, _ = self.check(validations=[bad, self.v2])
        self.assertEqual(code, 1)
        self.assertIn("validation v1 passed", out)

    def test_skipped_validation_is_not_a_pass(self):
        skipped = make_validation("v2", "ruff check", status="skipped", reason="no ruff")
        del skipped["exit_code"], skipped["evidence_ref"]
        self.assertEqual(self.check(validations=[self.v1, skipped])[0], 1)

    def test_validation_from_other_commit_fails(self):
        old = make_validation("v1", "pytest", git_head="c" * 40)
        code, out, _ = self.check(validations=[old, self.v2])
        self.assertEqual(code, 1)
        self.assertIn("ran on approved commit", out)

    def test_validation_on_dirty_tree_fails(self):
        dirty = make_validation("v1", "pytest", worktree_dirty=True)
        self.assertEqual(self.check(validations=[dirty, self.v2])[0], 1)

    def test_missing_validation_file_fails(self):
        code, out, _ = self.check(validations=[self.v1])
        self.assertEqual(code, 1)
        self.assertIn("validation v2 supplied", out)

    def test_plan_command_not_covered_fails(self):
        plan = make_plan(validation=["pytest", "ruff check", "mypy ."])
        code, out, _ = self.check(approval=make_approval(plan), plan=plan)
        self.assertEqual(code, 1)
        self.assertIn("plan validation covered: mypy .", out)

    def test_g2_without_review_fails(self):
        argv = ["check-approval", self.put("a.json", self.approval), "--plan", self.put("p.json", self.plan)]
        code, out, _ = self.run_cli(*argv)
        self.assertEqual(code, 1)
        self.assertIn("G2 requires --review", out)

    def test_malformed_approval_fails_closed(self):
        approval = dict(self.approval)
        del approval["scope"]
        code, out, _ = self.check(approval=approval)
        self.assertEqual(code, 1)
        self.assertNotIn("gate granted", out)  # did not reason over a malformed doc


class RepoCheck(Base):
    def git(self, *a):
        return subprocess.run(["git", "-C", str(self.dir), *a], capture_output=True, text=True, check=True).stdout.strip()

    def setUp(self):
        super().setUp()
        try:
            self.git("init", "-q")
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git not available")
        (self.dir / "f.txt").write_text("x")
        self.git("add", "f.txt")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        self.head = self.git("rev-parse", "HEAD")

    def run_g2(self):
        plan = make_plan(validation=["pytest"])
        approval = make_approval(plan, git_head=self.head, validation_ids=["v1"])
        review = make_review()
        v = make_validation("v1", "pytest", git_head=self.head)
        out_dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(out_dir, ignore_errors=True))
        paths = {}
        for name, doc in (("a", approval), ("p", plan), ("r", review), ("v", v)):
            paths[name] = out_dir / f"{name}.json"
            paths[name].write_text(json.dumps(doc))
        return self.run_cli("check-approval", str(paths["a"]), "--plan", str(paths["p"]), "--review", str(paths["r"]),
                            "--validation", str(paths["v"]), "--repo", str(self.dir))

    def test_clean_repo_at_approved_commit_passes(self):
        code, out, _ = self.run_g2()
        self.assertEqual(code, 0, out)

    def test_dirty_tree_fails(self):
        (self.dir / "f.txt").write_text("changed")
        code, out, _ = self.run_g2()
        self.assertEqual(code, 1)
        self.assertIn("tree is clean", out)

    def test_moved_head_fails(self):
        (self.dir / "f.txt").write_text("y")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "next")
        code, out, _ = self.run_g2()
        self.assertEqual(code, 1)
        self.assertIn("HEAD equals approved commit", out)


if __name__ == "__main__":
    unittest.main()
