#!/usr/bin/env python3
"""Verify one native Claude plugin Agent probe from frozen, local evidence.

This verifier never launches an agent. A passing synthetic transcript is only a
parser test; native qualification requires authentic transcripts and a frozen
release binding produced before the probe.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ClaudeQualificationHarness import ROOT, current_release_binding, registry_binding, transcript_effort_matches


def fail(code: str) -> None:
    raise ValueError(code)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_loader_log(raw: bytes, root: Path, session_id: str, filename: str) -> None:
    """Check native loader ordering for one exact session and candidate root."""
    if filename != session_id + ".txt" or not re.fullmatch(r"[A-Za-z0-9_-]+", session_id):
        fail("PROBE_LOADER_SESSION_MISMATCH")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError:
        fail("PROBE_LOADER_LOG_INVALID")
    candidate = str(root.resolve())
    first = f"--plugin-dir {candidate} is one plugin: .claude-plugin at its top marks it"
    second = "Loaded inline plugin from path: agent-council"
    third = 'Plugin "agent-council" from --plugin-dir overrides installed version'
    events: list[tuple[int, int]] = []
    for number, line in enumerate(lines):
        if "[DEBUG] " not in line:
            continue
        message = line.split("[DEBUG] ", 1)[1]
        if message.startswith("--plugin-dir ") and message.endswith(" is one plugin: .claude-plugin at its top marks it"):
            if message != first:
                fail("PROBE_LOADER_ROOT_MISMATCH")
            events.append((number, 0))
        elif message == second:
            events.append((number, 1))
        elif message == third:
            events.append((number, 2))
    if not events or len(events) % 3 or [kind for _, kind in events] != [0, 1, 2] * (len(events) // 3):
        fail("PROBE_LOADER_ORDER_INVALID")


def verify_async_completion(parent_rows: list[dict[str, Any]], child_rows: list[dict[str, Any]],
                            result_index: int, session_id: str, agent_id: str,
                            tool_id: str) -> None:
    notifications = []
    for row in parent_rows[result_index + 1:]:
        origin = row.get("origin")
        if (row.get("type") != "user" or not isinstance(origin, dict)
                or origin.get("kind") != "task-notification" or origin.get("producer") != "session-task"):
            continue
        message = row.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            continue
        try:
            notice = ET.fromstring(content)
        except ET.ParseError:
            continue
        if notice.tag != "task-notification" or notice.findtext("task-id") != agent_id:
            continue
        if row.get("sessionId") != session_id:
            fail("PROBE_ASYNC_SESSION_MISMATCH")
        if notice.findtext("tool-use-id") != tool_id or notice.findtext("status") != "completed":
            fail("PROBE_ASYNC_COMPLETION_INVALID")
        notifications.append(row)
    if len(notifications) != 1:
        fail("PROBE_ASYNC_COMPLETION_MISSING")

    handbacks = []
    for index, row in enumerate(child_rows):
        if row.get("type") != "assistant" or row.get("agentId") != agent_id:
            continue
        for block in blocks(row):
            if block.get("type") == "tool_use" and block.get("name") == "SubagentHandback":
                handbacks.append((index, row, block))
    if len(handbacks) != 1:
        fail("PROBE_ASYNC_HANDBACK_MISSING")
    index, handback_row, handback = handbacks[0]
    handback_id = handback.get("id")
    if not isinstance(handback_id, str) or not handback_id:
        fail("PROBE_ASYNC_HANDBACK_INVALID")
    results = [(row, block) for row in child_rows[index + 1:] if row.get("type") == "user"
               for block in blocks(row) if block.get("type") == "tool_result"
               and block.get("tool_use_id") == handback_id]
    if len(results) != 1:
        fail("PROBE_ASYNC_HANDBACK_INVALID")
    result_row, result_block = results[0]
    outcome = result_row.get("toolUseResult")
    if (result_row.get("agentId") != agent_id or result_row.get("sessionId") != handback_row.get("sessionId")
            or result_row.get("sourceToolAssistantUUID") != handback_row.get("uuid")
            or result_block.get("is_error") is True or not isinstance(outcome, dict)
            or outcome.get("success") is not True):
        fail("PROBE_ASYNC_HANDBACK_INVALID")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("PROBE_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"PROBE_JSON_INVALID:{path.name}:{type(exc).__name__}")


def rows(path: Path) -> list[dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        fail(f"PROBE_TRANSCRIPT_UNREADABLE:{path.name}:{type(exc).__name__}")
    if not raw or not raw.endswith("\n"):
        fail("PROBE_TRANSCRIPT_INCOMPLETE")
    result = []
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            fail(f"PROBE_TRANSCRIPT_BLANK:{number}")
        try:
            item = json.loads(line, object_pairs_hook=unique_object)
        except json.JSONDecodeError:
            fail(f"PROBE_TRANSCRIPT_JSON_INVALID:{number}")
        if not isinstance(item, dict):
            fail(f"PROBE_TRANSCRIPT_ROW_INVALID:{number}")
        result.append(item)
    return result


def blocks(row: dict[str, Any]) -> list[dict[str, Any]]:
    message = row.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [item for item in content if isinstance(item, dict)]


def agent_definition(path: Path, model: str, effort: str | None) -> None:
    raw = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", raw, re.DOTALL)
    if not match:
        fail("PROBE_AGENT_DEFINITION_INVALID")
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        field = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*):\s*(.*?)\s*", line)
        if not field or field.group(1) in fields:
            fail("PROBE_AGENT_DEFINITION_INVALID")
        fields[field.group(1)] = field.group(2)
    if fields.get("name") != path.stem or fields.get("model") != model:
        fail("PROBE_AGENT_DEFINITION_MISMATCH")
    if effort is None:
        if "effort" in fields:
            fail("PROBE_AGENT_DEFINITION_MISMATCH")
    elif fields.get("effort") != effort:
        fail("PROBE_AGENT_DEFINITION_MISMATCH")
    if fields.get("disallowedTools") != "Agent" or "council_reentry: denied" not in raw:
        fail("PROBE_AGENT_DEFINITION_INVALID")


def verify(parent: Path, child: Path, binding_id: str, release_binding_path: Path,
           root: Path = ROOT, debug_log: Path | None = None) -> dict[str, Any]:
    parent, child, release_binding_path, root = (item.resolve() for item in (parent, child, release_binding_path, root))
    frozen = read_json(release_binding_path)
    if not isinstance(frozen, dict) or frozen != current_release_binding(root):
        fail("PROBE_RELEASE_BINDING_MISMATCH")
    registry, binding = registry_binding(binding_id, root)
    if binding["provider"] != "claude_code":
        fail("PROBE_BINDING_PROVIDER_INVALID")
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{2,127}", binding_id) is None:
        fail("PROBE_AGENT_NAME_INVALID")
    canonical = {"claude-code-v3-ultimate", "claude-code-v3-operational",
                 "claude-code-v3-technical", "claude-code-v3-worker"}
    name = "council-" + binding_id.removeprefix("claude-code-v3-") if binding_id in canonical else binding_id
    agent = root / "agents" / (name + ".md")
    if not agent.is_file() or agent.is_symlink():
        fail("PROBE_AGENT_DEFINITION_MISSING")
    model = binding["model_id"]
    effort = binding["reasoning"]["default_effort"]
    agent_definition(agent, model, effort)

    parent_rows, child_rows = rows(parent), rows(child)
    plugin_type = "agent-council:" + name
    calls: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    seen_tool_ids: set[str] = set()
    for index, row in enumerate(parent_rows):
        if row.get("type") != "assistant":
            continue
        for block in blocks(row):
            if block.get("type") != "tool_use":
                continue
            tool_id = block.get("id")
            if not isinstance(tool_id, str) or not tool_id or tool_id in seen_tool_ids:
                fail("PROBE_TOOL_USE_ID_INVALID")
            seen_tool_ids.add(tool_id)
            if block.get("name") != "Agent":
                continue
            input_data = block.get("input")
            if not isinstance(input_data, dict):
                fail("PROBE_AGENT_INPUT_INVALID")
            if input_data.get("subagent_type") == plugin_type:
                calls.append((index, row, block))
    if len(calls) != 1:
        fail("PROBE_TARGET_CALL_COUNT_INVALID")
    call_index, call_row, call = calls[0]
    input_data = call["input"]
    if not isinstance(input_data.get("prompt"), str) or not input_data["prompt"].strip():
        fail("PROBE_TASK_MISSING")
    if input_data.get("run_in_background") is not False and "run_in_background" in input_data:
        fail("PROBE_BACKGROUND_UNSUPPORTED")
    session_id = call_row.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        fail("PROBE_PARENT_SESSION_MISSING")
    if debug_log is None:
        fail("PROBE_LOADER_LOG_MISSING")
    debug_log = debug_log.resolve()
    verify_loader_log(debug_log.read_bytes(), root, session_id, debug_log.name)

    matched_results: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for index, row in enumerate(parent_rows):
        if row.get("type") != "user":
            continue
        for block in blocks(row):
            if block.get("type") == "tool_result" and block.get("tool_use_id") == call["id"]:
                matched_results.append((index, row, block))
    if len(matched_results) != 1 or matched_results[0][0] <= call_index:
        fail("PROBE_AGENT_RESULT_INVALID")
    result_index, result_row, result_block = matched_results[0]
    if result_row.get("sessionId") != session_id or result_block.get("is_error") is True:
        fail("PROBE_AGENT_RESULT_INVALID")
    result = result_row.get("toolUseResult")
    if not isinstance(result, dict):
        fail("PROBE_AGENT_RESULT_INVALID")
    agent_id = result.get("agentId")
    if not isinstance(agent_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", agent_id):
        fail("PROBE_AGENT_ID_INVALID")
    if result.get("resolvedModel") != model:
        fail("PROBE_RESOLVED_MODEL_MISMATCH")
    child_name = f"agent-{agent_id}.jsonl"
    allowed_child_paths = {
        parent.parent / "subagents" / child_name,
        parent.parent / parent.stem / "subagents" / child_name,
    }
    if child not in allowed_child_paths:
        fail("PROBE_CHILD_PATH_MISMATCH")
    status = result.get("status")
    if status not in {"completed", "success", "async_launched"}:
        fail("PROBE_AGENT_STATUS_INVALID")
    completion_evidence = "agent_result"
    if status == "async_launched":
        if result.get("isAsync") is not True:
            fail("PROBE_AGENT_STATUS_INVALID")
    elif result.get("isAsync") is True:
        fail("PROBE_AGENT_STATUS_INVALID")

    assistant_count = 0
    child_session: str | None = None
    for row in child_rows:
        if row.get("type") != "assistant":
            if "agentId" in row and row["agentId"] != agent_id:
                fail("PROBE_CHILD_LINK_MISMATCH")
            if "isSidechain" in row and row["isSidechain"] is not True:
                fail("PROBE_CHILD_LINK_MISMATCH")
            if child_session is not None and "sessionId" in row and row["sessionId"] != child_session:
                fail("PROBE_CHILD_SESSION_INVALID")
            continue
        if row.get("agentId") != agent_id or row.get("isSidechain") is not True:
            fail("PROBE_CHILD_LINK_MISMATCH")
        current_session = row.get("sessionId")
        if not isinstance(current_session, str) or not current_session:
            fail("PROBE_CHILD_SESSION_INVALID")
        if child_session is None:
            child_session = current_session
        elif child_session != current_session:
            fail("PROBE_CHILD_SESSION_INVALID")
        assistant_count += 1
        message = row.get("message")
        if not isinstance(message, dict) or message.get("model") != model:
            fail("PROBE_CHILD_MODEL_MISMATCH")
        if not transcript_effort_matches(row, effort):
            fail("PROBE_CHILD_EFFORT_MISMATCH")
    if assistant_count == 0:
        fail("PROBE_CHILD_ASSISTANT_MISSING")
    if status == "async_launched":
        verify_async_completion(parent_rows, child_rows, result_index, session_id, agent_id, call["id"])
        completion_evidence = "task_notification_handback"

    return {
        "schema_version": "agent-council.claude-agent-probe/v1",
        "result": "passed",
        "binding_id": binding_id,
        "binding_sha256": binding["binding_sha256"],
        "registry_sha256": registry["registry_sha256"],
        "registry_file_sha256": sha(root / "standards" / "agent-model-registry.v3.yaml"),
        "agent_definition_sha256": sha(agent),
        "release_binding": frozen,
        "release_binding_file_sha256": sha(release_binding_path),
        "parent_transcript_sha256": sha(parent),
        "child_transcript_sha256": sha(child),
        "parent_session_id": session_id,
        "loader_root": str(root),
        "loader_debug_log_sha256": sha(debug_log),
        "child_session_id": child_session,
        "agent_id": agent_id,
        "tool_use_id": call["id"],
        "subagent_type": plugin_type,
        "model_id": model,
        "effort": effort,
        "child_assistant_rows": assistant_count,
        "completion_evidence": completion_evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", required=True, type=Path)
    parser.add_argument("--child", required=True, type=Path)
    parser.add_argument("--binding-id", required=True)
    parser.add_argument("--release-binding", required=True, type=Path)
    parser.add_argument("--debug-log", required=True, type=Path)
    args = parser.parse_args()
    try:
        receipt = verify(args.parent, args.child, args.binding_id, args.release_binding,
                         debug_log=args.debug_log)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"result": "failed", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
