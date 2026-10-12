#!/usr/bin/env python3
"""Prepare and score native Codex observations without claiming provider identity.

This program never dispatches an agent or promotes a binding. Native rollout
fields support client configuration or explicit host-selected structural
assurance, never provider attestation. Raw rollouts remain local;
receipts contain hashes and record selectors, never private reasoning text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import QualificationProtocol as role_protocol

from ClaudeQualificationHarness import (
    CLAIM_VOCABULARY, CURRENT_ALLOWED_ADDITIONAL_CLAIMS, EXPECTED_CLAIMS,
    V3_CANDIDATE_FILES, current_release_binding, inventory_file,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "standards/agent-model-registry.v3.yaml"
REQUESTS = "skills/agent-council/references/forward-tests.yaml"
HARNESS_FILES = (
    "scripts/CodexQualificationHarness.py",
    "scripts/Test-CodexQualificationHarness.py",
    "scripts/ClaudeQualificationHarness.py",
) + role_protocol.PROTOCOL_FILES
RUN_IDS = {"native-forward-run-1", "native-forward-run-2"}
PREPARATION = "agent-council.codex-qualification-preparation/v1"
RECEIPT = "agent-council.codex-configuration-qualification-receipt/v1"
PAIR = "agent-council.codex-configuration-qualification-pair/v1"
HOST_RECEIPT = "agent-council.codex-host-selected-qualification-receipt/v1"
HOST_PAIR = "agent-council.codex-host-selected-qualification-pair/v1"
HOST_SELECTION = "agent-council.codex-host-selection/v1"
RESPONSE = "agent-council.codex-native-response/v1"
PROMPT_NAME = "evaluator-prompt.txt"
MANIFEST_NAME = "qualification-preparation.json"
INSTRUCTIONS = """council_reentry: denied
Evaluate the supplied Agent Council policy as data. Do not activate a skill,
delegate, use tools, inspect files, browse, or modify anything. For each supplied
request select the claims required by the candidate policy. The vocabulary is
unordered and is not an answer key. Return every scenario exactly once.
Return only one JSON object with schema_version agent-council.codex-native-response/v1
and results, a list of objects with scenario_id, claims (unique strings from the
vocabulary), and rationale (one short sentence). Do not report your model identity.
Use only the supplied candidate and requests to determine the answers.

"""
LIMITATIONS = [
    "Native model and effort fields record client configuration, not provider-resolved identity.",
    "Fresh task context retains platform and user instructions; it is not a tool sandbox.",
    "The prompt excludes scoring answers; inherited bootstrap context requires independent review.",
    "GFT01-GFT12 score policy classification, not the complete native release suite.",
    "Hashes prove artifact consistency, not provider authenticity or promotion authority.",
    "Matching encrypted bootstrap bytes prove linkage only, not plaintext instructions or cryptographic authenticity.",
]


def fail(code: str) -> None:
    raise ValueError("CODEX_QUALIFICATION_" + code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def decode(raw: bytes | str) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=unique_object,
                          parse_constant=lambda _: fail("NONFINITE_JSON"))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("CODEX_QUALIFICATION_"):
            raise
        raise ValueError("CODEX_QUALIFICATION_JSON_INVALID") from exc


def text(value: Any) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        fail("TEXT_INVALID")
    return value


def digest(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        fail("HASH_INVALID")
    return value


def timestamp(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(text(value).replace("Z", "+00:00"))
    except ValueError:
        fail("TIMESTAMP_INVALID")
    if result.utcoffset() is None:
        fail("TIMESTAMP_OFFSET_MISSING")
    return result


def read_regular(path: Path) -> bytes:
    path = path.absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        fail("SYMLINK_UNSUPPORTED")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        fail("FILE_NOT_REGULAR")
    raw = path.read_bytes()
    after = path.stat()
    if any(part.is_symlink() for part in (path, *path.parents)):
        fail("SYMLINK_UNSUPPORTED")
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        fail("FILE_CHANGED_DURING_READ")
    return raw


def named_digest(files: dict[str, bytes]) -> str:
    result = hashlib.sha256()
    for relative, raw in sorted(files.items()):
        name = relative.encode("utf-8")
        result.update(len(name).to_bytes(8, "big"))
        result.update(name)
        result.update(len(raw).to_bytes(8, "big"))
        result.update(raw)
    return result.hexdigest()


def scenario_requests(raw: bytes) -> list[dict[str, str]]:
    scenarios: dict[str, str] = {}
    current = None
    for line in raw.decode("utf-8").splitlines():
        match = re.fullmatch(r'\s*- id: "(GFT\d{2})"', line)
        if match:
            current = match.group(1)
        match = re.fullmatch(r'\s+request: (".*")', line)
        if match and current in EXPECTED_CLAIMS:
            if current in scenarios:
                fail("DUPLICATE_REQUEST")
            scenarios[current] = text(decode(match.group(1)))
            current = None
    if set(scenarios) != set(EXPECTED_CLAIMS):
        fail("REQUEST_SET_INVALID")
    return [{"scenario_id": key, "request": scenarios[key]} for key in sorted(scenarios)]


def candidate(root: Path, binding_id: str | None = None) -> tuple[dict[str, Any], bytes]:
    """Freeze existing release bytes, including this collector and its scorer."""
    release = current_release_binding(root)
    required = set(V3_CANDIDATE_FILES) | set(HARNESS_FILES) | {REQUESTS}
    if not required <= set(release["behavioral_identity"]["paths"]):
        fail("HARNESS_OR_INPUT_NOT_IN_INVENTORY")
    files = {name: read_regular(inventory_file(root, name)) for name in sorted(required)}
    for name in HARNESS_FILES:
        if files[name] != read_regular(ROOT / name):
            fail("COLLECTOR_IMPLEMENTATION_MISMATCH")
    registry = decode(files[REGISTRY])
    if not isinstance(registry, dict) or registry.get("schema_version") != "agent-council.model-registry/v3" or registry.get("registry_version") != "v3":
        fail("REGISTRY_INVALID")
    if registry.get("registry_sha256") != sha(canonical({k: v for k, v in registry.items() if k != "registry_sha256"})):
        fail("REGISTRY_HASH_MISMATCH")
    bindings = registry.get("bindings")
    if not isinstance(bindings, list) or any(not isinstance(item, dict) for item in bindings):
        fail("BINDINGS_INVALID")
    ids = [item.get("binding_id") for item in bindings]
    if any(not isinstance(item, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{2,127}", item) is None for item in ids) or len(set(ids)) != len(ids):
        fail("BINDINGS_INVALID")
    codex = [item for item in bindings if item.get("provider") == "codex"]
    if not codex:
        fail("BINDINGS_INVALID")
    if registry.get("provider_states", {}).get("codex") != {"council_status": "fail_closed_until_qualified"}:
        fail("PROVIDER_NOT_CANDIDATE")
    for binding in codex:
        reasoning = binding.get("reasoning")
        if binding.get("status") != "candidate" or not isinstance(reasoning, dict):
            fail("BINDING_NOT_CANDIDATE")
        if binding.get("binding_sha256") != sha(canonical({k: v for k, v in binding.items() if k != "binding_sha256"})):
            fail("BINDING_HASH_MISMATCH")
        text(binding.get("model_id"))
        effort = reasoning.get("default_effort")
        if reasoning.get("supported") is not True or effort not in {"low", "medium", "high", "xhigh", "max", "ultra"} or effort not in reasoning.get("allowed_efforts", []):
            fail("EFFORT_INVALID")
    selected = None
    if binding_id is not None:
        selected = one([binding for binding in codex if binding["binding_id"] == binding_id], "BINDING_INVALID")
        codex = [selected]
    public = {
        "schema_version": "agent-council.codex-blind-input/v1",
        "candidate_files": [{"path": name, "content": files[name].decode("utf-8")} for name in V3_CANDIDATE_FILES],
        "requests": scenario_requests(files[REQUESTS]),
        "claim_vocabulary": CLAIM_VOCABULARY,
    }
    prompt = INSTRUCTIONS.encode("utf-8") + canonical(public) + b"\n"
    protocol = {}
    if selected is not None:
        protocol = {"qualification_protocol": role_protocol.protocol_binding(selected)}
        for role, expected_hash in protocol["qualification_protocol"]["role_contract_sha256"].items():
            if sha(files[role_protocol.ROLE_FILES[role]]) != expected_hash:
                fail("ROLE_CONTRACT_IMPLEMENTATION_MISMATCH")
        public = {"schema_version": "agent-council.role-blind-input/v1",
                  "candidate_files": public["candidate_files"],
                  "role": selected["tier"],
                  "role_contract": role_protocol.ROLE_FILES[selected["tier"]],
                  "requests": role_protocol.blind_requests(selected)}
        prompt = (role_protocol.INSTRUCTIONS + "\nUse the packaged role contract identified by role_contract. Complete lower-role tasks within their scope. Do not use tools or inspect files.\n").encode("utf-8") + canonical(public) + b"\n"
    if any(read_regular(root / name) != raw for name, raw in files.items()) or current_release_binding(root) != release:
        fail("CANDIDATE_CHANGED_DURING_FREEZE")
    return {"release_binding": release, "registry_sha256": registry["registry_sha256"],
            "registry_file_sha256": sha(files[REGISTRY]), "bindings": sorted(codex, key=lambda item: item["binding_id"]),
            "candidate_sha256": named_digest({name: files[name] for name in V3_CANDIDATE_FILES}),
            "evaluation_bundle_sha256": sha(prompt), "prompt_sha256": sha(prompt),
            "eval_suite_sha256": release["eval_suite_sha256"], **protocol}, prompt


def task_name(freeze_id: str, binding_id: str, run_id: str) -> str:
    """Preserve distinct dispatch identities within native task-name syntax."""
    return "cq_" + sha(canonical([freeze_id, binding_id, run_id]))


def file_delivery(prompt_path: str, prompt_sha256: str) -> dict[str, str]:
    """Exact read protocol. Paths remain original when evidence is archived."""
    path = Path(text(prompt_path))
    if not path.is_absolute() or str(path) != prompt_path or ".." in path.parts or path.name != PROMPT_NAME:
        fail("FILE_PROMPT_PATH_INVALID")
    digest(prompt_sha256)
    command = "cat -- " + shlex.quote(prompt_path)
    arguments = {"cmd": command, "shell": "/bin/sh", "login": False,
                 "max_output_tokens": 60000, "yield_time_ms": 10000}
    code = ('// @exec: {"max_output_tokens":60000}\n'
            'const r = await tools.exec_command(' + canonical(arguments).decode("utf-8") + ');\n'
            'if (r.exit_code !== 0 || r.session_id !== undefined) throw new Error("PROMPT_READ_FAILED");\n'
            'text(r.output);')
    message = ("council_reentry: denied\nRead the frozen blind prompt exactly once, then answer it.\n"
               "Do not activate skills, delegate, inspect other files, or send commentary.\n"
               f"Prompt: {prompt_path}\nSHA256: {prompt_sha256}\n"
               "Your only tool call must be functions.exec with exactly this input:\n"
               + code + "\nAfter that call, use only its complete returned prompt and produce the requested final JSON.\n"
               "No other tool calls or extra turns are permitted. The prompt's no-tools rule applies after this read.\n")
    return {"prompt_path": prompt_path, "prompt_sha256": prompt_sha256,
            "read_command": command, "read_call_input": code, "spawn_message": message}


def preparation_delivery(manifest: dict[str, Any]) -> dict[str, str] | None:
    mode = manifest.get("delivery_mode", "inline")
    if mode == "inline" and "file_delivery" not in manifest:
        return None
    delivery = manifest.get("file_delivery")
    if mode != "file" or not isinstance(delivery, dict):
        fail("FILE_DELIVERY_INVALID")
    if delivery != file_delivery(delivery.get("prompt_path"), manifest["prompt_sha256"]):
        fail("FILE_DELIVERY_INVALID")
    return delivery


def prepare(root: Path, output: Path, *, delivery_mode: str = "inline", binding_id: str | None = None) -> dict[str, Any]:
    if delivery_mode not in {"inline", "file"}:
        fail("DELIVERY_MODE_INVALID")
    frozen, prompt = candidate(root, binding_id)
    if output.exists() or output.is_symlink():
        fail("OUTPUT_ALREADY_EXISTS")
    if any(part.is_symlink() for part in output.absolute().parents):
        fail("SYMLINK_UNSUPPORTED")
    freeze_id = str(uuid.uuid4())
    delivery = file_delivery(str(output.absolute() / PROMPT_NAME), sha(prompt)) if delivery_mode == "file" else None
    plans = []
    for binding in frozen["bindings"]:
        for run_id in sorted(RUN_IDS):
            plans.append({"binding_id": binding["binding_id"], "run_id": run_id,
                          "spawn_arguments": {"task_name": task_name(freeze_id, binding["binding_id"], run_id),
                                              "model": binding["model_id"], "reasoning_effort": binding["reasoning"]["default_effort"],
                                              "fork_turns": "none"}, "message_file": PROMPT_NAME})
            if delivery:
                plans[-1]["spawn_arguments"]["message"] = delivery["spawn_message"]
                plans[-1]["prompt_file"] = plans[-1].pop("message_file")
    manifest = {"schema_version": PREPARATION, "freeze_id": freeze_id,
                "prepared_at": datetime.now(timezone.utc).isoformat(), **frozen,
                "dispatches": plans, "dispatch_performed": False,
                "identity_assurance": "client_configuration", "promotion_eligible": False}
    if delivery:
        manifest.update(delivery_mode="file", file_delivery=delivery)
    output.mkdir(parents=True)
    (output / PROMPT_NAME).write_bytes(prompt)
    if delivery:
        (output / PROMPT_NAME).chmod(0o444)
    (output / MANIFEST_NAME).write_bytes(canonical(manifest) + b"\n")
    return manifest


def load_preparation(root: Path, workspace: Path) -> tuple[dict[str, Any], str, str]:
    manifest_raw = read_regular(workspace / MANIFEST_NAME)
    manifest = decode(manifest_raw)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != PREPARATION or manifest.get("promotion_eligible") is not False or manifest.get("identity_assurance") != "client_configuration":
        fail("PREPARATION_INVALID")
    try:
        if str(uuid.UUID(manifest.get("freeze_id", ""))) != manifest["freeze_id"]:
            fail("PREPARATION_INVALID")
    except (ValueError, TypeError, AttributeError):
        fail("PREPARATION_INVALID")
    selected = manifest.get("bindings")
    binding_id = selected[0].get("binding_id") if "qualification_protocol" in manifest and isinstance(selected, list) and len(selected) == 1 and isinstance(selected[0], dict) else None
    if "qualification_protocol" in manifest and binding_id is None:
        fail("PREPARATION_INVALID")
    frozen, expected_prompt = candidate(root, binding_id)
    if any(manifest.get(key) != value for key, value in frozen.items()):
        fail("FROZEN_CANDIDATE_CHANGED")
    if read_regular(workspace / PROMPT_NAME) != expected_prompt:
        fail("PROMPT_CHANGED")
    preparation_delivery(manifest)
    return manifest, expected_prompt.decode("utf-8"), sha(manifest_raw)


def rows(raw: bytes) -> list[dict[str, Any]]:
    if not raw or not raw.endswith(b"\n"):
        fail("ROLLOUT_INCOMPLETE")
    result = [decode(line) for line in raw.splitlines()]
    if any(not isinstance(row, dict) or not isinstance(row.get("payload"), dict) for row in result):
        fail("ROLLOUT_SCHEMA_INVALID")
    return result


def one(items: list[Any], code: str) -> Any:
    if len(items) != 1:
        fail(code)
    return items[0]


def payloads(records: list[dict[str, Any]], kind: str, subtype: str | None = None) -> list[tuple[int, dict[str, Any]]]:
    return [(index, row["payload"]) for index, row in enumerate(records)
            if row.get("type") == kind and (subtype is None or row["payload"].get("type") == subtype)]


def content_text(value: Any, kind: str) -> str:
    if not isinstance(value, list) or not value or any(not isinstance(block, dict) or block.get("type") != kind or not isinstance(block.get("text"), str) for block in value):
        fail("TEXT_CONTENT_INVALID")
    return "".join(block["text"] for block in value)


def score_response(raw: str, binding: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    response = decode(raw)
    if binding is not None:
        return response, role_protocol.score_response(response, binding)
    if not isinstance(response, dict) or set(response) != {"schema_version", "results"} or response["schema_version"] != RESPONSE or not isinstance(response["results"], list):
        fail("RESPONSE_INVALID")
    actual: dict[str, set[str]] = {}
    for item in response["results"]:
        if not isinstance(item, dict) or set(item) != {"scenario_id", "claims", "rationale"}:
            fail("RESPONSE_INVALID")
        scenario = item["scenario_id"]
        claims = item["claims"]
        if not isinstance(scenario, str) or scenario not in EXPECTED_CLAIMS or scenario in actual or not isinstance(claims, list) or any(not isinstance(claim, str) for claim in claims) or len(set(claims)) != len(claims) or not set(claims) <= set(CLAIM_VOCABULARY) or not isinstance(item["rationale"], str) or not item["rationale"].strip():
            fail("RESPONSE_INVALID")
        actual[scenario] = set(claims)
    if set(actual) != set(EXPECTED_CLAIMS):
        fail("SCENARIO_SET_INVALID")
    scores = []
    for scenario in sorted(actual):
        missing = sorted(EXPECTED_CLAIMS[scenario] - actual[scenario])
        additional = sorted(actual[scenario] - EXPECTED_CLAIMS[scenario])
        disallowed = sorted(set(additional) - CURRENT_ALLOWED_ADDITIONAL_CLAIMS.get(scenario, set()))
        scores.append({"scenario_id": scenario, "status": "failed" if missing or disallowed else "passed",
                       "missing_claims": missing, "additional_claims": additional, "disallowed_additional_claims": disallowed})
    return response, scores


def verify_file_read(child: list[dict[str, Any]], delivery: dict[str, str], prompt: str,
                     delivery_index: int, final_index: int, turn_id: str, child_id: str) -> dict[str, Any]:
    """Accept one exact native functions.exec wrapper and its complete result."""
    tools = [(i, row["payload"]) for i, row in enumerate(child) if row["type"] == "response_item"
             and row["payload"].get("type") in {"function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output"}]
    if len(tools) != 2:
        fail("FILE_READ_COUNT_INVALID")
    (call_index, call), (result_index, result) = tools
    if (call.get("type") != "custom_tool_call" or call.get("name") not in {"exec", "functions.exec"}
            or call.get("input") not in (delivery["read_call_input"], delivery["read_call_input"] + "\n")
            or not (delivery_index < call_index < result_index < final_index)):
        fail("FILE_READ_CALL_INVALID")
    call_id = text(call.get("call_id"))
    if result.get("type") != "custom_tool_call_output" or result.get("call_id") != call_id:
        fail("FILE_READ_OUTPUT_INVALID")
    for item in (call, result):
        if item.get("internal_chat_message_metadata_passthrough", {}).get("turn_id") != turn_id:
            fail("FILE_READ_TURN_INVALID")
    output = result.get("output")
    if (not isinstance(output, list) or len(output) != 2
            or any(not isinstance(item, dict) or set(item) != {"type", "text"}
                   or item["type"] != "input_text" or not isinstance(item["text"], str) for item in output)
            or re.fullmatch(r"Script completed\nWall time [0-9]+(?:\.[0-9]+)? seconds\nOutput:\n", output[0]["text"]) is None
            or output[1]["text"].encode("utf-8") != prompt.encode("utf-8")):
        fail("FILE_READ_OUTPUT_INVALID")
    events = [(i, item) for i, item in payloads(child, "event_msg", "item_completed")
              if item.get("item", {}).get("type") == "CommandExecution"]
    if len(events) > 1:
        fail("FILE_READ_EVENT_INVALID")
    for index, event in events:
        item = event["item"]
        command = item.get("command")
        # New native events persist a bounded preview, not separate streams.
        # The linked tool result above remains the full-byte authority.
        raw = prompt.encode("utf-8")
        marker = b"\n... command output truncated for persistence ...\n"
        preview = raw if len(raw) <= 65536 else raw[:32743] + marker + raw[-32743:]
        aggregate = item.get("aggregated_output")
        legacy_streams = (item.get("stdout") == prompt and item.get("stderr") == ""
                          and aggregate == prompt)
        persisted_preview = ("stdout" not in item and "stderr" not in item
                             and isinstance(aggregate, str) and aggregate.encode("utf-8") == preview)
        if (not call_index < index < result_index or event.get("turn_id") != turn_id
                or event.get("thread_id") != child_id or not isinstance(command, list)
                or len(command) != 3 or command[0] not in {"/bin/zsh", "/bin/bash", "/bin/sh"}
                or command[1:] != ["-c", delivery["read_command"]]
                or item.get("status") != "completed" or type(item.get("exit_code")) is not int
                or item["exit_code"] != 0 or not (legacy_streams or persisted_preview)):
            fail("FILE_READ_EVENT_INVALID")
    return {"file_prompt_bytes_verified": True, "file_prompt_path": delivery["prompt_path"],
            "file_read_call_id": call_id, "file_read_call_line": call_index + 1,
            "file_read_result_line": result_index + 1}


def score(root: Path, workspace: Path, binding_id: str, run_id: str,
          parent_path: Path, child_path: Path) -> dict[str, Any]:
    manifest, prompt, manifest_sha = load_preparation(root, workspace)
    file_protocol = preparation_delivery(manifest)
    spawn_message = file_protocol["spawn_message"] if file_protocol else prompt
    if binding_id not in {item["binding_id"] for item in manifest["bindings"]} or run_id not in RUN_IDS:
        fail("RUN_SELECTION_INVALID")
    binding = one([item for item in manifest["bindings"] if item["binding_id"] == binding_id], "BINDING_INVALID")
    plans = manifest.get("dispatches")
    if not isinstance(plans, list):
        fail("DISPATCH_PLAN_INVALID")
    plan = one([item for item in plans if isinstance(item, dict) and item.get("binding_id") == binding_id and item.get("run_id") == run_id], "DISPATCH_PLAN_INVALID")
    expected_arguments = {"task_name": task_name(manifest["freeze_id"], binding_id, run_id),
                          "model": binding["model_id"], "reasoning_effort": binding["reasoning"]["default_effort"], "fork_turns": "none"}
    if file_protocol:
        expected_arguments["message"] = spawn_message
    if plan.get("spawn_arguments") != expected_arguments or plan.get("prompt_file" if file_protocol else "message_file") != PROMPT_NAME:
        fail("DISPATCH_PLAN_CHANGED")
    parent_raw, child_raw = read_regular(parent_path), read_regular(child_path)
    parent, child = rows(parent_raw), rows(child_raw)
    _, parent_meta = one(payloads(parent, "session_meta"), "PARENT_META_INVALID")
    meta_index, child_meta = one(payloads(child, "session_meta"), "CHILD_META_INVALID")
    parent_id, child_id = text(parent_meta.get("id")), text(child_meta.get("id"))
    if parent_id == child_id or meta_index != 0 or child_meta.get("model_provider") != "openai":
        fail("CHILD_META_INVALID")
    source = child_meta.get("source", {}).get("subagent", {}).get("thread_spawn", {})
    if not isinstance(source, dict) or source.get("parent_thread_id") != parent_id:
        fail("PARENT_LINK_MISMATCH")
    agent_path = text(source.get("agent_path"))
    expected_arguments["message"] = spawn_message
    calls = []
    for index, call in payloads(parent, "response_item", "function_call"):
        if call.get("name") not in {"spawn_agent", "collaboration.spawn_agent"}:
            continue
        args = decode(call.get("arguments", ""))
        if isinstance(args, dict) and args.get("task_name") == expected_arguments["task_name"]:
            calls.append((index, call, args))
    successful = []
    rejected = []
    for index, candidate_call, candidate_args in calls:
        candidate_id = text(candidate_call.get("call_id"))
        result_index, result = one([(i, item) for i, item in payloads(parent, "response_item", "function_call_output")
                                    if item.get("call_id") == candidate_id], "SPAWN_RESULT_INVALID")
        if result_index <= index:
            fail("SPAWN_RESULT_INVALID")
        if result.get("output") == "collab spawn failed: agent thread limit reached":
            rejected.append((index, candidate_args))
        else:
            try:
                linked = decode(result.get("output", "")) == {"task_name": agent_path}
            except ValueError:
                linked = False
            if not linked:
                fail("SPAWN_RESULT_INVALID")
            successful.append((index, candidate_call, candidate_args))
    call_index, call, args = one(successful, "SPAWN_CALL_INVALID")
    def valid_encrypted_message(candidate_args):
        opaque = candidate_args.get("message")
        return (file_protocol and isinstance(opaque, str)
                and re.fullmatch(r"gAAAA[A-Za-z0-9_-]{32,}={0,2}", opaque) is not None)

    def valid_rejected_arguments(candidate_args):
        if candidate_args == args:
            return True
        non_message = {key: value for key, value in candidate_args.items() if key != "message"}
        successful_non_message = {key: value for key, value in args.items() if key != "message"}
        return (non_message == successful_non_message and valid_encrypted_message(candidate_args)
                and valid_encrypted_message(args))

    if any(index >= call_index or not valid_rejected_arguments(candidate_args)
           for index, candidate_args in rejected):
        fail("SPAWN_RESULT_INVALID")
    encrypted_spawn = False
    if args != expected_arguments:
        # Native Desktop exports can redact the spawn message as the same opaque
        # encrypted_content delivered to the child. File bytes are independently
        # verified below; ciphertext is never treated as proof of the plaintext.
        non_message = {key: value for key, value in args.items() if key != "message"}
        expected_non_message = {key: value for key, value in expected_arguments.items() if key != "message"}
        if non_message != expected_non_message or not valid_encrypted_message(args):
            fail("SPAWN_ARGUMENTS_MISMATCH")
        encrypted_spawn = True
    call_id = text(call.get("call_id"))
    result_index, result = one([(index, item) for index, item in payloads(parent, "response_item", "function_call_output") if item.get("call_id") == call_id], "SPAWN_RESULT_INVALID")
    if agent_path.rsplit("/", 1)[-1] != args["task_name"]:
        fail("AGENT_PATH_MISMATCH")
    start_index, started = one(payloads(child, "event_msg", "task_started"), "CHILD_NOT_ONE_TURN")
    end_index, completed = one(payloads(child, "event_msg", "task_complete"), "CHILD_NOT_COMPLETED")
    context_index, context = one(payloads(child, "turn_context"), "CHILD_NOT_ONE_TURN")
    turn_id = text(started.get("turn_id"))
    if completed.get("turn_id") != turn_id or context.get("turn_id") != turn_id or not (start_index < context_index < end_index):
        fail("TURN_LINK_MISMATCH")
    started_at, completed_at = child[start_index].get("timestamp"), child[end_index].get("timestamp")
    if timestamp(completed_at) < timestamp(started_at):
        fail("COMPLETION_PRECEDES_START")
    if context.get("model") != binding["model_id"] or context.get("effort") != binding["reasoning"]["default_effort"]:
        fail("CLIENT_CONFIGURATION_MISMATCH")
    delivery_index, delivery = one(payloads(child, "response_item", "agent_message"), "TASK_DELIVERY_INVALID")
    author = agent_path.rsplit("/", 1)[0]
    header = f"Message Type: NEW_TASK\nTask name: {agent_path}\nSender: {author}\nPayload:\n"
    if delivery.get("author") != author or delivery.get("recipient") != agent_path or delivery.get("internal_chat_message_metadata_passthrough", {}).get("turn_id") != turn_id or not (context_index < delivery_index < end_index):
        fail("TASK_DELIVERY_INVALID")
    blocks = delivery.get("content")
    plaintext = False
    if isinstance(blocks, list) and len(blocks) == 2 and blocks[0] == {"type": "input_text", "text": header} and isinstance(blocks[1], dict) and blocks[1].get("type") == "encrypted_content" and isinstance(blocks[1].get("encrypted_content"), str) and blocks[1]["encrypted_content"]:
        if encrypted_spawn and blocks[1]["encrypted_content"] != args["message"]:
            fail("ENCRYPTED_TASK_LINK_MISMATCH")
    else:
        if encrypted_spawn:
            fail("ENCRYPTED_TASK_LINK_MISMATCH")
        if content_text(blocks, "input_text") != header + spawn_message:
            fail("TASK_PROMPT_MISMATCH")
        plaintext = True
    bootstrap = []
    bootstrap_metadata: set[str] = set()
    finals = []
    for index, row in enumerate(child):
        payload = row["payload"]
        if file_protocol and row["type"] in {"world_state", "inter_agent_communication_metadata"}:
            kind = row["type"]
            if kind in bootstrap_metadata:
                fail("FILE_BOOTSTRAP_METADATA_INVALID")
            if kind == "world_state":
                if (not start_index < index < context_index or set(payload) != {"full", "state"}
                        or payload["full"] is not True or not isinstance(payload["state"], dict)):
                    fail("FILE_BOOTSTRAP_METADATA_INVALID")
            elif not context_index < index < delivery_index or payload != {"trigger_turn": True}:
                fail("FILE_BOOTSTRAP_METADATA_INVALID")
            bootstrap_metadata.add(kind)
            bootstrap.append({"type": kind, "payload": payload})
            continue
        if row["type"] == "token_usage_record" and file_protocol:
            if payload.get("turn_id") != turn_id or payload.get("thread_id") != child_id or not start_index < index < end_index:
                fail("FILE_READ_USAGE_INVALID")
            continue
        if row["type"] not in {"session_meta", "turn_context", "event_msg", "response_item"}:
            fail("CHILD_RECORD_UNSUPPORTED")
        if row["type"] == "event_msg":
            subtype = payload.get("type")
            if subtype not in {"task_started", "task_complete", "token_count", "item_completed"}:
                fail("CHILD_EVENT_UNSUPPORTED")
            permitted_events = {"Reasoning", "AgentMessage"} | ({"CommandExecution"} if file_protocol else set())
            if subtype == "item_completed" and payload.get("item", {}).get("type") not in permitted_events:
                fail("CHILD_TOOL_OR_EVENT_UNSUPPORTED")
        if row["type"] != "response_item":
            continue
        subtype = payload.get("type")
        if file_protocol and subtype in {"function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output"}:
            continue
        if subtype not in {"message", "reasoning", "agent_message"}:
            fail("CHILD_TOOL_OR_ITEM_UNSUPPORTED")
        if subtype == "reasoning" and not (delivery_index < index < end_index):
            fail("REASONING_OUTSIDE_TASK")
        if subtype == "message":
            if payload.get("role") in {"system", "developer", "user"}:
                if index >= delivery_index:
                    fail("CHILD_CONTEXT_NOT_FRESH")
                bootstrap.append(payload)
            elif payload.get("role") == "assistant" and payload.get("phase") == "final_answer" and delivery_index < index < end_index:
                if payload.get("internal_chat_message_metadata_passthrough", {}).get("turn_id") != turn_id:
                    fail("FINAL_TURN_MISMATCH")
                finals.append((index, content_text(payload.get("content"), "output_text")))
            else:
                fail("UNEXPECTED_ASSISTANT_MESSAGE")
    final_index, final_text = one(finals, "FINAL_RESPONSE_INVALID")
    file_evidence = (verify_file_read(child, file_protocol, prompt, delivery_index, final_index, turn_id, child_id)
                     if file_protocol else {})
    if file_protocol:
        file_evidence.update(spawn_message_plaintext_verified=not encrypted_spawn,
                             task_bootstrap_plaintext_verified=plaintext and not encrypted_spawn,
                             encrypted_delivery_link_verified=encrypted_spawn)
    response, scores = score_response(final_text, binding if "qualification_protocol" in manifest else None)
    passed = all(item["status"] == "passed" for item in scores)
    evidence = {"parent_session_id": parent_id, "child_session_id": child_id, "agent_path": agent_path,
                "spawn_call_id": call_id, "turn_id": turn_id, "fork_turns": "none",
                "started_at": started_at, "completed_at": completed_at,
                "parent_transcript_sha256": sha(parent_raw), "child_transcript_sha256": sha(child_raw),
                "child_prompt_plaintext_verified": plaintext,
                **file_evidence,
                "bootstrap_context_sha256": sha(canonical(bootstrap)),
                "client_version": text(child_meta.get("cli_version")), "client_originator": text(child_meta.get("originator")),
                "source_lines": {"spawn_call": call_index + 1, "spawn_result": result_index + 1,
                                 "child_metadata": meta_index + 1, "turn_context": context_index + 1,
                                 "task_delivery": delivery_index + 1, "final_response": final_index + 1, "completion": end_index + 1}}
    receipt = {"schema_version": RECEIPT, "provider": "codex", "provenance": "native_session_export",
            "identity_assurance": "client_configuration", "evidence_assurance": "structural_only", "promotion_eligible": False,
            "provider_authenticity_verified": False, "result": "passed" if passed else "failed",
            "run_id": run_id, "session_id": child_id, "binding_id": binding_id,
            "binding_sha256": binding["binding_sha256"], "registry_version": "v3",
            **{key: manifest[key] for key in ("freeze_id", "registry_sha256", "registry_file_sha256", "release_binding", "candidate_sha256", "evaluation_bundle_sha256", "eval_suite_sha256", "prompt_sha256")},
            "preparation_sha256": manifest_sha, "requested_model_id": args["model"], "requested_effort": args["reasoning_effort"],
            "configured_model_id": context["model"], "configured_effort": context["effort"],
            "fresh_task": True, "blind_prompt": True, "full_context_blindness_verified": False,
            "tool_calls": 1 if file_protocol else 0, "council_reentry": "denied",
            "native_evidence": evidence, "response": response, "response_sha256": sha(canonical(response)),
            "native_response_text_sha256": sha(final_text.encode("utf-8")),
            "scenario_results": scores, "limitations": LIMITATIONS}
    if file_protocol:
        receipt["delivery_mode"] = "file"
    if "qualification_protocol" in manifest:
        receipt["qualification_protocol"] = manifest["qualification_protocol"]
    final_manifest, final_prompt, final_manifest_sha = load_preparation(root, workspace)
    if final_manifest != manifest or final_prompt != prompt or final_manifest_sha != manifest_sha:
        fail("PREPARATION_CHANGED_DURING_SCORE")
    return receipt


def validate_pair(receipts: list[dict[str, Any]], *, root: Path, workspace: Path,
                  native_transcripts: dict[str, tuple[Path, Path]]) -> dict[str, Any]:
    """Rederive both receipts from retained native snapshots before pairing."""
    manifest, _, manifest_sha = load_preparation(root, workspace)
    file_protocol = preparation_delivery(manifest)
    if len(receipts) != 2 or any(not isinstance(item, dict) for item in receipts):
        fail("PAIR_INVALID")
    if not isinstance(native_transcripts, dict) or set(native_transcripts) != RUN_IDS or any(
            not isinstance(paths, (tuple, list)) or len(paths) != 2 or
            any(not isinstance(path, Path) for path in paths) for paths in native_transcripts.values()):
        fail("PAIR_NATIVE_TRANSCRIPTS_REQUIRED")
    shared = ("freeze_id", "binding_id", "binding_sha256", "registry_version", "registry_sha256", "registry_file_sha256", "release_binding", "candidate_sha256", "evaluation_bundle_sha256", "eval_suite_sha256", "prompt_sha256", "preparation_sha256", "requested_model_id", "requested_effort", "configured_model_id", "configured_effort")
    if "qualification_protocol" in manifest:
        shared += ("qualification_protocol",)
    first = receipts[0]
    for receipt in receipts:
        if receipt.get("schema_version") != RECEIPT or receipt.get("result") != "passed" or receipt.get("provider") != "codex" or receipt.get("provenance") != "native_session_export" or receipt.get("evidence_assurance") != "structural_only" or receipt.get("promotion_eligible") is not False or receipt.get("provider_authenticity_verified") is not False or receipt.get("identity_assurance") != "client_configuration" or receipt.get("fresh_task") is not True or receipt.get("blind_prompt") is not True or receipt.get("full_context_blindness_verified") is not False or type(receipt.get("tool_calls")) is not int or receipt["tool_calls"] != (1 if file_protocol else 0) or receipt.get("council_reentry") != "denied":
            fail("PAIR_RECEIPT_INVALID")
        if receipt.get("registry_version") != "v3":
            fail("PAIR_BINDING_INVALID")
        binding = one([item for item in manifest["bindings"] if item["binding_id"] == receipt.get("binding_id")], "PAIR_BINDING_INVALID")
        expected = {key: manifest[key] for key in ("freeze_id", "registry_sha256", "registry_file_sha256", "release_binding", "candidate_sha256", "evaluation_bundle_sha256", "eval_suite_sha256", "prompt_sha256")}
        expected.update({"binding_sha256": binding["binding_sha256"], "preparation_sha256": manifest_sha,
                         "requested_model_id": binding["model_id"], "requested_effort": binding["reasoning"]["default_effort"]})
        if "qualification_protocol" in manifest:
            expected["qualification_protocol"] = role_protocol.protocol_binding(binding)
        if any(receipt.get(key) != value for key, value in expected.items()):
            fail("PAIR_FROZEN_BINDING_MISMATCH")
        if any(key not in receipt or receipt[key] != first.get(key) for key in shared):
            fail("PAIR_BINDING_MISMATCH")
        if any(key.startswith("provider_attested") or key.startswith("actual_") for key in receipt):
            fail("UNSUPPORTED_IDENTITY_CLAIM")
        if receipt["configured_model_id"] != receipt["requested_model_id"] or receipt["configured_effort"] != receipt["requested_effort"]:
            fail("PAIR_CONFIGURATION_MISMATCH")
        text(receipt["configured_model_id"])
        if receipt["configured_effort"] not in {"low", "medium", "high", "xhigh", "max", "ultra"}:
            fail("PAIR_CONFIGURATION_MISMATCH")
        for key in ("binding_sha256", "registry_sha256", "registry_file_sha256", "candidate_sha256", "evaluation_bundle_sha256", "eval_suite_sha256", "prompt_sha256", "preparation_sha256", "native_response_text_sha256"):
            digest(receipt.get(key))
        if receipt.get("response_sha256") != sha(canonical(receipt.get("response"))):
            fail("PAIR_RESPONSE_HASH_MISMATCH")
        _, derived = score_response(canonical(receipt.get("response")).decode("utf-8"), binding if "qualification_protocol" in manifest else None)
        if receipt.get("scenario_results") != derived or any(item["status"] != "passed" for item in derived):
            fail("PAIR_SCORE_MISMATCH")
        native = receipt.get("native_evidence")
        if not isinstance(native, dict) or native.get("child_session_id") != receipt.get("session_id") or native.get("parent_session_id") == receipt.get("session_id") or native.get("fork_turns") != "none":
            fail("PAIR_LINEAGE_INVALID")
        for key in ("child_transcript_sha256", "parent_transcript_sha256", "bootstrap_context_sha256"):
            digest(native.get(key))
        for key in ("parent_session_id", "child_session_id", "agent_path", "spawn_call_id", "turn_id"):
            text(native.get(key))
        if timestamp(native.get("completed_at")) < timestamp(native.get("started_at")):
            fail("COMPLETION_PRECEDES_START")
        text(receipt.get("session_id"))
        if receipt.get("run_id") not in RUN_IDS:
            fail("PAIR_RUNS_NOT_DISTINCT")
        parent_path, child_path = native_transcripts[receipt["run_id"]]
        native_receipt = score(root, workspace, receipt["binding_id"], receipt["run_id"],
                               parent_path, child_path)
        if native_receipt != receipt:
            fail("PAIR_NATIVE_RECEIPT_MISMATCH")
    if {item.get("run_id") for item in receipts} != RUN_IDS or len({item["session_id"] for item in receipts}) != 2 or any(len({item["native_evidence"][key] for item in receipts}) != 2 for key in ("agent_path", "turn_id", "child_transcript_sha256")) or len({(item["native_evidence"]["parent_session_id"], item["native_evidence"]["spawn_call_id"]) for item in receipts}) != 2:
        fail("PAIR_RUNS_NOT_DISTINCT")
    final_manifest, _, final_manifest_sha = load_preparation(root, workspace)
    if final_manifest != manifest or final_manifest_sha != manifest_sha:
        fail("PREPARATION_CHANGED_DURING_PAIR")
    return {"schema_version": PAIR, "result": "passed", "identity_assurance": "client_configuration",
            "evidence_assurance": "structural_only", "promotion_eligible": False, "provider_authenticity_verified": False,
            "full_context_blindness_verified": False,
            **{key: first[key] for key in shared}, "run_ids": sorted(RUN_IDS),
            "session_ids": sorted(item["session_id"] for item in receipts),
            "receipt_content_sha256": sorted(sha(canonical(item)) for item in receipts),
            "limitations": LIMITATIONS}


def host_selected_receipt(receipt: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Bind replayed scoring to an archived local-host collection record.

    This is structural assurance only. The caller must independently retain and
    pin the collected artifacts; JSON cannot authenticate the collecting host.
    """
    if receipt.get("schema_version") != RECEIPT or receipt.get("identity_assurance") != "client_configuration":
        fail("HOST_BASE_RECEIPT_INVALID")
    evidence = receipt["native_evidence"]
    expected_keys = {"schema_version", "source", "parent_rollout", "child_rollout",
                     "parent_transcript_sha256", "child_transcript_sha256"}
    if not isinstance(source, dict) or set(source) != expected_keys or source.get("schema_version") != HOST_SELECTION or source.get("source") != "codex_session_store":
        fail("HOST_SOURCE_INVALID")
    for role in ("parent", "child"):
        session = evidence[role + "_session_id"]
        try:
            if str(uuid.UUID(session)) != session:
                fail("HOST_SESSION_INVALID")
        except (ValueError, TypeError, AttributeError):
            fail("HOST_SESSION_INVALID")
        relative = source[role + "_rollout"]
        if not isinstance(relative, str) or re.fullmatch(
                r"\d{4}/\d{2}/\d{2}/rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-" + re.escape(session) + r"\.jsonl", relative) is None:
            fail("HOST_ROLLOUT_INVALID")
        if source[role + "_transcript_sha256"] != evidence[role + "_transcript_sha256"]:
            fail("HOST_TRANSCRIPT_MISMATCH")
    if re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?", evidence["client_version"]) is None or evidence["client_originator"] not in {"Codex Desktop", "codex_cli_rs", "codex_exec", "codex-tui"}:
        fail("HOST_CLIENT_INVALID")
    return {**receipt, "schema_version": HOST_RECEIPT, "identity_assurance": "host_selected",
            "promotion_eligible": receipt["result"] == "passed", "host_selection": source,
            "limitations": [*LIMITATIONS, "Host-selected qualification accepts explicit native selection at lower assurance; provider identity remains unverified."]}


def score_host_selected(root: Path, workspace: Path, binding_id: str, run_id: str,
                        parent_path: Path, child_path: Path) -> dict[str, Any]:
    """Verify exact retained exports against the configured native session store."""
    session_root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).absolute() / "sessions"
    receipt = score(root, workspace, binding_id, run_id, parent_path, child_path)
    relative = {}
    for role, path in (("parent", parent_path), ("child", child_path)):
        session = receipt["native_evidence"][role + "_session_id"]
        try:
            if str(uuid.UUID(session)) != session:
                fail("HOST_SESSION_INVALID")
        except (ValueError, TypeError, AttributeError):
            fail("HOST_SESSION_INVALID")
        original = one(list(session_root.glob("*/*/*/rollout-*-" + session + ".jsonl")),
                       "HOST_SESSION_STORE_REQUIRED")
        snapshot = read_regular(path)
        if sha(snapshot) != receipt["native_evidence"][role + "_transcript_sha256"] or not read_regular(original).startswith(snapshot):
            fail("HOST_SOURCE_MISMATCH")
        relative[role + "_rollout"] = original.relative_to(session_root).as_posix()
    source = {"schema_version": HOST_SELECTION, "source": "codex_session_store", **relative,
              **{key: receipt["native_evidence"][key] for key in ("parent_transcript_sha256", "child_transcript_sha256")}}
    return host_selected_receipt(receipt, source)


def validate_host_pair(receipts: list[dict[str, Any]], *, root: Path, workspace: Path,
                       native_transcripts: dict[str, tuple[Path, Path]], archived: bool = False) -> dict[str, Any]:
    """Replay native linkage and scoring; archives do not claim host authenticity."""
    if len(receipts) != 2 or any(not isinstance(item, dict) for item in receipts):
        fail("HOST_PAIR_INVALID")
    plain = []
    for receipt in receipts:
        run_id = receipt.get("run_id")
        if run_id not in native_transcripts:
            fail("PAIR_NATIVE_TRANSCRIPTS_REQUIRED")
        parent, child = native_transcripts[run_id]
        base = score(root, workspace, receipt.get("binding_id"), run_id, parent, child)
        observed = (host_selected_receipt(base, receipt.get("host_selection")) if archived else
                    score_host_selected(root, workspace, receipt.get("binding_id"), run_id, parent, child))
        if observed != receipt or receipt.get("promotion_eligible") is not True:
            fail("HOST_RECEIPT_MISMATCH")
        plain.append(base)
    pair = validate_pair(plain, root=root, workspace=workspace, native_transcripts=native_transcripts)
    return {**pair, "schema_version": HOST_PAIR, "identity_assurance": "host_selected", "promotion_eligible": True,
            "receipt_content_sha256": sorted(sha(canonical(item)) for item in receipts),
            "limitations": receipts[0]["limitations"]}


def save_new(path: Path, value: dict[str, Any]) -> None:
    """Write a new receipt only, without replacing an existing evidence file."""
    if any(part.is_symlink() for part in (path.absolute(), *path.absolute().parents)):
        fail("SYMLINK_UNSUPPORTED")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    prepared = commands.add_parser("prepare")
    prepared.add_argument("--output", type=Path, required=True)
    prepared.add_argument("--binding-id", required=True, help="Derive the cumulative suite from this exact candidate binding")
    prepared.add_argument("--delivery-mode", choices=("inline", "file"), default="inline",
                          help="File mode permits exactly one frozen prompt read before answering")
    scored = commands.add_parser("score")
    scored.add_argument("--workspace", type=Path, required=True)
    scored.add_argument("--binding-id", required=True)
    scored.add_argument("--run-id", required=True)
    scored.add_argument("--parent-transcript", type=Path, required=True)
    scored.add_argument("--child-transcript", type=Path, required=True)
    scored.add_argument("--receipt", type=Path, help="Save a new receipt; refuse to overwrite")
    scored.add_argument("--host-selected", action="store_true", help="Accept explicit selection from the local native session store at lower assurance")
    paired = commands.add_parser("validate-pair")
    paired.add_argument("--workspace", type=Path, required=True)
    paired.add_argument("--receipt", type=Path, action="append", required=True)
    paired.add_argument("--parent-transcript", type=Path, action="append", required=True,
                        help="Retained native parent snapshots, in receipt order")
    paired.add_argument("--child-transcript", type=Path, action="append", required=True,
                        help="Retained native child snapshots, in receipt order")
    paired.add_argument("--output", type=Path, help="Save a new pair; refuse to overwrite")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.root, args.output, delivery_mode=args.delivery_mode, binding_id=args.binding_id)
        elif args.command == "score":
            scorer = score_host_selected if args.host_selected else score
            result = scorer(args.root, args.workspace, args.binding_id, args.run_id, args.parent_transcript, args.child_transcript)
            if args.receipt:
                save_new(args.receipt, result)
        else:
            receipts = [decode(read_regular(path)) for path in args.receipt]
            if len(receipts) != 2 or len(args.parent_transcript) != 2 or len(args.child_transcript) != 2:
                fail("PAIR_NATIVE_TRANSCRIPTS_REQUIRED")
            native_transcripts = {receipt.get("run_id"): (parent, child)
                                  for receipt, parent, child in zip(receipts, args.parent_transcript, args.child_transcript)}
            validator = validate_host_pair if receipts[0].get("schema_version") == HOST_RECEIPT else validate_pair
            result = validator(receipts, root=args.root, workspace=args.workspace,
                                   native_transcripts=native_transcripts)
            if args.output:
                save_new(args.output, result)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if result.get("result", "passed") == "passed" else 1
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        reason = str(exc) if str(exc).startswith("CODEX_QUALIFICATION_") else "CODEX_QUALIFICATION_INPUT_INVALID"
        print(json.dumps({"result": "refused", "reason": reason, "promotion_eligible": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
