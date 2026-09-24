#!/usr/bin/env python3
"""Contract tests for clean, blind, exact-model Claude qualification."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


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


def transcript(path: Path, model: str, result: dict[str, object], session_id: str, workspace: Path, *, run_id: str = "native-forward-run-1", include_native_records: bool = True, prior_prompt: bool = False, prohibited_tool: bool = False, external_path: bool = False, failed_read: bool = False) -> None:
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
    rows.append({"type": "user", "parentUuid": None, "isSidechain": False, "entrypoint": "cli", "promptSource": "typed", "origin": {"kind": "human"}, "sessionId": session_id, "cwd": str(resolved), "message": {"role": "user", "content": "Read evaluator-instructions.md and complete the blind evaluation now. Return only the required JSON object."}})
    reads = [resolved / "evaluator-instructions.md", resolved / "requests.json", *sorted(item for item in (resolved / "candidate").rglob("*") if item.is_file())]
    for index, read_path in enumerate(reads):
        tool_name = "Write" if prohibited_tool and index == 0 else "Read"
        selected_path = Path("/tmp/outside-qualification") if external_path and index == 0 else read_path
        tool_id = f"tool-{index}"
        rows.append({"type": "assistant", "isSidechain": False, "entrypoint": "cli", "effort": "high", "sessionId": session_id, "cwd": str(resolved), "message": {"model": model, "content": [{"type": "tool_use", "id": tool_id, "name": tool_name, "input": {"file_path": str(selected_path)}}]}})
        rows.append({"type": "user", "isSidechain": False, "entrypoint": "cli", "sessionId": session_id, "cwd": str(resolved), "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "denied" if failed_read and index == 0 else "bounded", "is_error": failed_read and index == 0}]}})
    rows.append({"type": "assistant", "isSidechain": False, "entrypoint": "cli", "effort": "high", "sessionId": session_id, "cwd": str(resolved), "message": {"model": model, "content": [{"type": "text", "text": json.dumps(result)}]}})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    require(HARNESS.exists(), "Claude qualification harness is missing")
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
            command = manifest["launch_command"]
            require(command[0] == "claude" and command[command.index("--model") + 1] == "claude-opus-5-5", "launch command does not pin the exact model")
            require("--safe-mode" in command and "--restricted" in command, "launch command is not isolated")
            require("--tools" in command and command[command.index("--tools") + 1] == "Read,Glob,Grep", "launch command does not restrict tools to read-only operations")
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
