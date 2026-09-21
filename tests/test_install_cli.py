"""Tests for install.py, doctor.py and cli.py."""
import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest import mock

import support
from agentic import cli, doctor, install
from agentic.store import Store


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def bare_project(case) -> Path:
    import tempfile
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    return Path(tmp.name).resolve()


class Merge(unittest.TestCase):
    def test_adds_all_hooks_and_is_idempotent(self):
        root = bare_project(self)
        merged, changes = install.merge_settings({}, root, "python")
        self.assertEqual(len(changes), len(install.HOOK_SPECS))
        again, changes2 = install.merge_settings(merged, root, "python")
        self.assertEqual((changes2, again), ([], merged))

    def test_preserves_user_settings_and_user_hooks(self):
        root = bare_project(self)
        user = {"model": "sonnet", "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-linter"}]}]}}
        merged, _ = install.merge_settings(user, root, "python")
        self.assertEqual(merged["model"], "sonnet")
        pre = merged["hooks"]["PreToolUse"]
        self.assertEqual(pre[0], user["hooks"]["PreToolUse"][0])
        self.assertEqual(len(pre), 2)

    def test_updates_a_stale_managed_command_in_place(self):
        root = bare_project(self)
        merged, _ = install.merge_settings({}, root, "python")
        merged["hooks"]["SessionStart"][0]["hooks"][0]["command"] = 'python3 "/old/scripts/agentic.py" hook session-start'
        fixed, changes = install.merge_settings(merged, root, "python")
        self.assertEqual(changes, ["update SessionStart hook 'session-start'"])
        self.assertEqual(len(fixed["hooks"]["SessionStart"]), 1)

    def test_command_shape(self):
        root = bare_project(self)
        cmd = install.hook_command(root, "pre-tool-use", "python")
        self.assertRegex(cmd, r'^python ".*scripts/agentic\.py" hook pre-tool-use$')
        self.assertTrue(install.is_managed(cmd, "pre-tool-use"))
        self.assertFalse(install.is_managed(cmd, "post-tool-use"))
        self.assertFalse(install.is_managed("my-linter", "pre-tool-use"))


class Install(unittest.TestCase):
    def test_dry_run_writes_nothing(self):
        root = bare_project(self)
        actions = install.install(root, dry_run=True)
        self.assertTrue(actions)
        self.assertEqual(list(root.iterdir()), [])

    def test_install_creates_state_config_hooks_commands_and_manifest(self):
        root = bare_project(self)
        install.install(root, enforcement="warn")
        self.assertEqual(json.loads((root / ".agentic/config.json").read_text())["enforcement"], "warn")
        settings = json.loads((root / ".claude/settings.json").read_text())
        self.assertEqual(set(settings["hooks"]), {e for e, _, _ in install.HOOK_SPECS})
        for name in ("plan", "approve", "doctor", "status"):
            body = (root / ".claude/commands" / f"{name}.md").read_text()
            self.assertNotIn("{{AGENTIC}}", body)
        manifest = json.loads((root / ".agentic/install.json").read_text())
        self.assertEqual(len(manifest["managed_files"]), 4)
        self.assertEqual(install.install(root), ["nothing to do (already installed)"])

    def test_local_flag_targets_settings_local(self):
        root = bare_project(self)
        install.install(root, local=True)
        self.assertTrue((root / ".claude/settings.local.json").exists())
        self.assertFalse((root / ".claude/settings.json").exists())

    def test_user_edited_command_file_is_left_alone(self):
        root = bare_project(self)
        install.install(root)
        f = root / ".claude/commands/plan.md"
        f.write_text("my own plan command")
        actions = install.install(root)
        self.assertIn(".claude/commands/plan.md: exists and differs; left untouched", actions)
        self.assertEqual(f.read_text(), "my own plan command")

    def test_invalid_settings_json_aborts_without_writing(self):
        root = bare_project(self)
        (root / ".claude").mkdir()
        (root / ".claude/settings.json").write_text("{oops")
        with self.assertRaises(install.InstallError):
            install.install(root)
        self.assertFalse((root / ".agentic").exists())
        self.assertEqual((root / ".claude/settings.json").read_text(), "{oops")

    def test_refuses_the_home_directory(self):
        """Regression: an early smoke test installed hooks into ~/.claude, affecting every project."""
        home = bare_project(self)
        (home / ".claude").mkdir()
        with mock.patch.object(Path, "home", return_value=home):
            with self.assertRaises(install.InstallError) as ctx:
                install.install(home)
            self.assertIn("every Claude Code session", str(ctx.exception))
            with self.assertRaises(install.InstallError):
                install.install(home, dry_run=True)
        self.assertEqual(sorted(p.name for p in home.iterdir()), [".claude"])
        self.assertEqual(list((home / ".claude").iterdir()), [])


class Uninstall(unittest.TestCase):
    def test_install_then_uninstall_restores_user_settings_exactly(self):
        root = bare_project(self)
        (root / ".claude").mkdir()
        user = {"model": "sonnet", "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-linter"}]}]}}
        (root / ".claude/settings.json").write_text(json.dumps(user))
        install.install(root)
        actions = install.uninstall(root)
        self.assertEqual(json.loads((root / ".claude/settings.json").read_text()), user)
        self.assertFalse((root / ".claude/commands").exists())
        self.assertTrue((root / ".agentic").exists())  # state kept by default
        self.assertFalse((root / ".agentic/install.json").exists())
        self.assertTrue(any("remove managed PreToolUse hook" in a for a in actions))

    def test_empty_settings_file_and_dirs_are_cleaned_up(self):
        root = bare_project(self)
        install.install(root)
        install.uninstall(root, purge_state=True)
        self.assertEqual(list(root.iterdir()), [])

    def test_modified_command_file_and_user_files_survive(self):
        root = bare_project(self)
        install.install(root)
        (root / ".claude/commands/plan.md").write_text("mine")
        (root / ".claude/commands/other.md").write_text("theirs")
        actions = install.uninstall(root)
        self.assertEqual((root / ".claude/commands/plan.md").read_text(), "mine")
        self.assertEqual((root / ".claude/commands/other.md").read_text(), "theirs")
        self.assertIn(".claude/commands/plan.md: modified since install; left in place", actions)
        self.assertFalse((root / ".claude/commands/approve.md").exists())

    def test_dry_run_changes_nothing_and_missing_install_is_a_noop(self):
        root = bare_project(self)
        self.assertEqual(install.uninstall(root), ["nothing to remove"])
        install.install(root)
        snapshot = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
        self.assertTrue(install.uninstall(root, dry_run=True))
        self.assertEqual(snapshot, {p: p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_cli_uninstall_uses_explicit_dir(self):
        root = bare_project(self)
        install.install(root)
        code, out, _ = run_cli("uninstall", "--dir", str(root), "--purge-state")
        self.assertEqual(code, 0, out)
        self.assertEqual(list(root.iterdir()), [])


class Cli(unittest.TestCase):
    def test_init_uses_explicit_dir_and_never_discovers_a_parent(self):
        parent = bare_project(self)
        (parent / ".claude").mkdir()  # a decoy that must not be adopted
        child = parent / "proj"
        child.mkdir()
        code, out, _ = run_cli("init", "--dir", str(child))
        self.assertEqual(code, 0, out)
        self.assertTrue((child / ".agentic").is_dir())
        self.assertFalse((parent / ".agentic").exists())
        self.assertFalse((parent / ".claude/settings.json").exists())

    def test_init_dry_run_json(self):
        root = bare_project(self)
        code, out, _ = run_cli("init", "--dir", str(root), "--dry-run", "--json")
        doc = json.loads(out)
        self.assertEqual((code, doc["dry_run"]), (0, True))
        self.assertFalse((root / ".agentic").exists())

    def test_plan_new_raises_tier_and_seals(self):
        store = support.new_project(self)
        code, out, _ = run_cli("plan", "new", "--dir", str(store.root), "--goal", "big", "--tier", "T1",
                               *[a for i in range(5) for a in ("--file", f"src/{i}.py")],
                               "--validate", "pytest", "--security", "validate inputs")
        self.assertEqual(code, 0, out)
        self.assertIn("T1 -> T2", out)
        plan = store.read_plan()[0]
        self.assertEqual(plan["tier"], "T2")
        self.assertEqual(run_cli("validate", "plan-hash", str(store.plan_path))[0], 0)
        self.assertTrue((store.plans_dir / f"{plan['plan_hash'][:12]}.json").exists())

    def test_plan_new_without_validation_commands_fails_schema(self):
        store = support.new_project(self)
        code, out, _ = run_cli("plan", "new", "--dir", str(store.root), "--goal", "x", "--file", "a.py")
        self.assertEqual(code, 1)
        self.assertIn("validation", out)

    def test_plan_new_falls_back_to_configured_validation_commands(self):
        store = support.new_project(self, validation_commands=["make test"])
        code, _, _ = run_cli("plan", "new", "--dir", str(store.root), "--goal", "x", "--file", "a.py")
        self.assertEqual(code, 0)
        self.assertEqual(store.read_plan()[0]["validation"], ["make test"])

    def test_seal_logs_invalidation_of_previous_plan(self):
        store = support.new_project(self)
        first = support.seal(store)
        support.seal(store, scope=["different"])
        types = [e["type"] for e in support.events(store)]
        self.assertEqual(types.count("plan.created"), 2)
        self.assertEqual(types.count("plan.invalidated"), 1)
        self.assertEqual(support.events(store)[-1]["payload"]["previous_plan_hash"], first["plan_hash"])

    def test_status_and_approvals_output(self):
        store = support.new_project(self)
        support.seal(store, tier="T2")
        code, out, _ = run_cli("status", "--dir", str(store.root))
        self.assertIn("needs_g1", out)
        support.prompt(store, "/approve G1")
        info = json.loads(run_cli("plan", "status", "--dir", str(store.root), "--json")[1])
        self.assertEqual((info["status"], info["G1"] is not None, info["G2"]), ("active", True, None))
        self.assertIn("G1  granted", run_cli("approvals", "--dir", str(store.root))[1])

    def test_hook_entry_point_reads_stdin_and_uses_exit_codes(self):
        store = support.new_project(self)
        payload = json.dumps({"session_id": "t", "cwd": str(store.root), "tool_name": "Write",
                              "tool_input": {"file_path": str(store.root / "src/a.py"), "content": "x"}})
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with mock.patch("sys.stdin", io.StringIO(payload)), \
                    mock.patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": str(store.root)}):
                self.assertEqual(cli.run_hook("pre-tool-use"), 2)
            with mock.patch("sys.stdin", io.StringIO("not json")):
                self.assertEqual(cli.run_hook("pre-tool-use"), 2)   # fail closed
                self.assertEqual(cli.run_hook("session-start"), 0)  # others fail open


class Doctor(unittest.TestCase):
    def installed(self):
        root = bare_project(self)
        install.install(root)
        return root

    def statuses(self, root):
        return {r["check"]: r["status"] for r in doctor.run_doctor(root)}

    def test_healthy_after_install_runs_the_real_launcher(self):
        st = self.statuses(self.installed())
        self.assertEqual([k for k, v in st.items() if v == "fail"], [])
        self.assertEqual(st["launcher runs (session-start)"], "pass")
        self.assertEqual(st["guard blocks writes to protected paths"], "pass")

    def test_doctor_is_read_only(self):
        root = self.installed()
        before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
        doctor.run_doctor(root)
        after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_fails_when_uninstalled_or_hooks_removed_or_config_broken(self):
        self.assertEqual(self.statuses(bare_project(self))[".agentic/ exists"], "fail")
        root = self.installed()
        settings = root / ".claude/settings.json"
        data = json.loads(settings.read_text())
        del data["hooks"]["PreToolUse"]
        settings.write_text(json.dumps(data))
        self.assertEqual(self.statuses(root)["hook PreToolUse/pre-tool-use registered"], "fail")
        (root / ".agentic/config.json").write_text("{bad")
        self.assertEqual(self.statuses(root)["config valid"], "fail")

    def test_warns_in_non_enforcing_mode_and_on_modified_command_file(self):
        root = bare_project(self)
        install.install(root, enforcement="warn")
        (root / ".claude/commands/plan.md").write_text("edited")
        st = self.statuses(root)
        self.assertEqual(st["enforcement mode"], "warn")
        self.assertEqual(st["managed file .claude/commands/plan.md"], "warn")

    def test_detects_invalid_event_log_lines(self):
        root = self.installed()
        Store(root).events_path.write_text('{"nope": 1}\nnot json\n')
        self.assertEqual(self.statuses(root)["event log valid"], "warn")


if __name__ == "__main__":
    unittest.main()
