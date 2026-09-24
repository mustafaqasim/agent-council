#!/usr/bin/env python3
"""Hermetic contracts for check-only Agent Council updater controls."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("council_updates", Path(__file__).with_name("Manage-AgentCouncilUpdates.py"))
UPDATES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPDATES)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="council-update-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root, self.data = self.base / "plugin", self.base / "data"
        (self.root / ".codex-plugin").mkdir(parents=True)
        self.data.mkdir()
        (self.root / ".codex-plugin" / "plugin.json").write_text(json.dumps({"name": "agent-council", "version": "0.8.0"}))
        self.env, self.now = {"PLUGIN_ROOT": str(self.root), "PLUGIN_DATA": str(self.data)}, 1_800_000_000
        self.patch("ROOT", self.root)
        self.patch("time.time", return_value=self.now)
        self.opener = self.patch("urllib.request.build_opener", side_effect=AssertionError("Unexpected network"))
        self.popen = self.patch("subprocess.Popen", side_effect=AssertionError("Unexpected CLI"))
        self.fetch = self.patch("fetch_version", return_value="0.8.1")

    def patch(self, name, *args, **kwargs):
        owner = UPDATES
        parts = name.split(".")
        for part in parts[:-1]:
            owner = getattr(owner, part)
        patcher = mock.patch.object(owner, parts[-1], *args, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def write(self, name, value):
        (self.data / name).write_text(json.dumps(value))

    def state(self):
        return json.loads((self.data / UPDATES.STATE_FILE).read_text())

    def hook(self, prompt=None, env=None):
        return UPDATES.handle_hook("SessionStart" if prompt is None else "UserPromptSubmit", {} if prompt is None else {"prompt": prompt}, self.env if env is None else env)

    def message(self, result):
        self.assertEqual(set(result), {"hookSpecificOutput"})
        return result["hookSpecificOutput"]["additionalContext"]

    def verified_list(self, version="0.8.0", **changes):
        plugin = {"pluginId": UPDATES.PLUGIN_ID, "name": "agent-council", "marketplaceName": "agent-council", "version": version, "installed": True, "enabled": True, "marketplaceSource": {"sourceType": "git", "source": UPDATES.MARKETPLACE_SOURCE}}
        plugin.update(changes)
        return json.dumps({"installed": [plugin]}).encode()

    def test_default_check_notifies_but_never_invokes_cli(self):
        message = self.message(self.hook())
        self.assertIn("0.8.1 is available", message)
        self.fetch.assert_called_once_with()
        self.popen.assert_not_called()
        self.assertEqual(self.state()["status"], "available")

    def test_manual_now_is_fresh_check_only_and_returns_two_step_handoff(self):
        self.write(UPDATES.STATE_FILE, {"last_check_at": self.now, "checked_version": "0.8.0", "status": "available"})
        message = self.message(self.hook("agent-council update now"))
        self.assertIn(f"`{UPDATES.HANDOFF_COMMAND}`", message)
        self.assertIn(f"`{UPDATES.INSTALL_COMMAND}`", message)
        self.assertLess(message.index(UPDATES.HANDOFF_COMMAND), message.index(UPDATES.INSTALL_COMMAND))
        self.assertIn("did not install or modify", message)
        self.fetch.assert_called_once_with()
        self.popen.assert_not_called()

    def test_hooks_never_install_including_legacy_true_setting(self):
        self.write(UPDATES.SETTINGS_FILE, {"auto_update": True})
        message = self.message(self.hook())
        self.assertIn("Automatic installation is unavailable", message)
        self.popen.assert_not_called()
        self.assertFalse(hasattr(UPDATES, "install_version"))

    def test_auto_update_on_unavailable_and_auto_update_off_is_authoritative_under_check_lock(self):
        self.assertFalse((self.data / UPDATES.SETTINGS_FILE).exists())
        self.assertIn("No executable update consent", self.message(self.hook("agent-council auto-update on")))
        self.assertFalse((self.data / UPDATES.SETTINGS_FILE).exists())
        with UPDATES.update_lock(self.data / UPDATES.LOCK_FILE) as held:
            self.assertTrue(held)
            self.assertIn("saved immediately", self.message(self.hook("agent-council auto-update off")))
        self.assertEqual(UPDATES.read_object(self.data / UPDATES.SETTINGS_FILE)["auto_update"], False)
        self.fetch.assert_not_called()

    def test_update_check_off_has_zero_automatic_network_but_manual_still_checks(self):
        self.message(self.hook("agent-council update-check off"))
        self.assertIsNone(self.hook())
        self.fetch.assert_not_called()
        self.message(self.hook("agent-council update now"))
        self.fetch.assert_called_once_with()

    def test_update_check_on_restores_automatic_check(self):
        self.write(UPDATES.SETTINGS_FILE, {"update_check": False, "auto_update": False})
        self.message(self.hook("agent-council update-check on"))
        self.message(self.hook())
        self.fetch.assert_called_once_with()

    def test_status_is_read_only_and_never_checks_or_creates_data(self):
        absent = self.base / "absent"
        message = self.message(self.hook("agent-council update status", {**self.env, "PLUGIN_DATA": str(absent)}))
        self.assertIn("loaded version 0.8.0", message)
        self.assertFalse(absent.exists())
        self.fetch.assert_not_called()

    def test_status_reports_safe_prior_failure_reason(self):
        self.write(UPDATES.STATE_FILE, {"checked_version": "0.8.0", "status": "failed", "reason": "marketplace"})
        self.assertIn("marketplace response was invalid", self.message(self.hook("agent-council update status")))
        self.fetch.assert_not_called()

    def test_cleanup_removes_only_known_updater_state(self):
        self.write(UPDATES.SETTINGS_FILE, {"update_check": False})
        self.write(UPDATES.STATE_FILE, {"status": "current"})
        retained = self.data / "not-updater-owned.txt"
        retained.write_text("keep")
        self.message(self.hook("agent-council update cleanup"))
        self.assertFalse((self.data / UPDATES.SETTINGS_FILE).exists())
        self.assertFalse((self.data / UPDATES.STATE_FILE).exists())
        self.assertEqual(retained.read_text(), "keep")
        self.fetch.assert_not_called()

    def test_near_matches_guide_without_execution(self):
        for prompt in ("agent-council update now please", "agent-council auto-update maybe", "AGENT-COUNCIL update now"):
            with self.subTest(prompt=prompt):
                self.assertIn("not an executable", self.message(self.hook(prompt)))
        self.fetch.assert_not_called()
        self.popen.assert_not_called()

    def test_non_council_prompts_and_unsafe_host_markers_are_ignored(self):
        self.assertIsNone(self.hook("please agent-council update now"))
        self.assertIsNone(self.hook(env={"PLUGIN_ROOT": str(self.root)}))
        self.assertIsNone(self.hook(env={**self.env, "PLUGIN_DATA": "relative"}))
        self.fetch.assert_not_called()

    def test_new_installed_version_is_not_suppressed_by_old_task_state(self):
        self.write(UPDATES.STATE_FILE, {"last_check_at": self.now, "checked_version": "0.8.0", "status": "available", "available_version": "0.8.1"})
        (self.root / ".codex-plugin" / "plugin.json").write_text(json.dumps({"name": "agent-council", "version": "0.8.1"}))
        self.fetch.return_value = "0.8.1"
        self.hook()
        self.fetch.assert_called_once_with()
        self.assertEqual(self.state()["checked_version"], "0.8.1")
        self.assertEqual(self.state()["status"], "current")

    def test_failed_check_has_bounded_reason_and_manual_retry_is_fresh(self):
        self.fetch.side_effect = UPDATES.UpdateError("network")
        self.hook()
        self.assertEqual(self.state()["reason"], "network")
        self.message(self.hook("agent-council update now"))
        self.assertEqual(self.fetch.call_count, 2)

    def test_verification_rejects_enabled_false_and_non_boolean(self):
        for value in (False, 0, None, "true"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                UPDATES.verify_installation(self.verified_list(enabled=value), "0.8.0")
        UPDATES.verify_installation(self.verified_list(), "0.8.0")

    def test_semver_and_network_contracts(self):
        self.assertLess(UPDATES.SemVer("1.0.0-rc.1"), UPDATES.SemVer("1.0.0"))
        for version in (None, "v1.0.0", "01.0.0", "1.0.0-01", "1.0.0;sh"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                UPDATES.SemVer(version)
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({"name": "agent-council", "metadata": {"version": "0.8.1"}, "plugins": [{"name": "agent-council", "source": "./plugins/agent-council", "version": "0.8.1"}]}).encode()
        self.opener.side_effect = None
        self.opener.return_value.open.return_value = response
        self.assertEqual(ORIGINAL_FETCH(), "0.8.1")
        self.assertEqual(self.opener.return_value.open.call_args.kwargs, {"timeout": UPDATES.NETWORK_TIMEOUT})

    def fake_process(self, raw=b"{}", returncode=0):
        process = mock.Mock()
        process.pid, process.stdout = 1234, io.BytesIO(raw)
        process.wait.return_value, process.poll.return_value = returncode, returncode
        self.popen.side_effect = None
        self.popen.return_value = process
        return process

    def test_cli_process_uses_owned_posix_session(self):
        self.fake_process()
        self.assertEqual(ORIGINAL_CLI(["/trusted/codex"]), b"{}")
        self.popen.assert_called_once_with(["/trusted/codex"], shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)

    def test_cli_timeout_terminates_owned_process_group_within_budget(self):
        process = self.fake_process()
        process.poll.return_value = None
        with mock.patch.object(UPDATES.threading, "Thread") as thread, mock.patch.object(UPDATES.os, "killpg") as killpg:
            thread.return_value.is_alive.return_value = True
            with self.assertRaises(UPDATES.UpdateError):
                ORIGINAL_CLI(["/trusted/codex"], timeout=0.01)
            killpg.assert_any_call(1234, signal.SIGTERM)
            killpg.assert_any_call(1234, signal.SIGKILL)
            process.kill.assert_not_called()

    def test_cli_fails_closed_on_windows_and_main_is_nonfatal(self):
        with mock.patch.object(UPDATES.os, "name", "nt"), self.assertRaises(UPDATES.UpdateError):
            ORIGINAL_CLI(["/trusted/codex"])
        self.popen.assert_not_called()
        stdin, stdout = mock.Mock(buffer=io.BytesIO(b"not json")), io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(UPDATES.sys, "stdin", stdin), contextlib.redirect_stdout(stdout):
            self.assertEqual(UPDATES.main(["hook", "--event", "SessionStart"]), 0)


ORIGINAL_FETCH = UPDATES.fetch_version
ORIGINAL_CLI = UPDATES.run_cli

if __name__ == "__main__":
    unittest.main(verbosity=2)
