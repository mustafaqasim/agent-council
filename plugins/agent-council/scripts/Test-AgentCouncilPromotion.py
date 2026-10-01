#!/usr/bin/env python3
"""Synthetic integrity/parser tests. These artifacts are never native evidence."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import AgentCouncilPromotion as promotion
from ClaudeQualificationHarness import V3_CANDIDATE_FILES, EXPECTED_CLAIMS, current_release_binding
import CodexQualificationHarness as codex


def host_fixture(*, delivery_mode: str = "inline", role_protocol: bool = True) -> tuple[dict[str, bytes], dict]:
    spec = importlib.util.spec_from_file_location("codex_test_fixtures", Path(__file__).with_name("Test-CodexQualificationHarness.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    native = module.QualificationTests()
    native.setUp()
    try:
        if role_protocol:
            native.workspace = native.base / "prepared-role"
            native.manifest = codex.prepare(native.root, native.workspace, delivery_mode=delivery_mode,
                                             binding_id=native.binding_id)
        elif delivery_mode == "file":
            native.file_delivery()
        binding = next(row for row in promotion.registry((native.root / promotion.REGISTRY_PATH).read_bytes())["bindings"]
                       if row["binding_id"] == native.binding_id)
        def transcripts(run_id="native-forward-run-1"):
            (native.file_delivery if delivery_mode == "file" else native.make_transcripts)(run_id)
            if role_protocol:
                response = {"schema_version": promotion.protocol.RESPONSE, "results": [
                    {"scenario_id": case["scenario_id"], "output": case["expected_output"], "actions": []}
                    for case in promotion.protocol.suite_cases(binding)]}
                for item in native.child:
                    if item.get("payload", {}).get("role") == "assistant":
                        item["payload"]["content"] = [{"type": "output_text", "text": json.dumps(response)}]
                native.persist()
        files = {path.relative_to(native.root).as_posix(): path.read_bytes()
                 for path in native.root.rglob("*") if path.is_file()}
        archived = files[promotion.REGISTRY_PATH]
        files[promotion.ARCHIVE_PATH] = archived
        candidate_release = promotion.release_binding(files.__getitem__)
        protocols = {native.binding_id: promotion.protocol.protocol_binding(binding)} if role_protocol else None
        files[promotion.REGISTRY_PATH] = promotion.promote_registry(archived, [native.binding_id],
                                                                   qualification_protocols=protocols)
        def artifact(name, raw):
            path = "standards/model-qualifications/host/" + name
            files[path] = raw
            return {"path": path, "sha256": promotion.sha256(raw)}
        row = {"binding_id": native.binding_id, "runs": [], "host_selection": {
            "preparation": artifact("preparation.json", (native.workspace / codex.MANIFEST_NAME).read_bytes()),
            "prompt": artifact("prompt.txt", (native.workspace / codex.PROMPT_NAME).read_bytes())}}
        if role_protocol:
            row["qualification_protocol"] = protocols[native.binding_id]
        receipts = []
        for run_id in sorted(codex.RUN_IDS):
            transcripts(run_id)
            native.native_host_files()
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(native.host_home)}):
                receipt = codex.score_host_selected(native.root, native.workspace, native.binding_id,
                                                    run_id, native.parent_path, native.child_path)
            receipts.append(receipt)
            row["runs"].append({"receipt": artifact(run_id + ".json", encode(receipt)),
                                "transcript": artifact(run_id + "-child.jsonl", native.child_path.read_bytes()),
                                "parent_transcript": artifact(run_id + "-parent.jsonl", native.parent_path.read_bytes())})
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(native.host_home)}):
            pair = codex.validate_host_pair(receipts, root=native.root, workspace=native.workspace,
                                            native_transcripts=native.native_transcripts)
        row["pair"] = artifact("pair.json", encode(pair))
        native.workspace = native.base / "prepared-probe"
        native.manifest = codex.prepare(native.root, native.workspace, delivery_mode=delivery_mode,
                                        binding_id=native.binding_id if role_protocol else None)
        transcripts()
        native.native_host_files()
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(native.host_home)}):
            probe = codex.score_host_selected(native.root, native.workspace, native.binding_id,
                                              native.run_id, native.parent_path, native.child_path)
        row["probe"] = artifact("probe.json", encode(probe))
        row["probe_files"] = {"release_binding": artifact("release.json", encode(candidate_release)),
                              "preparation": artifact("probe-preparation.json", (native.workspace / codex.MANIFEST_NAME).read_bytes()),
                              "prompt": artifact("probe-prompt.txt", (native.workspace / codex.PROMPT_NAME).read_bytes()),
                              "parent_transcript": artifact("probe-parent.jsonl", native.parent_path.read_bytes()),
                              "child_transcript": artifact("probe-child.jsonl", native.child_path.read_bytes())}
        proof = {"schema_version": promotion.ROLE_SCHEMA if role_protocol else promotion.SCHEMA, "evidence_assurance": "structural_only",
                 "candidate_registry": {"path": promotion.ARCHIVE_PATH, "sha256": promotion.sha256(archived)},
                 "candidate_release_binding": candidate_release,
                 "promoted_release_binding": promotion.release_binding(files.__getitem__),
                 "binding_evidence": [row]}
        if role_protocol:
            proof["qualification_protocol_version"] = promotion.ROLE_PROTOCOL
        files[promotion.PROOF_PATH] = encode(proof)
        return files, proof
    finally:
        native.tearDown()


def encode(value: object) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def fixture(candidate_root: Path = promotion.ROOT, *, binding_ids: list[str] | None = None,
            registry_value: dict | None = None, role_protocol: bool = False,
            include_protocol_package: bool = False) -> tuple[dict[str, bytes], dict]:
    """Build all eight synthetic binding artifacts, never persist to the package."""
    candidate = promotion.decode((promotion.ROOT / promotion.REGISTRY_PATH).read_bytes())
    for binding in candidate["bindings"]:
        binding["status"] = "candidate"
        binding.pop("qualified_roles", None)
        binding["binding_sha256"] = promotion.sha256(promotion.canonical({k: v for k, v in binding.items() if k != "binding_sha256"}))
    for state in candidate["provider_states"].values():
        state["council_status"] = "fail_closed_until_qualified"
    candidate["registry_sha256"] = promotion.sha256(promotion.canonical({k: v for k, v in candidate.items() if k != "registry_sha256"}))
    if registry_value is not None:
        candidate = copy.deepcopy(registry_value)
    # Noncanonical candidate whitespace must survive as exact archive bytes.
    archived = b" \n" + encode(candidate)
    files = {path: (promotion.ROOT / path).read_bytes() for path in V3_CANDIDATE_FILES}
    if role_protocol or include_protocol_package:
        files.update({path: (promotion.ROOT / path).read_bytes() for path in promotion.protocol.PROTOCOL_FILES})
    files.update({"agents/council-" + role + ".md": (promotion.ROOT / ("agents/council-" + role + ".md")).read_bytes()
                  for role in promotion.TIERS})
    for binding in candidate["bindings"]:
        if binding["provider"] == "claude_code" and binding["binding_id"] not in promotion.BINDINGS:
            files["agents/" + binding["binding_id"] + ".md"] = (
                "---\nname: " + binding["binding_id"] + "\nmodel: " + binding["model_id"] +
                "\n---\nSynthetic binding-scoped Agent definition.\n").encode("utf-8")
    files["evals/fixture.yaml"] = b"synthetic: true\n"
    files["scripts/behavior.py"] = b"behavior = 'current'\n"
    protocols = {binding["binding_id"]: promotion.protocol.protocol_binding(binding)
                 for binding in candidate["bindings"] if binding["status"] == "candidate" and
                 (binding_ids is None or binding["binding_id"] in binding_ids)} if role_protocol else None
    files[promotion.REGISTRY_PATH] = promotion.promote_registry(archived, binding_ids,
                                                               qualification_protocols=protocols)
    files[promotion.INVENTORY_PATH] = encode({"schema_version": "agent-council.behavioral-inventory/v1",
                                             "identity_version": "current/v1", "paths": sorted(files)})
    candidate_release = promotion.release_binding(files.__getitem__, archived)
    promoted_release = promotion.release_binding(files.__getitem__)
    policy_sha = promotion.named_digest(list(V3_CANDIDATE_FILES),
                                       lambda path: archived if path == promotion.REGISTRY_PATH else files[path])
    def artifact(path: str, value: object, *, raw: bool = False) -> dict:
        data = value if raw else encode(value)
        files[path] = data
        return {"path": path, "sha256": promotion.sha256(data)}
    archive_ref = artifact(promotion.ARCHIVE_PATH, archived, raw=True)
    proof = {"schema_version": promotion.ROLE_SCHEMA if role_protocol else promotion.SCHEMA, "evidence_assurance": "structural_only",
             "candidate_registry": archive_ref, "candidate_release_binding": candidate_release,
             "promoted_release_binding": promoted_release, "binding_evidence": []}
    if role_protocol:
        proof["qualification_protocol_version"] = promotion.ROLE_PROTOCOL
    for index, binding in enumerate(candidate["bindings"]):
        binding_id, provider, model = binding["binding_id"], binding["provider"], binding["model_id"]
        if binding["status"] != "candidate" or binding_ids is not None and binding_id not in binding_ids:
            continue
        label = "claude" if provider == "claude_code" else "codex"
        effort = binding["reasoning"]["default_effort"]
        base = "standards/model-qualifications/synthetic/" + binding_id + "/"
        sessions = [f"session-{index}-1", f"session-{index}-2"]
        common = {"binding_id": binding_id, "binding_sha256": binding["binding_sha256"],
                  "registry_sha256": candidate["registry_sha256"], "release_binding": candidate_release}
        qualification = {**common, "registry_version": "v3", "candidate_sha256": policy_sha,
                         "eval_suite_sha256": candidate_release["eval_suite_sha256"]}
        if role_protocol:
            qualification["qualification_protocol"] = protocols[binding_id]
        attestation = {"provider": "codex", "provenance": "native_session_export", "requested_model_id": model,
                       "provider_attested_model_id": model, "requested_effort": effort, "provider_attested_effort": effort}
        pair = {**qualification, "schema_version": f"agent-council.{label}-qualification-pair/v3",
                "result": "passed", "model_id": model, "effort": effort, "session_ids": sessions,
                "run_ids": sorted(promotion.RUN_IDS), "evaluation_bundle_sha256": "b" * 64}
        if provider == "codex":
            pair.update(attestation)
        row = {"binding_id": binding_id, "pair": artifact(base + "pair.json", pair), "runs": []}
        if role_protocol:
            row["qualification_protocol"] = protocols[binding_id]
        for number, session in enumerate(sessions, 1):
            response = {"schema_version": f"agent-council.{label}-native-response/v1", "results": [
                {"scenario_id": scenario, "claims": sorted(claims), "rationale": "Synthetic parser test."}
                for scenario, claims in sorted(EXPECTED_CLAIMS.items())]}
            if role_protocol:
                response = {"schema_version": promotion.protocol.RESPONSE, "results": [
                    {"scenario_id": case["scenario_id"], "output": case["expected_output"], "actions": []}
                    for case in promotion.protocol.suite_cases(binding)]}
            if provider == "codex":
                transcript = [{"type": "provider_attestation", "session_id": session, "model_id": model,
                               "effort": effort, "status": "completed", "council_reentry": "denied"},
                              {"type": "qualification_result", "session_id": session, "response": response}]
            else:
                transcript = [{"type": "assistant", "sessionId": session, "effort": effort,
                               "message": {"model": model, "content": [{"type": "text", "text": json.dumps(response)}]}}]
                if effort is None:
                    transcript[0].pop("effort")
                    transcript[0]["perTurnEffort"] = None
            transcript_ref = artifact(base + f"run-{number}.jsonl", b"".join(promotion.canonical(item) + b"\n" for item in transcript), raw=True)
            receipt = {**qualification, "schema_version": f"agent-council.{label}-qualification-receipt/v3",
                       "result": "passed", "run_id": f"native-forward-run-{number}", "session_id": session,
                       "requested_model_id": model, "actual_model_id": model, "requested_effort": effort,
                       "actual_effort": effort, "clean_context": True, "blind": True,
                       "evaluation_bundle_sha256": pair["evaluation_bundle_sha256"], "transcript_sha256": transcript_ref["sha256"],
                       "scenario_results": [{"scenario_id": scenario, "status": "passed", "missing_claims": [],
                                             "additional_claims": [], "disallowed_additional_claims": []}
                                            for scenario in sorted(EXPECTED_CLAIMS)]}
            if role_protocol:
                receipt["scenario_results"] = promotion.protocol.score_response(response, binding)
            if provider == "codex":
                receipt.update(attestation)
            row["runs"].append({"receipt": artifact(base + f"receipt-{number}.json", receipt), "transcript": transcript_ref})
        parent_session = f"probe-{index}"
        child_session = f"probe-child-{index}" if provider == "codex" else parent_session
        probe = {**common, "schema_version": f"agent-council.{label}-agent-probe/v1", "result": "passed",
                 "model_id": model, "effort": effort, "registry_file_sha256": promotion.sha256(archived),
                 "parent_session_id": parent_session, "child_session_id": child_session}
        if provider == "codex":
            probe.update(attestation)
            parent = [{"type": "native_agent_dispatch", "parent_session_id": parent_session,
                       "child_session_id": child_session, "binding_id": binding_id,
                       "requested_model_id": model, "requested_effort": effort, "status": "completed", "council_reentry": "denied"}]
            child = [{"type": "provider_attestation", "session_id": child_session, "model_id": model,
                      "effort": effort, "status": "completed", "council_reentry": "denied"}]
        else:
            agent = ("council-" + binding_id.removeprefix("claude-code-v3-")
                     if binding_id in promotion.BINDINGS else binding_id)
            probe.update({"agent_definition_sha256": promotion.sha256(files["agents/" + agent + ".md"]),
                          "subagent_type": "agent-council:" + agent, "agent_id": f"agent-{index}",
                          "tool_use_id": f"tool-{index}", "child_assistant_rows": 1, "completion_evidence": "agent_result"})
            probe["loader_root"] = str(candidate_root.resolve())
            parent = [{"type": "assistant", "sessionId": parent_session, "message": {"content": [
                {"type": "tool_use", "id": probe["tool_use_id"], "name": "Agent", "input": {"subagent_type": probe["subagent_type"], "prompt": "Synthetic test."}}]}},
                {"type": "user", "sessionId": parent_session, "message": {"content": [
                    {"type": "tool_result", "tool_use_id": probe["tool_use_id"], "content": "Synthetic completion."}]},
                 "toolUseResult": {"agentId": probe["agent_id"], "resolvedModel": model, "status": "completed"}}]
            child = [{"type": "assistant", "sessionId": child_session, "agentId": probe["agent_id"],
                      "isSidechain": True, "effort": effort, "message": {"model": model, "content": [{"type": "text", "text": "Synthetic test."}]}}]
            if effort is None:
                child[0].pop("effort")
                child[0]["perTurnEffort"] = None
        probe_files = {"release_binding": artifact(base + "frozen-release.json", candidate_release),
                       "parent_transcript": artifact(base + "parent.jsonl", b"".join(promotion.canonical(item) + b"\n" for item in parent), raw=True),
                       "child_transcript": artifact(base + "child.jsonl", b"".join(promotion.canonical(item) + b"\n" for item in child), raw=True)}
        if provider == "claude_code":
            loader = (f"[DEBUG] --plugin-dir {candidate_root.resolve()} is one plugin: .claude-plugin at its top marks it\n"
                      "[DEBUG] Loaded inline plugin from path: agent-council\n"
                      '[DEBUG] Plugin "agent-council" from --plugin-dir overrides installed version\n').encode("utf-8")
            probe_files["loader_debug_log"] = artifact(base + parent_session + ".txt", loader, raw=True)
            probe["loader_debug_log_sha256"] = probe_files["loader_debug_log"]["sha256"]
        probe.update({"release_binding_file_sha256": probe_files["release_binding"]["sha256"],
                      "parent_transcript_sha256": probe_files["parent_transcript"]["sha256"],
                      "child_transcript_sha256": probe_files["child_transcript"]["sha256"]})
        row.update({"probe": artifact(base + "probe.json", probe), "probe_files": probe_files})
        proof["binding_evidence"].append(row)
    files[promotion.PROOF_PATH] = encode(proof)
    return files, proof


class PromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.files, self.proof = fixture()
        self.package_pin = self.proof["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"]
        self.proof_pin = promotion.sha256(self.files[promotion.PROOF_PATH])

    def verify(self) -> dict:
        return promotion.verify_promotion_bytes(self.files, expected_package_sha256=self.package_pin,
                                                expected_proof_sha256=self.proof_pin)

    def save_proof(self) -> None:
        self.files[promotion.PROOF_PATH] = encode(self.proof)
        self.proof_pin = promotion.sha256(self.files[promotion.PROOF_PATH])

    def update(self, reference: dict, value: object) -> None:
        self.files[reference["path"]] = encode(value)
        reference["sha256"] = promotion.sha256(self.files[reference["path"]])
        self.save_proof()

    def test_all_eight_synthetic_bindings_verify_with_explicit_assurance(self) -> None:
        result = self.verify()
        self.assertEqual(result["binding_ids"], sorted(promotion.BINDINGS))
        self.assertFalse(result["provider_authenticity_verified"])
        self.assertFalse(result["native_harness_scoring_replayed"])
        self.assertEqual(result["evidence_assurance"], "structural_only")
        receipt_binding = promotion.release_proof_binding(result)
        self.assertEqual(receipt_binding["promotion_proof_sha256"], self.proof_pin)
        self.assertEqual(receipt_binding["promoted_behavioral_sha256"], self.package_pin)

    def use_host_fixture(self, *, delivery_mode: str = "inline") -> None:
        self.files, self.proof = host_fixture(delivery_mode=delivery_mode)
        self.package_pin = self.proof["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"]
        self.proof_pin = promotion.sha256(self.files[promotion.PROOF_PATH])

    def test_host_selected_promotion_replays_archives_without_live_host(self) -> None:
        self.use_host_fixture()
        result = self.verify()
        self.assertEqual(result["host_selected_binding_ids"], ["codex-v3-ultimate"])
        self.assertTrue(result["native_harness_scoring_replayed"])
        self.assertFalse(result["provider_authenticity_verified"])

    def test_file_delivery_promotion_and_probe_replay_archived_reads(self) -> None:
        self.use_host_fixture(delivery_mode="file")
        result = self.verify()
        self.assertTrue(result["native_harness_scoring_replayed"])
        self.assertEqual(result["host_selected_binding_ids"], ["codex-v3-ultimate"])
        self.assertFalse(result["provider_authenticity_verified"])
        row = self.proof["binding_evidence"][0]
        for reference in [row["probe"], *[run["receipt"] for run in row["runs"]]]:
            self.assertEqual(promotion.decode(self.files[reference["path"]])["tool_calls"], 1)

    def test_file_delivery_promotion_rejects_tampered_probe_read(self) -> None:
        self.use_host_fixture(delivery_mode="file")
        row = self.proof["binding_evidence"][0]
        reference = row["probe_files"]["child_transcript"]
        records = [json.loads(line) for line in self.files[reference["path"]].splitlines()]
        output = next(record["payload"] for record in records
                      if record["payload"].get("type") == "custom_tool_call_output")
        output["output"][1]["text"] = output["output"][1]["text"][:-1]
        self.files[reference["path"]] = b"".join(promotion.canonical(item) + b"\n" for item in records)
        reference["sha256"] = promotion.sha256(self.files[reference["path"]])
        self.save_proof()
        with self.assertRaisesRegex(ValueError, "FILE_READ_OUTPUT_INVALID"):
            self.verify()

    def test_host_selected_promotion_rejects_client_only_receipt(self) -> None:
        self.use_host_fixture()
        reference = self.proof["binding_evidence"][0]["runs"][0]["receipt"]
        receipt = promotion.decode(self.files[reference["path"]])
        receipt["identity_assurance"] = "client_configuration"
        self.update(reference, receipt)
        with self.assertRaisesRegex(ValueError, "HOST_RECEIPT_MISMATCH"):
            self.verify()

    def test_host_selected_promotion_rejects_prompt_only_and_forged_selection(self) -> None:
        for mutation in ("missing_parent", "changed_effort", "synthetic_origin"):
            with self.subTest(mutation=mutation):
                self.use_host_fixture()
                row = self.proof["binding_evidence"][0]
                if mutation == "missing_parent":
                    del row["runs"][0]["parent_transcript"]
                    self.save_proof()
                else:
                    reference = row["runs"][0]["transcript"]
                    records = [json.loads(line) for line in self.files[reference["path"]].splitlines()]
                    if mutation == "changed_effort":
                        records[4]["payload"]["effort"] = "low"
                    else:
                        records[0]["payload"]["originator"] = "Synthetic collector test"
                    self.files[reference["path"]] = b"".join(promotion.canonical(item) + b"\n" for item in records)
                    reference["sha256"] = promotion.sha256(self.files[reference["path"]])
                    self.save_proof()
                with self.assertRaises(ValueError):
                    self.verify()

    def test_host_selected_probe_must_be_independent_and_pass(self) -> None:
        self.use_host_fixture()
        row = self.proof["binding_evidence"][0]
        probe_ref = row["probe"]
        probe = promotion.decode(self.files[probe_ref["path"]])
        probe["result"] = "failed"
        self.update(probe_ref, probe)
        with self.assertRaisesRegex(ValueError, "HOST_PROBE_MISMATCH"):
            self.verify()

    def test_promotion_rejects_different_candidate_root(self) -> None:
        with self.assertRaisesRegex(ValueError, "PROBE_LOADER_RECEIPT_MISMATCH"):
            promotion.verify_promotion_bytes(self.files, expected_package_sha256=self.package_pin,
                                             expected_proof_sha256=self.proof_pin,
                                             candidate_root=Path("/tmp/other-candidate"))

    def test_claude_loader_receipt_and_log_are_independently_checked(self) -> None:
        row = self.proof["binding_evidence"][4]
        reference = row["probe_files"]["loader_debug_log"]
        probe_ref = row["probe"]
        probe = promotion.decode(self.files[probe_ref["path"]])
        probe["loader_debug_log_sha256"] = "0" * 64
        self.update(probe_ref, probe)
        with self.assertRaisesRegex(ValueError, "PROBE_LOADER_RECEIPT_MISMATCH"):
            self.verify()
        probe["loader_debug_log_sha256"] = reference["sha256"]
        self.update(probe_ref, probe)
        self.files[reference["path"]] = self.files[reference["path"]].replace(
            str(promotion.ROOT).encode(), b"/tmp/stale-candidate")
        reference["sha256"] = promotion.sha256(self.files[reference["path"]])
        probe["loader_debug_log_sha256"] = reference["sha256"]
        self.update(probe_ref, probe)
        with self.assertRaisesRegex(ValueError, "PROBE_LOADER_ROOT_MISMATCH"):
            self.verify()

    def test_claude_loader_missing_order_and_wrong_session_fail(self) -> None:
        row = self.proof["binding_evidence"][4]
        reference = row["probe_files"]["loader_debug_log"]
        del row["probe_files"]["loader_debug_log"]
        self.save_proof()
        with self.assertRaisesRegex(ValueError, "PROBE_FILES_INVALID"):
            self.verify()
        row["probe_files"]["loader_debug_log"] = reference
        reference["path"] = reference["path"].replace("probe-4.txt", "other-session.txt")
        self.files[reference["path"]] = self.files[row["probe_files"]["parent_transcript"]["path"]]
        self.save_proof()
        with self.assertRaisesRegex(ValueError, "PROBE_LOADER_SESSION_MISMATCH"):
            self.verify()
        self.setUp()
        row = self.proof["binding_evidence"][4]
        reference = row["probe_files"]["loader_debug_log"]
        raw = self.files[reference["path"]]
        self.files[reference["path"]] = b"\n".join(reversed(raw.splitlines())) + b"\n"
        reference["sha256"] = promotion.sha256(self.files[reference["path"]])
        probe_ref = row["probe"]
        probe = promotion.decode(self.files[probe_ref["path"]])
        probe["loader_debug_log_sha256"] = reference["sha256"]
        self.update(probe_ref, probe)
        with self.assertRaisesRegex(ValueError, "PROBE_LOADER_ORDER_INVALID"):
            self.verify()

    def test_deterministic_transformation_changes_only_status_and_hashes(self) -> None:
        candidate_bytes = self.files[promotion.ARCHIVE_PATH]
        before = promotion.decode(candidate_bytes)
        promoted_bytes = promotion.promote_registry(candidate_bytes)
        self.assertEqual(promoted_bytes, promotion.promote_registry(candidate_bytes))
        after = promotion.decode(promoted_bytes)
        after["registry_sha256"] = before["registry_sha256"]
        after["provider_states"] = before["provider_states"]
        for initial, changed in zip(before["bindings"], after["bindings"]):
            changed["status"], changed["binding_sha256"] = initial["status"], initial["binding_sha256"]
        self.assertEqual(before, after)
        self.assertEqual(candidate_bytes, self.files[promotion.ARCHIVE_PATH])

    def test_exact_candidate_bytes_determine_reconstructed_identity(self) -> None:
        original = self.proof["candidate_release_binding"]
        reformatted = encode(promotion.decode(self.files[promotion.ARCHIVE_PATH]))
        self.assertNotEqual(original, promotion.release_binding(self.files.__getitem__, reformatted))
        self.update(self.proof["candidate_registry"], promotion.decode(reformatted))
        with self.assertRaisesRegex(ValueError, "RELEASE_BINDING_MISMATCH"):
            self.verify()

    def test_matches_existing_harness_identity_algorithm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            files, proof = fixture(root)
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            self.assertEqual(current_release_binding(root), proof["promoted_release_binding"])
            self.assertEqual(promotion.verify_promotion(root)["promotion_proof_sha256"], promotion.sha256(files[promotion.PROOF_PATH]))

    def write_package(self, root: Path) -> None:
        for relative, content in self.files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def test_non_registry_behavior_change_rejects_old_candidate(self) -> None:
        self.files["scripts/behavior.py"] += b"changed = True\n"
        with self.assertRaisesRegex(ValueError, "RELEASE_BINDING_MISMATCH"):
            self.verify()

    def test_registry_with_recomputed_arbitrary_edit_is_rejected(self) -> None:
        live = promotion.decode(self.files[promotion.REGISTRY_PATH])
        live["bindings"][0]["model_id"] = "unqualified-replacement"
        binding = live["bindings"][0]
        binding["binding_sha256"] = promotion.sha256(promotion.canonical({k: v for k, v in binding.items() if k != "binding_sha256"}))
        live["registry_sha256"] = promotion.sha256(promotion.canonical({k: v for k, v in live.items() if k != "registry_sha256"}))
        self.files[promotion.REGISTRY_PATH] = encode(live)
        with self.assertRaisesRegex(ValueError, "TRANSFORMATION_MISMATCH"):
            self.verify()

    def test_missing_duplicate_and_unknown_binding_evidence_fail(self) -> None:
        for mutation in (lambda rows: rows.pop(), lambda rows: rows.__setitem__(0, copy.deepcopy(rows[1])),
                         lambda rows: rows[0].__setitem__("binding_id", "unknown")):
            with self.subTest(mutation=mutation):
                self.setUp()
                mutation(self.proof["binding_evidence"])
                self.save_proof()
                with self.assertRaisesRegex(ValueError, "EVIDENCE_SET_INVALID"):
                    self.verify()

    def test_stale_artifact_bytes_are_rejected(self) -> None:
        reference = self.proof["binding_evidence"][0]["pair"]
        self.files[reference["path"]] += b" "
        with self.assertRaisesRegex(ValueError, "ARTIFACT_HASH_MISMATCH"):
            self.verify()

    def test_proof_and_package_pins_are_checked(self) -> None:
        for pin in ("proof_pin", "package_pin"):
            with self.subTest(pin=pin):
                self.setUp()
                setattr(self, pin, "0" * 64)
                with self.assertRaisesRegex(ValueError, "PIN_MISMATCH"):
                    self.verify()

    def test_reused_qualification_session_rejected(self) -> None:
        reference = self.proof["binding_evidence"][1]["pair"]
        pair = promotion.decode(self.files[reference["path"]])
        pair["session_ids"][0] = "session-0-1"
        self.update(reference, pair)
        with self.assertRaisesRegex(ValueError, "SESSION_REUSED"):
            self.verify()

    def test_missing_null_effort_rejected(self) -> None:
        reference = self.proof["binding_evidence"][-1]["pair"]
        pair = promotion.decode(self.files[reference["path"]])
        del pair["effort"]
        self.update(reference, pair)
        with self.assertRaisesRegex(ValueError, "PAIR_INVALID"):
            self.verify()

    def test_codex_attested_identity_required(self) -> None:
        reference = self.proof["binding_evidence"][0]["probe"]
        probe = promotion.decode(self.files[reference["path"]])
        del probe["provider_attested_effort"]
        self.update(reference, probe)
        with self.assertRaisesRegex(ValueError, "CODEX_ATTESTATION_INVALID"):
            self.verify()

    def test_transcript_claims_are_rescored(self) -> None:
        row = self.proof["binding_evidence"][0]
        run = row["runs"][0]
        transcript = promotion.json_lines(self.files[run["transcript"]["path"]])
        transcript[1]["response"]["results"][0]["claims"] = []
        raw = b"".join(promotion.canonical(item) + b"\n" for item in transcript)
        self.files[run["transcript"]["path"]] = raw
        run["transcript"]["sha256"] = promotion.sha256(raw)
        receipt = promotion.decode(self.files[run["receipt"]["path"]])
        receipt["transcript_sha256"] = promotion.sha256(raw)
        self.update(run["receipt"], receipt)
        with self.assertRaisesRegex(ValueError, "TRANSCRIPT_SCENARIO_FAILED"):
            self.verify()

    def test_unknown_or_duplicate_scenario_rejected(self) -> None:
        reference = self.proof["binding_evidence"][0]["runs"][0]["receipt"]
        receipt = promotion.decode(self.files[reference["path"]])
        receipt["scenario_results"][0] = receipt["scenario_results"][1]
        self.update(reference, receipt)
        with self.assertRaisesRegex(ValueError, "SCENARIO_RESULTS_INVALID"):
            self.verify()

    def test_duplicate_json_keys_rejected_in_proof_archive_and_transcript(self) -> None:
        for kind in ("proof", "archive", "transcript"):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == "proof":
                    self.files[promotion.PROOF_PATH] = self.files[promotion.PROOF_PATH].replace(b'{', b'{"schema_version":"duplicate",', 1)
                    self.proof_pin = promotion.sha256(self.files[promotion.PROOF_PATH])
                else:
                    reference = self.proof["candidate_registry"] if kind == "archive" else self.proof["binding_evidence"][0]["runs"][0]["transcript"]
                    raw = self.files[reference["path"]].replace(b'{', b'{"duplicate":1,"duplicate":2,', 1)
                    self.files[reference["path"]] = raw
                    reference["sha256"] = promotion.sha256(raw)
                    self.save_proof()
                with self.assertRaisesRegex(ValueError, "DUPLICATE_JSON_KEY"):
                    self.verify()

    def test_traversal_and_duplicate_file_references_rejected(self) -> None:
        for path in ("../outside.json", "/tmp/outside.json", "standards//outside.json", promotion.ARCHIVE_PATH):
            with self.subTest(path=path):
                self.setUp()
                self.proof["binding_evidence"][0]["pair"]["path"] = path
                self.save_proof()
                with self.assertRaisesRegex(ValueError, "PATH_UNSAFE|REFERENCE_DUPLICATE"):
                    self.verify()

    def test_archive_must_stay_outside_behavioral_inventory(self) -> None:
        declaration = promotion.decode(self.files[promotion.INVENTORY_PATH])
        declaration["paths"].append(promotion.ARCHIVE_PATH)
        self.files[promotion.INVENTORY_PATH] = encode(declaration)
        with self.assertRaisesRegex(ValueError, "REFERENCE_DUPLICATE_OR_BEHAVIORAL"):
            self.verify()

    def test_symlinks_and_hardlinks_rejected(self) -> None:
        for alias in ("file_symlink", "directory_symlink", "hardlink"):
            with self.subTest(alias=alias), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve() / "package"
                self.write_package(root)
                target = root / self.proof["binding_evidence"][0]["pair"]["path"]
                source = root / self.proof["binding_evidence"][1]["pair"]["path"]
                if alias == "directory_symlink":
                    real = target.parent.with_name(target.parent.name + "-real")
                    target.parent.rename(real)
                    target.parent.symlink_to(real, target_is_directory=True)
                else:
                    target.unlink()
                    if alias == "file_symlink":
                        target.symlink_to(source)
                    else:
                        os.link(root / promotion.ARCHIVE_PATH, target)
                with self.assertRaisesRegex(ValueError, "PATH_UNSAFE|FILE_ALIAS"):
                    promotion.verify_promotion(root)

    def test_stale_hash_partial_registry_is_rejected(self) -> None:
        candidate = promotion.decode(self.files[promotion.ARCHIVE_PATH])
        candidate["bindings"][0]["status"] = "qualified"
        with self.assertRaisesRegex(ValueError, "BINDING_HASH_MISMATCH"):
            promotion.promote_registry(encode(candidate))

    def use_fixture(self, **options: object) -> None:
        self.files, self.proof = fixture(**options)
        self.package_pin = self.proof["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"]
        self.proof_pin = promotion.sha256(self.files[promotion.PROOF_PATH])

    def rehash(self, value: dict) -> dict:
        for binding in value["bindings"]:
            binding["binding_sha256"] = promotion.sha256(promotion.canonical({k: v for k, v in binding.items() if k != "binding_sha256"}))
        value["provider_states"] = promotion.provider_states(value["bindings"], value["provider_states"])
        value["registry_sha256"] = promotion.sha256(promotion.canonical({k: v for k, v in value.items() if k != "registry_sha256"}))
        return value

    def test_one_provider_promotes_without_other_provider_evidence(self) -> None:
        selected = [key for key in promotion.BINDINGS if key.startswith("codex-")]
        self.use_fixture(binding_ids=selected)
        self.assertEqual(self.verify()["binding_ids"], sorted(selected))
        live = promotion.registry(self.files[promotion.REGISTRY_PATH])
        self.assertEqual(live["provider_states"], {"codex": {"council_status": "qualified"},
                         "claude_code": {"council_status": "fail_closed_until_qualified"}})
        self.assertEqual(promotion.frozen_candidate_root(self.files), promotion.ROOT)

    def test_one_binding_promotes_without_other_tier_evidence(self) -> None:
        self.use_fixture(binding_ids=["claude-code-v3-worker"])
        self.assertEqual(self.verify()["binding_ids"], ["claude-code-v3-worker"])
        before = promotion.registry(self.files[promotion.ARCHIVE_PATH])
        after = promotion.registry(self.files[promotion.REGISTRY_PATH])
        self.assertEqual(after["provider_states"]["claude_code"]["council_status"], "partially_qualified")
        for old, new in zip(before["bindings"], after["bindings"]):
            if old["binding_id"] != "claude-code-v3-worker":
                self.assertEqual(old, new)

    def test_reserve_binding_promotes_independently(self) -> None:
        candidate = promotion.decode(self.files[promotion.ARCHIVE_PATH])
        reserve = copy.deepcopy(candidate["bindings"][0])
        reserve["binding_id"] = "codex-v3-ultimate-reserve"
        reserve["selection"] = {"role": "reserve", "priority": 2, "fallback_for": ["codex-v3-operational"]}
        candidate["bindings"].append(reserve)
        self.use_fixture(binding_ids=[reserve["binding_id"]], registry_value=self.rehash(candidate))
        self.assertEqual(self.verify()["binding_ids"], [reserve["binding_id"]])

    def claude_reserve_fixture(self) -> None:
        candidate = promotion.decode(self.files[promotion.ARCHIVE_PATH])
        reserve = copy.deepcopy(candidate["bindings"][-1])
        reserve["binding_id"] = "reserve-worker"
        reserve["model_id"] = "claude-reserve-distinct-model"
        reserve["selection"] = {"role": "reserve", "priority": 1, "fallback_for": []}
        candidate["bindings"].append(reserve)
        self.use_fixture(binding_ids=[reserve["binding_id"]], registry_value=self.rehash(candidate))

    def test_claude_reserve_uses_distinct_binding_agent_definition(self) -> None:
        self.claude_reserve_fixture()
        self.assertEqual(self.verify()["binding_ids"], ["reserve-worker"])
        row = self.proof["binding_evidence"][0]
        probe = promotion.decode(self.files[row["probe"]["path"]])
        self.assertEqual(probe["subagent_type"], "agent-council:reserve-worker")
        self.assertEqual(probe["agent_definition_sha256"], promotion.sha256(self.files["agents/reserve-worker.md"]))
        self.assertEqual(promotion.frozen_candidate_root(self.files), promotion.ROOT)

    def test_claude_reserve_cannot_reuse_primary_agent_definition(self) -> None:
        self.claude_reserve_fixture()
        reference = self.proof["binding_evidence"][0]["probe"]
        probe = promotion.decode(self.files[reference["path"]])
        probe["subagent_type"] = "agent-council:council-worker"
        probe["agent_definition_sha256"] = promotion.sha256(self.files["agents/council-worker.md"])
        self.update(reference, probe)
        with self.assertRaisesRegex(ValueError, "PROBE_AGENT_MISMATCH"):
            self.verify()

    def test_claude_reserve_definition_must_be_in_frozen_inventory(self) -> None:
        self.claude_reserve_fixture()
        declaration = promotion.decode(self.files[promotion.INVENTORY_PATH])
        declaration["paths"].remove("agents/reserve-worker.md")
        self.files[promotion.INVENTORY_PATH] = encode(declaration)
        # Rebind synthetic evidence to isolate the missing-inventory guard.
        old_release = self.proof["candidate_release_binding"]
        candidate_release = promotion.release_binding(self.files.__getitem__, self.files[promotion.ARCHIVE_PATH])
        def replace(value: object) -> object:
            if value == old_release:
                return candidate_release
            if isinstance(value, dict):
                return {key: replace(item) for key, item in value.items()}
            if isinstance(value, list):
                return [replace(item) for item in value]
            return value
        row = self.proof["binding_evidence"][0]
        frozen_ref = row["probe_files"]["release_binding"]
        self.update(frozen_ref, candidate_release)
        for reference in [row["pair"], row["probe"], *(run["receipt"] for run in row["runs"])]:
            value = replace(promotion.decode(self.files[reference["path"]]))
            if reference is row["probe"]:
                value["release_binding_file_sha256"] = frozen_ref["sha256"]
            self.update(reference, value)
        self.proof["candidate_release_binding"] = candidate_release
        self.proof["promoted_release_binding"] = promotion.release_binding(self.files.__getitem__)
        self.package_pin = self.proof["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"]
        self.save_proof()
        with self.assertRaisesRegex(ValueError, "PROBE_AGENT_NOT_IN_INVENTORY"):
            self.verify()

    def test_retirement_preserved_and_not_promotable(self) -> None:
        candidate = promotion.decode(self.files[promotion.ARCHIVE_PATH])
        retired = candidate["bindings"][0]
        retired["status"] = "retired"
        retired["lifecycle"] = {"retired_at": "2026-10-01T09:00:00+10:00", "reason": "Model withdrawn",
                                "replacement_binding_id": None}
        self.use_fixture(binding_ids=["codex-v3-worker"], registry_value=self.rehash(candidate))
        self.assertEqual(self.verify()["binding_ids"], ["codex-v3-worker"])
        self.assertEqual(promotion.registry(self.files[promotion.REGISTRY_PATH])["bindings"][0], retired)
        with self.assertRaisesRegex(ValueError, "PROMOTION_SET_INVALID"):
            promotion.promote_registry(self.files[promotion.ARCHIVE_PATH], [retired["binding_id"]])

    def test_partial_promotion_cannot_silently_promote_unproven_binding(self) -> None:
        self.use_fixture(binding_ids=["codex-v3-worker"])
        self.files[promotion.REGISTRY_PATH] = promotion.promote_registry(self.files[promotion.ARCHIVE_PATH])
        with self.assertRaisesRegex(ValueError, "EVIDENCE_SET_INVALID"):
            self.verify()

    def test_existing_qualified_binding_is_preserved_by_later_promotion(self) -> None:
        candidate = promotion.decode(self.files[promotion.ARCHIVE_PATH])
        candidate["bindings"][0]["status"] = "qualified"
        candidate = self.rehash(candidate)
        promoted = promotion.registry(promotion.promote_registry(encode(candidate), ["codex-v3-worker"]))
        self.assertEqual(promoted["bindings"][0], candidate["bindings"][0])

    def test_prequalified_archive_cannot_bypass_binding_evidence(self) -> None:
        candidate = promotion.decode(self.files[promotion.ARCHIVE_PATH])
        candidate["bindings"][0]["status"] = "qualified"
        self.use_fixture(binding_ids=["codex-v3-worker"], registry_value=self.rehash(candidate))
        with self.assertRaisesRegex(ValueError, "PRIOR_QUALIFICATION_UNPROVEN"):
            self.verify()

    def test_invalid_fallback_and_retirement_metadata_rejected(self) -> None:
        for kind in ("unknown", "lower_tier", "cross_provider", "missing_retirement", "naive_time"):
            with self.subTest(kind=kind):
                candidate = promotion.decode(self.files[promotion.ARCHIVE_PATH])
                binding = candidate["bindings"][-1]
                if kind in {"missing_retirement", "naive_time"}:
                    binding["status"] = "retired"
                    if kind == "naive_time":
                        binding["lifecycle"] = {"retired_at": "2026-10-01T09:00:00", "reason": "Withdrawn", "replacement_binding_id": None}
                else:
                    target = {"unknown": "unknown-binding", "lower_tier": "claude-code-v3-ultimate", "cross_provider": "codex-v3-worker"}[kind]
                    binding["selection"] = {"role": "reserve", "priority": 1, "fallback_for": [target]}
                with self.assertRaisesRegex(ValueError, "FALLBACK_INVALID|LIFECYCLE_INVALID"):
                    promotion.registry(encode(self.rehash(candidate)))

    def test_missing_proof_cannot_authorize_qualified_registry(self) -> None:
        del self.files[promotion.PROOF_PATH]
        with self.assertRaisesRegex(ValueError, "FILE_MISSING"):
            self.verify()

    def test_unknown_evidence_property_rejected(self) -> None:
        self.proof["binding_evidence"][0]["extra_receipt"] = self.proof["binding_evidence"][0]["pair"]
        self.save_proof()
        with self.assertRaisesRegex(ValueError, "EVIDENCE_INVALID"):
            self.verify()

    def test_candidate_binding_substitution_rejects_original_evidence(self) -> None:
        candidate = promotion.decode(self.files[promotion.ARCHIVE_PATH])
        binding = candidate["bindings"][0]
        binding["model_id"] = "substituted-model"
        binding["binding_sha256"] = promotion.sha256(promotion.canonical({k: v for k, v in binding.items() if k != "binding_sha256"}))
        candidate["registry_sha256"] = promotion.sha256(promotion.canonical({k: v for k, v in candidate.items() if k != "registry_sha256"}))
        self.update(self.proof["candidate_registry"], candidate)
        archived = self.files[promotion.ARCHIVE_PATH]
        self.files[promotion.REGISTRY_PATH] = promotion.promote_registry(archived)
        self.proof["candidate_release_binding"] = promotion.release_binding(self.files.__getitem__, archived)
        self.proof["promoted_release_binding"] = promotion.release_binding(self.files.__getitem__)
        self.package_pin = self.proof["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"]
        self.save_proof()
        with self.assertRaisesRegex(ValueError, "PAIR_INVALID"):
            self.verify()

    def test_boolean_attestations_are_not_numeric(self) -> None:
        reference = self.proof["binding_evidence"][0]["runs"][0]["receipt"]
        receipt = promotion.decode(self.files[reference["path"]])
        receipt["clean_context"] = 1
        self.update(reference, receipt)
        with self.assertRaisesRegex(ValueError, "RUN_INVALID"):
            self.verify()

    def test_child_council_reentry_is_rejected(self) -> None:
        row = self.proof["binding_evidence"][-1]
        reference = row["probe_files"]["child_transcript"]
        child = promotion.json_lines(self.files[reference["path"]])
        child[0]["message"]["content"].append({"type": "tool_use", "name": "Agent", "id": "recursive", "input": {}})
        raw = b"".join(promotion.canonical(item) + b"\n" for item in child)
        self.files[reference["path"]] = raw
        reference["sha256"] = promotion.sha256(raw)
        probe = promotion.decode(self.files[row["probe"]["path"]])
        probe["child_transcript_sha256"] = reference["sha256"]
        self.update(row["probe"], probe)
        with self.assertRaisesRegex(ValueError, "COUNCIL_REENTRY"):
            self.verify()

    def test_parent_probe_completion_must_be_present(self) -> None:
        row = self.proof["binding_evidence"][-1]
        reference = row["probe_files"]["parent_transcript"]
        parent = promotion.json_lines(self.files[reference["path"]])
        parent.pop()
        raw = b"".join(promotion.canonical(item) + b"\n" for item in parent)
        self.files[reference["path"]] = raw
        reference["sha256"] = promotion.sha256(raw)
        probe = promotion.decode(self.files[row["probe"]["path"]])
        probe["parent_transcript_sha256"] = reference["sha256"]
        self.update(row["probe"], probe)
        with self.assertRaisesRegex(ValueError, "PROBE_RESULT_INVALID"):
            self.verify()

    def set_async_completion(self, completion_session: str | None, *, child_finished: bool = False) -> None:
        row = self.proof["binding_evidence"][-1]
        probe = promotion.decode(self.files[row["probe"]["path"]])
        reference = row["probe_files"]["parent_transcript"]
        parent = promotion.json_lines(self.files[reference["path"]])
        parent[-1]["toolUseResult"].update({"status": "async_launched", "isAsync": True})
        completion = {"type": "user", "origin": {"kind": "task-notification", "producer": "session-task"},
                      "message": {"content": "<task-notification><task-id>" + probe["agent_id"]
                                  + "</task-id><tool-use-id>" + probe["tool_use_id"]
                                  + "</tool-use-id><status>completed</status></task-notification>"}}
        if completion_session is not None:
            completion["sessionId"] = completion_session
        parent.append(completion)
        raw = b"".join(promotion.canonical(item) + b"\n" for item in parent)
        self.files[reference["path"]] = raw
        reference["sha256"] = promotion.sha256(raw)
        probe.update({"parent_transcript_sha256": reference["sha256"], "completion_evidence": "task_notification_handback"})
        child_ref = row["probe_files"]["child_transcript"]
        child = promotion.json_lines(self.files[child_ref["path"]])
        child[-1]["uuid"] = "synthetic-handback-row"
        child[-1]["message"]["content"] = [{"type": "tool_use", "name": "SubagentHandback", "id": "handback-tool"}]
        child.append({"type": "user", "sessionId": probe["child_session_id"], "agentId": probe["agent_id"],
                      "sourceToolAssistantUUID": "synthetic-handback-row", "message": {"content": [
                          {"type": "tool_result", "tool_use_id": "handback-tool"}]},
                      "toolUseResult": {"success": True}})
        if child_finished:
            child[-2]["message"]["stop_reason"] = "end_turn"
        child_raw = b"".join(promotion.canonical(item) + b"\n" for item in child)
        self.files[child_ref["path"]] = child_raw
        child_ref["sha256"] = promotion.sha256(child_raw)
        probe["child_transcript_sha256"] = child_ref["sha256"]
        self.update(row["probe"], probe)

    def test_async_completion_from_parent_session_is_accepted(self) -> None:
        self.set_async_completion("probe-7")
        self.assertEqual(self.verify()["result"], "verified")

    def test_async_completion_requires_exact_parent_session(self) -> None:
        for session in ("foreign-session", None):
            with self.subTest(session=session):
                self.setUp()
                self.set_async_completion(session)
                with self.assertRaisesRegex(ValueError, "PROBE_ASYNC_SESSION_MISMATCH"):
                    self.verify()

    def test_child_end_turn_does_not_mask_foreign_completion_session(self) -> None:
        self.set_async_completion("foreign-session", child_finished=True)
        with self.assertRaisesRegex(ValueError, "PROBE_ASYNC_SESSION_MISMATCH"):
            self.verify()

    def set_probe_sessions(self, index: int, parent_session: str, child_session: str) -> None:
        row = self.proof["binding_evidence"][index]
        probe = promotion.decode(self.files[row["probe"]["path"]])
        probe.update({"parent_session_id": parent_session, "child_session_id": child_session})
        for kind, session in (("parent_transcript", parent_session), ("child_transcript", child_session)):
            reference = row["probe_files"][kind]
            transcript = promotion.json_lines(self.files[reference["path"]])
            for item in transcript:
                if "sessionId" in item:
                    item["sessionId"] = session
                if "session_id" in item:
                    item["session_id"] = session
                if "parent_session_id" in item:
                    item["parent_session_id"] = parent_session
                if "child_session_id" in item:
                    item["child_session_id"] = child_session
            raw = b"".join(promotion.canonical(item) + b"\n" for item in transcript)
            self.files[reference["path"]] = raw
            reference["sha256"] = promotion.sha256(raw)
            probe[kind + "_sha256"] = reference["sha256"]
        self.update(row["probe"], probe)

    def test_codex_probes_can_share_parent_with_distinct_child_sessions(self) -> None:
        for index in range(4):
            self.set_probe_sessions(index, "shared-codex-parent", f"probe-child-{index}")
        shared_parent = b"".join(self.files[self.proof["binding_evidence"][index]["probe_files"]["parent_transcript"]["path"]]
                                 for index in range(4))
        shared_ref = {"path": "standards/model-qualifications/synthetic/shared-codex-parent.jsonl",
                      "sha256": promotion.sha256(shared_parent)}
        self.files[shared_ref["path"]] = shared_parent
        for index in range(4):
            row = self.proof["binding_evidence"][index]
            row["probe_files"]["parent_transcript"] = dict(shared_ref)
            probe = promotion.decode(self.files[row["probe"]["path"]])
            probe["parent_transcript_sha256"] = shared_ref["sha256"]
            self.update(row["probe"], probe)
        self.assertEqual(self.verify()["result"], "verified")

    def test_codex_probe_child_cannot_equal_parent(self) -> None:
        self.set_probe_sessions(0, "same-parent-child", "same-parent-child")
        with self.assertRaisesRegex(ValueError, "CODEX_CHILD_SESSION_NOT_DISTINCT"):
            self.verify()

    def test_codex_probe_child_session_cannot_be_reused(self) -> None:
        self.set_probe_sessions(1, "probe-1", "probe-child-0")
        with self.assertRaisesRegex(ValueError, "SESSION_REUSED"):
            self.verify()

    def test_claude_probes_share_parent_export_with_distinct_agent_ids(self) -> None:
        for index in range(4, 8):
            self.set_probe_sessions(index, "shared-claude-root", "shared-claude-root")
        shared_parent = b"".join(self.files[self.proof["binding_evidence"][index]["probe_files"]["parent_transcript"]["path"]]
                                 for index in range(4, 8))
        shared_ref = {"path": "standards/model-qualifications/synthetic/shared-parent.jsonl",
                      "sha256": promotion.sha256(shared_parent)}
        self.files[shared_ref["path"]] = shared_parent
        frozen_ref = self.proof["binding_evidence"][4]["probe_files"]["release_binding"]
        loader_ref = self.proof["binding_evidence"][4]["probe_files"]["loader_debug_log"]
        shared_loader = {"path": "standards/model-qualifications/synthetic/shared-claude-root.txt",
                         "sha256": loader_ref["sha256"]}
        self.files[shared_loader["path"]] = self.files[loader_ref["path"]]
        for index in range(4, 8):
            row = self.proof["binding_evidence"][index]
            row["probe_files"]["parent_transcript"] = dict(shared_ref)
            row["probe_files"]["release_binding"] = dict(frozen_ref)
            row["probe_files"]["loader_debug_log"] = dict(shared_loader)
            probe = promotion.decode(self.files[row["probe"]["path"]])
            probe["parent_transcript_sha256"] = shared_ref["sha256"]
            probe["loader_debug_log_sha256"] = shared_loader["sha256"]
            self.update(row["probe"], probe)
        self.assertEqual(self.verify()["result"], "verified")

    def test_claude_probe_child_agent_cannot_be_reused(self) -> None:
        row = self.proof["binding_evidence"][-1]
        probe = promotion.decode(self.files[row["probe"]["path"]])
        probe["agent_id"] = "agent-6"
        self.update(row["probe"], probe)
        with self.assertRaisesRegex(ValueError, "PROBE_CHILD_REUSED"):
            self.verify()


class PublicProjectionTests(unittest.TestCase):
    def project(self, host=False):
        files, proof = host_fixture() if host else fixture(binding_ids=["claude-code-v3-ultimate"])
        closure = promotion.export_public_promotion_bytes(
            files, expected_package_sha256=proof["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"],
            expected_proof_sha256=promotion.sha256(files[promotion.PROOF_PATH]))
        self.assertEqual(set(closure), {promotion.PROOF_PATH, promotion.ARCHIVE_PATH})
        public_files = {path: files[path] for path in proof["promoted_release_binding"]["behavioral_identity"]["paths"]}
        public_files[promotion.INVENTORY_PATH] = files[promotion.INVENTORY_PATH]
        public_files.update(closure)
        return public_files, promotion.decode(closure[promotion.PROOF_PATH])

    def verify(self, files, proof):
        files[promotion.PROOF_PATH] = encode(proof)
        return promotion.verify_promotion_bytes(files,
            expected_package_sha256=proof["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"],
            expected_proof_sha256=promotion.sha256(files[promotion.PROOF_PATH]))

    def test_public_claude_offline_and_privacy(self):
        files, proof = self.project()
        raw = files[promotion.PROOF_PATH]
        for secret in (str(promotion.ROOT), "session-", "probe-child-", "Synthetic", "loader_root", "tool_use_id", "rationale", "preparation"):
            self.assertNotIn(secret.encode(), raw)
        result = self.verify(files, proof)
        self.assertFalse(result["native_harness_scoring_replayed"])
        self.assertFalse(result["provider_authenticity_verified"])
        self.assertTrue(result["claims_scoring_replayed"])
        self.assertEqual(result["artifact_paths"], sorted([promotion.PROOF_PATH, promotion.ARCHIVE_PATH]))
        self.assertEqual(proof["binding_evidence"][0]["identity_assurance"], "transcript_reported")
        self.assertEqual(promotion.frozen_candidate_root(files), promotion.ROOT)

    def test_public_codex_preserves_host_selected_assurance(self):
        files, proof = self.project(host=True)
        self.assertEqual(proof["binding_evidence"][0]["identity_assurance"], "host_selected")
        self.assertEqual(self.verify(files, proof)["result"], "verified")

    def test_public_rejects_unknown_keys_and_claims(self):
        for target in ("top", "row", "run", "probe", "claim"):
            with self.subTest(target=target):
                files, proof = self.project()
                row = proof["binding_evidence"][0]
                if target == "claim":
                    row["runs"][0]["scenario_claims"][0]["claims"].append("/Users/private/free-text")
                else:
                    value = {"top": proof, "row": row, "run": row["runs"][0], "probe": row["probe"]}[target]
                    value["private_path"] = "/Users/private/native.jsonl"
                with self.assertRaises(ValueError):
                    self.verify(files, proof)

    def test_public_rejects_reused_sessions_missing_claims_and_stale_hashes(self):
        for mutation in ("session", "claims", "candidate", "promoted", "archive", "rows"):
            with self.subTest(mutation=mutation):
                files, proof = self.project()
                row = proof["binding_evidence"][0]
                if mutation == "session":
                    row["runs"][1]["session_sha256"] = row["runs"][0]["session_sha256"]
                elif mutation == "claims":
                    row["runs"][0]["scenario_claims"][0]["claims"] = []
                elif mutation in {"candidate", "promoted"}:
                    proof[mutation + "_release_binding"]["behavioral_identity"]["behavioral_sha256"] = "0" * 64
                elif mutation == "archive":
                    proof["candidate_registry"]["sha256"] = "0" * 64
                else:
                    proof["binding_evidence"] = []
                with self.assertRaises(ValueError):
                    self.verify(files, proof)

    def test_export_requires_verified_private_proof(self):
        files, proof = fixture(binding_ids=["claude-code-v3-ultimate"])
        files[proof["binding_evidence"][0]["runs"][0]["transcript"]["path"]] += b"private corruption\n"
        with self.assertRaises(ValueError):
            promotion.export_public_promotion_bytes(files,
                expected_package_sha256=proof["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"],
                expected_proof_sha256=promotion.sha256(files[promotion.PROOF_PATH]))

    def test_public_rejects_codex_probe_reuse_and_identity_upgrade(self):
        for mutation in ("session_sha256", "agent_sha256", "turn_sha256", "transcript_sha256", "assurance", "model", "effort", "native", "authenticity"):
            with self.subTest(mutation=mutation):
                files, proof = self.project(host=True)
                row = proof["binding_evidence"][0]
                if mutation.endswith("sha256"):
                    row["probe"][mutation] = row["runs"][0][mutation]
                elif mutation == "assurance":
                    row["identity_assurance"] = "provider_observed"
                elif mutation == "model":
                    row["model_id"] = "/Users/private/model"
                elif mutation == "effort":
                    row["effort"] = "minimal"
                elif mutation == "native":
                    proof["native_harness_scoring_replayed"] = True
                else:
                    proof["provider_authenticity_verified"] = True
                with self.assertRaises(ValueError):
                    self.verify(files, proof)

    def test_identifier_hashes_separate_candidates_and_domains(self):
        first = promotion.public_identifier("a" * 64, "session", "private-native-id")
        self.assertNotEqual(first, promotion.public_identifier("b" * 64, "session", "private-native-id"))
        self.assertNotEqual(first, promotion.public_identifier("a" * 64, "agent", "private-native-id"))
        self.assertEqual(first, promotion.public_identifier("a" * 64, "session", "private-native-id"))

    def test_public_all_selected_claude_rows_and_cross_binding_sessions(self):
        files, private = fixture(binding_ids=[name for name in promotion.BINDINGS if name.startswith("claude-code-")])
        closure = promotion.export_public_promotion_bytes(files,
            expected_package_sha256=private["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"],
            expected_proof_sha256=promotion.sha256(files[promotion.PROOF_PATH]))
        files.update(closure)
        proof = promotion.decode(closure[promotion.PROOF_PATH])
        self.assertEqual(len(self.verify(files, proof)["binding_ids"]), 4)
        proof["binding_evidence"][1]["runs"][0]["session_sha256"] = proof["binding_evidence"][0]["runs"][0]["session_sha256"]
        with self.assertRaisesRegex(ValueError, "SESSION_REUSED"):
            self.verify(files, proof)

    def test_public_schema_covers_projection_and_claim_vocabulary(self):
        schema = promotion.decode((promotion.ROOT / "standards/agent-council-promotion.schema.v2.yaml").read_bytes())
        self.assertEqual(set(schema["$defs"]["claims"]["items"]["properties"]["claims"]["items"]["enum"]), set(promotion.CLAIM_VOCABULARY))
        try:
            import jsonschema
        except ImportError:
            return
        jsonschema.Draft202012Validator.check_schema(schema)
        for host in (False, True):
            _, proof = self.project(host=host)
            if host:
                schema = promotion.decode((promotion.ROOT / "standards/agent-council-promotion.schema.v4.yaml").read_bytes())
            jsonschema.validate(proof, schema)


class RolePromotionTests(unittest.TestCase):
    """Synthetic role evidence checks integrity only, never native qualification."""

    def setUp(self):
        self.files, self.proof = fixture(binding_ids=["claude-code-v3-ultimate"], role_protocol=True)

    def verify(self):
        self.files[promotion.PROOF_PATH] = encode(self.proof)
        return promotion.verify_promotion_bytes(self.files,
            expected_package_sha256=self.proof["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"],
            expected_proof_sha256=promotion.sha256(self.files[promotion.PROOF_PATH]))

    def update(self, reference, value):
        self.files[reference["path"]] = encode(value)
        reference["sha256"] = promotion.sha256(self.files[reference["path"]])

    def project(self):
        self.verify()
        self.files.update(promotion.export_public_promotion_bytes(self.files,
            expected_package_sha256=self.proof["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"],
            expected_proof_sha256=promotion.sha256(self.files[promotion.PROOF_PATH])))
        self.proof = promotion.decode(self.files[promotion.PROOF_PATH])

    def test_role_coverage_transformation_and_public_projection(self):
        result = self.verify()
        self.assertEqual(result["qualification_protocol_version"], promotion.ROLE_PROTOCOL)
        self.assertFalse(result["provider_authenticity_verified"])
        self.assertFalse(result["claude_workspace_preparation_replayed"])
        self.assertFalse(result["claude_clean_context_replayed"])
        self.assertFalse(result["native_harness_scoring_replayed"])
        promoted = promotion.registry(self.files[promotion.REGISTRY_PATH])
        binding = next(row for row in promoted["bindings"] if row["binding_id"] == "claude-code-v3-ultimate")
        self.assertEqual(binding["qualified_roles"], list(promotion.protocol.TIERS))
        self.project()
        self.assertEqual(self.proof["schema_version"], promotion.ROLE_PUBLIC_SCHEMA)
        self.assertFalse(self.proof["full_context_blindness_verified"])
        self.assertFalse(self.verify()["native_harness_scoring_replayed"])
        for secret in ("expected_output", '"output":', "Synthetic test.", "loader_root", "session-", "scenario_claims", "rationale"):
            self.assertNotIn(secret, self.files[promotion.PROOF_PATH].decode())

    def test_codex_role_native_pair_and_distinct_probe_replayed(self):
        for delivery_mode in ("inline", "file"):
            with self.subTest(delivery_mode=delivery_mode):
                self.files, self.proof = host_fixture(delivery_mode=delivery_mode, role_protocol=True)
                self.assertTrue(self.verify()["native_harness_scoring_replayed"])
                self.project()
                self.assertEqual(self.proof["schema_version"], promotion.ROLE_PUBLIC_SCHEMA)
                self.assertFalse(self.proof["full_context_blindness_verified"])
                self.assertFalse(self.verify()["native_harness_scoring_replayed"])

    def test_role_codex_legacy_attestation_rejected(self):
        self.files, self.proof = fixture(binding_ids=["codex-v3-ultimate"], role_protocol=True)
        with self.assertRaisesRegex(ValueError, "ROLE_CODEX_HOST_SELECTION_REQUIRED"):
            self.verify()

    def test_role_package_rejects_legacy_private_and_public_proof(self):
        self.files, self.proof = fixture(binding_ids=["claude-code-v3-ultimate"], include_protocol_package=True)
        with self.assertRaisesRegex(ValueError, "ROLE_PROTOCOL_REQUIRED"):
            self.verify()
        # Genuine legacy projections still verify. Adding the protocol to the
        # frozen package cannot silently preserve that historical authority.
        self.files, self.proof = fixture(binding_ids=["claude-code-v3-ultimate"])
        self.project()
        self.assertEqual(self.verify()["result"], "verified")
        inventory = promotion.decode(self.files[promotion.INVENTORY_PATH])
        inventory["paths"].extend(promotion.protocol.PROTOCOL_FILES)
        self.files[promotion.INVENTORY_PATH] = encode(inventory)
        for path in promotion.protocol.PROTOCOL_FILES:
            self.files[path] = (promotion.ROOT / path).read_bytes()
        with self.assertRaisesRegex(ValueError, "ROLE_PROTOCOL_REQUIRED"):
            self.verify()

    def test_partial_protocol_inventory_cannot_downgrade(self):
        self.files, self.proof = fixture(binding_ids=["claude-code-v3-ultimate"], include_protocol_package=True)
        inventory = promotion.decode(self.files[promotion.INVENTORY_PATH])
        inventory["paths"].remove(promotion.protocol.SPEC_PATH)
        self.files[promotion.INVENTORY_PATH] = encode(inventory)
        with self.assertRaisesRegex(ValueError, "QUALIFICATION_PROTOCOL_PACKAGE_INCOMPLETE"):
            self.verify()

    def test_haiku_worker_null_effort_runs_and_probe_promote(self):
        self.files, self.proof = fixture(binding_ids=["claude-code-v3-worker"], role_protocol=True)
        self.assertEqual(self.verify()["binding_ids"], ["claude-code-v3-worker"])
        row = self.proof["binding_evidence"][0]
        binding = next(item for item in promotion.registry(self.files[promotion.ARCHIVE_PATH])["bindings"]
                       if item["binding_id"] == row["binding_id"])
        probe = promotion.decode(self.files[row["probe"]["path"]])
        parent = promotion.json_lines(self.files[row["probe_files"]["parent_transcript"]["path"]])
        run = row["runs"][0]
        receipt = promotion.decode(self.files[run["receipt"]["path"]])
        original_run = promotion.json_lines(self.files[run["transcript"]["path"]])
        original_child = promotion.json_lines(self.files[row["probe_files"]["child_transcript"]["path"]])
        self.assertIsNone(original_run[0]["perTurnEffort"])
        self.assertIsNone(original_child[0]["perTurnEffort"])
        for change in ("missing", "conflicting_top", "conflicting_per_turn"):
            for kind, original in (("run", original_run), ("probe", original_child)):
                with self.subTest(change=change, kind=kind):
                    rows = copy.deepcopy(original)
                    if change == "missing":
                        rows[0].pop("perTurnEffort", None)
                    if change == "conflicting_top":
                        rows[0]["effort"] = "high"
                    elif change == "conflicting_per_turn":
                        rows[0]["perTurnEffort"] = "high"
                    with self.assertRaises(ValueError):
                        if kind == "run":
                            promotion._qualification_transcript(rows, "claude_code", receipt["session_id"],
                                binding["model_id"], None, binding=binding)
                        else:
                            promotion._claude_probe(probe, parent, rows, binding["model_id"], None)

    def test_weaker_suite_forged_coverage_unknown_version_and_stale_hash_rejected(self):
        for change in ("suite", "coverage", "version", "hash", "cases"):
            with self.subTest(change=change):
                self.setUp()
                selected = self.proof["binding_evidence"][0]["qualification_protocol"]
                if change == "suite":
                    selected.update(promotion.protocol.protocol_binding({"tier": "worker_intelligence"}))
                elif change == "coverage":
                    selected["role_coverage"] = ["worker_intelligence"]
                elif change == "version":
                    selected["protocol_version"] = "agent-council.role-qualification/v0"
                elif change == "hash":
                    selected["suite_sha256"] = "0" * 64
                else:
                    selected["scenario_ids"].pop()
                with self.assertRaises(ValueError):
                    self.verify()

    def test_receipt_forgery_cannot_replace_failed_transcript_output(self):
        run = self.proof["binding_evidence"][0]["runs"][0]
        transcript = promotion.json_lines(self.files[run["transcript"]["path"]])
        response = json.loads(transcript[0]["message"]["content"][0]["text"])
        response["results"][-1]["output"] = {"forged": True}
        transcript[0]["message"]["content"][0]["text"] = json.dumps(response)
        raw = b"".join(promotion.canonical(row) + b"\n" for row in transcript)
        self.files[run["transcript"]["path"]] = raw
        run["transcript"]["sha256"] = promotion.sha256(raw)
        receipt = promotion.decode(self.files[run["receipt"]["path"]])
        receipt["transcript_sha256"] = promotion.sha256(raw)
        self.update(run["receipt"], receipt)
        with self.assertRaisesRegex(ValueError, "SCENARIO_TRANSCRIPT_MISMATCH"):
            self.verify()

    def test_mixed_pair_and_run_protocol_rejected(self):
        for location in ("pair", "receipt"):
            with self.subTest(location=location):
                self.setUp()
                row = self.proof["binding_evidence"][0]
                ref = row["pair"] if location == "pair" else row["runs"][0]["receipt"]
                value = promotion.decode(self.files[ref["path"]])
                value.pop("qualification_protocol")
                self.update(ref, value)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_suite_and_role_contract_must_match_frozen_package_bytes(self):
        for relative in (promotion.protocol.SPEC_PATH, "scripts/QualificationProtocol.py",
                         "agents/council-ultimate.md"):
            with self.subTest(relative=relative):
                self.setUp()
                self.files[relative] += b"\nforged candidate bytes\n"
                with self.assertRaises(ValueError):
                    self.verify()

    def test_frozen_role_protocol_survives_installed_upgrade(self):
        self.verify()
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory)
            for relative in (*promotion.protocol.PROTOCOL_FILES,
                             *promotion.protocol.ROLE_FILES.values(),
                             "scripts/ClaudeQualificationHarness.py"):
                path = installed / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                source = self.files.get(relative, (promotion.ROOT / relative).read_bytes())
                path.write_bytes(source + b"\ninstalled upgrade\n")
            with mock.patch.object(promotion.protocol, "ROOT", installed):
                result = self.verify()
            self.assertEqual(result["qualification_protocol_version"], promotion.ROLE_PROTOCOL)

    def test_public_nested_canaries_missing_outcomes_and_assurance_upgrade_rejected(self):
        self.project()
        original = copy.deepcopy(self.proof)
        for change in ("row", "case", "protocol", "case_set", "assurance", "coverage", "reused", "unknown_case"):
            with self.subTest(change=change):
                self.proof = copy.deepcopy(original)
                row = self.proof["binding_evidence"][0]
                if change == "row":
                    row["raw_output"] = "/private/canary"
                elif change == "case":
                    row["runs"][0]["case_outcomes"][0]["rationale"] = "private canary"
                elif change == "protocol":
                    row["qualification_protocol"]["prompt"] = "private canary"
                elif change == "case_set":
                    row["runs"][0]["case_outcomes"].pop()
                elif change == "assurance":
                    self.proof["full_context_blindness_verified"] = True
                elif change == "coverage":
                    row["qualification_protocol"]["role_coverage"] = ["ultimate_intelligence"]
                elif change == "reused":
                    row["runs"][1]["session_sha256"] = row["runs"][0]["session_sha256"]
                else:
                    row["runs"][0]["case_outcomes"][0]["scenario_id"] = "UNKNOWN"
                with self.assertRaises(ValueError):
                    self.verify()

    def test_schema_validates_private_and_public_role_proofs(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema unavailable")
        for version in (3, 4):
            if version == 4:
                self.project()
            schema = promotion.decode((promotion.ROOT / f"standards/agent-council-promotion.schema.v{version}.yaml").read_bytes())
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.validate(self.proof, schema)


if __name__ == "__main__":
    unittest.main()
