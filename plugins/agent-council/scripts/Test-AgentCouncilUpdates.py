#!/usr/bin/env python3
"""Hermetic update-hook contracts: temporary data, mocked network, mocked CLI."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
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
        self.root = self.base / "plugin"
        self.data = self.base / "data"
        (self.root / ".codex-plugin").mkdir(parents=True)
        self.data.mkdir()
        (self.root / ".codex-plugin" / "plugin.json").write_text(json.dumps({"name": "agent-council", "version": "0.6.0"}))
        self.env = {"PLUGIN_ROOT": str(self.root), "PLUGIN_DATA": str(self.data)}
        self.now = 1_800_000_000
        self.patch("ROOT", self.root)
        self.patch("time.time", return_value=self.now)
        # Guard every test against accidentally invoking a real network or CLI.
        self.opener = self.patch("urllib.request.build_opener", side_effect=AssertionError("Unexpected network"))
        self.popen = self.patch("subprocess.Popen", side_effect=AssertionError("Unexpected CLI"))
        self.fetch = self.patch("fetch_version", return_value="0.7.0")
        self.cli = self.patch("run_cli", return_value=b"{}")
        self.resolve = self.patch("resolve_codex", return_value="/trusted/bin/codex")

    def patch(self, name, *args, **kwargs):
        # patch.object supports a module loaded without sys.modules registration.
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
        return UPDATES.handle_hook("SessionStart" if prompt is None else "UserPromptSubmit",
                                   {} if prompt is None else {"prompt": prompt}, self.env if env is None else env)

    def message(self, result):
        self.assertEqual(set(result), {"hookSpecificOutput"})
        details = result["hookSpecificOutput"]
        self.assertIn(details["hookEventName"], ("SessionStart", "UserPromptSubmit"))
        self.assertTrue(details["additionalContext"].startswith("Visibly tell the user:"))
        return details["additionalContext"]

    def verified_list(self, version="0.7.0", **changes):
        plugin = {"pluginId": UPDATES.PLUGIN_ID, "name": "agent-council", "marketplaceName": "agent-council",
                  "version": version, "installed": True, "enabled": True,
                  "marketplaceSource": {"sourceType": "git", "source": UPDATES.MARKETPLACE_SOURCE}}
        plugin.update(changes)
        return json.dumps({"installed": [plugin]}).encode()

    def test_default_is_notification_only(self):
        result = self.hook()
        message = self.message(result)
        self.assertIn("Agent Council 0.6.0 is installed", message)
        self.assertIn("0.7.0 is available", message)
        self.assertIn("Automatic updates are off", message)
        self.cli.assert_not_called()
        self.assertFalse((self.data / UPDATES.SETTINGS_FILE).exists())

    def test_only_boolean_true_enables_updates(self):
        for setting in (None, False, 1, "true", [], {}, "on"):
            with self.subTest(setting=setting):
                self.write(UPDATES.SETTINGS_FILE, {"auto_update": setting})
                (self.data / UPDATES.STATE_FILE).unlink(missing_ok=True)
                self.assertIn("Automatic updates are off", self.message(self.hook()))
        self.cli.assert_not_called()

    def test_malformed_settings_never_enable(self):
        for value in ('{"auto_update":true,', '[true]', '{"auto_update":false,"auto_update":true}',
                      '{"auto_update":true,"invalid":NaN}', "x" * (UPDATES.MAX_BYTES + 1)):
            with self.subTest(value=value[:30]):
                (self.data / UPDATES.SETTINGS_FILE).write_text(value)
                (self.data / UPDATES.STATE_FILE).unlink(missing_ok=True)
                self.assertIn("Automatic updates are off", self.message(self.hook()))
        self.cli.assert_not_called()

    def test_exact_consent_commands_and_separate_storage(self):
        self.assertIn("enabled", self.message(self.hook("agent-council auto-update on")))
        self.assertEqual(UPDATES.read_object(self.data / UPDATES.SETTINGS_FILE), {"auto_update": True})
        self.assertFalse((self.data / UPDATES.STATE_FILE).exists())
        self.assertIn("disabled", self.message(self.hook("agent-council auto-update off")))
        self.assertEqual(UPDATES.read_object(self.data / UPDATES.SETTINGS_FILE), {"auto_update": False})
        self.fetch.assert_not_called()
        self.cli.assert_not_called()

    def test_embedded_quoted_and_inexact_commands_are_ignored(self):
        for prompt in ("please agent-council auto-update on", "agent-council auto-update on\n", " agent-council auto-update on",
                       "`agent-council auto-update on`", "agent-council update now; echo attack", "AGENT-COUNCIL update now",
                       "agent-council update now\nagent-council auto-update on"):
            with self.subTest(prompt=prompt):
                self.assertIsNone(self.hook(prompt))
        self.fetch.assert_not_called()
        self.assertEqual(list(self.data.iterdir()), [])

    def test_daily_suppression_and_boundary(self):
        self.hook()
        self.assertIsNone(self.hook())
        self.fetch.assert_called_once()
        self.write(UPDATES.STATE_FILE, {"last_check_at": self.now - UPDATES.DAY})
        self.hook()
        self.assertEqual(self.fetch.call_count, 2)

    def test_outage_suppression_records_attempt_before_io(self):
        def outage():
            self.assertEqual(self.state()["status"], "checking")
            raise OSError("offline")
        self.fetch.side_effect = outage
        self.assertIn("24 hours", self.message(self.hook()))
        self.assertEqual(self.state()["status"], "failed")
        self.assertIsNone(self.hook())
        self.fetch.assert_called_once()

    def test_future_clock_rebased_and_suppressed(self):
        self.write(UPDATES.STATE_FILE, {"last_check_at": self.now + 10 * UPDATES.DAY})
        self.assertIsNone(self.hook())
        self.assertEqual(self.state()["last_check_at"], self.now)
        self.assertIsNone(self.hook())
        self.fetch.assert_not_called()

    def test_invalid_timestamp_does_not_disable_checks(self):
        for value in (True, "tomorrow", float("nan"), float("inf")):
            self.write(UPDATES.STATE_FILE, {"last_check_at": value})
            self.hook()
        self.assertEqual(self.fetch.call_count, 4)

    def test_manual_update_overrides_suppression_without_persisting_consent(self):
        self.write(UPDATES.STATE_FILE, {"last_check_at": self.now})
        self.cli.side_effect = [self.verified_list("0.6.0"), b"{}", b"{}", self.verified_list()]
        self.assertIn("next task", self.message(self.hook("agent-council update now")))
        self.assertFalse((self.data / UPDATES.SETTINGS_FILE).exists())

    def test_automatic_success_fixed_argv_and_notice(self):
        self.write(UPDATES.SETTINGS_FILE, {"auto_update": True})
        self.cli.side_effect = [self.verified_list("0.6.0"), b"{}", b"{}", self.verified_list()]
        self.assertIn("next task", self.message(self.hook()))
        self.resolve.assert_called_once_with()
        self.assertEqual([call.args[0] for call in self.cli.call_args_list],
                         [["/trusted/bin/codex", "plugin", "list", "--json"],
                          ["/trusted/bin/codex", "plugin", "marketplace", "upgrade", "agent-council", "--json"],
                          ["/trusted/bin/codex", "plugin", "add", "agent-council@agent-council", "--json"],
                          ["/trusted/bin/codex", "plugin", "list", "--json"]])
        self.assertTrue(all(call.kwargs["timeout"] <= UPDATES.CLI_TIMEOUT for call in self.cli.call_args_list))
        self.assertEqual(self.state()["status"], "installed")
        self.assertEqual(self.state()["installed_version"], "0.7.0")
        self.assertEqual(json.loads((self.root / ".codex-plugin" / "plugin.json").read_text())["version"], "0.6.0")

    def test_install_failure_stops_and_suppresses(self):
        self.write(UPDATES.SETTINGS_FILE, {"auto_update": True})
        self.cli.side_effect = [self.verified_list("0.6.0"), b"{}", OSError("install failed")]
        self.assertIn("could not be completed", self.message(self.hook()))
        self.assertEqual(self.cli.call_count, 3)
        self.assertEqual(self.state()["status"], "failed")
        self.assertIsNone(self.hook())

    def test_verification_rejects_wrong_identity_or_version(self):
        for changes in ({"pluginId": "other@agent-council"}, {"marketplaceName": "other"}, {"name": "other"},
                        {"installed": False}, {"installed": 1}, {"version": "0.6.0"},
                        {"marketplaceSource": {"sourceType": "git", "source": "https://example.invalid/repo.git"}}):
            with self.subTest(changes=changes):
                self.cli.side_effect = [self.verified_list("0.6.0"), b"{}", b"{}", self.verified_list(**changes)]
                self.assertIn("could not be completed", self.message(self.hook("agent-council update now")))

    def test_preflight_rejects_wrong_marketplace_source_before_mutation(self):
        self.cli.side_effect = [self.verified_list("0.6.0", marketplaceSource={"sourceType": "git", "source": "https://example.invalid/repo.git"})]
        self.assertIn("could not be completed", self.message(self.hook("agent-council update now")))
        self.assertEqual(self.cli.call_count, 1)

    def test_install_has_aggregate_deadline_below_hook_timeout(self):
        hooks = json.loads((Path(__file__).parents[1] / "hooks" / "hooks.json").read_text())
        update_timeouts = [hook["timeout"] for groups in hooks["hooks"].values() for group in groups
                           for hook in group["hooks"] if "Manage-AgentCouncilUpdates.py" in hook["command"]]
        self.assertEqual(update_timeouts, [UPDATES.HOOK_TIMEOUT, UPDATES.HOOK_TIMEOUT])
        self.assertGreaterEqual(UPDATES.HOOK_TIMEOUT - UPDATES.NETWORK_TIMEOUT - UPDATES.INSTALL_TIMEOUT, 10)
        with mock.patch.object(UPDATES.time, "monotonic", side_effect=[0, UPDATES.INSTALL_TIMEOUT + 1]), self.assertRaises(ValueError):
            UPDATES.install_version("0.6.0", "0.7.0")
        self.cli.assert_not_called()

    def test_interrupted_check_is_visible_and_manually_recoverable(self):
        self.write(UPDATES.STATE_FILE, {"last_check_at": self.now, "status": "checking"})
        self.assertIn("interrupted", self.message(self.hook()))
        self.assertEqual(self.state()["status"], "interrupted")
        self.fetch.assert_not_called()
        self.cli.side_effect = [self.verified_list("0.6.0"), b"{}", b"{}", self.verified_list()]
        self.assertIn("next task", self.message(self.hook("agent-council update now")))

    def test_verification_rejects_duplicate_identity(self):
        listed = json.loads(self.verified_list())
        listed["installed"] *= 2
        self.cli.side_effect = [self.verified_list("0.6.0"), b"{}", b"{}", json.dumps(listed).encode()]
        self.assertIn("could not be completed", self.message(self.hook("agent-council update now")))

    def test_current_or_older_remote_does_not_install(self):
        for version in ("0.6.0", "0.6.0+build.2", "0.5.99", "0.6.0-rc.1"):
            self.fetch.return_value = version
            self.assertIn("up to date", self.message(self.hook("agent-council update now")))
        self.cli.assert_not_called()

    def test_semver_precedence(self):
        versions = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
                    "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.0.1", "1.2.0", "1.10.0", "2.0.0"]
        values = list(map(UPDATES.SemVer, versions))
        self.assertEqual(sorted(reversed(values)), values)
        self.assertEqual(UPDATES.SemVer("1.0.0+one"), UPDATES.SemVer("1.0.0+two"))
        self.assertLess(UPDATES.SemVer("1.0.0-1"), UPDATES.SemVer("1.0.0-a"))

    def test_semver_rejects_invalid_values(self):
        for version in (None, "v1.0.0", "1.0", "01.0.0", "1.0.0-01", "1.0.0-a..b", "1.0.0+", "1.0.0\n", "1.0.0;sh"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                UPDATES.SemVer(version)

    def test_unknown_claude_missing_or_mismatched_host_skips(self):
        for env in ({}, {"CLAUDE_PLUGIN_ROOT": str(self.root)}, {"CODEX_HOME": str(self.base)},
                    {**self.env, "PLUGIN_ROOT": str(self.base / "other")},
                    {"PLUGIN_ROOT": str(self.root)}, {**self.env, "PLUGIN_DATA": "relative"},
                    {**self.env, "PLUGIN_DATA": str(self.root / "cache")}):
            with self.subTest(env=env):
                self.assertIsNone(self.hook(env=env))
        self.fetch.assert_not_called()
        self.assertEqual(list(self.data.iterdir()), [])

    def test_codex_with_claude_compatibility_marker_proceeds(self):
        self.assertIn("Automatic updates are off", self.message(self.hook(env={**self.env, "CLAUDE_PLUGIN_ROOT": str(self.root)})))
        self.fetch.assert_called_once()

    def test_nonblocking_lock_contention_and_stale_file(self):
        with UPDATES.update_lock(self.data / UPDATES.LOCK_FILE) as held:
            self.assertTrue(held)
            self.assertIsNone(self.hook())
            self.assertIn("already running", self.message(self.hook("agent-council update now")))
            self.fetch.assert_not_called()
        self.assertTrue((self.data / UPDATES.LOCK_FILE).exists())
        self.hook()
        self.fetch.assert_called_once()

    def test_atomic_private_state_and_settings(self):
        self.hook("agent-council auto-update off")
        self.hook()
        for name in (UPDATES.SETTINGS_FILE, UPDATES.STATE_FILE, UPDATES.LOCK_FILE):
            self.assertEqual((self.data / name).stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.data.glob(".updates-*")))

    def test_failed_atomic_replace_keeps_prior_state(self):
        path = self.data / UPDATES.STATE_FILE
        self.write(UPDATES.STATE_FILE, {"before": True})
        with mock.patch.object(UPDATES.os, "replace", side_effect=OSError("failed")), self.assertRaises(OSError):
            UPDATES.atomic_write(path, {"after": True})
        self.assertEqual(json.loads(path.read_text()), {"before": True})
        self.assertFalse(list(self.data.glob(".updates-*")))

    def test_remote_url_timeout_identity_and_bounds(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({"name": "agent-council", "metadata": {"version": "0.7.0"}, "plugins": [
            {"name": "agent-council", "source": "./plugins/agent-council", "version": "0.7.0"}]}).encode()
        self.opener.side_effect = None
        self.opener.return_value.open.return_value = response
        self.assertEqual(ORIGINAL_FETCH(), "0.7.0")
        request = self.opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, UPDATES.MARKETPLACE_URL)
        self.assertEqual(self.opener.return_value.open.call_args.kwargs, {"timeout": UPDATES.NETWORK_TIMEOUT})
        response.read.assert_called_once_with(UPDATES.MAX_BYTES + 1)

    def test_malformed_oversized_or_wrong_remote_rejected(self):
        bad = [b"not json", b"[]", b"x" * (UPDATES.MAX_BYTES + 1), b'{"name":"other","plugins":[]}',
               b'{"name":"agent-council","plugins":[]}',
               b'{"name":"other","name":"agent-council","plugins":[]}',
               b'{"name":"agent-council","plugins":[],"invalid":NaN}',
               json.dumps({"name": "agent-council", "plugins": [{"name": "agent-council", "source": "./evil", "version": "1.0.0"}]}).encode(),
               json.dumps({"name": "agent-council", "plugins": [{"name": "agent-council", "source": "./plugins/agent-council", "version": "1.0.0"}] * 2}).encode()]
        response = mock.MagicMock()
        response.__enter__.return_value = response
        self.opener.side_effect = None
        self.opener.return_value.open.return_value = response
        for raw in bad:
            response.read.return_value = raw
            with self.subTest(raw=raw[:50]), self.assertRaises(ValueError):
                ORIGINAL_FETCH()

    def test_marketplace_metadata_must_match_plugin_version(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        self.opener.side_effect = None
        self.opener.return_value.open.return_value = response
        for metadata in (None, {}, {"version": "0.6.0"}):
            response.read.return_value = json.dumps({"name": "agent-council", "metadata": metadata, "plugins": [
                {"name": "agent-council", "source": "./plugins/agent-council", "version": "0.7.0"}]}).encode()
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                ORIGINAL_FETCH()

    def test_json_duplicate_and_nonfinite_values_rejected(self):
        for raw in (b'{"auto_update":false,"auto_update":true}', b'{"value":NaN}', b'{"value":Infinity}', b'{"value":-Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                UPDATES.decode_object(raw)

    def test_redirects_rejected(self):
        with self.assertRaises(ValueError):
            UPDATES.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.invalid/")

    def test_network_timeout_bounds_entire_download(self):
        with mock.patch.object(UPDATES.threading, "Thread") as thread:
            thread.return_value.is_alive.return_value = True
            with self.assertRaises(ValueError):
                ORIGINAL_FETCH()
            thread.return_value.join.assert_called_once_with(UPDATES.NETWORK_TIMEOUT)
            self.assertTrue(thread.call_args.kwargs["daemon"])

    def fake_process(self, raw=b"{}", returncode=0):
        process = mock.Mock()
        process.stdout = io.BytesIO(raw)
        process.wait.return_value = returncode
        process.poll.return_value = returncode
        self.popen.side_effect = None
        self.popen.return_value = process
        return process

    def test_cli_shell_false_fixed_input_and_capture(self):
        self.fake_process()
        self.assertEqual(ORIGINAL_CLI(UPDATES.UPGRADE_ARGV), b"{}")
        self.popen.assert_called_once_with(UPDATES.UPGRADE_ARGV, shell=False, stdin=subprocess.DEVNULL,
                                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def test_codex_resolution_requires_absolute_executable_file(self):
        with mock.patch.object(UPDATES.shutil, "which", return_value=None), self.assertRaises(ValueError):
            ORIGINAL_RESOLVE()
        executable = self.base / "codex"
        executable.write_text("#!/bin/sh\n")
        executable.chmod(0o700)
        with mock.patch.object(UPDATES.shutil, "which", return_value=str(executable)):
            self.assertEqual(ORIGINAL_RESOLVE(), str(executable.resolve()))
        executable.chmod(0o600)
        with mock.patch.object(UPDATES.shutil, "which", return_value=str(executable)), self.assertRaises(ValueError):
            ORIGINAL_RESOLVE()

    def test_cli_oversized_output_rejected(self):
        self.fake_process(b"x" * (UPDATES.MAX_BYTES + 1))
        with self.assertRaises(ValueError):
            ORIGINAL_CLI(UPDATES.LIST_ARGV)

    def test_cli_nonzero_rejected(self):
        self.fake_process(returncode=1)
        with self.assertRaises(ValueError):
            ORIGINAL_CLI(UPDATES.ADD_ARGV)

    def test_cli_timeout_kills_process(self):
        process = self.fake_process()
        process.poll.return_value = None
        with mock.patch.object(UPDATES.threading, "Thread") as thread:
            thread.return_value.is_alive.return_value = True
            with self.assertRaises(ValueError):
                ORIGINAL_CLI(UPDATES.ADD_ARGV)
            process.kill.assert_called_once()
            thread.return_value.join.assert_any_call(UPDATES.CLI_TIMEOUT)

    def test_main_hook_contract_and_zero_exit_on_failure(self):
        for raw in (b"{}", b"not json", b"x" * (UPDATES.MAX_BYTES + 1)):
            stdin = mock.Mock(buffer=io.BytesIO(raw))
            stdout = io.StringIO()
            with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(UPDATES.sys, "stdin", stdin), contextlib.redirect_stdout(stdout):
                self.assertEqual(UPDATES.main(["hook", "--event", "SessionStart"]), 0)
            output = stdout.getvalue()
            if output:
                self.message(json.loads(output))

    def test_data_access_failure_is_nonfatal(self):
        with mock.patch.object(UPDATES, "update_lock", side_effect=OSError("unwritable")):
            self.assertIn("continues normally", self.message(self.hook()))


ORIGINAL_FETCH = UPDATES.fetch_version
ORIGINAL_CLI = UPDATES.run_cli
ORIGINAL_RESOLVE = UPDATES.resolve_codex

if __name__ == "__main__":
    unittest.main(verbosity=2)
