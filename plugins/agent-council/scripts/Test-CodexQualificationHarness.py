#!/usr/bin/env python3
"""Synthetic collector tests, never native qualification or promotion evidence."""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

import CodexQualificationHarness as harness
import AgentCouncilPromotion as promotion


class QualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-qualification-test-")
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "package"
        paths = set(harness.V3_CANDIDATE_FILES) | set(harness.HARNESS_FILES) | {harness.REQUESTS}
        for name in paths:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(harness.ROOT / name, target)
        # The fixture always starts from a candidate, even after release work.
        registry = harness.decode((self.root / harness.REGISTRY).read_bytes())
        registry["provider_states"]["codex"] = {"council_status": "fail_closed_until_qualified"}
        for binding in registry["bindings"]:
            if binding["provider"] == "codex":
                binding["status"] = "candidate"
                binding.pop("qualified_roles", None)
                binding["binding_sha256"] = harness.sha(harness.canonical({k: v for k, v in binding.items() if k != "binding_sha256"}))
        registry["registry_sha256"] = harness.sha(harness.canonical({k: v for k, v in registry.items() if k != "registry_sha256"}))
        (self.root / harness.REGISTRY).write_bytes(harness.canonical(registry))
        # Deliberate scorer-only material must not reach the public prompt.
        request_lines = []
        for scenario in sorted(harness.EXPECTED_CLAIMS):
            request_lines.extend([f'  - id: "{scenario}"', f'    request: "Bounded request {scenario}"',
                                  '    expected: ["DO_NOT_EXPOSE_ORACLE"]'])
        (self.root / harness.REQUESTS).write_text("\n".join(request_lines) + "\n")
        (self.root / "evals").mkdir()
        (self.root / "evals/fixture.yaml").write_text("synthetic: true\n")
        paths.add("evals/fixture.yaml")
        self.inventory_path = self.root / "standards/behavioral-inventory.v1.json"
        self.inventory = {"schema_version": "agent-council.behavioral-inventory/v1",
                          "identity_version": "test/v1", "paths": sorted(paths)}
        self.inventory_path.write_bytes(harness.canonical(self.inventory))
        self.workspace = self.base / "prepared"
        self.manifest = harness.prepare(self.root, self.workspace)
        self.binding_id = "codex-v3-ultimate"
        self.run_id = "native-forward-run-1"
        self.native_transcripts: dict[str, tuple[Path, Path]] = {}
        self.make_transcripts()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_setup_normalizes_promoted_codex_roles_without_changing_other_provider(self) -> None:
        promoted_root = self.base / "promoted-shaped-source"
        shutil.copytree(self.root, promoted_root)
        registry = harness.decode((promoted_root / harness.REGISTRY).read_bytes())
        for binding in registry["bindings"]:
            binding["status"] = "qualified"
            tiers = harness.role_protocol.TIERS
            binding["qualified_roles"] = list(tiers[:tiers.index(binding["tier"]) + 1])
            binding["binding_sha256"] = harness.sha(harness.canonical({k: v for k, v in binding.items() if k != "binding_sha256"}))
        for state in registry["provider_states"].values():
            state["council_status"] = "qualified"
        registry["registry_sha256"] = harness.sha(harness.canonical({k: v for k, v in registry.items() if k != "registry_sha256"}))
        promoted_bytes = harness.canonical(registry)
        promotion.registry(promoted_bytes, status="qualified")
        (promoted_root / harness.REGISTRY).write_bytes(promoted_bytes)
        nested = QualificationTests()
        try:
            with mock.patch.object(harness, "ROOT", promoted_root):
                nested.setUp()
                normalized = promotion.registry((nested.root / harness.REGISTRY).read_bytes())
                self.assertEqual(normalized["provider_states"]["codex"],
                                 {"council_status": "fail_closed_until_qualified"})
                self.assertEqual(normalized["provider_states"]["claude_code"], registry["provider_states"]["claude_code"])
                for actual, original in zip(normalized["bindings"], registry["bindings"]):
                    if actual["provider"] == "codex":
                        self.assertEqual(actual["status"], "candidate")
                        self.assertNotIn("qualified_roles", actual)
                        expected = {**original, "status": "candidate"}
                        expected.pop("qualified_roles")
                        expected["binding_sha256"] = harness.sha(harness.canonical(
                            {k: v for k, v in expected.items() if k != "binding_sha256"}))
                        self.assertEqual(actual, expected)
                    else:
                        self.assertEqual(actual, original)
                self.assertEqual((promoted_root / harness.REGISTRY).read_bytes(), promoted_bytes)
        finally:
            if hasattr(nested, "temporary"):
                nested.tearDown()

    def make_transcripts(self, run_id: str = "native-forward-run-1", *, encrypted: bool = False) -> None:
        self.run_id = run_id
        self.parent_path = self.base / ("parent-" + run_id + ".jsonl")
        self.child_path = self.base / ("child-" + run_id + ".jsonl")
        self.native_transcripts[run_id] = (self.parent_path, self.child_path)
        plan = next(item for item in self.manifest["dispatches"]
                    if item["binding_id"] == self.binding_id and item["run_id"] == run_id)
        args = copy.deepcopy(plan["spawn_arguments"])
        prompt = (self.workspace / harness.PROMPT_NAME).read_text()
        args["message"] = prompt
        agent_path = "/root/" + args["task_name"]
        child_id = "child-" + run_id
        turn_id = "turn-" + run_id
        call_id = "call-" + run_id
        def row(kind: str, payload: dict) -> dict:
            return {"timestamp": "2026-09-29T15:00:00Z", "type": kind, "payload": payload}
        self.parent = [row("session_meta", {"id": "parent"}),
                       row("response_item", {"type": "function_call", "name": "spawn_agent", "call_id": call_id,
                                             "arguments": json.dumps(args)}),
                       row("response_item", {"type": "function_call_output", "call_id": call_id,
                                             "output": json.dumps({"task_name": agent_path})})]
        header = f"Message Type: NEW_TASK\nTask name: {agent_path}\nSender: /root\nPayload:\n"
        content = [{"type": "input_text", "text": header}, {"type": "encrypted_content", "encrypted_content": "synthetic-opaque-payload"}] if encrypted else [{"type": "input_text", "text": header + prompt}]
        self.response = {"schema_version": harness.RESPONSE, "results": [
            {"scenario_id": scenario, "claims": sorted(claims), "rationale": "Synthetic scorer fixture."}
            for scenario, claims in sorted(harness.EXPECTED_CLAIMS.items())]}
        if "qualification_protocol" in self.manifest:
            binding = next(item for item in self.manifest["bindings"] if item["binding_id"] == self.binding_id)
            self.response = {"schema_version": harness.role_protocol.RESPONSE, "results": [
                {"scenario_id": case["scenario_id"], "output": copy.deepcopy(case["expected_output"]), "actions": []}
                for case in harness.role_protocol.suite_cases(binding)]}
        self.child = [
            row("session_meta", {"id": child_id, "model_provider": "openai", "cli_version": "synthetic", "originator": "Synthetic collector test",
                                 "source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent", "agent_path": agent_path, "depth": 1}}}}),
            row("event_msg", {"type": "task_started", "turn_id": turn_id}),
            row("response_item", {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "Synthetic platform instructions."}]}),
            row("response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Synthetic user configuration."}]}),
            row("turn_context", {"turn_id": turn_id, "model": args["model"], "effort": args["reasoning_effort"]}),
            row("response_item", {"type": "agent_message", "author": "/root", "recipient": agent_path, "content": content,
                                  "internal_chat_message_metadata_passthrough": {"turn_id": turn_id}}),
            row("response_item", {"type": "reasoning", "summary": "Private synthetic reasoning, never export."}),
            row("response_item", {"type": "message", "role": "assistant", "phase": "final_answer",
                                  "content": [{"type": "output_text", "text": json.dumps(self.response)}],
                                  "internal_chat_message_metadata_passthrough": {"turn_id": turn_id}}),
            row("event_msg", {"type": "task_complete", "turn_id": turn_id}),
        ]
        self.persist()

    def persist(self) -> None:
        for path, records in ((self.parent_path, self.parent), (self.child_path, self.child)):
            path.write_bytes(b"".join(harness.canonical(item) + b"\n" for item in records))

    def file_delivery(self, run_id: str = "native-forward-run-1") -> None:
        if self.manifest.get("delivery_mode") != "file":
            self.workspace = self.base / "prepared-file"
            self.manifest = harness.prepare(self.root, self.workspace, delivery_mode="file")
        self.make_transcripts(run_id)
        delivery = self.manifest["file_delivery"]
        message = delivery["spawn_message"]
        args = json.loads(self.parent[1]["payload"]["arguments"])
        args["message"] = message
        self.parent[1]["payload"]["arguments"] = json.dumps(args)
        old_text = self.child[5]["payload"]["content"][0]["text"]
        self.child[5]["payload"]["content"][0]["text"] = old_text.split("Payload:\n", 1)[0] + "Payload:\n" + message
        turn = self.child[1]["payload"]["turn_id"]
        link = {"internal_chat_message_metadata_passthrough": {"turn_id": turn}}
        read_call = {"type": "response_item", "payload": {
            "type": "custom_tool_call", "name": "exec", "call_id": "read-prompt",
            "input": delivery["read_call_input"], **link}}
        read_result = {"type": "response_item", "payload": {
            "type": "custom_tool_call_output", "call_id": "read-prompt", **link,
            "output": [{"type": "input_text", "text": "Script completed\nWall time 0.1 seconds\nOutput:\n"},
                       {"type": "input_text", "text": (self.workspace / harness.PROMPT_NAME).read_text()}]}}
        self.child[6:6] = [read_call, read_result]
        self.persist()

    def test_role_suites_freeze_score_pair_all_bindings(self) -> None:
        for binding in self.manifest["bindings"]:
            self.binding_id = binding["binding_id"]
            self.workspace = self.base / ("role-" + self.binding_id)
            self.manifest = harness.prepare(self.root, self.workspace, binding_id=self.binding_id)
            self.assertEqual(len(self.manifest["dispatches"]), 2)
            self.assertEqual(self.manifest["qualification_protocol"], harness.role_protocol.protocol_binding(binding))
            prompt = (self.workspace / harness.PROMPT_NAME).read_text()
            self.assertNotIn('"expected_output"', prompt)
            self.assertIn(harness.role_protocol.ROLE_FILES[binding["tier"]], prompt)
            receipts = []
            for run_id in sorted(harness.RUN_IDS):
                self.make_transcripts(run_id)
                receipts.append(self.score())
            pair = self.pair(receipts)
            self.assertEqual(pair["qualification_protocol"], self.manifest["qualification_protocol"])
            self.assertFalse(pair["full_context_blindness_verified"])
            forged = copy.deepcopy(receipts)
            forged[0]["qualification_protocol"]["suite_sha256"] = "0" * 64
            with self.assertRaises(ValueError):
                self.pair(forged)

    def test_role_suite_rejects_prohibited_action_and_legacy_answer(self) -> None:
        self.workspace = self.base / "role-worker"
        self.binding_id = "codex-v3-worker"
        self.manifest = harness.prepare(self.root, self.workspace, binding_id=self.binding_id)
        self.make_transcripts()
        self.response["results"][0]["actions"] = ["send_email"]
        self.child[-2]["payload"]["content"][0]["text"] = json.dumps(self.response)
        self.persist()
        failed = self.score()
        self.assertEqual(failed["result"], "failed")
        self.assertEqual(failed["scenario_results"][0]["prohibited_actions"], ["send_email"])
        self.child[-2]["payload"]["content"][0]["text"] = json.dumps({"schema_version": harness.RESPONSE, "results": []})
        self.persist()
        with self.assertRaises(ValueError):
            self.score()

    def test_role_suite_rejects_tampered_selection(self) -> None:
        self.workspace = self.base / "role-tampered"
        self.manifest = harness.prepare(self.root, self.workspace, binding_id=self.binding_id)
        self.manifest["qualification_protocol"] = harness.role_protocol.protocol_binding({"tier": "worker_intelligence"})
        (self.workspace / harness.MANIFEST_NAME).write_bytes(harness.canonical(self.manifest))
        with self.assertRaisesRegex(ValueError, "FROZEN_CANDIDATE_CHANGED"):
            harness.load_preparation(self.root, self.workspace)

    def test_file_delivery_short_exact_message_and_verified_read(self) -> None:
        self.file_delivery()
        delivery = self.manifest["file_delivery"]
        self.assertLess(len(delivery["spawn_message"]), 2000)
        self.assertIn(str(self.workspace / harness.PROMPT_NAME), delivery["spawn_message"])
        self.assertIn(self.manifest["prompt_sha256"], delivery["spawn_message"])
        receipt = self.score()
        self.assertEqual(receipt["tool_calls"], 1)
        self.assertEqual(receipt["delivery_mode"], "file")
        self.assertTrue(receipt["native_evidence"]["file_prompt_bytes_verified"])
        self.assertFalse(receipt["provider_authenticity_verified"])

    def test_file_delivery_capacity_rejection_then_one_linked_spawn(self) -> None:
        self.file_delivery()
        successful_call = copy.deepcopy(self.parent[1])
        successful_result = copy.deepcopy(self.parent[2])
        successful_call["payload"]["call_id"] = "retry-call"
        successful_result["payload"]["call_id"] = "retry-call"
        self.parent[2]["payload"]["output"] = "collab spawn failed: agent thread limit reached"
        self.parent.extend([successful_call, successful_result])
        self.persist()
        receipt = self.score()
        self.assertEqual(receipt["native_evidence"]["spawn_call_id"], "retry-call")
        self.assertEqual(receipt["result"], "passed")

        self.parent.append(copy.deepcopy(successful_call))
        self.parent[-1]["payload"]["call_id"] = "duplicate-call"
        duplicate_result = copy.deepcopy(successful_result)
        duplicate_result["payload"]["call_id"] = "duplicate-call"
        self.parent.append(duplicate_result)
        self.assert_rejected("SPAWN_CALL_INVALID")

        self.parent = self.parent[:-2]
        self.parent[2]["payload"]["output"] = "unrecognized spawn failure"
        self.assert_rejected("SPAWN_RESULT_INVALID")

    def test_file_delivery_read_only_prompt_file(self) -> None:
        self.file_delivery()
        self.assertEqual((self.workspace / harness.PROMPT_NAME).stat().st_mode & 0o222, 0)

    def test_file_delivery_tampered_message_path_hash_or_read_call(self) -> None:
        self.file_delivery()
        for old, new in ((str(self.workspace / harness.PROMPT_NAME), "/tmp/other-prompt"),
                         (self.manifest["prompt_sha256"], "0" * 64)):
            self.file_delivery()
            args = json.loads(self.parent[1]["payload"]["arguments"])
            args["message"] = args["message"].replace(old, new)
            self.parent[1]["payload"]["arguments"] = json.dumps(args)
            self.assert_rejected("SPAWN_ARGUMENTS_MISMATCH")
        self.file_delivery()
        self.child[6]["payload"]["input"] += '\ntext("extra");'
        self.assert_rejected("FILE_READ_CALL_INVALID")

    def test_file_delivery_native_single_trailing_newline_is_accepted(self) -> None:
        self.file_delivery()
        self.child[6]["payload"]["input"] += "\n"
        self.persist()
        self.assertEqual(self.score()["result"], "passed")
        for suffix in ("\n\n", '\ntext("extra");\n', "\n ", "\r\n"):
            self.file_delivery()
            self.child[6]["payload"]["input"] += suffix
            self.assert_rejected("FILE_READ_CALL_INVALID")

    def test_file_delivery_truncated_changed_or_duplicate_output(self) -> None:
        self.file_delivery()
        original = self.child[7]["payload"]["output"][1]["text"]
        for output in (original[:-1], original + "extra", original.replace("council_reentry", "changed", 1)):
            self.file_delivery()
            self.child[7]["payload"]["output"][1]["text"] = output
            self.assert_rejected("FILE_READ_OUTPUT_INVALID")
        self.file_delivery()
        self.child[7]["payload"]["output"].append(copy.deepcopy(self.child[7]["payload"]["output"][1]))
        self.assert_rejected("FILE_READ_OUTPUT_INVALID")

    def test_file_delivery_missing_duplicate_extra_or_reordered_tools(self) -> None:
        for mutation in ("missing", "duplicate", "extra", "reorder", "after_final", "wrong_id", "wrong_turn"):
            self.file_delivery()
            if mutation == "missing":
                del self.child[6:8]
            elif mutation == "duplicate":
                self.child[8:8] = copy.deepcopy(self.child[6:8])
            elif mutation == "extra":
                self.child.insert(8, {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command"}})
            elif mutation == "reorder":
                self.child[6], self.child[7] = self.child[7], self.child[6]
            elif mutation == "after_final":
                reads = self.child[6:8]
                del self.child[6:8]
                self.child[-1:-1] = reads
            elif mutation == "wrong_id":
                self.child[7]["payload"]["call_id"] = "other"
            else:
                self.child[6]["payload"]["internal_chat_message_metadata_passthrough"]["turn_id"] = "other"
            self.persist()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.score()

    def test_file_delivery_native_command_event_and_usage_record(self) -> None:
        self.file_delivery()
        prompt = (self.workspace / harness.PROMPT_NAME).read_text()
        turn = self.child[1]["payload"]["turn_id"]
        self.child.insert(7, {"type": "event_msg", "payload": {"type": "item_completed", "turn_id": turn,
            "thread_id": self.child[0]["payload"]["id"], "item": {"type": "CommandExecution",
            "command": ["/bin/zsh", "-c", self.manifest["file_delivery"]["read_command"]],
            "status": "completed", "exit_code": 0, "stdout": prompt, "stderr": "",
            "aggregated_output": prompt, "formatted_output": "UI preview truncated"}}})
        self.child.insert(8, {"type": "token_usage_record", "payload": {"turn_id": turn,
                            "thread_id": self.child[0]["payload"]["id"]}})
        self.persist()
        self.assertEqual(self.score()["result"], "passed")
        self.child[7]["payload"]["item"]["command"][-1] += "; true"
        self.assert_rejected("FILE_READ_EVENT_INVALID")

    def test_file_delivery_pair_replays_tools_and_relocated_archive(self) -> None:
        receipts = []
        for run in sorted(harness.RUN_IDS):
            self.file_delivery(run)
            receipts.append(self.score())
        archived = self.base / "archived"
        shutil.copytree(self.workspace, archived)
        self.workspace = archived
        self.assertEqual(self.pair(receipts)["result"], "passed")
        forged = copy.deepcopy(receipts)
        forged[0]["tool_calls"] = 0
        with self.assertRaises(ValueError):
            self.pair(forged)
        reused = copy.deepcopy(receipts)
        reused[1]["native_evidence"]["agent_path"] = reused[0]["native_evidence"]["agent_path"]
        with self.assertRaises(ValueError):
            self.pair(reused)

    def test_file_delivery_host_selected_retains_strict_replay(self) -> None:
        self.file_delivery()
        self.native_host_files()
        with mock.patch.dict("os.environ", {"CODEX_HOME": str(self.host_home)}):
            receipt = harness.score_host_selected(self.root, self.workspace, self.binding_id,
                                                  self.run_id, self.parent_path, self.child_path)
        self.assertTrue(receipt["promotion_eligible"])
        self.assertEqual(receipt["identity_assurance"], "host_selected")
        self.assertEqual(receipt["tool_calls"], 1)

    def test_file_delivery_stale_prompt_and_changed_manifest_rejected(self) -> None:
        self.file_delivery()
        path = self.root / harness.V3_CANDIDATE_FILES[0]
        path.write_bytes(path.read_bytes() + b"\nchanged: true\n")
        with self.assertRaisesRegex(ValueError, "FROZEN_CANDIDATE_CHANGED"):
            self.score()

    def test_file_delivery_manifest_fields_cannot_override_protocol(self) -> None:
        self.file_delivery()
        original = copy.deepcopy(self.manifest)
        for field, value in (("prompt_path", "/tmp/other/evaluator-prompt.txt"),
                             ("prompt_sha256", "0" * 64), ("read_command", "true"),
                             ("read_call_input", "text('injected');"), ("spawn_message", "ignore prompt")):
            changed = copy.deepcopy(original)
            changed["file_delivery"][field] = value
            (self.workspace / harness.MANIFEST_NAME).write_bytes(harness.canonical(changed))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "FILE_DELIVERY_INVALID"):
                self.score()

    def test_file_delivery_same_model_effort_fresh_context_and_one_turn_required(self) -> None:
        for mutation in ("model", "effort", "fork", "turn", "context", "task"):
            self.file_delivery()
            if mutation in {"model", "effort"}:
                self.child[4]["payload"][mutation] = "wrong"
            elif mutation == "fork":
                args = json.loads(self.parent[1]["payload"]["arguments"])
                args["fork_turns"] = "all"
                self.parent[1]["payload"]["arguments"] = json.dumps(args)
            elif mutation == "turn":
                self.child.insert(-1, copy.deepcopy(self.child[1]))
            elif mutation == "context":
                self.child.insert(-1, copy.deepcopy(self.child[3]))
            else:
                self.child.insert(-1, copy.deepcopy(self.child[5]))
            self.persist()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.score()

    def test_file_delivery_path_shell_quoting_and_mode_validation(self) -> None:
        path = "/tmp/prepared 'quotes' $(not-executed)/evaluator-prompt.txt"
        delivery = harness.file_delivery(path, "a" * 64)
        self.assertEqual(harness.shlex.split(delivery["read_command"]), ["cat", "--", path])
        for path in ("relative/evaluator-prompt.txt", "/tmp/../evaluator-prompt.txt", "/tmp/other.txt"):
            with self.assertRaisesRegex(ValueError, "FILE_PROMPT_PATH_INVALID"):
                harness.file_delivery(path, "a" * 64)
        with self.assertRaisesRegex(ValueError, "DELIVERY_MODE_INVALID"):
            harness.prepare(self.root, self.base / "invalid", delivery_mode="unsafe")

    def encrypted_file_delivery(self) -> None:
        self.file_delivery()
        ciphertext = "gAAAA" + "opaque_native_ciphertext_" * 5 + "=="
        args = json.loads(self.parent[1]["payload"]["arguments"])
        args["message"] = ciphertext
        self.parent[1]["payload"]["arguments"] = json.dumps(args)
        delivered = self.child[5]["payload"]["content"][0]["text"]
        header = delivered.split("Payload:\n", 1)[0] + "Payload:\n"
        self.child[5]["payload"]["content"] = [{"type": "input_text", "text": header},
            {"type": "encrypted_content", "encrypted_content": ciphertext}]
        self.persist()

    def test_file_delivery_encrypted_bootstrap_binds_bytes_without_plaintext_claim(self) -> None:
        self.encrypted_file_delivery()
        receipt = self.score()
        evidence = receipt["native_evidence"]
        self.assertEqual(receipt["result"], "passed")
        self.assertTrue(evidence["encrypted_delivery_link_verified"])
        self.assertFalse(evidence["task_bootstrap_plaintext_verified"])
        self.assertFalse(evidence["spawn_message_plaintext_verified"])
        self.assertFalse(evidence["child_prompt_plaintext_verified"])
        self.assertTrue(evidence["file_prompt_bytes_verified"])
        self.assertFalse(receipt["full_context_blindness_verified"])
        self.assertFalse(receipt["provider_authenticity_verified"])

    def test_encrypted_thread_limit_retry_accepts_fresh_ciphertext(self) -> None:
        self.encrypted_file_delivery()
        successful_call = copy.deepcopy(self.parent[1])
        successful_result = copy.deepcopy(self.parent[2])
        successful_call["payload"]["call_id"] = "retry-call"
        successful_result["payload"]["call_id"] = "retry-call"
        rejected_args = json.loads(self.parent[1]["payload"]["arguments"])
        rejected_args["message"] = "gAAAA" + "different_valid_ciphertext_" * 5 + "=="
        self.parent[1]["payload"]["arguments"] = json.dumps(rejected_args)
        self.parent[2]["payload"]["output"] = "collab spawn failed: agent thread limit reached"
        self.parent.extend([successful_call, successful_result])
        self.persist()
        receipt = self.score()
        self.assertEqual(receipt["result"], "passed")
        self.assertEqual(receipt["native_evidence"]["spawn_call_id"], "retry-call")

        for mutation in ("invalid_ciphertext", "changed_model", "post_success"):
            with self.subTest(mutation=mutation):
                original = copy.deepcopy(self.parent)
                if mutation == "invalid_ciphertext":
                    args = json.loads(self.parent[1]["payload"]["arguments"])
                    args["message"] = "not-encrypted"
                    self.parent[1]["payload"]["arguments"] = json.dumps(args)
                elif mutation == "changed_model":
                    args = json.loads(self.parent[1]["payload"]["arguments"])
                    args["model"] = "other-model"
                    self.parent[1]["payload"]["arguments"] = json.dumps(args)
                else:
                    self.parent = [self.parent[0], *self.parent[3:], *self.parent[1:3]]
                self.assert_rejected("SPAWN_RESULT_INVALID")
                self.parent = original

    def test_file_delivery_encrypted_bootstrap_mismatch_and_plaintext_substitution_rejected(self) -> None:
        for mutation in ("mismatch", "plaintext_child", "model", "extra_arg", "truncated_read"):
            self.encrypted_file_delivery()
            if mutation == "mismatch":
                self.child[5]["payload"]["content"][1]["encrypted_content"] += "tampered"
            elif mutation == "plaintext_child":
                header = self.child[5]["payload"]["content"][0]["text"]
                self.child[5]["payload"]["content"] = [{"type": "input_text", "text":
                    header + self.manifest["file_delivery"]["spawn_message"]}]
            elif mutation in {"model", "extra_arg"}:
                args = json.loads(self.parent[1]["payload"]["arguments"])
                args[mutation] = "unexpected"
                self.parent[1]["payload"]["arguments"] = json.dumps(args)
            else:
                self.child[7]["payload"]["output"][1]["text"] = "truncated"
            self.persist()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.score()

    def test_inline_encrypted_spawn_is_not_accepted_without_verified_file(self) -> None:
        self.make_transcripts(encrypted=True)
        args = json.loads(self.parent[1]["payload"]["arguments"])
        args["message"] = self.child[5]["payload"]["content"][1]["encrypted_content"]
        self.parent[1]["payload"]["arguments"] = json.dumps(args)
        self.assert_rejected("SPAWN_ARGUMENTS_MISMATCH")

    def test_file_delivery_native_bootstrap_metadata_is_bound_and_positioned(self) -> None:
        self.encrypted_file_delivery()
        world = {"type": "world_state", "payload": {"full": True, "state": {"model": "native-config"}}}
        communication = {"type": "inter_agent_communication_metadata", "payload": {"trigger_turn": True}}
        self.child.insert(4, world)
        self.child.insert(6, communication)
        self.persist()
        receipt = self.score()
        self.assertEqual(receipt["result"], "passed")
        original = copy.deepcopy(self.child)
        self.child[4]["payload"]["state"]["model"] = "changed native-config"
        self.persist()
        self.assertNotEqual(receipt["native_evidence"]["bootstrap_context_sha256"],
                            self.score()["native_evidence"]["bootstrap_context_sha256"])
        for row in (world, communication):
            self.child = copy.deepcopy(original)
            self.child.insert(-1, copy.deepcopy(row))
            self.persist()
            with self.assertRaisesRegex(ValueError, "FILE_BOOTSTRAP_METADATA_INVALID"):
                self.score()

    def score(self) -> dict:
        return harness.score(self.root, self.workspace, self.binding_id, self.run_id,
                             self.parent_path, self.child_path)

    def native_host_files(self) -> None:
        """Native-shaped local fixture, never evidence of real provider execution."""
        parent_id, child_id, turn_id = (str(uuid.uuid4()) for _ in range(3))
        old_child = self.child[0]["payload"]["id"]
        old_turn = self.child[1]["payload"]["turn_id"]
        self.parent = json.loads(json.dumps(self.parent).replace('"parent"', json.dumps(parent_id)))
        self.child = json.loads(json.dumps(self.child).replace('"parent"', json.dumps(parent_id))
                                .replace(old_child, child_id).replace(old_turn, turn_id))
        for records in (self.parent, self.child):
            records[0]["payload"].update(cli_version="0.120.0", originator="Codex Desktop", model_provider="openai")
        self.host_home = self.base / "host"
        folder = self.host_home / "sessions/2026/09/29"
        folder.mkdir(parents=True, exist_ok=True)
        self.parent_path = folder / ("rollout-2026-09-29T15-00-00-" + parent_id + ".jsonl")
        self.child_path = folder / ("rollout-2026-09-29T15-00-00-" + child_id + ".jsonl")
        self.native_transcripts[self.run_id] = (self.parent_path, self.child_path)
        self.persist()

    def test_host_selection_requires_native_files_and_preserves_lower_assurance(self) -> None:
        self.native_host_files()
        with mock.patch.dict("os.environ", {"CODEX_HOME": str(self.host_home)}):
            receipt = harness.score_host_selected(self.root, self.workspace, self.binding_id,
                                                  self.run_id, self.parent_path, self.child_path)
        self.assertEqual(receipt["identity_assurance"], "host_selected")
        self.assertTrue(receipt["promotion_eligible"])
        self.assertFalse(receipt["provider_authenticity_verified"])
        self.assertNotIn("provider_attested_model_id", receipt)
        derived = self.score()
        self.assertEqual(harness.host_selected_receipt(derived, receipt["host_selection"]), receipt)

    def test_host_selection_rejects_synthetic_and_unverified_files(self) -> None:
        with self.assertRaisesRegex(ValueError, "HOST_"):
            harness.score_host_selected(self.root, self.workspace, self.binding_id,
                                        self.run_id, self.parent_path, self.child_path)
        self.native_host_files()
        with mock.patch.dict("os.environ", {"CODEX_HOME": str(self.base / "other-host")}):
            with self.assertRaisesRegex(ValueError, "HOST_"):
                harness.score_host_selected(self.root, self.workspace, self.binding_id,
                                            self.run_id, self.parent_path, self.child_path)

    def test_host_selection_accepts_interactive_codex_cli_origin(self) -> None:
        self.native_host_files()
        self.child[0]["payload"].update(originator="codex-tui", cli_version="0.159.3")
        self.persist()
        with mock.patch.dict("os.environ", {"CODEX_HOME": str(self.host_home)}):
            receipt = harness.score_host_selected(self.root, self.workspace, self.binding_id,
                                                  self.run_id, self.parent_path, self.child_path)
        self.assertEqual(receipt["native_evidence"]["client_originator"], "codex-tui")
        self.assertEqual(receipt["identity_assurance"], "host_selected")
        self.assertTrue(receipt["promotion_eligible"])
        self.assertFalse(receipt["provider_authenticity_verified"])

    def test_host_selection_cannot_upgrade_forged_or_failed_evidence(self) -> None:
        self.native_host_files()
        with mock.patch.dict("os.environ", {"CODEX_HOME": str(self.host_home)}):
            receipt = harness.score_host_selected(self.root, self.workspace, self.binding_id,
                                                  self.run_id, self.parent_path, self.child_path)
        source = receipt["host_selection"]
        base = self.score()
        for field, value in (("child_transcript_sha256", "0" * 64), ("source", "synthetic"),
                              ("parent_rollout", "../rollout.jsonl")):
            with self.subTest(field=field):
                forged = {**source, field: value}
                with self.assertRaisesRegex(ValueError, "HOST_"):
                    harness.host_selected_receipt(base, forged)
        base["result"] = "failed"
        self.assertFalse(harness.host_selected_receipt(base, source)["promotion_eligible"])
        base["native_evidence"]["client_originator"] = "Synthetic collector test"
        with self.assertRaisesRegex(ValueError, "HOST_CLIENT_INVALID"):
            harness.host_selected_receipt(base, source)

    def test_host_collection_verifies_retained_snapshot_against_append_only_source(self) -> None:
        self.native_host_files()
        parent_snapshot = self.base / "retained-parent.jsonl"
        child_snapshot = self.base / "retained-child.jsonl"
        shutil.copyfile(self.parent_path, parent_snapshot)
        shutil.copyfile(self.child_path, child_snapshot)
        with self.parent_path.open("ab") as stream:
            stream.write(harness.canonical({"type": "event_msg", "payload": {"type": "token_count"}}) + b"\n")
        with mock.patch.dict("os.environ", {"CODEX_HOME": str(self.host_home)}):
            result = harness.score_host_selected(self.root, self.workspace, self.binding_id,
                                                 self.run_id, parent_snapshot, child_snapshot)
            self.assertTrue(result["promotion_eligible"])
            self.child_path.write_bytes(b'{"not":"the retained source"}\n')
            with self.assertRaisesRegex(ValueError, "HOST_SOURCE_MISMATCH"):
                harness.score_host_selected(self.root, self.workspace, self.binding_id,
                                            self.run_id, parent_snapshot, child_snapshot)

    def pair(self, receipts: list[dict]) -> dict:
        return harness.validate_pair(receipts, root=self.root, workspace=self.workspace,
                                     native_transcripts=self.native_transcripts)

    def assert_rejected(self, code: str) -> None:
        self.persist()
        with self.assertRaisesRegex(ValueError, "CODEX_QUALIFICATION_" + code):
            self.score()

    def prepare_reserve(self) -> dict:
        registry = harness.decode((self.root / harness.REGISTRY).read_bytes())
        primary = next(item for item in registry["bindings"] if item["binding_id"] == self.binding_id)
        reserve = copy.deepcopy(primary)
        reserve.update(binding_id="codex-v3-ultimate-reserve", model_id="synthetic-distinct-reserve-model",
                       selection={"role": "reserve", "priority": 1, "fallback_for": [self.binding_id]})
        reserve["reasoning"]["default_effort"] = "high"
        reserve["binding_sha256"] = harness.sha(harness.canonical({k: v for k, v in reserve.items() if k != "binding_sha256"}))
        registry["bindings"].append(reserve)
        registry["registry_sha256"] = harness.sha(harness.canonical({k: v for k, v in registry.items() if k != "registry_sha256"}))
        (self.root / harness.REGISTRY).write_bytes(harness.canonical(registry))
        self.workspace = self.base / "prepared-reserve"
        self.manifest = harness.prepare(self.root, self.workspace)
        self.binding_id = reserve["binding_id"]
        self.make_transcripts()
        return reserve

    def test_distinct_model_reserve_freezes_scores_and_pairs_exact_configuration(self) -> None:
        reserve = self.prepare_reserve()
        self.assertEqual(len(self.manifest["dispatches"]), 10)
        self.assertEqual(len({item["spawn_arguments"]["task_name"] for item in self.manifest["dispatches"]}), 10)
        receipts = []
        for run_id in sorted(harness.RUN_IDS):
            self.make_transcripts(run_id)
            receipt = self.score()
            self.assertEqual(receipt["binding_id"], reserve["binding_id"])
            self.assertEqual(receipt["binding_sha256"], reserve["binding_sha256"])
            for field in ("requested_model_id", "configured_model_id"):
                self.assertEqual(receipt[field], reserve["model_id"])
            for field in ("requested_effort", "configured_effort"):
                self.assertEqual(receipt[field], "high")
            receipts.append(receipt)
        pair = self.pair(receipts)
        self.assertEqual(pair["result"], "passed")
        self.assertEqual(pair["identity_assurance"], "client_configuration")
        self.assertEqual(pair["evidence_assurance"], "structural_only")
        self.assertFalse(pair["promotion_eligible"])
        self.assertFalse(pair["provider_authenticity_verified"])
        self.assertFalse(pair["full_context_blindness_verified"])

    def test_reserve_rejects_primary_model_or_effort(self) -> None:
        self.prepare_reserve()
        primary = next(item for item in self.manifest["bindings"] if item["binding_id"] == "codex-v3-ultimate")
        for field, value in (("model", primary["model_id"]), ("effort", primary["reasoning"]["default_effort"])):
            with self.subTest(field=field):
                self.make_transcripts()
                self.child[4]["payload"][field] = value
                self.assert_rejected("CLIENT_CONFIGURATION_MISMATCH")

    def test_unregistered_or_other_provider_binding_cannot_score_or_pair(self) -> None:
        self.prepare_reserve()
        first = self.score()
        self.make_transcripts("native-forward-run-2")
        second = self.score()
        for binding_id in ("codex-v3-ultimate-unregistered", "claude-code-v3-ultimate"):
            with self.subTest(binding_id=binding_id):
                with self.assertRaisesRegex(ValueError, "RUN_SELECTION_INVALID"):
                    harness.score(self.root, self.workspace, binding_id, self.run_id,
                                  self.parent_path, self.child_path)
                forged = copy.deepcopy([first, second])
                for receipt in forged:
                    receipt["binding_id"] = binding_id
                with self.assertRaisesRegex(ValueError, "PAIR_BINDING_INVALID"):
                    self.pair(forged)

    def test_manifest_cannot_add_an_unregistered_reserve(self) -> None:
        reserve = self.prepare_reserve()
        reserve["binding_id"] = "codex-v3-injected-reserve"
        self.manifest["bindings"].append(reserve)
        (self.workspace / harness.MANIFEST_NAME).write_bytes(harness.canonical(self.manifest))
        with self.assertRaisesRegex(ValueError, "FROZEN_CANDIDATE_CHANGED"):
            self.score()

    def test_reserve_binding_hash_and_candidate_status_are_required(self) -> None:
        self.prepare_reserve()
        path = self.root / harness.REGISTRY
        original = harness.decode(path.read_bytes())
        for field, value, code in (("binding_sha256", "0" * 64, "BINDING_HASH_MISMATCH"),
                                   ("status", "qualified", "BINDING_NOT_CANDIDATE")):
            with self.subTest(field=field):
                registry = copy.deepcopy(original)
                reserve = next(item for item in registry["bindings"] if item["binding_id"] == self.binding_id)
                reserve[field] = value
                registry["registry_sha256"] = harness.sha(harness.canonical({k: v for k, v in registry.items() if k != "registry_sha256"}))
                path.write_bytes(harness.canonical(registry))
                with self.assertRaisesRegex(ValueError, code):
                    harness.candidate(self.root)

    def test_registry_rejects_duplicate_malformed_or_empty_codex_binding_set(self) -> None:
        self.prepare_reserve()
        path = self.root / harness.REGISTRY
        original = harness.decode(path.read_bytes())
        for binding_id in ("codex-v3-ultimate", "../reserve", "", None):
            with self.subTest(binding_id=binding_id):
                registry = copy.deepcopy(original)
                reserve = registry["bindings"][-1]
                reserve["binding_id"] = binding_id
                reserve["binding_sha256"] = harness.sha(harness.canonical({k: v for k, v in reserve.items() if k != "binding_sha256"}))
                registry["registry_sha256"] = harness.sha(harness.canonical({k: v for k, v in registry.items() if k != "registry_sha256"}))
                path.write_bytes(harness.canonical(registry))
                with self.assertRaisesRegex(ValueError, "BINDINGS_INVALID"):
                    harness.candidate(self.root)
        registry = copy.deepcopy(original)
        registry["bindings"] = [item for item in registry["bindings"] if item["provider"] != "codex"]
        registry["registry_sha256"] = harness.sha(harness.canonical({k: v for k, v in registry.items() if k != "registry_sha256"}))
        path.write_bytes(harness.canonical(registry))
        with self.assertRaisesRegex(ValueError, "BINDINGS_INVALID"):
            harness.candidate(self.root)

    def test_registry_ids_remain_distinct_in_dispatch_names(self) -> None:
        self.prepare_reserve()
        path = self.root / harness.REGISTRY
        registry = harness.decode(path.read_bytes())
        reserve = registry["bindings"][-1]
        reserve["binding_id"] = "ultimate"
        reserve["binding_sha256"] = harness.sha(harness.canonical({k: v for k, v in reserve.items() if k != "binding_sha256"}))
        registry["registry_sha256"] = harness.sha(harness.canonical({k: v for k, v in registry.items() if k != "registry_sha256"}))
        path.write_bytes(harness.canonical(registry))
        manifest = harness.prepare(self.root, self.base / "prepared-distinct-ids")
        self.assertEqual(len({item["spawn_arguments"]["task_name"] for item in manifest["dispatches"]}), 10)

    def test_dispatch_names_support_native_syntax_for_mixed_case_registry_ids(self) -> None:
        self.prepare_reserve()
        path = self.root / harness.REGISTRY
        registry = harness.decode(path.read_bytes())
        reserve = registry["bindings"][-1]
        reserve["binding_id"] = "Codex.Reserve-ULTIMATE"
        reserve["binding_sha256"] = harness.sha(harness.canonical({k: v for k, v in reserve.items() if k != "binding_sha256"}))
        registry["registry_sha256"] = harness.sha(harness.canonical({k: v for k, v in registry.items() if k != "registry_sha256"}))
        path.write_bytes(harness.canonical(registry))
        self.workspace = self.base / "prepared-native-syntax"
        self.manifest = harness.prepare(self.root, self.workspace)
        self.binding_id = reserve["binding_id"]
        for dispatch in self.manifest["dispatches"]:
            self.assertRegex(dispatch["spawn_arguments"]["task_name"], r"^[a-z0-9_]+$")
        self.make_transcripts()
        self.assertEqual(self.score()["result"], "passed")

    def test_prepare_eight_exact_fresh_dispatches_and_oracle_free_prompt(self) -> None:
        self.assertEqual(len(self.manifest["dispatches"]), 8)
        self.assertEqual(len({item["spawn_arguments"]["task_name"] for item in self.manifest["dispatches"]}), 8)
        for dispatch in self.manifest["dispatches"]:
            self.assertRegex(dispatch["spawn_arguments"]["task_name"], r"^[a-z0-9_]+$")
        self.assertTrue(all(item["spawn_arguments"]["fork_turns"] == "none" for item in self.manifest["dispatches"]))
        prompt = (self.workspace / harness.PROMPT_NAME).read_text()
        self.assertNotIn("DO_NOT_EXPOSE_ORACLE", prompt)
        public = harness.decode(prompt[len(harness.INSTRUCTIONS):])
        self.assertEqual({item["path"] for item in public["candidate_files"]}, set(harness.V3_CANDIDATE_FILES))
        self.assertEqual(len(public["requests"]), 12)
        self.assertTrue(all(set(item) == {"scenario_id", "request"} for item in public["requests"]))
        self.assertFalse(self.manifest["dispatch_performed"])
        self.assertFalse(self.manifest["promotion_eligible"])

    def test_prepare_requires_collector_and_test_in_inventory(self) -> None:
        self.inventory["paths"].remove("scripts/CodexQualificationHarness.py")
        self.inventory_path.write_bytes(harness.canonical(self.inventory))
        with self.assertRaisesRegex(ValueError, "HARNESS_OR_INPUT_NOT_IN_INVENTORY"):
            harness.prepare(self.root, self.base / "second")

    def test_prepare_never_overwrites(self) -> None:
        with self.assertRaisesRegex(ValueError, "OUTPUT_ALREADY_EXISTS"):
            harness.prepare(self.root, self.workspace)

    def test_native_observation_is_not_provider_attestation(self) -> None:
        receipt = self.score()
        self.assertEqual(receipt["result"], "passed")
        self.assertEqual(receipt["identity_assurance"], "client_configuration")
        self.assertFalse(receipt["promotion_eligible"])
        self.assertFalse(receipt["provider_authenticity_verified"])
        self.assertFalse(receipt["full_context_blindness_verified"])
        self.assertTrue(receipt["native_evidence"]["child_prompt_plaintext_verified"])
        serialized = json.dumps(receipt)
        self.assertNotIn("provider_attested", serialized)
        self.assertNotIn("actual_model", serialized)
        self.assertNotIn("Private synthetic reasoning", serialized)
        self.assertNotIn("Synthetic platform instructions", serialized)

    def test_opaque_native_task_payload_is_reported_honestly(self) -> None:
        self.make_transcripts(encrypted=True)
        self.assertFalse(self.score()["native_evidence"]["child_prompt_plaintext_verified"])

    def test_bootstrap_answer_key_does_not_claim_full_context_blindness(self) -> None:
        self.child[3]["payload"]["content"][0]["text"] = "Inherited answer key: " + json.dumps(self.response)
        self.persist()
        receipt = self.score()
        self.assertTrue(receipt["blind_prompt"])
        self.assertFalse(receipt["full_context_blindness_verified"])
        self.assertFalse(receipt["promotion_eligible"])

    def test_candidate_drift_invalidates_run(self) -> None:
        path = self.root / harness.V3_CANDIDATE_FILES[0]
        path.write_bytes(path.read_bytes() + b"\nchanged: true\n")
        with self.assertRaisesRegex(ValueError, "FROZEN_CANDIDATE_CHANGED"):
            self.score()

    def test_candidate_change_during_transcript_read_invalidates_run(self) -> None:
        original_read = harness.read_regular
        policy = self.root / harness.V3_CANDIDATE_FILES[0]
        changed = False
        def change_after_read(path: Path) -> bytes:
            nonlocal changed
            raw = original_read(path)
            if path == self.child_path and not changed:
                changed = True
                policy.write_bytes(policy.read_bytes() + b"\nchanged_during_score: true\n")
            return raw
        with mock.patch.object(harness, "read_regular", side_effect=change_after_read):
            with self.assertRaisesRegex(ValueError, "FROZEN_CANDIDATE_CHANGED"):
                self.score()
        self.assertTrue(changed)

    def test_prompt_drift_invalidates_run(self) -> None:
        (self.workspace / harness.PROMPT_NAME).write_text("Altered prompt")
        with self.assertRaisesRegex(ValueError, "PROMPT_CHANGED"):
            self.score()

    def test_missing_or_mismatched_model_effort_is_rejected(self) -> None:
        for field, value in (("model", "other"), ("effort", "low"), ("effort", None)):
            with self.subTest(field=field, value=value):
                self.make_transcripts()
                self.child[4]["payload"][field] = value
                self.assert_rejected("CLIENT_CONFIGURATION_MISMATCH")

    def test_forked_history_or_wrong_prompt_is_rejected(self) -> None:
        for field, value in (("fork_turns", "all"), ("message", "oracle: injected")):
            with self.subTest(field=field):
                self.make_transcripts()
                args = json.loads(self.parent[1]["payload"]["arguments"])
                args[field] = value
                self.parent[1]["payload"]["arguments"] = json.dumps(args)
                self.assert_rejected("SPAWN_ARGUMENTS_MISMATCH")

    def test_parent_and_returned_path_must_match_child(self) -> None:
        self.child[0]["payload"]["source"]["subagent"]["thread_spawn"]["parent_thread_id"] = "unrelated"
        self.assert_rejected("PARENT_LINK_MISMATCH")
        self.make_transcripts()
        self.parent[2]["payload"]["output"] = json.dumps({"task_name": "/root/wrong"})
        self.assert_rejected("SPAWN_RESULT_INVALID")

    def test_no_extra_turns_or_task_messages(self) -> None:
        for index, code in ((1, "CHILD_NOT_ONE_TURN"), (4, "CHILD_NOT_ONE_TURN"), (5, "TASK_DELIVERY_INVALID")):
            with self.subTest(index=index):
                self.make_transcripts()
                self.child.insert(-1, copy.deepcopy(self.child[index]))
                self.assert_rejected(code)

    def test_no_tools_or_compaction(self) -> None:
        for row, code in (
            ({"type": "response_item", "payload": {"type": "function_call", "name": "spawn_agent"}}, "CHILD_TOOL_OR_ITEM_UNSUPPORTED"),
            ({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec"}}, "CHILD_TOOL_OR_ITEM_UNSUPPORTED"),
            ({"type": "compacted", "payload": {}}, "CHILD_RECORD_UNSUPPORTED"),
            ({"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "CommandExecution"}}}, "CHILD_TOOL_OR_EVENT_UNSUPPORTED"),
        ):
            with self.subTest(code=code):
                self.make_transcripts()
                self.child.insert(-1, row)
                self.assert_rejected(code)

    def test_prior_conversation_or_post_task_user_message_is_rejected(self) -> None:
        self.child.insert(5, {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "final_answer", "content": [{"type": "output_text", "text": "Prior answer"}]}})
        self.assert_rejected("UNEXPECTED_ASSISTANT_MESSAGE")
        self.make_transcripts()
        self.child.insert(-1, copy.deepcopy(self.child[3]))
        self.assert_rejected("CHILD_CONTEXT_NOT_FRESH")

    def test_completion_and_final_turn_must_match(self) -> None:
        self.child.pop()
        self.assert_rejected("CHILD_NOT_COMPLETED")
        self.make_transcripts()
        self.child[7]["payload"]["internal_chat_message_metadata_passthrough"]["turn_id"] = "other"
        self.assert_rejected("FINAL_TURN_MISMATCH")

    def test_plaintext_delivery_must_match_dispatch(self) -> None:
        self.child[5]["payload"]["content"][0]["text"] += "Extra instruction"
        self.assert_rejected("TASK_PROMPT_MISMATCH")

    def test_strict_json_and_exact_scenario_set(self) -> None:
        cases = ["```json\n" + json.dumps(self.response) + "\n```", '{"schema_version":"x","schema_version":"y"}', "NaN"]
        duplicate = copy.deepcopy(self.response)
        duplicate["results"].append(duplicate["results"][0])
        cases.append(json.dumps(duplicate))
        duplicate = copy.deepcopy(self.response)
        duplicate["results"][0]["claims"].append(duplicate["results"][0]["claims"][0])
        cases.append(json.dumps(duplicate))
        missing = copy.deepcopy(self.response)
        missing["results"].pop()
        cases.append(json.dumps(missing))
        for case in cases:
            with self.subTest(case=case[:40]), self.assertRaises(ValueError):
                harness.score_response(case)

    def test_valid_but_wrong_answers_produce_failed_receipt(self) -> None:
        self.response["results"][0]["claims"].pop()
        self.child[7]["payload"]["content"][0]["text"] = json.dumps(self.response)
        self.persist()
        receipt = self.score()
        self.assertEqual(receipt["result"], "failed")
        self.assertTrue(receipt["scenario_results"][0]["missing_claims"])

    def test_ce_authority_extra_is_valid_but_routine_authority_remains_required(self) -> None:
        response = copy.deepcopy(self.response)
        by_id = {item["scenario_id"]: item for item in response["results"]}
        by_id["GFT08"]["claims"].append("authorization_preserved")
        _, scores = harness.score_response(json.dumps(response))
        self.assertEqual({row["scenario_id"]: row["status"] for row in scores}["GFT08"], "passed")
        by_id["GFT09"]["claims"].remove("authorization_preserved")
        _, scores = harness.score_response(json.dumps(response))
        routine = next(row for row in scores if row["scenario_id"] == "GFT09")
        self.assertEqual(routine["status"], "failed")
        self.assertEqual(routine["missing_claims"], ["authorization_preserved"])
        by_id["GFT08"]["claims"].append("fault_evidence")
        _, scores = harness.score_response(json.dumps(response))
        ce = next(row for row in scores if row["scenario_id"] == "GFT08")
        self.assertEqual(ce["disallowed_additional_claims"], ["fault_evidence"])

    def test_pair_two_fresh_sessions_same_parent(self) -> None:
        first = self.score()
        self.make_transcripts("native-forward-run-2")
        second = self.score()
        pair = self.pair([first, second])
        self.assertEqual(pair["result"], "passed")
        self.assertFalse(pair["promotion_eligible"])
        self.assertEqual(len(pair["session_ids"]), 2)

    def test_pair_rederives_failed_native_answers_instead_of_trusting_receipts(self) -> None:
        forged = []
        for run_id in sorted(harness.RUN_IDS):
            self.make_transcripts(run_id)
            passing_response = copy.deepcopy(self.response)
            self.response["results"][0]["claims"].pop()
            self.child[7]["payload"]["content"][0]["text"] = json.dumps(self.response)
            self.persist()
            receipt = self.score()
            self.assertEqual(receipt["result"], "failed")
            receipt["response"] = passing_response
            receipt["response_sha256"] = harness.sha(harness.canonical(passing_response))
            receipt["native_response_text_sha256"] = harness.sha(json.dumps(passing_response).encode("utf-8"))
            _, receipt["scenario_results"] = harness.score_response(json.dumps(passing_response))
            receipt["result"] = "passed"
            forged.append(receipt)
        with self.assertRaisesRegex(ValueError, "PAIR_NATIVE_RECEIPT_MISMATCH"):
            self.pair(forged)

    def test_pair_requires_both_retained_native_snapshots(self) -> None:
        first = self.score()
        self.make_transcripts("native-forward-run-2")
        second = self.score()
        with self.assertRaisesRegex(ValueError, "PAIR_NATIVE_TRANSCRIPTS_REQUIRED"):
            harness.validate_pair([first, second], root=self.root, workspace=self.workspace,
                                  native_transcripts={})

    def test_pair_rejects_changed_native_bytes(self) -> None:
        first = self.score()
        self.make_transcripts("native-forward-run-2")
        second = self.score()
        self.child[2]["payload"]["content"][0]["text"] = "Changed bootstrap"
        self.persist()
        with self.assertRaisesRegex(ValueError, "PAIR_NATIVE_RECEIPT_MISMATCH"):
            self.pair([first, second])

    def test_pair_rejects_reuse_drift_and_laundered_attestation(self) -> None:
        first = self.score()
        self.make_transcripts("native-forward-run-2")
        second = self.score()
        mutations = [lambda item: item.update(session_id=first["session_id"]),
                     lambda item: item.update(candidate_sha256="0" * 64),
                     lambda item: item.update(provider_attested_model_id=item["configured_model_id"]),
                     lambda item: item.update(promotion_eligible=True),
                     lambda item: item["response"]["results"][0]["claims"].pop()]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                changed = copy.deepcopy(second)
                mutate(changed)
                with self.assertRaises(ValueError):
                    self.pair([first, changed])

    def test_pair_checks_frozen_root_not_only_receipt_agreement(self) -> None:
        first = self.score()
        self.make_transcripts("native-forward-run-2")
        second = self.score()
        first["candidate_sha256"] = second["candidate_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "PAIR_FROZEN_BINDING_MISMATCH"):
            self.pair([first, second])

    def test_timestamp_requires_offset(self) -> None:
        self.child[-1]["timestamp"] = "2026-09-29T15:00:00"
        self.assert_rejected("TIMESTAMP_OFFSET_MISSING")

    def test_reasoning_outside_turn_is_rejected(self) -> None:
        self.child.insert(4, copy.deepcopy(self.child[6]))
        self.assert_rejected("REASONING_OUTSIDE_TASK")

    def test_evidence_save_is_non_overwriting(self) -> None:
        target = self.base / "receipt.json"
        harness.save_new(target, self.score())
        saved = target.read_bytes()
        with self.assertRaises(FileExistsError):
            harness.save_new(target, {"changed": True})
        self.assertEqual(target.read_bytes(), saved)

    def test_ancestor_symlink_swap_during_read_is_rejected(self) -> None:
        source_dir = self.base / "regular-source"
        source_dir.mkdir()
        source = source_dir / "data.jsonl"
        source.write_bytes(b"native-data\n")
        retained = self.base / "retained-source"
        original_read = Path.read_bytes
        def swap_after_read(path: Path) -> bytes:
            raw = original_read(path)
            if path == source:
                source_dir.rename(retained)
                source_dir.symlink_to(retained, target_is_directory=True)
            return raw
        with mock.patch.object(Path, "read_bytes", side_effect=swap_after_read, autospec=True):
            with self.assertRaisesRegex(ValueError, "SYMLINK_UNSUPPORTED"):
                harness.read_regular(source)

    def test_partial_log_and_duplicate_json_keys_rejected(self) -> None:
        self.child_path.write_bytes(self.child_path.read_bytes().rstrip(b"\n"))
        with self.assertRaisesRegex(ValueError, "ROLLOUT_INCOMPLETE"):
            self.score()
        with self.assertRaisesRegex(ValueError, "DUPLICATE_JSON_KEY"):
            harness.rows(b'{"type":"x","type":"y","payload":{}}\n')


if __name__ == "__main__":
    unittest.main()
