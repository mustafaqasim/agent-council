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
PROMPT = "Read evaluator-instructions.md and complete the blind evaluation now. Return only the required JSON object."
CANDIDATE_FILES = (
    "skills/agent-council/SKILL.md",
    "skills/agent-council/references/model-adapters.yaml",
    "skills/agent-council/references/project-profiles.yaml",
    "skills/agent-council/references/compound-engineering.yaml",
    "profiles/default.yaml",
    "standards/agent-council-standard.v2.yaml",
)
# The v1 native qualification format permanently uses CANDIDATE_FILES above.
# Current package behavior has a separate, versioned identity and no bearing on
# historical receipt acceptance. Extend its inventory only with existing files.
BEHAVIORAL_INVENTORY = "standards/behavioral-inventory.v1.json"
BEHAVIORAL_INVENTORY_SCHEMA = "agent-council.behavioral-inventory/v1"
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
ALLOWED_ADDITIONAL_CLAIMS = {"GFT11": {"closure_held"}}
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


def named_file_digest(files: list[tuple[str, Path]]) -> str:
    value = hashlib.sha256()
    for relative, path in sorted(files):
        name = relative.encode("utf-8")
        content = path.read_bytes()
        value.update(len(name).to_bytes(8, "big"))
        value.update(name)
        value.update(len(content).to_bytes(8, "big"))
        value.update(content)
    return value.hexdigest()


def candidate_digest() -> str:
    return named_file_digest([(relative, ROOT / relative) for relative in CANDIDATE_FILES])


def inventory_file(root: Path, relative: str) -> Path:
    """Require a canonical, regular plugin file without symlink indirection."""
    if not isinstance(relative, str) or not relative or relative.startswith("/") or "\\" in relative or ":" in relative or any(ord(char) < 32 or ord(char) == 127 for char in relative) or any(part in {"", ".", ".."} for part in relative.split("/")):
        raise ValueError("INVENTORY_PATH_UNSAFE")
    path = root / relative
    current = root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            raise ValueError(f"INVENTORY_PATH_UNSAFE:{relative}")
    if not path_within(path, root):
        raise ValueError(f"INVENTORY_PATH_UNSAFE:{relative}")
    if not path.is_file():
        raise ValueError(f"INVENTORY_FILE_MISSING:{relative}")
    return path


def inventory_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"INVENTORY_DUPLICATE_KEY:{key}")
        value[key] = item
    return value


def current_behavioral_identity(root: Path = ROOT, inventory: str = BEHAVIORAL_INVENTORY) -> dict[str, Any]:
    """Bind the canonical declaration and all declared bytes to a current ID.

    JSON object ordering, whitespace and path ordering are immaterial. Schema,
    identity version, membership, names and file bytes are all identity inputs.
    Missing or future files cannot qualify. This is an identity, not a passing
    evaluation receipt, and never replaces the historical candidate digest.
    """
    root = root.resolve()
    declaration = json.loads(inventory_file(root, inventory).read_text(encoding="utf-8"), object_pairs_hook=inventory_object)
    if not isinstance(declaration, dict) or set(declaration) != {"schema_version", "identity_version", "paths"} or declaration.get("schema_version") != BEHAVIORAL_INVENTORY_SCHEMA:
        raise ValueError("INVENTORY_SCHEMA_INVALID")
    version = declaration["identity_version"]
    if not isinstance(version, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._/-]*", version):
        raise ValueError("INVENTORY_VERSION_INVALID")
    paths = declaration["paths"]
    if not isinstance(paths, list) or not paths or any(not isinstance(path, str) for path in paths) or len(set(paths)) != len(paths):
        raise ValueError("INVENTORY_PATHS_INVALID")
    paths = sorted(paths)
    if inventory in paths:
        raise ValueError("INVENTORY_SELF_REFERENCE")
    files = [(relative, inventory_file(root, relative)) for relative in paths]
    identities = [(path.stat().st_dev, path.stat().st_ino) for _, path in files]
    if len(set(identities)) != len(identities):
        raise ValueError("INVENTORY_PATHS_INVALID:duplicate-file")
    canonical = json.dumps({**declaration, "paths": paths}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    inventory_sha = digest_bytes(canonical)
    files_sha = named_file_digest(files)
    behavioral_sha = digest_bytes(b"agent-council.behavioral-identity/v1\0" + bytes.fromhex(inventory_sha) + bytes.fromhex(files_sha))
    return {
        "schema_version": "agent-council.behavioral-identity/v1",
        "identity_version": version,
        "inventory_sha256": inventory_sha,
        "files_sha256": files_sha,
        "behavioral_sha256": behavioral_sha,
        "paths": paths,
    }


def workspace_candidate_digest(workspace: Path) -> str:
    files = []
    for relative in CANDIDATE_FILES:
        copied = relative.removeprefix("skills/agent-council/")
        files.append((relative, workspace / "candidate" / copied))
    return named_file_digest(files)


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


def launch_command(run_id: str, session_id: str, model_id: str) -> list[str]:
    return ["claude", "--model", model_id, "--effort", "high", "--safe-mode", "--restricted", "--no-chrome", "--strict-mcp-config", "--tools", "Read,Glob,Grep", "--session-id", session_id, "--name", f"Agent Council {run_id}", PROMPT]


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
    command = launch_command(args.run_id, args.session_id, args.model_id)
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


def path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def extract_response(transcript: Path, expected_model: str, expected_session_id: str, expected_workspace: Path, expected_run_id: str) -> tuple[str, dict[str, Any]]:
    models: list[str] = []
    texts: list[tuple[int, str]] = []
    session_ids: set[str] = set()
    workspaces: set[Path] = set()
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(transcript.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"TRANSCRIPT_JSON_INVALID:{number}") from error
        if not isinstance(row, dict):
            raise ValueError(f"TRANSCRIPT_JSON_INVALID:{number}")
        rows.append(row)
        session_id = row.get("sessionId")
        if isinstance(session_id, str) and session_id:
            session_ids.add(session_id)
        cwd = row.get("cwd")
        if isinstance(cwd, str) and cwd:
            workspaces.add(Path(cwd).resolve())
        if row.get("type") != "assistant" or not isinstance(row.get("message"), dict):
            continue
        model = row["message"].get("model")
        if isinstance(model, str) and model:
            models.append(model)
        content = row["message"].get("content")
        if isinstance(content, list):
            text = "\n".join(item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text")
            if text.strip():
                texts.append((len(rows) - 1, text.strip()))
    if not models or any(model != expected_model for model in models):
        raise ValueError("MODEL_IDENTITY_MISMATCH")
    if session_ids != {expected_session_id}:
        raise ValueError("TRANSCRIPT_SESSION_MISMATCH")
    if workspaces != {expected_workspace.resolve()}:
        raise ValueError("TRANSCRIPT_WORKSPACE_MISMATCH")
    response_index = -1
    response: dict[str, Any] | None = None
    for index, text in reversed(texts):
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                response_index = index
                response = value
                break
    if response is None:
        raise ValueError("QUALIFICATION_RESPONSE_MISSING")

    conversational_users: list[tuple[int, dict[str, Any]]] = []
    for index, row in enumerate(rows[: response_index + 1]):
        if row.get("type") != "user" or row.get("isMeta") is True:
            continue
        message = row.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            conversational_users.append((index, row))
    if len(conversational_users) != 1:
        raise ValueError("TRANSCRIPT_CONTEXT_NOT_CLEAN")
    prompt_index, prompt_row = conversational_users[0]
    prompt_message = prompt_row.get("message", {})
    if prompt_message.get("content") != PROMPT or prompt_row.get("parentUuid") is not None or prompt_row.get("isSidechain") is not False or prompt_row.get("entrypoint") != "cli" or prompt_row.get("promptSource") != "typed" or prompt_row.get("origin") != {"kind": "human"}:
        raise ValueError("TRANSCRIPT_PROMPT_MISMATCH")

    preceding = rows[:prompt_index]
    expected_name = f"Agent Council {expected_run_id}"
    if not any(row.get("type") == "custom-title" and row.get("customTitle") == expected_name for row in preceding) or not any(row.get("type") == "agent-name" and row.get("agentName") == expected_name for row in preceding) or not any(row.get("type") == "mode" for row in preceding) or not any(row.get("type") == "permission-mode" for row in preceding):
        raise ValueError("TRANSCRIPT_NATIVE_RECORDS_MISSING")

    required_reads = {expected_workspace / "evaluator-instructions.md", expected_workspace / "requests.json"}
    for relative in CANDIDATE_FILES:
        copied = relative.removeprefix("skills/agent-council/")
        required_reads.add(expected_workspace / "candidate" / copied)
    requested_reads: dict[str, Path] = {}
    successful_reads: set[Path] = set()
    for row in rows[prompt_index + 1 : response_index + 1]:
        if row.get("type") == "user":
            message = row.get("message", {})
            for item in message.get("content", []) if isinstance(message.get("content"), list) else []:
                if not isinstance(item, dict) or item.get("type") != "tool_result" or item.get("is_error") is True:
                    continue
                tool_id = item.get("tool_use_id")
                content = item.get("content")
                if isinstance(tool_id, str) and tool_id in requested_reads and isinstance(content, str) and content:
                    successful_reads.add(requested_reads[tool_id])
            continue
        if row.get("type") != "assistant":
            continue
        if row.get("isSidechain") is not False or row.get("entrypoint") != "cli" or row.get("effort") != "high":
            raise ValueError("TRANSCRIPT_NATIVE_ASSISTANT_INVALID")
        message = row.get("message", {})
        for item in message.get("content", []) if isinstance(message.get("content"), list) else []:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            name = item.get("name")
            inputs = item.get("input")
            if name not in {"Read", "Glob", "Grep"} or not isinstance(inputs, dict):
                raise ValueError("TRANSCRIPT_TOOL_NOT_ALLOWED")
            path_value = inputs.get("file_path") if name == "Read" else inputs.get("path")
            if path_value is not None:
                if not isinstance(path_value, str) or not path_within(Path(path_value), expected_workspace):
                    raise ValueError("TRANSCRIPT_PATH_OUTSIDE_WORKSPACE")
                if name == "Read":
                    tool_id = item.get("id")
                    if not isinstance(tool_id, str) or not tool_id:
                        raise ValueError("TRANSCRIPT_TOOL_RESULT_INVALID")
                    requested_reads[tool_id] = Path(path_value).resolve()
    if {path.resolve() for path in required_reads} - successful_reads:
        raise ValueError("TRANSCRIPT_REQUIRED_READS_MISSING")
    return models[-1], response


def score(args: argparse.Namespace) -> dict[str, Any]:
    workspace = args.workspace.resolve()
    manifest = json.loads((workspace / MANIFEST).read_text(encoding="utf-8"))
    try:
        manifest_session = str(uuid.UUID(manifest.get("session_id", "")))
    except ValueError:
        manifest_session = ""
    if manifest.get("schema_version") != "agent-council.claude-qualification-run/v1" or manifest.get("run_id") not in RUN_IDS or manifest.get("requested_model_id") != MODEL_ID or manifest_session != manifest.get("session_id"):
        raise ValueError("QUALIFICATION_MANIFEST_INVALID")
    if manifest.get("launch_command") != launch_command(manifest["run_id"], manifest["session_id"], manifest["requested_model_id"]):
        raise ValueError("QUALIFICATION_LAUNCH_COMMAND_INVALID")
    if manifest.get("clean_context") is not True or manifest.get("blind") is not True:
        raise ValueError("QUALIFICATION_ISOLATION_INVALID")
    if workspace_candidate_digest(workspace) != manifest.get("candidate_sha256"):
        raise ValueError("QUALIFICATION_CANDIDATE_CHANGED")
    if tree_digest(workspace, bundle_paths(workspace)) != manifest.get("evaluation_bundle_sha256"):
        raise ValueError("QUALIFICATION_BUNDLE_CHANGED")
    actual_model, response = extract_response(args.transcript.resolve(), manifest["requested_model_id"], manifest["session_id"], workspace, manifest["run_id"])
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
        disallowed = sorted(set(unexpected) - ALLOWED_ADDITIONAL_CLAIMS.get(scenario_id, set()))
        status = "passed" if not missing and not disallowed else "failed"
        details.append({"scenario_id": scenario_id, "status": status, "missing_claims": missing, "additional_claims": unexpected, "disallowed_additional_claims": disallowed})
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
    for item in receipts:
        results = item.get("scenario_results")
        if item.get("schema_version") != "agent-council.claude-qualification-receipt/v1" or item.get("requested_model_id") != MODEL_ID or not isinstance(results, list):
            raise ValueError("QUALIFICATION_RECEIPT_INVALID")
        if {result.get("scenario_id") for result in results if isinstance(result, dict)} != set(EXPECTED_CLAIMS) or any(not isinstance(result, dict) or result.get("status") != "passed" or result.get("missing_claims") or result.get("disallowed_additional_claims") for result in results):
            raise ValueError("QUALIFICATION_RECEIPT_INVALID")
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
    identity = commands.add_parser("current-identity", help="Digest current declared behavior without changing historical qualification")
    identity.add_argument("--root", default=ROOT, type=Path)
    identity.add_argument("--inventory", default=BEHAVIORAL_INVENTORY, help="Canonical plugin-relative inventory path")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args)
        elif args.command == "score":
            result = score(args)
        elif args.command == "current-identity":
            result = current_behavioral_identity(args.root, args.inventory)
        else:
            result = validate_pair(args)
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"result": "refused", "code": str(error)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
