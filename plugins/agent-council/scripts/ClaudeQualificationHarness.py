#!/usr/bin/env python3
"""Prepare and score clean, blind, interactive Claude Code qualifications."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FORWARD_TESTS = ROOT / "skills" / "agent-council" / "references" / "forward-tests.yaml"
MANIFEST = "qualification-run.json"
MODEL_ID = "claude-opus-5-5"
RUN_IDS = {"native-forward-run-1", "native-forward-run-2"}
CANDIDATE_FILES = (
    "skills/agent-council/SKILL.md",
    "skills/agent-council/references/model-adapters.yaml",
    "skills/agent-council/references/project-profiles.yaml",
    "skills/agent-council/references/compound-engineering.yaml",
    "profiles/default.yaml",
    "standards/agent-council-standard.v2.yaml",
)
EXPECTED_CLAIMS = {
    "GFT01": {"route_r1_or_higher", "technical_implementation", "independent_operational_review", "ultimate_routing", "ultimate_final"},
    "GFT02": {"route_r3", "ultimate_design", "integration_evidence", "fault_evidence"},
    "GFT03": {"route_r3", "separate_symptom_from_cause", "no_blind_repeat"},
    "GFT04": {"reject_self_review", "closure_held", "name_independent_review_gap"},
    "GFT05": {"reject_lower_tier", "record_required_tier_unavailable", "gate_not_advanced"},
    "GFT06": {"new_candidate_cycle", "reject_stale_evidence", "fresh_review", "fresh_native_qualification"},
    "GFT07": {"reconcile_ownership", "no_duplicate_unknown_work", "link_resumption"},
    "GFT08": {"council_owns_routing", "ce_owns_method", "reuse_exact_receipts"},
    "GFT09": {"ordinary_operation_exclusion", "no_full_council", "authorization_preserved"},
    "GFT10": {"visible_dispatch_notice", "no_private_reasoning", "worker_disposition_reported"},
    "GFT11": {"reject_narrative_only", "file_backed_evidence", "exact_missing_gates"},
    "GFT12": {"packaged_default_profile", "no_unrelated_rule_inheritance", "external_authority_unchanged"},
}
CLAIM_VOCABULARY = sorted(set().union(*EXPECTED_CLAIMS.values()))


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def tree_digest(root: Path, paths: list[Path]) -> str:
    value = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        value.update(len(relative).to_bytes(8, "big"))
        value.update(relative)
        value.update(len(content).to_bytes(8, "big"))
        value.update(content)
    return value.hexdigest()


def candidate_digest() -> str:
    paths = [ROOT / relative for relative in CANDIDATE_FILES]
    return tree_digest(ROOT, paths)


def scenario_requests() -> list[dict[str, str]]:
    scenarios: list[dict[str, str]] = []
    current: str | None = None
    for line in FORWARD_TESTS.read_text(encoding="utf-8").splitlines():
        match_id = re.match(r'\s*- id: "(GFT\d{2})"$', line)
        if match_id:
            current = match_id.group(1)
            continue
        match_request = re.match(r'\s+request: (".*")$', line)
        if current in EXPECTED_CLAIMS and match_request:
            scenarios.append({"scenario_id": current, "request": json.loads(match_request.group(1))})
            current = None
    if {item["scenario_id"] for item in scenarios} != set(EXPECTED_CLAIMS):
        raise ValueError("FORWARD_TEST_REQUEST_SET_INVALID")
    return scenarios


def evaluator_instructions() -> str:
    vocabulary = json.dumps(CLAIM_VOCABULARY, indent=2)
    return f"""You are evaluating the supplied Agent Council candidate, not modifying it.

Read candidate/SKILL.md and every file under candidate/references, candidate/profiles, and candidate/standards. Then read requests.json. For each request, decide the behavior required by the candidate rules.

Return one JSON object and no markdown. Use this schema:
{{"schema_version":"agent-council.claude-native-response/v1","results":[{{"scenario_id":"GFT01","claims":["claim"],"rationale":"one short sentence"}}]}}

Return every scenario exactly once. Select only claims from this vocabulary. Use only the claims that apply to that scenario. Use read operations only inside this workspace. Do not run commands, modify files, delegate, browse, or inspect outside paths.

Claim vocabulary:
{vocabulary}
"""


def bundle_paths(workspace: Path) -> list[Path]:
    return [path for path in workspace.rglob("*") if path.is_file() and path.name != MANIFEST]


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("QUALIFICATION_WORKSPACE_NOT_EMPTY")
    try:
        parsed_session_id = str(uuid.UUID(args.session_id))
    except ValueError:
        parsed_session_id = ""
    if args.run_id not in RUN_IDS or args.model_id != MODEL_ID or parsed_session_id != args.session_id.lower():
        raise ValueError("QUALIFICATION_ARGUMENT_INVALID")
    output.mkdir(parents=True, exist_ok=True)
    for relative in CANDIDATE_FILES:
        source = ROOT / relative
        target = output / "candidate" / relative.removeprefix("skills/agent-council/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    (output / "requests.json").write_text(json.dumps({"schema_version": "agent-council.blind-requests/v1", "scenarios": scenario_requests()}, indent=2) + "\n", encoding="utf-8")
    (output / "evaluator-instructions.md").write_text(evaluator_instructions(), encoding="utf-8")
    bundle_sha = tree_digest(output, bundle_paths(output))
    prompt = "Read evaluator-instructions.md and complete the blind evaluation now. Return only the required JSON object."
    command = ["claude", "--model", args.model_id, "--effort", "high", "--safe-mode", "--restricted", "--no-chrome", "--strict-mcp-config", "--session-id", args.session_id, "--name", f"Agent Council {args.run_id}", prompt]
    manifest = {
        "schema_version": "agent-council.claude-qualification-run/v1",
        "run_id": args.run_id,
        "session_id": args.session_id,
        "requested_model_id": args.model_id,
        "candidate_sha256": candidate_digest(),
        "evaluation_bundle_sha256": bundle_sha,
        "clean_context": True,
        "blind": True,
        "launch_command": command,
    }
    (output / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def extract_response(transcript: Path, expected_model: str) -> tuple[str, dict[str, Any]]:
    models: list[str] = []
    texts: list[str] = []
    for number, line in enumerate(transcript.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"TRANSCRIPT_JSON_INVALID:{number}") from error
        if row.get("type") != "assistant" or not isinstance(row.get("message"), dict):
            continue
        model = row["message"].get("model")
        if isinstance(model, str) and model:
            models.append(model)
        content = row["message"].get("content")
        if isinstance(content, list):
            text = "\n".join(item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text")
            if text.strip():
                texts.append(text.strip())
    if not models or any(model != expected_model for model in models):
        raise ValueError("MODEL_IDENTITY_MISMATCH")
    for text in reversed(texts):
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return models[-1], value
    raise ValueError("QUALIFICATION_RESPONSE_MISSING")


def score(args: argparse.Namespace) -> dict[str, Any]:
    workspace = args.workspace.resolve()
    manifest = json.loads((workspace / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("clean_context") is not True or manifest.get("blind") is not True:
        raise ValueError("QUALIFICATION_ISOLATION_INVALID")
    if tree_digest(workspace, bundle_paths(workspace)) != manifest.get("evaluation_bundle_sha256"):
        raise ValueError("QUALIFICATION_BUNDLE_CHANGED")
    actual_model, response = extract_response(args.transcript.resolve(), manifest["requested_model_id"])
    if response.get("schema_version") != "agent-council.claude-native-response/v1" or not isinstance(response.get("results"), list):
        raise ValueError("QUALIFICATION_RESPONSE_SCHEMA_INVALID")
    actual: dict[str, set[str]] = {}
    details: list[dict[str, Any]] = []
    for item in response["results"]:
        if not isinstance(item, dict) or not isinstance(item.get("scenario_id"), str) or not isinstance(item.get("claims"), list) or not all(isinstance(claim, str) for claim in item["claims"]):
            raise ValueError("QUALIFICATION_RESPONSE_SCHEMA_INVALID")
        scenario_id = item["scenario_id"]
        claims = set(item["claims"])
        if scenario_id in actual or scenario_id not in EXPECTED_CLAIMS or not claims <= set(CLAIM_VOCABULARY):
            raise ValueError("QUALIFICATION_RESPONSE_SCHEMA_INVALID")
        actual[scenario_id] = claims
    if set(actual) != set(EXPECTED_CLAIMS):
        raise ValueError("QUALIFICATION_SCENARIO_SET_INVALID")
    for scenario_id in sorted(EXPECTED_CLAIMS):
        missing = sorted(EXPECTED_CLAIMS[scenario_id] - actual[scenario_id])
        unexpected = sorted(actual[scenario_id] - EXPECTED_CLAIMS[scenario_id])
        status = "passed" if not missing and not unexpected else "failed"
        details.append({"scenario_id": scenario_id, "status": status, "missing_claims": missing, "unexpected_claims": unexpected})
    result = "passed" if all(item["status"] == "passed" for item in details) else "failed"
    receipt = {
        "schema_version": "agent-council.claude-qualification-receipt/v1",
        "run_id": manifest["run_id"],
        "session_id": manifest["session_id"],
        "requested_model_id": manifest["requested_model_id"],
        "actual_model_id": actual_model,
        "candidate_sha256": manifest["candidate_sha256"],
        "evaluation_bundle_sha256": manifest["evaluation_bundle_sha256"],
        "transcript_sha256": digest_bytes(args.transcript.resolve().read_bytes()),
        "clean_context": True,
        "blind": True,
        "scenario_results": details,
        "result": result,
    }
    args.receipt.resolve().write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if result != "passed":
        raise ValueError("QUALIFICATION_SCENARIOS_FAILED")
    return receipt


def validate_pair(args: argparse.Namespace) -> dict[str, Any]:
    receipts = [json.loads(path.read_text(encoding="utf-8")) for path in args.receipt]
    if len(receipts) != 2 or {item.get("run_id") for item in receipts} != RUN_IDS:
        raise ValueError("QUALIFICATION_RUN_SET_INVALID")
    if any(item.get("result") != "passed" or item.get("clean_context") is not True or item.get("blind") is not True for item in receipts):
        raise ValueError("QUALIFICATION_RUN_FAILED")
    if {item.get("actual_model_id") for item in receipts} != {MODEL_ID}:
        raise ValueError("MODEL_IDENTITY_MISMATCH")
    if len({item.get("session_id") for item in receipts}) != 2:
        raise ValueError("QUALIFICATION_CONTEXTS_NOT_FRESH")
    if len({item.get("candidate_sha256") for item in receipts}) != 1 or len({item.get("evaluation_bundle_sha256") for item in receipts}) != 1:
        raise ValueError("QUALIFICATION_CANDIDATE_MISMATCH")
    return {"schema_version": "agent-council.claude-qualification-pair/v1", "result": "passed", "model_id": MODEL_ID, "candidate_sha256": receipts[0]["candidate_sha256"], "evaluation_bundle_sha256": receipts[0]["evaluation_bundle_sha256"], "run_ids": sorted(RUN_IDS), "session_ids": sorted(item["session_id"] for item in receipts)}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    commands = value.add_subparsers(dest="command", required=True)
    prepared = commands.add_parser("prepare")
    prepared.add_argument("--output", required=True, type=Path)
    prepared.add_argument("--run-id", required=True)
    prepared.add_argument("--session-id", required=True)
    prepared.add_argument("--model-id", required=True)
    scored = commands.add_parser("score")
    scored.add_argument("--workspace", required=True, type=Path)
    scored.add_argument("--transcript", required=True, type=Path)
    scored.add_argument("--receipt", required=True, type=Path)
    paired = commands.add_parser("validate-pair")
    paired.add_argument("--receipt", required=True, action="append", type=Path)
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args)
        elif args.command == "score":
            result = score(args)
        else:
            result = validate_pair(args)
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"result": "refused", "code": str(error)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
