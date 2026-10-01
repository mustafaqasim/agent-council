#!/usr/bin/env python3
"""Contract tests for clean, blind, exact-model Claude qualification."""
from __future__ import annotations

import json
import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import QualificationProtocol as role_protocol
import AgentCouncilPromotion as promotion
import ClaudeQualificationHarness as harness


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "ClaudeQualificationHarness.py"
EXPECTED_CLAIMS = {
    "GFT01": ["route_r1_or_higher", "technical_implementation", "independent_operational_review", "ultimate_routing", "ultimate_final"],
    "GFT02": ["route_r3", "ultimate_design", "integration_evidence", "fault_evidence"],
    "GFT03": ["route_r3", "separate_symptom_from_cause", "no_blind_repeat"],
    "GFT04": ["reject_self_review", "closure_held", "name_independent_review_gap"],
    "GFT05": ["reject_lower_tier", "record_required_tier_unavailable", "gate_not_advanced"],
    "GFT06": ["new_candidate_cycle", "reject_stale_evidence", "fresh_review", "fresh_native_qualification"],
    "GFT07": ["reconcile_ownership", "no_duplicate_unknown_work", "link_resumption"],
    "GFT08": ["council_owns_routing", "ce_owns_method", "reuse_exact_receipts"],
    "GFT09": ["ordinary_operation_exclusion", "no_full_council", "authorization_preserved"],
    "GFT10": ["visible_dispatch_notice", "no_private_reasoning", "worker_disposition_reported"],
    "GFT11": ["reject_narrative_only", "file_backed_evidence", "exact_missing_gates"],
    "GFT12": ["packaged_default_profile", "no_unrelated_rule_inheritance", "external_authority_unchanged"],
}


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(HARNESS), *args], text=True, capture_output=True, check=False)


def synthetic_legacy_receipts(root: Path) -> list[Path]:
    """Exercise the historical v1 schema without distributing native evidence."""
    paths = []
    for index in (1, 2):
        receipt = {
            "schema_version": "agent-council.claude-qualification-receipt/v1",
            "run_id": f"native-forward-run-{index}",
            "session_id": str(uuid.UUID(int=index)),
            "requested_model_id": "claude-opus-5-5",
            "actual_model_id": "claude-opus-5-5",
            "candidate_sha256": "a" * 64,
            "evaluation_bundle_sha256": "b" * 64,
            "transcript_sha256": str(index) * 64,
            "clean_context": True,
            "blind": True,
            "scenario_results": [
                {"scenario_id": scenario, "status": "passed", "missing_claims": [],
                 "additional_claims": [], "disallowed_additional_claims": []}
                for scenario in EXPECTED_CLAIMS
            ],
            "result": "passed",
        }
        path = root / f"synthetic-legacy-receipt-{index}.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        paths.append(path)
    return paths


def transcript(path: Path, model: str, result: dict[str, object], session_id: str, workspace: Path, *, run_id: str = "native-forward-run-1", effort: str | None = "high", include_native_records: bool = True, prior_prompt: bool = False, prohibited_tool: bool = False, external_path: bool = False, failed_read: bool = False) -> None:
    resolved = workspace.resolve()
    rows: list[dict[str, object]] = []
    if include_native_records:
        name = f"Agent Council {run_id}"
        rows.extend([
            {"type": "custom-title", "customTitle": name, "sessionId": session_id},
            {"type": "agent-name", "agentName": name, "sessionId": session_id},
            {"type": "mode", "mode": "normal", "sessionId": session_id},
            {"type": "permission-mode", "permissionMode": "auto", "sessionId": session_id},
        ])
    if prior_prompt:
        rows.append({"type": "user", "parentUuid": None, "isSidechain": False, "entrypoint": "cli", "promptSource": "typed", "origin": {"kind": "human"}, "sessionId": session_id, "cwd": str(resolved), "message": {"role": "user", "content": "Earlier conversation"}})
    rows.append({"type": "user", "parentUuid": None, "isSidechain": False, "entrypoint": "cli", "promptSource": "typed", "origin": {"kind": "human"}, "sessionId": session_id, "cwd": str(resolved), "message": {"role": "user", "content": harness.PROMPT}})
    reads = [resolved / "evaluator-instructions.md", resolved / "requests.json", *sorted(item for item in (resolved / "candidate").rglob("*") if item.is_file())]
    effort_fields = {"perTurnEffort": None} if effort is None else {"effort": effort, "perTurnEffort": None}
    for index, read_path in enumerate(reads):
        tool_name = "Write" if prohibited_tool and index == 0 else "Read"
        selected_path = Path("/tmp/outside-qualification") if external_path and index == 0 else read_path
        tool_id = f"tool-{index}"
        rows.append({"type": "assistant", "isSidechain": False, "entrypoint": "cli", **effort_fields, "sessionId": session_id, "cwd": str(resolved), "message": {"model": model, "content": [{"type": "tool_use", "id": tool_id, "name": tool_name, "input": {"file_path": str(selected_path)}}]}})
        rows.append({"type": "user", "isSidechain": False, "entrypoint": "cli", "sessionId": session_id, "cwd": str(resolved), "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "denied" if failed_read and index == 0 else "bounded", "is_error": failed_read and index == 0}]}})
    rows.append({"type": "assistant", "isSidechain": False, "entrypoint": "cli", **effort_fields, "sessionId": session_id, "cwd": str(resolved), "message": {"model": model, "content": [{"type": "text", "text": json.dumps(result)}]}})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_current_identity() -> None:
    spec = importlib.util.spec_from_file_location("qualification_harness", HARNESS)
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    require(hasattr(harness, "current_behavioral_identity"), "current behavioral identity API is missing")
    legacy_paths = (
        "skills/agent-council/SKILL.md",
        "skills/agent-council/references/model-adapters.yaml",
        "skills/agent-council/references/project-profiles.yaml",
        "skills/agent-council/references/compound-engineering.yaml",
        "profiles/default.yaml",
        "standards/agent-council-standard.v2.yaml",
    )
    require(harness.CANDIDATE_FILES == legacy_paths, "legacy qualification inventory changed")
    require(harness.candidate_digest() == harness.named_file_digest([(name, ROOT / name) for name in legacy_paths]), "legacy candidate digest semantics changed")
    require(hasattr(harness, "current_release_binding"), "current qualification binding is missing")
    binding = harness.current_release_binding()
    require(binding["behavioral_identity"] == harness.current_behavioral_identity(), "current binding omits behavior identity")
    require(len(binding["eval_suite_sha256"]) == 64, "current binding omits eval suite digest")
    with tempfile.TemporaryDirectory(prefix="current-qualification-") as temporary:
        workspace = Path(temporary) / "workspace"
        args = argparse.Namespace(output=workspace, run_id="native-forward-run-1", session_id=str(uuid.uuid4()), model_id="claude-opus-5-5", effort="medium", current=True)
        manifest = harness.prepare(args)
        require(manifest["schema_version"].endswith("/v2") and manifest["release_binding"] == binding, "current preparation is not bound to this release")
        source_skill = ROOT / "skills/agent-council"
        copied_skill = workspace / "candidate/skills/agent-council"
        for relative in harness.CURRENT_CANDIDATE_FILES:
            require((workspace / "candidate" / relative).read_bytes() == (ROOT / relative).read_bytes(), "current workspace changes package path or bytes: " + relative)
        for relative in ("references/lightweight-routing.yaml", "references/governed-workflow.yaml", "references/project-profiles.yaml"):
            require((copied_skill / relative).read_bytes() == (source_skill / relative).read_bytes(), "current workspace breaks skill reference: " + relative)
        governed = (source_skill / "references/governed-workflow.yaml").read_text()
        profile_match = re.search(r"(\.\./\.\./profiles/default\.yaml) relative to the skill directory", governed)
        require(profile_match is not None, "governed profile path must resolve from the skill directory")
        profile_path = profile_match.group(1)
        require((source_skill / profile_path).resolve() == ROOT / "profiles/default.yaml", "packaged governed profile path does not resolve")
        require((copied_skill / profile_path).resolve() == (workspace / "candidate/profiles/default.yaml").resolve(), "current workspace breaks governed profile path")
        require("candidate/skills/agent-council/SKILL.md" in (workspace / "evaluator-instructions.md").read_text(), "current evaluator points to a flattened skill")
        response = {"schema_version": "agent-council.claude-native-response/v1", "results": [{"scenario_id": key, "claims": value} for key, value in EXPECTED_CLAIMS.items()]}
        response["results"][9]["claims"] = [*response["results"][9]["claims"], "ultimate_design", "technical_implementation"]
        source = Path(temporary) / "native.jsonl"
        transcript(source, "claude-opus-5-5", response, args.session_id, workspace, effort="medium")
        score_args = argparse.Namespace(workspace=workspace, transcript=source, receipt=Path(temporary) / "receipt.json")
        receipt = harness.score(score_args)
        require(receipt["schema_version"].endswith("/v2") and receipt["release_binding"] == binding, "current scoring loses release binding")
        gft10 = next(item for item in receipt["scenario_results"] if item["scenario_id"] == "GFT10")
        require(gft10["status"] == "passed" and gft10["additional_claims"] == ["technical_implementation", "ultimate_design"], "current scoring rejects permitted GFT10 claims")
        original_transcript = source.read_text()
        rows = [json.loads(line) for line in original_transcript.splitlines()]
        require(len(promotion._qualification_transcript(rows, "claude_code", args.session_id,
                    args.model_id, "medium")) == len(EXPECTED_CLAIMS), "promotion rejects scored transcript")
        native_tail = {"parentUuid": rows[-1].get("uuid", "assistant-final"), "isSidechain": False,
                       "type": "system", "subtype": "turn_duration", "durationMs": 1234,
                       "messageCount": len(rows), "timestamp": "2026-10-01T00:00:00.000Z",
                       "uuid": "terminal-duration", "isMeta": False, "userType": "external",
                       "entrypoint": "cli", "cwd": str(workspace.resolve()),
                       "sessionId": args.session_id, "version": "2.1.286", "gitBranch": "test"}
        rows[-1]["uuid"] = native_tail["parentUuid"]
        rows[-1]["version"] = native_tail["version"]
        source.write_text("".join(json.dumps(row) + "\n" for row in [*rows, native_tail]))
        harness.score(score_args)
        require(len(promotion._qualification_transcript([*rows, native_tail], "claude_code", args.session_id,
                    args.model_id, "medium")) == len(EXPECTED_CLAIMS), "promotion rejects native terminal duration")
        ui_tail = [
            {"type": "last-prompt", "lastPrompt": harness.PROMPT, "leafUuid": native_tail["uuid"], "sessionId": args.session_id},
            {"type": "custom-title", "customTitle": f"Agent Council {args.run_id}", "sessionId": args.session_id},
            {"type": "agent-name", "agentName": f"Agent Council {args.run_id}", "sessionId": args.session_id},
            {"type": "mode", "mode": "normal", "sessionId": args.session_id},
            {"type": "permission-mode", "permissionMode": "auto", "sessionId": args.session_id},
            {"type": "atis-latch", "atis": "", "sessionId": args.session_id},
        ]
        accepted_tail = [*rows, native_tail, *ui_tail]
        source.write_text("".join(json.dumps(row) + "\n" for row in accepted_tail))
        harness.score(score_args)
        require(len(promotion._qualification_transcript(accepted_tail, "claude_code", args.session_id,
                    args.model_id, "medium")) == len(EXPECTED_CLAIMS), "promotion rejects native UI metadata")
        default_rows = [
            {**row, "permissionMode": "default"} if row.get("type") == "permission-mode" else row
            for row in rows
        ]
        default_tail = [
            {**row, "permissionMode": "default"} if row.get("type") == "permission-mode" else row
            for row in ui_tail
        ]
        default_transcript = [*default_rows, native_tail, *default_tail]
        source.write_text("".join(json.dumps(row) + "\n" for row in default_transcript))
        harness.score(score_args)
        require(len(promotion._qualification_transcript(default_transcript, "claude_code", args.session_id,
                    args.model_id, "medium")) == len(EXPECTED_CLAIMS), "promotion rejects matching default permission metadata")
        bad_ui_tails = (
            ("duplicate UI row", [*ui_tail, ui_tail[-1]]),
            ("out-of-order UI row", [ui_tail[1], ui_tail[0], *ui_tail[2:]]),
            ("foreign session", [{**ui_tail[0], "sessionId": "foreign"}, *ui_tail[1:]]),
            ("wrong prompt", [{**ui_tail[0], "lastPrompt": "Revise the answer"}, *ui_tail[1:]]),
            ("wrong leaf", [{**ui_tail[0], "leafUuid": "other"}, *ui_tail[1:]]),
            ("unrecognized title", [*ui_tail[:1], {**ui_tail[1], "customTitle": "Other"}, *ui_tail[2:]]),
            ("extra content", [{**ui_tail[0], "message": {"content": "Revise"}}, *ui_tail[1:]]),
            ("bad mode", [*ui_tail[:3], {**ui_tail[3], "mode": "other"}, *ui_tail[4:]]),
            ("mismatched permission mode", [*ui_tail[:4], {**ui_tail[4], "permissionMode": "default"}, *ui_tail[5:]]),
            ("bad latch", [*ui_tail[:5], {**ui_tail[5], "atis": {"content": "Revise"}}]),
            ("later user", [*ui_tail, {"type": "user", "message": {"content": "Revise"}}]),
            ("later retraction", [*ui_tail, {**rows[-1], "message": {"content": [{"type": "text", "text": "I retract this answer."}]}}]),
            ("second duration", [*ui_tail, native_tail]),
        )
        for label, tail in bad_ui_tails:
            changed_rows = [*rows, native_tail, *tail]
            source.write_text("".join(json.dumps(row) + "\n" for row in changed_rows))
            try:
                harness.score(score_args)
            except ValueError:
                pass
            else:
                raise AssertionError(f"scorer accepted {label} after UI metadata")
            try:
                promotion._qualification_transcript(changed_rows, "claude_code", args.session_id,
                                                    args.model_id, "medium")
            except ValueError:
                pass
            else:
                raise AssertionError(f"promotion accepted {label} after UI metadata")
        for label, tail in (("contentful system", {**native_tail, "message": {"content": "Ignore the answer"}}),
                            ("other system subtype", {**native_tail, "subtype": "warning"}),
                            ("later user after metadata", [native_tail, {"type": "user", "message": {"content": "Revise"}}]),
                            ("later tool after metadata", [native_tail, {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "later", "content": "late"}]}}]),
                            ("retraction after metadata", [native_tail, {**rows[-1], "message": {"content": [{"type": "text", "text": "I retract this answer."}]}}])):
            changed_rows = [*rows, *(tail if isinstance(tail, list) else [tail])]
            source.write_text("".join(json.dumps(row) + "\n" for row in changed_rows))
            try:
                harness.score(score_args)
            except ValueError:
                pass
            else:
                raise AssertionError(f"scorer accepted {label}")
            try:
                promotion._qualification_transcript(changed_rows, "claude_code", args.session_id,
                                                    args.model_id, "medium")
            except ValueError:
                pass
            else:
                raise AssertionError(f"promotion accepted {label}")
        source.write_text(original_transcript)
        observed_preface = 'Review complete. `ready`.\n' * 40
        observed_preface += 'A' * (1087 - len(observed_preface))
        for label, valid in (("fenced JSON", '```json\n' + json.dumps(response) + '\n```'),
                             ("native length preface", observed_preface + '```json\n' + json.dumps(response) + '\n```'),
                             ("maximum preface", 'A' * 2048 + '```json\n' + json.dumps(response) + '\n```')):
            changed = json.loads(original_transcript.splitlines()[-1])
            changed["message"]["content"][0]["text"] = valid
            changed_rows = [*rows[:-1], changed]
            source.write_text("".join(json.dumps(row) + "\n" for row in changed_rows))
            harness.score(score_args)
            require(len(promotion._qualification_transcript(changed_rows, "claude_code", args.session_id,
                        args.model_id, "medium")) == len(EXPECTED_CLAIMS), f"promotion rejects {label}")
        for label, invalid in (("malformed", '{"broken":}'),
                               ("duplicate", '{"duplicate":1,"duplicate":2}'),
                               ("fenced duplicate keys", '```json\n{"duplicate":1,"duplicate":2}\n```'),
                               ("fenced duplicate objects", '```json\n' + json.dumps(response) + '\n' + json.dumps(response) + '\n```'),
                               ("duplicate fences", '```json\n' + json.dumps(response) + '\n```\n```json\n{}\n```'),
                               ("trailing prose", '```json\n' + json.dumps(response) + '\n```\nI retract this answer.'),
                               ("oversized preface", 'A' * 2049 + '```json\n' + json.dumps(response) + '\n```'),
                               ("object in preface", '{"alternate":true}\n```json\n' + json.dumps(response) + '\n```'),
                               ("earlier fence", '```text\nprior answer\n```\n```json\n' + json.dumps(response) + '\n```'),
                               ("earlier json fence", '```json\n{}\n```\n```json\n' + json.dumps(response) + '\n```'),
                               ("malformed fence", '```JSON\n' + json.dumps(response) + '\n```'),
                               ("prefix prose", 'Answer: ' + json.dumps(response)),
                               ("suffix prose", json.dumps(response) + '\nI retract this answer.'),
                               ("two objects", json.dumps(response) + '\n' + json.dumps(response))):
            changed = json.loads(original_transcript.splitlines()[-1])
            changed["message"]["content"][0]["text"] = invalid
            changed_rows = [*rows[:-1], changed]
            source.write_text("".join(json.dumps(row) + "\n" for row in changed_rows))
            try:
                harness.score(score_args)
            except ValueError:
                pass
            else:
                raise AssertionError(f"scorer accepted {label} response")
            try:
                promotion._qualification_transcript(changed_rows, "claude_code", args.session_id,
                                                    args.model_id, "medium")
            except ValueError:
                pass
            else:
                raise AssertionError(f"promotion accepted {label} response")
        for label, extra in (
            ("retraction", {**rows[-1], "message": {**rows[-1]["message"], "content": [{"type": "text", "text": "I retract this answer."}]}}),
            ("empty assistant", {**rows[-1], "message": {**rows[-1]["message"], "content": []}}),
            ("later user", {"type": "user", "sessionId": args.session_id, "cwd": str(workspace), "message": {"role": "user", "content": "Please revise."}}),
            ("later metadata", {"type": "system", "sessionId": args.session_id, "cwd": str(workspace)}),
        ):
            changed_rows = [*rows, extra]
            source.write_text("".join(json.dumps(row) + "\n" for row in changed_rows))
            try:
                harness.score(score_args)
            except ValueError:
                pass
            else:
                raise AssertionError(f"scorer accepted {label} after response")
            try:
                promotion._qualification_transcript(changed_rows, "claude_code", args.session_id,
                                                    args.model_id, "medium")
            except ValueError:
                pass
            else:
                raise AssertionError(f"promotion accepted {label} after response")
        mixed = {**rows[-1], "message": {**rows[-1]["message"], "content": [
            *rows[-1]["message"]["content"], {"type": "tool_use", "id": "late-tool", "name": "Read", "input": {"file_path": str(workspace / "requests.json")}}]}}
        mixed_rows = [*rows[:-1], mixed]
        source.write_text("".join(json.dumps(row) + "\n" for row in mixed_rows))
        for check in (lambda: harness.score(score_args),
                      lambda: promotion._qualification_transcript(mixed_rows, "claude_code", args.session_id,
                                                                 args.model_id, "medium")):
            try:
                check()
            except ValueError:
                pass
            else:
                raise AssertionError("qualification accepted answer with tool output")
        source.write_text(original_transcript)
        unread_ids = {item["id"] for row in rows for item in row.get("message", {}).get("content", []) if isinstance(item, dict) and item.get("type") == "tool_use" and item.get("input", {}).get("file_path", "").endswith("references/lightweight-routing.yaml")}
        filtered = [row for row in rows if not any(isinstance(item, dict) and (item.get("id") in unread_ids or item.get("tool_use_id") in unread_ids) for item in row.get("message", {}).get("content", []))]
        source.write_text("".join(json.dumps(row) + "\n" for row in filtered))
        try:
            harness.score(score_args)
        except ValueError as error:
            require("REQUIRED_READS_MISSING" in str(error), "missing route read rejected for wrong reason")
        else:
            raise AssertionError("current qualification accepted unread route policy")
        source.write_text(original_transcript)
        second_workspace = Path(temporary) / "second"
        second_args = argparse.Namespace(output=second_workspace, run_id="native-forward-run-2", session_id=str(uuid.uuid4()), model_id="claude-opus-5-5", effort="medium", current=True)
        harness.prepare(second_args)
        second_transcript = Path(temporary) / "second.jsonl"
        transcript(second_transcript, "claude-opus-5-5", response, second_args.session_id, second_workspace, run_id="native-forward-run-2", effort="medium")
        second_receipt = Path(temporary) / "second-receipt.json"
        harness.score(argparse.Namespace(workspace=second_workspace, transcript=second_transcript, receipt=second_receipt))
        pair = harness.validate_pair(argparse.Namespace(receipt=[score_args.receipt, second_receipt], require_current=True))
        require(pair["schema_version"].endswith("/v2") and pair["release_binding"] == binding, "current pair loses release binding")
        for label, effort in (("missing", None), ("invented", "ultra"), ("null", None), ("object", {"claimed": "high"})):
            synthetic_paths = []
            for index, original in enumerate((receipt, json.loads(second_receipt.read_text(encoding="utf-8"))), start=1):
                synthetic = dict(original)
                if label == "missing":
                    synthetic.pop("requested_effort")
                    synthetic.pop("actual_effort")
                else:
                    synthetic["requested_effort"] = effort
                    synthetic["actual_effort"] = effort
                synthetic_path = Path(temporary) / f"{label}-effort-receipt-{index}.json"
                synthetic_path.write_text(json.dumps(synthetic), encoding="utf-8")
                synthetic_paths.append(synthetic_path)
            try:
                harness.validate_pair(argparse.Namespace(receipt=synthetic_paths, require_current=True))
            except ValueError as error:
                require("QUALIFICATION_RECEIPT_INVALID" in str(error), f"{label} effort rejected for wrong reason: {error}")
            else:
                raise AssertionError(f"current qualification accepted {label} effort")
        historical = synthetic_legacy_receipts(Path(temporary))
        try:
            harness.validate_pair(argparse.Namespace(receipt=historical, require_current=True))
        except ValueError as error:
            require("CURRENT_EVIDENCE_REQUIRED" in str(error), "historical pair rejected for wrong reason")
        else:
            raise AssertionError("historical evidence accepted as current release")
        manifest["release_binding"]["eval_suite_sha256"] = "0" * 64
        (workspace / harness.MANIFEST).write_text(json.dumps(manifest))
        try:
            harness.score(score_args)
        except ValueError as error:
            require("RELEASE_CHANGED" in str(error), "stale release rejected for wrong reason")
        else:
            raise AssertionError("stale current release binding accepted")
    with tempfile.TemporaryDirectory(prefix="agent-council-identity-") as temporary:
        root = Path(temporary) / "plugin"
        root.mkdir()
        (root / "a.txt").write_text("first", encoding="utf-8")
        (root / "b.txt").write_text("second", encoding="utf-8")
        inventory = root / "inventory.json"
        declaration = {"schema_version": "agent-council.behavioral-inventory/v1", "identity_version": "current/v1", "paths": ["b.txt", "a.txt"]}

        def identify(value: object) -> dict[str, object]:
            inventory.write_text(json.dumps(value), encoding="utf-8")
            return harness.current_behavioral_identity(root, "inventory.json")

        def refused(value: object, code: str) -> None:
            try:
                identify(value)
            except ValueError as error:
                require(code in str(error), f"unexpected inventory rejection: {error}")
            else:
                raise AssertionError(f"invalid inventory was accepted: {value}")

        identity = identify(declaration)
        require(identity["paths"] == ["a.txt", "b.txt"], "identity paths are not canonical")
        require(identity == identify({**declaration, "paths": ["a.txt", "b.txt"]}), "inventory ordering changes identity")
        (root / "untracked.txt").write_text("irrelevant", encoding="utf-8")
        require(identity == identify(declaration), "undeclared file changes identity")
        require(identity["behavioral_sha256"] != identify({**declaration, "paths": [*declaration["paths"], "untracked.txt"]})["behavioral_sha256"], "new declared behavior does not change identity")
        (root / "b.txt").write_text("changed", encoding="utf-8")
        require(identity["behavioral_sha256"] != identify(declaration)["behavioral_sha256"], "behavioral file change does not change identity")
        (root / "b.txt").write_text("second", encoding="utf-8")
        require(identity["behavioral_sha256"] != identify({**declaration, "identity_version": "current/v2"})["behavioral_sha256"], "identity version is not bound to digest")
        require(identity["behavioral_sha256"] != identify({**declaration, "paths": ["a.txt"]})["behavioral_sha256"], "inventory membership is not bound to digest")
        for paths in (["a.txt", "a.txt"], []):
            refused({**declaration, "paths": paths}, "INVENTORY_PATHS_INVALID")
        for name in ("../outside", "/tmp/outside", "a/../a.txt", "./a.txt", "a//b.txt", "C:\\outside", "a\\b.txt", "a.txt\n"):
            refused({**declaration, "paths": [name]}, "INVENTORY_PATH_UNSAFE")
        for name in ("missing.txt", "directory"):
            (root / "directory").mkdir(exist_ok=True)
            refused({**declaration, "paths": [name]}, "INVENTORY_FILE_MISSING")
        (root / "alias.txt").symlink_to(root / "a.txt")
        (root / "outside.txt").symlink_to(Path(temporary) / "outside.txt")
        (root / "linked-dir").symlink_to(root, target_is_directory=True)
        for name in ("alias.txt", "outside.txt", "linked-dir/a.txt"):
            refused({**declaration, "paths": [name]}, "INVENTORY_PATH_UNSAFE")
        os.link(root / "a.txt", root / "hardlink.txt")
        refused({**declaration, "paths": ["a.txt", "hardlink.txt"]}, "INVENTORY_PATHS_INVALID")
        refused({**declaration, "paths": ["inventory.json"]}, "INVENTORY_SELF_REFERENCE")
        for value in ([], {**declaration, "schema_version": "unknown"}, {**declaration, "identity_version": ""}, {**declaration, "extra": True}, {**declaration, "paths": [1]}):
            refused(value, "INVENTORY")
        inventory.write_text('{"schema_version":"one","schema_version":"two"}', encoding="utf-8")
        try:
            harness.current_behavioral_identity(root, "inventory.json")
        except ValueError as error:
            require("INVENTORY_DUPLICATE_KEY" in str(error), "duplicate JSON key rejected for unexpected reason")
        else:
            raise AssertionError("duplicate inventory keys were accepted")
        inventory.unlink()
        inventory.symlink_to(root / "a.txt")
        try:
            harness.current_behavioral_identity(root, "inventory.json")
        except ValueError as error:
            require("INVENTORY_PATH_UNSAFE" in str(error), "inventory symlink rejected for unexpected reason")
        else:
            raise AssertionError("symlinked inventory was accepted")
    current = run("current-identity")
    require(current.returncode == 0, f"current identity command failed: {current.stdout} {current.stderr}")
    packaged = json.loads(current.stdout)
    require(set(legacy_paths) <= set(packaged["paths"]), "current inventory omits legacy behavior")
    require({"hooks/hooks.json", "hooks/agent-council-routing.sh", "codex/routing-directive.md", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "scripts/ClaudeQualificationHarness.py"} <= set(packaged["paths"]), "current inventory omits activation or identity behavior")
    with tempfile.TemporaryDirectory(prefix="agent-council-legacy-schema-") as temporary:
        historical = synthetic_legacy_receipts(Path(temporary))
        pair = run("validate-pair", "--receipt", str(historical[0]), "--receipt", str(historical[1]))
        require(pair.returncode == 0, f"legacy receipt validation changed: {pair.stdout} {pair.stderr}")
        result = json.loads(pair.stdout)
        require(result["schema_version"] == "agent-council.claude-qualification-pair/v1" and result["candidate_sha256"] == "a" * 64 and result["effort"] == "high", "legacy receipt schema or default effort changed")
        for field, value, expected_error in (
            ("session_id", str(uuid.UUID(int=1)), "CONTEXTS_NOT_FRESH"),
            ("candidate_sha256", "c" * 64, "CANDIDATE_MISMATCH"),
            ("evaluation_bundle_sha256", "c" * 64, "CANDIDATE_MISMATCH"),
            ("actual_model_id", "wrong-model", "MODEL_IDENTITY_MISMATCH"),
            ("scenario_results", [], "RECEIPT_INVALID"),
            ("blind", False, "RUN_FAILED"),
        ):
            historical = synthetic_legacy_receipts(Path(temporary))
            altered = json.loads(historical[1].read_text())
            altered[field] = value
            historical[1].write_text(json.dumps(altered))
            rejected = run("validate-pair", "--receipt", str(historical[0]), "--receipt", str(historical[1]))
            require(rejected.returncode != 0 and expected_error in rejected.stdout, f"legacy validation accepted invalid {field}: {rejected.stdout}")


def _test_v3_bindings_candidate() -> None:
    spec = importlib.util.spec_from_file_location("qualification_harness_v3", HARNESS)
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    response = {"schema_version": "agent-council.claude-native-response/v1", "results": [{"scenario_id": key, "claims": value} for key, value in EXPECTED_CLAIMS.items()]}
    expected = {
        "claude-code-v3-ultimate": ("claude-opus-5-5", "high"),
        "claude-code-v3-operational": ("claude-opus-5-5", "medium"),
        "claude-code-v3-technical": ("claude-opus-5-5", "medium"),
        "claude-code-v3-worker": ("claude-haiku-4-5-20251001", None),
    }
    with tempfile.TemporaryDirectory(prefix="agent-council-v3-qualification-") as temporary:
        root = Path(temporary)
        for binding_id, (model, effort) in expected.items():
            binding = next(item for item in json.loads((ROOT / "standards/agent-model-registry.v3.yaml").read_text())["bindings"] if item["binding_id"] == binding_id)
            response = {"schema_version": role_protocol.RESPONSE, "results": [
                {"scenario_id": case["scenario_id"], "output": case["expected_output"], "actions": []}
                for case in role_protocol.suite_cases(binding)]}
            receipts = []
            workspaces = []
            for index in (1, 2):
                workspace = root / binding_id / f"run-{index}"
                session_id = str(uuid.uuid4())
                prepared = run("prepare", "--output", str(workspace), "--run-id", f"native-forward-run-{index}", "--session-id", session_id, "--binding-id", binding_id)
                require(prepared.returncode == 0, f"v3 prepare failed: {prepared.stdout}")
                manifest = json.loads(prepared.stdout)
                require(manifest["schema_version"].endswith("/v3") and manifest["requested_model_id"] == model and "requested_effort" in manifest and manifest["requested_effort"] == effort, "v3 binding was not derived")
                v3_files = (
                    "standards/agent-model-registry.v3.yaml",
                    "standards/agent-model-registry.schema.v3.yaml",
                    "standards/model-qualifications/provider-catalog-refresh.v3.yaml",
                    "agents/council-ultimate.md",
                    "agents/council-operational.md",
                    "agents/council-technical.md",
                    "agents/council-worker.md",
                )
                for relative in v3_files:
                    require((workspace / "candidate" / relative).read_bytes() == (ROOT / relative).read_bytes(), "v3 workspace omitted or changed " + relative)
                instructions = (workspace / "evaluator-instructions.md").read_text()
                require("candidate/agents" in instructions and "candidate/standards" in instructions, "v3 evaluator omits binding policy reads")
                require("bare raw JSON object" in instructions and "no Markdown code fences, preamble, or suffix" in instructions, "v3 evaluator omits raw JSON output rule")
                require("bare raw JSON object" in harness.PROMPT and "Markdown code fences" in harness.PROMPT and "preamble or suffix" in harness.PROMPT, "Claude launch prompt omits raw JSON output rule")
                listed_reads = re.findall(r"^- (candidate/[^\n]+)$", instructions, re.MULTILINE)
                copied_reads = {path.relative_to(workspace).as_posix() for path in (workspace / "candidate").rglob("*") if path.is_file()}
                require(set(listed_reads) == copied_reads and len(listed_reads) == len(copied_reads), "v3 evaluator does not enumerate every copied candidate file exactly once")
                require("candidate/standards/agent-model-registry.schema.v3.yaml" in listed_reads and "candidate/standards/model-qualifications/provider-catalog-refresh.v3.yaml" in listed_reads, "v3 evaluator omits the previously skipped schema or nested catalog file")
                command = manifest["launch_command"]
                require(("--effort" in command) == (effort is not None) and "--model" in command and command[command.index("--model") + 1] == model and "--print" not in command and "-p" not in command, "v3 launch does not match binding or interactive mode")
                require(command.count("--disallowedTools") == 1 and command[command.index("--disallowedTools") + 1] == "EndConversation", "v3 launch does not deny EndConversation")
                require(not any(path.name == "forward-tests.yaml" for path in workspace.rglob("*")) and '"expected"' not in "\n".join(path.read_text() for path in workspace.rglob("*") if path.is_file()), "v3 workspace exposed answer key")
                source = root / f"{binding_id}-{index}.jsonl"
                receipt_path = root / f"{binding_id}-{index}.json"
                transcript(source, model, response, session_id, workspace, run_id=f"native-forward-run-{index}", effort=effort)
                scored = run("score", "--workspace", str(workspace), "--transcript", str(source), "--receipt", str(receipt_path))
                require(scored.returncode == 0, f"v3 score failed: {scored.stdout}")
                receipt = json.loads(receipt_path.read_text())
                require(receipt["binding_id"] == binding_id and receipt["actual_effort"] == effort and receipt["eval_suite_sha256"] == manifest["eval_suite_sha256"], "v3 receipt lost binding evidence")
                receipts.append(receipt_path)
                workspaces.append((workspace, source, manifest))
            pair = run("validate-pair", "--receipt", str(receipts[0]), "--receipt", str(receipts[1]), "--require-current")
            require(pair.returncode == 0 and json.loads(pair.stdout)["binding_id"] == binding_id, f"v3 pair failed: {pair.stdout}")
            legacy_receipts = []
            for index, receipt_path in enumerate(receipts, start=1):
                legacy = json.loads(receipt_path.read_text())
                legacy.pop("qualification_protocol")
                legacy.pop("response")
                legacy_path = root / f"{binding_id}-legacy-{index}.json"
                legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
                legacy_receipts.append(legacy_path)
            legacy_pair = run("validate-pair", "--receipt", str(legacy_receipts[0]), "--receipt", str(legacy_receipts[1]), "--require-current")
            require(legacy_pair.returncode != 0 and "QUALIFICATION_RECEIPT_INVALID" in legacy_pair.stdout,
                    "v3 pair accepted receipts without the role protocol")
            workspace, source, manifest = workspaces[0]
            launch_path = workspace / "qualification-run.json"
            launch_without_deny = json.loads(launch_path.read_text(encoding="utf-8"))
            original_launch = launch_without_deny["launch_command"]
            deny_index = original_launch.index("--disallowedTools")
            launch_without_deny["launch_command"] = original_launch[:deny_index] + original_launch[deny_index + 2:]
            launch_path.write_text(json.dumps(launch_without_deny), encoding="utf-8")
            denied_launch = run("score", "--workspace", str(workspace), "--transcript", str(source), "--receipt", str(root / "missing-endconversation-deny.json"))
            require(denied_launch.returncode != 0 and "QUALIFICATION_LAUNCH_COMMAND_INVALID" in denied_launch.stdout, "v3 accepted a launch command without EndConversation denial")
            launch_without_deny["launch_command"] = original_launch
            launch_path.write_text(json.dumps(launch_without_deny), encoding="utf-8")
            original_digest = harness.workspace_candidate_digest(workspace, True, True)
            require(original_digest == manifest["candidate_sha256"], "v3 candidate digest omits copied policy")
            for relative in ("standards/agent-model-registry.v3.yaml", "agents/council-ultimate.md"):
                candidate_file = workspace / "candidate" / relative
                original = candidate_file.read_bytes()
                candidate_file.write_bytes(original + b"\n# changed candidate\n")
                require(harness.workspace_candidate_digest(workspace, True, True) != original_digest, "v3 candidate digest ignores " + relative)
                changed = run("score", "--workspace", str(workspace), "--transcript", str(source), "--receipt", str(root / "changed-v3.json"))
                require(changed.returncode != 0 and "QUALIFICATION_CANDIDATE_CHANGED" in changed.stdout, "v3 accepted stale manifest after changing " + relative)
                candidate_file.write_bytes(original)
            rows = [json.loads(line) for line in source.read_text().splitlines()]
            first_assistant = next(row for row in rows if row.get("type") == "assistant")
            contradictory = [dict(row) for row in rows]
            contradictory_assistant = next(row for row in contradictory if row.get("type") == "assistant")
            if effort is None:
                contradictory_assistant["effort"] = "high"
            else:
                contradictory_assistant["perTurnEffort"] = "low"
            contradictory_path = root / f"{binding_id}-contradictory-effort.jsonl"
            contradictory_path.write_text("".join(json.dumps(row) + "\n" for row in contradictory))
            contradictory_result = run("score", "--workspace", str(workspace), "--transcript", str(contradictory_path), "--receipt", str(root / "contradictory-effort.json"))
            require(contradictory_result.returncode != 0 and "TRANSCRIPT_BINDING_MISMATCH" in contradictory_result.stdout, "v3 accepted contradictory effort evidence")
            require(("effort" in first_assistant) == (effort is not None) and first_assistant.get("perTurnEffort") is None, "v3 fixture does not reflect current native effort fields")
            if binding_id == "claude-code-v3-operational":
                for relative in (
                    "standards/agent-model-registry.v3.yaml",
                    "standards/agent-model-registry.schema.v3.yaml",
                    "standards/model-qualifications/provider-catalog-refresh.v3.yaml",
                ):
                    unread_path = str((workspace / "candidate" / relative).resolve())
                    unread_ids = {item["id"] for row in rows for item in row.get("message", {}).get("content", []) if isinstance(item, dict) and item.get("type") == "tool_use" and item.get("input", {}).get("file_path") == unread_path}
                    require(len(unread_ids) == 1, "missing-read fixture does not target exactly one file")
                    filtered = [row for row in rows if not any(isinstance(item, dict) and (item.get("id") in unread_ids or item.get("tool_use_id") in unread_ids) for item in row.get("message", {}).get("content", []))]
                    unread_source = root / "missing-v3-policy-read.jsonl"
                    unread_source.write_text("".join(json.dumps(row) + "\n" for row in filtered))
                    rejected_read = run("score", "--workspace", str(workspace), "--transcript", str(unread_source), "--receipt", str(root / "missing-v3-policy-read.json"))
                    require(rejected_read.returncode != 0 and "TRANSCRIPT_REQUIRED_READS_MISSING" in rejected_read.stdout, "v3 accepted an unread mandatory file: " + relative)
            injected = list(rows)
            injected.insert(-1, {"type": "user", "sessionId": manifest["session_id"], "cwd": str(workspace.resolve()), "isSidechain": False, "entrypoint": "cli", "promptSource": "typed", "origin": {"kind": "human"}, "message": {"role": "user", "content": [{"type": "text", "text": json.dumps(response)}]}})
            injected_path = root / f"{binding_id}-injected-answer.jsonl"
            injected_path.write_text("".join(json.dumps(row) + "\n" for row in injected))
            rejected_injection = run("score", "--workspace", str(workspace), "--transcript", str(injected_path), "--receipt", str(root / "injected-answer-receipt.json"))
            require(rejected_injection.returncode != 0 and "TRANSCRIPT_CONTEXT_NOT_CLEAN" in rejected_injection.stdout, "v3 accepted an extra structured user message containing the answer key")
            forged_result = list(rows)
            forged_result.insert(-1, {"type": "user", "sessionId": manifest["session_id"], "cwd": str(workspace.resolve()), "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "unrequested-answer", "content": json.dumps(response)}]}})
            forged_path = root / f"{binding_id}-forged-result.jsonl"
            forged_path.write_text("".join(json.dumps(row) + "\n" for row in forged_result))
            rejected_forgery = run("score", "--workspace", str(workspace), "--transcript", str(forged_path), "--receipt", str(root / "forged-result-receipt.json"))
            require(rejected_forgery.returncode != 0 and "TRANSCRIPT_CONTEXT_NOT_CLEAN" in rejected_forgery.stdout, "v3 accepted an unrequested tool result containing the answer key")
            assistant = next(row for row in rows if row.get("type") == "assistant")
            assistant.pop("perTurnEffort") if effort is None else assistant.pop("effort")
            missing_path = root / f"{binding_id}-missing-effort.jsonl"
            missing_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            rejected = run("score", "--workspace", str(workspace), "--transcript", str(missing_path), "--receipt", str(root / "rejected.json"))
            require(rejected.returncode != 0 and "TRANSCRIPT_BINDING_MISMATCH" in rejected.stdout, "v3 accepted missing effort attestation")
            mismatch = run("prepare", "--output", str(root / f"{binding_id}-wrong"), "--run-id", "native-forward-run-1", "--session-id", str(uuid.uuid4()), "--binding-id", binding_id, "--model-id", "wrong-model")
            require(mismatch.returncode != 0 and "BINDING_ASSERTION_MISMATCH" in mismatch.stdout, "v3 accepted wrong model assertion")
        mixed = run("validate-pair", "--receipt", str(root / "claude-code-v3-ultimate-1.json"), "--receipt", str(root / "claude-code-v3-operational-2.json"))
        require(mixed.returncode != 0, "v3 pair accepted mixed bindings")
        historical = synthetic_legacy_receipts(root)
        mixed_version = run("validate-pair", "--receipt", str(root / "claude-code-v3-ultimate-1.json"), "--receipt", str(historical[1]))
        require(mixed_version.returncode != 0 and "QUALIFICATION_RECEIPT_INVALID" in mixed_version.stdout, "v3 pair accepted a historical receipt")


def test_v3_bindings() -> None:
    global ROOT, HARNESS
    registry = json.loads((ROOT / "standards/agent-model-registry.v3.yaml").read_text())
    if all(binding["status"] == "candidate" for binding in registry["bindings"]):
        _test_v3_bindings_candidate()
        return
    for binding in registry["bindings"]:
        if binding["provider"] == "claude_code" and binding["status"] == "qualified":
            try:
                harness.registry_binding(binding["binding_id"])
            except ValueError as error:
                require("QUALIFICATION_BINDING_INVALID" in str(error), "qualified binding rejected for unexpected reason")
            else:
                raise AssertionError("qualification accepted an already qualified binding")
    with tempfile.TemporaryDirectory(prefix="agent-council-candidate-package-") as temporary:
        candidate_root = Path(temporary) / "agent-council"
        shutil.copytree(ROOT, candidate_root, ignore=shutil.ignore_patterns("local", "results", "__pycache__", "tmp*"))
        candidate_registry = json.loads(json.dumps(registry))
        for binding in candidate_registry["bindings"]:
            binding["status"] = "candidate"
            binding.pop("qualified_roles", None)
            binding["binding_sha256"] = promotion.sha256(promotion.canonical({key: value for key, value in binding.items() if key != "binding_sha256"}))
        for state in candidate_registry["provider_states"].values():
            state["council_status"] = "fail_closed_until_qualified"
        candidate_registry["registry_sha256"] = promotion.sha256(promotion.canonical({key: value for key, value in candidate_registry.items() if key != "registry_sha256"}))
        (candidate_root / "standards/agent-model-registry.v3.yaml").write_text(json.dumps(candidate_registry) + "\n")
        original_root, original_harness = ROOT, HARNESS
        try:
            ROOT = candidate_root
            HARNESS = candidate_root / "scripts/ClaudeQualificationHarness.py"
            _test_v3_bindings_candidate()
        finally:
            ROOT, HARNESS = original_root, original_harness


def main() -> int:
    require(HARNESS.exists(), "Claude qualification harness is missing")
    test_current_identity()
    test_v3_bindings()
    with tempfile.TemporaryDirectory(prefix="agent-council-claude-qualification-") as temporary:
        root = Path(temporary)
        workspaces: list[Path] = []
        manifests: list[dict[str, object]] = []
        for index in (1, 2):
            workspace = root / f"run-{index}"
            context_id = str(uuid.uuid4())
            prepared = run("prepare", "--output", str(workspace), "--run-id", f"native-forward-run-{index}", "--session-id", context_id, "--model-id", "claude-opus-5-5")
            require(prepared.returncode == 0, f"prepare run {index} failed: {prepared.stdout} {prepared.stderr}")
            manifest = json.loads(prepared.stdout)
            require((workspace / "candidate/SKILL.md").is_file() and not (workspace / "candidate/skills").exists(), "historical v1 workspace layout changed")
            require("Read candidate/SKILL.md and every file under candidate/references" in (workspace / "evaluator-instructions.md").read_text(), "historical evaluator instructions changed")
            command = manifest["launch_command"]
            require(command[0] == "claude" and command[command.index("--model") + 1] == "claude-opus-5-5", "launch command does not pin the exact model")
            require(command[command.index("--effort") + 1] == "high", "historical default effort changed")
            require("--safe-mode" in command and "--restricted" in command, "launch command is not isolated")
            require("--tools" in command and command[command.index("--tools") + 1] == "Read,Glob,Grep", "launch command does not restrict tools to read-only operations")
            require("--disallowedTools" not in command, "historical v1 launch command changed")
            require("--session-id" in command and command[command.index("--session-id") + 1] == context_id, "launch command does not pin the fresh context")
            require("-p" not in command and "--print" not in command, "qualification must not use headless one-shot mode")
            exposed = "\n".join(path.read_text(encoding="utf-8") for path in workspace.rglob("*") if path.is_file())
            require("Escalates to R3" not in exposed and 'expected:' not in exposed and '"expected"' not in exposed, "evaluator workspace leaks the answer key")
            require(not any(path.name == "forward-tests.yaml" for path in workspace.rglob("*")), "evaluator workspace contains the source oracle")
            workspaces.append(workspace)
            manifests.append(manifest)
        require(manifests[0]["candidate_sha256"] == manifests[1]["candidate_sha256"], "candidate bytes differ between runs")
        require(manifests[0]["evaluation_bundle_sha256"] == manifests[1]["evaluation_bundle_sha256"], "blind evaluation bundle differs between runs")
        require(manifests[0]["session_id"] != manifests[1]["session_id"], "qualification contexts are not fresh")

        receipts: list[Path] = []
        for index, workspace in enumerate(workspaces, 1):
            response = {"schema_version": "agent-council.claude-native-response/v1", "results": [{"scenario_id": scenario_id, "claims": claims, "rationale": "bounded"} for scenario_id, claims in EXPECTED_CLAIMS.items()]}
            response["results"][10]["claims"] = [*response["results"][10]["claims"], "closure_held"]
            transcript_path = root / f"transcript-{index}.jsonl"
            receipt_path = root / f"receipt-{index}.json"
            transcript(transcript_path, "claude-opus-5-5", response, str(manifests[index - 1]["session_id"]), workspace, run_id=f"native-forward-run-{index}")
            scored = run("score", "--workspace", str(workspace), "--transcript", str(transcript_path), "--receipt", str(receipt_path))
            require(scored.returncode == 0, f"valid run {index} did not score: {scored.stdout} {scored.stderr}")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            require(receipt["result"] == "passed" and receipt["actual_model_id"] == "claude-opus-5-5", "valid run receipt is incomplete")
            receipts.append(receipt_path)
        paired = run("validate-pair", "--receipt", str(receipts[0]), "--receipt", str(receipts[1]))
        require(paired.returncode == 0 and json.loads(paired.stdout)["result"] == "passed", "two fresh identical-candidate receipts did not validate")

        for additional in ("ultimate_design", "technical_implementation"):
            extra_response = json.loads(json.dumps(response))
            extra_response["results"][9]["claims"].append(additional)
            extra_transcript = root / f"legacy-extra-{additional}.jsonl"
            extra_receipt = root / f"legacy-extra-{additional}.json"
            transcript(extra_transcript, "claude-opus-5-5", extra_response, str(manifests[0]["session_id"]), workspaces[0])
            extra = run("score", "--workspace", str(workspaces[0]), "--transcript", str(extra_transcript), "--receipt", str(extra_receipt))
            require(extra.returncode != 0 and "QUALIFICATION_SCENARIOS_FAILED" in extra.stdout, "historical v1 accepted extra GFT10 claim: " + additional)
            gft10 = next(item for item in json.loads(extra_receipt.read_text())["scenario_results"] if item["scenario_id"] == "GFT10")
            require(gft10["disallowed_additional_claims"] == [additional], "historical v1 rejected GFT10 for the wrong reason")

        wrong_transcript = root / "wrong-model.jsonl"
        transcript(wrong_transcript, "claude-opus-5", response, str(manifests[0]["session_id"]), workspaces[0])
        wrong = run("score", "--workspace", str(workspaces[0]), "--transcript", str(wrong_transcript), "--receipt", str(root / "wrong.json"))
        require(wrong.returncode != 0 and "MODEL_IDENTITY_MISMATCH" in wrong.stdout, "wrong Claude model identity was accepted")

        wrong_session_transcript = root / "wrong-session.jsonl"
        transcript(wrong_session_transcript, "claude-opus-5-5", response, str(uuid.uuid4()), workspaces[0])
        wrong_session = run("score", "--workspace", str(workspaces[0]), "--transcript", str(wrong_session_transcript), "--receipt", str(root / "wrong-session.json"))
        require(wrong_session.returncode != 0 and "TRANSCRIPT_SESSION_MISMATCH" in wrong_session.stdout, "unbound transcript session was accepted")

        missing_native_transcript = root / "missing-native.jsonl"
        transcript(missing_native_transcript, "claude-opus-5-5", response, str(manifests[0]["session_id"]), workspaces[0], include_native_records=False)
        missing_native = run("score", "--workspace", str(workspaces[0]), "--transcript", str(missing_native_transcript), "--receipt", str(root / "missing-native.json"))
        require(missing_native.returncode != 0 and "TRANSCRIPT_NATIVE_RECORDS_MISSING" in missing_native.stdout, "transcript without native session records was accepted")

        prior_prompt_transcript = root / "prior-prompt.jsonl"
        transcript(prior_prompt_transcript, "claude-opus-5-5", response, str(manifests[0]["session_id"]), workspaces[0], prior_prompt=True)
        prior_prompt_result = run("score", "--workspace", str(workspaces[0]), "--transcript", str(prior_prompt_transcript), "--receipt", str(root / "prior-prompt.json"))
        require(prior_prompt_result.returncode != 0 and "TRANSCRIPT_CONTEXT_NOT_CLEAN" in prior_prompt_result.stdout, "transcript with prior conversation was accepted")

        prohibited_tool_transcript = root / "prohibited-tool.jsonl"
        transcript(prohibited_tool_transcript, "claude-opus-5-5", response, str(manifests[0]["session_id"]), workspaces[0], prohibited_tool=True)
        prohibited_tool_result = run("score", "--workspace", str(workspaces[0]), "--transcript", str(prohibited_tool_transcript), "--receipt", str(root / "prohibited-tool.json"))
        require(prohibited_tool_result.returncode != 0 and "TRANSCRIPT_TOOL_NOT_ALLOWED" in prohibited_tool_result.stdout, "prohibited transcript tool use was accepted")

        external_path_transcript = root / "external-path.jsonl"
        transcript(external_path_transcript, "claude-opus-5-5", response, str(manifests[0]["session_id"]), workspaces[0], external_path=True)
        external_path_result = run("score", "--workspace", str(workspaces[0]), "--transcript", str(external_path_transcript), "--receipt", str(root / "external-path.json"))
        require(external_path_result.returncode != 0 and "TRANSCRIPT_PATH_OUTSIDE_WORKSPACE" in external_path_result.stdout, "out-of-workspace transcript read was accepted")

        failed_read_transcript = root / "failed-read.jsonl"
        transcript(failed_read_transcript, "claude-opus-5-5", response, str(manifests[0]["session_id"]), workspaces[0], failed_read=True)
        failed_read_result = run("score", "--workspace", str(workspaces[0]), "--transcript", str(failed_read_transcript), "--receipt", str(root / "failed-read.json"))
        require(failed_read_result.returncode != 0 and "TRANSCRIPT_REQUIRED_READS_MISSING" in failed_read_result.stdout, "failed required read was accepted")

        overclaimed = json.loads(json.dumps(response))
        overclaimed["results"][0]["claims"].append("route_r3")
        overclaimed_transcript = root / "overclaimed.jsonl"
        transcript(overclaimed_transcript, "claude-opus-5-5", overclaimed, str(manifests[0]["session_id"]), workspaces[0])
        overclaim = run("score", "--workspace", str(workspaces[0]), "--transcript", str(overclaimed_transcript), "--receipt", str(root / "overclaimed.json"))
        require(overclaim.returncode != 0 and "QUALIFICATION_SCENARIOS_FAILED" in overclaim.stdout, "incorrect additional claim was accepted")

        invalid_receipt = json.loads(receipts[1].read_text(encoding="utf-8"))
        invalid_receipt["scenario_results"] = []
        invalid_receipt_path = root / "invalid-receipt.json"
        invalid_receipt_path.write_text(json.dumps(invalid_receipt), encoding="utf-8")
        invalid_pair = run("validate-pair", "--receipt", str(receipts[0]), "--receipt", str(invalid_receipt_path))
        require(invalid_pair.returncode != 0 and "QUALIFICATION_RECEIPT_INVALID" in invalid_pair.stdout, "pair validation accepted a receipt without scenario evidence")

        candidate_file = workspaces[0] / "candidate" / "SKILL.md"
        candidate_bytes = candidate_file.read_bytes()
        candidate_file.write_bytes(candidate_bytes + b"\n")
        changed_candidate = run("score", "--workspace", str(workspaces[0]), "--transcript", str(root / "transcript-1.jsonl"), "--receipt", str(root / "changed-candidate.json"))
        require(changed_candidate.returncode != 0 and "QUALIFICATION_CANDIDATE_CHANGED" in changed_candidate.stdout, "candidate workspace tampering was accepted")
        candidate_file.write_bytes(candidate_bytes)

        changed_manifest = workspaces[0] / "qualification-run.json"
        manifest_value = json.loads(changed_manifest.read_text(encoding="utf-8"))
        manifest_value["launch_command"] = [item for item in manifest_value["launch_command"] if item != "--safe-mode"]
        changed_manifest.write_text(json.dumps(manifest_value), encoding="utf-8")
        changed_launch = run("score", "--workspace", str(workspaces[0]), "--transcript", str(root / "transcript-1.jsonl"), "--receipt", str(root / "changed-launch.json"))
        require(changed_launch.returncode != 0 and "QUALIFICATION_LAUNCH_COMMAND_INVALID" in changed_launch.stdout, "manifest launch-command tampering was accepted")

        same_context = json.loads(receipts[1].read_text(encoding="utf-8"))
        same_context["session_id"] = json.loads(receipts[0].read_text(encoding="utf-8"))["session_id"]
        same_path = root / "same-context.json"
        same_path.write_text(json.dumps(same_context), encoding="utf-8")
        stale_pair = run("validate-pair", "--receipt", str(receipts[0]), "--receipt", str(same_path))
        require(stale_pair.returncode != 0 and "QUALIFICATION_CONTEXTS_NOT_FRESH" in stale_pair.stdout, "same-context qualification pair was accepted")
    print(json.dumps({"result": "passed", "scenarios": len(EXPECTED_CLAIMS), "native_runs": 2}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
