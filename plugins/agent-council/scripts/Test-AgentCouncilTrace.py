#!/usr/bin/env python3
"""Fault-first, offline privacy and storage checks for local decision tracing."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("AgentCouncilTrace.py")
ROOT = SCRIPT.parents[1]
spec = importlib.util.spec_from_file_location("trace", SCRIPT)
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="council trace ")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.env = {"HOME": str(self.home), "AGENT_COUNCIL_TRACE": "1", "PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"}

    def run_cli(self, data="{}", *args, env=None):
        return subprocess.run([sys.executable, str(SCRIPT), *(args or ("decision",))],
                              input=data, text=True, capture_output=True, env=env or self.env)

    def records(self):
        return [json.loads(line) for line in (self.home / ".local/state/agent-council/decisions.jsonl").read_text().splitlines()]

    def test_disabled_creates_nothing(self):
        for flag in ("", "0", "true"):
            result = self.run_cli('{"prompt":"secret"}', env={**self.env, "AGENT_COUNCIL_TRACE": flag})
            self.assertEqual(result.returncode, 0)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(trace.inspect_trace({**self.env, "AGENT_COUNCIL_TRACE": "0"})["state"], "disabled")

    def test_malformed_oversized_and_unknown_fields_leave_no_trace(self):
        for data in ("[", "[]", "x" * 20000, '{"prompt":"secret"}',
                     '{"outcome":"secret prompt"}', '{"trigger_codes":["secret"]}',
                     '{"outcome":"direct_execution","outcome":"skipped"}'):
            self.assertEqual(self.run_cli(data).returncode, 0)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_allowlist_private_modes_and_evidence_split(self):
        self.run_cli('{"outcome":"direct_execution","requested_model":"gpt-6-astra"}')
        self.run_cli('{}', 'hook', '--event', 'UserPromptSubmit')
        rows = self.records()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["evidence_source"], "agent_reported")
        self.assertEqual(rows[1]["evidence_source"], "hook_observed")
        self.assertEqual(rows[1]["outcome"], "unknown")
        self.assertIsNone(rows[1]["session_token"])
        self.assertEqual(set(rows[0]), trace.RECORD_FIELDS)
        store = self.home / '.local/state/agent-council'
        self.assertEqual(store.stat().st_mode & 0o777, 0o700)
        self.assertEqual((store / 'decisions.jsonl').stat().st_mode & 0o777, 0o600)
        state = trace.inspect_trace(self.env)
        self.assertEqual(state["hook_observations"], 1)
        self.assertEqual(state["agent_reports"], 1)
        self.assertEqual(state["actual_agent_compliance"], "unknown")

    def test_unsafe_paths_and_symlink(self):
        for root in ('relative', str(ROOT / 'trace'), str(self.home), '/tmp/outside-council-trace'):
            self.run_cli('{"outcome":"direct_execution"}', env={**self.env, 'AGENT_COUNCIL_TRACE_DIR': root})
        self.assertEqual(list(self.home.iterdir()), [])
        target = self.home / 'target'
        target.mkdir(mode=0o700)
        (self.home / 'alias').symlink_to(target, target_is_directory=True)
        env = {**self.env, 'AGENT_COUNCIL_TRACE_DIR': str(self.home / 'alias')}
        self.run_cli('{"outcome":"direct_execution"}', env=env)
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual(trace.inspect_trace(env)["state"], "unavailable")
        file_target = target / 'keep'
        file_target.write_text('keep')
        (target / 'decisions.jsonl').symlink_to(file_target)
        self.run_cli('{"outcome":"direct_execution"}', env={**self.env, 'AGENT_COUNCIL_TRACE_DIR': str(target)})
        self.assertEqual(file_target.read_text(), 'keep')

    def test_concurrent_writes(self):
        children = [subprocess.Popen([sys.executable, str(SCRIPT), 'decision'], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env) for _ in range(24)]
        for child in children:
            stdout, stderr = child.communicate('{"outcome":"lightweight_routing"}', timeout=15)
            self.assertEqual((child.returncode, stdout, stderr), (0, '', ''))
        rows = self.records()
        self.assertEqual(len(rows), len(children))
        self.assertEqual(len({row['event_id'] for row in rows}), len(children))

    def test_quota_never_deletes_and_permission_failure_is_silent(self):
        self.run_cli('{"outcome":"direct_execution"}')
        file = self.home / '.local/state/agent-council/decisions.jsonl'
        file.write_bytes(b' ' * trace.MAX_BYTES)
        before = file.read_bytes()
        self.run_cli('{"outcome":"direct_execution"}')
        self.assertEqual(file.read_bytes(), before)
        self.assertEqual(trace.inspect_trace(self.env)['state'], 'quota')
        file.chmod(0o644)
        self.assertEqual(trace.inspect_trace(self.env)['state'], 'unavailable')
        with patch.object(trace.os, 'open', side_effect=PermissionError):
            self.assertEqual(trace.append_record(trace.make_record({'outcome': 'direct_execution'}, self.env), self.env), 'unavailable')

    def test_hook_failure_keeps_activation_and_never_counts_as_compliance(self):
        hooks = json.loads((ROOT / 'hooks/hooks.json').read_text())['hooks']
        for event in ('SessionStart', 'UserPromptSubmit'):
            command = next(item['command'] for group in hooks[event] for item in group['hooks'] if 'agent-council-routing.sh' in item['command'])
            for markers in ({'PLUGIN_ROOT': str(ROOT)}, {'CLAUDE_PLUGIN_ROOT': str(ROOT)},
                            {'PLUGIN_ROOT': str(ROOT), 'CLAUDE_PLUGIN_ROOT': '/does not exist'}):
                env = {**self.env, **markers, 'AGENT_COUNCIL_TRACE_DIR': '/invalid'}
                result = subprocess.run(['bash', '-c', command], input='{"prompt":"must never persist"}', text=True, capture_output=True, env=env)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['hookEventName'], event)
            result = subprocess.run(['bash', '-c', command], input='{}', text=True, capture_output=True, env=self.env)
            self.assertEqual((result.returncode, result.stdout), (0, ''))
        self.run_cli('{"prompt":"discarded in memory"}', 'hook', '--event', 'SessionStart')
        state = trace.inspect_trace(self.env)
        self.assertEqual(state['hook_observations'], 1)
        self.assertEqual(state['agent_reports'], 0)
        self.assertEqual(state['actual_agent_compliance'], 'unknown')

    def test_status_is_read_only_and_xdg_is_confined(self):
        self.assertEqual(trace.inspect_trace(self.env)['state'], 'unavailable')
        self.assertEqual(list(self.home.iterdir()), [])
        env = {**self.env, 'XDG_STATE_HOME': str(self.home / 'state with spaces')}
        self.run_cli('{"outcome":"skipped"}', env=env)
        self.assertTrue((self.home / 'state with spaces/agent-council/decisions.jsonl').is_file())
        self.assertEqual(trace.inspect_trace(env)['agent_reports'], 1)
        self.assertEqual(trace.inspect_trace({**self.env, 'XDG_STATE_HOME': '/tmp'})['state'], 'unavailable')

    def test_schema_matches_runtime_and_unknown_records_are_not_reports(self):
        schema = json.loads((ROOT / 'standards/agent-council-decision-trace.schema.v1.yaml').read_text())
        self.assertEqual(schema, trace.schema_document())
        self.run_cli('{"outcome":"blocked","limitation_codes":["authority_required"]}')
        file = self.home / '.local/state/agent-council/decisions.jsonl'
        with file.open('a') as stream:
            stream.write('{"event_kind":"agent_decision","prompt":"not a valid record"}\n')
        state = trace.inspect_trace(self.env)
        self.assertEqual(state['agent_reports'], 1)
        self.assertEqual(state['unknown_records'], 1)
        self.assertEqual(state['agent_reported_outcomes']['blocked'], 1)
        self.assertEqual(state['agent_reported_outcomes']['direct_execution'], 0)

    def test_hook_root_spaces_token_and_input_privacy(self):
        package = self.home / 'package root with spaces'
        (package / 'hooks').mkdir(parents=True)
        (package / 'scripts').mkdir()
        shutil.copy2(ROOT / 'hooks/agent-council-routing.sh', package / 'hooks/agent-council-routing.sh')
        shutil.copy2(SCRIPT, package / 'scripts/AgentCouncilTrace.py')
        # A packaged install can be inside HOME. State must still be external.
        env = {**self.env, 'PLUGIN_ROOT': str(package), 'AGENT_COUNCIL_TRACE_SESSION_TOKEN': '12d7f7af-6132-4325-9a5e-50f690682841'}
        result = subprocess.run(['bash', str(package / 'hooks/agent-council-routing.sh'), 'SessionStart'],
                                input='{"prompt":"private canary", "session_id":"secret"}', text=True, capture_output=True, env=env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['hookEventName'], 'SessionStart')
        rows = self.records()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['session_token'], env['AGENT_COUNCIL_TRACE_SESSION_TOKEN'])
        self.assertNotIn('private canary', json.dumps(rows))
        self.assertNotIn('secret', json.dumps(rows))

    def test_hardlinks_nonregular_files_and_locked_storage_fail_closed(self):
        self.run_cli('{"outcome":"direct_execution"}')
        file = self.home / '.local/state/agent-council/decisions.jsonl'
        before = file.read_bytes()
        alias = file.with_name('alias')
        os.link(file, alias)
        self.run_cli('{"outcome":"direct_execution"}')
        self.assertEqual(file.read_bytes(), before)
        self.assertEqual(trace.inspect_trace(self.env)['state'], 'unavailable')
        alias.unlink()
        with file.open('r') as stream:
            trace.fcntl.flock(stream, trace.fcntl.LOCK_EX)
            result = self.run_cli('{"outcome":"direct_execution"}')
            self.assertEqual(result.returncode, 0)
            self.assertEqual(trace.inspect_trace(self.env)['state'], 'unavailable')
        self.assertEqual(file.read_bytes(), before)
        file.unlink()
        os.mkfifo(file, 0o600)
        self.assertEqual(self.run_cli('{"outcome":"direct_execution"}').returncode, 0)
        self.assertEqual(trace.inspect_trace(self.env)['state'], 'unavailable')

    def test_record_limit_input_spoofing_and_diagnostic_read_only(self):
        record = trace.make_record({'outcome': 'direct_execution'}, self.env)
        with patch.object(trace, 'MAX_RECORD', 32):
            self.assertEqual(trace.append_record(record, self.env), 'invalid')
        self.assertEqual(list(self.home.iterdir()), [])
        for document in ({'evidence_source': 'hook_observed'}, {'activation_source': 'session_start_hook'},
                         {'requested_model': 'private prompt'}, {'method_ids': ['private prompt']},
                         {'plugin_ids': ['unrecognized']}, {'requested_effort': True},
                         {'session_token': 'private session'}, {'metadata': {'prompt': 'secret'}}):
            self.run_cli(json.dumps(document))
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(trace.append_record(record, self.env), 'recorded')
        file = self.home / '.local/state/agent-council/decisions.jsonl'
        before = file.read_bytes()
        with patch.object(trace, 'MAX_RECORDS', 1):
            self.assertEqual(trace.append_record(record, self.env), 'quota')
            self.assertEqual(trace.inspect_trace(self.env)['state'], 'quota')
        self.assertEqual(file.read_bytes(), before)
        inventory = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in self.home.rglob('*')}
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/Diagnose-AgentCouncil.py')],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0)
        diagnosis = json.loads(result.stdout)
        self.assertEqual(diagnosis['decision_trace']['agent_reports'], 1)
        self.assertEqual(diagnosis['actual_agent_compliance']['status'], 'unknown')
        self.assertEqual(inventory, {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in self.home.rglob('*')})


if __name__ == '__main__':
    unittest.main()
