#!/usr/bin/env python3
"""Synthetic parser tests only; these do not constitute native probe evidence."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ClaudeAgentProbe import verify
from ClaudeQualificationHarness import current_release_binding, transcript_effort_matches
from AgentCouncilPromotion import canonical, sha256


class ProbeTests(unittest.TestCase):
    def test_historical_unsupported_effort_requires_explicit_null(self) -> None:
        self.assertTrue(transcript_effort_matches({"perTurnEffort": None}, None))
        for row in ({}, {"effort": None}, {"effort": "high", "perTurnEffort": None},
                    {"perTurnEffort": "high"}):
            with self.subTest(row=row):
                self.assertFalse(transcript_effort_matches(row, None))

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        source = Path(__file__).resolve().parents[1]
        self.candidate_root = root / "candidate-package"
        inventory = json.loads((source / "standards/behavioral-inventory.v1.json").read_text())
        for relative in set(inventory["paths"] + ["standards/behavioral-inventory.v1.json"]):
            target = self.candidate_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
        registry_path = self.candidate_root / "standards/agent-model-registry.v3.yaml"
        registry = json.loads(registry_path.read_text())
        if any(binding["status"] != "candidate" for binding in registry["bindings"]):
            for binding in registry["bindings"]:
                binding["status"] = "candidate"
                binding.pop("qualified_roles", None)
                binding["binding_sha256"] = sha256(canonical({key: value for key, value in binding.items() if key != "binding_sha256"}))
            for state in registry["provider_states"].values():
                state["council_status"] = "fail_closed_until_qualified"
            registry["registry_sha256"] = sha256(canonical({key: value for key, value in registry.items() if key != "registry_sha256"}))
            registry_path.write_text(json.dumps(registry) + "\n")
        self.parent = root / "parent.jsonl"
        self.child = root / "subagents" / "agent-a1.jsonl"
        self.child.parent.mkdir()
        self.release = root / "release.json"
        self.release.write_text(json.dumps(current_release_binding(self.candidate_root)), encoding="utf-8")
        self.debug_log = root / "s1.txt"
        self.binding = "claude-code-v3-technical"
        self.model = "claude-opus-5-5"
        self.parent_rows = [
            {"type": "assistant", "sessionId": "s1", "message": {"content": [
                {"type": "tool_use", "id": "u1", "name": "Agent", "input": {
                    "subagent_type": "agent-council:council-technical", "prompt": "Verify one fixture."}},
                {"type": "tool_use", "id": "other", "name": "Read", "input": {"file_path": "x"}},
            ]}},
            {"type": "user", "sessionId": "s1", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "u1", "content": "Launched"},
            ]}, "toolUseResult": {"agentId": "a1", "resolvedModel": self.model,
                                   "status": "async_launched", "isAsync": True}},
            {"type": "user", "sessionId": "s1", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "other", "content": "read"},
            ]}, "toolUseResult": "unrelated"},
            {"type": "user", "sessionId": "s1", "origin": {"kind": "task-notification", "producer": "session-task"},
             "message": {"content": "<task-notification><task-id>a1</task-id><tool-use-id>u1</tool-use-id><status>completed</status></task-notification>"}},
        ]
        self.child_rows = [
            {"type": "assistant", "isSidechain": True, "agentId": "a1", "sessionId": "s1",
             "effort": "medium", "uuid": "handback-row", "message": {"model": self.model, "content": [
                 {"type": "tool_use", "id": "h1", "name": "SubagentHandback", "input": {"message": "done"}}]}},
            {"type": "user", "isSidechain": True, "agentId": "a1", "sessionId": "s1",
             "sourceToolAssistantUUID": "handback-row", "message": {"content": [
                 {"type": "tool_result", "tool_use_id": "h1", "content": []}]},
             "toolUseResult": {"success": True}},
        ]
        self.save()
        self.save_log()

    def save_log(self, candidate_root: Path | None = None, session: str = "s1") -> None:
        candidate_root = (candidate_root or self.candidate_root).resolve()
        self.debug_log = self.debug_log.with_name(session + ".txt")
        self.debug_log.write_text(
            f"[DEBUG] --plugin-dir {candidate_root} is one plugin: .claude-plugin at its top marks it\n"
            "[DEBUG] Loaded inline plugin from path: agent-council\n"
            '[DEBUG] Plugin "agent-council" from --plugin-dir overrides installed version\n', encoding="utf-8")

    def save(self) -> None:
        self.parent.write_text("".join(json.dumps(row) + "\n" for row in self.parent_rows), encoding="utf-8")
        self.child.write_text("".join(json.dumps(row) + "\n" for row in self.child_rows), encoding="utf-8")

    def probe(self) -> dict:
        return verify(self.parent, self.child, self.binding, self.release, root=self.candidate_root, debug_log=self.debug_log)

    def rejected(self, code: str) -> None:
        with self.assertRaisesRegex(ValueError, code):
            self.probe()

    def test_complete_async_probe(self) -> None:
        result = self.probe()
        self.assertEqual(result["result"], "passed")
        self.assertEqual(result["child_assistant_rows"], 1)
        self.assertEqual(result["completion_evidence"], "task_notification_handback")
        self.assertEqual(result["agent_id"], "a1")
        self.assertEqual(len(result["parent_transcript_sha256"]), 64)
        self.assertEqual(len(result["loader_debug_log_sha256"]), 64)

    def test_loader_wrong_root_and_session_rejected(self) -> None:
        self.save_log(Path(self.temp.name) / "stale-candidate")
        self.rejected("PROBE_LOADER_ROOT_MISMATCH")
        self.save_log(session="other-session")
        self.rejected("PROBE_LOADER_SESSION_MISMATCH")

    def test_loader_missing_and_forged_order_rejected(self) -> None:
        self.debug_log.write_text("", encoding="utf-8")
        self.rejected("PROBE_LOADER_ORDER_INVALID")

    def test_loader_repeated_complete_triplet_accepted(self) -> None:
        triplet = self.debug_log.read_text(encoding="utf-8")
        self.debug_log.write_text(triplet + triplet, encoding="utf-8")
        self.assertEqual(self.probe()["result"], "passed")

    def test_loader_repeated_incomplete_triplet_rejected(self) -> None:
        triplet = self.debug_log.read_text(encoding="utf-8")
        self.debug_log.write_text(triplet + triplet.splitlines()[0] + "\n", encoding="utf-8")
        self.rejected("PROBE_LOADER_ORDER_INVALID")
        self.save_log()
        lines = self.debug_log.read_text(encoding="utf-8").splitlines()
        self.debug_log.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")
        self.rejected("PROBE_LOADER_ORDER_INVALID")

    def test_distinct_candidate_root_uses_its_registry(self) -> None:
        source = self.candidate_root
        candidate = Path(self.temp.name) / "candidate"
        inventory = json.loads((source / "standards/behavioral-inventory.v1.json").read_text())
        for relative in inventory["paths"] + ["standards/behavioral-inventory.v1.json", "agents/council-technical.md"]:
            target = candidate / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
        registry_path = candidate / "standards/agent-model-registry.v3.yaml"
        registry = json.loads(registry_path.read_text())
        binding = next(item for item in registry["bindings"] if item["binding_id"] == self.binding)
        binding["model_id"] = "other-candidate-model"
        binding["binding_sha256"] = sha256(canonical({key: value for key, value in binding.items() if key != "binding_sha256"}))
        registry["registry_sha256"] = sha256(canonical({key: value for key, value in registry.items() if key != "registry_sha256"}))
        registry_path.write_text(json.dumps(registry) + "\n", encoding="utf-8")
        agent = candidate / "agents/council-technical.md"
        agent.write_text(agent.read_text().replace("model: claude-opus-5-5", "model: other-candidate-model"), encoding="utf-8")
        self.release.write_text(json.dumps(current_release_binding(candidate)), encoding="utf-8")
        self.save_log(candidate)
        with self.assertRaisesRegex(ValueError, "PROBE_RESOLVED_MODEL_MISMATCH"):
            verify(self.parent, self.child, self.binding, self.release, root=candidate, debug_log=self.debug_log)

    def test_distinct_model_reserve_uses_binding_scoped_agent(self) -> None:
        source = self.candidate_root
        candidate = Path(self.temp.name) / "reserve-candidate"
        inventory_path = source / "standards/behavioral-inventory.v1.json"
        inventory = json.loads(inventory_path.read_text())
        for relative in inventory["paths"] + ["standards/behavioral-inventory.v1.json"]:
            target = candidate / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
        self.binding = "claude-code-v3-technical-reserve"
        self.model = "claude-sonnet-5-5"
        registry_path = candidate / "standards/agent-model-registry.v3.yaml"
        registry = json.loads(registry_path.read_text())
        original = next(item for item in registry["bindings"] if item["binding_id"] == "claude-code-v3-technical")
        reserve = dict(original, binding_id=self.binding, model_id=self.model,
                       selection={"role": "reserve", "priority": 1, "fallback_for": []})
        reserve["binding_sha256"] = sha256(canonical({key: value for key, value in reserve.items() if key != "binding_sha256"}))
        registry["bindings"].append(reserve)
        registry["registry_sha256"] = sha256(canonical({key: value for key, value in registry.items() if key != "registry_sha256"}))
        registry_path.write_text(json.dumps(registry) + "\n", encoding="utf-8")
        agent_path = candidate / "agents" / (self.binding + ".md")
        original_agent = (candidate / "agents/council-technical.md").read_text()
        agent_path.write_text(original_agent.replace("council-technical", self.binding).replace("claude-opus-5-5", self.model), encoding="utf-8")
        inventory["paths"].append("agents/" + self.binding + ".md")
        (candidate / "standards/behavioral-inventory.v1.json").write_text(json.dumps(inventory) + "\n", encoding="utf-8")
        self.parent_rows[0]["message"]["content"][0]["input"]["subagent_type"] = "agent-council:" + self.binding
        self.parent_rows[1]["toolUseResult"]["resolvedModel"] = self.model
        self.child_rows[0]["message"]["model"] = self.model
        self.save()
        self.save_log(candidate)
        self.release.write_text(json.dumps(current_release_binding(candidate)), encoding="utf-8")
        result = verify(self.parent, self.child, self.binding, self.release, root=candidate, debug_log=self.debug_log)
        self.assertEqual(result["subagent_type"], "agent-council:" + self.binding)
        self.assertEqual(result["model_id"], self.model)

    def test_native_desktop_child_layout(self) -> None:
        native_child = self.parent.parent / self.parent.stem / "subagents" / self.child.name
        native_child.parent.mkdir(parents=True)
        self.child.replace(native_child)
        self.child = native_child
        self.assertEqual(self.probe()["agent_id"], "a1")

    def test_unrelated_child_layout_rejected(self) -> None:
        unrelated_child = self.parent.parent / "other-session" / "subagents" / self.child.name
        unrelated_child.parent.mkdir(parents=True)
        self.child.replace(unrelated_child)
        self.child = unrelated_child
        self.rejected("PROBE_CHILD_PATH_MISMATCH")

    def test_async_launch_alone_is_insufficient(self) -> None:
        self.parent_rows.pop()
        self.save()
        self.rejected("PROBE_ASYNC_COMPLETION_MISSING")

    def test_child_end_turn_without_notification_is_insufficient(self) -> None:
        self.parent_rows.pop()
        self.child_rows[0]["message"]["stop_reason"] = "end_turn"
        self.save()
        self.rejected("PROBE_ASYNC_COMPLETION_MISSING")

    def test_failed_notification_rejected(self) -> None:
        self.parent_rows[3]["message"]["content"] = self.parent_rows[3]["message"]["content"].replace("completed", "failed")
        self.save()
        self.rejected("PROBE_ASYNC_COMPLETION_INVALID")

    def test_async_completion_from_other_parent_session_rejected(self) -> None:
        self.parent_rows[3]["sessionId"] = "other-session"
        self.save()
        self.rejected("PROBE_ASYNC_SESSION_MISMATCH")

    def test_wrong_tool_notification_rejected(self) -> None:
        self.parent_rows[3]["message"]["content"] = self.parent_rows[3]["message"]["content"].replace("u1", "other")
        self.save()
        self.rejected("PROBE_ASYNC_COMPLETION_INVALID")

    def test_other_agent_notification_rejected(self) -> None:
        self.parent_rows[3]["message"]["content"] = self.parent_rows[3]["message"]["content"].replace("a1", "a2")
        self.save()
        self.rejected("PROBE_ASYNC_COMPLETION_MISSING")

    def test_plain_parent_result_cannot_replace_notification(self) -> None:
        self.parent_rows[3] = {"type": "user", "sessionId": "s1", "toolUseResult": {
            "agentId": "a1", "resolvedModel": self.model, "status": "completed"}}
        self.save()
        self.rejected("PROBE_ASYNC_COMPLETION_MISSING")

    def test_notification_requires_native_origin(self) -> None:
        self.parent_rows[3].pop("origin")
        self.save()
        self.rejected("PROBE_ASYNC_COMPLETION_MISSING")

    def test_handback_failure_and_wrong_tool_rejected(self) -> None:
        self.child_rows[1]["toolUseResult"]["success"] = False
        self.save()
        self.rejected("PROBE_ASYNC_HANDBACK_INVALID")
        self.child_rows[1]["toolUseResult"]["success"] = True
        self.child_rows[1]["message"]["content"][0]["tool_use_id"] = "other"
        self.save()
        self.rejected("PROBE_ASYNC_HANDBACK_INVALID")

    def test_handback_source_identity_required(self) -> None:
        self.child_rows[1]["sourceToolAssistantUUID"] = "other-assistant"
        self.save()
        self.rejected("PROBE_ASYNC_HANDBACK_INVALID")

    def test_duplicate_target_call_rejected(self) -> None:
        extra = dict(self.parent_rows[0]["message"]["content"][0])
        extra["id"] = "u2"
        self.parent_rows[0]["message"]["content"].append(extra)
        self.save()
        self.rejected("PROBE_TARGET_CALL_COUNT_INVALID")

    def test_model_and_effort_are_exact(self) -> None:
        self.child_rows[0]["message"]["model"] = "claude-sonnet-5"
        self.save()
        self.rejected("PROBE_CHILD_MODEL_MISMATCH")
        self.child_rows[0]["message"]["model"] = self.model
        del self.child_rows[0]["effort"]
        self.save()
        self.rejected("PROBE_CHILD_EFFORT_MISMATCH")

    def test_substitution_rejected(self) -> None:
        self.parent_rows[1]["toolUseResult"]["agentId"] = "a2"
        self.save()
        self.rejected("PROBE_CHILD_PATH_MISMATCH")

    def test_frozen_release_binding_required(self) -> None:
        frozen = current_release_binding()
        frozen["eval_suite_sha256"] = "0" * 64
        self.release.write_text(json.dumps(frozen), encoding="utf-8")
        self.rejected("PROBE_RELEASE_BINDING_MISMATCH")

    def test_malformed_json_and_result_rejected(self) -> None:
        self.parent.write_text('{"type":"assistant"}\n{bad}\n', encoding="utf-8")
        self.rejected("PROBE_TRANSCRIPT_JSON_INVALID")
        self.save()
        self.parent_rows[1]["toolUseResult"] = "unexpected string"
        self.save()
        self.rejected("PROBE_AGENT_RESULT_INVALID")

    def test_haiku_worker_requires_explicit_null_effort(self) -> None:
        self.binding = "claude-code-v3-worker"
        self.model = "claude-haiku-4-5-20251001"
        self.parent_rows[0]["message"]["content"][0]["input"]["subagent_type"] = "agent-council:council-worker"
        self.parent_rows[1]["toolUseResult"]["resolvedModel"] = self.model
        self.child_rows[0]["message"]["model"] = self.model
        del self.child_rows[0]["effort"]
        self.save()
        self.rejected("PROBE_CHILD_EFFORT_MISMATCH")
        self.child_rows[0]["perTurnEffort"] = None
        self.save()
        self.assertIsNone(self.probe()["effort"])
        for key, value in (("effort", "medium"), ("perTurnEffort", "medium")):
            with self.subTest(key=key):
                self.child_rows[0].pop("effort", None)
                self.child_rows[0]["perTurnEffort"] = None
                self.child_rows[0][key] = value
                self.save()
                self.rejected("PROBE_CHILD_EFFORT_MISMATCH")

    def test_conflicting_per_turn_effort_rejected(self) -> None:
        self.child_rows[0]["perTurnEffort"] = "low"
        self.save()
        self.rejected("PROBE_CHILD_EFFORT_MISMATCH")


if __name__ == "__main__":
    unittest.main()
