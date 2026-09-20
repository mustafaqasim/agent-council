#!/usr/bin/env python3
"""Fail-closed, standard-library evaluator for Agent Council v2 case records.

It consumes structured, immutable records only. It does not contact a provider
or a workload. It validates receipt shape and local record linkage only. It cannot
verify a provider attestation, authorize UAT, or make an operational closure.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SHA = re.compile(r"^[a-f0-9]{64}$")
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,127}$")
_ROLES = {"ultimate_intelligence", "operational_intelligence", "technical_tactical_intelligence", "worker_intelligence"}
_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
_STAGES = ("intake", "observe", "orient", "decide", "act", "verify", "review", "close")
_STAGE = {name: index for index, name in enumerate(_STAGES)}
_TYPES = {"case", "packet", "dispatch", "gate", "test", "evidence", "interruption", "resumption", "supersession", "candidate_transition", "closure"}
_SECRET_PARTS = {"secret", "password", "passwd", "credential", "api_key", "access_token", "refresh_token", "private_key", "dpapi", "cookie"}
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk(?:[-_](?:live|test|proj))?[-_][A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret)\s*[:=]\s*\S+", re.IGNORECASE),
)
_CANDIDATE_HASH_FIELDS = ("source_sha256", "package_sha256", "dependency_lock_sha256", "harness_sha256")
_ESCALATION_CAUSES = {"explicit_case_requirement", "complexity_escalation", "provider_constraint", "unresolved_risk", "route_floor"}
_ROUTE_RANK = {"R1": 1, "R2": 2, "R3": 3}
_ACTIVATION_ROUTE_FLOORS = {
    "bounded_automation_repair": "R1",
    "unexpected_qualification_failure": "R2",
    "unqualified_composition": "R2",
    "shared_contract_change": "R3",
    "lifecycle_authority_change": "R3",
    "architecture_change": "R3",
    "risk_boundary_change": "R3",
    "uat_gate_change": "R3",
    "repeated_unresolved_failure": "R3",
    "council_qualification": "R3",
}
_ROUTE_GATES = {
    "R1": ("ultimate-routing", "implementation-verification", "operational-review", "ultimate-final-disposition"),
    "R2": ("ultimate-routing", "ultimate-design", "implementation-verification", "independent-review", "ultimate-final-disposition"),
    "R3": ("ultimate-routing", "ultimate-design", "implementation-verification", "fault-tests", "independent-review", "ultimate-final-disposition"),
}
_QUALIFICATION_GATES = ("native-forward-run-1", "native-forward-run-2")
_BEHAVIORAL_EVIDENCE_KINDS = {
    "behavioral_assertion",
    "behavioral_gate",
    "behavioral_review",
    "behavioral_test",
    "behavioral_verification",
}
_BEHAVIORAL_EVIDENCE_SCHEMA = "agent-council.behavioral-evidence/v2"
_MAX_JSON_DEPTH = 64


class _JsonDepthError(ValueError):
    """Raised when JSON nesting is unsafe for structural-only validation."""


def _json_structure_problem(value: Any) -> str | None:
    """Bound recursive JSON work before validation or canonicalization reaches it."""
    pending: list[tuple[Any, int]] = [(value, 1)]
    seen_containers: set[int] = set()
    while pending:
        current, depth = pending.pop()
        if isinstance(current, (dict, list, tuple)):
            if depth > _MAX_JSON_DEPTH or id(current) in seen_containers:
                return "SCHEMA_VALIDATION_FAILED"
            seen_containers.add(id(current))
            if isinstance(current, dict):
                pending.extend((nested, depth + 1) for nested in current.values())
            else:
                pending.extend((nested, depth + 1) for nested in current)
    return None


def _decode_json(raw: str | bytes) -> Any:
    """Decode JSON while refusing excessive nesting before later structural walks."""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise
    except ValueError as exc:
        # Python's integer-string conversion limit is reported as ValueError.
        # Treat it exactly like any other untrusted structural decoding failure.
        raise _JsonDepthError("JSON decoding exceeds the structural validation bound") from exc
    except RecursionError as exc:
        raise _JsonDepthError("JSON nesting exceeds the structural validation bound") from exc
    if _json_structure_problem(value):
        raise _JsonDepthError("JSON nesting exceeds the structural validation bound")
    return value


def _canonical(value: Any) -> bytes:
    if _json_structure_problem(value):
        raise ValueError("JSON structure exceeds the structural validation bound")
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except RecursionError as exc:
        raise ValueError("JSON nesting exceeds the structural validation bound") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _outcome(result: str, code: str, effort: str | None = None, state: dict[str, Any] | None = None) -> dict[str, Any]:
    answer: dict[str, Any] = {
        "result": result,
        "code": code,
        "assurance": "structural_only",
        "provider_execution_attested": False,
        "uat_authority": False,
    }
    if effort is not None:
        answer["effort"] = effort
    if state is not None:
        answer["state"] = state
    return answer


def _refuse(code: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    return _outcome("refused", code, state=state)


def _sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA.fullmatch(value))


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def _public_text_problem(value: Any) -> str | None:
    """Require a public capture field to be a nonempty, control-free string."""
    if not isinstance(value, str) or not value:
        return "SCHEMA_VALIDATION_FAILED"
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return "CONTROL_CHARACTER_REFUSED"
    return None


def _public_text_list(value: Any, allowed: set[str] | tuple[str, ...] | None = None) -> bool:
    """Validate a JSON list before set membership or digesting can observe it."""
    if not isinstance(value, list) or not value or any(_public_text_problem(item) for item in value):
        return False
    if len(value) != len(set(value)):
        return False
    return allowed is None or all(item in allowed for item in value)


def _owned_process_valid(process: Any, reconciled_only: bool = False) -> bool:
    """An interruption can resume only from explicit, reconciled owned work."""
    if not isinstance(process, dict) or set(process) != {"identity", "status"}:
        return False
    if not _identifier(process.get("identity")):
        return False
    status = process.get("status")
    return status == "reconciled" if reconciled_only else status in {"reconciled", "unknown"}


def _candidate_digest(candidate: dict[str, Any]) -> str:
    fields = {key: candidate.get(key) for key in ("source_sha256", "package_sha256", "dependency_lock_sha256", "harness_sha256", "policy_sha256")}
    return _digest(fields)


def _security_problem(value: Any) -> str | None:
    issue = _json_structure_problem(value)
    if issue:
        return issue
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            for key, nested in current.items():
                if not isinstance(key, str):
                    return "SCHEMA_VALIDATION_FAILED"
                lowered = key.lower()
                compact = re.sub(r"[^a-z0-9]", "", lowered)
                if any(ord(char) < 32 or ord(char) == 127 for char in lowered):
                    return "CONTROL_CHARACTER_REFUSED"
                if any(part in lowered or part.replace("_", "") in compact for part in _SECRET_PARTS):
                    return "SECRET_REFUSED"
                pending.append(nested)
        elif isinstance(current, (list, tuple)):
            pending.extend(current)
        elif isinstance(current, str):
            if any(ord(char) < 32 or ord(char) == 127 for char in current):
                return "CONTROL_CHARACTER_REFUSED"
            if any(pattern.search(current) for pattern in _SECRET_VALUE_PATTERNS):
                return "SECRET_REFUSED"
    return None


def _evidence_problem(case_root: str) -> str | None:
    try:
        evidence_root = Path(case_root) / "evidence"
        if not evidence_root.is_dir():
            return "SCHEMA_VALIDATION_FAILED"
        for path in evidence_root.rglob("*"):
            if path.is_file():
                raw = path.read_bytes()
                if any((byte < 32 and byte not in {9, 10, 13}) or byte == 127 for byte in raw):
                    return "CONTROL_CHARACTER_REFUSED"
                try:
                    issue = _security_problem(_decode_json(raw.decode("utf-8")))
                except json.JSONDecodeError:
                    issue = None
                except (_JsonDepthError, ValueError):
                    return "SCHEMA_VALIDATION_FAILED"
                if issue:
                    return issue
    except (OSError, UnicodeDecodeError):
        return "SCHEMA_VALIDATION_FAILED"
    return None


def _identity(value: Any, case_id: str | None = None) -> bool:
    return isinstance(value, dict) and _identifier(value.get("case_id")) and (case_id is None or value.get("case_id") == case_id) and _sha(value.get("policy_bundle_sha256")) and isinstance(value.get("registry_version"), str) and bool(re.fullmatch(r"v[0-9]+", value["registry_version"])) and _sha(value.get("registry_sha256"))


def _document_valid(case: Any) -> bool:
    required = {"schema_version", "case_id", "case_root", "cycle_id", "route", "identity", "policy_bundle", "engineering_candidate", "registry", "provider_capability_receipt", "provider_dispatch_receipt", "events"}
    if not isinstance(case, dict) or not required <= case.keys() or case.get("schema_version") != "agent-council.case/v2":
        return False
    if not _identifier(case.get("case_id")) or not _identifier(case.get("cycle_id")) or not isinstance(case.get("case_root"), str) or not case["case_root"] or case.get("route") not in {"R1", "R2", "R3"} or not _identity(case.get("identity"), case["case_id"]):
        return False
    policy, candidate = case.get("policy_bundle"), case.get("engineering_candidate")
    candidate_keys = {"candidate_id", "candidate_sha256", "source_sha256", "package_sha256", "dependency_lock_sha256", "harness_sha256", "policy_sha256"}
    if not isinstance(policy, dict) or not isinstance(candidate, dict) or not isinstance(policy.get("policy_bundle_id"), str) or not _sha(policy.get("policy_sha256")) or not candidate_keys <= candidate.keys() or not _identifier(candidate.get("candidate_id")):
        return False
    if any(not _sha(candidate.get(key)) for key in candidate_keys - {"candidate_id"}):
        return False
    expected_candidate_sha = _candidate_digest(candidate)
    if candidate["candidate_sha256"] != expected_candidate_sha or candidate["candidate_id"] != f"candidate-{expected_candidate_sha[:24]}":
        return False
    return policy["policy_sha256"] == case["identity"]["policy_bundle_sha256"] == candidate["policy_sha256"] and isinstance(case.get("events"), list) and case["events"]


def _candidate_identity_problem(case: Any) -> str | None:
    candidate = case.get("engineering_candidate") if isinstance(case, dict) else None
    if not isinstance(candidate, dict):
        return None
    hash_keys = ("source_sha256", "package_sha256", "dependency_lock_sha256", "harness_sha256", "policy_sha256")
    if not all(_sha(candidate.get(key)) for key in hash_keys) or not _sha(candidate.get("candidate_sha256")) or not isinstance(candidate.get("candidate_id"), str):
        return None
    expected = _candidate_digest(candidate)
    return None if candidate["candidate_sha256"] == expected and candidate["candidate_id"] == f"candidate-{expected[:24]}" else "CANDIDATE_IDENTITY_MISMATCH"


def _registry_valid(registry: Any, identity: dict[str, Any]) -> bool:
    if not isinstance(registry, dict) or not isinstance(identity, dict) or not isinstance(registry.get("reasoning"), dict) or registry.get("schema_version") != "agent-council.model-registry/v2" or registry.get("registry_version") != identity.get("registry_version") or registry.get("registry_sha256") != identity.get("registry_sha256") or registry["reasoning"].get("default_effort") != "high" or not isinstance(registry.get("provider_states"), dict):
        return False
    declared_registry_sha = registry.get("registry_sha256")
    if declared_registry_sha != _digest({key: value for key, value in registry.items() if key != "registry_sha256"}):
        return False
    if any(not isinstance(state, dict) or state.get("council_status") not in {"qualified", "fail_closed_until_qualified"} for state in registry["provider_states"].values()):
        return False
    bindings = registry.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        return False
    seen: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, dict) or not _identifier(binding.get("binding_id")) or binding["binding_id"] in seen:
            return False
        seen.add(binding["binding_id"])
        if not isinstance(binding.get("provider"), str) or not binding["provider"] or not isinstance(binding.get("model_id"), str) or not binding["model_id"] or binding.get("tier") not in _ROLES or binding.get("status") not in {"qualified", "candidate", "revoked", "hard_expired"} or not _sha(binding.get("binding_sha256")):
            return False
        if binding["binding_sha256"] != _digest({key: value for key, value in binding.items() if key != "binding_sha256"}):
            return False
    return True


def _capability_valid(value: Any) -> bool:
    required = {"receipt_type", "receipt_id", "receipt_sha256", "provider", "observed_at", "context_id", "models", "efforts"}
    if not isinstance(value, dict) or set(value) != required or value.get("receipt_type") != "provider_capability" or not _sha(value.get("receipt_sha256")) or any(_public_text_problem(value.get(field)) for field in ("receipt_id", "provider", "observed_at", "context_id")):
        return False
    models, efforts = value.get("models"), value.get("efforts")
    if not _public_text_list(models) or not _public_text_list(efforts, _EFFORTS):
        return False
    if value["receipt_sha256"] != _digest({key: nested for key, nested in value.items() if key != "receipt_sha256"}):
        return False
    try:
        return datetime.fromisoformat(value["observed_at"].replace("Z", "+00:00")).tzinfo is not None
    except (TypeError, ValueError):
        return False


def _dispatch_valid(value: Any) -> bool:
    required = {"receipt_type", "receipt_id", "receipt_sha256", "dispatch_id", "provider", "model_id", "selected_effort", "attested_effort", "context_id", "system_generated"}
    fields = ("receipt_id", "dispatch_id", "provider", "model_id", "context_id")
    if not isinstance(value, dict) or set(value) != required or value.get("receipt_type") != "provider_dispatch" or not _sha(value.get("receipt_sha256")) or any(_public_text_problem(value.get(field)) for field in fields) or value.get("selected_effort") not in _EFFORTS or value.get("attested_effort") not in _EFFORTS or not isinstance(value.get("system_generated"), bool):
        return False
    try:
        return value["receipt_sha256"] == _digest({key: nested for key, nested in value.items() if key != "receipt_sha256"})
    except (TypeError, ValueError):
        return False


def _authority_dispatch_payload_shape_valid(payload: Any) -> bool:
    """Validate public provenance types before an evaluator reaches authority."""
    return isinstance(payload, dict) and _public_text_problem(payload.get("platform_output_ref")) is None


def _event_valid(event: Any, case: dict[str, Any]) -> bool:
    required = {"record_type", "event_id", "event_sha256", "recorded_at", "identity", "candidate_id", "cycle_id", "payload"}
    if not isinstance(event, dict) or not required <= event.keys() or event.get("record_type") not in _TYPES or not _identifier(event.get("event_id")) or not _sha(event.get("event_sha256")) or not _identifier(event.get("candidate_id")) or not _identifier(event.get("cycle_id")) or not isinstance(event.get("payload"), dict) or not _identity(event.get("identity"), case["case_id"]) or event["identity"] != case["identity"]:
        return False
    if event["event_sha256"] != _digest({key: value for key, value in event.items() if key != "event_sha256"}):
        return False
    try:
        if datetime.fromisoformat(str(event["recorded_at"]).replace("Z", "+00:00")).tzinfo is None:
            return False
    except ValueError:
        return False
    payload = event["payload"]
    if event["record_type"] in {"case", "dispatch", "gate", "closure"} and payload.get("system_generated") is not True:
        return False
    if event["record_type"] == "packet":
        if not {"packet_id", "phase", "status"} <= payload.keys() or not _identifier(payload.get("packet_id")) or not isinstance(payload.get("phase"), str) or payload.get("phase") not in {"request", "result"} or not isinstance(payload.get("status"), str):
            return False
    if event["record_type"] == "dispatch" and not _authority_dispatch_payload_shape_valid(payload):
        return False
    if event["record_type"] == "interruption":
        processes = payload.get("owned_processes")
        if payload.get("status") != "interrupted" or "owned_processes" not in payload or not isinstance(processes, list) or any(not _owned_process_valid(process) for process in processes):
            return False
    if event["record_type"] == "resumption" and (payload.get("exact_resumption") is not True or not {"interruption_id", "prior_candidate_id"} <= payload.keys()):
        return False
    return event["record_type"] != "supersession" or {"supersedes_event_id", "retired_event_id"} <= payload.keys()


def _immutable_events(case: dict[str, Any], events: list[dict[str, Any]]) -> bool:
    try:
        root = Path(case["case_root"])
        events_root = root / "events"
        expected_names = {f"{event['event_id']}.json" for event in events}
        actual_names = {path.name for path in events_root.iterdir() if path.is_file()}
        if actual_names != expected_names or any(path.is_symlink() for path in events_root.iterdir()):
            return False
        for event in events:
            path = events_root / f"{event['event_id']}.json"
            if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o222:
                return False
            stored = _decode_json(path.read_text(encoding="utf-8"))
            if stored != event:
                return False
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, _JsonDepthError, ValueError):
        return False
    return True


def _behavioral_evidence_content_valid(content: Any, evidence_kind: Any, candidate_id: Any, candidate_sha256: Any, cycle_id: Any) -> bool:
    """Validate positive, candidate-bound behavioral evidence content."""
    if evidence_kind not in _BEHAVIORAL_EVIDENCE_KINDS or not isinstance(content, dict):
        return False
    required_fields = {"schema_version", "evidence_kind", "candidate_id", "candidate_sha256", "cycle_id", "run", "assertion", "result"}
    if set(content) != required_fields:
        return False
    if content.get("schema_version") != _BEHAVIORAL_EVIDENCE_SCHEMA or content.get("evidence_kind") != evidence_kind:
        return False
    if not _identifier(candidate_id) or not _sha(candidate_sha256) or candidate_id != f"candidate-{candidate_sha256[:24]}" or not _identifier(cycle_id):
        return False
    if content.get("candidate_id") != candidate_id or content.get("candidate_sha256") != candidate_sha256 or content.get("cycle_id") != cycle_id:
        return False
    run, assertion, result = content.get("run"), content.get("assertion"), content.get("result")
    if not isinstance(run, dict) or not isinstance(assertion, dict) or not isinstance(result, dict):
        return False
    if not _identifier(run.get("run_id")) or not isinstance(run.get("run_kind"), str) or not run["run_kind"]:
        return False
    if not _identifier(assertion.get("assertion_id")) or not isinstance(assertion.get("subject"), str) or not assertion["subject"] or not isinstance(assertion.get("expected"), str) or not assertion["expected"]:
        return False
    return _identifier(result.get("result_id")) and result.get("status") == "passed"


def _candidate_transition_metadata_valid(content: Any, payload: dict[str, Any], event: dict[str, Any]) -> bool:
    if not isinstance(content, dict) or payload.get("kind") != "candidate_transition_metadata":
        return False
    if content.get("schema_version") != "agent-council.candidate-transition/v2":
        return False
    if content.get("candidate_id") != event["candidate_id"] or content.get("candidate_sha256") != payload.get("candidate_sha256") or content.get("cycle_id") != event["cycle_id"]:
        return False
    return _sha(content.get("candidate_sha256")) and event["candidate_id"] == f"candidate-{content['candidate_sha256'][:24]}" and _identifier(content.get("prior_candidate_id"))


def _read_evidence_content(case_root: Path, relative: str) -> Any | None:
    try:
        return _decode_json((case_root / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, _JsonDepthError, ValueError):
        return None


def _evidence_integrity_valid(case: dict[str, Any], events: list[dict[str, Any]]) -> bool:
    try:
        case_root = Path(case["case_root"]).resolve()
        evidence_root = (case_root / "evidence").resolve()
        for event in events:
            if event["record_type"] != "evidence":
                continue
            payload = event["payload"]
            relative = payload.get("path")
            kind = payload.get("kind")
            if kind in {"provider_capability", "provider_dispatch"}:
                if relative is not None or not _sha(payload.get("receipt_sha256")):
                    return False
                continue
            if kind not in _BEHAVIORAL_EVIDENCE_KINDS | {"candidate_transition_metadata"}:
                return False
            if not isinstance(relative, str) or not relative or not _sha(payload.get("sha256")):
                return False
            path = (case_root / relative).resolve()
            if evidence_root not in path.parents or not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o222 or _file_sha(path) != payload["sha256"]:
                return False
            content = _read_evidence_content(case_root, relative)
            if kind in _BEHAVIORAL_EVIDENCE_KINDS:
                if not isinstance(content, dict):
                    return False
            elif not _candidate_transition_metadata_valid(content, payload, event):
                return False
    except (OSError, RuntimeError):
        return False
    return True


def reduce_events(case: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Build immutable history, active view, candidate/cycle DAG and lifecycle indexes."""
    events = case["events"]
    ids: set[str] = set(); hashes: set[str] = set()
    previous_event_sha256 = None
    for event in events:
        if not _event_valid(event, case) or event["event_id"] in ids or event["event_sha256"] in hashes:
            return None, "SCHEMA_VALIDATION_FAILED"
        if event["payload"].get("previous_event_sha256") != previous_event_sha256:
            return None, "SCHEMA_VALIDATION_FAILED"
        ids.add(event["event_id"]); hashes.add(event["event_sha256"])
        previous_event_sha256 = event["event_sha256"]
    if not _immutable_events(case, events):
        return None, "SCHEMA_VALIDATION_FAILED"
    if not _evidence_integrity_valid(case, events):
        return None, "EVIDENCE_INTEGRITY_FAILED"
    history = {event["event_id"]: event for event in events}
    active = dict(history); superseded: set[str] = set()
    cycle_dag: dict[str, set[str]] = {}; candidate_dag: dict[str, set[str]] = {}
    for event in events:
        cycle_dag.setdefault(event["cycle_id"], set()).add(event["candidate_id"])
        candidate_dag.setdefault(event["candidate_id"], set()).add(event["cycle_id"])
        if event["record_type"] == "supersession":
            payload = event["payload"]; target = payload["supersedes_event_id"]
            prior = history.get(target)
            if prior is None or target != payload["retired_event_id"] or prior["cycle_id"] != event["cycle_id"] or prior["candidate_id"] != event["candidate_id"] or prior["identity"] != event["identity"]:
                return None, "SUPERSESSION_TARGET_MISSING"
            superseded.add(target); active.pop(target, None)
    interruptions: dict[str, dict[str, Any]] = {}; resumptions: dict[str, dict[str, Any]] = {}
    for event in events:
        if event["record_type"] == "interruption":
            interruptions[event["event_id"]] = event
        elif event["record_type"] == "resumption":
            target = event["payload"]["interruption_id"]; interruption = interruptions.get(target)
            if interruption is None or event["payload"].get("prior_candidate_id") != interruption["candidate_id"] or event["candidate_id"] != interruption["candidate_id"]:
                return None, "RESUMPTION_ORPHANED"
            if target in resumptions:
                return None, "RESUMPTION_DUPLICATE"
            if interruption["cycle_id"] == event["cycle_id"]:
                return None, "RESUMPTION_SAME_CYCLE"
            resumptions[target] = event
    for key, interruption in interruptions.items():
        payload = interruption["payload"]
        processes = payload.get("owned_processes")
        if key not in resumptions or "owned_processes" not in payload or not isinstance(processes, list) or any(not _owned_process_valid(process, reconciled_only=True) for process in processes):
            return None, "INTERRUPTION_UNRESOLVED"
    candidate = case["engineering_candidate"]["candidate_id"]
    if candidate not in cycle_dag.get(case["cycle_id"], set()):
        return None, "SCHEMA_VALIDATION_FAILED"
    evidence_owner: dict[str, str] = {}
    reused_evidence: set[str] = set()
    for event in events:
        if event["record_type"] == "evidence" and isinstance(event["payload"].get("evidence_id"), str):
            evidence_id = event["payload"]["evidence_id"]
            if evidence_id in evidence_owner:
                if evidence_owner[evidence_id] != event["candidate_id"]:
                    reused_evidence.add(evidence_id)
                else:
                    return None, "SCHEMA_VALIDATION_FAILED"
            evidence_owner.setdefault(evidence_id, event["candidate_id"])
    current_transitions = 0
    case_root = Path(case["case_root"])
    for index, event in enumerate(events):
        if event["record_type"] == "candidate_transition":
            payload = event["payload"]
            transition_evidence = [
                item for item in events[:index]
                if item["record_type"] == "evidence"
                and item["payload"].get("evidence_id") == payload.get("fresh_evidence_id")
                and item["candidate_id"] == event["candidate_id"]
                and item["cycle_id"] == event["cycle_id"]
            ]
            metadata = transition_evidence[0] if len(transition_evidence) == 1 else None
            metadata_payload = metadata.get("payload", {}) if isinstance(metadata, dict) else {}
            metadata_content = _read_evidence_content(case_root, metadata_payload.get("path", "")) if isinstance(metadata_payload.get("path"), str) else None
            if (
                not isinstance(payload.get("prior_candidate_id"), str)
                or payload["prior_candidate_id"] == event["candidate_id"]
                or payload.get("fresh_evidence_id") in reused_evidence
                or evidence_owner.get(payload.get("fresh_evidence_id")) != event["candidate_id"]
                or not isinstance(metadata, dict)
                or metadata_payload.get("kind") != "candidate_transition_metadata"
                or not _candidate_transition_metadata_valid(metadata_content, metadata_payload, metadata)
                or metadata_content.get("prior_candidate_id") != payload["prior_candidate_id"]
            ):
                return None, "CANDIDATE_EVIDENCE_MISMATCH"
            if event["candidate_id"] == candidate and event["cycle_id"] == case["cycle_id"]:
                current_transitions += 1
        if event["record_type"] in {"test", "gate", "closure"}:
            evidence_id = event["payload"].get("evidence_id")
            if isinstance(evidence_id, str) and (evidence_id in reused_evidence or evidence_owner.get(evidence_id) not in {None, event["candidate_id"]}):
                return None, "CANDIDATE_EVIDENCE_MISMATCH"
        if event["record_type"] == "test" and isinstance(event["payload"].get("evidence_id"), str) and event["payload"]["evidence_id"] not in evidence_owner:
            return None, "CANDIDATE_EVIDENCE_MISMATCH"
    if current_transitions > 1:
        return None, "CANDIDATE_EVIDENCE_MISMATCH"
    return {
        "history": history, "active": active, "superseded": sorted(superseded),
        "cycle_candidate_dag": {key: sorted(value) for key, value in cycle_dag.items()},
        "candidate_cycle_dag": {key: sorted(value) for key, value in candidate_dag.items()},
        "interruptions": interruptions, "resumptions": resumptions, "candidate_transition": current_transitions == 1,
    }, None


def _route_and_provider(case: dict[str, Any], state: dict[str, Any]) -> tuple[str | None, str | None]:
    registry = case["registry"]; capability = case["provider_capability_receipt"]; dispatch = case["provider_dispatch_receipt"]
    if dispatch["system_generated"] is not True:
        return None, "PROVIDER_RECEIPT_UNVERIFIED"
    if dispatch["selected_effort"] != dispatch["attested_effort"]:
        return None, "EFFECTIVE_EFFORT_MISMATCH"
    try:
        observed = datetime.fromisoformat(capability["observed_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None, "SCHEMA_VALIDATION_FAILED"
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    if age < -86400 or age > 86400:
        return None, "CAPABILITY_STALE"
    bindings = [binding for binding in registry["bindings"] if binding["provider"] == dispatch["provider"] and binding["model_id"] == dispatch["model_id"] and binding["status"] == "qualified"]
    matching_dispatches = [event for event in state["active"].values() if event["record_type"] == "dispatch" and event["candidate_id"] == case["engineering_candidate"]["candidate_id"] and event["cycle_id"] == case["cycle_id"] and event["payload"].get("dispatch_receipt_id") == dispatch["receipt_id"]]
    requested = matching_dispatches[0]["payload"].get("requested_role") if len(matching_dispatches) == 1 else None
    tier = bindings[0]["tier"] if len(bindings) == 1 else None
    if len(bindings) != 1:
        return None, "PROVIDER_RECEIPT_MISMATCH"
    bounded = any(event["payload"].get("bounded_worker") is True for event in state["history"].values() if event["record_type"] == "packet")
    allowed = tier == requested == "technical_tactical_intelligence"
    if case["route"] == "R1" and tier == requested == "worker_intelligence" and bounded:
        allowed = True
    if not allowed:
        return None, "IMPLEMENTATION_TIER_INVALID"
    effort = dispatch["selected_effort"]
    if effort != "high":
        if _EFFORTS.index(effort) < _EFFORTS.index("high"):
            return None, "EFFORT_POLICY_INVALID"
        current = case["engineering_candidate"]["candidate_id"]
        evidence = {event["payload"].get("evidence_id") for event in state["history"].values() if event["record_type"] == "evidence" and event["candidate_id"] == current}
        escalations = [event for event in state["history"].values() if event["record_type"] == "gate" and event["payload"].get("system_generated") is True and event["payload"].get("cause") in _ESCALATION_CAUSES]
        if not any(event["payload"].get("evidence_id") in evidence for event in escalations):
            return None, "EFFORT_POLICY_INVALID"
        if dispatch["provider"] != capability["provider"] or dispatch["context_id"] != capability["context_id"] or dispatch["model_id"] not in capability["models"] or effort not in capability["efforts"] or registry["provider_states"].get(dispatch["provider"], {}).get("council_status") != "qualified":
            return None, "PROVIDER_RECEIPT_MISMATCH"
        return effort, "EFFORT_ESCALATION_ACCEPTED"
    if len(bindings) != 1 or dispatch["provider"] != capability["provider"] or dispatch["context_id"] != capability["context_id"] or dispatch["model_id"] not in capability["models"] or effort not in capability["efforts"] or registry["provider_states"].get(dispatch["provider"], {}).get("council_status") != "qualified":
        return None, "PROVIDER_RECEIPT_MISMATCH"
    return effort, None


def _activation_and_route(case: dict[str, Any], state: dict[str, Any]) -> tuple[str | None, str | None]:
    current = case["engineering_candidate"]["candidate_id"]
    intakes = [event for event in state["active"].values() if event["record_type"] == "case" and event["candidate_id"] == current and event["cycle_id"] == case["cycle_id"]]
    if len(intakes) != 1:
        return None, "ROUTE_CLASSIFICATION_MISSING"
    payload = intakes[0]["payload"]
    activation_class = payload.get("activation_class")
    case_kind = payload.get("case_kind")
    floor = _ACTIVATION_ROUTE_FLOORS.get(activation_class)
    if payload.get("route") != case["route"] or floor is None or case_kind not in {"operational_change", "council_qualification"}:
        return None, "ROUTE_CLASSIFICATION_MISSING"
    if _ROUTE_RANK[case["route"]] < _ROUTE_RANK[floor]:
        return None, "ROUTE_FLOOR_VIOLATION"
    if (case_kind == "council_qualification") != (activation_class == "council_qualification"):
        return None, "ROUTE_CLASSIFICATION_MISSING"
    return case_kind, None


def _packet_dispatch_problem(events: list[dict[str, Any]], packet_id: str, request_index: int, result_index: int) -> str | None:
    """Bind a packet result to one request and one preceding implementation."""
    if result_index <= request_index:
        return "PACKET_NOT_ACTIONABLE"
    request_payload = events[request_index].get("payload")
    if not isinstance(request_payload, dict):
        return "SCHEMA_VALIDATION_FAILED"
    role = request_payload.get("requested_role")
    if not isinstance(role, str) or role not in _ROLES:
        return "PACKET_NOT_ACTIONABLE"
    candidates: list[dict[str, Any]] = []
    for event in events[request_index + 1:result_index]:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return "SCHEMA_VALIDATION_FAILED"
        if event.get("record_type") == "dispatch" and payload.get("decision_kind") == "implementation" and payload.get("disposition") == "approved" and payload.get("requested_role") == role:
            candidates.append(event)
    request_sha = request_payload.get("dispatch_request_sha256")
    nonce_sha = request_payload.get("dispatch_plan_nonce_sha256")
    if request_sha is not None or nonce_sha is not None:
        if not _sha(request_sha) or not _sha(nonce_sha):
            return "PACKET_NOT_ACTIONABLE"
        matches = [
            event for event in candidates
            if event["payload"].get("packet_id") == packet_id
            and event["payload"].get("dispatch_request_sha256") == request_sha
            and event["payload"].get("plan_nonce_sha256") == nonce_sha
        ]
    else:
        # v2 imported records predate explicit packet linkage.  They remain
        # usable only when chronology leaves one, and only one, candidate.
        matches = [event for event in candidates if "packet_id" not in event["payload"]]
    return None if len(matches) == 1 else "PACKET_NOT_ACTIONABLE"


def _stage_and_packets(case: dict[str, Any], state: dict[str, Any]) -> str | None:
    candidate = case["engineering_candidate"]["candidate_id"]
    events = [event for event in state["active"].values() if event["candidate_id"] == candidate and event["cycle_id"] == case["cycle_id"]]
    cursor = -1
    stages = []
    for event in events:
        stage = event["payload"].get("stage")
        if stage is not None:
            if stage not in _STAGE or _STAGE[stage] < cursor:
                return "STAGE_ORDER_INVALID"
            cursor = _STAGE[stage]
            stages.append(stage)
    if stages and stages[0] != "intake":
        return "STAGE_ORDER_INVALID"
    has_post_decision_work = any(event["record_type"] in {"test", "closure"} or (event["record_type"] == "packet" and event["payload"].get("phase") == "result") or _STAGE.get(event["payload"].get("stage"), -1) > _STAGE["decide"] for event in events)
    if "decide" in stages and not has_post_decision_work:
        return "STAGE_DECIDE_ACCEPTED"
    packets: dict[str, dict[str, list[tuple[int, dict[str, Any]]]]] = {}
    for index, event in enumerate(events):
        if event["record_type"] != "packet":
            continue
        payload = event["payload"]; packet_id = payload.get("packet_id")
        if not isinstance(packet_id, str) or not packet_id:
            return "SCHEMA_VALIDATION_FAILED"
        bucket = packets.setdefault(packet_id, {"request": [], "result": []})
        phase = payload.get("phase")
        if phase not in bucket:
            return "PACKET_NOT_ACTIONABLE"
        bucket[phase].append((index, event))
    if not packets:
        return "SCHEMA_VALIDATION_FAILED"
    for bucket in packets.values():
        if len(bucket["request"]) != 1 or len(bucket["result"]) != 1:
            return "PACKET_RESULT_CONFLICT"
        request_index, request = bucket["request"][0]
        result_index, result_event = bucket["result"][0]
        if request["payload"].get("status") != "accepted":
            return "PACKET_NOT_ACTIONABLE"
        result = result_event["payload"]
        if result.get("status") not in {"completed", "passed"}:
            return "PACKET_RESULT_CONFLICT"
        checks = result.get("checks")
        if not isinstance(checks, list) or not checks or any(not isinstance(check, dict) or check.get("status") != "passed" for check in checks):
            return "PACKET_CHECK_FAILED"
        packet_problem = _packet_dispatch_problem(events, request["payload"]["packet_id"], request_index, result_index)
        if packet_problem:
            return packet_problem
    return None


def _authority_dispatch_valid(event: dict[str, Any], case: dict[str, Any], role: str) -> bool:
    if not isinstance(event, dict) or not isinstance(case, dict) or not isinstance(event.get("payload"), dict) or not isinstance(case.get("registry"), dict):
        return False
    payload = event["payload"]
    registry = case["registry"]
    bindings = registry.get("bindings")
    provider_states = registry.get("provider_states")
    if not isinstance(bindings, list) or not isinstance(provider_states, dict):
        return False
    matches = [binding for binding in bindings if isinstance(binding, dict) and binding.get("provider") == payload.get("provider") and binding.get("model_id") == payload.get("model_id") and binding.get("tier") == role and binding.get("status") == "qualified" and binding.get("binding_id") == payload.get("binding_id") and binding.get("binding_sha256") == payload.get("binding_sha256")]
    provider_state = provider_states.get(payload.get("provider"), {})
    # A local replay may validate all fields, but never proves the provider
    # generated them.  Legacy imported records are treated with the same
    # structural-only assurance and do not elevate the evaluator's outcome.
    if not isinstance(provider_state, dict) or len(matches) != 1 or provider_state.get("council_status") != "qualified" or payload.get("requested_role") != role or payload.get("receipt_provenance") not in {"structural_only", "platform_returned"} or payload.get("receipt_assurance", "structural_only") != "structural_only" or payload.get("selected_effort") != payload.get("attested_effort") or payload.get("selected_effort") not in {"high", "xhigh", "max", "ultra"}:
        return False
    required_public = ("dispatch_receipt_id", "provider", "binding_id", "requested_role", "model_id", "capability_receipt_id", "platform_task_id", "platform_context_id", "platform_output_ref", "capability_context_id", "capability_observed_at")
    if any(_public_text_problem(payload.get(field)) for field in required_public) or payload.get("capability_context_id") != payload.get("platform_context_id") or not _public_text_list(payload.get("capability_models")) or not _public_text_list(payload.get("capability_efforts"), _EFFORTS) or payload.get("model_id") not in payload["capability_models"] or payload.get("selected_effort") not in payload["capability_efforts"] or not _sha(payload.get("capability_receipt_sha256")) or not _sha(payload.get("dispatch_receipt_sha256")) or not _sha(payload.get("binding_sha256")):
        return False
    capability_snapshot = {"receipt_type": "provider_capability", "receipt_id": payload["capability_receipt_id"], "provider": payload["provider"], "observed_at": payload.get("capability_observed_at"), "context_id": payload["capability_context_id"], "models": payload.get("capability_models"), "efforts": payload.get("capability_efforts")}
    dispatch_snapshot = {"receipt_type": "provider_dispatch", "receipt_id": payload.get("dispatch_receipt_id"), "dispatch_id": payload["platform_task_id"], "provider": payload["provider"], "model_id": payload["model_id"], "selected_effort": payload["selected_effort"], "attested_effort": payload["attested_effort"], "context_id": payload["platform_context_id"], "system_generated": True}
    if not payload.get("dispatch_receipt_id") or not _sha(payload.get("dispatch_receipt_sha256")) or payload["capability_receipt_sha256"] != _digest(capability_snapshot) or payload["dispatch_receipt_sha256"] != _digest(dispatch_snapshot):
        return False
    try:
        observed = datetime.fromisoformat(str(payload.get("capability_observed_at", "")).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return False
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    return -86400 <= age <= 86400


def _behavioral_evidence_records(case_root: Path, events: list[dict[str, Any]], candidate: dict[str, Any], cycle_id: str) -> dict[str, dict[str, Any]]:
    """Return behavioral evidence bound exactly to the active candidate and cycle."""
    accepted: dict[str, dict[str, Any]] = {}
    candidate_id = candidate.get("candidate_id")
    candidate_sha256 = candidate.get("candidate_sha256")
    if not _identifier(candidate_id) or not _sha(candidate_sha256) or candidate_id != f"candidate-{candidate_sha256[:24]}" or not _identifier(cycle_id):
        return accepted
    for event in events:
        payload = event["payload"]
        if (
            event["record_type"] != "evidence"
            or event.get("candidate_id") != candidate_id
            or event.get("cycle_id") != cycle_id
            or payload.get("kind") not in _BEHAVIORAL_EVIDENCE_KINDS
            or payload.get("candidate_id") != candidate_id
            or payload.get("candidate_sha256") != candidate_sha256
            or payload.get("cycle_id") != cycle_id
            or not isinstance(payload.get("path"), str)
        ):
            continue
        content = _read_evidence_content(case_root, payload["path"])
        if not _behavioral_evidence_content_valid(content, payload.get("kind"), candidate_id, candidate_sha256, cycle_id):
            continue
        if isinstance(payload.get("evidence_id"), str):
            accepted[payload["evidence_id"]] = content
    return accepted


def _behavioral_evidence_ids(case_root: Path, events: list[dict[str, Any]], candidate: dict[str, Any], cycle_id: str) -> set[str]:
    return set(_behavioral_evidence_records(case_root, events, candidate, cycle_id))


def _active_behavioral_evidence_binding_problem(case_root: Path, events: list[dict[str, Any]], candidate: dict[str, Any], cycle_id: str) -> bool:
    """Detect an active evidence envelope rebound to another candidate or cycle."""
    candidate_id = candidate.get("candidate_id")
    candidate_sha256 = candidate.get("candidate_sha256")
    if not _identifier(candidate_id) or not _sha(candidate_sha256) or candidate_id != f"candidate-{candidate_sha256[:24]}" or not _identifier(cycle_id):
        return True
    for event in events:
        payload = event["payload"]
        if event["record_type"] != "evidence" or payload.get("kind") not in _BEHAVIORAL_EVIDENCE_KINDS or not isinstance(payload.get("path"), str):
            continue
        content = _read_evidence_content(case_root, payload["path"])
        if not _behavioral_evidence_content_valid(content, payload.get("kind"), payload.get("candidate_id"), payload.get("candidate_sha256"), payload.get("cycle_id")):
            continue
        if (
            event.get("candidate_id") != candidate_id
            or event.get("cycle_id") != cycle_id
            or payload.get("candidate_id") != candidate_id
            or payload.get("candidate_sha256") != candidate_sha256
            or payload.get("cycle_id") != cycle_id
        ):
            return True
    return False


def _implementation_dispatch_valid(event: dict[str, Any], case: dict[str, Any]) -> bool:
    return _authority_dispatch_valid(event, case, "technical_tactical_intelligence") or (case["route"] == "R1" and _authority_dispatch_valid(event, case, "worker_intelligence"))


def _active_decision_problem(case: dict[str, Any], events: list[dict[str, Any]], case_kind: str) -> str | None:
    """Resolve every active authority disposition before choosing approvals."""
    dispatches = [event for event in events if event["record_type"] == "dispatch"]
    known = {"routing", "design", "implementation", "review", "native_forward", "final"}
    for event in dispatches:
        kind = event["payload"].get("decision_kind")
        if kind not in known:
            return "AUTHORITY_DISPATCH_INVALID"
        if kind == "implementation":
            valid, rejected = _implementation_dispatch_valid(event, case), "IMPLEMENTATION_NOT_APPROVED"
        elif kind == "review":
            valid, rejected = _authority_dispatch_valid(event, case, "operational_intelligence"), "OPERATIONAL_REVIEW_NOT_APPROVED"
        else:
            valid = _authority_dispatch_valid(event, case, "ultimate_intelligence")
            rejected = "NATIVE_FORWARD_RUN_NOT_APPROVED" if kind == "native_forward" else "ULTIMATE_GATE_NOT_APPROVED"
        if not valid:
            return "NATIVE_FORWARD_RUNS_INSUFFICIENT" if kind == "native_forward" else "AUTHORITY_DISPATCH_INVALID"
        if event["payload"].get("disposition") != "approved":
            return rejected
        if kind == "native_forward" and (case_kind != "council_qualification" or event["payload"].get("qualification_run_id") not in _QUALIFICATION_GATES):
            return "NATIVE_FORWARD_RUNS_NOT_FRESH"

    required: list[tuple[str, str | None]] = [("routing", None)]
    if case["route"] in {"R2", "R3"}:
        required.append(("design", None))
    required.extend((("implementation", None), ("review", None), ("final", None)))
    if case_kind == "council_qualification":
        required.extend(("native_forward", run_id) for run_id in _QUALIFICATION_GATES)
    for kind, run_id in required:
        matches = [event for event in dispatches if event["payload"].get("decision_kind") == kind and (run_id is None or event["payload"].get("qualification_run_id") == run_id)]
        if len(matches) == 1:
            continue
        if len(matches) > 1:
            return "DUPLICATE_ACTIVE_DISPOSITION"
        if kind in {"routing", "design", "final"}:
            return "ULTIMATE_GATE_RECEIPT_MISSING"
        if kind == "review":
            return "INDEPENDENT_REVIEW_REQUIRED"
        if kind == "native_forward":
            return "NATIVE_FORWARD_RUNS_INSUFFICIENT"
        return "IMPLEMENTATION_RECEIPT_MISSING"
    return None


def _closure_and_gates(case: dict[str, Any], state: dict[str, Any], case_kind: str) -> str | None:
    candidate = case["engineering_candidate"]["candidate_id"]
    events = [event for event in state["active"].values() if event["candidate_id"] == candidate and event["cycle_id"] == case["cycle_id"]]
    closures = [event for event in events if event["record_type"] == "closure"]
    if len(closures) != 1 or events[-1] is not closures[0]:
        return "REQUIRED_GATE_EVIDENCE_MISSING"
    closure = closures[0]["payload"]; required = closure.get("required_gate_ids")
    if closure.get("self_declared_proof") or "proof" in closure or not isinstance(required, list) or not required:
        return "REQUIRED_GATE_EVIDENCE_MISSING"
    normative = list(_ROUTE_GATES[case["route"]])
    if case_kind == "council_qualification":
        normative.extend(_QUALIFICATION_GATES)
    if case_kind == "council_qualification" and not set(_QUALIFICATION_GATES) <= set(required):
        return "NATIVE_FORWARD_RUNS_INSUFFICIENT"
    if required != normative or len(required) != len(set(required)):
        return "ROUTE_GATE_SET_INVALID"
    all_gate_events = [event for event in events if event["record_type"] == "gate"]
    if any("status" in event["payload"] and event["payload"].get("status") != "passed" for event in all_gate_events):
        return "UNRESOLVED_GATE_FAILURE"
    gate_events = [event for event in all_gate_events if isinstance(event["payload"].get("gate_id"), str)]
    if any("gate_id" not in event["payload"] and event["payload"].get("cause") not in _ESCALATION_CAUSES for event in all_gate_events):
        return "ROUTE_GATE_SET_INVALID"
    if any(sum(1 for event in events if event["record_type"] == "gate" and event["payload"].get("gate_id") == gate) != 1 for gate in normative):
        return "REQUIRED_GATE_EVIDENCE_MISSING"
    if any(event["payload"]["gate_id"] not in normative for event in gate_events):
        return "ROUTE_GATE_SET_INVALID"
    # A named closure gate is evidence only when it explicitly records a pass.
    # Status-free gate records remain valid escalation metadata, but cannot
    # satisfy a required/normative closure gate.
    passed_gate_events = [event for event in gate_events if event["payload"].get("status") == "passed"]
    passed_gates = {event["payload"].get("gate_id"): event for event in passed_gate_events}
    tests = [event for event in events if event["record_type"] == "test" and event["payload"].get("status") == "passed"]
    if any(event["record_type"] == "test" and event["payload"].get("status") != "passed" for event in events):
        return "UNRESOLVED_TEST_FAILURE"
    if _active_behavioral_evidence_binding_problem(Path(case["case_root"]), events, case["engineering_candidate"], case["cycle_id"]):
        return "CANDIDATE_EVIDENCE_MISMATCH"
    evidence = _behavioral_evidence_records(Path(case["case_root"]), events, case["engineering_candidate"], case["cycle_id"])
    if not set(normative) <= set(passed_gates) or not tests or any(test["payload"].get("evidence_id") not in evidence or evidence[test["payload"]["evidence_id"]]["run"]["run_id"] != test["payload"].get("run_id") for test in tests) or any(passed_gates[gate]["payload"].get("evidence_id") not in evidence for gate in normative):
        return "REQUIRED_GATE_EVIDENCE_MISSING"

    independent = passed_gates.get("independent-review")
    if "fault-tests" in normative and not any(test["payload"].get("test_kind") == "fault" for test in tests):
        return "FAULT_TEST_REQUIRED"

    dispatches = [event for event in events if event["record_type"] == "dispatch"]
    issue = _active_decision_problem(case, events, case_kind)
    if issue:
        return issue
    implementations = [event for event in dispatches if event["payload"].get("decision_kind") == "implementation"]
    all_reviews = [event for event in dispatches if event["payload"].get("decision_kind") == "review"]
    if any(not _authority_dispatch_valid(event, case, "operational_intelligence") for event in all_reviews):
        return "INDEPENDENT_REVIEW_REQUIRED"
    if any(event["payload"].get("disposition") != "approved" for event in all_reviews):
        return "OPERATIONAL_REVIEW_NOT_APPROVED"
    if len(all_reviews) != 1:
        return "INDEPENDENT_REVIEW_REQUIRED" if independent else "OPERATIONAL_REVIEW_RECEIPT_MISSING"
    review = all_reviews[0]
    verification_ids = {test["payload"].get("evidence_id") for test in tests}
    before_review = implementations + tests + [event for event in events if (event["record_type"] == "packet" and event["payload"].get("phase") == "result") or (event["record_type"] == "evidence" and event["payload"].get("evidence_id") in verification_ids)]
    if any(events.index(event) >= events.index(review) for event in before_review) or (independent and events.index(independent) <= events.index(review)):
        return "REVIEW_ORDER_INVALID"
    if independent:
        reviewer_id = independent["payload"].get("reviewer_id"); implementation_id = independent["payload"].get("implementation_id")
        review_dispatches = [event for event in dispatches if event["payload"].get("platform_task_id") == reviewer_id and event["payload"].get("decision_kind") == "review" and event["payload"].get("disposition") == "approved" and _authority_dispatch_valid(event, case, "operational_intelligence")]
        implementation_dispatches = [event for event in dispatches if event["payload"].get("platform_task_id") == implementation_id and event["payload"].get("decision_kind") == "implementation" and _implementation_dispatch_valid(event, case)]
        if reviewer_id == implementation_id or len(review_dispatches) != 1 or len(implementation_dispatches) != 1 or review_dispatches[0]["payload"].get("platform_context_id") == implementation_dispatches[0]["payload"].get("platform_context_id"):
            return "INDEPENDENT_REVIEW_REQUIRED"
    ultimate_decisions: dict[str, dict[str, Any]] = {}
    for gate_id, decision_kind in (("ultimate-routing", "routing"), ("ultimate-design", "design"), ("ultimate-final-disposition", "final")):
        if gate_id not in normative:
            continue
        matches = [event for event in dispatches if event["payload"].get("decision_kind") == decision_kind and _authority_dispatch_valid(event, case, "ultimate_intelligence")]
        if not matches:
            named = [event for event in dispatches if event["payload"].get("requested_role") == "ultimate_intelligence" and event["payload"].get("decision_kind") == decision_kind]
            return "AUTHORITY_DISPATCH_INVALID" if named else "ULTIMATE_GATE_RECEIPT_MISSING"
        if any(event["payload"].get("disposition") != "approved" for event in matches):
            return "ULTIMATE_GATE_NOT_APPROVED"
        if len(matches) != 1:
            return "AUTHORITY_DISPATCH_INVALID"
        ultimate_decisions[decision_kind] = matches[0]

    if "operational-review" in normative:
        reviews = [event for event in all_reviews if event["payload"].get("disposition") == "approved"]
        if not all_reviews:
            return "OPERATIONAL_REVIEW_RECEIPT_MISSING"
        if len(reviews) != 1 or len(all_reviews) != 1 or len(implementations) != 1 or reviews[0]["payload"].get("platform_task_id") == implementations[0]["payload"].get("platform_task_id") or reviews[0]["payload"].get("platform_context_id") == implementations[0]["payload"].get("platform_context_id"):
            return "INDEPENDENT_REVIEW_REQUIRED"

    if case_kind == "council_qualification":
        native = [event for event in dispatches if event["payload"].get("decision_kind") == "native_forward" and event["payload"].get("qualification_run_id") in _QUALIFICATION_GATES]
        if any(not _authority_dispatch_valid(event, case, "ultimate_intelligence") for event in native):
            return "NATIVE_FORWARD_RUNS_INSUFFICIENT"
        if any(event["payload"].get("disposition") != "approved" for event in native):
            return "NATIVE_FORWARD_RUN_NOT_APPROVED"
        by_run = {run_id: [event for event in native if event["payload"].get("qualification_run_id") == run_id] for run_id in _QUALIFICATION_GATES}
        if any(len(items) != 1 for items in by_run.values()):
            return "NATIVE_FORWARD_RUNS_INSUFFICIENT"
        required_native = [by_run[run_id][0] for run_id in _QUALIFICATION_GATES]
        task_ids = {event["payload"].get("platform_task_id") for event in required_native}
        context_ids = {event["payload"].get("platform_context_id") for event in required_native}
        if len(task_ids) < 2 or len(context_ids) < 2 or None in task_ids or None in context_ids:
            return "NATIVE_FORWARD_RUNS_NOT_FRESH"

    final = ultimate_decisions.get("final")
    if final:
        final_index = events.index(final)
        required_before_final = [event for event in events if (event["record_type"] == "packet" and event["payload"].get("phase") == "result") or event["record_type"] == "test" or (event["record_type"] == "dispatch" and event["payload"].get("decision_kind") in {"routing", "design", "review"}) or (event["record_type"] == "gate" and event["payload"].get("gate_id") == "independent-review")]
        if case_kind == "council_qualification":
            required_before_final.extend(event for event in events if event["record_type"] == "dispatch" and event["payload"].get("decision_kind") == "native_forward" and event["payload"].get("qualification_run_id") in _QUALIFICATION_GATES)
        if required_before_final and any(events.index(event) > final_index for event in required_before_final):
            return "FINAL_DISPOSITION_ORDER_INVALID"
        decision_boundary = [event for event in events if event["record_type"] == "packet" and event["payload"].get("phase") == "request"] + implementations
        for decision_kind in ("routing", "design"):
            decision = ultimate_decisions.get(decision_kind)
            if decision is not None and decision_boundary and any(events.index(decision) > events.index(work) for work in decision_boundary):
                return "FINAL_DISPOSITION_ORDER_INVALID"
    return None


def evaluate_contract_case(case_document: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a v2 case without inspecting a fixture name, path, or oracle."""
    try:
        issue = _security_problem(case_document)
        if issue:
            return _refuse(issue)
        issue = _candidate_identity_problem(case_document)
        if issue:
            return _refuse(issue)
        if not _document_valid(case_document):
            return _refuse("SCHEMA_VALIDATION_FAILED")
        issue = _evidence_problem(case_document["case_root"])
        if issue:
            return _refuse(issue)
        if not _registry_valid(case_document["registry"], case_document["identity"]) or not _capability_valid(case_document["provider_capability_receipt"]) or not _dispatch_valid(case_document["provider_dispatch_receipt"]):
            return _refuse("SCHEMA_VALIDATION_FAILED")
        state, issue = reduce_events(case_document)
        if issue:
            return _refuse(issue)
        assert state is not None
        case_kind, issue = _activation_and_route(case_document, state)
        if issue:
            return _refuse(issue, state)
        assert case_kind is not None
        effort, provider_code = _route_and_provider(case_document, state)
        if provider_code and provider_code != "EFFORT_ESCALATION_ACCEPTED":
            return _refuse(provider_code, state)
        assert effort is not None
        if not any(event["record_type"] in {"closure", "test"} or event["payload"].get("stage") == "decide" for event in state["history"].values()):
            return _outcome("resolved", "DEFAULT_EFFORT_HIGH", "high", state)
        issue = _stage_and_packets(case_document, state)
        if issue == "STAGE_DECIDE_ACCEPTED":
            return _outcome("accepted", issue, effort, state)
        if issue:
            return _refuse(issue, state)
        issue = _closure_and_gates(case_document, state, case_kind)
        if issue:
            return _refuse(issue, state)
        if case_document.get("pinned_schema_sha256") and case_document.get("package_schema_sha256") and case_document["pinned_schema_sha256"] != case_document["package_schema_sha256"]:
            return _outcome("accepted", "PINNED_SCHEMA_USED", effort, state)
        if provider_code:
            return _outcome("accepted", provider_code, effort, state)
        if state["candidate_transition"]:
            return _outcome("accepted", "CANDIDATE_TRANSITION_ACCEPTED", effort, state)
        if state["superseded"]:
            return _outcome("accepted", "SUPERSESSION_APPLIED", effort, state)
        if state["resumptions"]:
            return _outcome("resumed", "INTERRUPTION_RESUMED", effort, state)
        return _outcome("accepted", "CASE_ACCEPTED", effort, state)
    except (AttributeError, KeyError, TypeError, ValueError, OSError, RuntimeError, RecursionError):
        return _refuse("SCHEMA_VALIDATION_FAILED")


# v2 authoring deliberately has no provider client.  It captures local structural
# provenance from facts returned by an already-completed native dispatch.
_PACKAGE = Path(__file__).resolve().parents[4]
_PINNED_ARTIFACTS = (
    ".codex-plugin/plugin.json",
    "scripts/core/agent-council/0.2.0/Invoke-AgentCouncil.py",
    "scripts/core/agent-council/0.2.0/Bootstrap-AgentCouncil.py",
    "scripts/core/agent-council/0.2.0/Test-AgentCouncilContracts.py",
    "standards/agent-council-standard.v2.yaml",
    "standards/agent-council-record.schema.v2.yaml",
    "standards/agent-council-executing-bundle.schema.v2.yaml",
    "standards/agent-model-registry.schema.v2.yaml",
    "standards/provider-capability-receipt.schema.v2.yaml",
    "standards/provider-dispatch-receipt.schema.v2.yaml",
    "standards/agent-model-registry.v2.yaml",
    "standards/model-qualifications/initial-codex-designation.v2.yaml",
    "skills/agent-council/SKILL.md",
    "skills/agent-council/references/model-adapters.yaml",
    "skills/agent-council/references/review-lenses.yaml",
    "skills/agent-council/references/forward-tests.yaml",
    "skills/agent-council/references/project-profiles.yaml",
    "skills/agent-council/references/compound-engineering.yaml",
    "standards/project-profile.schema.yaml",
    "profiles/default.yaml",
)
_PROTECTED = {"case", "dispatch", "gate", "closure"}


class AuthoringError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _candidate_input_problem(candidate: Any) -> str | None:
    """Validate caller-supplied candidate material before a case root exists."""
    issue = _security_problem(candidate)
    if issue:
        return issue
    if not isinstance(candidate, dict) or any(not _sha(candidate.get(key)) for key in _CANDIDATE_HASH_FIELDS):
        return "SCHEMA_VALIDATION_FAILED"
    return None


def _legacy_default_project_profile(state: dict[str, Any]) -> dict[str, str] | None:
    """Derive a stable, explicitly legacy profile for pre-profile v2 cases.

    The profile is outer-agent guidance only.  It is intentionally derived
    from the already-pinned policy hash instead of claiming that an older case
    pinned the current package profile.
    """
    policy = state.get("policy_bundle")
    policy_sha256 = policy.get("policy_sha256") if isinstance(policy, dict) else None
    if not _sha(policy_sha256):
        return None
    return {
        "profile_id": "legacy-default",
        "profile_path": "legacy/default-on-read",
        "profile_sha256": _digest({"migration": "project-profile-default-on-read/v1", "policy_bundle_sha256": policy_sha256}),
        "semantic_policy_enforcement": "outer_agent_only",
    }


def _normalize_authoring_state(state: Any) -> Any:
    """Safely default fields introduced after the original v2 authoring form.

    This is an in-memory, default-on-read migration.  The next successful
    authoring transaction persists the normalized form without changing event
    history, candidate material, or the original policy identity.
    """
    if not isinstance(state, dict):
        return state
    normalized = dict(state)
    if "project_profile" not in normalized:
        profile = _legacy_default_project_profile(normalized)
        if profile is not None:
            normalized["project_profile"] = profile
    if "handoff_lifecycle" not in normalized:
        normalized["handoff_lifecycle"] = {}
    if "project_root" not in normalized and isinstance(normalized.get("case_root"), str):
        normalized["project_root"] = str(Path(normalized["case_root"]).parent.resolve())
    return normalized


def _authoring_state_problem(state: Any) -> str | None:
    """Reject unsafe state before either an event or the state document is written."""
    issue = _security_problem(state)
    if issue:
        return issue
    required = {"authoring_schema_version", "case_id", "case_root", "project_root", "route", "activation_class", "case_kind", "cycle_id", "policy_bundle", "project_profile", "engineering_candidate", "registry", "events", "capabilities", "dispatch_plans", "dispatch_receipts", "handoff_lifecycle"}
    if not isinstance(state, dict) or not required <= state.keys() or state.get("authoring_schema_version") != "agent-council.authoring/v2" or not isinstance(state.get("events"), list) or not isinstance(state.get("capabilities"), dict) or not isinstance(state.get("dispatch_plans"), dict) or not isinstance(state.get("dispatch_receipts"), dict) or not isinstance(state.get("handoff_lifecycle"), dict):
        return "SCHEMA_VALIDATION_FAILED"
    for context_id, receipt in state["capabilities"].items():
        if _public_text_problem(context_id) or not _capability_valid(receipt) or receipt.get("context_id") != context_id:
            return "SCHEMA_VALIDATION_FAILED"
    for receipt_id, receipt in state["dispatch_receipts"].items():
        if _public_text_problem(receipt_id) or not _dispatch_valid(receipt) or receipt.get("receipt_id") != receipt_id:
            return "SCHEMA_VALIDATION_FAILED"
    profile = state.get("project_profile")
    expected_profile = {
        "profile_id": "default",
        "profile_path": "profiles/default.yaml",
        "profile_sha256": state.get("policy_bundle", {}).get("artifact_pins", {}).get("profiles/default.yaml"),
        "semantic_policy_enforcement": "outer_agent_only",
    }
    legacy_profile = _legacy_default_project_profile(state)
    if not isinstance(profile, dict) or (profile != expected_profile and profile != legacy_profile):
        return "SCHEMA_VALIDATION_FAILED"
    lifecycle = state["handoff_lifecycle"]
    for nonce, status in lifecycle.items():
        plan = state["dispatch_plans"].get(nonce)
        if not _sha(nonce) or status not in {"reconciled", "invalidated", "interruption_reconciled"} or not isinstance(plan, dict) or plan.get("work_method") != "compound_engineering":
            return "SCHEMA_VALIDATION_FAILED"
        if status == "reconciled" and plan.get("consumed") is not True:
            return "SCHEMA_VALIDATION_FAILED"
        if status == "invalidated" and plan.get("invalidated") is not True:
            return "SCHEMA_VALIDATION_FAILED"
    return None


def _assert_pinned_project_root(root: Path, project_root: Path) -> None:
    state = _read_local_case(root)
    if state.get("project_root") != str(project_root.resolve()):
        raise AuthoringError("PROJECT_ROOT_MISMATCH")


def _dispatch_plan_identity_valid(identity: Any) -> bool:
    required = {"case_id", "policy_bundle_sha256", "registry_version", "registry_sha256", "candidate_id", "candidate_sha256", "cycle_id"}
    return isinstance(identity, dict) and set(identity) == required and _identity(identity) and _identifier(identity.get("candidate_id")) and _sha(identity.get("candidate_sha256")) and identity["candidate_id"] == f"candidate-{identity['candidate_sha256'][:24]}" and _identifier(identity.get("cycle_id"))


def _dispatch_payload_problem(payload: Any) -> str | None:
    """Validate every structural provenance field before consuming a plan."""
    if not isinstance(payload, dict) or payload.get("system_generated") is not True:
        return "SCHEMA_VALIDATION_FAILED"
    required = {
        "system_generated", "dispatch_receipt_id", "dispatch_receipt_sha256", "provider", "binding_id", "binding_sha256", "requested_role", "decision_kind", "disposition", "receipt_provenance", "receipt_assurance", "model_id", "selected_effort", "attested_effort", "capability_receipt_id", "capability_receipt_sha256", "capability_context_id", "capability_models", "capability_efforts", "capability_observed_at", "platform_task_id", "platform_context_id", "platform_output_ref", "plan_nonce_sha256", "dispatch_request_sha256", "dispatch_plan_identity",
    }
    if not required <= payload.keys():
        return "SCHEMA_VALIDATION_FAILED"
    public_fields = ("dispatch_receipt_id", "provider", "binding_id", "requested_role", "model_id", "capability_receipt_id", "capability_context_id", "capability_observed_at", "platform_task_id", "platform_context_id", "platform_output_ref")
    for field in public_fields:
        issue = _public_text_problem(payload.get(field))
        if issue:
            return issue
    if not all(_sha(payload.get(field)) for field in ("dispatch_receipt_sha256", "binding_sha256", "capability_receipt_sha256", "plan_nonce_sha256", "dispatch_request_sha256")):
        return "SCHEMA_VALIDATION_FAILED"
    string_enums = ("requested_role", "decision_kind", "disposition", "receipt_provenance", "receipt_assurance", "selected_effort", "attested_effort")
    if any(not isinstance(payload.get(field), str) for field in string_enums) or payload.get("requested_role") not in _ROLES or payload.get("decision_kind") not in {"routing", "design", "implementation", "review", "native_forward", "final"} or payload.get("disposition") not in {"approved", "hold", "rejected"} or payload.get("receipt_provenance") != "structural_only" or payload.get("receipt_assurance") != "structural_only" or payload.get("selected_effort") not in _EFFORTS or payload.get("attested_effort") not in _EFFORTS or not _public_text_list(payload.get("capability_models")) or not _public_text_list(payload.get("capability_efforts"), _EFFORTS) or not _dispatch_plan_identity_valid(payload.get("dispatch_plan_identity")):
        return "SCHEMA_VALIDATION_FAILED"
    if payload["model_id"] not in payload["capability_models"] or payload["selected_effort"] not in payload["capability_efforts"] or payload["attested_effort"] not in payload["capability_efforts"] or payload["capability_context_id"] != payload["platform_context_id"]:
        return "SCHEMA_VALIDATION_FAILED"
    method_fields = {"work_method", "orchestrator_owner", "council_reentry", "execution_mode"}
    if method_fields & set(payload):
        if not method_fields <= set(payload):
            return "SCHEMA_VALIDATION_FAILED"
        method_probe = {
            "work_method": payload["work_method"],
            "role": payload["requested_role"],
            "decision_kind": payload["decision_kind"],
            "orchestrator_owner": payload["orchestrator_owner"],
            "council_reentry": payload["council_reentry"],
            "execution_mode": payload["execution_mode"],
            "handoff_status": "pending" if payload["work_method"] == "compound_engineering" else "not_applicable",
            "consumed": False,
        }
        if not _method_contract_valid(method_probe):
            return "SCHEMA_VALIDATION_FAILED"
    capability_snapshot = {"receipt_type": "provider_capability", "receipt_id": payload["capability_receipt_id"], "provider": payload["provider"], "observed_at": payload["capability_observed_at"], "context_id": payload["capability_context_id"], "models": payload["capability_models"], "efforts": payload["capability_efforts"]}
    dispatch_snapshot = {"receipt_type": "provider_dispatch", "receipt_id": payload["dispatch_receipt_id"], "dispatch_id": payload["platform_task_id"], "provider": payload["provider"], "model_id": payload["model_id"], "selected_effort": payload["selected_effort"], "attested_effort": payload["attested_effort"], "context_id": payload["platform_context_id"], "system_generated": True}
    if payload["capability_receipt_sha256"] != _digest(capability_snapshot) or payload["dispatch_receipt_sha256"] != _digest(dispatch_snapshot):
        return "SCHEMA_VALIDATION_FAILED"
    packet_id = payload.get("packet_id")
    is_implementation = payload.get("decision_kind") == "implementation"
    if is_implementation:
        if not _identifier(packet_id):
            return "SCHEMA_VALIDATION_FAILED"
    elif packet_id is not None:
        return "SCHEMA_VALIDATION_FAILED"
    qualification_run_id = payload.get("qualification_run_id")
    if payload.get("decision_kind") == "native_forward":
        if qualification_run_id not in _QUALIFICATION_GATES:
            return "SCHEMA_VALIDATION_FAILED"
    elif qualification_run_id is not None:
        return "SCHEMA_VALIDATION_FAILED"
    return None


def _authoring_payload_problem(record_type: Any, payload: Any) -> str | None:
    """Validate every authoring payload at the single immutable-event boundary."""
    issue = _security_problem(payload)
    if issue:
        return issue
    if not isinstance(record_type, str) or record_type not in _TYPES or not isinstance(payload, dict):
        return "SCHEMA_VALIDATION_FAILED"
    if record_type in _PROTECTED and payload.get("system_generated") is not True:
        return "SCHEMA_VALIDATION_FAILED"
    if record_type == "case":
        if payload.get("stage") != "intake" or payload.get("route") not in _ROUTE_RANK or payload.get("activation_class") not in _ACTIVATION_ROUTE_FLOORS or payload.get("case_kind") not in {"operational_change", "council_qualification"}:
            return "SCHEMA_VALIDATION_FAILED"
    elif record_type == "packet":
        if not _identifier(payload.get("packet_id")) or payload.get("phase") not in {"request", "result"}:
            return "SCHEMA_VALIDATION_FAILED"
        if payload["phase"] == "request":
            if payload.get("status") != "accepted" or payload.get("requested_role") not in _ROLES:
                return "SCHEMA_VALIDATION_FAILED"
        elif payload.get("status") not in {"completed", "passed"} or not isinstance(payload.get("checks"), list) or not payload["checks"]:
            return "SCHEMA_VALIDATION_FAILED"
    elif record_type == "evidence":
        if not _identifier(payload.get("evidence_id")) or not isinstance(payload.get("kind"), str) or not payload["kind"]:
            return "SCHEMA_VALIDATION_FAILED"
        kind = payload["kind"]
        if kind == "provider_capability":
            if not _sha(payload.get("receipt_sha256")):
                return "SCHEMA_VALIDATION_FAILED"
        elif kind in _BEHAVIORAL_EVIDENCE_KINDS:
            if not isinstance(payload.get("path"), str) or not payload["path"] or not _sha(payload.get("sha256")) or not _identifier(payload.get("candidate_id")) or not _sha(payload.get("candidate_sha256")) or not _identifier(payload.get("cycle_id")):
                return "SCHEMA_VALIDATION_FAILED"
        elif kind == "candidate_transition_metadata":
            if not isinstance(payload.get("path"), str) or not payload["path"] or not _sha(payload.get("sha256")) or not _sha(payload.get("candidate_sha256")):
                return "SCHEMA_VALIDATION_FAILED"
        else:
            return "SCHEMA_VALIDATION_FAILED"
    elif record_type == "interruption":
        processes = payload.get("owned_processes")
        if payload.get("status") != "interrupted" or "owned_processes" not in payload or not isinstance(processes, list) or any(not _owned_process_valid(process) for process in processes):
            return "SCHEMA_VALIDATION_FAILED"
    elif record_type == "resumption":
        if payload.get("exact_resumption") is not True or not _identifier(payload.get("interruption_id")) or not _identifier(payload.get("prior_candidate_id")) or not _identifier(payload.get("prior_cycle_id")):
            return "SCHEMA_VALIDATION_FAILED"
    elif record_type == "supersession":
        if not _identifier(payload.get("supersedes_event_id")) or payload.get("retired_event_id") != payload.get("supersedes_event_id"):
            return "SCHEMA_VALIDATION_FAILED"
    elif record_type == "candidate_transition":
        if not _identifier(payload.get("prior_candidate_id")) or not _identifier(payload.get("fresh_evidence_id")):
            return "SCHEMA_VALIDATION_FAILED"
    elif record_type == "test":
        if not _identifier(payload.get("run_id")) or not _identifier(payload.get("evidence_id")) or payload.get("test_kind") not in {"normative", "fault"} or payload.get("status") not in {"passed", "failed"}:
            return "SCHEMA_VALIDATION_FAILED"
    elif record_type == "gate":
        if not _identifier(payload.get("gate_id")) or not _identifier(payload.get("evidence_id")) or payload.get("status") not in {"passed", "failed"}:
            return "SCHEMA_VALIDATION_FAILED"
    elif record_type == "dispatch":
        return _dispatch_payload_problem(payload)
    elif record_type == "closure":
        if payload.get("stage") != "close" or not isinstance(payload.get("required_gate_ids"), list):
            return "SCHEMA_VALIDATION_FAILED"
    return None


@contextmanager
def _authoring_lock(root: Path):
    """Serialize public CLI mutations for one case across local processes."""
    # This file is deliberately stable: `case.json` is atomically replaced on
    # every successful transaction, so locking it would lock different inodes.
    # The benign lock file is retained as part of the local case contract.
    lock_path = root / ".agent-council.lock"
    with lock_path.open("a+b") as handle:
        lock_path.chmod(0o600)
        unix_lock = None
        windows_lock = None
        try:
            try:
                import fcntl as unix_lock
                unix_lock.flock(handle.fileno(), unix_lock.LOCK_EX)
            except ImportError:
                import msvcrt as windows_lock
                if lock_path.stat().st_size == 0:
                    handle.write(b"\0"); handle.flush()
                handle.seek(0); windows_lock.locking(handle.fileno(), windows_lock.LK_LOCK, 1)
            yield
        finally:
            try:
                if unix_lock is not None:
                    unix_lock.flock(handle.fileno(), unix_lock.LOCK_UN)
                elif windows_lock is not None:
                    handle.seek(0); windows_lock.locking(handle.fileno(), windows_lock.LK_UNLCK, 1)
            except OSError:
                pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_exclusive(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(value)
            handle.flush(); __import__("os").fsync(handle.fileno())
    except FileExistsError as exc:
        raise AuthoringError("DUPLICATE_EVENT_REFUSED") from exc
    path.chmod(0o400)


def _write_atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{hashlib.sha256(value).hexdigest()}.tmp")
    if temporary.exists():
        temporary.unlink()
    with temporary.open("xb") as handle:
        handle.write(value); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_local_case(root: Path) -> dict[str, Any]:
    try:
        state = _normalize_authoring_state(_decode_json((root / "case.json").read_text(encoding="utf-8")))
    except _JsonDepthError as exc:
        raise AuthoringError("SCHEMA_VALIDATION_FAILED") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AuthoringError("CASE_NOT_FOUND") from exc
    if state.get("authoring_schema_version") != "agent-council.authoring/v2":
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    issue = _authoring_state_problem(state)
    if issue:
        raise AuthoringError(issue)
    return state


def _local_identity(state: dict[str, Any]) -> dict[str, str]:
    return {"case_id": state["case_id"], "policy_bundle_sha256": state["policy_bundle"]["policy_sha256"], "registry_version": state["registry"]["registry_version"], "registry_sha256": state["registry"]["registry_sha256"]}


def _copy_authoring_state(state: dict[str, Any]) -> dict[str, Any]:
    """Clone only through the hardened JSON boundary before a transaction."""
    try:
        copied = _decode_json(_canonical(state))
    except (json.JSONDecodeError, _JsonDepthError, TypeError, ValueError, RecursionError) as exc:
        raise AuthoringError("SCHEMA_VALIDATION_FAILED") from exc
    if not isinstance(copied, dict):
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    return copied


def _prepare_event_transaction(
    state: dict[str, Any],
    additions: list[tuple[str, dict[str, Any], str | None]],
) -> dict[str, Any]:
    """Build, validate, depth-check, and serialize a complete event/state proposal."""
    proposed = _copy_authoring_state(state)
    events: list[dict[str, Any]] = []
    try:
        for record_type, payload, requested_id in additions:
            sequence = len(proposed["events"]) + 1
            event_id = requested_id or f"event-{sequence:06d}-{record_type}"
            event = _prepared_local_event(proposed, record_type, payload, event_id)
            proposed["events"].append(event)
            events.append(event)
        issue = _authoring_state_problem(proposed)
        if issue:
            raise AuthoringError(issue)
        event_bytes = [_canonical(event) + b"\n" for event in events]
        state_bytes = _canonical(proposed) + b"\n"
    except AuthoringError:
        raise
    except (TypeError, ValueError, RecursionError) as exc:
        raise AuthoringError("SCHEMA_VALIDATION_FAILED") from exc
    return {"state": proposed, "events": events, "event_bytes": event_bytes, "state_bytes": state_bytes}


def _commit_prepared_transaction(
    root: Path,
    state: dict[str, Any],
    transaction: dict[str, Any],
    artifacts: tuple[tuple[Path, bytes], ...] = (),
) -> None:
    """Commit prevalidated supporting artifacts, immutable events, then state.

    Everything that can return a semantic refusal is checked before the first
    persistent write.  State is intentionally last, so it never references an
    event or evidence artifact that was not successfully written.
    """
    events = transaction["events"]
    event_bytes = transaction["event_bytes"]
    if any(path.exists() for path, _ in artifacts) or any((root / "events" / f"{event['event_id']}.json").exists() for event in events):
        raise AuthoringError("DUPLICATE_EVENT_REFUSED")
    for path, value in artifacts:
        _write_exclusive(path, value)
    for event, value in zip(events, event_bytes):
        _write_exclusive(root / "events" / f"{event['event_id']}.json", value)
    _write_atomic(root / "case.json", transaction["state_bytes"])
    state.clear()
    state.update(transaction["state"])


def _append_local_event(root: Path, state: dict[str, Any], record_type: str, payload: dict[str, Any], event_id: str | None = None) -> dict[str, Any]:
    transaction = _prepare_event_transaction(state, [(record_type, payload, event_id)])
    _commit_prepared_transaction(root, state, transaction)
    return transaction["events"][0]


def _pinned_artifact_material() -> tuple[dict[str, str], tuple[tuple[str, bytes], ...], dict[str, Any]]:
    """Read and validate all pin inputs before a case root is created."""
    pins: dict[str, str] = {}
    material: list[tuple[str, bytes]] = []
    registry_bytes: bytes | None = None
    for relative in _PINNED_ARTIFACTS:
        source = _PACKAGE / relative
        if not source.is_file():
            raise AuthoringError("PINNED_ARTIFACT_MISSING")
        value = source.read_bytes()
        material.append((relative, value))
        pins[relative] = hashlib.sha256(value).hexdigest()
        if relative == "standards/agent-model-registry.v2.yaml":
            registry_bytes = value
    if registry_bytes is None:
        raise AuthoringError("PINNED_ARTIFACT_MISSING")
    try:
        registry = _decode_json(registry_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, _JsonDepthError, ValueError) as exc:
        raise AuthoringError("PINNED_ARTIFACT_MISSING") from exc
    if not isinstance(registry, dict):
        raise AuthoringError("PINNED_ARTIFACT_MISSING")
    return pins, tuple(material), registry


def _candidate_artifact_digest(pins: dict[str, str]) -> str:
    """Pin behavioral artifacts, deliberately excluding raw manifest status."""
    return _digest(pins)


def init_case(root: Path, project_root: Path, case_id: str, route: str, candidate: dict[str, Any] | None = None, activation_class: str | None = None, case_kind: str = "operational_change") -> dict[str, Any]:
    defaults = {"R1": "bounded_automation_repair", "R2": "unqualified_composition", "R3": "shared_contract_change"}
    # Omission selects a route default.  An explicitly supplied empty or
    # malformed class is an invalid public request and must not create a root.
    if not isinstance(route, str) or not isinstance(case_kind, str):
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    if activation_class is None:
        activation_class = defaults.get(route)
    elif _public_text_problem(activation_class):
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    floor = _ACTIVATION_ROUTE_FLOORS.get(activation_class)
    if not _identifier(case_id) or route not in _ROUTE_RANK or floor is None or _ROUTE_RANK[route] < _ROUTE_RANK[floor] or case_kind not in {"operational_change", "council_qualification"} or ((case_kind == "council_qualification") != (activation_class == "council_qualification")):
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    if candidate is not None:
        issue = _candidate_input_problem(candidate)
        if issue:
            raise AuthoringError(issue)
    if root.exists():
        raise AuthoringError("DUPLICATE_EVENT_REFUSED")
    pins, pin_material, registry = _pinned_artifact_material()
    policy = {key: value for key, value in pins.items() if key.startswith("standards/") or key.startswith("skills/")}
    policy_sha = _digest(policy)
    candidate_value = candidate if candidate is not None else {"source_sha256": _file_sha(Path(__file__)), "package_sha256": _candidate_artifact_digest(pins), "dependency_lock_sha256": _digest({}), "harness_sha256": _file_sha(Path(__file__))}
    for key in _CANDIDATE_HASH_FIELDS:
        if not _sha(candidate_value.get(key)):
            raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    candidate_hashes = dict(candidate_value, policy_sha256=policy_sha)
    candidate_sha = _candidate_digest(candidate_hashes)
    state = {"authoring_schema_version": "agent-council.authoring/v2", "case_id": case_id, "case_root": str(root.resolve()), "project_root": str(project_root.resolve()), "route": route, "activation_class": activation_class, "case_kind": case_kind, "cycle_id": "cycle-000001", "policy_bundle": {"policy_bundle_id": "policy-v2", "policy_sha256": policy_sha, "artifact_pins": pins}, "project_profile": {"profile_id": "default", "profile_path": "profiles/default.yaml", "profile_sha256": pins["profiles/default.yaml"], "semantic_policy_enforcement": "outer_agent_only"}, "engineering_candidate": dict(candidate_hashes, candidate_id=f"candidate-{candidate_sha[:24]}", candidate_sha256=candidate_sha), "registry": registry, "events": [], "capabilities": {}, "dispatch_plans": {}, "dispatch_receipts": {}, "handoff_lifecycle": {}}
    transaction = _prepare_event_transaction(state, [("case", {"stage": "intake", "route": route, "activation_class": activation_class, "case_kind": case_kind, "system_generated": True}, None)])
    # The proposed state, its first event, and every pin are complete and
    # serialized before a directory is made visible at the requested root.
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{root.name}.agent-council-", dir=root.parent))
    try:
        for relative, value in pin_material:
            _write_exclusive(staging / "pinned" / relative, value)
        event = transaction["events"][0]
        _write_exclusive(staging / "events" / f"{event['event_id']}.json", transaction["event_bytes"][0])
        _write_exclusive(staging / "case.json", transaction["state_bytes"])
        if root.exists():
            raise AuthoringError("DUPLICATE_EVENT_REFUSED")
        os.rename(staging, root)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    state = transaction["state"]
    return _outcome("accepted", "CASE_INITIALIZED", state=state) | {"candidate_artifact_sha256": state["engineering_candidate"]["package_sha256"]}


def build_bundle(root: Path) -> dict[str, Any]:
    state = _read_local_case(root)
    pins = state["policy_bundle"]["artifact_pins"]
    for relative, expected in pins.items():
        pinned = root / "pinned" / relative
        if not pinned.is_file() or _file_sha(pinned) != expected:
            raise AuthoringError("PINNED_ARTIFACT_MISSING")
    descriptor = {"runtime": "python-standard-library-only", "provider_calls": "none", "pinned_artifacts": sorted(pins), "assurance": "structural_only", "provider_execution_attested": False, "uat_authority": False, "provider_signing": "not_cryptographically_verified"}
    try:
        descriptor_bytes = _canonical(descriptor) + b"\n"
        bundle = {"case_id": state["case_id"], "policy_bundle_sha256": state["policy_bundle"]["policy_sha256"], "engineering_candidate_sha256": _digest(state["engineering_candidate"]), "candidate_artifact_sha256": state["engineering_candidate"]["package_sha256"], "runtime_descriptor_sha256": hashlib.sha256(descriptor_bytes).hexdigest(), "pinned_artifact_count": len(pins)}
        bundle_bytes = _canonical(bundle) + b"\n"
    except (TypeError, ValueError, RecursionError) as exc:
        raise AuthoringError("SCHEMA_VALIDATION_FAILED") from exc
    _write_atomic(root / "runtime-descriptor.json", descriptor_bytes)
    _write_atomic(root / "executing-bundle.json", bundle_bytes)
    return _outcome("accepted", "EXECUTING_BUNDLE_BUILT") | bundle


def _binding(state: dict[str, Any], provider: str, role: str) -> dict[str, Any]:
    if provider == "claude_code" and state["registry"].get("provider_states", {}).get(provider, {}).get("council_status") != "qualified":
        raise AuthoringError("REQUIRED_TIER_BINDING_UNAVAILABLE")
    matches = [item for item in state["registry"].get("bindings", []) if item.get("provider") == provider and item.get("tier") == role and item.get("status") == "qualified"]
    if len(matches) != 1:
        raise AuthoringError("REQUIRED_TIER_BINDING_UNAVAILABLE")
    return matches[0]


def capture_capability(root: Path, provider: str, model_id: str, efforts: list[str], context_id: str, observed_at: str | None) -> dict[str, Any]:
    if any(_public_text_problem(value) for value in (provider, model_id, context_id)) or not _public_text_list(efforts, _EFFORTS):
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    observed_at = _utc_now() if observed_at is None else observed_at
    if _public_text_problem(observed_at):
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    try: age = abs((datetime.now(timezone.utc) - datetime.fromisoformat(observed_at.replace("Z", "+00:00")).astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError) as exc: raise AuthoringError("SCHEMA_VALIDATION_FAILED") from exc
    if age > 86400: raise AuthoringError("CAPABILITY_STALE")
    state = _read_local_case(root)
    receipt = {"receipt_type": "provider_capability", "receipt_id": f"capability-{len(state['capabilities']) + 1:06d}", "provider": provider, "observed_at": observed_at, "context_id": context_id, "models": [model_id], "efforts": efforts}
    receipt["receipt_sha256"] = _digest(receipt)
    proposed = _copy_authoring_state(state)
    proposed["capabilities"][context_id] = receipt
    transaction = _prepare_event_transaction(proposed, [("evidence", {"evidence_id": receipt["receipt_id"], "kind": "provider_capability", "receipt_sha256": receipt["receipt_sha256"]}, None)])
    _commit_prepared_transaction(root, state, transaction)
    event = transaction["events"][0]
    return _outcome("accepted", "CAPABILITY_CAPTURED") | {"receipt": receipt, "event_id": event["event_id"]}


def _dispatch_plan_identity(state: dict[str, Any]) -> dict[str, str]:
    candidate = state["engineering_candidate"]
    return dict(_local_identity(state), candidate_id=candidate["candidate_id"], candidate_sha256=candidate["candidate_sha256"], cycle_id=state["cycle_id"])


def _invalidate_dispatch_plans(state: dict[str, Any]) -> None:
    lifecycle = state.setdefault("handoff_lifecycle", {})
    for nonce, plan in state.get("dispatch_plans", {}).items():
        if not plan.get("consumed"):
            plan["invalidated"] = True
            # A Compound Engineering handoff cannot survive a candidate or
            # cycle boundary.  Lifecycle state is deliberately separate from
            # the hashed immutable request.
            if plan.get("work_method") == "compound_engineering":
                lifecycle[nonce] = "invalidated"


def _pending_compound_engineering_handoff(state: dict[str, Any]) -> bool:
    """Return whether a CE handoff retains the Council execution lease."""
    lifecycle = state.get("handoff_lifecycle", {})
    return any(
        plan.get("work_method") == "compound_engineering"
        and not plan.get("consumed")
        and not plan.get("invalidated")
        and lifecycle.get(nonce) is None
        for nonce, plan in state.get("dispatch_plans", {}).items()
    )


def _require_no_pending_compound_engineering_handoff(state: dict[str, Any]) -> None:
    """Prevent parallel Council work while a bounded CE handoff is active."""
    if _pending_compound_engineering_handoff(state):
        raise AuthoringError("COMPOUND_ENGINEERING_HANDOFF_PENDING")


def _reconcile_pending_compound_engineering_handoffs(state: dict[str, Any], status: str) -> None:
    """Terminally reconcile outstanding CE leases during an interruption."""
    if status != "interruption_reconciled":
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    lifecycle = state.setdefault("handoff_lifecycle", {})
    for nonce, plan in state.get("dispatch_plans", {}).items():
        if plan.get("work_method") == "compound_engineering" and not plan.get("consumed") and not plan.get("invalidated"):
            lifecycle[nonce] = status


_NOTICE_COST_CLASS = {
    "ultimate_intelligence": "premium",
    "operational_intelligence": "premium",
    "technical_tactical_intelligence": "standard",
    "worker_intelligence": "economical",
}
_NOTICE_REASON = {
    "routing": "the case requires an independent routing decision",
    "design": "the approved route requires design before implementation",
    "implementation": "the case is ready for bounded implementation work",
    "review": "the implementation requires an independent operational review",
    "final": "the case requires a final independent disposition",
    "native_forward": "the candidate requires a fresh native forward qualification run",
}


def _user_notice(model_id: str, effort: str, role: str, decision_kind: str) -> dict[str, str]:
    """Return the exact public notice bound to a dispatch request.

    This is a transparency record for the outer agent to display. It proves
    that a notice was generated, not that any chat client rendered it.
    """
    cost_class = _NOTICE_COST_CLASS.get(role)
    reason = _NOTICE_REASON.get(decision_kind)
    if cost_class is None or reason is None:
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    task = f"{decision_kind} task"
    return {
        "schema_version": "agent-council.user-notice/v1",
        "model_id": model_id,
        "effort": effort,
        "role": role,
        "decision_kind": decision_kind,
        "cost_class": cost_class,
        "task": task,
        "reason": reason,
        "message": f"Council: {model_id}/{effort} ({cost_class}) assigned {task} because {reason}.",
    }


def _user_notice_valid(notice: Any, model_id: str, effort: str, role: str, decision_kind: str) -> bool:
    return isinstance(notice, dict) and notice == _user_notice(model_id, effort, role, decision_kind)


def _method_contract(work_method: str, role: str, decision_kind: str) -> dict[str, str]:
    """Return the immutable routing boundary for one dispatch method."""
    if work_method == "native":
        return {
            "work_method": "native",
            "orchestrator_owner": "council",
            "council_reentry": "denied",
            "execution_mode": "native",
            "handoff_status": "not_applicable",
        }
    if work_method == "compound_engineering" and role == "technical_tactical_intelligence" and decision_kind == "implementation":
        return {
            "work_method": "compound_engineering",
            "orchestrator_owner": "compound_engineering",
            "council_reentry": "denied",
            "execution_mode": "return_to_caller",
            "handoff_status": "pending",
        }
    raise AuthoringError("WORK_METHOD_POLICY_INVALID")


def _method_contract_valid(plan: dict[str, Any]) -> bool:
    try:
        expected = _method_contract(plan.get("work_method"), plan.get("role"), plan.get("decision_kind"))
    except AuthoringError:
        return False
    # These are request fields and remain immutable after planning. Terminal
    # CE lifecycle is recorded in state.handoff_lifecycle, never here.
    return all(plan.get(key) == value for key, value in expected.items())


def dispatch_plan(root: Path, provider: str, role: str, context_id: str, effort: str = "high", decision_kind: str | None = None, qualification_run_id: str | None = None, work_method: str = "native") -> dict[str, Any]:
    if any(_public_text_problem(value) for value in (provider, role, context_id, effort, work_method)) or (decision_kind is not None and _public_text_problem(decision_kind)) or (qualification_run_id is not None and _public_text_problem(qualification_run_id)):
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    state = _read_local_case(root); binding = _binding(state, provider, role)
    if _candidate_identity_problem(state) or not _registry_valid(state["registry"], _local_identity(state)):
        raise AuthoringError("DISPATCH_PLAN_IDENTITY_MISMATCH")
    defaults = {"ultimate_intelligence": "routing", "operational_intelligence": "review", "technical_tactical_intelligence": "implementation", "worker_intelligence": "implementation"}
    decision_kind = decision_kind or defaults.get(role)
    allowed_kinds = {"ultimate_intelligence": {"routing", "design", "final", "native_forward"}, "operational_intelligence": {"review"}, "technical_tactical_intelligence": {"implementation"}, "worker_intelligence": {"implementation"}}
    if not context_id or decision_kind not in allowed_kinds.get(role, set()) or (decision_kind == "native_forward" and (state.get("case_kind") != "council_qualification" or qualification_run_id not in _QUALIFICATION_GATES)) or (decision_kind != "native_forward" and qualification_run_id is not None):
        raise AuthoringError("DISPATCH_PLAN_IDENTITY_MISMATCH")
    method = _method_contract(work_method, role, decision_kind)
    # A CE handoff owns the sole Council execution lease until terminally
    # reconciled. This blocks native as well as CE dispatches.
    _require_no_pending_compound_engineering_handoff(state)
    if role in {"technical_tactical_intelligence", "worker_intelligence"}:
        current = [event for event in state["events"] if event["record_type"] == "dispatch" and event["cycle_id"] == state["cycle_id"] and event["candidate_id"] == state["engineering_candidate"]["candidate_id"]]
        required_decisions = ["routing"] + (["design"] if state["route"] in {"R2", "R3"} else [])
        case_view = {"registry": state["registry"]}
        if any(not any(event["payload"].get("decision_kind") == decision and event["payload"].get("disposition") == "approved" and _authority_dispatch_valid(event, case_view, "ultimate_intelligence") for event in current) for decision in required_decisions):
            raise AuthoringError("ULTIMATE_GATE_RECEIPT_MISSING")
    if effort not in _EFFORTS or _EFFORTS.index(effort) < _EFFORTS.index("high"):
        raise AuthoringError("EFFORT_POLICY_INVALID")
    if effort != "high":
        # Elevated effort needs an evidenced cause, represented by a prior system gate.
        causes = [e for e in state["events"] if e["record_type"] == "gate" and e["payload"].get("cause") in _ESCALATION_CAUSES]
        if not causes: raise AuthoringError("EFFORT_POLICY_INVALID")
    nonce = hashlib.sha256(f"{state['case_id']}:{len(state['dispatch_plans'])}:{_utc_now()}".encode()).hexdigest()
    notice = _user_notice(binding["model_id"], effort, role, decision_kind)
    request = {"plan_nonce": nonce, "identity": _dispatch_plan_identity(state), "provider": provider, "role": role, "model_id": binding["model_id"], "binding_id": binding["binding_id"], "binding_sha256": binding["binding_sha256"], "effort": effort, "context_id": context_id, "decision_kind": decision_kind, "qualification_run_id": qualification_run_id, "user_notice": notice} | method
    if role in {"technical_tactical_intelligence", "worker_intelligence"}:
        request["packet_id"] = f"packet-{len(state['dispatch_plans']) + 1:06d}"
    plan = dict(request, request_sha256=_digest(request), consumed=False)
    try:
        request_bytes = _canonical(request) + b"\n"
    except (TypeError, ValueError, RecursionError) as exc:
        raise AuthoringError("SCHEMA_VALIDATION_FAILED") from exc
    proposed = _copy_authoring_state(state)
    proposed["dispatch_plans"][nonce] = plan
    additions: list[tuple[str, dict[str, Any], str | None]] = []
    if "packet_id" in plan:
        additions.append(("packet", {"packet_id": plan["packet_id"], "phase": "request", "status": "accepted", "requested_role": role, "dispatch_plan_nonce_sha256": _digest(nonce), "dispatch_request_sha256": plan["request_sha256"]}, None))
    transaction = _prepare_event_transaction(proposed, additions)
    _commit_prepared_transaction(root, state, transaction, ((root / "requests" / f"{nonce}.json", request_bytes),))
    return _outcome("accepted", "DISPATCH_PLAN_CREATED") | plan


def _dispatch_capture_plan_problem(state: dict[str, Any], plan: Any, nonce: Any, root: Path) -> str | None:
    """Verify the immutable request before accepting any provider return data."""
    if not _sha(nonce) or not isinstance(plan, dict):
        return "DISPATCH_PLAN_IDENTITY_MISMATCH"
    role = plan.get("role")
    if not isinstance(role, str) or role not in _ROLES:
        return "SCHEMA_VALIDATION_FAILED"
    request_keys = {"plan_nonce", "identity", "provider", "role", "model_id", "binding_id", "binding_sha256", "effort", "context_id", "decision_kind", "qualification_run_id", "user_notice", "work_method", "orchestrator_owner", "council_reentry", "execution_mode", "handoff_status"}
    if role in {"technical_tactical_intelligence", "worker_intelligence"}:
        request_keys.add("packet_id")
    plan_keys = request_keys | {"request_sha256", "consumed"}
    if plan.get("invalidated") is not None:
        plan_keys.add("invalidated")
    if set(plan) != plan_keys or not isinstance(plan.get("consumed"), bool) or ("invalidated" in plan and not isinstance(plan["invalidated"], bool)):
        return "SCHEMA_VALIDATION_FAILED"
    if plan.get("plan_nonce") != nonce or not _dispatch_plan_identity_valid(plan.get("identity")):
        return "DISPATCH_PLAN_IDENTITY_MISMATCH"
    public_fields = ("provider", "model_id", "binding_id", "effort", "context_id", "decision_kind")
    if any(_public_text_problem(plan.get(field)) for field in public_fields) or not _sha(plan.get("binding_sha256")) or not _sha(plan.get("request_sha256")):
        return "SCHEMA_VALIDATION_FAILED"
    if role in {"technical_tactical_intelligence", "worker_intelligence"} and not _identifier(plan.get("packet_id")):
        return "SCHEMA_VALIDATION_FAILED"
    if plan.get("decision_kind") not in {"routing", "design", "implementation", "review", "native_forward", "final"} or plan.get("effort") not in _EFFORTS or (plan.get("qualification_run_id") is not None and plan.get("qualification_run_id") not in _QUALIFICATION_GATES):
        return "SCHEMA_VALIDATION_FAILED"
    if not _user_notice_valid(plan.get("user_notice"), plan["model_id"], plan["effort"], role, plan["decision_kind"]) or not _method_contract_valid(plan):
        return "SCHEMA_VALIDATION_FAILED"
    allowed_kinds = {"ultimate_intelligence": {"routing", "design", "final", "native_forward"}, "operational_intelligence": {"review"}, "technical_tactical_intelligence": {"implementation"}, "worker_intelligence": {"implementation"}}
    if plan["decision_kind"] not in allowed_kinds[role] or (plan["decision_kind"] == "native_forward" and plan.get("qualification_run_id") not in _QUALIFICATION_GATES) or (plan["decision_kind"] != "native_forward" and plan.get("qualification_run_id") is not None):
        return "DISPATCH_PLAN_IDENTITY_MISMATCH"
    request = {key: value for key, value in plan.items() if key not in {"request_sha256", "consumed", "invalidated"}}
    if plan.get("request_sha256") != _digest(request):
        return "DISPATCH_PLAN_IDENTITY_MISMATCH"
    request_path = root / "requests" / f"{nonce}.json"
    try:
        if not request_path.is_file() or request_path.is_symlink() or request_path.stat().st_mode & 0o222 or _decode_json(request_path.read_text(encoding="utf-8")) != request:
            return "DISPATCH_PLAN_IDENTITY_MISMATCH"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, _JsonDepthError, ValueError):
        return "DISPATCH_PLAN_IDENTITY_MISMATCH"
    matches = [binding for binding in state["registry"].get("bindings", []) if isinstance(binding, dict) and binding.get("provider") == plan["provider"] and binding.get("tier") == role and binding.get("status") == "qualified" and binding.get("model_id") == plan["model_id"] and binding.get("binding_id") == plan["binding_id"] and binding.get("binding_sha256") == plan["binding_sha256"]]
    return None if len(matches) == 1 else "DISPATCH_PLAN_IDENTITY_MISMATCH"


def _prepared_local_event(state: dict[str, Any], record_type: str, payload: dict[str, Any], event_id: str) -> dict[str, Any]:
    """Construct and validate an immutable event without touching disk or state."""
    issue = _authoring_state_problem(state) or _authoring_payload_problem(record_type, payload)
    if issue:
        raise AuthoringError(issue)
    if not _identifier(event_id) or any(item.get("event_id") == event_id for item in state["events"] if isinstance(item, dict)):
        raise AuthoringError("DUPLICATE_EVENT_REFUSED")
    prior = state["events"][-1]["event_sha256"] if state["events"] else None
    event = {"record_type": record_type, "event_id": event_id, "identity": _local_identity(state), "candidate_id": state["engineering_candidate"]["candidate_id"], "cycle_id": state["cycle_id"], "recorded_at": _utc_now(), "payload": dict(payload, previous_event_sha256=prior)}
    event["event_sha256"] = _digest(event)
    return event


def dispatch_capture(root: Path, provider: str, nonce: str, task_id: str, model_id: str, effort: str, context_id: str, output_ref: str, decision_kind: str = "implementation", disposition: str = "approved", qualification_run_id: str | None = None) -> dict[str, Any]:
    public_values = (provider, nonce, task_id, model_id, effort, context_id, output_ref, decision_kind, disposition)
    if any(_public_text_problem(value) for value in public_values) or (qualification_run_id is not None and _public_text_problem(qualification_run_id)):
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    state = _read_local_case(root)
    plan = state["dispatch_plans"].get(nonce)
    if plan is None:
        raise AuthoringError("DISPATCH_PLAN_REQUIRED")
    plan_problem = _dispatch_capture_plan_problem(state, plan, nonce, root)
    if plan_problem:
        raise AuthoringError(plan_problem)
    if plan["consumed"]:
        raise AuthoringError("DISPATCH_PLAN_CONSUMED")
    if plan.get("invalidated") or plan.get("identity") != _dispatch_plan_identity(state):
        raise AuthoringError("DISPATCH_PLAN_STALE")
    if _candidate_identity_problem(state) or not _registry_valid(state["registry"], _local_identity(state)):
        raise AuthoringError("DISPATCH_PLAN_IDENTITY_MISMATCH")
    if decision_kind != plan["decision_kind"] or qualification_run_id != plan["qualification_run_id"]:
        raise AuthoringError("DISPATCH_PLAN_IDENTITY_MISMATCH")
    if provider != plan["provider"] or model_id != plan["model_id"] or effort != plan["effort"] or context_id != plan["context_id"] or decision_kind not in {"routing", "design", "implementation", "review", "native_forward", "final"} or disposition not in {"approved", "hold", "rejected"} or (qualification_run_id is not None and qualification_run_id not in _QUALIFICATION_GATES):
        raise AuthoringError("PROVIDER_RECEIPT_MISMATCH")
    capability = state["capabilities"].get(context_id)
    if capability is None:
        raise AuthoringError("CAPABILITY_REQUIRED")
    if not _capability_valid(capability):
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    if capability["provider"] != provider or capability["context_id"] != context_id or model_id not in capability["models"] or effort not in capability["efforts"]:
        raise AuthoringError("PROVIDER_RECEIPT_MISMATCH")
    receipt_id = f"dispatch-{len(state['events']) + 1:06d}"
    if receipt_id in state["dispatch_receipts"]:
        raise AuthoringError("DUPLICATE_EVENT_REFUSED")
    receipt = {"receipt_type": "provider_dispatch", "receipt_id": receipt_id, "dispatch_id": task_id, "provider": provider, "model_id": model_id, "selected_effort": effort, "attested_effort": effort, "context_id": context_id, "system_generated": True}
    receipt["receipt_sha256"] = _digest(receipt)
    if not _dispatch_valid(receipt):
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    payload = {"system_generated": True, "dispatch_receipt_id": receipt["receipt_id"], "dispatch_receipt_sha256": receipt["receipt_sha256"], "provider": provider, "binding_id": plan["binding_id"], "binding_sha256": plan["binding_sha256"], "requested_role": plan["role"], "decision_kind": decision_kind, "disposition": disposition, "receipt_provenance": "structural_only", "receipt_assurance": "structural_only", "model_id": model_id, "selected_effort": effort, "attested_effort": effort, "capability_receipt_id": capability["receipt_id"], "capability_receipt_sha256": capability["receipt_sha256"], "capability_context_id": capability["context_id"], "capability_models": capability["models"], "capability_efforts": capability["efforts"], "capability_observed_at": capability["observed_at"], "platform_task_id": task_id, "platform_context_id": context_id, "platform_output_ref": output_ref, "plan_nonce_sha256": _digest(nonce), "dispatch_request_sha256": plan["request_sha256"], "dispatch_plan_identity": plan["identity"], "work_method": plan["work_method"], "orchestrator_owner": plan["orchestrator_owner"], "council_reentry": plan["council_reentry"], "execution_mode": plan["execution_mode"]}
    if "packet_id" in plan:
        payload["packet_id"] = plan["packet_id"]
    if qualification_run_id is not None:
        payload["qualification_run_id"] = qualification_run_id
    issue = _dispatch_payload_problem(payload)
    if issue:
        raise AuthoringError(issue)
    try:
        staged_state = _decode_json(_canonical(state))
    except (TypeError, ValueError, RecursionError) as exc:
        raise AuthoringError("SCHEMA_VALIDATION_FAILED") from exc
    staged_state["dispatch_plans"][nonce]["consumed"] = True
    if plan["work_method"] == "compound_engineering":
        staged_state["handoff_lifecycle"][nonce] = "reconciled"
    staged_state["dispatch_receipts"][receipt_id] = receipt
    transaction = _prepare_event_transaction(staged_state, [("dispatch", payload, f"event-{len(state['events']) + 1:06d}-dispatch")])
    _commit_prepared_transaction(root, state, transaction)
    event = transaction["events"][0]
    return _outcome("accepted", "DISPATCH_CAPTURED") | {"receipt": receipt, "event_id": event["event_id"]}


def evidence_add(root: Path, evidence_id: str, evidence_kind: str, content: Any) -> dict[str, Any]:
    issue = _security_problem(content)
    if not _identifier(evidence_id) or not isinstance(evidence_kind, str) or issue:
        raise AuthoringError(issue or "SCHEMA_VALIDATION_FAILED")
    state = _read_local_case(root)
    candidate = state["engineering_candidate"]
    if not _behavioral_evidence_content_valid(content, evidence_kind, candidate["candidate_id"], candidate["candidate_sha256"], state["cycle_id"]):
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    path = root / "evidence" / f"{evidence_id}.json"
    content_bytes = _canonical(content) + b"\n"
    payload = {
        "evidence_id": evidence_id,
        "kind": evidence_kind,
        "path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(content_bytes).hexdigest(),
        "candidate_id": candidate["candidate_id"],
        "candidate_sha256": candidate["candidate_sha256"],
        "cycle_id": state["cycle_id"],
    }
    event_id = f"evidence-{evidence_id}"
    if not _identifier(event_id):
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    transaction = _prepare_event_transaction(state, [("evidence", payload, event_id)])
    _commit_prepared_transaction(root, state, transaction, ((path, content_bytes),))
    event = transaction["events"][0]
    return _outcome("accepted", "EVIDENCE_ADDED") | {"event_id": event["event_id"]}


def _authoring_document(state: dict[str, Any], case_root: Path, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    active_events = events if events is not None else state["events"]
    candidate_id = state["engineering_candidate"]["candidate_id"]
    retired = {event["payload"].get("supersedes_event_id") for event in active_events if event["record_type"] == "supersession"}
    implementation = [event for event in active_events if event["event_id"] not in retired and event["record_type"] == "dispatch" and event["cycle_id"] == state["cycle_id"] and event["candidate_id"] == candidate_id and event["payload"].get("decision_kind") == "implementation" and event["payload"].get("disposition") == "approved"]
    if len(implementation) != 1:
        raise AuthoringError("PACKET_RESULT_CONFLICT")
    receipt_id = implementation[0]["payload"].get("dispatch_receipt_id")
    receipt = state.get("dispatch_receipts", {}).get(receipt_id)
    if not receipt:
        raise AuthoringError("PROVIDER_RECEIPT_UNVERIFIED")
    capability = state.get("capabilities", {}).get(receipt["context_id"])
    if not capability:
        raise AuthoringError("CAPABILITY_REQUIRED")
    return {
        "schema_version": "agent-council.case/v2",
        "case_id": state["case_id"],
        "case_root": str(case_root),
        "cycle_id": state["cycle_id"],
        "route": state["route"],
        "identity": _local_identity(state),
        "policy_bundle": {"policy_bundle_id": state["policy_bundle"]["policy_bundle_id"], "policy_sha256": state["policy_bundle"]["policy_sha256"]},
        "engineering_candidate": state["engineering_candidate"],
        "registry": state["registry"],
        "provider_capability_receipt": capability,
        "provider_dispatch_receipt": receipt,
        "events": active_events,
    }


def close_local_case(root: Path) -> dict[str, Any]:
    state = _read_local_case(root)
    _require_no_pending_compound_engineering_handoff(state)
    if any(event["record_type"] == "closure" and event["cycle_id"] == state["cycle_id"] for event in state["events"]):
        raise AuthoringError("DUPLICATE_EVENT_REFUSED")
    if state.get("case_kind") == "council_qualification":
        native = [event for event in state["events"] if event["record_type"] == "dispatch" and event["cycle_id"] == state["cycle_id"] and event["candidate_id"] == state["engineering_candidate"]["candidate_id"] and event["payload"].get("decision_kind") == "native_forward"]
        if any(event["payload"].get("qualification_run_id") not in _QUALIFICATION_GATES for event in native) or any(sum(1 for event in native if event["payload"].get("qualification_run_id") == run_id) != 1 for run_id in _QUALIFICATION_GATES):
            raise AuthoringError("NATIVE_FORWARD_RUNS_INSUFFICIENT")
    required = list(_ROUTE_GATES[state["route"]])
    if state.get("case_kind") == "council_qualification":
        required.extend(_QUALIFICATION_GATES)
    gates = [e for e in state["events"] if e["record_type"] == "gate" and e["cycle_id"] == state["cycle_id"] and e["candidate_id"] == state["engineering_candidate"]["candidate_id"] and e["payload"].get("status") == "passed"]
    tests = [e for e in state["events"] if e["record_type"] == "test" and e["cycle_id"] == state["cycle_id"] and e["payload"].get("status") == "passed"]
    passed = {e["payload"].get("gate_id") for e in gates}
    if not set(required) <= passed or not tests: raise AuthoringError("REQUIRED_GATE_EVIDENCE_MISSING")
    sequence = len(state["events"]) + 1
    payload = {"system_generated": True, "stage": "close", "required_gate_ids": required, "previous_event_sha256": state["events"][-1]["event_sha256"] if state["events"] else None}
    issue = _authoring_state_problem(state) or _authoring_payload_problem("closure", payload)
    if issue:
        raise AuthoringError(issue)
    transaction = _prepare_event_transaction(state, [("closure", payload, f"event-{sequence:06d}-closure")])
    event = transaction["events"][0]
    with tempfile.TemporaryDirectory(prefix="agent-council-close-") as temporary:
        temporary_root = Path(temporary)
        shutil.copytree(root / "events", temporary_root / "events", copy_function=shutil.copy2)
        shutil.copytree(root / "evidence", temporary_root / "evidence", copy_function=shutil.copy2)
        _write_exclusive(temporary_root / "events" / f"{event['event_id']}.json", transaction["event_bytes"][0])
        document = _authoring_document(state, temporary_root, state["events"] + [event])
        evaluated = evaluate_contract_case(document)
    if evaluated.get("result") == "refused":
        raise AuthoringError(str(evaluated.get("code", "REQUIRED_GATE_EVIDENCE_MISSING")))
    _commit_prepared_transaction(root, state, transaction)
    return _outcome("accepted", "CASE_CLOSED") | {"event_id": event["event_id"], "evaluation_code": evaluated.get("code")}


def _cycle_candidate_material(state: dict[str, Any], candidate: dict[str, Any]) -> tuple[dict[str, Any], str, str, bool]:
    """Compute a candidate transition without mutating authoring state."""
    candidate_hashes = dict(candidate, policy_sha256=state["policy_bundle"]["policy_sha256"])
    candidate_sha = _candidate_digest(candidate_hashes)
    candidate_id = f"candidate-{candidate_sha[:24]}"
    current = state["engineering_candidate"]
    unchanged = candidate_id == current.get("candidate_id") and all(
        candidate_hashes.get(field) == current.get(field) for field in _CANDIDATE_HASH_FIELDS
    )
    return candidate_hashes, candidate_sha, candidate_id, unchanged


def cycle_start(root: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    issue = _candidate_input_problem(candidate)
    if issue:
        raise AuthoringError(issue)
    state = _read_local_case(root)
    candidate_hashes, candidate_sha, candidate_id, unchanged = _cycle_candidate_material(state, candidate)
    if unchanged:
        raise AuthoringError("CANDIDATE_UNCHANGED")
    next_number = len({event["cycle_id"] for event in state["events"]}) + 1
    prior = state["engineering_candidate"]["candidate_id"]
    proposed = _copy_authoring_state(state)
    proposed["cycle_id"] = f"cycle-{next_number:06d}"
    proposed["engineering_candidate"] = dict(candidate_hashes, candidate_id=candidate_id, candidate_sha256=candidate_sha)
    _invalidate_dispatch_plans(proposed)
    transition_evidence_id = f"candidate-transition-{proposed['cycle_id']}"
    transition_path = root / "evidence" / f"{transition_evidence_id}.json"
    transition_content = {"schema_version": "agent-council.candidate-transition/v2", "candidate_id": proposed["engineering_candidate"]["candidate_id"], "candidate_sha256": candidate_sha, "cycle_id": proposed["cycle_id"], "prior_candidate_id": prior}
    try:
        transition_bytes = _canonical(transition_content) + b"\n"
    except (TypeError, ValueError, RecursionError) as exc:
        raise AuthoringError("SCHEMA_VALIDATION_FAILED") from exc
    transaction = _prepare_event_transaction(proposed, [
        ("case", {"stage": "intake", "route": proposed["route"], "activation_class": proposed["activation_class"], "case_kind": proposed["case_kind"], "system_generated": True}, None),
        ("evidence", {"evidence_id": transition_evidence_id, "kind": "candidate_transition_metadata", "path": str(transition_path.relative_to(root)), "sha256": hashlib.sha256(transition_bytes).hexdigest(), "candidate_sha256": candidate_sha}, None),
        ("candidate_transition", {"prior_candidate_id": prior, "fresh_evidence_id": transition_evidence_id, "system_generated": True}, None),
    ])
    _commit_prepared_transaction(root, state, transaction, ((transition_path, transition_bytes),))
    event = transaction["events"][-1]
    return _outcome("accepted", "CYCLE_STARTED") | {"cycle_id": state["cycle_id"], "candidate_id": state["engineering_candidate"]["candidate_id"], "candidate_artifact_sha256": state["engineering_candidate"]["package_sha256"], "event_id": event["event_id"]}


def packet_request(root: Path, packet_id: str, role: str) -> dict[str, Any]:
    if not _identifier(packet_id) or not isinstance(role, str) or role not in _ROLES: raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    state = _read_local_case(root)
    event = _append_local_event(root, state, "packet", {"packet_id": packet_id, "phase": "request", "status": "accepted", "requested_role": role}, f"packet-request-{packet_id}")
    return _outcome("accepted", "PACKET_REQUESTED") | {"event_id": event["event_id"]}


def packet_result(root: Path, packet_id: str, status: str, checks: list[Any]) -> dict[str, Any]:
    if not _identifier(packet_id) or not isinstance(status, str) or not isinstance(checks, list):
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    if status not in {"completed", "passed"} or not checks or any(not isinstance(check, dict) or check.get("status") != "passed" for check in checks): raise AuthoringError("PACKET_CHECK_FAILED")
    state = _read_local_case(root)
    _require_no_pending_compound_engineering_handoff(state)
    requested = [(index, event) for index, event in enumerate(state["events"]) if event.get("record_type") == "packet" and isinstance(event.get("payload"), dict) and event["payload"].get("packet_id") == packet_id and event["payload"].get("phase") == "request"]
    results = [event for event in state["events"] if event.get("record_type") == "packet" and isinstance(event.get("payload"), dict) and event["payload"].get("packet_id") == packet_id and event["payload"].get("phase") == "result"]
    if len(requested) != 1 or results or requested[0][1]["payload"].get("status") != "accepted": raise AuthoringError("PACKET_NOT_ACTIONABLE")
    packet_problem = _packet_dispatch_problem(state["events"], packet_id, requested[0][0], len(state["events"]))
    if packet_problem:
        raise AuthoringError(packet_problem)
    event = _append_local_event(root, state, "packet", {"packet_id": packet_id, "phase": "result", "status": status, "checks": checks}, f"packet-result-{packet_id}")
    return _outcome("accepted", "PACKET_RESULT_RECORDED") | {"event_id": event["event_id"]}


def test_record(root: Path, run_id: str, evidence_id: str, status: str, test_kind: str = "normative") -> dict[str, Any]:
    if not isinstance(status, str) or not isinstance(test_kind, str) or not _identifier(run_id) or not _identifier(evidence_id): raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    if status != "passed" or test_kind not in {"normative", "fault"} or not (root / "evidence" / f"{evidence_id}.json").is_file(): raise AuthoringError("REQUIRED_GATE_EVIDENCE_MISSING")
    state = _read_local_case(root)
    _require_no_pending_compound_engineering_handoff(state)
    current = [event for event in state["events"] if event["cycle_id"] == state["cycle_id"] and event["candidate_id"] == state["engineering_candidate"]["candidate_id"]]
    evidence = _behavioral_evidence_records(root, current, state["engineering_candidate"], state["cycle_id"]).get(evidence_id)
    if evidence is None or evidence["run"]["run_id"] != run_id:
        raise AuthoringError("REQUIRED_GATE_EVIDENCE_MISSING")
    event = _append_local_event(root, state, "test", {"run_id": run_id, "test_kind": test_kind, "status": status, "evidence_id": evidence_id}, f"test-{run_id}")
    return _outcome("accepted", "TEST_RECORDED") | {"event_id": event["event_id"]}


def review_record(root: Path, review_id: str, reviewer_id: str, implementation_id: str, evidence_id: str) -> dict[str, Any]:
    if not _identifier(review_id) or not _identifier(reviewer_id) or not _identifier(implementation_id) or not _identifier(evidence_id): raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    if review_id != "independent-review" or reviewer_id == implementation_id or not (root / "evidence" / f"{evidence_id}.json").is_file(): raise AuthoringError("INDEPENDENT_REVIEW_REQUIRED")
    state = _read_local_case(root); _require_no_pending_compound_engineering_handoff(state); current = [event for event in state["events"] if event["cycle_id"] == state["cycle_id"] and event["candidate_id"] == state["engineering_candidate"]["candidate_id"] and event["record_type"] == "dispatch"]
    cycle_events = [event for event in state["events"] if event["cycle_id"] == state["cycle_id"] and event["candidate_id"] == state["engineering_candidate"]["candidate_id"]]
    if evidence_id not in _behavioral_evidence_ids(root, cycle_events, state["engineering_candidate"], state["cycle_id"]):
        raise AuthoringError("REQUIRED_GATE_EVIDENCE_MISSING")
    case_view = {"registry": state["registry"]}
    reviews = [event for event in current if event["payload"].get("platform_task_id") == reviewer_id and event["payload"].get("decision_kind") == "review" and event["payload"].get("disposition") == "approved" and _authority_dispatch_valid(event, case_view, "operational_intelligence")]
    implementations = [event for event in current if event["payload"].get("platform_task_id") == implementation_id and event["payload"].get("decision_kind") == "implementation" and event["payload"].get("disposition") == "approved" and _authority_dispatch_valid(event, case_view, "technical_tactical_intelligence")]
    if len(reviews) != 1 or len(implementations) != 1 or reviews[0]["payload"].get("platform_context_id") == implementations[0]["payload"].get("platform_context_id"):
        raise AuthoringError("INDEPENDENT_REVIEW_REQUIRED")
    event = _append_local_event(root, state, "gate", {"gate_id": review_id, "status": "passed", "reviewer_id": reviewer_id, "implementation_id": implementation_id, "evidence_id": evidence_id, "system_generated": True}, f"review-{state['cycle_id']}-{review_id}")
    return _outcome("accepted", "REVIEW_RECORDED") | {"event_id": event["event_id"]}


def gate_record(root: Path, gate_id: str, evidence_id: str, cause: str | None = None) -> dict[str, Any]:
    if not _identifier(gate_id) or not _identifier(evidence_id) or (cause is not None and not isinstance(cause, str)): raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    if not (root / "evidence" / f"{evidence_id}.json").is_file(): raise AuthoringError("REQUIRED_GATE_EVIDENCE_MISSING")
    state = _read_local_case(root); _require_no_pending_compound_engineering_handoff(state); payload = {"gate_id": gate_id, "status": "passed", "evidence_id": evidence_id, "system_generated": True}
    cycle_events = [event for event in state["events"] if event["cycle_id"] == state["cycle_id"] and event["candidate_id"] == state["engineering_candidate"]["candidate_id"]]
    if evidence_id not in _behavioral_evidence_ids(root, cycle_events, state["engineering_candidate"], state["cycle_id"]):
        raise AuthoringError("REQUIRED_GATE_EVIDENCE_MISSING")
    if cause:
        if cause not in _ESCALATION_CAUSES: raise AuthoringError("SCHEMA_VALIDATION_FAILED")
        payload["cause"] = cause
    if cause is None:
        allowed = set(_ROUTE_GATES[state["route"]]) | (set(_QUALIFICATION_GATES) if state.get("case_kind") == "council_qualification" else set())
        if gate_id not in allowed:
            raise AuthoringError("ROUTE_GATE_SET_INVALID")
        current = [event for event in state["events"] if event["cycle_id"] == state["cycle_id"] and event["candidate_id"] == state["engineering_candidate"]["candidate_id"]]
        if gate_id == "independent-review":
            raise AuthoringError("INDEPENDENT_REVIEW_REQUIRED")
        decision = {"ultimate-routing": ("ultimate_intelligence", "routing"), "ultimate-design": ("ultimate_intelligence", "design"), "ultimate-final-disposition": ("ultimate_intelligence", "final"), "operational-review": ("operational_intelligence", "review")}.get(gate_id)
        if decision and not any(event["record_type"] == "dispatch" and event["payload"].get("decision_kind") == decision[1] and event["payload"].get("disposition") == "approved" and _authority_dispatch_valid(event, {"registry": state["registry"]}, decision[0]) for event in current):
            raise AuthoringError("ULTIMATE_GATE_RECEIPT_MISSING" if decision[0] == "ultimate_intelligence" else "OPERATIONAL_REVIEW_RECEIPT_MISSING")
        if gate_id == "implementation-verification" and not any(event["record_type"] == "test" and event["payload"].get("status") == "passed" for event in current):
            raise AuthoringError("REQUIRED_GATE_EVIDENCE_MISSING")
        if gate_id == "fault-tests" and not any(event["record_type"] == "test" and event["payload"].get("status") == "passed" and event["payload"].get("test_kind") == "fault" for event in current):
            raise AuthoringError("FAULT_TEST_REQUIRED")
        if gate_id in _QUALIFICATION_GATES and not any(event["record_type"] == "dispatch" and event["payload"].get("decision_kind") == "native_forward" and event["payload"].get("qualification_run_id") == gate_id and event["payload"].get("disposition") == "approved" and _authority_dispatch_valid(event, {"registry": state["registry"]}, "ultimate_intelligence") for event in current):
            raise AuthoringError("NATIVE_FORWARD_RUNS_INSUFFICIENT")
    event = _append_local_event(root, state, "gate", payload, f"gate-{state['cycle_id']}-{gate_id}")
    return _outcome("accepted", "GATE_RECORDED") | {"event_id": event["event_id"]}


def interrupt_case(root: Path, processes: list[Any]) -> dict[str, Any]:
    issue = _security_problem(processes)
    if issue:
        raise AuthoringError(issue)
    if not isinstance(processes, list) or any(not _owned_process_valid(process) for process in processes): raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    state = _read_local_case(root)
    proposed = _copy_authoring_state(state)
    _reconcile_pending_compound_engineering_handoffs(proposed, "interruption_reconciled")
    transaction = _prepare_event_transaction(proposed, [("interruption", {"status": "interrupted", "owned_processes": processes}, f"interruption-{len(state['events']) + 1:06d}")])
    _commit_prepared_transaction(root, state, transaction)
    event = transaction["events"][0]
    return _outcome("accepted", "INTERRUPTED") | {"interruption_id": event["event_id"]}


def resume_case(root: Path, interruption_id: str) -> dict[str, Any]:
    if not _identifier(interruption_id):
        raise AuthoringError("SCHEMA_VALIDATION_FAILED")
    state = _read_local_case(root)
    matches = [event for event in state["events"] if isinstance(event, dict) and event.get("event_id") == interruption_id and event.get("record_type") == "interruption"]
    if len(matches) != 1:
        raise AuthoringError("INTERRUPTION_UNRESOLVED")
    match = matches[0]
    resumptions = [event for event in state["events"] if isinstance(event, dict) and event.get("record_type") == "resumption" and isinstance(event.get("payload"), dict) and event["payload"].get("interruption_id") == interruption_id]
    if resumptions:
        raise AuthoringError("RESUMPTION_DUPLICATE")
    candidate = state.get("engineering_candidate")
    if not isinstance(candidate, dict) or match.get("candidate_id") != candidate.get("candidate_id") or match.get("cycle_id") != state.get("cycle_id"):
        raise AuthoringError("INTERRUPTION_UNRESOLVED")
    payload = match.get("payload")
    owned_processes = payload.get("owned_processes") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or "owned_processes" not in payload or not isinstance(owned_processes, list) or any(not _owned_process_valid(item, reconciled_only=True) for item in owned_processes):
        raise AuthoringError("INTERRUPTION_UNRESOLVED")
    next_number = len({event["cycle_id"] for event in state["events"]}) + 1; prior_cycle = state["cycle_id"]
    proposed = _copy_authoring_state(state)
    proposed["cycle_id"] = f"cycle-{next_number:06d}"; _invalidate_dispatch_plans(proposed)
    transaction = _prepare_event_transaction(proposed, [
        ("case", {"stage": "intake", "route": proposed["route"], "activation_class": proposed["activation_class"], "case_kind": proposed["case_kind"], "system_generated": True}, None),
        ("resumption", {"interruption_id": interruption_id, "prior_cycle_id": prior_cycle, "prior_candidate_id": proposed["engineering_candidate"]["candidate_id"], "exact_resumption": True}, f"resumption-{interruption_id}"),
    ])
    _commit_prepared_transaction(root, state, transaction)
    event = transaction["events"][-1]
    return _outcome("resumed", "INTERRUPTION_RESUMED") | {"event_id": event["event_id"], "cycle_id": state["cycle_id"]}


def _self_test() -> int:
    return 0 if _security_problem({"items": [{"credential": "blocked"}]}) == "SECRET_REFUSED" else 1


def _candidate_json_argument(raw: str) -> dict[str, Any]:
    """Decode an explicitly supplied candidate argument without treating it as omitted."""
    try:
        candidate = _decode_json(raw)
    except (json.JSONDecodeError, _JsonDepthError, ValueError) as exc:
        raise AuthoringError("SCHEMA_VALIDATION_FAILED") from exc
    issue = _candidate_input_problem(candidate)
    if issue:
        raise AuthoringError(issue)
    assert isinstance(candidate, dict)
    return candidate


def _json_argument(raw: str) -> Any:
    """Decode an untrusted public JSON argument before a mutation lock is opened."""
    try:
        return _decode_json(raw)
    except (json.JSONDecodeError, _JsonDepthError, ValueError) as exc:
        raise AuthoringError("SCHEMA_VALIDATION_FAILED") from exc


def _confined_case_root(case_root: Path, project_root: Path | None) -> Path:
    """Resolve one case root only within an explicitly declared project root."""
    if project_root is None:
        raise AuthoringError("CASE_ROOT_BOUNDARY_REQUIRED")
    try:
        raw_boundary = project_root.expanduser()
        if not raw_boundary.is_absolute():
            raw_boundary = Path.cwd() / raw_boundary
        boundary = raw_boundary.resolve(strict=True)
        if not boundary.is_dir():
            raise OSError("project root is not a directory")
        raw_case_root = case_root.expanduser()
        if not raw_case_root.is_absolute():
            raw_case_root = Path.cwd() / raw_case_root
        resolved_case_root = raw_case_root.resolve(strict=False)
        resolved_case_root.relative_to(boundary)
    except (OSError, RuntimeError, ValueError) as exc:
        raise AuthoringError("CASE_ROOT_OUTSIDE_PROJECT_BOUNDARY") from exc
    # Reject symlinks introduced below the caller-declared root. Do not reject
    # operating-system aliases above that root, such as macOS /var -> /private/var.
    try:
        relative_raw_path = raw_case_root.relative_to(raw_boundary)
    except ValueError:
        relative_raw_path = None
    if relative_raw_path is not None:
        cursor = raw_boundary
        for part in relative_raw_path.parts:
            cursor /= part
            if cursor.exists() and cursor.is_symlink():
                raise AuthoringError("CASE_ROOT_SYMLINK_REFUSED")
    return resolved_case_root


def _safe_case_tree(root: Path) -> None:
    """Refuse a mutable case containing a symlink before acquiring a write lock.

    The project boundary prevents accidental writes to a different project. This
    check prevents a previously created child path, such as `events` or
    `evidence`, from redirecting a later write outside that boundary.
    """
    try:
        if not root.is_dir() or root.is_symlink():
            raise AuthoringError("CASE_PATH_SYMLINK_REFUSED")
        for path in root.rglob("*"):
            if path.is_symlink():
                raise AuthoringError("CASE_PATH_SYMLINK_REFUSED")
    except AuthoringError:
        raise
    except OSError as exc:
        raise AuthoringError("CASE_NOT_FOUND") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    evaluate = commands.add_parser("evaluate", help="evaluate one case JSON document")
    evaluate.add_argument("case_json", type=Path)
    commands.add_parser("self-test", help="run standard-library smoke checks")
    init = commands.add_parser("init-case", help="create a pinned local authoring case")
    init.add_argument("--case-root", required=True, type=Path); init.add_argument("--project-root", required=True, type=Path); init.add_argument("--case-id", required=True); init.add_argument("--route", required=True); init.add_argument("--activation-class"); init.add_argument("--case-kind", default="operational_change"); init.add_argument("--candidate-json")
    bundle = commands.add_parser("build-bundle", help="build an executing bundle from pinned artifacts")
    bundle.add_argument("--case-root", required=True, type=Path); bundle.add_argument("--project-root", required=True, type=Path)
    append = commands.add_parser("append", help="append a non-protected local event")
    append.add_argument("--case-root", required=True, type=Path); append.add_argument("--project-root", required=True, type=Path); append.add_argument("--record-type", required=True); append.add_argument("--payload-json", required=True)
    evidence = commands.add_parser("evidence-add", help="add immutable candidate-bound behavioral evidence")
    evidence.add_argument("--case-root", required=True, type=Path); evidence.add_argument("--project-root", required=True, type=Path); evidence.add_argument("--evidence-id", required=True); evidence.add_argument("--evidence-kind", required=True, choices=sorted(_BEHAVIORAL_EVIDENCE_KINDS)); evidence.add_argument("--content-json", required=True)
    capability = commands.add_parser("capability-capture", help="record a current adapter capability observation")
    capability.add_argument("--case-root", required=True, type=Path); capability.add_argument("--project-root", required=True, type=Path); capability.add_argument("--provider", required=True); capability.add_argument("--model-id", required=True); capability.add_argument("--efforts-json", required=True); capability.add_argument("--context-id", required=True); capability.add_argument("--observed-at")
    plan = commands.add_parser("dispatch-plan", help="issue one single-use adapter dispatch plan")
    plan.add_argument("--case-root", required=True, type=Path); plan.add_argument("--project-root", required=True, type=Path); plan.add_argument("--provider", required=True); plan.add_argument("--role", required=True); plan.add_argument("--context-id", required=True); plan.add_argument("--effort", default="high"); plan.add_argument("--decision-kind"); plan.add_argument("--qualification-run-id"); plan.add_argument("--work-method", default="native", choices=("native", "compound_engineering"))
    capture = commands.add_parser("dispatch-capture", help="capture exact native dispatch return fields")
    capture.add_argument("--case-root", required=True, type=Path); capture.add_argument("--project-root", required=True, type=Path); capture.add_argument("--provider", required=True); capture.add_argument("--plan-nonce"); capture.add_argument("--task-id", required=True); capture.add_argument("--model-id", required=True); capture.add_argument("--effort", required=True); capture.add_argument("--context-id", required=True); capture.add_argument("--output-ref", required=True); capture.add_argument("--decision-kind", default="implementation"); capture.add_argument("--disposition", default="approved"); capture.add_argument("--qualification-run-id")
    close = commands.add_parser("close-case", help="atomically close only after passing gates and tests")
    close.add_argument("--case-root", required=True, type=Path); close.add_argument("--project-root", required=True, type=Path)
    cycle = commands.add_parser("cycle-start", help="start a changed engineering candidate cycle")
    cycle.add_argument("--case-root", required=True, type=Path); cycle.add_argument("--project-root", required=True, type=Path); cycle.add_argument("--candidate-json", required=True)
    request = commands.add_parser("packet-request", help="record an accepted bounded packet")
    request.add_argument("--case-root", required=True, type=Path); request.add_argument("--project-root", required=True, type=Path); request.add_argument("--packet-id", required=True); request.add_argument("--role", required=True)
    packet_result_parser = commands.add_parser("packet-result", help="record a packet's actual checks")
    packet_result_parser.add_argument("--case-root", required=True, type=Path); packet_result_parser.add_argument("--project-root", required=True, type=Path); packet_result_parser.add_argument("--packet-id", required=True); packet_result_parser.add_argument("--status", required=True); packet_result_parser.add_argument("--checks-json", required=True)
    test_record_parser = commands.add_parser("test-record", help="record candidate-bound passing test evidence")
    test_record_parser.add_argument("--case-root", required=True, type=Path); test_record_parser.add_argument("--project-root", required=True, type=Path); test_record_parser.add_argument("--run-id", required=True); test_record_parser.add_argument("--evidence-id", required=True); test_record_parser.add_argument("--status", default="passed"); test_record_parser.add_argument("--test-kind", default="normative")
    review = commands.add_parser("review-record", help="record independent review")
    review.add_argument("--case-root", required=True, type=Path); review.add_argument("--project-root", required=True, type=Path); review.add_argument("--review-id", required=True); review.add_argument("--reviewer-id", required=True); review.add_argument("--implementation-id", required=True); review.add_argument("--evidence-id", required=True)
    gate = commands.add_parser("gate", help="record a system-generated passing gate")
    gate.add_argument("--case-root", required=True, type=Path); gate.add_argument("--project-root", required=True, type=Path); gate.add_argument("--gate-id", required=True); gate.add_argument("--evidence-id", required=True); gate.add_argument("--cause")
    interrupt = commands.add_parser("interrupt", help="record an interruption and owned process reconciliation")
    interrupt.add_argument("--case-root", required=True, type=Path); interrupt.add_argument("--project-root", required=True, type=Path); interrupt.add_argument("--processes-json", required=True)
    resume = commands.add_parser("resume", help="exactly resume a reconciled interruption in a new cycle")
    resume.add_argument("--case-root", required=True, type=Path); resume.add_argument("--project-root", required=True, type=Path); resume.add_argument("--interruption-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "self-test":
        return _self_test()
    try:
        if hasattr(args, "case_root"):
            args.case_root = _confined_case_root(args.case_root, args.project_root)
        parsed: dict[str, Any] = {}
        if args.command == "init-case" and args.candidate_json is not None:
            parsed["candidate"] = _candidate_json_argument(args.candidate_json)
        elif args.command == "cycle-start":
            parsed["candidate"] = _candidate_json_argument(args.candidate_json)
            state = _read_local_case(args.case_root)
            if _cycle_candidate_material(state, parsed["candidate"])[3]:
                raise AuthoringError("CANDIDATE_UNCHANGED")
        elif args.command == "append":
            parsed["payload"] = _json_argument(args.payload_json)
        elif args.command == "evidence-add":
            parsed["content"] = _json_argument(args.content_json)
        elif args.command == "capability-capture":
            parsed["efforts"] = _json_argument(args.efforts_json)
        elif args.command == "packet-result":
            parsed["checks"] = _json_argument(args.checks_json)
        elif args.command == "interrupt":
            parsed["processes"] = _json_argument(args.processes_json)
        if hasattr(args, "case_root") and args.command != "init-case":
            _safe_case_tree(args.case_root)
        lock = _authoring_lock(args.case_root) if hasattr(args, "case_root") and args.command != "init-case" else nullcontext()
        with lock:
            if hasattr(args, "case_root") and args.command != "init-case":
                _safe_case_tree(args.case_root)
                _assert_pinned_project_root(args.case_root, args.project_root)
            if args.command == "init-case": result = init_case(args.case_root, args.project_root, args.case_id, args.route, candidate=parsed.get("candidate"), activation_class=args.activation_class, case_kind=args.case_kind)
            elif args.command == "build-bundle": result = build_bundle(args.case_root)
            elif args.command == "append":
                if args.record_type in _PROTECTED: raise AuthoringError("PROTECTED_RECORD_REFUSED")
                result = _outcome("accepted", "EVENT_APPENDED") | {"event_id": _append_local_event(args.case_root, _read_local_case(args.case_root), args.record_type, parsed["payload"])["event_id"]}
            elif args.command == "evidence-add": result = evidence_add(args.case_root, args.evidence_id, args.evidence_kind, parsed["content"])
            elif args.command == "capability-capture": result = capture_capability(args.case_root, args.provider, args.model_id, parsed["efforts"], args.context_id, args.observed_at)
            elif args.command == "dispatch-plan": result = dispatch_plan(args.case_root, args.provider, args.role, args.context_id, args.effort, args.decision_kind, args.qualification_run_id, args.work_method)
            elif args.command == "dispatch-capture":
                if not args.plan_nonce: raise AuthoringError("DISPATCH_PLAN_REQUIRED")
                result = dispatch_capture(args.case_root, args.provider, args.plan_nonce, args.task_id, args.model_id, args.effort, args.context_id, args.output_ref, args.decision_kind, args.disposition, args.qualification_run_id)
            elif args.command == "close-case": result = close_local_case(args.case_root)
            elif args.command == "cycle-start": result = cycle_start(args.case_root, parsed["candidate"])
            elif args.command == "packet-request": result = packet_request(args.case_root, args.packet_id, args.role)
            elif args.command == "packet-result": result = packet_result(args.case_root, args.packet_id, args.status, parsed["checks"])
            elif args.command == "test-record": result = test_record(args.case_root, args.run_id, args.evidence_id, args.status, args.test_kind)
            elif args.command == "review-record": result = review_record(args.case_root, args.review_id, args.reviewer_id, args.implementation_id, args.evidence_id)
            elif args.command == "gate": result = gate_record(args.case_root, args.gate_id, args.evidence_id, args.cause)
            elif args.command == "interrupt": result = interrupt_case(args.case_root, parsed["processes"])
            elif args.command == "resume": result = resume_case(args.case_root, args.interruption_id)
            else: result = None
            if result is not None:
                print(json.dumps(result, sort_keys=True)); return 0
    except (AuthoringError, json.JSONDecodeError, TypeError, ValueError, KeyError, AttributeError, IndexError, OSError, RuntimeError, RecursionError) as exc:
        code = exc.code if isinstance(exc, AuthoringError) else "SCHEMA_VALIDATION_FAILED"
        print(json.dumps(_refuse(code), sort_keys=True)); return 1
    try:
        document = _decode_json(args.case_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, _JsonDepthError, ValueError, RecursionError):
        print(json.dumps(_refuse("SCHEMA_VALIDATION_FAILED"), sort_keys=True))
        return 2
    if not isinstance(document, dict):
        print(json.dumps(_refuse("SCHEMA_VALIDATION_FAILED"), sort_keys=True))
        return 1
    if document.get("authoring_schema_version") == "agent-council.authoring/v2":
        try:
            document = _read_local_case(args.case_json.parent)
            result = evaluate_contract_case(_authoring_document(document, args.case_json.parent))
        except (AuthoringError, json.JSONDecodeError, TypeError, ValueError, KeyError, AttributeError, IndexError, OSError, RuntimeError, RecursionError) as exc:
            result = _refuse(exc.code if isinstance(exc, AuthoringError) else "SCHEMA_VALIDATION_FAILED")
    else:
        result = evaluate_contract_case(document)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] != "refused" else 1


if __name__ == "__main__":
    sys.exit(main())
