#!/usr/bin/env python3
"""Opt-in, bounded, private local observations. No task content is accepted."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

SCHEMA = "agent-council.decision-trace/v1"
ROOT = Path(__file__).resolve().parents[1]
PROTECTED_ROOT = next((path for path in (ROOT, *ROOT.parents) if (path / '.git').exists()), ROOT)
MAX_INPUT = 8192
MAX_RECORD = 2048
MAX_BYTES = 1024 * 1024
MAX_RECORDS = 4096
FILE = "decisions.jsonl"
ENUMS = {
    "host_kind": {"codex", "claude_code", "ambiguous", "unknown"},
    "event_kind": {"hook_observation", "agent_decision"},
    "activation_source": {"session_start_hook", "user_prompt_submit_hook", "skill", "host_instruction", "explicit", "unknown"},
    "outcome": {"direct_execution", "lightweight_routing", "governed_r1", "governed_r2", "governed_r3", "skipped", "blocked", "unknown"},
    "evidence_source": {"hook_observed", "agent_reported"},
    "requested_role": {"orchestrator", "investigator", "builder", "reviewer", "arbiter", "ultimate_intelligence", "operational_intelligence", "technical_tactical_intelligence", "worker_intelligence"},
    "requested_model": {"gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"},
    "requested_effort": {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"},
}
ENUMS["observed_model"] = ENUMS["requested_model"]
ENUMS["observed_effort"] = ENUMS["requested_effort"]
LIST_ENUMS = {
    "trigger_codes": {"automation_repair", "unexpected_failure", "uncertain_composition", "material_design", "architecture_change", "lifecycle_change", "updater_change", "authority_change", "shared_contract_change", "safety_change", "acceptance_change", "qualification_failure", "repeated_failure", "delegation_benefit"},
    "exclusion_codes": {"trivial", "conversational", "single_step", "read_only", "ordinary_operation", "known_cause_reversible", "tightly_coupled", "user_local_only", "overhead_exceeds_benefit", "reentry_denied", "out_of_scope"},
    "limitation_codes": {"model_unavailable", "effort_unavailable", "identity_unobservable", "host_unknown", "no_qualified_binding", "tool_unavailable", "authority_required"},
    "fallback_codes": {"same_tier", "higher_tier", "direct_execution", "none"},
    "method_ids": {"direct", "lightweight", "governed", "ce-debug", "ce-work", "ce-plan", "ce-code-review", "ce-brainstorm", "ce-pov", "acpl-lab"},
    "plugin_ids": {"agent-council", "compound-engineering", "acpl-cyber-range", "frontend-design", "openai-docs", "deslop-content"},
}
NULLABLE = {"requested_role", "requested_model", "requested_effort", "observed_model", "observed_effort"}
INPUT_FIELDS = {"activation_source", "outcome", "session_token", *NULLABLE, *LIST_ENUMS}
RECORD_FIELDS = {"schema_version", "timestamp", "plugin_version", "event_id", "host_kind", "event_kind", "evidence_source", *INPUT_FIELDS}


def schema_document():
    properties = {key: {"enum": sorted(values) + ([None] if key in NULLABLE else [])} for key, values in ENUMS.items()}
    properties.update({key: {"type": "array", "maxItems": 16, "uniqueItems": True,
                             "items": {"enum": sorted(values)}} for key, values in LIST_ENUMS.items()})
    token = {"type": ["string", "null"], "pattern": r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"}
    properties.update({"schema_version": {"const": SCHEMA}, "timestamp": {"type": "string", "format": "date-time", "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$"},
                       "plugin_version": {"type": ["string", "null"], "pattern": r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}$"},
                       "event_id": {**token, "type": "string"}, "session_token": token})
    decision_properties = {key: value for key, value in properties.items() if key in INPUT_FIELDS}
    decision_properties['activation_source'] = {"enum": ["explicit", "skill", "host_instruction", "unknown"]}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": SCHEMA,
            "title": "Agent Council local decision trace", "type": "object", "additionalProperties": False,
            "required": sorted(RECORD_FIELDS), "properties": properties,
            "allOf": [{"if": {"properties": {"event_kind": {"const": "hook_observation"}}},
                       "then": {"properties": {"evidence_source": {"const": "hook_observed"}, "outcome": {"const": "unknown"},
                                                  "activation_source": {"enum": ["session_start_hook", "user_prompt_submit_hook"]}}},
                       "else": {"properties": {"evidence_source": {"const": "agent_reported"},
                                                  "activation_source": decision_properties['activation_source']}}}],
            "$defs": {"decision_input": {"type": "object", "additionalProperties": False, "properties": decision_properties}}}


def enabled(environ):
    return environ.get("AGENT_COUNCIL_TRACE") == "1"


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def opaque(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", value):
        raise ValueError("invalid opaque token")
    return value


def validate_fields(document, fields):
    if not isinstance(document, dict) or set(document) - fields:
        raise ValueError("unknown fields")
    for key, value in document.items():
        if key in NULLABLE and value is None:
            continue
        if key in ENUMS and (not isinstance(value, str) or value not in ENUMS[key]):
            raise ValueError("invalid enum")
        if key in LIST_ENUMS:
            if (not isinstance(value, list) or len(value) > 16 or
                any(not isinstance(item, str) or item not in LIST_ENUMS[key] for item in value) or
                len(set(value)) != len(value)):
                raise ValueError("invalid code list")
    if "session_token" in document:
        opaque(document["session_token"])


def make_record(document, environ, event=None):
    validate_fields(document, INPUT_FIELDS)
    codex = bool(environ.get("PLUGIN_ROOT") or environ.get("PLUGIN_DATA"))
    claude = bool(environ.get("CLAUDE_PLUGIN_ROOT"))
    host = "ambiguous" if codex and claude else "codex" if codex else "claude_code" if claude else "unknown"
    version = None
    try:
        candidate = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())["version"]
        if isinstance(candidate, str) and re.fullmatch(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}", candidate):
            version = candidate
    except (OSError, ValueError, KeyError, TypeError):
        pass
    record = {"schema_version": SCHEMA, "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "plugin_version": version, "event_id": str(uuid.uuid4()), "host_kind": host,
              "event_kind": "hook_observation" if event else "agent_decision",
              "evidence_source": "hook_observed" if event else "agent_reported",
              "activation_source": "explicit", "outcome": "unknown", "session_token": None,
              **dict.fromkeys(NULLABLE), **{key: [] for key in LIST_ENUMS}, **document}
    if event:
        if event not in {"SessionStart", "UserPromptSubmit"}:
            raise ValueError("invalid event")
        record["activation_source"] = "session_start_hook" if event == "SessionStart" else "user_prompt_submit_hook"
        record["outcome"] = "unknown"
    elif record["activation_source"] not in {"explicit", "skill", "host_instruction", "unknown"}:
        raise ValueError("agent report cannot claim hook source")
    return record


def trace_path(environ):
    home = Path(environ.get("HOME", ""))
    xdg = Path(environ.get("XDG_STATE_HOME") or str(home / '.local/state'))
    target = Path(environ.get("AGENT_COUNCIL_TRACE_DIR") or str(xdg / 'agent-council'))
    if (not home.is_absolute() or not target.is_absolute() or '..' in target.parts or
        '..' in home.parts or target == home or home not in target.parents or
        target == PROTECTED_ROOT or PROTECTED_ROOT in target.parents or '.agent' in target.parts):
        raise ValueError("unsafe state location")
    return home, target


def open_directory(environ, create):
    """Walk via directory descriptors so no path component may follow a symlink."""
    home, target = trace_path(environ)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    current = Path('/')
    try:
        for component in target.parts[1:]:
            current /= component
            if create and home in current.parents:
                try:
                    os.mkdir(component, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if current == home or home in current.parents:
                if info.st_uid != os.getuid() or info.st_mode & 0o022:
                    raise ValueError("unsafe directory owner or mode")
        if os.fstat(fd).st_mode & 0o077:
            raise ValueError("state directory must be private")
        return fd
    except BaseException:
        os.close(fd)
        raise


def open_file(directory, create):
    flags = (os.O_RDWR | os.O_CREAT | os.O_APPEND) if create else os.O_RDONLY
    fd = os.open(FILE, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
        os.close(fd)
        raise ValueError("unsafe trace file")
    return fd


def lock_writer(fd):
    deadline = time.monotonic() + 0.5
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.005)


def append_record(record, environ):
    if not enabled(environ):
        return "disabled"
    directory = fd = None
    try:
        validate_record(record)
        data = (json.dumps(record, separators=(',', ':'), sort_keys=True) + '\n').encode()
        if len(data) > MAX_RECORD:
            return "invalid"
        directory = open_directory(environ, True)
        fd = open_file(directory, True)
        lock_writer(fd)
        size = os.fstat(fd).st_size
        if size > MAX_BYTES - MAX_RECORD:
            return "quota"
        existing = os.read(fd, MAX_BYTES + 1)
        if existing.count(b'\n') >= MAX_RECORDS:
            return "quota"
        if existing and not existing.endswith(b'\n'):
            return "unavailable"
        # A single append is made while holding the file lock. No pruning or rotation.
        if os.write(fd, data) != len(data):
            # Restore the locked pre-append boundary so a short write cannot
            # poison every later append with an incomplete JSONL record.
            os.ftruncate(fd, size)
            return "unavailable"
        return "recorded"
    except (OSError, ValueError, TypeError, OverflowError):
        return "unavailable"
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)


def validate_record(record):
    validate_fields(record, RECORD_FIELDS)
    if set(record) != RECORD_FIELDS or record['schema_version'] != SCHEMA:
        raise ValueError("invalid record")
    opaque(record['event_id'])
    if not isinstance(record['timestamp'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}', record['timestamp']):
        raise ValueError("invalid timestamp")
    datetime.fromisoformat(record['timestamp'])
    if record['plugin_version'] is not None and (not isinstance(record['plugin_version'], str) or not re.fullmatch(r'[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}', record['plugin_version'])):
        raise ValueError("invalid version")
    hook = record['event_kind'] == 'hook_observation'
    if record['evidence_source'] != ('hook_observed' if hook else 'agent_reported'):
        raise ValueError("inconsistent evidence")
    if hook and (record['outcome'] != 'unknown' or record['activation_source'] not in {'session_start_hook', 'user_prompt_submit_hook'}):
        raise ValueError("hook cannot prove a decision")
    if not hook and record['activation_source'] in {'session_start_hook', 'user_prompt_submit_hook'}:
        raise ValueError("agent cannot claim hook evidence")


def inspect_trace(environ):
    report = {"state": "disabled" if not enabled(environ) else "unavailable", "hook_observations": 0,
              "agent_reports": 0, "unknown_records": 0, "actual_agent_compliance": "unknown",
              "agent_reported_outcomes": {key: 0 for key in sorted(ENUMS['outcome'])}}
    if not enabled(environ):
        return report
    directory = fd = None
    try:
        directory = open_directory(environ, False)
        fd = open_file(directory, False)
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        size = os.fstat(fd).st_size
        data = os.read(fd, MAX_BYTES + 1)
        report['state'] = 'quota' if size > MAX_BYTES - MAX_RECORD or data.count(b'\n') >= MAX_RECORDS else 'available'
        lines = data.splitlines()
        if data and len(data) == size and not data.endswith(b'\n'):
            report['state'] = 'unavailable'
            report['unknown_records'] += 1
            lines = lines[:-1]
        for line in lines[:MAX_RECORDS]:
            try:
                if len(line) > MAX_RECORD:
                    raise ValueError('oversized record')
                record = json.loads(line, object_pairs_hook=pairs)
                validate_record(record)
                key = 'hook_observations' if record['event_kind'] == 'hook_observation' else 'agent_reports'
                report[key] += 1
                if key == 'agent_reports':
                    report['agent_reported_outcomes'][record['outcome']] += 1
            except (ValueError, TypeError, KeyError):
                report['unknown_records'] += 1
        return report
    except (OSError, ValueError, TypeError):
        return report
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('decision', 'hook', 'status'))
    parser.add_argument('--event', choices=('SessionStart', 'UserPromptSubmit'))
    args = parser.parse_args(argv)
    environ = dict(os.environ)
    if args.command == 'status':
        print(json.dumps(inspect_trace(environ), sort_keys=True))
        return 0
    if not enabled(environ):
        return 0
    try:
        if args.command == 'hook':
            # Hook stdin can contain task content. Deliberately never read it.
            if args.event is None:
                return 0
            token = opaque(environ.get('AGENT_COUNCIL_TRACE_SESSION_TOKEN'))
            record = make_record({'session_token': token}, environ, args.event)
        else:
            data = sys.stdin.buffer.read(MAX_INPUT + 1)
            if len(data) > MAX_INPUT:
                return 0
            record = make_record(json.loads(data, object_pairs_hook=pairs), environ)
        append_record(record, environ)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
