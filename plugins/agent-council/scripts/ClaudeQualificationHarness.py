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

import QualificationProtocol as role_protocol


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("TRANSCRIPT_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def strict_transcript_json(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_unique_json_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("TRANSCRIPT_JSON_NONFINITE")))


def extract_qualification_json(texts: list[tuple[int, str]]) -> tuple[int, dict[str, Any]]:
    if not texts:
        raise ValueError("QUALIFICATION_RESPONSE_MISSING")
    index, text = texts[-1]
    # Native Claude replies may put a short prose lead-in before one JSON fence.
    # Braces and another fence in the lead-in could conceal a second answer.
    # Inline backticks are normal in Claude's observed prose preface.
    fenced = re.fullmatch(r"(?P<preface>(?:(?!```)[^{}]){0,2048})```json[ \t]*\r?\n"
                          r"(?P<body>.*?)\r?\n```[ \t]*\s*", text, re.DOTALL)
    if fenced:
        text = fenced.group("body")
    try:
        value = strict_transcript_json(text)
    except json.JSONDecodeError as error:
        raise ValueError("QUALIFICATION_RESPONSE_INVALID") from error
    if not isinstance(value, dict):
        raise ValueError("QUALIFICATION_RESPONSE_INVALID")
    return index, value


def validate_qualification_tail(rows: list[dict[str, Any]], response_index: int) -> None:
    suffix = rows[response_index + 1:]
    if suffix:
        if not _native_turn_duration(suffix[0], rows[response_index]):
            raise ValueError("QUALIFICATION_RESPONSE_NOT_FINAL")
        metadata_fields = {
            "last-prompt": {"lastPrompt", "leafUuid"},
            "custom-title": {"customTitle"},
            "agent-name": {"agentName"},
            "mode": {"mode"},
            "permission-mode": {"permissionMode"},
            "atis-latch": {"atis"},
        }
        order = tuple(metadata_fields)
        previous = -1
        for row in suffix[1:]:
            kind = row.get("type")
            if not isinstance(kind, str) or kind not in metadata_fields or order.index(kind) <= previous or set(row) != metadata_fields[kind] | {"type", "sessionId"} or row["sessionId"] != suffix[0]["sessionId"]:
                raise ValueError("QUALIFICATION_RESPONSE_NOT_FINAL")
            previous = order.index(kind)
            if kind == "last-prompt":
                if row["lastPrompt"] != PROMPT or row["leafUuid"] != suffix[0]["uuid"]:
                    raise ValueError("QUALIFICATION_RESPONSE_NOT_FINAL")
            elif kind in {"custom-title", "agent-name"}:
                field = next(iter(metadata_fields[kind]))
                if not isinstance(row[field], str) or not any(
                    earlier.get("type") == kind and earlier.get(field) == row[field]
                    for earlier in rows[:response_index]
                ):
                    raise ValueError("QUALIFICATION_RESPONSE_NOT_FINAL")
            elif kind == "mode":
                if row["mode"] != "normal":
                    raise ValueError("QUALIFICATION_RESPONSE_NOT_FINAL")
            elif kind == "permission-mode":
                if not isinstance(row["permissionMode"], str) or not any(
                    earlier.get("type") == "permission-mode"
                    and earlier.get("sessionId") == row["sessionId"]
                    and earlier.get("permissionMode") == row["permissionMode"]
                    for earlier in rows[:response_index]
                ):
                    raise ValueError("QUALIFICATION_RESPONSE_NOT_FINAL")
            elif not isinstance(row["atis"], str):
                raise ValueError("QUALIFICATION_RESPONSE_NOT_FINAL")
    message = rows[response_index].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list) or not content or any(
        not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str)
        for block in content
    ):
        raise ValueError("QUALIFICATION_RESPONSE_INVALID")


def _native_turn_duration(row: dict[str, Any], response: dict[str, Any]) -> bool:
    """Accept only Claude's content-free terminal turn bookkeeping record."""
    if set(row) != {"parentUuid", "isSidechain", "type", "subtype", "durationMs",
                    "messageCount", "timestamp", "uuid", "isMeta", "userType",
                    "entrypoint", "cwd", "sessionId", "version", "gitBranch"}:
        return False
    return (row["type"] == "system" and row["subtype"] == "turn_duration"
            and row["isSidechain"] is False and row["isMeta"] is False
            and row["userType"] == "external" and row["entrypoint"] == "cli"
            and type(row["durationMs"]) is int and row["durationMs"] >= 0
            and type(row["messageCount"]) is int and row["messageCount"] > 0
            and all(isinstance(row[key], str) and row[key] for key in
                    ("timestamp", "uuid", "cwd", "sessionId", "version", "gitBranch"))
            and row["parentUuid"] == response.get("uuid")
            and row["sessionId"] == response.get("sessionId")
            and row["cwd"] == response.get("cwd")
            and row["version"] == response.get("version"))


ROOT = Path(__file__).resolve().parents[1]
FORWARD_TESTS = ROOT / "skills" / "agent-council" / "references" / "forward-tests.yaml"
MANIFEST = "qualification-run.json"
MODEL_ID = "claude-opus-5-5"
REGISTRY_V3 = ROOT / "standards" / "agent-model-registry.v3.yaml"
RUN_IDS = {"native-forward-run-1", "native-forward-run-2"}
PROMPT = ("Read evaluator-instructions.md and complete the blind evaluation now. "
          "Your final response must be one bare raw JSON object. Do not wrap it in Markdown code fences "
          "or add a preamble or suffix.")
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
CURRENT_CANDIDATE_FILES = CANDIDATE_FILES + (
    "skills/agent-council/references/lightweight-routing.yaml",
    "skills/agent-council/references/governed-workflow.yaml",
)
V3_CANDIDATE_FILES = CURRENT_CANDIDATE_FILES + (
    "standards/agent-model-registry.v3.yaml",
    "standards/agent-model-registry.schema.v3.yaml",
    "standards/model-qualifications/provider-catalog-refresh.v3.yaml",
    "agents/council-ultimate.md",
    "agents/council-operational.md",
    "agents/council-technical.md",
    "agents/council-worker.md",
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
ALLOWED_ADDITIONAL_CLAIMS = {
    "GFT11": {"closure_held"},
}
CURRENT_ALLOWED_ADDITIONAL_CLAIMS = {
    **ALLOWED_ADDITIONAL_CLAIMS,
    "GFT08": {"authorization_preserved"},
    "GFT10": {"ultimate_design", "technical_implementation"},
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


def eval_suite_digest(root: Path = ROOT, identity: dict[str, Any] | None = None) -> str:
    identity = identity or current_behavioral_identity(root)
    paths = [relative for relative in identity["paths"] if relative.startswith("evals/")]
    if not paths:
        raise ValueError("EVAL_INVENTORY_EMPTY")
    return named_file_digest([(relative, inventory_file(root, relative)) for relative in paths])


def current_release_binding(root: Path = ROOT) -> dict[str, Any]:
    identity = current_behavioral_identity(root)
    return {"schema_version": "agent-council.release-binding/v1",
            "behavioral_identity": identity,
            "eval_suite_sha256": eval_suite_digest(root, identity)}


def registry_binding(binding_id: str, root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    registry = json.loads((root / "standards" / "agent-model-registry.v3.yaml").read_text(encoding="utf-8"),
                          object_pairs_hook=inventory_object)
    def canonical(value: Any) -> str:
        return digest_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    bindings = registry.get("bindings")
    if registry.get("schema_version") != "agent-council.model-registry/v3" or registry.get("registry_version") != "v3" or registry.get("registry_sha256") != canonical({key: value for key, value in registry.items() if key != "registry_sha256"}) or not isinstance(bindings, list) or any(not isinstance(item, dict) for item in bindings) or len({item.get("binding_id") for item in bindings}) != len(bindings):
        raise ValueError("QUALIFICATION_REGISTRY_INVALID")
    matches = [item for item in bindings if item.get("binding_id") == binding_id]
    if len(matches) != 1:
        raise ValueError("QUALIFICATION_BINDING_INVALID")
    binding = matches[0]
    reasoning = binding.get("reasoning")
    if binding.get("provider") != "claude_code" or binding.get("status") != "candidate" or binding.get("binding_sha256") != canonical({key: value for key, value in binding.items() if key != "binding_sha256"}) or not isinstance(reasoning, dict):
        raise ValueError("QUALIFICATION_BINDING_INVALID")
    effort = reasoning.get("default_effort")
    if (reasoning.get("supported") is True and (effort not in reasoning.get("allowed_efforts", []) or not isinstance(effort, str))) or (reasoning.get("supported") is False and (effort is not None or reasoning.get("allowed_efforts") != [])):
        raise ValueError("QUALIFICATION_BINDING_INVALID")
    return registry, binding


def qualification_files(current: bool, v3: bool = False) -> tuple[str, ...]:
    return V3_CANDIDATE_FILES if v3 else CURRENT_CANDIDATE_FILES if current else CANDIDATE_FILES


def workspace_candidate_path(workspace: Path, relative: str, current: bool) -> Path:
    copied = relative if current else relative.removeprefix("skills/agent-council/")
    return workspace / "candidate" / copied


def workspace_candidate_digest(workspace: Path, current: bool = False, v3: bool = False) -> str:
    files = []
    for relative in qualification_files(current, v3):
        files.append((relative, workspace_candidate_path(workspace, relative, current)))
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


def evaluator_instructions(current: bool = False, v3: bool = False, binding: dict[str, Any] | None = None) -> str:
    vocabulary = json.dumps(CLAIM_VOCABULARY, indent=2)
    candidate_read = (
        "Read candidate/skills/agent-council/SKILL.md and every supplied file under candidate/skills/agent-council/references, candidate/profiles, and candidate/standards."
        if current else
        "Read candidate/SKILL.md and every file under candidate/references, candidate/profiles, and candidate/standards."
    )
    if v3:
        required_paths = "\n".join(f"- candidate/{relative}" for relative in qualification_files(True, True))
        candidate_read = (
            "Use Read to read every required candidate file below in full, including the registry schema and nested standards/model-qualifications file. "
            "Directory listings, searches, and summaries do not replace reading these files.\n\n"
            f"Required candidate files:\n{required_paths}\n\n"
            "Before answering, check that every listed file was successfully read."
        )
    if binding is not None:
        return (role_protocol.INSTRUCTIONS + "\n" + candidate_read
                + "\nApply candidate/" + role_protocol.ROLE_FILES[binding["tier"]]
                + " as your role contract; complete lower-role tasks within their scope."
                + "\nThen read requests.json and complete every task. Use Read only inside this workspace."
                + "\nFinal response: one bare raw JSON object, with no Markdown code fences, preamble, or suffix.\n")
    return f"""You are evaluating the supplied Agent Council candidate, not modifying it.

{candidate_read} Then read requests.json. For each request, decide the behavior required by the candidate rules.

Return one JSON object and no markdown. Use this schema:
{{"schema_version":"agent-council.claude-native-response/v1","results":[{{"scenario_id":"GFT01","claims":["claim"],"rationale":"one short sentence"}}]}}

Return every scenario exactly once. Select only claims from this vocabulary. Use only the claims that apply to that scenario. Use read operations only inside this workspace. Do not run commands, modify files, delegate, browse, or inspect outside paths.

Claim vocabulary:
{vocabulary}
"""


def launch_command(run_id: str, session_id: str, model_id: str, effort: str | None, *, v3: bool = False) -> list[str]:
    return (["claude", "--model", model_id] + (["--effort", effort] if effort is not None else [])
            + ["--safe-mode", "--restricted", "--no-chrome", "--strict-mcp-config", "--tools", "Read,Glob,Grep"]
            + (["--disallowedTools", "EndConversation"] if v3 else [])
            + ["--session-id", session_id, "--name", f"Agent Council {run_id}", PROMPT])


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
    binding_id = getattr(args, "binding_id", None)
    registry = binding = None
    if binding_id:
        registry, binding = registry_binding(binding_id)
        model_id = binding["model_id"]
        effort = binding["reasoning"]["default_effort"]
        if (getattr(args, "model_id", None) is not None and args.model_id != model_id) or (getattr(args, "effort", None) is not None and args.effort != effort):
            raise ValueError("QUALIFICATION_BINDING_ASSERTION_MISMATCH")
    else:
        model_id = getattr(args, "model_id", None)
        effort = getattr(args, "effort", None) or "high"
    if args.run_id not in RUN_IDS or (not binding_id and (model_id != MODEL_ID or effort not in {"medium", "high"})) or parsed_session_id != args.session_id.lower():
        raise ValueError("QUALIFICATION_ARGUMENT_INVALID")
    output.mkdir(parents=True, exist_ok=True)
    current = getattr(args, "current", False) or bool(binding_id)
    for relative in qualification_files(current, bool(binding_id)):
        source = ROOT / relative
        target = workspace_candidate_path(output, relative, current)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    (output / "requests.json").write_text(json.dumps({"schema_version": "agent-council.blind-requests/v1", "scenarios": role_protocol.blind_requests(binding) if binding else scenario_requests()}, indent=2) + "\n", encoding="utf-8")
    (output / "evaluator-instructions.md").write_text(evaluator_instructions(current, bool(binding_id), binding), encoding="utf-8")
    bundle_sha = tree_digest(output, bundle_paths(output))
    command = launch_command(args.run_id, args.session_id, model_id, effort, v3=bool(binding_id))
    manifest = {
        "schema_version": "agent-council.claude-qualification-run/v3" if binding_id else "agent-council.claude-qualification-run/v2" if current else "agent-council.claude-qualification-run/v1",
        "run_id": args.run_id,
        "session_id": args.session_id,
        "requested_model_id": model_id,
        "requested_effort": effort,
        "candidate_sha256": workspace_candidate_digest(output, current, bool(binding_id)),
        "evaluation_bundle_sha256": bundle_sha,
        "clean_context": True,
        "blind": True,
        "launch_command": command,
    }
    if current:
        manifest["release_binding"] = current_release_binding()
    if binding_id:
        manifest.update({"registry_version": registry["registry_version"], "registry_sha256": registry["registry_sha256"], "binding_id": binding_id, "binding_sha256": binding["binding_sha256"], "eval_suite_sha256": manifest["release_binding"]["eval_suite_sha256"]})
        manifest["qualification_protocol"] = role_protocol.protocol_binding(binding)
    (output / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def transcript_effort_matches(row: dict[str, Any], requested_effort: str | None) -> bool:
    if requested_effort is None:
        return row.get("effort") is None and "perTurnEffort" in row and row["perTurnEffort"] is None
    per_turn = row.get("perTurnEffort", requested_effort)
    return "effort" in row and row["effort"] == requested_effort and (per_turn is None or per_turn == requested_effort)


def extract_response(transcript: Path, expected_model: str, expected_session_id: str, expected_workspace: Path, expected_run_id: str) -> tuple[str, dict[str, Any]]:
    manifest = json.loads((expected_workspace / MANIFEST).read_text(encoding="utf-8"))
    v3 = manifest.get("schema_version") == "agent-council.claude-qualification-run/v3"
    models: list[str] = []
    texts: list[tuple[int, str]] = []
    session_ids: set[str] = set()
    workspaces: set[Path] = set()
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(transcript.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = strict_transcript_json(line)
        except (json.JSONDecodeError, ValueError) as error:
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
        if v3 and row.get("type") == "assistant" and (not isinstance(row.get("message"), dict) or row["message"].get("model") != expected_model or not transcript_effort_matches(row, manifest["requested_effort"])):
            raise ValueError("TRANSCRIPT_BINDING_MISMATCH")
        if row.get("type") != "assistant" or not isinstance(row.get("message"), dict):
            continue
        model = row["message"].get("model")
        if isinstance(model, str) and model:
            models.append(model)
        content = row["message"].get("content")
        if isinstance(content, list):
            text = "\n".join(item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text")
            texts.append((len(rows) - 1, text.strip()))
    if not models or any(model != expected_model for model in models):
        raise ValueError("MODEL_IDENTITY_MISMATCH")
    if session_ids != {expected_session_id}:
        raise ValueError("TRANSCRIPT_SESSION_MISMATCH")
    if workspaces != {expected_workspace.resolve()}:
        raise ValueError("TRANSCRIPT_WORKSPACE_MISMATCH")
    response_index, response = extract_qualification_json(texts)
    validate_qualification_tail(rows, response_index)

    conversational_users: list[tuple[int, dict[str, Any]]] = []
    for index, row in enumerate(rows[: response_index + 1]):
        if v3 and row.get("type") == "user" and row.get("isMeta") is True:
            raise ValueError("TRANSCRIPT_CONTEXT_NOT_CLEAN")
        if row.get("type") != "user" or row.get("isMeta") is True:
            continue
        message = row.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            conversational_users.append((index, row))
        elif v3:
            content = message.get("content") if isinstance(message, dict) else None
            if not conversational_users or not isinstance(content, list) or not content or any(not isinstance(item, dict) or item.get("type") != "tool_result" for item in content) or row.get("origin") == {"kind": "human"} or row.get("promptSource") == "typed":
                raise ValueError("TRANSCRIPT_CONTEXT_NOT_CLEAN")
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
    current = manifest.get("schema_version") in {"agent-council.claude-qualification-run/v2", "agent-council.claude-qualification-run/v3"}
    for relative in qualification_files(current, v3):
        required_reads.add(workspace_candidate_path(expected_workspace, relative, current))
    requested_reads: dict[str, Path] = {}
    requested_tools: set[str] = set()
    completed_tools: set[str] = set()
    successful_reads: set[Path] = set()
    for row in rows[prompt_index + 1 : response_index + 1]:
        if row.get("type") == "user":
            message = row.get("message", {})
            for item in message.get("content", []) if isinstance(message.get("content"), list) else []:
                if not isinstance(item, dict) or item.get("type") != "tool_result":
                    continue
                tool_id = item.get("tool_use_id")
                if v3:
                    if not isinstance(tool_id, str) or tool_id not in requested_tools or tool_id in completed_tools:
                        raise ValueError("TRANSCRIPT_CONTEXT_NOT_CLEAN")
                    completed_tools.add(tool_id)
                if item.get("is_error") is True:
                    continue
                content = item.get("content")
                if isinstance(tool_id, str) and tool_id in requested_reads and isinstance(content, str) and content:
                    successful_reads.add(requested_reads[tool_id])
            continue
        if row.get("type") != "assistant":
            continue
        if row.get("isSidechain") is not False or row.get("entrypoint") != "cli" or (not transcript_effort_matches(row, manifest["requested_effort"]) if v3 else row.get("effort") != manifest.get("requested_effort", "high")):
            raise ValueError("TRANSCRIPT_NATIVE_ASSISTANT_INVALID")
        message = row.get("message", {})
        for item in message.get("content", []) if isinstance(message.get("content"), list) else []:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            name = item.get("name")
            inputs = item.get("input")
            if name not in {"Read", "Glob", "Grep"} or not isinstance(inputs, dict):
                raise ValueError("TRANSCRIPT_TOOL_NOT_ALLOWED")
            if v3:
                tool_id = item.get("id")
                if not isinstance(tool_id, str) or not tool_id or tool_id in requested_tools:
                    raise ValueError("TRANSCRIPT_TOOL_RESULT_INVALID")
                requested_tools.add(tool_id)
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
    v3 = manifest.get("schema_version") == "agent-council.claude-qualification-run/v3"
    current = manifest.get("schema_version") in {"agent-council.claude-qualification-run/v2", "agent-council.claude-qualification-run/v3"}
    if manifest.get("schema_version") not in {"agent-council.claude-qualification-run/v1", "agent-council.claude-qualification-run/v2", "agent-council.claude-qualification-run/v3"} or manifest.get("run_id") not in RUN_IDS or (not v3 and (manifest.get("requested_model_id") != MODEL_ID or manifest.get("requested_effort", "high") not in {"medium", "high"})) or manifest_session != manifest.get("session_id"):
        raise ValueError("QUALIFICATION_MANIFEST_INVALID")
    if not v3 and any(key in manifest for key in ("registry_version", "registry_sha256", "binding_id", "binding_sha256", "eval_suite_sha256")):
        raise ValueError("QUALIFICATION_MANIFEST_INVALID")
    if v3:
        registry, binding = registry_binding(manifest.get("binding_id"))
        if any(manifest.get(key) != value for key, value in {"registry_version": registry["registry_version"], "registry_sha256": registry["registry_sha256"], "binding_sha256": binding["binding_sha256"], "requested_model_id": binding["model_id"], "requested_effort": binding["reasoning"]["default_effort"], "eval_suite_sha256": current_release_binding()["eval_suite_sha256"]}.items()) or "requested_effort" not in manifest:
            raise ValueError("QUALIFICATION_BINDING_CHANGED")
        if "qualification_protocol" in manifest and manifest["qualification_protocol"] != role_protocol.protocol_binding(binding):
            raise ValueError("QUALIFICATION_PROTOCOL_CHANGED")
    if current and manifest.get("release_binding") != current_release_binding():
        raise ValueError("QUALIFICATION_RELEASE_CHANGED")
    if manifest.get("launch_command") != launch_command(manifest["run_id"], manifest["session_id"], manifest["requested_model_id"], manifest.get("requested_effort", "high"), v3=v3):
        raise ValueError("QUALIFICATION_LAUNCH_COMMAND_INVALID")
    if manifest.get("clean_context") is not True or manifest.get("blind") is not True:
        raise ValueError("QUALIFICATION_ISOLATION_INVALID")
    if workspace_candidate_digest(workspace, current, v3) != manifest.get("candidate_sha256"):
        raise ValueError("QUALIFICATION_CANDIDATE_CHANGED")
    if current and manifest["candidate_sha256"] != named_file_digest([(relative, ROOT / relative) for relative in qualification_files(current, v3)]):
        raise ValueError("QUALIFICATION_CANDIDATE_CHANGED")
    if tree_digest(workspace, bundle_paths(workspace)) != manifest.get("evaluation_bundle_sha256"):
        raise ValueError("QUALIFICATION_BUNDLE_CHANGED")
    actual_model, response = extract_response(args.transcript.resolve(), manifest["requested_model_id"], manifest["session_id"], workspace, manifest["run_id"])
    details = score_scenarios(response, current, binding if v3 and "qualification_protocol" in manifest else None)
    result = "passed" if all(item["status"] == "passed" for item in details) else "failed"
    receipt = {
        "schema_version": "agent-council.claude-qualification-receipt/v3" if v3 else "agent-council.claude-qualification-receipt/v2" if current else "agent-council.claude-qualification-receipt/v1",
        "run_id": manifest["run_id"],
        "session_id": manifest["session_id"],
        "requested_model_id": manifest["requested_model_id"],
        "actual_model_id": actual_model,
        "requested_effort": manifest.get("requested_effort", "high"),
        "actual_effort": manifest.get("requested_effort", "high"),
        "candidate_sha256": manifest["candidate_sha256"],
        "evaluation_bundle_sha256": manifest["evaluation_bundle_sha256"],
        "transcript_sha256": digest_bytes(args.transcript.resolve().read_bytes()),
        "clean_context": True,
        "blind": True,
        "scenario_results": details,
        "result": result,
    }
    if current:
        receipt["release_binding"] = manifest["release_binding"]
    if v3:
        receipt.update({key: manifest[key] for key in ("registry_version", "registry_sha256", "binding_id", "binding_sha256", "eval_suite_sha256")})
    if "qualification_protocol" in manifest:
        receipt["qualification_protocol"] = manifest["qualification_protocol"]
        receipt["response"] = response
    args.receipt.resolve().write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if result != "passed":
        raise ValueError("QUALIFICATION_SCENARIOS_FAILED")
    return receipt


def score_scenarios(response: dict[str, Any], current: bool, binding: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if binding is not None:
        return role_protocol.score_response(response, binding)
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
    allowed_additional = CURRENT_ALLOWED_ADDITIONAL_CLAIMS if current else ALLOWED_ADDITIONAL_CLAIMS
    for scenario_id in sorted(EXPECTED_CLAIMS):
        missing = sorted(EXPECTED_CLAIMS[scenario_id] - actual[scenario_id])
        unexpected = sorted(actual[scenario_id] - EXPECTED_CLAIMS[scenario_id])
        disallowed = sorted(set(unexpected) - allowed_additional.get(scenario_id, set()))
        status = "passed" if not missing and not disallowed else "failed"
        details.append({"scenario_id": scenario_id, "status": status, "missing_claims": missing, "additional_claims": unexpected, "disallowed_additional_claims": disallowed})
    return details


def validate_pair(args: argparse.Namespace) -> dict[str, Any]:
    receipts = [json.loads(path.read_text(encoding="utf-8")) for path in args.receipt]
    if any(item.get("schema_version") == "agent-council.claude-qualification-receipt/v3" for item in receipts):
        if len(receipts) != 2 or any(item.get("schema_version") != "agent-council.claude-qualification-receipt/v3" for item in receipts) or {item.get("run_id") for item in receipts} != RUN_IDS:
            raise ValueError("QUALIFICATION_RECEIPT_INVALID")
        first = receipts[0]
        registry, binding = registry_binding(first.get("binding_id"))
        release = current_release_binding()
        expected = {"registry_version": registry["registry_version"], "registry_sha256": registry["registry_sha256"], "binding_id": binding["binding_id"], "binding_sha256": binding["binding_sha256"], "requested_model_id": binding["model_id"], "actual_model_id": binding["model_id"], "requested_effort": binding["reasoning"]["default_effort"], "actual_effort": binding["reasoning"]["default_effort"], "eval_suite_sha256": release["eval_suite_sha256"], "release_binding": release, "candidate_sha256": named_file_digest([(relative, ROOT / relative) for relative in V3_CANDIDATE_FILES])}
        expected["qualification_protocol"] = role_protocol.protocol_binding(binding)
        for item in receipts:
            if any(key not in item or item[key] != value for key, value in expected.items()) or item.get("result") != "passed" or item.get("clean_context") is not True or item.get("blind") is not True or not isinstance(item.get("scenario_results"), list):
                raise ValueError("QUALIFICATION_RECEIPT_INVALID")
            role_protocol.validate_results(item["scenario_results"], binding)
            if role_protocol.score_response(item.get("response"), binding) != item["scenario_results"]:
                raise ValueError("QUALIFICATION_RECEIPT_INVALID")
            if not all(isinstance(item.get(key), str) and re.fullmatch(r"[a-f0-9]{64}", item[key]) for key in ("evaluation_bundle_sha256", "transcript_sha256")):
                raise ValueError("QUALIFICATION_RECEIPT_INVALID")
        if len({item.get("session_id") for item in receipts}) != 2 or any(not isinstance(item.get("session_id"), str) or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", item["session_id"]) for item in receipts):
            raise ValueError("QUALIFICATION_CONTEXTS_NOT_FRESH")
        if len({item["evaluation_bundle_sha256"] for item in receipts}) != 1:
            raise ValueError("QUALIFICATION_CANDIDATE_MISMATCH")
        return {"schema_version": "agent-council.claude-qualification-pair/v3", "result": "passed", "model_id": binding["model_id"], "effort": binding["reasoning"]["default_effort"], "candidate_sha256": first["candidate_sha256"], "evaluation_bundle_sha256": first["evaluation_bundle_sha256"], "eval_suite_sha256": first["eval_suite_sha256"], "registry_version": first["registry_version"], "registry_sha256": first["registry_sha256"], "binding_id": first["binding_id"], "binding_sha256": first["binding_sha256"], "release_binding": release, "run_ids": sorted(RUN_IDS), "session_ids": sorted(item["session_id"] for item in receipts), "qualification_protocol": expected["qualification_protocol"]}
    current = any(item.get("schema_version") == "agent-council.claude-qualification-receipt/v2" for item in receipts)
    if getattr(args, "require_current", False) and not current:
        raise ValueError("QUALIFICATION_CURRENT_EVIDENCE_REQUIRED")
    receipt_schema = "agent-council.claude-qualification-receipt/v2" if current else "agent-council.claude-qualification-receipt/v1"
    if len(receipts) != 2 or {item.get("run_id") for item in receipts} != RUN_IDS:
        raise ValueError("QUALIFICATION_RUN_SET_INVALID")
    if any(item.get("result") != "passed" or item.get("clean_context") is not True or item.get("blind") is not True for item in receipts):
        raise ValueError("QUALIFICATION_RUN_FAILED")
    for item in receipts:
        results = item.get("scenario_results")
        if item.get("schema_version") != receipt_schema or item.get("requested_model_id") != MODEL_ID or item.get("actual_effort", item.get("requested_effort", "high")) != item.get("requested_effort", "high") or not isinstance(results, list):
            raise ValueError("QUALIFICATION_RECEIPT_INVALID")
        if current and (not isinstance(item.get("requested_effort"), str) or item["requested_effort"] not in {"medium", "high"} or not isinstance(item.get("actual_effort"), str) or item["actual_effort"] not in {"medium", "high"}):
            raise ValueError("QUALIFICATION_RECEIPT_INVALID")
        if current and item.get("release_binding") != current_release_binding():
            raise ValueError("QUALIFICATION_RELEASE_CHANGED")
        if current and item.get("candidate_sha256") != named_file_digest([(relative, ROOT / relative) for relative in CURRENT_CANDIDATE_FILES]):
            raise ValueError("QUALIFICATION_CANDIDATE_CHANGED")
        if {result.get("scenario_id") for result in results if isinstance(result, dict)} != set(EXPECTED_CLAIMS) or any(not isinstance(result, dict) or result.get("status") != "passed" or result.get("missing_claims") or result.get("disallowed_additional_claims") for result in results):
            raise ValueError("QUALIFICATION_RECEIPT_INVALID")
    if {item.get("actual_model_id") for item in receipts} != {MODEL_ID} or len({item.get("requested_effort", "high") for item in receipts}) != 1:
        raise ValueError("MODEL_IDENTITY_MISMATCH")
    if len({item.get("session_id") for item in receipts}) != 2:
        raise ValueError("QUALIFICATION_CONTEXTS_NOT_FRESH")
    if len({item.get("candidate_sha256") for item in receipts}) != 1 or len({item.get("evaluation_bundle_sha256") for item in receipts}) != 1:
        raise ValueError("QUALIFICATION_CANDIDATE_MISMATCH")
    result = {"schema_version": "agent-council.claude-qualification-pair/v2" if current else "agent-council.claude-qualification-pair/v1", "result": "passed", "model_id": MODEL_ID, "effort": receipts[0].get("requested_effort", "high"), "candidate_sha256": receipts[0]["candidate_sha256"], "evaluation_bundle_sha256": receipts[0]["evaluation_bundle_sha256"], "run_ids": sorted(RUN_IDS), "session_ids": sorted(item["session_id"] for item in receipts)}
    if current:
        result["release_binding"] = receipts[0]["release_binding"]
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    commands = value.add_subparsers(dest="command", required=True)
    prepared = commands.add_parser("prepare")
    prepared.add_argument("--output", required=True, type=Path)
    prepared.add_argument("--run-id", required=True)
    prepared.add_argument("--session-id", required=True)
    prepared.add_argument("--model-id")
    prepared.add_argument("--effort", choices=("medium", "high"))
    prepared.add_argument("--binding-id", help="Prepare v3 evidence for an exact Claude candidate binding")
    prepared.add_argument("--current", action="store_true", help="Prepare historical v2 qualification bound to current behavior and eval suite; v3 release evidence uses --binding-id")
    scored = commands.add_parser("score")
    scored.add_argument("--workspace", required=True, type=Path)
    scored.add_argument("--transcript", required=True, type=Path)
    scored.add_argument("--receipt", required=True, type=Path)
    paired = commands.add_parser("validate-pair")
    paired.add_argument("--receipt", required=True, action="append", type=Path)
    paired.add_argument("--require-current", action="store_true", help="Reject historical v1 receipts in v2 pair validation; v3 pairs are bound to an exact binding")
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
