#!/usr/bin/env python3
"""Fixture-driven v2 Council contract tests, red until a runtime exists."""
from __future__ import annotations

import ast
import argparse
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import runpy
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[4]
RUNTIME = Path(__file__).with_name("Invoke-AgentCouncil.py")
SCHEMAS = ("agent-council-record.schema.v2.yaml", "agent-model-registry.schema.v2.yaml", "agent-model-registry.schema.v3.yaml", "provider-capability-receipt.schema.v2.yaml", "provider-dispatch-receipt.schema.v2.yaml", "agent-council-executing-bundle.schema.v2.yaml")
ROLES = ("ultimate_intelligence", "operational_intelligence", "technical_tactical_intelligence", "worker_intelligence")
ROUTE_GATES = {
    "R1": ("ultimate-routing", "implementation-verification", "operational-review", "ultimate-final-disposition"),
    "R2": ("ultimate-routing", "ultimate-design", "implementation-verification", "independent-review", "ultimate-final-disposition"),
    "R3": ("ultimate-routing", "ultimate-design", "implementation-verification", "fault-tests", "independent-review", "ultimate-final-disposition"),
}
QUALIFICATION_GATES = ("native-forward-run-1", "native-forward-run-2")
CASE_SPECS = {
    "later_operational_review_hold": ("routes", "refused", "OPERATIONAL_REVIEW_NOT_APPROVED"), "later_implementation_hold": ("routes", "refused", "IMPLEMENTATION_NOT_APPROVED"), "later_invalid_final_record": ("routes", "refused", "AUTHORITY_DISPATCH_INVALID"),
    "later_native_run_hold": ("routes", "refused", "NATIVE_FORWARD_RUN_NOT_APPROVED"),
    "capability_metadata_as_behavioral_evidence": ("routes", "refused", "REQUIRED_GATE_EVIDENCE_MISSING"), "wrapped_capability_metadata_as_behavioral_evidence": ("routes", "refused", "REQUIRED_GATE_EVIDENCE_MISSING"), "candidate_transition_metadata_as_behavioral_evidence": ("routes", "refused", "REQUIRED_GATE_EVIDENCE_MISSING"), "behavioral_evidence_missing_type": ("routes", "refused", "REQUIRED_GATE_EVIDENCE_MISSING"), "behavioral_evidence_candidate_mismatch": ("routes", "refused", "REQUIRED_GATE_EVIDENCE_MISSING"), "behavioral_evidence_run_mismatch": ("routes", "refused", "REQUIRED_GATE_EVIDENCE_MISSING"), "behavioral_evidence_empty_assertions": ("routes", "refused", "REQUIRED_GATE_EVIDENCE_MISSING"), "behavioral_evidence_result_not_passed": ("routes", "refused", "REQUIRED_GATE_EVIDENCE_MISSING"),
    "review_before_implementation": ("routes", "refused", "REVIEW_ORDER_INVALID"), "qualification_evidence_candidate_payload_tamper": ("routes", "refused", "CANDIDATE_EVIDENCE_MISMATCH"), "qualification_evidence_cycle_payload_tamper": ("routes", "refused", "CANDIDATE_EVIDENCE_MISMATCH"), "qualification_non_normative_failed_gate": ("routes", "refused", "UNRESOLVED_GATE_FAILURE"),
    "cross_cycle_unreconciled": ("lifecycle", "refused", "INTERRUPTION_UNRESOLVED"), "cross_cycle_exact_resumption": ("lifecycle", "resumed", "INTERRUPTION_RESUMED"), "nonexistent_supersession": ("lifecycle", "refused", "SUPERSESSION_TARGET_MISSING"), "valid_supersession_retires_failure": ("lifecycle", "accepted", "SUPERSESSION_APPLIED"), "changed_candidate_new_cycle": ("lifecycle", "accepted", "CANDIDATE_TRANSITION_ACCEPTED"), "candidate_bytes_changed_same_id": ("lifecycle", "refused", "CANDIDATE_IDENTITY_MISMATCH"), "prior_candidate_evidence_reuse": ("lifecycle", "refused", "CANDIDATE_EVIDENCE_MISMATCH"), "orphan_resumption": ("lifecycle", "refused", "RESUMPTION_ORPHANED"), "duplicate_resumption": ("lifecycle", "refused", "RESUMPTION_DUPLICATE"), "same_cycle_resumption": ("lifecycle", "refused", "RESUMPTION_SAME_CYCLE"),
    "required_gate_without_test": ("stages", "refused", "REQUIRED_GATE_EVIDENCE_MISSING"), "failed_packet_check": ("stages", "refused", "PACKET_CHECK_FAILED"), "blocked_packet_request": ("stages", "refused", "PACKET_NOT_ACTIONABLE"), "packet_result_conflict": ("stages", "refused", "PACKET_RESULT_CONFLICT"), "stage_ordering": ("stages", "refused", "STAGE_ORDER_INVALID"), "decide_without_implementation": ("stages", "accepted", "STAGE_DECIDE_ACCEPTED"), "decide_cannot_bypass_close": ("stages", "refused", "ROUTE_GATE_SET_INVALID"), "closure_self_declared_gate": ("stages", "refused", "REQUIRED_GATE_EVIDENCE_MISSING"), "closure_omits_normative_gate": ("stages", "refused", "ROUTE_GATE_SET_INVALID"), "prior_cycle_gate_reuse": ("stages", "refused", "REQUIRED_GATE_EVIDENCE_MISSING"), "independent_review_same_implementer": ("stages", "refused", "INDEPENDENT_REVIEW_REQUIRED"),
    "r3_luna_implementation": ("routes", "refused", "IMPLEMENTATION_TIER_INVALID"), "all_dispatches_low_effort": ("routes", "refused", "EFFORT_POLICY_INVALID"), "evidenced_higher_effort": ("routes", "accepted", "EFFORT_ESCALATION_ACCEPTED"), "route_floor_violation": ("routes", "refused", "ROUTE_FLOOR_VIOLATION"), "missing_ultimate_design": ("routes", "refused", "ULTIMATE_GATE_RECEIPT_MISSING"), "ultimate_wrong_binding": ("routes", "refused", "AUTHORITY_DISPATCH_INVALID"), "final_disposition_hold": ("routes", "refused", "ULTIMATE_GATE_NOT_APPROVED"), "later_final_hold": ("routes", "refused", "ULTIMATE_GATE_NOT_APPROVED"), "final_before_review": ("routes", "refused", "FINAL_DISPOSITION_ORDER_INVALID"), "design_after_final": ("routes", "refused", "FINAL_DISPOSITION_ORDER_INVALID"), "missing_operational_review": ("routes", "refused", "INDEPENDENT_REVIEW_REQUIRED"), "r1_review_same_implementer": ("routes", "refused", "INDEPENDENT_REVIEW_REQUIRED"), "active_failed_test": ("routes", "refused", "UNRESOLVED_TEST_FAILURE"), "r3_missing_fault_test": ("routes", "refused", "FAULT_TEST_REQUIRED"), "qualification_activation_operational_kind": ("routes", "refused", "ROUTE_CLASSIFICATION_MISSING"), "qualification_omits_native_gates": ("routes", "refused", "NATIVE_FORWARD_RUNS_INSUFFICIENT"), "qualification_one_native_run": ("routes", "refused", "NATIVE_FORWARD_RUNS_INSUFFICIENT"), "qualification_same_context": ("routes", "refused", "NATIVE_FORWARD_RUNS_NOT_FRESH"), "qualification_unrelated_diversity": ("routes", "refused", "NATIVE_FORWARD_RUNS_NOT_FRESH"), "qualification_blank_identity": ("routes", "refused", "NATIVE_FORWARD_RUNS_INSUFFICIENT"), "qualification_native_gate_status_missing": ("routes", "refused", "REQUIRED_GATE_EVIDENCE_MISSING"), "qualification_normative_route_gate_status_missing": ("routes", "refused", "REQUIRED_GATE_EVIDENCE_MISSING"), "qualification_final_before_native": ("routes", "refused", "FINAL_DISPOSITION_ORDER_INVALID"), "qualification_two_native_runs": ("routes", "accepted", "CASE_ACCEPTED"),
    "high_selected_low_attested": ("provider", "refused", "EFFECTIVE_EFFORT_MISMATCH"), "stale_capability": ("provider", "refused", "CAPABILITY_STALE"), "invalid_capability_context": ("provider", "refused", "SCHEMA_VALIDATION_FAILED"), "resolver_default_effort": ("provider", "resolved", "DEFAULT_EFFORT_HIGH"), "provider_model_or_effort_mismatch": ("provider", "refused", "PROVIDER_RECEIPT_MISMATCH"), "caller_authored_native_receipt": ("provider", "refused", "PROVIDER_RECEIPT_UNVERIFIED"), "provider_fail_closed_authority": ("provider", "refused", "AUTHORITY_DISPATCH_INVALID"), "registry_content_tamper": ("provider", "refused", "SCHEMA_VALIDATION_FAILED"),
    "pinned_schema_after_package_rotation": ("authoring", "accepted", "PINNED_SCHEMA_USED"), "orphan_immutable_event": ("authoring", "refused", "SCHEMA_VALIDATION_FAILED"), "missing_evidence_file": ("authoring", "refused", "EVIDENCE_INTEGRITY_FAILED"), "password_field_in_evidence": ("security", "refused", "SECRET_REFUSED"), "utf8_control_byte_evidence": ("security", "refused", "CONTROL_CHARACTER_REFUSED"),
    "authority_dispatch_output_ref_missing": ("security", "refused", "SCHEMA_VALIDATION_FAILED"), "authority_dispatch_output_ref_null": ("security", "refused", "SCHEMA_VALIDATION_FAILED"), "authority_dispatch_output_ref_object": ("security", "refused", "SCHEMA_VALIDATION_FAILED"), "authority_dispatch_output_ref_control": ("security", "refused", "CONTROL_CHARACTER_REFUSED"), "authority_dispatch_capability_models_null": ("security", "refused", "AUTHORITY_DISPATCH_INVALID"), "object_stage": ("security", "refused", "SCHEMA_VALIDATION_FAILED"), "object_decision_kind": ("security", "refused", "PACKET_NOT_ACTIONABLE"), "object_evidence_id": ("security", "refused", "CANDIDATE_EVIDENCE_MISMATCH"), "object_provider": ("security", "refused", "SCHEMA_VALIDATION_FAILED"), "packet_result_before_request": ("security", "refused", "PACKET_NOT_ACTIONABLE"), "packet_result_before_implementation": ("security", "refused", "PACKET_NOT_ACTIONABLE"), "packet_result_pair_mismatch": ("security", "refused", "PACKET_RESULT_CONFLICT"),
}
EXPECTED_EFFORT = {"evidenced_higher_effort": "ultra", "resolver_default_effort": "high"}
EVALUATOR_ASSURANCE_CASES = frozenset({"authority_dispatch_output_ref_missing", "authority_dispatch_output_ref_null", "authority_dispatch_output_ref_object", "authority_dispatch_output_ref_control", "authority_dispatch_capability_models_null", "object_stage", "object_decision_kind", "object_evidence_id", "object_provider", "packet_result_before_request", "packet_result_before_implementation", "packet_result_pair_mismatch"})
# Each group below executes a distinct suite.  These are local structural
# contracts, not evidence that a native provider adapter has been qualified.
GROUPS = ("schema", "registry-schema", "lifecycle", "stages", "routes", "provider", "authoring", "security", "dispatch-contracts")
FIXTURE_NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def token(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def behavioral_evidence(candidate: dict[str, Any], run_id: str = "test-normative", cycle_id: str = "cycle-current", evidence_kind: str = "behavioral_test") -> dict[str, Any]:
    return {
        "schema_version": "agent-council.behavioral-evidence/v2",
        "evidence_kind": evidence_kind,
        "candidate_id": candidate["candidate_id"],
        "candidate_sha256": candidate["candidate_sha256"],
        "cycle_id": cycle_id,
        "run": {"run_id": run_id, "run_kind": "contract"},
        "assertion": {"assertion_id": f"assertion-{run_id}", "subject": "candidate behavior", "expected": "passes"},
        "result": {"result_id": f"result-{run_id}", "status": "passed"},
    }


def reseal_dispatch_payload(payload: dict[str, Any]) -> None:
    capability = {"receipt_type": "provider_capability", "receipt_id": payload["capability_receipt_id"], "provider": payload["provider"], "observed_at": payload["capability_observed_at"], "context_id": payload["capability_context_id"], "models": payload["capability_models"], "efforts": payload["capability_efforts"]}
    payload["capability_receipt_sha256"] = digest(capability)
    receipt = {"receipt_type": "provider_dispatch", "receipt_id": payload["dispatch_receipt_id"], "dispatch_id": payload["platform_task_id"], "provider": payload["provider"], "model_id": payload["model_id"], "selected_effort": payload["selected_effort"], "attested_effort": payload["attested_effort"], "context_id": payload["platform_context_id"], "system_generated": True}
    payload["dispatch_receipt_sha256"] = digest(receipt)


def event(case_id: str, cycle_id: str, candidate_id: str, event_id: str, record_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = {"record_type": record_type, "event_id": event_id, "recorded_at": FIXTURE_NOW, "identity": {"case_id": case_id, "policy_bundle_sha256": token(case_id + "-policy"), "registry_version": "v2", "registry_sha256": registry(case_id)["registry_sha256"]}, "candidate_id": candidate_id, "cycle_id": cycle_id, "payload": payload}
    record["event_sha256"] = digest(record)
    return record


def protected_dispatch(case_id: str, cycle_id: str, candidate_id: str, event_id: str, role: str, decision_kind: str, context_id: str, task_id: str, disposition: str = "approved", qualification_run_id: str | None = None) -> dict[str, Any]:
    selected_binding = binding(case_id, role)
    binding_id = selected_binding["binding_id"]
    capability_receipt = {"receipt_type": "provider_capability", "receipt_id": f"capability-{context_id}", "provider": "codex", "observed_at": FIXTURE_NOW, "context_id": context_id, "models": [selected_binding["model_id"]], "efforts": ["high"]}
    capability_receipt["receipt_sha256"] = digest(capability_receipt)
    dispatch_receipt = {"receipt_type": "provider_dispatch", "receipt_id": f"dispatch-{event_id}", "dispatch_id": task_id, "provider": "codex", "model_id": selected_binding["model_id"], "selected_effort": "high", "attested_effort": "high", "context_id": context_id, "system_generated": True}
    dispatch_receipt["receipt_sha256"] = digest(dispatch_receipt)
    payload = {
        "system_generated": True,
        "dispatch_receipt_id": dispatch_receipt["receipt_id"],
        "dispatch_receipt_sha256": dispatch_receipt["receipt_sha256"],
        "requested_role": role,
        "decision_kind": decision_kind,
        "disposition": disposition,
        "receipt_provenance": "platform_returned",
        "provider": "codex",
        "binding_id": binding_id,
        "binding_sha256": selected_binding["binding_sha256"],
        "capability_receipt_id": capability_receipt["receipt_id"],
        "capability_receipt_sha256": capability_receipt["receipt_sha256"],
        "capability_context_id": context_id,
        "capability_models": [selected_binding["model_id"]],
        "capability_efforts": ["high"],
        "capability_observed_at": FIXTURE_NOW,
        "platform_task_id": task_id,
        "platform_context_id": context_id,
        "platform_output_ref": f"evidence/{task_id}.json",
        "model_id": selected_binding["model_id"],
        "selected_effort": "high",
        "attested_effort": "high",
    }
    if qualification_run_id:
        payload["qualification_run_id"] = qualification_run_id
    return event(case_id, cycle_id, candidate_id, event_id, "dispatch", payload)


def binding(case_id: str, role: str) -> dict[str, Any]:
    value = {"binding_id": f"binding-{role}", "provider": "codex", "model_id": f"qualified-{role}-model", "tier": role, "status": "qualified"}
    value["binding_sha256"] = digest(value)
    return value


def registry(case_id: str) -> dict[str, Any]:
    bindings = [binding(case_id, role) for role in ROLES]
    value = {"schema_version": "agent-council.model-registry/v2", "registry_version": "v2", "reasoning": {"default_effort": "high"}, "provider_states": {"codex": {"council_status": "qualified"}, "claude_code": {"council_status": "fail_closed_until_qualified"}}, "bindings": bindings}
    value["registry_sha256"] = digest(value)
    return value


def base_case(case_name: str, root: Path) -> dict[str, Any]:
    case_id, cycle_id = f"case-{case_name}", "cycle-current"
    candidate_hashes = {"source_sha256": token(case_id + "source"), "package_sha256": token(case_id + "package"), "dependency_lock_sha256": token(case_id + "lock"), "harness_sha256": token(case_id + "harness"), "policy_sha256": token(case_id + "-policy")}
    candidate_sha256 = digest(candidate_hashes)
    candidate_id = f"candidate-{candidate_sha256[:24]}"
    model_id = "qualified-technical_tactical_intelligence-model"
    technical_binding = binding(case_id, "technical_tactical_intelligence")
    capability = {"receipt_type": "provider_capability", "receipt_id": "capability-current", "provider": "codex", "observed_at": FIXTURE_NOW, "context_id": "context-current", "models": [model_id], "efforts": ["high", "ultra"]}
    capability["receipt_sha256"] = digest(capability)
    dispatch = {"receipt_type": "provider_dispatch", "receipt_id": "dispatch-current", "dispatch_id": "task-technical", "provider": "codex", "model_id": model_id, "selected_effort": "high", "attested_effort": "high", "context_id": "context-current", "system_generated": True}
    dispatch["receipt_sha256"] = digest(dispatch)
    route = "R2"
    events = [
        event(case_id, cycle_id, candidate_id, "event-intake", "case", {"stage": "intake", "route": route, "activation_class": "unqualified_composition", "case_kind": "operational_change", "system_generated": True}),
        protected_dispatch(case_id, cycle_id, candidate_id, "event-ultimate-routing", "ultimate_intelligence", "routing", "context-ultimate-routing", "task-ultimate-routing"),
        protected_dispatch(case_id, cycle_id, candidate_id, "event-ultimate-design", "ultimate_intelligence", "design", "context-ultimate-design", "task-ultimate-design"),
        event(case_id, cycle_id, candidate_id, "event-packet-request", "packet", {"packet_id": "packet-implementation", "phase": "request", "status": "accepted", "requested_role": "technical_tactical_intelligence"}),
        event(case_id, cycle_id, candidate_id, "event-dispatch", "dispatch", {"dispatch_receipt_id": dispatch["receipt_id"], "requested_role": "technical_tactical_intelligence", "decision_kind": "implementation", "disposition": "approved", "receipt_provenance": "platform_returned", "provider": "codex", "binding_id": technical_binding["binding_id"], "binding_sha256": technical_binding["binding_sha256"], "capability_receipt_id": capability["receipt_id"], "capability_receipt_sha256": capability["receipt_sha256"], "capability_context_id": capability["context_id"], "capability_models": capability["models"], "capability_efforts": capability["efforts"], "capability_observed_at": capability["observed_at"], "platform_task_id": "task-technical", "platform_context_id": "context-current", "platform_output_ref": "evidence/task-technical.json", "model_id": model_id, "selected_effort": "high", "attested_effort": "high", "system_generated": True}),
        event(case_id, cycle_id, candidate_id, "event-packet-result", "packet", {"packet_id": "packet-implementation", "phase": "result", "status": "completed", "checks": [{"gate_id": "gate-packet", "status": "passed"}]}),
        event(case_id, cycle_id, candidate_id, "event-evidence", "evidence", {"evidence_id": "evidence-current", "kind": "behavioral_test", "path": "evidence/test-output.json", "sha256": token(case_id + "evidence"), "candidate_id": candidate_id, "candidate_sha256": candidate_sha256, "cycle_id": cycle_id}),
        event(case_id, cycle_id, candidate_id, "event-test", "test", {"run_id": "test-normative", "status": "passed", "evidence_id": "evidence-current"}),
        protected_dispatch(case_id, cycle_id, candidate_id, "event-operational-review", "operational_intelligence", "review", "context-operational-review", "task-operational-review"),
    ]
    for gate_id in ROUTE_GATES[route]:
        payload = {"gate_id": gate_id, "status": "passed", "evidence_id": "evidence-current", "system_generated": True}
        if gate_id == "independent-review": payload.update({"reviewer_id": "task-operational-review", "implementation_id": "task-technical"})
        if gate_id == "ultimate-final-disposition": events.append(protected_dispatch(case_id, cycle_id, candidate_id, "event-ultimate-final", "ultimate_intelligence", "final", "context-ultimate-final", "task-ultimate-final"))
        events.append(event(case_id, cycle_id, candidate_id, f"event-gate-{gate_id}", "gate", payload))
    events.append(event(case_id, cycle_id, candidate_id, "event-closure", "closure", {"stage": "close", "required_gate_ids": list(ROUTE_GATES[route]), "system_generated": True}))
    registry_value = registry(case_id)
    document = {"schema_version": "agent-council.case/v2", "case_id": case_id, "case_root": str(root), "cycle_id": cycle_id, "route": route, "identity": {"case_id": case_id, "policy_bundle_sha256": token(case_id + "-policy"), "registry_version": "v2", "registry_sha256": registry_value["registry_sha256"]}, "policy_bundle": {"policy_bundle_id": "policy-v2", "policy_sha256": token(case_id + "-policy")}, "engineering_candidate": dict(candidate_hashes, candidate_id=candidate_id, candidate_sha256=candidate_sha256), "registry": registry_value, "provider_capability_receipt": capability, "provider_dispatch_receipt": dispatch, "events": events}
    document["evidence_content"] = behavioral_evidence(document["engineering_candidate"], cycle_id=cycle_id)

    def configure_qualification(native_runs: int, same_context: bool = False) -> None:
        document["route"] = "R3"
        document["events"][0]["payload"].update({"route": "R3", "activation_class": "council_qualification", "case_kind": "council_qualification"})
        document["events"] = [item for item in document["events"] if item["record_type"] not in {"gate", "closure"} and item["event_id"] != "event-ultimate-final"]
        review = next(item for item in document["events"] if item["payload"].get("decision_kind") == "review")
        document["events"].remove(review)
        document["events"].append(event(case_id, cycle_id, candidate_id, "event-evidence-fault", "evidence", {"evidence_id": "evidence-fault", "kind": "behavioral_test", "path": "evidence/fault-output.json", "sha256": token(case_id + "fault-evidence"), "candidate_id": candidate_id, "candidate_sha256": candidate_sha256, "cycle_id": cycle_id}))
        document["events"].append(event(case_id, cycle_id, candidate_id, "event-test-fault", "test", {"run_id": "test-fault", "test_kind": "fault", "status": "passed", "evidence_id": "evidence-fault"}))
        document["fault_evidence_content"] = behavioral_evidence(document["engineering_candidate"], "test-fault", cycle_id)
        for index in range(native_runs):
            run_id = QUALIFICATION_GATES[index]
            context_id = "context-native-shared" if same_context else f"context-native-{index + 1}"
            document["events"].append(protected_dispatch(case_id, cycle_id, candidate_id, f"event-{run_id}", "ultimate_intelligence", "native_forward", context_id, f"task-native-{index + 1}", qualification_run_id=run_id))
        document["events"].append(review)
        required = list(ROUTE_GATES["R3"] + QUALIFICATION_GATES)
        for gate_id in required:
            payload = {"gate_id": gate_id, "status": "passed", "evidence_id": "evidence-current", "system_generated": True}
            if gate_id == "independent-review": payload.update({"reviewer_id": "task-operational-review", "implementation_id": "task-technical"})
            if gate_id == "ultimate-final-disposition": document["events"].append(protected_dispatch(case_id, cycle_id, candidate_id, "event-ultimate-final", "ultimate_intelligence", "final", "context-ultimate-final", "task-ultimate-final"))
            document["events"].append(event(case_id, cycle_id, candidate_id, f"event-gate-{gate_id}", "gate", payload))
        document["events"].append(event(case_id, cycle_id, candidate_id, "event-closure", "closure", {"stage": "close", "required_gate_ids": required, "system_generated": True}))

    if case_name == "resolver_default_effort":
        document["events"] = document["events"][:5]
    if case_name == "decide_without_implementation":
        document["events"] = document["events"][:5] + [event(case_id, cycle_id, candidate_id, "event-decide", "gate", {"stage": "decide", "status": "passed", "system_generated": True})]
    if case_name == "decide_cannot_bypass_close":
        document["events"].insert(6, event(case_id, cycle_id, candidate_id, "event-decide", "gate", {"stage": "decide", "status": "passed", "system_generated": True}))
        document["events"][-1]["payload"]["required_gate_ids"] = list(ROUTE_GATES["R2"][:-1])
    if case_name == "required_gate_without_test": document["events"][-2]["payload"]["gate_id"] = "gate-unrelated"
    if case_name == "failed_packet_check": next(item for item in document["events"] if item["record_type"] == "packet" and item["payload"].get("phase") == "result")["payload"]["checks"][0]["status"] = "failed"
    if case_name == "blocked_packet_request": next(item for item in document["events"] if item["record_type"] == "packet" and item["payload"].get("phase") == "request")["payload"]["status"] = "blocked"
    if case_name == "packet_result_conflict": document["events"].insert(4, event(case_id, cycle_id, candidate_id, "event-packet-result-conflict", "packet", {"packet_id": "packet-implementation", "phase": "result", "status": "completed", "checks": [{"gate_id": "gate-packet", "status": "failed"}]}))
    if case_name == "stage_ordering": document["events"][0]["payload"]["stage"] = "review"
    if case_name == "closure_self_declared_gate": document["events"][-1]["payload"]["self_declared_proof"] = True
    if case_name == "closure_omits_normative_gate": document["events"][-1]["payload"]["required_gate_ids"] = list(ROUTE_GATES["R2"][:-1])
    if case_name == "prior_cycle_gate_reuse": document["events"][-2]["cycle_id"] = "cycle-prior"
    if case_name == "independent_review_same_implementer":
        gate = next(item for item in document["events"] if item["record_type"] == "gate" and item["payload"].get("gate_id") == "independent-review")
        gate["payload"]["reviewer_id"] = gate["payload"]["implementation_id"]
    if case_name == "all_dispatches_low_effort": dispatch.update(selected_effort="low", attested_effort="low")
    if case_name == "evidenced_higher_effort":
        dispatch.update(selected_effort="ultra", attested_effort="ultra"); document["events"].insert(4, event(case_id, cycle_id, candidate_id, "event-escalation", "gate", {"cause": "complexity_escalation", "receipt_id": "escalation-risk", "evidence_id": "evidence-current", "system_generated": True}))
    if case_name == "high_selected_low_attested": dispatch["attested_effort"] = "low"
    if case_name == "r3_luna_implementation":
        document["route"] = "R3"; document["events"][0]["payload"]["route"] = "R3"
        worker_binding = binding(case_id, "worker_intelligence")
        dispatch["model_id"] = worker_binding["model_id"]; capability["models"] = [worker_binding["model_id"]]
        implementation = next(item for item in document["events"] if item["payload"].get("decision_kind") == "implementation")
        implementation["payload"].update({"requested_role": "worker_intelligence", "model_id": worker_binding["model_id"], "binding_id": worker_binding["binding_id"], "binding_sha256": worker_binding["binding_sha256"], "capability_models": capability["models"]})
    if case_name == "route_floor_violation":
        document["route"] = "R1"; document["events"][0]["payload"].update({"route": "R1", "activation_class": "shared_contract_change"})
    if case_name == "missing_ultimate_design": document["events"] = [item for item in document["events"] if item["event_id"] != "event-ultimate-design"]
    if case_name == "ultimate_wrong_binding":
        for item in document["events"]:
            if item["record_type"] == "dispatch" and item["payload"].get("requested_role") == "ultimate_intelligence":
                worker_binding = binding(case_id, "worker_intelligence")
                item["payload"].update({"model_id": worker_binding["model_id"], "binding_id": worker_binding["binding_id"], "binding_sha256": worker_binding["binding_sha256"], "selected_effort": "low", "attested_effort": "low"})
    if case_name == "final_disposition_hold":
        next(item for item in document["events"] if item["event_id"] == "event-ultimate-final")["payload"]["disposition"] = "hold"
    if case_name == "later_final_hold":
        document["events"].insert(-1, protected_dispatch(case_id, cycle_id, candidate_id, "event-ultimate-final-hold", "ultimate_intelligence", "final", "context-ultimate-final-hold", "task-ultimate-final-hold", disposition="hold"))
    if case_name == "later_operational_review_hold":
        final_index = next(index for index, item in enumerate(document["events"]) if item["payload"].get("decision_kind") == "final")
        document["events"].insert(final_index, protected_dispatch(case_id, cycle_id, candidate_id, "event-operational-review-hold", "operational_intelligence", "review", "context-operational-review-hold", "task-operational-review-hold", disposition="hold"))
    if case_name == "later_implementation_hold": document["events"].insert(-1, protected_dispatch(case_id, cycle_id, candidate_id, "event-implementation-hold", "technical_tactical_intelligence", "implementation", "context-implementation-hold", "task-implementation-hold", disposition="hold"))
    if case_name == "later_invalid_final_record":
        invalid_final = protected_dispatch(case_id, cycle_id, candidate_id, "event-ultimate-final-invalid", "ultimate_intelligence", "final", "context-ultimate-final-invalid", "task-ultimate-final-invalid")
        invalid_final["payload"].update({"binding_id": "binding-invalid", "binding_sha256": token(case_id + "invalid-binding")})
        document["events"].insert(-1, invalid_final)
    if case_name == "later_native_run_hold":
        configure_qualification(2)
        final_index = next(index for index, item in enumerate(document["events"]) if item["payload"].get("decision_kind") == "final")
        document["events"].insert(final_index, protected_dispatch(case_id, cycle_id, candidate_id, "event-native-run-hold", "ultimate_intelligence", "native_forward", "context-native-run-hold", "task-native-run-hold", disposition="hold", qualification_run_id="native-forward-run-1"))
    if case_name == "capability_metadata_as_behavioral_evidence":
        metadata = next(item for item in document["events"] if item["record_type"] == "evidence")
        metadata["payload"].pop("path")
        metadata["payload"].pop("sha256")
        metadata["payload"].update({"kind": "provider_capability", "receipt_sha256": capability["receipt_sha256"]})
    if case_name == "wrapped_capability_metadata_as_behavioral_evidence":
        document["evidence_content"] = behavioral_evidence(document["engineering_candidate"]) | {"provider_capability_receipt": capability}
    if case_name == "candidate_transition_metadata_as_behavioral_evidence":
        metadata = next(item for item in document["events"] if item["record_type"] == "evidence")
        metadata["payload"].update({"kind": "candidate_transition_metadata", "candidate_sha256": candidate_sha256})
        document["evidence_content"] = {"schema_version": "agent-council.candidate-transition/v2", "candidate_id": candidate_id, "candidate_sha256": candidate_sha256, "cycle_id": cycle_id, "prior_candidate_id": "candidate-prior"}
    if case_name == "behavioral_evidence_missing_type":
        document["evidence_content"].pop("evidence_kind")
    if case_name == "behavioral_evidence_candidate_mismatch":
        document["evidence_content"]["candidate_id"] = "candidate-prior"
    if case_name == "behavioral_evidence_run_mismatch":
        document["evidence_content"]["run"]["run_id"] = "test-other"
    if case_name == "behavioral_evidence_empty_assertions":
        document["evidence_content"]["assertion"] = {}
    if case_name == "behavioral_evidence_result_not_passed":
        document["evidence_content"]["result"]["status"] = "failed"
    if case_name in {"qualification_evidence_candidate_payload_tamper", "qualification_evidence_cycle_payload_tamper"}:
        configure_qualification(2)
        alternate_sha256 = token(case_id + "alternate-evidence-candidate")
        alternate_candidate = {"candidate_id": f"candidate-{alternate_sha256[:24]}", "candidate_sha256": alternate_sha256}
        for item in document["events"]:
            if item["record_type"] == "evidence" and item["payload"].get("kind") == "behavioral_test":
                if case_name == "qualification_evidence_candidate_payload_tamper":
                    item["payload"].update(alternate_candidate)
                else:
                    item["payload"]["cycle_id"] = "cycle-prior"
        if case_name == "qualification_evidence_candidate_payload_tamper":
            document["evidence_content"] = behavioral_evidence(alternate_candidate, "test-normative", cycle_id)
            document["fault_evidence_content"] = behavioral_evidence(alternate_candidate, "test-fault", cycle_id)
        else:
            document["evidence_content"] = behavioral_evidence(document["engineering_candidate"], "test-normative", "cycle-prior")
            document["fault_evidence_content"] = behavioral_evidence(document["engineering_candidate"], "test-fault", "cycle-prior")
    if case_name == "qualification_non_normative_failed_gate":
        configure_qualification(2)
        document["events"].insert(-1, event(case_id, cycle_id, candidate_id, "event-gate-additional-security", "gate", {"gate_id": "additional-security", "status": "failed", "evidence_id": "evidence-current", "system_generated": True}))
    if case_name == "review_before_implementation":
        review = next(item for item in document["events"] if item["payload"].get("decision_kind") == "review")
        document["events"].remove(review)
        request_index = next(index for index, item in enumerate(document["events"]) if item["record_type"] == "packet" and item["payload"].get("phase") == "request")
        document["events"].insert(request_index, review)
    if case_name == "final_before_review":
        final = next(item for item in document["events"] if item["event_id"] == "event-ultimate-final")
        document["events"].remove(final); document["events"].insert(1, final)
    if case_name == "design_after_final":
        design = next(item for item in document["events"] if item["event_id"] == "event-ultimate-design")
        document["events"].remove(design)
        final = next(item for item in document["events"] if item["event_id"] == "event-ultimate-final")
        document["events"].insert(document["events"].index(final) + 1, design)
    if case_name == "missing_operational_review": document["events"] = [item for item in document["events"] if item["event_id"] != "event-operational-review"]
    if case_name == "r1_review_same_implementer":
        document["route"] = "R1"
        document["events"][0]["payload"].update({"route": "R1", "activation_class": "bounded_automation_repair"})
        document["events"] = [item for item in document["events"] if item["record_type"] not in {"gate", "closure"} and item["event_id"] not in {"event-ultimate-design", "event-ultimate-final"}]
        review = next(item for item in document["events"] if item["event_id"] == "event-operational-review")
        review["payload"].update({"platform_task_id": "task-technical", "platform_context_id": "context-current", "capability_context_id": "context-current"})
        for gate_id in ROUTE_GATES["R1"]:
            if gate_id == "ultimate-final-disposition": document["events"].append(protected_dispatch(case_id, cycle_id, candidate_id, "event-ultimate-final", "ultimate_intelligence", "final", "context-ultimate-final", "task-ultimate-final"))
            document["events"].append(event(case_id, cycle_id, candidate_id, f"event-gate-{gate_id}", "gate", {"gate_id": gate_id, "status": "passed", "evidence_id": "evidence-current", "system_generated": True}))
        document["events"].append(event(case_id, cycle_id, candidate_id, "event-closure", "closure", {"stage": "close", "required_gate_ids": list(ROUTE_GATES["R1"]), "system_generated": True}))
    if case_name == "active_failed_test":
        final_index = next(index for index, item in enumerate(document["events"]) if item["event_id"] == "event-ultimate-final")
        document["events"].insert(final_index, event(case_id, cycle_id, candidate_id, "event-test-active-failure", "test", {"run_id": "test-active-failure", "status": "failed", "evidence_id": "evidence-current"}))
    if case_name == "r3_missing_fault_test":
        configure_qualification(2)
        document["events"][0]["payload"].update({"activation_class": "shared_contract_change", "case_kind": "operational_change"})
        document["events"] = [item for item in document["events"] if item["event_id"] != "event-test-fault" and item["payload"].get("qualification_run_id") is None and item["payload"].get("gate_id") not in QUALIFICATION_GATES]
        next(item for item in document["events"] if item["record_type"] == "closure")["payload"]["required_gate_ids"] = list(ROUTE_GATES["R3"])
    if case_name == "qualification_activation_operational_kind":
        configure_qualification(2)
        document["events"][0]["payload"].update({"activation_class": "council_qualification", "case_kind": "operational_change"})
    if case_name == "qualification_omits_native_gates":
        configure_qualification(0)
        document["events"] = [item for item in document["events"] if item["payload"].get("gate_id") not in QUALIFICATION_GATES]
        next(item for item in document["events"] if item["record_type"] == "closure")["payload"]["required_gate_ids"] = list(ROUTE_GATES["R3"])
    if case_name == "qualification_one_native_run": configure_qualification(1)
    if case_name == "qualification_same_context": configure_qualification(2, same_context=True)
    if case_name == "qualification_unrelated_diversity":
        configure_qualification(2, same_context=True)
        document["events"].insert(-1, protected_dispatch(case_id, cycle_id, candidate_id, "event-native-unrelated", "ultimate_intelligence", "native_forward", "context-native-unrelated", "task-native-unrelated"))
    if case_name == "qualification_blank_identity":
        configure_qualification(2)
        run = next(item for item in document["events"] if item["payload"].get("qualification_run_id") == "native-forward-run-2")
        run["payload"].update({"platform_task_id": "", "platform_context_id": "", "capability_context_id": ""})
    if case_name == "qualification_native_gate_status_missing":
        configure_qualification(2)
        gate = next(item for item in document["events"] if item["record_type"] == "gate" and item["payload"].get("gate_id") == "native-forward-run-2")
        gate["payload"].pop("status")
    if case_name == "qualification_normative_route_gate_status_missing":
        configure_qualification(2)
        for gate in (item for item in document["events"] if item["record_type"] == "gate" and item["payload"].get("gate_id") in ROUTE_GATES["R3"]):
            gate["payload"].pop("status")
    if case_name == "qualification_final_before_native":
        configure_qualification(2)
        final = next(item for item in document["events"] if item["event_id"] == "event-ultimate-final")
        native = [item for item in document["events"] if item["payload"].get("decision_kind") == "native_forward"]
        document["events"] = [item for item in document["events"] if item not in native]
        final_index = document["events"].index(final)
        document["events"][final_index + 1:final_index + 1] = native
    if case_name == "qualification_two_native_runs": configure_qualification(2)
    if case_name == "stale_capability": capability["observed_at"] = "2000-01-01T00:00:00Z"
    if case_name == "invalid_capability_context": capability["context_id"] = ""
    if case_name == "provider_model_or_effort_mismatch": dispatch["model_id"] = "other-qualified-model"
    if case_name == "caller_authored_native_receipt": dispatch["system_generated"] = False
    if case_name == "provider_fail_closed_authority":
        claude_binding = {"binding_id": "binding-claude-ultimate", "provider": "claude_code", "model_id": "qualified-ultimate_intelligence-model", "tier": "ultimate_intelligence", "status": "qualified"}
        claude_binding["binding_sha256"] = digest(claude_binding)
        document["registry"]["bindings"].append(claude_binding)
        for item in document["events"]:
            if item["record_type"] == "dispatch" and item["payload"].get("requested_role") == "ultimate_intelligence":
                item["payload"].update({"provider": "claude_code", "binding_id": claude_binding["binding_id"], "binding_sha256": claude_binding["binding_sha256"]})
        registry_without_digest = {key: value for key, value in document["registry"].items() if key != "registry_sha256"}
        document["registry"]["registry_sha256"] = digest(registry_without_digest)
        document["identity"]["registry_sha256"] = document["registry"]["registry_sha256"]
        for item in document["events"]: item["identity"]["registry_sha256"] = document["registry"]["registry_sha256"]
    if case_name == "registry_content_tamper": document["registry"]["bindings"][-1]["model_id"] = "tampered-worker-model"
    if case_name == "missing_evidence_file":
        required_evidence = next(item for item in document["events"] if item["event_id"] == "event-evidence")
        required_evidence["payload"].update({"path": "evidence/does-not-exist.json", "sha256": token("wrong-evidence")})
    if case_name in {"authority_dispatch_output_ref_missing", "authority_dispatch_output_ref_null", "authority_dispatch_output_ref_object", "authority_dispatch_output_ref_control"}:
        for item in (event for event in document["events"] if event["record_type"] == "dispatch"):
            if case_name == "authority_dispatch_output_ref_missing": item["payload"].pop("platform_output_ref", None)
            elif case_name == "authority_dispatch_output_ref_null": item["payload"]["platform_output_ref"] = None
            elif case_name == "authority_dispatch_output_ref_object": item["payload"]["platform_output_ref"] = {"invalid": "object"}
            else: item["payload"]["platform_output_ref"] = "control\nvalue"
    if case_name == "authority_dispatch_capability_models_null":
        for item in (event for event in document["events"] if event["record_type"] == "dispatch"): item["payload"]["capability_models"] = None
    if case_name == "object_stage": document["events"][0]["payload"]["stage"] = {"invalid": "object"}
    if case_name == "object_decision_kind":
        for item in (event for event in document["events"] if event["record_type"] == "dispatch"): item["payload"]["decision_kind"] = {"invalid": "object"}
    if case_name == "object_evidence_id": next(item for item in document["events"] if item["record_type"] == "evidence")["payload"]["evidence_id"] = {"invalid": "object"}
    if case_name == "object_provider":
        for item in (event for event in document["events"] if event["record_type"] == "dispatch"): item["payload"]["provider"] = {"invalid": "object"}
    if case_name in {"packet_result_before_request", "packet_result_before_implementation"}:
        result = next(item for item in document["events"] if item["record_type"] == "packet" and item["payload"].get("phase") == "result")
        document["events"].remove(result)
        if case_name == "packet_result_before_request": document["events"].insert(1, result)
        else:
            request_index = next(index for index, item in enumerate(document["events"]) if item["record_type"] == "packet" and item["payload"].get("phase") == "request")
            document["events"].insert(request_index + 1, result)
    if case_name == "packet_result_pair_mismatch": next(item for item in document["events"] if item["record_type"] == "packet" and item["payload"].get("phase") == "result")["payload"]["packet_id"] = "packet-other"
    if case_name == "orphan_immutable_event": document["_orphan_event"] = event(case_id, cycle_id, candidate_id, "event-orphan-interruption", "interruption", {"status": "interrupted", "owned_processes": [{"identity": "orphan-process", "status": "unknown"}]})
    if case_name == "password_field_in_evidence": document["evidence_content"] = {"password": "fixture-only-invalid-value"}
    if case_name == "utf8_control_byte_evidence": document["evidence_content"] = "control\u0001byte"
    if case_name == "cross_cycle_unreconciled": document["events"].insert(1, event(case_id, "cycle-prior", "candidate-prior", "event-interruption", "interruption", {"status": "interrupted", "interrupted_event_id": "event-prior-work", "owned_processes": [{"identity": "process-prior", "status": "unknown"}]}))
    if case_name == "cross_cycle_exact_resumption":
        document["events"].insert(1, event(case_id, "cycle-prior", candidate_id, "event-interruption", "interruption", {"status": "interrupted", "interrupted_event_id": "event-prior-work", "owned_processes": [{"identity": "process-prior", "status": "reconciled"}]})); document["events"].insert(2, event(case_id, cycle_id, candidate_id, "event-resumption", "resumption", {"interruption_id": "event-interruption", "exact_resumption": True, "prior_candidate_id": candidate_id}))
    if case_name == "orphan_resumption": document["events"].insert(1, event(case_id, cycle_id, candidate_id, "event-resumption", "resumption", {"interruption_id": "event-missing", "exact_resumption": True, "prior_candidate_id": candidate_id}))
    if case_name == "duplicate_resumption":
        interruption = event(case_id, "cycle-prior", candidate_id, "event-interruption", "interruption", {"status": "interrupted", "interrupted_event_id": "event-prior-work", "owned_processes": [{"identity": "process-prior", "status": "reconciled"}]})
        resumption = event(case_id, cycle_id, candidate_id, "event-resumption-one", "resumption", {"interruption_id": "event-interruption", "exact_resumption": True, "prior_candidate_id": candidate_id})
        duplicate = event(case_id, cycle_id, candidate_id, "event-resumption-two", "resumption", {"interruption_id": "event-interruption", "exact_resumption": True, "prior_candidate_id": candidate_id})
        document["events"][1:1] = [interruption, resumption, duplicate]
    if case_name == "same_cycle_resumption":
        interruption = event(case_id, cycle_id, candidate_id, "event-interruption", "interruption", {"status": "interrupted", "interrupted_event_id": "event-prior-work", "owned_processes": [{"identity": "process-prior", "status": "reconciled"}]})
        resumption = event(case_id, cycle_id, candidate_id, "event-resumption", "resumption", {"interruption_id": "event-interruption", "exact_resumption": True, "prior_candidate_id": candidate_id})
        document["events"][1:1] = [interruption, resumption]
    if case_name == "nonexistent_supersession": document["events"].insert(-1, event(case_id, cycle_id, candidate_id, "event-supersession", "supersession", {"supersedes_event_id": "event-not-present", "retired_event_id": "event-not-present"}))
    if case_name == "valid_supersession_retires_failure":
        document["events"].insert(6, event(case_id, cycle_id, candidate_id, "event-test-failed", "test", {"run_id": "test-failed", "status": "failed", "evidence_id": "evidence-current"})); document["events"].insert(7, event(case_id, cycle_id, candidate_id, "event-supersession", "supersession", {"supersedes_event_id": "event-test-failed", "retired_event_id": "event-test-failed"}))
    if case_name == "changed_candidate_new_cycle":
        transition_evidence = {"schema_version": "agent-council.candidate-transition/v2", "candidate_id": candidate_id, "candidate_sha256": candidate_sha256, "cycle_id": cycle_id, "prior_candidate_id": "candidate-prior"}
        document["transition_evidence_content"] = transition_evidence
        document["events"].insert(1, event(case_id, cycle_id, candidate_id, "event-transition-evidence", "evidence", {"evidence_id": "evidence-transition", "kind": "candidate_transition_metadata", "path": "evidence/transition.json", "sha256": token(case_id + "transition-evidence"), "candidate_sha256": candidate_sha256})); document["events"].insert(2, event(case_id, cycle_id, candidate_id, "event-candidate-transition", "candidate_transition", {"prior_candidate_id": "candidate-prior", "fresh_evidence_id": "evidence-transition", "system_generated": True}))
    if case_name == "candidate_bytes_changed_same_id": document["engineering_candidate"]["source_sha256"] = token(case_id + "changed-source")
    if case_name == "prior_candidate_evidence_reuse":
        prior_sha256 = token(case_id + "prior-candidate")
        prior_candidate = {"candidate_id": f"candidate-{prior_sha256[:24]}", "candidate_sha256": prior_sha256}
        next(item for item in document["events"] if item["record_type"] == "test")["payload"]["evidence_id"] = "evidence-prior"; document["prior_evidence_content"] = behavioral_evidence(prior_candidate, "test-prior", "cycle-prior"); document["events"].insert(1, event(case_id, "cycle-prior", prior_candidate["candidate_id"], "event-prior-evidence", "evidence", {"evidence_id": "evidence-prior", "kind": "behavioral_test", "path": "evidence/prior.json", "sha256": token(case_id + "prior-evidence"), "candidate_id": prior_candidate["candidate_id"], "candidate_sha256": prior_sha256, "cycle_id": "cycle-prior"}))
    if case_name == "pinned_schema_after_package_rotation": document["pinned_schema_sha256"] = token(case_id + "schema-pinned"); document["package_schema_sha256"] = token(case_id + "schema-rotated")
    previous = None
    capability["receipt_sha256"] = digest({key: value for key, value in capability.items() if key != "receipt_sha256"})
    dispatch["receipt_sha256"] = digest({key: value for key, value in dispatch.items() if key != "receipt_sha256"})
    implementation = next((item for item in document["events"] if item["record_type"] == "dispatch" and item["payload"].get("dispatch_receipt_id") == dispatch["receipt_id"]), None)
    if implementation is not None:
        implementation["payload"].update({"dispatch_receipt_sha256": dispatch["receipt_sha256"], "model_id": dispatch["model_id"], "selected_effort": dispatch["selected_effort"], "attested_effort": dispatch["attested_effort"], "platform_task_id": dispatch["dispatch_id"], "platform_context_id": dispatch["context_id"], "capability_receipt_sha256": capability["receipt_sha256"], "capability_context_id": capability["context_id"], "capability_models": capability["models"], "capability_efforts": capability["efforts"], "capability_observed_at": capability["observed_at"]})
    for item in document["events"]:
        if item["record_type"] == "dispatch":
            reseal_dispatch_payload(item["payload"])
    for item in document["events"]:
        item["payload"]["previous_event_sha256"] = previous
        item["event_sha256"] = digest({key: value for key, value in item.items() if key != "event_sha256"})
        previous = item["event_sha256"]
    return document


def write_case(case_name: str, parent: Path) -> dict[str, Any]:
    root = parent / case_name; root.mkdir(parents=True); document = base_case(case_name, root)
    orphan = document.pop("_orphan_event", None)
    evidence = document.pop("evidence_content", behavioral_evidence(document["engineering_candidate"], cycle_id=document["cycle_id"]))
    evidence_path = root / "evidence" / "test-output.json"; evidence_path.parent.mkdir(exist_ok=True)
    evidence_path.write_bytes(b"control\x01byte" if case_name == "utf8_control_byte_evidence" else canonical(evidence) + b"\n")
    fault_evidence_path = root / "evidence" / "fault-output.json"
    if any(item["record_type"] == "evidence" and item["payload"].get("path") == "evidence/fault-output.json" for item in document["events"]):
        fault_evidence = document.pop("fault_evidence_content", behavioral_evidence(document["engineering_candidate"], "test-fault", document["cycle_id"]))
        fault_evidence_path.write_bytes(canonical(fault_evidence) + b"\n")
    prior_evidence_path = root / "evidence" / "prior.json"
    if any(item["record_type"] == "evidence" and item["payload"].get("path") == "evidence/prior.json" for item in document["events"]):
        prior_evidence = document.pop("prior_evidence_content", behavioral_evidence(document["engineering_candidate"], "test-prior", "cycle-prior"))
        prior_evidence_path.write_bytes(canonical(prior_evidence) + b"\n")
    transition_evidence_path = root / "evidence" / "transition.json"
    if any(item["record_type"] == "evidence" and item["payload"].get("path") == "evidence/transition.json" for item in document["events"]):
        transition_evidence = document.pop("transition_evidence_content", {"schema_version": "agent-council.candidate-transition/v2"})
        transition_evidence_path.write_bytes(canonical(transition_evidence) + b"\n")
    for item in document["events"]:
        path = item["payload"].get("path") if item["record_type"] == "evidence" else None
        evidence_file = root / path if isinstance(path, str) else None
        if evidence_file is not None and evidence_file.is_file():
            item["payload"]["sha256"] = hashlib.sha256(evidence_file.read_bytes()).hexdigest()
    previous = None
    for item in document["events"]:
        item["payload"]["previous_event_sha256"] = previous
        item["event_sha256"] = digest({key: value for key, value in item.items() if key != "event_sha256"})
        previous = item["event_sha256"]
        path = root / "events" / f"{item['event_id']}.json"; path.parent.mkdir(exist_ok=True); path.write_bytes(canonical(item) + b"\n")
    if orphan is not None:
        path = root / "events" / f"{orphan['event_id']}.json"; path.write_bytes(canonical(orphan) + b"\n")
    (root / "case.json").write_bytes(canonical(document) + b"\n")
    for path in sorted(root.rglob("*"), reverse=True): os.chmod(path, stat.S_IXUSR | stat.S_IRUSR if path.is_dir() else stat.S_IRUSR)
    return json.loads((root / "case.json").read_text(encoding="utf-8"))


def schema_declaration_preflight(path: Path) -> dict[str, Any]:
    schema = json.loads(path.read_text(encoding="utf-8"))
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema" or not isinstance(schema.get("$id"), str):
        raise ValueError(f"{path.name} does not declare a Draft 2020-12 schema")
    if schema.get("type") != "object" or not isinstance(schema.get("required"), list) or not isinstance(schema.get("properties"), dict):
        raise ValueError(f"{path.name} lacks the required object-schema structure")
    return schema


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def document_schema_errors(name: str, value: Any) -> list[str]:
    if not isinstance(value, dict): return [f"{name} must be an object"]
    if name == "bundle":
        required = {"schema_version", "case_id", "case_root", "cycle_id", "route", "identity", "policy_bundle", "engineering_candidate", "registry", "provider_capability_receipt", "provider_dispatch_receipt", "events"}
        identity = value.get("identity", {}); candidate = value.get("engineering_candidate", {})
        valid = required <= value.keys() and value["schema_version"] == "agent-council.case/v2" and value["route"] in {"R1", "R2", "R3"} and identity.get("registry_version") == "v2" and {"candidate_sha256", "dependency_lock_sha256", "policy_sha256"} <= candidate.keys()
        return [] if valid else ["bundle required fields are invalid"]
    if name == "registry":
        return [] if value.get("schema_version") == "agent-council.model-registry/v2" and value.get("reasoning", {}).get("default_effort") == "high" and value.get("bindings") else ["registry required fields are invalid"]
    if name == "capability":
        return [] if value.get("receipt_type") == "provider_capability" and is_sha256(value.get("receipt_sha256")) and isinstance(value.get("context_id"), str) and value.get("context_id") and value.get("models") and value.get("efforts") else ["capability required fields are invalid"]
    if name == "dispatch":
        return [] if value.get("receipt_type") == "provider_dispatch" and is_sha256(value.get("receipt_sha256")) and value.get("selected_effort") and value.get("attested_effort") else ["dispatch required fields are invalid"]
    if name == "record":
        required = {"record_type", "event_id", "event_sha256", "recorded_at", "identity", "candidate_id", "cycle_id", "payload"}
        payload = value.get("payload", {}); identity = value.get("identity", {})
        valid = required <= value.keys() and is_sha256(value.get("event_sha256")) and identity.get("registry_version") == "v2" and isinstance(payload, dict) and "previous_event_sha256" in payload
        if value.get("record_type") in {"case", "dispatch", "gate", "closure"}: valid = valid and payload.get("system_generated") is True and "proof" not in payload
        if value.get("record_type") == "packet": valid = valid and {"packet_id", "phase", "status"} <= payload.keys()
        if value.get("record_type") == "resumption": valid = valid and payload.get("exact_resumption") is True and {"interruption_id", "prior_candidate_id"} <= payload.keys()
        if value.get("record_type") == "supersession": valid = valid and {"supersedes_event_id", "retired_event_id"} <= payload.keys()
        return [] if valid else ["record required fields are invalid"]
    return [f"unsupported schema check: {name}"]


def fixture_errors(document: dict[str, Any], validators: dict[str, dict[str, Any]], expected_code: str) -> list[str]:
    errors = []
    checks = (("bundle", document), ("registry", document["registry"]), ("capability", document["provider_capability_receipt"]), ("dispatch", document["provider_dispatch_receipt"]))
    for name, value in checks:
        if expected_code == "SCHEMA_VALIDATION_FAILED" and name in {"bundle", "capability"}: continue
        if document_schema_errors(name, value): errors.append(f"{name} schema rejected fixture")
    events = document["events"]; hashes = {item["event_sha256"] for item in events}; ids = {item["event_id"] for item in events}
    if len(hashes) != len(events) or len(ids) != len(events): errors.append("event hashes and identifiers must be distinct")
    if not {item["candidate_id"] for item in events} or not {item["cycle_id"] for item in events} or not any(item["record_type"] == "packet" for item in events): errors.append("fixture lacks candidate, cycle, or packet records")
    for item in events:
        if item["event_sha256"] != digest({key: value for key, value in item.items() if key != "event_sha256"}): errors.append(f"event hash mismatch: {item['event_id']}")
        if document_schema_errors("record", item): errors.append(f"event schema rejected: {item['event_id']}")
        path = Path(document["case_root"]) / "events" / f"{item['event_id']}.json"
        if not path.exists() or path.stat().st_mode & stat.S_IWUSR: errors.append(f"event is not immutable: {item['event_id']}")
    for key in ("provider_capability_receipt", "provider_dispatch_receipt", "engineering_candidate"):
        if not document.get(key): errors.append(f"fixture lacks {key}")
    if not (Path(document["case_root"]) / "evidence" / "test-output.json").exists(): errors.append("fixture lacks evidence")
    return errors


def test_schema() -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []; validators: dict[str, dict[str, Any]] = {}
    try:
        for name in SCHEMAS: validators[name] = schema_declaration_preflight(PACKAGE / "standards" / name); rows.append((name, True, "declares an identified Draft 2020-12 object schema"))
        standard = json.loads((PACKAGE / "standards" / "agent-council-standard.v2.yaml").read_text(encoding="utf-8"))
        permanent = canonical({"roles": standard["roles"], "routes": standard["route_role_requirements"]}).decode("utf-8")
        rows.append(("vendor-neutral permanent roles", standard["roles"] == list(ROLES) and "gpt-" not in permanent, "permanent tiers contain roles only; bindings belong in the registry"))
        rows.append(("normative-route-gates", all(tuple(standard["route_closure_gates"][route]) == gates for route, gates in ROUTE_GATES.items()) and tuple(standard["qualification_closure_gates"]) == QUALIFICATION_GATES, "runtime route and qualification gates are declared by policy"))
        rows.append(("normative-route-floors", standard["activation_route_floors"]["bounded_automation_repair"] == "R1" and standard["activation_route_floors"]["unqualified_composition"] == "R2" and standard["activation_route_floors"]["shared_contract_change"] == "R3", "activation classes have explicit minimum routes"))
        with tempfile.TemporaryDirectory(prefix="agent-council-v2-schema-") as temporary:
            for case_name in CASE_SPECS:
                _, _, expected_code = CASE_SPECS[case_name]
                document = write_case(case_name, Path(temporary)); issues = fixture_errors(document, validators, expected_code)
                rows.append((f"fixture-{case_name}", not issues, "; ".join(issues) if issues else "structured immutable case document is valid"))
                rows.append((f"fixture-{case_name}-no-oracle", "expected" not in document, "runtime fixture must not contain its expected answer"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc: rows.append(("schema qualification", False, str(exc)))
    return rows


def candidate_v3_registry() -> dict[str, Any]:
    """Derive a valid candidate from either an installed or promoted catalog."""
    candidate = json.loads((PACKAGE / "standards/agent-model-registry.v3.yaml").read_bytes())
    for binding in candidate["bindings"]:
        binding["status"] = "candidate"
        binding.pop("qualified_roles", None)
        binding["binding_sha256"] = digest({key: value for key, value in binding.items() if key != "binding_sha256"})
    for state in candidate["provider_states"].values():
        state["council_status"] = "fail_closed_until_qualified"
    candidate["registry_sha256"] = digest({key: value for key, value in candidate.items() if key != "registry_sha256"})
    return candidate


def test_registry_role_schema() -> list[tuple[str, bool, str]]:
    """Optional Draft 2020-12 checks, run with jsonschema supplied externally."""
    from jsonschema import Draft202012Validator
    api, error = load_runtime()
    if error:
        return [("registry-role-schema-runtime", False, error)]
    promotion = api.__globals__["_promotion_verifier"]()
    schema = json.loads((PACKAGE / "standards/agent-model-registry.schema.v3.yaml").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    candidate = candidate_v3_registry()
    candidate_bytes = canonical(candidate)
    protocols = {binding["binding_id"]: promotion.protocol.protocol_binding(binding) for binding in candidate["bindings"]}
    promoted = json.loads(promotion.promote_registry(candidate_bytes, qualification_protocols=protocols))
    legacy = json.loads(promotion.promote_registry(candidate_bytes))
    rows = [("registry-schema-" + label, validator.is_valid(value), "declared registry schema accepts the exact supported transformation") for label, value in (("candidate", candidate), ("legacy-promoted", legacy), ("role-promoted", promoted))]
    for label, change in (
        ("empty-coverage", {"qualified_roles": []}),
        ("duplicate-coverage", {"qualified_roles": ["ultimate_intelligence", "ultimate_intelligence"]}),
        ("unknown-coverage", {"qualified_roles": ["ultimate_intelligence", "invented_role"]}),
        ("missing-own-tier", {"qualified_roles": ["worker_intelligence"]}),
        ("wrong-shape", {"qualified_roles": "ultimate_intelligence"}),
        ("candidate-coverage", {"status": "candidate"}),
        ("revoked-coverage", {"status": "revoked"}),
        ("expired-coverage", {"status": "hard_expired"}),
    ):
        invalid = json.loads(json.dumps(promoted))
        next(binding for binding in invalid["bindings"] if binding["tier"] == "ultimate_intelligence").update(change)
        rows.append(("registry-schema-refuses-" + label, not validator.is_valid(invalid), "invalid role-coverage metadata fails the published JSON Schema"))
    retired = json.loads(json.dumps(promoted))
    retired["bindings"][0].update(status="retired", lifecycle={"retired_at": FIXTURE_NOW, "reason": "Binding retired", "replacement_binding_id": None})
    rows.append(("registry-schema-retired-coverage", validator.is_valid(retired), "retirement preserves historical verified coverage without granting eligibility"))
    return rows


def load_runtime() -> tuple[Any | None, str | None]:
    if not RUNTIME.exists(): return None, "v2 runtime file is absent"
    try:
        source = RUNTIME.read_text(encoding="utf-8"); tree = ast.parse(source)
        forbidden = set(CASE_SPECS); strings = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        if forbidden & strings: return None, "production runtime contains test-case dispatch literals"
        spec = importlib.util.spec_from_file_location("agent_council_v2", RUNTIME)
        if spec is None or spec.loader is None: return None, "v2 runtime import specification unavailable"
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); api = getattr(module, "evaluate_contract_case", None)
        return (api, None) if callable(api) else (None, "public evaluate_contract_case(case_document) API is absent")
    except (OSError, SyntaxError, ImportError, RuntimeError, TypeError, ValueError) as exc: return None, str(exc)


def runtime_red_cases(group: str) -> list[tuple[str, bool, str]]:
    names = [name for name, (case_group, _, _) in CASE_SPECS.items() if case_group == group]
    if group == "authoring": names.append("changed_candidate_new_cycle")
    rows: list[tuple[str, bool, str]] = []; api, runtime_error = load_runtime(); validators: dict[str, dict[str, Any]] = {name: schema_declaration_preflight(PACKAGE / "standards" / name) for name in SCHEMAS}
    with tempfile.TemporaryDirectory(prefix=f"agent-council-v2-{group}-") as temporary:
        for name in names:
            _, expected_result, expected_code = CASE_SPECS[name]
            document = write_case(name, Path(temporary)); issues = fixture_errors(document, validators, expected_code); rows.append((f"{name}-fixture", not issues, "; ".join(issues) if issues else "immutable structured fixture is valid"))
            if runtime_error: rows.append((name, False, f"runtime/API absent: {runtime_error}; expected {expected_result} with {expected_code}")); continue
            try:
                observed = api(document); matched = observed.get("result") == expected_result and observed.get("code") == expected_code
                if name in EXPECTED_EFFORT: matched = matched and observed.get("effort") == EXPECTED_EFFORT[name]
                if name in EVALUATOR_ASSURANCE_CASES: matched = matched and structural_refusal(observed, expected_code)
                rows.append((name, matched, f"expected {expected_result} with {expected_code}"))
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc: rows.append((name, False, f"runtime/API error: {exc}; expected {expected_result} with {expected_code}"))
    return rows


def cli_detail(*args: str) -> tuple[int, dict[str, Any], str]:
    command = list(args)
    if "--case-root" in command and "--project-root" not in command:
        case_root = Path(command[command.index("--case-root") + 1])
        command.extend(("--project-root", str(case_root.parent)))
    if command and command[0] == "init-case" and "--registry-version" not in command:
        namespace = runpy.run_path(str(RUNTIME), run_name="agent_council_legacy_test_fixture")
        runtime_globals = namespace["main"].__globals__
        original = runtime_globals["_pinned_artifact_material"]
        runtime_globals["_pinned_artifact_material"] = lambda _version="v3": original("v2")
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = namespace["main"](command)
        stdout, stderr = output.getvalue(), errors.getvalue()
    else:
        completed = subprocess.run([sys.executable, str(RUNTIME), *command], capture_output=True, text=True, check=False)
        code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
    try:
        response = json.loads(stdout)
    except json.JSONDecodeError:
        response = {"result": "invalid", "stdout": stdout, "stderr": stderr}
    return code, response, stderr


def cli(*args: str) -> tuple[int, dict[str, Any]]:
    code, response, _ = cli_detail(*args)
    return code, response


def cli_fault(boundary: str, *args: str) -> tuple[int, dict[str, Any], str]:
    """Run one public command with a deterministic post-durability fault."""
    command = list(args)
    if "--case-root" in command and "--project-root" not in command:
        case_root = Path(command[command.index("--case-root") + 1])
        command.extend(("--project-root", str(case_root.parent)))
    environment = os.environ.copy()
    environment["AGENT_COUNCIL_TEST_FAIL_AFTER_BOUNDARY"] = boundary
    completed = subprocess.run([sys.executable, str(RUNTIME), *command], capture_output=True, text=True, check=False, env=environment)
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError:
        response = {"result": "invalid", "stdout": completed.stdout, "stderr": completed.stderr}
    return completed.returncode, response, completed.stderr


def event_inventory(case_root: Path) -> dict[str, str]:
    events_root = case_root / "events"
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(events_root.glob("*.json"))}


def structural_refusal(response: dict[str, Any], code: str) -> bool:
    return response.get("result") == "refused" and response.get("code") == code and response.get("assurance") == "structural_only" and response.get("provider_execution_attested") is False and response.get("uat_authority") is False


def filesystem_inventory(case_root: Path) -> dict[str, str]:
    return {str(path.relative_to(case_root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(path for path in case_root.rglob("*") if path.is_file())}


def mutable_case_inventory(case_root: Path) -> dict[str, str]:
    tracked = [case_root / "case.json", case_root / "runtime-descriptor.json", case_root / "executing-bundle.json"]
    for directory in ("events", "evidence", "requests"):
        root = case_root / directory
        if root.is_dir(): tracked.extend(path for path in root.rglob("*") if path.is_file())
    return {str(path.relative_to(case_root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(path for path in tracked if path.is_file())}


def complete_r2_cycle(case_root: Path, label: str) -> tuple[bool, dict[str, Any]]:
    """Drive a complete, candidate-bound R2 cycle through public commands."""
    state = json.loads((case_root / "case.json").read_text(encoding="utf-8"))
    candidate, cycle_id, evidence_id = state["engineering_candidate"], state["cycle_id"], f"evidence-{label}"
    outcomes: list[bool] = []

    def invoke(*args: str) -> dict[str, Any]:
        code, response = cli(*args)
        outcomes.append(code == 0)
        return response

    invoke("evidence-add", "--case-root", str(case_root), "--evidence-id", evidence_id, "--evidence-kind", "behavioral_test", "--content-json", json.dumps(behavioral_evidence(candidate, f"test-{label}", cycle_id)))
    for decision_kind in ("routing", "design"):
        context_id = f"context-{label}-{decision_kind}"
        invoke("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-6-astra", "--efforts-json", '["high"]', "--context-id", context_id)
        plan = invoke("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", context_id, "--decision-kind", decision_kind)
        invoke("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", plan.get("plan_nonce", ""), "--task-id", f"task-{label}-{decision_kind}", "--model-id", "gpt-6-astra", "--effort", "high", "--context-id", context_id, "--output-ref", f"output-{label}-{decision_kind}", "--decision-kind", decision_kind)
    implementation_context = f"context-{label}-implementation"
    invoke("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-5.6-terra", "--efforts-json", '["high"]', "--context-id", implementation_context)
    implementation_plan = invoke("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "technical_tactical_intelligence", "--context-id", implementation_context)
    invoke("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", implementation_plan.get("plan_nonce", ""), "--task-id", f"task-{label}-implementation", "--model-id", "gpt-5.6-terra", "--effort", "high", "--context-id", implementation_context, "--output-ref", f"output-{label}-implementation")
    invoke("packet-result", "--case-root", str(case_root), "--packet-id", implementation_plan.get("packet_id", ""), "--status", "completed", "--checks-json", '[{"gate_id":"implementation","status":"passed"}]')
    invoke("test-record", "--case-root", str(case_root), "--run-id", f"test-{label}", "--evidence-id", evidence_id)
    review_context = f"context-{label}-review"
    invoke("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-5.6-sol", "--efforts-json", '["high"]', "--context-id", review_context)
    review_plan = invoke("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "operational_intelligence", "--context-id", review_context, "--decision-kind", "review")
    invoke("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", review_plan.get("plan_nonce", ""), "--task-id", f"task-{label}-review", "--model-id", "gpt-5.6-sol", "--effort", "high", "--context-id", review_context, "--output-ref", f"output-{label}-review", "--decision-kind", "review")
    invoke("review-record", "--case-root", str(case_root), "--review-id", "independent-review", "--reviewer-id", f"task-{label}-review", "--implementation-id", f"task-{label}-implementation", "--evidence-id", evidence_id)
    final_context = f"context-{label}-final"
    invoke("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-6-astra", "--efforts-json", '["high"]', "--context-id", final_context)
    final_plan = invoke("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", final_context, "--decision-kind", "final")
    invoke("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", final_plan.get("plan_nonce", ""), "--task-id", f"task-{label}-final", "--model-id", "gpt-6-astra", "--effort", "high", "--context-id", final_context, "--output-ref", f"output-{label}-final", "--decision-kind", "final")
    for gate_id in ("ultimate-routing", "ultimate-design", "implementation-verification", "ultimate-final-disposition"):
        invoke("gate", "--case-root", str(case_root), "--gate-id", gate_id, "--evidence-id", evidence_id)
    closed = invoke("close-case", "--case-root", str(case_root))
    return all(outcomes) and closed.get("code") == "CASE_CLOSED", closed


def prepare_pending_routing_plan(case_root: Path, label: str) -> tuple[bool, dict[str, str], dict[str, Any]]:
    candidate = {key: token(f"{label}-{key}") for key in ("source_sha256", "package_sha256", "dependency_lock_sha256", "harness_sha256")}
    init_code, _ = cli("init-case", "--case-root", str(case_root), "--case-id", f"case-{label}", "--route", "R2", "--candidate-json", json.dumps(candidate))
    context_id = f"context-{label}-routing"
    capability_code, _ = cli("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-6-astra", "--efforts-json", '["high"]', "--context-id", context_id)
    plan_code, plan = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", context_id, "--decision-kind", "routing")
    return init_code == capability_code == plan_code == 0 and bool(plan.get("plan_nonce")), candidate, plan


def test_stale_dispatch_plans() -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []
    for transition in ("candidate-change", "cycle-only"):
        with tempfile.TemporaryDirectory(prefix=f"agent-council-v2-stale-{transition}-") as temporary:
            case_root = Path(temporary) / "case-stale-plan"
            native = transition == "candidate-change"
            purpose = "native_forward" if native else "routing"
            run_args = ["--qualification-run-id", "native-forward-run-1"] if native else []
            init_args = ["--route", "R3", "--activation-class", "council_qualification", "--case-kind", "council_qualification"] if native else ["--route", "R2"]
            init_code, _ = cli("init-case", "--case-root", str(case_root), "--case-id", "case-stale-plan", *init_args)
            cap_code, _ = cli("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-6-astra", "--efforts-json", '["high"]', "--context-id", "context-original")
            # The routing case also preserves the default-ultimate-purpose compatibility contract.
            purpose_args = ["--decision-kind", purpose] if native else []
            plan_code, plan = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", "context-original", *purpose_args, *run_args)
            setup_ok = init_code == cap_code == plan_code == 0 and bool(plan.get("plan_nonce")) and plan.get("decision_kind") == purpose and (not native or plan.get("qualification_run_id") == "native-forward-run-1")
            rows.append((f"stale-plan-{transition}-setup", setup_ok, "create an exact purpose-bound plan in the original cycle"))
            if not setup_ok:
                continue
            original_state = json.loads((case_root / "case.json").read_text(encoding="utf-8"))
            if native:
                candidate = {key: token(f"{transition}-{key}") for key in ("source_sha256", "package_sha256", "dependency_lock_sha256", "harness_sha256")}
                boundary_code, _ = cli("cycle-start", "--case-root", str(case_root), "--candidate-json", json.dumps(candidate))
            else:
                interruption_code, interruption = cli("interrupt", "--case-root", str(case_root), "--processes-json", '[]')
                boundary_code, _ = cli("resume", "--case-root", str(case_root), "--interruption-id", interruption.get("interruption_id", "missing"))
                boundary_code = boundary_code or interruption_code
            before_capture = (case_root / "case.json").read_bytes()
            transitioned = json.loads(before_capture)
            candidate_changed = transitioned["engineering_candidate"]["candidate_id"] != original_state["engineering_candidate"]["candidate_id"]
            boundary_ok = boundary_code == 0 and transitioned["cycle_id"] != original_state["cycle_id"] and candidate_changed == native
            rows.append((f"stale-plan-{transition}-boundary", boundary_ok, "advance the cycle with exactly the intended candidate identity change"))
            event_names = {path.name for path in (case_root / "events").iterdir()}
            capture_code, capture = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", plan["plan_nonce"], "--task-id", "task-original-output", "--model-id", "gpt-6-astra", "--effort", "high", "--context-id", "context-original", "--output-ref", "original-candidate-output", "--decision-kind", purpose, *run_args)
            unchanged = (case_root / "case.json").read_bytes() == before_capture and {path.name for path in (case_root / "events").iterdir()} == event_names
            rows.append((f"stale-plan-{transition}-refused", boundary_ok and capture_code != 0 and capture.get("code") == "DISPATCH_PLAN_STALE" and unchanged, "stale capture refuses without consuming its nonce or writing current-cycle authority"))
    return rows


def test_public_cli_boundaries() -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory(prefix="agent-council-v2-cli-boundaries-") as temporary:
        root = Path(temporary)
        for label, candidate_json in (
            ("empty-object", "{}"),
            ("null", "null"),
            ("empty-list", "[]"),
            ("zero", "0"),
            ("false", "false"),
            ("empty-string", '\"\"'),
            ("true", "true"),
            ("one", "1"),
            ("arbitrary-string", json.dumps("not-a-candidate")),
            ("arbitrary-list", json.dumps(["not-a-candidate"])),
        ):
            invalid_root = root / f"case-invalid-candidate-{label}"
            invalid_code, invalid, invalid_stderr = cli_detail("init-case", "--case-root", str(invalid_root), "--case-id", f"case-invalid-candidate-{label}", "--route", "R2", "--candidate-json", candidate_json)
            structured = invalid.get("result") == "refused" and invalid.get("code") == "SCHEMA_VALIDATION_FAILED"
            no_traceback = "Traceback" not in invalid_stderr and "Traceback" not in invalid.get("stdout", "")
            rows.append((f"init-invalid-candidate-{label}-refused-before-root", invalid_code != 0 and structured and no_traceback and not invalid_root.exists(), "every non-object or incomplete candidate JSON value fails structurally before creating a partial case root"))

        default_root = root / "case-default-candidate"
        default_code, default, default_stderr = cli_detail("init-case", "--case-root", str(default_root), "--case-id", "case-default-candidate", "--route", "R2")
        default_candidate = default.get("state", {}).get("engineering_candidate", {})
        rows.append(("init-omitted-candidate-uses-defaults", default_code == 0 and default.get("result") == "accepted" and not default_stderr and default_root.is_dir() and all(isinstance(default_candidate.get(key), str) and len(default_candidate[key]) == 64 for key in ("source_sha256", "package_sha256", "dependency_lock_sha256", "harness_sha256")), "omitting candidate JSON alone initializes the pinned default engineering candidate"))

        security_root = root / "case-recursive-secret-refusal"
        security_init_code, _ = cli("init-case", "--case-root", str(security_root), "--case-id", "case-recursive-secret-refusal", "--route", "R2")
        for command, field in (("interrupt", "password"), ("interrupt", "secret"), ("interrupt", "api_key"), ("append", "password"), ("append", "secret"), ("append", "api_key")):
            state_before = (security_root / "case.json").read_bytes() if security_init_code == 0 else b""
            events_before = event_inventory(security_root) if security_init_code == 0 else {}
            nested_payload = {"outer": [{"middle": {"inner": {field: "not-permitted"}}}]}
            if command == "interrupt":
                refusal_code, refusal, refusal_stderr = cli_detail("interrupt", "--case-root", str(security_root), "--processes-json", json.dumps([nested_payload]))
            else:
                refusal_code, refusal, refusal_stderr = cli_detail("append", "--case-root", str(security_root), "--record-type", "packet", "--payload-json", json.dumps(nested_payload))
            unchanged = security_init_code == 0 and (security_root / "case.json").read_bytes() == state_before and event_inventory(security_root) == events_before
            structured = refusal.get("result") == "refused" and refusal.get("code") == "SECRET_REFUSED"
            no_traceback = "Traceback" not in refusal_stderr and "Traceback" not in refusal.get("stdout", "")
            rows.append((f"{command}-recursive-{field}-refused-before-write", refusal_code != 0 and structured and no_traceback and unchanged, "recursively nested secret-bearing public payloads refuse before case state or immutable event inventory changes"))

        state_before_secret_value = (security_root / "case.json").read_bytes() if security_init_code == 0 else b""
        events_before_secret_value = event_inventory(security_root) if security_init_code == 0 else {}
        secret_evidence = behavioral_evidence(json.loads(state_before_secret_value.decode("utf-8"))["engineering_candidate"], "secret-value", "cycle-000001") if state_before_secret_value else {}
        secret_evidence["assertion"]["expected"] = "api_key=" + "sk" + "_live_" + "0123456789abcdefghijklmnop"
        secret_value_code, secret_value, secret_value_stderr = cli_detail("evidence-add", "--case-root", str(security_root), "--evidence-id", "evidence-secret-value", "--evidence-kind", "behavioral_test", "--content-json", json.dumps(secret_evidence))
        rows.append(("evidence-recursive-secret-like-value-refused-before-write", secret_value_code != 0 and secret_value.get("code") == "SECRET_REFUSED" and "Traceback" not in secret_value_stderr and (security_root / "case.json").read_bytes() == state_before_secret_value and event_inventory(security_root) == events_before_secret_value, "secret-shaped values in otherwise allowed evidence fields refuse before state or event mutation"))
        dash_secret_evidence = behavioral_evidence(json.loads(state_before_secret_value.decode("utf-8"))["engineering_candidate"], "dash-secret-value", "cycle-000001") if state_before_secret_value else {}
        dash_secret_evidence["assertion"]["expected"] = "token=" + "sk" + "-proj-" + "0123456789abcdefghijklmnop"
        dash_secret_code, dash_secret, dash_secret_stderr = cli_detail("evidence-add", "--case-root", str(security_root), "--evidence-id", "evidence-dash-secret-value", "--evidence-kind", "behavioral_test", "--content-json", json.dumps(dash_secret_evidence))
        rows.append(("evidence-dash-form-secret-value-refused-before-write", dash_secret_code != 0 and dash_secret.get("code") == "SECRET_REFUSED" and "Traceback" not in dash_secret_stderr and (security_root / "case.json").read_bytes() == state_before_secret_value and event_inventory(security_root) == events_before_secret_value, "dash-form secret-shaped values refuse before state or event mutation"))

        project_boundary = root / "declared-project"
        project_boundary.mkdir()
        outside_root = root / "outside-case"
        boundary_code, boundary_refusal, boundary_stderr = cli_detail("init-case", "--case-root", str(outside_root), "--project-root", str(project_boundary), "--case-id", "case-outside-boundary", "--route", "R1")
        symlink_target = root / "outside-symlink-target"
        symlink_target.mkdir()
        symlink_path = project_boundary / "escaped-link"
        symlink_path.symlink_to(symlink_target, target_is_directory=True)
        symlink_case_root = symlink_path / "case-through-link"
        symlink_code, symlink_refusal, symlink_stderr = cli_detail("init-case", "--case-root", str(symlink_case_root), "--project-root", str(project_boundary), "--case-id", "case-symlink-escape", "--route", "R1")
        rows.append(("case-root-declared-boundary-and-symlink-escape-refused", boundary_code != 0 and boundary_refusal.get("code") == "CASE_ROOT_OUTSIDE_PROJECT_BOUNDARY" and symlink_code != 0 and symlink_refusal.get("code") == "CASE_ROOT_OUTSIDE_PROJECT_BOUNDARY" and "Traceback" not in boundary_stderr and "Traceback" not in symlink_stderr and not outside_root.exists() and not (symlink_target / "case-through-link").exists(), "case roots outside the declared project or through a symlink escape are refused before filesystem mutation"))
        safe_case_root = project_boundary / "case-safe-path"
        safe_init_code, _ = cli("init-case", "--case-root", str(safe_case_root), "--project-root", str(project_boundary), "--case-id", "case-safe-path", "--route", "R1")
        mismatch_code, mismatch, mismatch_stderr = cli_detail("capability-capture", "--case-root", str(safe_case_root), "--project-root", str(root), "--provider", "codex", "--model-id", "gpt-6-astra", "--efforts-json", '["high"]', "--context-id", "context-project-root-mismatch")
        outside_evidence = root / "outside-evidence"
        outside_evidence.mkdir()
        (safe_case_root / "evidence").symlink_to(outside_evidence, target_is_directory=True)
        symlink_state_before = (safe_case_root / "case.json").read_bytes() if safe_init_code == 0 else b""
        child_symlink_code, child_symlink, child_symlink_stderr = cli_detail("evidence-add", "--case-root", str(safe_case_root), "--project-root", str(project_boundary), "--evidence-id", "evidence-child-symlink", "--evidence-kind", "behavioral_test", "--content-json", json.dumps(behavioral_evidence(json.loads(symlink_state_before.decode("utf-8"))["engineering_candidate"], "child-symlink", "cycle-000001")) if symlink_state_before else "{}")
        rows.append(("pinned-project-boundary-and-child-symlink-refused", safe_init_code == 0 and mismatch_code != 0 and mismatch.get("code") == "PROJECT_ROOT_MISMATCH" and child_symlink_code != 0 and child_symlink.get("code") == "CASE_PATH_SYMLINK_REFUSED" and "Traceback" not in mismatch_stderr and "Traceback" not in child_symlink_stderr and (safe_case_root / "case.json").read_bytes() == symlink_state_before and not any(outside_evidence.iterdir()), "later mutations require the pinned project boundary and refuse a child symlink before outside writes"))

        resume_root = root / "case-repeat-resume"
        resume_init_code, _ = cli("init-case", "--case-root", str(resume_root), "--case-id", "case-repeat-resume", "--route", "R2")
        interruption_code, interruption = cli("interrupt", "--case-root", str(resume_root), "--processes-json", '[{"identity":"resume-process","status":"reconciled"}]')
        first_resume_code, first_resume = cli("resume", "--case-root", str(resume_root), "--interruption-id", interruption.get("interruption_id", "missing"))
        capability_code, _ = cli("capability-capture", "--case-root", str(resume_root), "--provider", "codex", "--model-id", "gpt-6-astra", "--efforts-json", '["high"]', "--context-id", "context-repeat-resume")
        plan_code, pending_plan = cli("dispatch-plan", "--case-root", str(resume_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", "context-repeat-resume", "--decision-kind", "routing")
        pending_nonce = pending_plan.get("plan_nonce", "")
        state_before_repeat = (resume_root / "case.json").read_bytes() if all(code == 0 for code in (resume_init_code, interruption_code, first_resume_code, capability_code, plan_code)) else b""
        events_before_repeat = event_inventory(resume_root) if state_before_repeat else {}
        repeat_state_before = json.loads(state_before_repeat) if state_before_repeat else {}
        repeat_cycle = repeat_state_before.get("cycle_id")
        pending_plan_state = repeat_state_before.get("dispatch_plans", {}).get(pending_nonce)
        repeat_code, repeated, repeat_stderr = cli_detail("resume", "--case-root", str(resume_root), "--interruption-id", interruption.get("interruption_id", "missing"))
        state_after_repeat = (resume_root / "case.json").read_bytes() if state_before_repeat else b""
        events_after_repeat = event_inventory(resume_root) if state_before_repeat else {}
        repeat_state = json.loads(state_after_repeat) if state_after_repeat else {}
        plan_preserved = repeat_state.get("dispatch_plans", {}).get(pending_nonce) == pending_plan_state and not repeat_state.get("dispatch_plans", {}).get(pending_nonce, {}).get("invalidated", False)
        no_repeat_traceback = "Traceback" not in repeat_stderr and "Traceback" not in repeated.get("stdout", "")
        rows.append(("repeat-resume-refuses-atomically-with-pending-plan", repeat_code != 0 and repeated.get("result") == "refused" and repeated.get("code") == "RESUMPTION_DUPLICATE" and no_repeat_traceback and state_after_repeat == state_before_repeat and events_after_repeat == events_before_repeat and repeat_state.get("cycle_id") == repeat_cycle and plan_preserved, "a consumed interruption cannot advance the cycle, mutate immutable events, or invalidate a pending current-cycle plan"))
        capture_code, captured = cli("dispatch-capture", "--case-root", str(resume_root), "--provider", "codex", "--plan-nonce", pending_nonce, "--task-id", "task-repeat-resume-routing", "--model-id", "gpt-6-astra", "--effort", "high", "--context-id", "context-repeat-resume", "--output-ref", "output-repeat-resume-routing", "--decision-kind", "routing")
        rows.append(("repeat-resume-leaves-pending-plan-usable", capture_code == 0 and captured.get("result") == "accepted" and captured.get("code") == "DISPATCH_CAPTURED", "the unchanged pending plan remains single-use and capturable after the duplicate resume refusal"))

        concurrent_root = root / "case-concurrent-resume"
        concurrent_init_code, _ = cli("init-case", "--case-root", str(concurrent_root), "--case-id", "case-concurrent-resume", "--route", "R2")
        concurrent_interrupt_code, concurrent_interruption = cli("interrupt", "--case-root", str(concurrent_root), "--processes-json", '[{"identity":"concurrent-resume-process","status":"reconciled"}]')
        concurrent_command = [sys.executable, str(RUNTIME), "resume", "--case-root", str(concurrent_root), "--project-root", str(concurrent_root.parent), "--interruption-id", concurrent_interruption.get("interruption_id", "missing")]
        concurrent_processes = [subprocess.Popen(concurrent_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        concurrent_results = []
        for process in concurrent_processes:
            stdout, stderr = process.communicate(timeout=30)
            try:
                response = json.loads(stdout)
            except json.JSONDecodeError:
                response = {"result": "invalid", "stdout": stdout}
            concurrent_results.append((process.returncode, response, stderr))
        concurrent_state = json.loads((concurrent_root / "case.json").read_text(encoding="utf-8")) if concurrent_init_code == concurrent_interrupt_code == 0 else {}
        concurrent_resumptions = [event for event in concurrent_state.get("events", []) if event.get("record_type") == "resumption"]
        concurrent_new_cycle = [event for event in concurrent_state.get("events", []) if event.get("cycle_id") == "cycle-000002"]
        accepted = [result for result in concurrent_results if result[0] == 0 and result[1].get("code") == "INTERRUPTION_RESUMED"]
        refused = [result for result in concurrent_results if result[0] != 0 and result[1].get("result") == "refused" and result[1].get("code") == "RESUMPTION_DUPLICATE" and "Traceback" not in result[2] and "Traceback" not in result[1].get("stdout", "")]
        rows.append(("concurrent-resume-single-transition-atomic", concurrent_init_code == concurrent_interrupt_code == 0 and len(accepted) == len(refused) == 1 and concurrent_state.get("cycle_id") == "cycle-000002" and len(concurrent_resumptions) == 1 and {event.get("record_type") for event in concurrent_new_cycle} == {"case", "resumption"} and len(event_inventory(concurrent_root)) == len(concurrent_state.get("events", [])), "concurrent resume attempts serialize into exactly one new cycle and one immutable resumption event"))

        capture_root = root / "case-capture-output-refusal"
        capture_init_code, _ = cli("init-case", "--case-root", str(capture_root), "--case-id", "case-capture-output-refusal", "--route", "R2")
        capture_capability_code, _ = cli("capability-capture", "--case-root", str(capture_root), "--provider", "codex", "--model-id", "gpt-6-astra", "--efforts-json", '["high"]', "--context-id", "context-capture-output-refusal")
        capture_plan_code, capture_plan = cli("dispatch-plan", "--case-root", str(capture_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", "context-capture-output-refusal", "--decision-kind", "routing")
        capture_nonce = capture_plan.get("plan_nonce", "")
        capture_setup = capture_init_code == capture_capability_code == capture_plan_code == 0
        for label, output_ref in (("newline", "output\nref"), ("control", "output\x1fref"), ("empty", "")):
            capture_before = (capture_root / "case.json").read_bytes() if capture_setup else b""
            capture_events_before = event_inventory(capture_root) if capture_setup else {}
            request_before = (capture_root / "requests" / f"{capture_nonce}.json").read_bytes() if capture_setup else b""
            refusal_code, refusal, refusal_stderr = cli_detail("dispatch-capture", "--case-root", str(capture_root), "--provider", "codex", "--plan-nonce", capture_nonce, "--task-id", "task-capture-output-refusal", "--model-id", "gpt-6-astra", "--effort", "high", "--context-id", "context-capture-output-refusal", "--output-ref", output_ref, "--decision-kind", "routing")
            capture_after = (capture_root / "case.json").read_bytes() if capture_setup else b""
            capture_state = json.loads(capture_after) if capture_after else {}
            unchanged = capture_setup and capture_after == capture_before and event_inventory(capture_root) == capture_events_before and (capture_root / "requests" / f"{capture_nonce}.json").read_bytes() == request_before
            plan_unconsumed = capture_state.get("dispatch_plans", {}).get(capture_nonce, {}).get("consumed") is False
            rows.append((f"dispatch-capture-{label}-output-ref-refused-atomically", refusal_code != 0 and structural_refusal(refusal, "SCHEMA_VALIDATION_FAILED") and "Traceback" not in refusal_stderr and "Traceback" not in refusal.get("stdout", "") and unchanged and plan_unconsumed and not capture_state.get("dispatch_receipts"), "malformed public output references refuse before consuming a plan, creating a receipt, or changing any case bytes"))
        retry_code, retried = cli("dispatch-capture", "--case-root", str(capture_root), "--provider", "codex", "--plan-nonce", capture_nonce, "--task-id", "task-capture-output-retry", "--model-id", "gpt-6-astra", "--effort", "high", "--context-id", "context-capture-output-refusal", "--output-ref", "output-capture-retry", "--decision-kind", "routing")
        rows.append(("dispatch-capture-valid-retry-after-output-refusal", capture_setup and retry_code == 0 and retried.get("result") == "accepted" and retried.get("code") == "DISPATCH_CAPTURED", "a valid retry captures the original still-pending plan after every malformed output reference refusal"))

        malformed_interrupt_root = root / "case-malformed-interruption"
        malformed_interrupt_init_code, _ = cli("init-case", "--case-root", str(malformed_interrupt_root), "--case-id", "case-malformed-interruption", "--route", "R2")
        for label, processes_json in (("missing-owned-process-status", '[{"identity":"missing-status"}]'), ("null-owned-processes", "null"), ("invalid-owned-process-status", '[{"identity":"invalid-status","status":"not-a-status"}]')):
            interrupt_before = (malformed_interrupt_root / "case.json").read_bytes() if malformed_interrupt_init_code == 0 else b""
            interrupt_events_before = event_inventory(malformed_interrupt_root) if interrupt_before else {}
            refusal_code, refusal, refusal_stderr = cli_detail("interrupt", "--case-root", str(malformed_interrupt_root), "--processes-json", processes_json)
            resume_code, resume, resume_stderr = cli_detail("resume", "--case-root", str(malformed_interrupt_root), "--interruption-id", "interruption-missing")
            interrupt_after = (malformed_interrupt_root / "case.json").read_bytes() if interrupt_before else b""
            unchanged = malformed_interrupt_init_code == 0 and interrupt_after == interrupt_before and event_inventory(malformed_interrupt_root) == interrupt_events_before
            rows.append((f"interrupt-{label}-refuses-and-cannot-resume", refusal_code != 0 and structural_refusal(refusal, "SCHEMA_VALIDATION_FAILED") and resume_code != 0 and structural_refusal(resume, "INTERRUPTION_UNRESOLVED") and "Traceback" not in refusal_stderr + resume_stderr and "Traceback" not in refusal.get("stdout", "") + resume.get("stdout", "") and unchanged, "missing, null, or invalid owned-process records do not create resumable interruption state"))

        for label, activation_class in (("empty", ""), ("invalid", "not-an-activation-class")):
            activation_root = root / f"case-invalid-activation-{label}"
            activation_code, activation, activation_stderr = cli_detail("init-case", "--case-root", str(activation_root), "--case-id", f"case-invalid-activation-{label}", "--route", "R2", "--activation-class", activation_class)
            rows.append((f"init-explicit-{label}-activation-class-refuses-before-root", activation_code != 0 and structural_refusal(activation, "SCHEMA_VALIDATION_FAILED") and "Traceback" not in activation_stderr and "Traceback" not in activation.get("stdout", "") and not activation_root.exists(), "an explicit empty or unknown activation class is distinct from omission and cannot create a case root"))

        before_request_root = root / "case-packet-before-request"
        before_request_init_code, _ = cli("init-case", "--case-root", str(before_request_root), "--case-id", "case-packet-before-request", "--route", "R2")
        before_request_state = (before_request_root / "case.json").read_bytes() if before_request_init_code == 0 else b""
        before_request_events = event_inventory(before_request_root) if before_request_state else {}
        before_request_code, before_request = cli("packet-result", "--case-root", str(before_request_root), "--packet-id", "packet-before-request", "--status", "completed", "--checks-json", '[{"gate_id":"packet-check","status":"passed"}]')
        rows.append(("packet-result-before-request-refuses-atomically", before_request_init_code == 0 and before_request_code != 0 and structural_refusal(before_request, "PACKET_NOT_ACTIONABLE") and (before_request_root / "case.json").read_bytes() == before_request_state and event_inventory(before_request_root) == before_request_events, "a result cannot appear without an exact preceding request"))

        packet_root = root / "case-packet-order"
        packet_init_code, _ = cli("init-case", "--case-root", str(packet_root), "--case-id", "case-packet-order", "--route", "R2")
        routing_capability_code, _ = cli("capability-capture", "--case-root", str(packet_root), "--provider", "codex", "--model-id", "gpt-6-astra", "--efforts-json", '["high"]', "--context-id", "context-packet-routing")
        routing_plan_code, routing_plan = cli("dispatch-plan", "--case-root", str(packet_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", "context-packet-routing", "--decision-kind", "routing")
        routing_capture_code, _ = cli("dispatch-capture", "--case-root", str(packet_root), "--provider", "codex", "--plan-nonce", routing_plan.get("plan_nonce", ""), "--task-id", "task-packet-routing", "--model-id", "gpt-6-astra", "--effort", "high", "--context-id", "context-packet-routing", "--output-ref", "output-packet-routing", "--decision-kind", "routing")
        design_capability_code, _ = cli("capability-capture", "--case-root", str(packet_root), "--provider", "codex", "--model-id", "gpt-6-astra", "--efforts-json", '["high"]', "--context-id", "context-packet-design")
        design_plan_code, design_plan = cli("dispatch-plan", "--case-root", str(packet_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", "context-packet-design", "--decision-kind", "design")
        design_capture_code, _ = cli("dispatch-capture", "--case-root", str(packet_root), "--provider", "codex", "--plan-nonce", design_plan.get("plan_nonce", ""), "--task-id", "task-packet-design", "--model-id", "gpt-6-astra", "--effort", "high", "--context-id", "context-packet-design", "--output-ref", "output-packet-design", "--decision-kind", "design")
        implementation_capability_code, _ = cli("capability-capture", "--case-root", str(packet_root), "--provider", "codex", "--model-id", "gpt-5.6-terra", "--efforts-json", '["high"]', "--context-id", "context-packet-implementation")
        implementation_plan_code, implementation_plan = cli("dispatch-plan", "--case-root", str(packet_root), "--provider", "codex", "--role", "technical_tactical_intelligence", "--context-id", "context-packet-implementation")
        packet_id = implementation_plan.get("packet_id", "missing")
        packet_setup = all(code == 0 for code in (packet_init_code, routing_capability_code, routing_plan_code, routing_capture_code, design_capability_code, design_plan_code, design_capture_code, implementation_capability_code, implementation_plan_code))
        packet_before = (packet_root / "case.json").read_bytes() if packet_setup else b""
        packet_events_before = event_inventory(packet_root) if packet_before else {}
        before_implementation_code, before_implementation = cli("packet-result", "--case-root", str(packet_root), "--packet-id", packet_id, "--status", "completed", "--checks-json", '[{"gate_id":"packet-check","status":"passed"}]')
        rows.append(("packet-result-before-implementation-refuses-atomically", packet_setup and before_implementation_code != 0 and structural_refusal(before_implementation, "PACKET_NOT_ACTIONABLE") and (packet_root / "case.json").read_bytes() == packet_before and event_inventory(packet_root) == packet_events_before, "an accepted request still requires its exact approved implementation dispatch before a result"))
        implementation_capture_code, _ = cli("dispatch-capture", "--case-root", str(packet_root), "--provider", "codex", "--plan-nonce", implementation_plan.get("plan_nonce", ""), "--task-id", "task-packet-implementation", "--model-id", "gpt-5.6-terra", "--effort", "high", "--context-id", "context-packet-implementation", "--output-ref", "output-packet-implementation")
        ordered_result_code, ordered_result = cli("packet-result", "--case-root", str(packet_root), "--packet-id", packet_id, "--status", "completed", "--checks-json", '[{"gate_id":"packet-check","status":"passed"}]')
        rows.append(("packet-result-requires-exact-request-dispatch-pairing", packet_setup and implementation_capture_code == ordered_result_code == 0 and ordered_result.get("result") == "accepted" and ordered_result.get("code") == "PACKET_RESULT_RECORDED", "only the planned packet's request, dispatch, and later result form a valid packet lifecycle"))

        exact_candidate = {key: token(f"exact-{key}") for key in ("source_sha256", "package_sha256", "dependency_lock_sha256", "harness_sha256")}
        exact_root = root / "case-exact-candidate"
        exact_code, exact = cli("init-case", "--case-root", str(exact_root), "--case-id", "case-exact-candidate", "--route", "R2", "--candidate-json", json.dumps(exact_candidate))
        exact_state = exact.get("state", {}).get("engineering_candidate", {})
        rows.append(("exact-candidate-init-still-works", exact_code == 0 and all(exact_state.get(key) == value for key, value in exact_candidate.items()), "public init preserves every caller-supplied candidate artifact hash"))

        manifest_root = root / "case-manifest-status"
        manifest_code, manifest = cli("init-case", "--case-root", str(manifest_root), "--case-id", "case-manifest-status", "--route", "R2")
        manifest_state = manifest.get("state", {})
        artifact_pins = manifest_state.get("policy_bundle", {}).get("artifact_pins", {})
        for policy_ref in ("lightweight-routing.yaml", "governed-workflow.yaml"):
            policy_path = "skills/agent-council/references/" + policy_ref
            changed_pins = dict(artifact_pins, **{policy_path: token("changed-" + policy_ref)})
            rows.append(("new-case-pins-" + policy_ref, policy_path in artifact_pins and digest(changed_pins) != digest(artifact_pins), "new cases bind route-specific policy bytes"))
        stable_before = manifest_state.get("engineering_candidate", {}).get("package_sha256")
        status_only_promotion = {"status": "promoted"}
        changed_manifest_pins = dict(artifact_pins)
        changed_manifest_pins[".codex-plugin/plugin.json"] = token("changed-plugin-manifest")
        stable_after = digest(artifact_pins)
        rows.append(("plugin-manifest-change-alters-behavioral-candidate-digest", manifest_code == 0 and ".codex-plugin/plugin.json" in artifact_pins and stable_before == stable_after and digest(changed_manifest_pins) != stable_after and status_only_promotion["status"] == "promoted", "plugin manifest bytes are part of the behavioral candidate digest while detached release status is not"))

        classification_root = root / "case-invalid-qualification-class"
        classification_code, classification = cli("init-case", "--case-root", str(classification_root), "--case-id", "case-invalid-qualification-class", "--route", "R3", "--activation-class", "council_qualification", "--case-kind", "operational_change")
        rows.append(("qualification-activation-cannot-use-operational-kind", classification_code != 0 and classification.get("code") == "SCHEMA_VALIDATION_FAILED", "public init refuses council qualification labelled as an operational change"))

        metadata_root = root / "case-wrapped-capability"
        metadata_init_code, metadata_init = cli("init-case", "--case-root", str(metadata_root), "--case-id", "case-wrapped-capability", "--route", "R2")
        metadata_state = metadata_init.get("state", {})
        metadata_candidate = metadata_state.get("engineering_candidate", {})
        wrapped_capability = behavioral_evidence(metadata_candidate, "test-wrapped-capability", metadata_state.get("cycle_id", "")) | {"provider_capability_receipt": {"receipt_type": "provider_capability", "provider": "codex", "context_id": "context-local"}}
        metadata_evidence_code, metadata_evidence = cli("evidence-add", "--case-root", str(metadata_root), "--evidence-id", "evidence-wrapped-capability", "--evidence-kind", "behavioral_test", "--content-json", json.dumps(wrapped_capability))
        metadata_test_code, metadata_test = cli("test-record", "--case-root", str(metadata_root), "--run-id", "test-wrapped-capability", "--evidence-id", "evidence-wrapped-capability")
        rows.append(("wrapped-capability-is-not-cli-behavioral-evidence", metadata_init_code == 0 and metadata_evidence_code != 0 and metadata_evidence.get("code") == "SCHEMA_VALIDATION_FAILED" and metadata_test_code != 0 and metadata_test.get("code") == "REQUIRED_GATE_EVIDENCE_MISSING", "a wrapped capability receipt is refused at ingestion and cannot become a passing behavioral test"))

        transition_root = root / "case-transition-metadata"
        transition_init_code, _ = cli("init-case", "--case-root", str(transition_root), "--case-id", "case-transition-metadata", "--route", "R2")
        changed_candidate = {key: token(f"transition-{key}") for key in ("source_sha256", "package_sha256", "dependency_lock_sha256", "harness_sha256")}
        transition_code, transition = cli("cycle-start", "--case-root", str(transition_root), "--candidate-json", json.dumps(changed_candidate))
        transition_evidence_id = f"candidate-transition-{transition.get('cycle_id', 'missing')}"
        transition_test_code, transition_test = cli("test-record", "--case-root", str(transition_root), "--run-id", "test-transition-metadata", "--evidence-id", transition_evidence_id)
        rows.append(("candidate-transition-is-not-cli-behavioral-evidence", transition_init_code == transition_code == 0 and transition_test_code != 0 and transition_test.get("code") == "REQUIRED_GATE_EVIDENCE_MISSING", "candidate-transition metadata cannot be promoted into a passing behavioral test"))

        qualification_root = root / "case-qualification-native-gates"
        qualification_init_code, _ = cli("init-case", "--case-root", str(qualification_root), "--case-id", "case-qualification-native-gates", "--route", "R3", "--activation-class", "council_qualification", "--case-kind", "council_qualification")
        qualification_close_code, qualification_close = cli("close-case", "--case-root", str(qualification_root))
        rows.append(("qualification-cli-close-requires-native-gates", qualification_init_code == 0 and qualification_close_code != 0 and qualification_close.get("code") == "NATIVE_FORWARD_RUNS_INSUFFICIENT", "public close reports missing qualification native gates before closure"))

        for case_name, expected_code in (
            ("qualification_evidence_candidate_payload_tamper", "CANDIDATE_EVIDENCE_MISMATCH"),
            ("qualification_evidence_cycle_payload_tamper", "CANDIDATE_EVIDENCE_MISMATCH"),
            ("qualification_non_normative_failed_gate", "UNRESOLVED_GATE_FAILURE"),
            ("qualification_native_gate_status_missing", "REQUIRED_GATE_EVIDENCE_MISSING"),
            ("qualification_normative_route_gate_status_missing", "REQUIRED_GATE_EVIDENCE_MISSING"),
            ("authority_dispatch_output_ref_missing", "SCHEMA_VALIDATION_FAILED"),
            ("authority_dispatch_output_ref_null", "SCHEMA_VALIDATION_FAILED"),
            ("authority_dispatch_output_ref_object", "SCHEMA_VALIDATION_FAILED"),
            ("authority_dispatch_output_ref_control", "CONTROL_CHARACTER_REFUSED"),
            ("authority_dispatch_capability_models_null", "AUTHORITY_DISPATCH_INVALID"),
            ("object_stage", "SCHEMA_VALIDATION_FAILED"),
            ("object_decision_kind", "PACKET_NOT_ACTIONABLE"),
            ("object_evidence_id", "CANDIDATE_EVIDENCE_MISMATCH"),
            ("object_provider", "SCHEMA_VALIDATION_FAILED"),
            ("packet_result_before_request", "PACKET_NOT_ACTIONABLE"),
            ("packet_result_before_implementation", "PACKET_NOT_ACTIONABLE"),
            ("packet_result_pair_mismatch", "PACKET_RESULT_CONFLICT"),
        ):
            document = write_case(case_name, root)
            evaluate_code, evaluated, evaluate_stderr = cli_detail("evaluate", str(Path(document["case_root"]) / "case.json"))
            rows.append((f"{case_name}-public-evaluate", evaluate_code != 0 and structural_refusal(evaluated, expected_code) and "Traceback" not in evaluate_stderr and "Traceback" not in evaluated.get("stdout", ""), f"public evaluate returns a structured structural-only refusal with {expected_code}"))
    return rows


def test_public_cli_multi_cycle_transitions() -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory(prefix="agent-council-v2-multi-cycle-") as temporary:
        case_root = Path(temporary) / "case-multi-cycle"
        initial_candidate = {key: token(f"multi-cycle-initial-{key}") for key in ("source_sha256", "package_sha256", "dependency_lock_sha256", "harness_sha256")}
        init_code, init = cli("init-case", "--case-root", str(case_root), "--case-id", "case-multi-cycle", "--route", "R2", "--candidate-json", json.dumps(initial_candidate))
        if init_code != 0:
            return [("two-candidate-transitions-fresh-r2-history", False, "initialize a multi-cycle public case"), ("three-candidate-transitions-fresh-r2-history", False, "initialize a multi-cycle public case"), ("multi-cycle-stale-evidence-refused", False, "initialize a multi-cycle public case")]
        initial_complete, initial_closed = complete_r2_cycle(case_root, "multi-cycle-initial")
        candidate_ids = [init.get("state", {}).get("engineering_candidate", {}).get("candidate_id")]
        transition_rows: list[dict[str, Any]] = []
        for ordinal in range(1, 4):
            prior_candidate = json.loads((case_root / "case.json").read_text(encoding="utf-8"))["engineering_candidate"]
            next_candidate = {key: token(f"multi-cycle-{ordinal}-{key}") for key in ("source_sha256", "package_sha256", "dependency_lock_sha256", "harness_sha256")}
            transition_code, transition = cli("cycle-start", "--case-root", str(case_root), "--candidate-json", json.dumps(next_candidate))
            current_state = json.loads((case_root / "case.json").read_text(encoding="utf-8"))
            current_candidate = current_state["engineering_candidate"]
            candidate_ids.append(current_candidate.get("candidate_id"))
            before_stale_state = (case_root / "case.json").read_bytes()
            before_stale_inventory = mutable_case_inventory(case_root)
            stale_content = behavioral_evidence(prior_candidate, f"test-stale-transition-{ordinal}", current_state["cycle_id"])
            stale_code, stale, stale_stderr = cli_detail("evidence-add", "--case-root", str(case_root), "--evidence-id", f"evidence-stale-{ordinal}", "--evidence-kind", "behavioral_test", "--content-json", json.dumps(stale_content))
            stale_unchanged = (case_root / "case.json").read_bytes() == before_stale_state and mutable_case_inventory(case_root) == before_stale_inventory
            complete, closed = complete_r2_cycle(case_root, f"multi-cycle-{ordinal}")
            evaluate_code, evaluated, evaluate_stderr = cli_detail("evaluate", str(case_root / "case.json"))
            transition_rows.append({
                "transition": transition_code == 0 and transition.get("code") == "CYCLE_STARTED" and transition.get("cycle_id") == f"cycle-{ordinal + 1:06d}" and transition.get("candidate_id") == current_candidate.get("candidate_id"),
                "stale": stale_code != 0 and structural_refusal(stale, "SCHEMA_VALIDATION_FAILED") and "Traceback" not in stale_stderr and "Traceback" not in stale.get("stdout", "") and stale_unchanged,
                "complete": complete and closed.get("code") == "CASE_CLOSED",
                "evaluation": evaluate_code == 0 and evaluated.get("result") == "accepted" and evaluated.get("code") == "CANDIDATE_TRANSITION_ACCEPTED" and evaluated.get("assurance") == "structural_only" and evaluated.get("provider_execution_attested") is False and evaluated.get("uat_authority") is False and "Traceback" not in evaluate_stderr and "Traceback" not in evaluated.get("stdout", ""),
                "state": json.loads((case_root / "case.json").read_text(encoding="utf-8")),
            })

        def historical_links_valid(state: dict[str, Any], transition_count: int) -> bool:
            transitions = [event for event in state.get("events", []) if event.get("record_type") == "candidate_transition"]
            return len(transitions) == transition_count and all(event.get("cycle_id") == f"cycle-{index + 2:06d}" and event.get("candidate_id") == candidate_ids[index + 1] and event.get("payload", {}).get("prior_candidate_id") == candidate_ids[index] for index, event in enumerate(transitions))

        first_two = transition_rows[:2]
        rows.append(("two-candidate-transitions-fresh-r2-history", initial_complete and initial_closed.get("code") == "CASE_CLOSED" and all(all(item[key] for key in ("transition", "complete", "evaluation")) for item in first_two) and historical_links_valid(first_two[-1]["state"], 2), "two candidate transitions each produce a complete fresh R2 closure and evaluate their own historical identities"))
        rows.append(("three-candidate-transitions-fresh-r2-history", initial_complete and initial_closed.get("code") == "CASE_CLOSED" and all(all(item[key] for key in ("transition", "complete", "evaluation")) for item in transition_rows) and historical_links_valid(transition_rows[-1]["state"], 3), "three candidate transitions each produce a complete fresh R2 closure and evaluate their own historical identities"))
        rows.append(("multi-cycle-stale-evidence-refused", all(item["stale"] for item in transition_rows), "prior-candidate evidence refuses atomically in every fresh transition cycle"))
    return rows


def test_public_cli_evidence_id_boundary() -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory(prefix="agent-council-v2-evidence-id-") as temporary:
        case_root = Path(temporary) / "case-evidence-id"
        init_code, init = cli("init-case", "--case-root", str(case_root), "--case-id", "case-evidence-id", "--route", "R2")
        candidate = init.get("state", {}).get("engineering_candidate", {})
        cycle_id = init.get("state", {}).get("cycle_id", "")
        maximum_id = "e" * 128
        before_state = (case_root / "case.json").read_bytes() if init_code == 0 else b""
        before_inventory = mutable_case_inventory(case_root) if init_code == 0 else {}
        oversized_code, oversized, oversized_stderr = cli_detail("evidence-add", "--case-root", str(case_root), "--evidence-id", maximum_id, "--evidence-kind", "behavioral_test", "--content-json", json.dumps(behavioral_evidence(candidate, "test-maximum-evidence-id", cycle_id)))
        unchanged = init_code == 0 and (case_root / "case.json").read_bytes() == before_state and mutable_case_inventory(case_root) == before_inventory
        rows.append(("maximum-evidence-id-refuses-before-partial-write", init_code == 0 and oversized_code != 0 and structural_refusal(oversized, "SCHEMA_VALIDATION_FAILED") and "Traceback" not in oversized_stderr and "Traceback" not in oversized.get("stdout", "") and unchanged, "a valid 128-character evidence id whose prefixed immutable event id is too long refuses before evidence, event, or state changes"))
        clean_id = "evidence-clean-retry"
        retry_code, retry = cli("evidence-add", "--case-root", str(case_root), "--evidence-id", clean_id, "--evidence-kind", "behavioral_test", "--content-json", json.dumps(behavioral_evidence(candidate, "test-clean-evidence-id", cycle_id)))
        rows.append(("maximum-evidence-id-clean-retry-succeeds", init_code == 0 and retry_code == 0 and retry.get("result") == "accepted" and retry.get("code") == "EVIDENCE_ADDED" and (case_root / "evidence" / f"{clean_id}.json").is_file() and (case_root / "events" / f"{retry.get('event_id', 'missing')}.json").is_file(), "a clean shorter evidence id remains usable after the oversized-id refusal"))
    return rows


def test_public_evaluate_read_only() -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory(prefix="agent-council-v2-evaluate-read-only-") as temporary:
        root = Path(temporary)
        refused_root = root / "case-evaluate-refused"
        refused_init_code, _ = cli("init-case", "--case-root", str(refused_root), "--case-id", "case-evaluate-refused", "--route", "R2")
        refused_before = filesystem_inventory(refused_root) if refused_init_code == 0 else {}
        refused_code, refused, refused_stderr = cli_detail("evaluate", str(refused_root / "case.json"))
        refused_after = filesystem_inventory(refused_root) if refused_init_code == 0 else {}
        refused_artifacts_absent = not (refused_root / "runtime-descriptor.json").exists() and not (refused_root / "executing-bundle.json").exists()
        rows.append(("public-evaluate-refusal-is-read-only", refused_init_code == 0 and refused_code != 0 and structural_refusal(refused, "PACKET_RESULT_CONFLICT") and "Traceback" not in refused_stderr and "Traceback" not in refused.get("stdout", "") and refused_after == refused_before and refused_artifacts_absent, "evaluating an incomplete authoring case refuses without creating runtime artifacts or changing case filesystem bytes"))

        accepted_root = root / "case-evaluate-accepted"
        accepted_init_code, _ = cli("init-case", "--case-root", str(accepted_root), "--case-id", "case-evaluate-accepted", "--route", "R2")
        accepted_complete, _ = complete_r2_cycle(accepted_root, "evaluate-accepted") if accepted_init_code == 0 else (False, {})
        accepted_before = filesystem_inventory(accepted_root) if accepted_init_code == 0 else {}
        accepted_code, accepted, accepted_stderr = cli_detail("evaluate", str(accepted_root / "case.json"))
        accepted_after = filesystem_inventory(accepted_root) if accepted_init_code == 0 else {}
        accepted_artifacts_absent = not (accepted_root / "runtime-descriptor.json").exists() and not (accepted_root / "executing-bundle.json").exists()
        rows.append(("public-evaluate-acceptance-is-read-only", accepted_init_code == 0 and accepted_complete and accepted_code == 0 and accepted.get("result") == "accepted" and accepted.get("code") == "CASE_ACCEPTED" and accepted.get("assurance") == "structural_only" and accepted.get("provider_execution_attested") is False and accepted.get("uat_authority") is False and "Traceback" not in accepted_stderr and "Traceback" not in accepted.get("stdout", "") and accepted_after == accepted_before and accepted_artifacts_absent, "evaluating a complete authoring case accepts structurally without creating runtime artifacts or mutating case filesystem bytes"))
    return rows


def test_public_cycle_start_unchanged() -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory(prefix="agent-council-v2-cycle-unchanged-") as temporary:
        root = Path(temporary)
        preserved_root = root / "case-preserved-pending-plan"
        setup, candidate, plan = prepare_pending_routing_plan(preserved_root, "preserved-pending-plan")
        nonce = plan.get("plan_nonce", "")
        before = filesystem_inventory(preserved_root) if setup else {}
        before_state = json.loads((preserved_root / "case.json").read_text(encoding="utf-8")) if setup else {}
        pending_before = before_state.get("dispatch_plans", {}).get(nonce)
        refused_code, refused, refused_stderr = cli_detail("cycle-start", "--case-root", str(preserved_root), "--candidate-json", json.dumps(candidate))
        after = filesystem_inventory(preserved_root) if setup else {}
        after_state = json.loads((preserved_root / "case.json").read_text(encoding="utf-8")) if setup else {}
        pending_after = after_state.get("dispatch_plans", {}).get(nonce)
        capture_code, captured = cli("dispatch-capture", "--case-root", str(preserved_root), "--provider", "codex", "--plan-nonce", nonce, "--task-id", "task-preserved-pending-plan", "--model-id", plan.get("model_id", ""), "--effort", plan.get("effort", ""), "--context-id", plan.get("context_id", ""), "--output-ref", "output-preserved-pending-plan", "--decision-kind", plan.get("decision_kind", ""))
        rows.append(("cycle-start-unchanged-refuses-atomically-and-preserves-pending-plan", setup and refused_code != 0 and structural_refusal(refused, "CANDIDATE_UNCHANGED") and "Traceback" not in refused_stderr and "Traceback" not in refused.get("stdout", "") and after == before and pending_after == pending_before and pending_after is not None and pending_after.get("consumed") is False and not pending_after.get("invalidated", False) and capture_code == 0 and captured.get("code") == "DISPATCH_CAPTURED", "an unchanged four-hash candidate refuses before changing the lock, state, events, evidence, files, or a live plan"))

        changed_root = root / "case-changed-after-unchanged"
        changed_setup, unchanged_candidate, _ = prepare_pending_routing_plan(changed_root, "changed-after-unchanged")
        unchanged_code, unchanged, unchanged_stderr = cli_detail("cycle-start", "--case-root", str(changed_root), "--candidate-json", json.dumps(unchanged_candidate))
        changed_candidate = dict(unchanged_candidate, source_sha256=token("changed-after-unchanged-source"))
        changed_code, changed = cli("cycle-start", "--case-root", str(changed_root), "--candidate-json", json.dumps(changed_candidate))
        changed_state = json.loads((changed_root / "case.json").read_text(encoding="utf-8")) if changed_setup else {}
        rows.append(("cycle-start-genuinely-changed-succeeds-after-unchanged-refusal", changed_setup and unchanged_code != 0 and structural_refusal(unchanged, "CANDIDATE_UNCHANGED") and "Traceback" not in unchanged_stderr and "Traceback" not in unchanged.get("stdout", "") and changed_code == 0 and changed.get("result") == "accepted" and changed.get("code") == "CYCLE_STARTED" and changed.get("cycle_id") == "cycle-000002" and changed_state.get("engineering_candidate", {}).get("source_sha256") == changed_candidate["source_sha256"] and changed_state.get("engineering_candidate", {}).get("candidate_id") == changed.get("candidate_id"), "a materially changed candidate can start the next cycle immediately after an unchanged-candidate refusal"))
    return rows


def test_public_json_depth_guard() -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []
    depth = 1200
    deep_array = "[" * depth + "0" + "]" * depth
    deep_object = '{"nested":' * depth + "0" + "}" * depth

    def no_traceback(response: dict[str, Any], stderr: str) -> bool:
        return "Traceback" not in stderr and "Traceback" not in response.get("stdout", "")

    with tempfile.TemporaryDirectory(prefix="agent-council-v2-json-depth-") as temporary:
        root = Path(temporary)
        case_root = root / "case-deep-json"
        init_code, _ = cli("init-case", "--case-root", str(case_root), "--case-id", "case-deep-json", "--route", "R2")
        argument_cases = (
            ("append-payload", ("append", "--case-root", str(case_root), "--record-type", "packet", "--payload-json", deep_array)),
            ("evidence-content", ("evidence-add", "--case-root", str(case_root), "--evidence-id", "evidence-deep-json", "--evidence-kind", "behavioral_test", "--content-json", deep_object)),
            ("capability-efforts", ("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-6-astra", "--efforts-json", deep_array, "--context-id", "context-deep-json")),
            ("packet-checks", ("packet-result", "--case-root", str(case_root), "--packet-id", "packet-deep-json", "--status", "completed", "--checks-json", deep_object)),
            ("interrupt-processes", ("interrupt", "--case-root", str(case_root), "--processes-json", deep_array)),
        )
        for label, args in argument_cases:
            before = {path: digest for path, digest in filesystem_inventory(case_root).items() if path != ".agent-council.lock"} if init_code == 0 else {}
            code, response, stderr = cli_detail(*args)
            after = filesystem_inventory(case_root) if init_code == 0 else {}
            rows.append((f"deep-json-{label}-refuses-before-lock-or-write", init_code == 0 and code != 0 and structural_refusal(response, "SCHEMA_VALIDATION_FAILED") and no_traceback(response, stderr) and after == before, "deep public JSON is rejected by the shared depth guard before authoring lock or case filesystem mutation"))

        cycle_before = filesystem_inventory(case_root) if init_code == 0 else {}
        cycle_code, cycle_response, cycle_stderr = cli_detail("cycle-start", "--case-root", str(case_root), "--candidate-json", deep_object)
        cycle_after = filesystem_inventory(case_root) if init_code == 0 else {}
        rows.append(("deep-json-cycle-candidate-refuses-before-lock-or-write", init_code == 0 and cycle_code != 0 and structural_refusal(cycle_response, "SCHEMA_VALIDATION_FAILED") and no_traceback(cycle_response, cycle_stderr) and cycle_after == cycle_before, "deep replacement candidate JSON refuses before the cycle-start lock or any case filesystem mutation"))

        candidate_root = root / "case-deep-candidate"
        candidate_code, candidate_response, candidate_stderr = cli_detail("init-case", "--case-root", str(candidate_root), "--case-id", "case-deep-candidate", "--route", "R2", "--candidate-json", deep_object)
        rows.append(("deep-json-candidate-refuses-before-root", candidate_code != 0 and structural_refusal(candidate_response, "SCHEMA_VALIDATION_FAILED") and no_traceback(candidate_response, candidate_stderr) and not candidate_root.exists(), "deep candidate JSON refuses before initialization can create a case root"))

        for label, payload in (("arrays", deep_array), ("objects", deep_object)):
            document = root / f"deep-evaluate-{label}.json"
            document.write_text(payload, encoding="utf-8")
            before = filesystem_inventory(root)
            code, response, stderr = cli_detail("evaluate", str(document))
            after = filesystem_inventory(root)
            rows.append((f"evaluate-1200-nested-{label}-refuses-read-only", code != 0 and structural_refusal(response, "SCHEMA_VALIDATION_FAILED") and no_traceback(response, stderr) and after == before, "public evaluation rejects 1,200 nested JSON containers structurally without traceback or filesystem writes"))
    return rows


def test_public_complete_envelope_depth_guard() -> list[tuple[str, bool, str]]:
    """Reject JSON that is shallow alone but unsafe once enveloped as an event."""
    rows: list[tuple[str, bool, str]] = []

    def nested_arrays(depth: int) -> Any:
        value: Any = "metadata-leaf"
        for _ in range(depth):
            value = [value]
        return value

    def no_traceback(response: dict[str, Any], stderr: str) -> bool:
        return "Traceback" not in stderr and "Traceback" not in response.get("stdout", "")

    with tempfile.TemporaryDirectory(prefix="agent-council-v2-envelope-depth-") as temporary:
        root = Path(temporary)
        case_root = root / "case-envelope-depth"
        init_code, _ = cli("init-case", "--case-root", str(case_root), "--case-id", "case-envelope-depth", "--route", "R2")
        deep_metadata = nested_arrays(61)
        append_cases = (
            (
                "packet",
                {
                    "packet_id": "packet-envelope-depth",
                    "phase": "request",
                    "status": "accepted",
                    "requested_role": "technical_tactical_intelligence",
                    "metadata": deep_metadata,
                },
            ),
            (
                "test",
                {
                    "run_id": "test-envelope-depth",
                    "evidence_id": "evidence-envelope-depth",
                    "test_kind": "normative",
                    "status": "passed",
                    "metadata": deep_metadata,
                },
            ),
        )
        for record_type, payload in append_cases:
            before = {path: digest for path, digest in filesystem_inventory(case_root).items() if path != ".agent-council.lock"} if init_code == 0 else {}
            before_events = event_inventory(case_root) if init_code == 0 else {}
            before_state = (case_root / "case.json").read_bytes() if init_code == 0 else b""
            code, response, stderr = cli_detail("append", "--case-root", str(case_root), "--record-type", record_type, "--payload-json", json.dumps(payload))
            after = filesystem_inventory(case_root) if init_code == 0 else {}
            after_without_lock = {path: digest for path, digest in after.items() if path != ".agent-council.lock"}
            after_events = event_inventory(case_root) if init_code == 0 else {}
            after_state = (case_root / "case.json").read_bytes() if init_code == 0 else b""
            rows.append((f"append-{record_type}-61-array-metadata-refuses-before-any-write", init_code == 0 and code != 0 and structural_refusal(response, "SCHEMA_VALIDATION_FAILED") and no_traceback(response, stderr) and after_without_lock == before and after_events == before_events and after_state == before_state, "metadata that becomes over-depth only in the complete immutable envelope refuses without event, evidence, or state mutation; a stable local lock file is allowed"))

        clean_payload = {
            "packet_id": "packet-envelope-depth-clean",
            "phase": "request",
            "status": "accepted",
            "requested_role": "technical_tactical_intelligence",
        }
        retry_code, retry, retry_stderr = cli_detail("append", "--case-root", str(case_root), "--record-type", "packet", "--payload-json", json.dumps(clean_payload))
        rows.append(("append-61-array-metadata-clean-retry-succeeds", init_code == 0 and retry_code == 0 and retry.get("result") == "accepted" and retry.get("code") == "EVENT_APPENDED" and "Traceback" not in retry_stderr and (case_root / "events" / f"{retry.get('event_id', 'missing')}.json").is_file(), "the same valid packet request remains appendable after the complete-envelope depth refusal"))
    return rows


def test_public_init_candidate_complete_envelope_depth() -> list[tuple[str, bool, str]]:
    """Keep initialization invisible when candidate metadata overflows its final state envelope."""
    rows: list[tuple[str, bool, str]] = []

    def nested_arrays(depth: int) -> Any:
        value: Any = "metadata-leaf"
        for _ in range(depth):
            value = [value]
        return value

    with tempfile.TemporaryDirectory(prefix="agent-council-v2-init-envelope-depth-") as temporary:
        root = Path(temporary)
        case_root = root / "case-init-envelope-depth"
        valid_candidate = {key: token(f"init-envelope-depth-{key}") for key in ("source_sha256", "package_sha256", "dependency_lock_sha256", "harness_sha256")}
        deep_candidate = dict(valid_candidate, metadata=nested_arrays(63))
        code, response, stderr = cli_detail("init-case", "--case-root", str(case_root), "--case-id", "case-init-envelope-depth", "--route", "R2", "--candidate-json", json.dumps(deep_candidate))
        rows.append(("init-case-63-array-candidate-metadata-refuses-before-root-or-pins", code != 0 and structural_refusal(response, "SCHEMA_VALIDATION_FAILED") and "Traceback" not in stderr and "Traceback" not in response.get("stdout", "") and not case_root.exists(), "a valid four-hash candidate whose metadata only exceeds depth in the complete state envelope leaves no root or pinned artifacts"))

        retry_code, retry, retry_stderr = cli_detail("init-case", "--case-root", str(case_root), "--case-id", "case-init-envelope-depth", "--route", "R2", "--candidate-json", json.dumps(valid_candidate))
        rows.append(("init-case-63-array-candidate-metadata-clean-retry-succeeds", retry_code == 0 and retry.get("result") == "accepted" and retry.get("code") == "CASE_INITIALIZED" and "Traceback" not in retry_stderr and (case_root / "case.json").is_file() and (case_root / "pinned").is_dir(), "a clean valid candidate initializes normally after the rejected staged candidate"))
    return rows


def test_public_evaluate_integer_digit_bound() -> list[tuple[str, bool, str]]:
    """Exercise native decimal-limit handling where available, with portable public behavior otherwise."""
    rows: list[tuple[str, bool, str]] = []
    getter = getattr(sys, "get_int_max_str_digits", None)
    digit_limit = getter() if callable(getter) else 0
    limit_active = isinstance(digit_limit, int) and 0 < digit_limit < 5000
    with tempfile.TemporaryDirectory(prefix="agent-council-v2-integer-bound-") as temporary:
        root = Path(temporary)
        document = root / "five-thousand-digit-integer.json"
        document.write_text('{"integer":' + "9" * 5000 + "}", encoding="utf-8")
        before = filesystem_inventory(root)
        code, response, stderr = cli_detail("evaluate", str(document))
        after = filesystem_inventory(root)
        path_note = "the interpreter's native decimal digit limit" if limit_active else "the evaluator's structural invalid-document path on this interpreter without a decimal digit limit"
        rows.append(("evaluate-5000-digit-integer-refuses-structurally-read-only", code != 0 and structural_refusal(response, "SCHEMA_VALIDATION_FAILED") and "Traceback" not in stderr and "Traceback" not in response.get("stdout", "") and after == before, f"a valid JSON document with a 5,000-digit integer refuses through {path_note}, without traceback or filesystem mutation"))
    return rows


def test_pending_case_transactions() -> list[tuple[str, bool, str]]:
    """Exercise durable recovery solely through the public CLI contract."""
    rows: list[tuple[str, bool, str]] = []

    def faulted_case(root: Path, label: str, boundary: str) -> tuple[dict[str, Any], bytes]:
        init_code, _ = cli("init-case", "--case-root", str(root), "--case-id", f"case-journal-{label}", "--route", "R2")
        before = (root / "case.json").read_bytes() if init_code == 0 else b""
        state = json.loads(before) if before else {}
        failure_code, _, failure_stderr = cli_fault(boundary, "evidence-add", "--case-root", str(root), "--evidence-id", f"evidence-journal-{label}", "--evidence-kind", "behavioral_test", "--content-json", json.dumps(behavioral_evidence(state.get("engineering_candidate", {}), f"test-journal-{label}", state.get("cycle_id", ""))))
        rows.append((f"pending-journal-{label}-fault-injected", init_code == 0 and failure_code != 0 and "Traceback" not in failure_stderr and (root / ".agent-council.pending.v1.json").is_file(), "a failure after the requested durable boundary leaves an exact pending write-ahead journal"))
        return state, before

    with tempfile.TemporaryDirectory(prefix="agent-council-v2-pending-") as temporary:
        root = Path(temporary)
        journal_root = root / "case-journal-boundary"
        _, old_state = faulted_case(journal_root, "boundary", "journal")
        journal = journal_root / ".agent-council.pending.v1.json"
        wrong_boundary_before = filesystem_inventory(journal_root)
        wrong_boundary_code, wrong_boundary, wrong_boundary_stderr = cli_detail("recover-case", "--case-root", str(journal_root), "--project-root", str(root.parent))
        rows.append(("pending-journal-wrong-project-root-cannot-recover", wrong_boundary_code != 0 and structural_refusal(wrong_boundary, "PROJECT_ROOT_MISMATCH") and "Traceback" not in wrong_boundary_stderr and filesystem_inventory(journal_root) == wrong_boundary_before and (journal_root / "case.json").read_bytes() == old_state and journal.exists(), "a broader but unpinned project root cannot publish a pending state or remove its journal"))
        lock = journal_root / ".agent-council.lock"
        if lock.exists(): lock.unlink()
        read_before = filesystem_inventory(journal_root)
        evaluate_code, evaluate, evaluate_stderr = cli_detail("evaluate", str(journal_root / "case.json"))
        rows.append(("pending-journal-evaluation-is-read-only-and-requires-recovery", evaluate_code != 0 and structural_refusal(evaluate, "RECOVERY_REQUIRED") and "Traceback" not in evaluate_stderr and filesystem_inventory(journal_root) == read_before and not lock.exists(), "read-only evaluation reports pending recovery without taking the lock or repairing bytes"))
        recovered_code, recovered = cli("recover-case", "--case-root", str(journal_root))
        recovered_state = json.loads((journal_root / "case.json").read_text(encoding="utf-8"))
        rows.append(("pending-journal-recover-after-journal-boundary", recovered_code == 0 and recovered.get("code") == "CASE_RECOVERED" and not journal.exists() and (journal_root / "case.json").read_bytes() != old_state and any(item.get("record_type") == "evidence" for item in recovered_state.get("events", [])), "recovery publishes the complete immutable transaction and replaces state last"))

        target_root = root / "case-journal-target"
        _, target_old = faulted_case(target_root, "target", "target-1")
        target_journal = json.loads((target_root / ".agent-council.pending.v1.json").read_text(encoding="utf-8"))
        target = target_journal["targets"][0]
        target_path = target_root / target["path"]
        target_before = target_path.read_bytes() if target_path.is_file() else b""
        target_recover_code, target_recover = cli("recover-case", "--case-root", str(target_root))
        target_expected_state = base64.b64decode(target_journal["state"]["bytes_b64"])
        rows.append(("pending-journal-exact-immutable-replay", target_recover_code == 0 and target_recover.get("code") == "CASE_RECOVERED" and target_before == target_path.read_bytes() and (target_root / "case.json").read_bytes() == target_expected_state and (target_root / "case.json").read_bytes() != target_old, "recovery accepts an already-published immutable target only when its exact bytes match"))

        committed_root = root / "case-journal-committed"
        _, _ = faulted_case(committed_root, "committed", "case")
        committed_journal = committed_root / ".agent-council.pending.v1.json"
        committed_state = (committed_root / "case.json").read_bytes()
        committed_code, committed = cli("recover-case", "--case-root", str(committed_root))
        rows.append(("pending-journal-committed-not-cleaned-recovery", committed_code == 0 and committed.get("code") == "CASE_RECOVERED" and not committed_journal.exists() and (committed_root / "case.json").read_bytes() == committed_state, "a committed but uncleaned journal is cleaned without changing exact state bytes"))

        conflict_root = root / "case-journal-conflict"
        _, conflict_old = faulted_case(conflict_root, "conflict", "journal")
        conflict = json.loads((conflict_root / ".agent-council.pending.v1.json").read_text(encoding="utf-8"))
        conflicting_target = conflict_root / conflict["targets"][0]["path"]
        conflicting_target.parent.mkdir(parents=True, exist_ok=True)
        conflicting_target.write_bytes(b"conflicting bytes\n")
        conflict_code, conflict_result, conflict_stderr = cli_detail("recover-case", "--case-root", str(conflict_root))
        rows.append(("pending-journal-conflicting-target-fails-closed", conflict_code != 0 and structural_refusal(conflict_result, "PENDING_TRANSACTION_CONFLICT") and "Traceback" not in conflict_stderr and (conflict_root / "case.json").read_bytes() == conflict_old and (conflict_root / ".agent-council.pending.v1.json").exists(), "conflicting immutable bytes leave both state and recovery evidence untouched"))

        malformed_root = root / "case-journal-malformed"
        malformed_init, _ = cli("init-case", "--case-root", str(malformed_root), "--case-id", "case-journal-malformed", "--route", "R2")
        malformed_old = (malformed_root / "case.json").read_bytes() if malformed_init == 0 else b""
        (malformed_root / ".agent-council.pending.v1.json").write_text("not-json\n", encoding="utf-8")
        malformed_code, malformed, malformed_stderr = cli_detail("recover-case", "--case-root", str(malformed_root))
        rows.append(("pending-journal-malformed-fails-closed", malformed_code != 0 and structural_refusal(malformed, "PENDING_TRANSACTION_INVALID") and "Traceback" not in malformed_stderr and (malformed_root / "case.json").read_bytes() == malformed_old, "malformed pending journals are never interpreted or discarded"))

        symlink_root = root / "case-journal-symlink"
        _, symlink_old = faulted_case(symlink_root, "symlink", "journal")
        symlink_plan = json.loads((symlink_root / ".agent-council.pending.v1.json").read_text(encoding="utf-8"))
        outside = root / "outside-journal-target"; outside.mkdir()
        symlink_target = symlink_root / symlink_plan["targets"][0]["path"]
        symlink_target.parent.mkdir(parents=True, exist_ok=True)
        symlink_target.symlink_to(outside / "escaped.json")
        symlink_code, symlink_result, symlink_stderr = cli_detail("recover-case", "--case-root", str(symlink_root))
        rows.append(("pending-journal-symlink-refused-before-repair", symlink_code != 0 and structural_refusal(symlink_result, "CASE_PATH_SYMLINK_REFUSED") and "Traceback" not in symlink_stderr and (symlink_root / "case.json").read_bytes() == symlink_old and not any(outside.iterdir()), "a symlinked recovery target is refused before it can redirect a repair write"))

        concurrent_root = root / "case-journal-concurrent"
        _, _ = faulted_case(concurrent_root, "concurrent", "journal")
        command = [sys.executable, str(RUNTIME), "recover-case", "--case-root", str(concurrent_root), "--project-root", str(concurrent_root.parent)]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        replies = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            try: response = json.loads(stdout)
            except json.JSONDecodeError: response = {}
            replies.append((process.returncode, response, stderr))
        concurrent_state = json.loads((concurrent_root / "case.json").read_text(encoding="utf-8"))
        recovered = [reply for reply in replies if reply[0] == 0 and reply[1].get("code") == "CASE_RECOVERED"]
        idle = [reply for reply in replies if reply[0] == 0 and reply[1].get("code") == "NO_PENDING_TRANSACTION"]
        rows.append(("pending-journal-concurrent-retry-idempotent", len(recovered) == len(idle) == 1 and not (concurrent_root / ".agent-council.pending.v1.json").exists() and len([item for item in concurrent_state.get("events", []) if item.get("record_type") == "evidence"]) == 1 and all("Traceback" not in reply[2] for reply in replies), "concurrent recoveries serialize to one exact publication and one harmless retry"))
    return rows


def test_authoring(group: str) -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory(prefix="agent-council-v2-authoring-") as temporary:
        case_root = Path(temporary) / "case-safe-authoring"
        initial_candidate = {key: token(f"initial-{key}") for key in ("source_sha256", "package_sha256", "dependency_lock_sha256", "harness_sha256")}
        code, init = cli("init-case", "--case-root", str(case_root), "--case-id", "case-safe-authoring", "--route", "R2", "--candidate-json", json.dumps(initial_candidate))
        rows.append(("init-case", code == 0 and init.get("result") == "accepted", "initializes a pinned local case"))
        initialized_candidate = init.get("state", {}).get("engineering_candidate", {})
        rows.append(("init-exact-candidate", all(initialized_candidate.get(key) == value for key, value in initial_candidate.items()), "public init binds the exact supplied source, package, dependency, and harness hashes"))
        code, bundle = cli("build-bundle", "--case-root", str(case_root))
        rows.append(("executing-bundle", code == 0 and bundle.get("policy_bundle_sha256") and bundle.get("engineering_candidate_sha256") and bundle.get("policy_bundle_sha256") != bundle.get("engineering_candidate_sha256"), "separates policy and engineering candidate digests"))
        code, protected = cli("append", "--case-root", str(case_root), "--record-type", "dispatch", "--payload-json", "{}")
        rows.append(("protected-generic-append", code != 0 and protected.get("code") == "PROTECTED_RECORD_REFUSED", "generic append refuses protected dispatch records"))
        initial_cycle = init.get("state", {}).get("cycle_id", "")
        valid_evidence = json.dumps(behavioral_evidence(initialized_candidate, "test-safe", initial_cycle))
        code, event_one = cli("evidence-add", "--case-root", str(case_root), "--evidence-id", "evidence-valid", "--evidence-kind", "behavioral_test", "--content-json", valid_evidence)
        code2, event_two = cli("evidence-add", "--case-root", str(case_root), "--evidence-id", "evidence-valid", "--evidence-kind", "behavioral_test", "--content-json", valid_evidence)
        rows.append(("duplicate-event-exclusive", code == 0 and code2 != 0 and event_two.get("code") == "DUPLICATE_EVENT_REFUSED", "duplicate immutable events refuse before partial writes"))
        concurrent_commands = [[sys.executable, str(RUNTIME), "evidence-add", "--case-root", str(case_root), "--project-root", str(case_root.parent), "--evidence-id", evidence_id, "--evidence-kind", "behavioral_test", "--content-json", json.dumps(behavioral_evidence(initialized_candidate, f"test-{evidence_id}", initial_cycle))] for evidence_id in ("evidence-concurrent-a", "evidence-concurrent-b")]
        concurrent = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for command in concurrent_commands]
        concurrent_results = [process.communicate(timeout=30) + (process.returncode,) for process in concurrent]
        concurrent_state = json.loads((case_root / "case.json").read_text(encoding="utf-8"))
        concurrent_ids = {event["payload"].get("evidence_id") for event in concurrent_state["events"] if event["record_type"] == "evidence"}
        rows.append(("concurrent-authoring-serialized", all(result[2] == 0 for result in concurrent_results) and {"evidence-concurrent-a", "evidence-concurrent-b"} <= concurrent_ids, "case-level lock prevents concurrent writers from losing either immutable event"))
        code, invalid_evidence = cli("evidence-add", "--case-root", str(case_root), "--evidence-id", "evidence-secret", "--evidence-kind", "behavioral_test", "--content-json", '{"password":"not-permitted"}')
        rows.append(("invalid-evidence-refused", code != 0 and invalid_evidence.get("code") == "SECRET_REFUSED", "invalid secret-bearing evidence is refused"))
        code, stale = cli("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-5.6-terra", "--efforts-json", '["high"]', "--context-id", "context-safe", "--observed-at", "2000-01-01T00:00:00Z")
        rows.append(("stale-capability-refused", code != 0 and stale.get("code") == "CAPABILITY_STALE", "stale capability capture fails closed"))
        code, capability = cli("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-5.6-terra", "--efforts-json", '["high","ultra"]', "--context-id", "context-safe")
        rows.append(("capability-capture", code == 0 and capability.get("result") == "accepted", "current capability is captured as immutable evidence"))
        code, no_plan = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--task-id", "task-1", "--model-id", "gpt-5.6-terra", "--effort", "high", "--context-id", "context-safe", "--output-ref", "output-1")
        rows.append(("capture-without-plan", code != 0 and no_plan.get("code") == "DISPATCH_PLAN_REQUIRED", "adapter capture requires a live plan"))
        code, early_plan = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "technical_tactical_intelligence", "--context-id", "context-safe")
        rows.append(("implementation-before-decisions-refused", code != 0 and early_plan.get("code") == "ULTIMATE_GATE_RECEIPT_MISSING", "implementation cannot be planned before required ultimate routing and design"))
        decision_captures: list[bool] = []
        for decision_kind in ("routing", "design"):
            context_id = f"context-ultimate-{decision_kind}"
            code1, _ = cli("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-6-astra", "--efforts-json", '["high"]', "--context-id", context_id)
            code2, decision_plan = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", context_id, "--decision-kind", decision_kind)
            code3, decision_capture = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", decision_plan.get("plan_nonce", ""), "--task-id", f"task-ultimate-{decision_kind}", "--model-id", "gpt-6-astra", "--effort", "high", "--context-id", context_id, "--output-ref", f"output-ultimate-{decision_kind}", "--decision-kind", decision_kind)
            decision_captures.append(code1 == code2 == code3 == 0 and decision_capture.get("code") == "DISPATCH_CAPTURED")
        rows.append(("ultimate-decision-captures", all(decision_captures), "routing and design receipts come from planned native ultimate dispatches"))
        code, plan = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "technical_tactical_intelligence", "--context-id", "context-safe")
        nonce = plan.get("plan_nonce", "")
        rows.append(("codex-plan", code == 0 and bool(nonce) and plan.get("decision_kind") == "implementation", "technical plans default to implementation and have a single-use nonce"))
        code, wrong = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", nonce, "--task-id", "task-1", "--model-id", "gpt-5.6-luna", "--effort", "high", "--context-id", "context-safe", "--output-ref", "output-1")
        rows.append(("wrong-model-refused", code != 0 and wrong.get("code") == "PROVIDER_RECEIPT_MISMATCH", "capture rejects an unplanned model"))
        code, capture = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", nonce, "--task-id", "task-1", "--model-id", "gpt-5.6-terra", "--effort", "high", "--context-id", "context-safe", "--output-ref", "output-1")
        code2, reused = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", nonce, "--task-id", "task-1", "--model-id", "gpt-5.6-terra", "--effort", "high", "--context-id", "context-safe", "--output-ref", "output-1")
        rows.append(("codex-capture-single-use", code == 0 and capture.get("result") == "accepted" and code2 != 0 and reused.get("code") == "DISPATCH_PLAN_CONSUMED", "capture records platform return references and consumes plan nonce"))
        packet_code, _ = cli("packet-result", "--case-root", str(case_root), "--packet-id", plan.get("packet_id", "missing"), "--status", "completed", "--checks-json", '[{"gate_id":"implementation","status":"passed"}]')
        rows.append(("implementation-packet-result", packet_code == 0, "implementation dispatch has one completed checked packet"))
        claude_case = case_root.parent / "case-claude-qualified"
        cli("init-case", "--case-root", str(claude_case), "--case-id", "case-claude-qualified", "--route", "R2", "--candidate-json", json.dumps(initial_candidate))
        cli("capability-capture", "--case-root", str(claude_case), "--provider", "claude_code", "--model-id", "claude-fable-5-1", "--efforts-json", '["high"]', "--context-id", "context-claude")
        claude_code_status, claude_plan = cli("dispatch-plan", "--case-root", str(claude_case), "--provider", "claude_code", "--role", "ultimate_intelligence", "--context-id", "context-claude", "--decision-kind", "routing")
        rows.append(("claude-code-qualified-dispatch", claude_code_status == 0 and claude_plan.get("code") == "DISPATCH_PLAN_CREATED" and claude_plan.get("model_id") == "claude-fable-5-1" and claude_plan.get("binding_id") == "claude-code-v2-ultimate", "qualified Claude Code adapter resolves its ultimate-tier binding"))
        code, close = cli("close-case", "--case-root", str(case_root))
        rows.append(("close-before-gates", code != 0 and close.get("code") == "REQUIRED_GATE_EVIDENCE_MISSING", "close fails before required gates"))
        code, tested = cli("test-record", "--case-root", str(case_root), "--run-id", "test-safe", "--evidence-id", "evidence-valid")
        code2, arbitrary = cli("gate", "--case-root", str(case_root), "--gate-id", "gate-safe", "--evidence-id", "evidence-valid")
        rows.append(("arbitrary-gate-refused", code2 != 0 and arbitrary.get("code") == "ROUTE_GATE_SET_INVALID", "caller cannot invent an easier closure gate"))
        code_review_cap, _ = cli("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-5.6-sol", "--efforts-json", '["high"]', "--context-id", "context-operational-review")
        code_review_plan, review_plan = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "operational_intelligence", "--context-id", "context-operational-review", "--decision-kind", "review")
        code_review_capture, _ = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", review_plan.get("plan_nonce", ""), "--task-id", "task-operational-review", "--model-id", "gpt-5.6-sol", "--effort", "high", "--context-id", "context-operational-review", "--output-ref", "output-operational-review", "--decision-kind", "review")
        code3, reviewed = cli("review-record", "--case-root", str(case_root), "--review-id", "independent-review", "--reviewer-id", "task-operational-review", "--implementation-id", "task-1", "--evidence-id", "evidence-valid")
        code_final_cap, _ = cli("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-6-astra", "--efforts-json", '["high"]', "--context-id", "context-ultimate-final")
        code_final_plan, final_plan = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", "context-ultimate-final", "--decision-kind", "final")
        code_final_capture, _ = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", final_plan.get("plan_nonce", ""), "--task-id", "task-ultimate-final", "--model-id", "gpt-6-astra", "--effort", "high", "--context-id", "context-ultimate-final", "--output-ref", "output-ultimate-final", "--decision-kind", "final")
        rows.append(("review-and-final-order", all(value == 0 for value in (code_review_cap, code_review_plan, code_review_capture, code3, code_final_cap, code_final_plan, code_final_capture)), "independent operational review precedes final ultimate disposition"))
        gate_results = []
        for gate_id in ("ultimate-routing", "ultimate-design", "implementation-verification", "ultimate-final-disposition"):
            gate_code, gate_value = cli("gate", "--case-root", str(case_root), "--gate-id", gate_id, "--evidence-id", "evidence-valid")
            gate_results.append(gate_code == 0 and gate_value.get("code") == "GATE_RECORDED")
        code4, closed = cli("close-case", "--case-root", str(case_root))
        rows.append(("successful-r2-close", code == code3 == code4 == 0 and all(gate_results) and tested.get("result") == "accepted" and closed.get("code") == "CASE_CLOSED", "candidate-bound tests and route-derived receipts close R2"))
        evaluation_code, evaluation = cli("evaluate", str(case_root / "case.json"))
        descriptor = json.loads((case_root / "runtime-descriptor.json").read_text(encoding="utf-8"))
        structural_only = lambda outcome: outcome.get("assurance") == "structural_only" and outcome.get("provider_execution_attested") is False and outcome.get("uat_authority") is False
        rows.append(("local-receipts-remain-structural-only", evaluation_code == 0 and evaluation.get("result") == "accepted" and descriptor.get("provider_signing") == "not_cryptographically_verified" and structural_only(descriptor) and structural_only(evaluation) and structural_only(closed), "local captures may accept a structural case but explicitly do not attest provider execution or grant UAT authority"))
        candidate = json.dumps({"source_sha256": token("changed-source"), "package_sha256": token("changed-package"), "dependency_lock_sha256": token("changed-lock"), "harness_sha256": token("changed-harness")})
        code, changed = cli("cycle-start", "--case-root", str(case_root), "--candidate-json", candidate)
        changed_state = json.loads((case_root / "case.json").read_text(encoding="utf-8"))
        changed_candidate_state = changed_state["engineering_candidate"]
        changed_evidence = json.dumps(behavioral_evidence(changed_candidate_state, "test-changed", changed_state["cycle_id"]))
        code2, changed_evidence_result = cli("evidence-add", "--case-root", str(case_root), "--evidence-id", "evidence-changed", "--evidence-kind", "behavioral_test", "--content-json", changed_evidence)
        fresh_decisions = []
        for decision_kind in ("routing", "design"):
            context_id = f"context-ultimate-{decision_kind}"
            plan_code, decision_plan = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", context_id, "--decision-kind", decision_kind)
            capture_code, _ = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", decision_plan.get("plan_nonce", ""), "--task-id", f"task-changed-{decision_kind}", "--model-id", "gpt-6-astra", "--effort", "high", "--context-id", context_id, "--output-ref", f"output-changed-{decision_kind}", "--decision-kind", decision_kind)
            fresh_decisions.append(plan_code == capture_code == 0)
        technical_plan_code, changed_technical_plan = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "technical_tactical_intelligence", "--context-id", "context-safe")
        technical_capture_code, _ = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", changed_technical_plan.get("plan_nonce", ""), "--task-id", "task-changed-implementation", "--model-id", "gpt-5.6-terra", "--effort", "high", "--context-id", "context-safe", "--output-ref", "output-changed-implementation")
        technical_result_code, _ = cli("packet-result", "--case-root", str(case_root), "--packet-id", changed_technical_plan.get("packet_id", "missing"), "--status", "completed", "--checks-json", '[{"gate_id":"implementation","status":"passed"}]')
        code3, changed_test = cli("test-record", "--case-root", str(case_root), "--run-id", "test-changed", "--evidence-id", "evidence-changed")
        review_plan_code, changed_review_plan = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "operational_intelligence", "--context-id", "context-operational-review", "--decision-kind", "review")
        review_capture_code, _ = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", changed_review_plan.get("plan_nonce", ""), "--task-id", "task-changed-review", "--model-id", "gpt-5.6-sol", "--effort", "high", "--context-id", "context-operational-review", "--output-ref", "output-changed-review", "--decision-kind", "review")
        code5, changed_review = cli("review-record", "--case-root", str(case_root), "--review-id", "independent-review", "--reviewer-id", "task-changed-review", "--implementation-id", "task-changed-implementation", "--evidence-id", "evidence-changed")
        final_plan_code, changed_final_plan = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", "context-ultimate-final", "--decision-kind", "final")
        final_capture_code, _ = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", changed_final_plan.get("plan_nonce", ""), "--task-id", "task-changed-final", "--model-id", "gpt-6-astra", "--effort", "high", "--context-id", "context-ultimate-final", "--output-ref", "output-changed-final", "--decision-kind", "final")
        changed_gates = []
        for gate_id in ("ultimate-routing", "ultimate-design", "implementation-verification", "ultimate-final-disposition"):
            gate_code, _ = cli("gate", "--case-root", str(case_root), "--gate-id", gate_id, "--evidence-id", "evidence-changed")
            changed_gates.append(gate_code == 0)
        code6, changed_close = cli("close-case", "--case-root", str(case_root))
        rows.append(("changed-candidate-fresh-close", all(value == 0 for value in (code, code2, technical_plan_code, technical_capture_code, technical_result_code, code3, review_plan_code, review_capture_code, code5, final_plan_code, final_capture_code, code6)) and all(fresh_decisions) and all(changed_gates) and changed.get("code") == "CYCLE_STARTED" and changed_close.get("code") == "CASE_CLOSED", "changed candidate starts a fresh cycle and repeats route-derived decisions and evidence"))
        pinned_schema = case_root / "pinned" / "standards" / "agent-council-record.schema.v2.yaml"; before = hashlib.sha256(pinned_schema.read_bytes()).hexdigest()
        code, replay = cli("evaluate", str(case_root / "case.json"))
        after = hashlib.sha256(pinned_schema.read_bytes()).hexdigest()
        rows.append(("pinned-replay", before == after and replay.get("code") != "SCHEMA_VALIDATION_FAILED", "evaluation leaves pinned schema bytes unchanged and never mutates shared source"))
        code, interrupted = cli("interrupt", "--case-root", str(case_root), "--processes-json", '[{"identity":"local-process","status":"reconciled"}]')
        code2, resumed = cli("resume", "--case-root", str(case_root), "--interruption-id", interrupted.get("interruption_id", "missing"))
        rows.append(("cross-cycle-exact-resumption", code == code2 == 0 and resumed.get("code") == "INTERRUPTION_RESUMED", "reconciled interruption resumes exactly in a new cycle"))
    return rows + test_pending_case_transactions() + test_stale_dispatch_plans() + test_public_cli_boundaries() + test_public_cli_multi_cycle_transitions() + test_public_cli_evidence_id_boundary() + test_public_evaluate_read_only() + test_public_cycle_start_unchanged() + test_public_json_depth_guard() + test_public_complete_envelope_depth_guard() + test_public_init_candidate_complete_envelope_depth() + test_public_evaluate_integer_digit_bound()


def test_dispatch_contracts() -> list[tuple[str, bool, str]]:
    """Exercise immutable notices and bounded CE handoff metadata via public CLI."""
    rows: list[tuple[str, bool, str]] = []

    def prepare_decisions(case_root: Path) -> bool:
        if cli("init-case", "--case-root", str(case_root), "--case-id", "case-dispatch-contracts", "--route", "R2")[0] != 0:
            return False
        for decision_kind in ("routing", "design"):
            context_id = f"context-{decision_kind}"
            cap_code, _ = cli("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-6-astra", "--efforts-json", '["high"]', "--context-id", context_id)
            plan_code, plan = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", context_id, "--decision-kind", decision_kind)
            capture_code, _ = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", plan.get("plan_nonce", ""), "--task-id", f"task-{decision_kind}", "--model-id", "gpt-6-astra", "--effort", "high", "--context-id", context_id, "--output-ref", f"output-{decision_kind}", "--decision-kind", decision_kind)
            if cap_code or plan_code or capture_code:
                return False
        return cli("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-5.6-terra", "--efforts-json", '["high"]', "--context-id", "context-implementation")[0] == 0

    with tempfile.TemporaryDirectory(prefix="agent-council-v2-dispatch-") as temporary:
        root = Path(temporary)
        case_root = root / "case-ce"
        ready = prepare_decisions(case_root)
        operational_capability_code, _ = cli("capability-capture", "--case-root", str(case_root), "--provider", "codex", "--model-id", "gpt-5.6-sol", "--efforts-json", '["high"]', "--context-id", "context-operational-review")
        plan_code, plan = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "technical_tactical_intelligence", "--context-id", "context-implementation", "--work-method", "compound_engineering")
        notice = plan.get("user_notice", {})
        rows.append(("dispatch-plan-generated-visible-notice", ready and plan_code == 0 and notice == {"schema_version": "agent-council.user-notice/v1", "model_id": "gpt-5.6-terra", "effort": "high", "role": "technical_tactical_intelligence", "decision_kind": "implementation", "cost_class": "standard", "task": "implementation task", "reason": "the case is ready for bounded implementation work", "message": "Council: gpt-5.6-terra/high (standard) assigned implementation task because the case is ready for bounded implementation work."}, "dispatch plan persists the exact user-facing notice the outer agent must display"))
        rows.append(("compound-engineering-boundary-contract", ready and operational_capability_code == 0 and plan_code == 0 and all(plan.get(key) == value for key, value in {"work_method": "compound_engineering", "orchestrator_owner": "compound_engineering", "council_reentry": "denied", "execution_mode": "return_to_caller", "handoff_status": "pending"}.items()), "CE is limited to one bounded return-to-caller implementation handoff"))
        duplicate_code, duplicate = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "technical_tactical_intelligence", "--context-id", "context-implementation", "--work-method", "compound_engineering")
        rows.append(("compound-engineering-single-outstanding-handoff", duplicate_code != 0 and duplicate.get("code") == "COMPOUND_ENGINEERING_HANDOFF_PENDING", "a second CE handoff refuses while the first handoff remains pending"))
        before_native_refusal = (case_root / "case.json").read_bytes()
        native_blocked_code, native_blocked = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "operational_intelligence", "--context-id", "context-operational-review", "--decision-kind", "review")
        rows.append(("compound-engineering-pending-blocks-native-dispatch-atomically", native_blocked_code != 0 and native_blocked.get("code") == "COMPOUND_ENGINEERING_HANDOFF_PENDING" and (case_root / "case.json").read_bytes() == before_native_refusal, "a pending CE lease blocks every later Council dispatch without mutating state"))
        capture_code, captured = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", plan.get("plan_nonce", ""), "--task-id", "task-ce-implementation", "--model-id", "gpt-5.6-terra", "--effort", "high", "--context-id", "context-implementation", "--output-ref", "output-ce-implementation")
        state = json.loads((case_root / "case.json").read_text(encoding="utf-8")) if case_root.exists() else {}
        stored = state.get("dispatch_plans", {}).get(plan.get("plan_nonce", ""), {})
        request_path = case_root / "requests" / f"{plan.get('plan_nonce', '')}.json"
        immutable_request = {key: value for key, value in stored.items() if key not in {"request_sha256", "consumed", "invalidated"}}
        request_bytes_valid = request_path.is_file() and json.loads(request_path.read_text(encoding="utf-8")) == immutable_request and stored.get("request_sha256") == digest(immutable_request)
        rows.append(("compound-engineering-handoff-reconciles-on-capture", capture_code == 0 and captured.get("code") == "DISPATCH_CAPTURED" and stored.get("consumed") is True and stored.get("handoff_status") == "pending" and state.get("handoff_lifecycle", {}).get(plan.get("plan_nonce", "")) == "reconciled", "consuming a CE plan records terminal local reconciliation outside the immutable request"))
        rows.append(("compound-engineering-reconciliation-preserves-request-integrity", request_bytes_valid, "CE reconciliation leaves the request file and request hash valid"))
        before_repeat_capture = (case_root / "case.json").read_bytes()
        repeated_capture_code, repeated_capture = cli("dispatch-capture", "--case-root", str(case_root), "--provider", "codex", "--plan-nonce", plan.get("plan_nonce", ""), "--task-id", "task-ce-repeat", "--model-id", "gpt-5.6-terra", "--effort", "high", "--context-id", "context-implementation", "--output-ref", "output-ce-repeat")
        rows.append(("compound-engineering-repeat-capture-consumed-atomically", repeated_capture_code != 0 and repeated_capture.get("code") == "DISPATCH_PLAN_CONSUMED" and (case_root / "case.json").read_bytes() == before_repeat_capture, "a reconciled CE plan refuses repeat capture without partial mutation"))
        native_after_capture_code, native_after_capture = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "operational_intelligence", "--context-id", "context-operational-review", "--decision-kind", "review")
        rows.append(("compound-engineering-reconciliation-releases-native-dispatch", native_after_capture_code == 0 and native_after_capture.get("work_method") == "native", "native operational review can proceed after CE capture reconciliation"))
        authority_code, authority = cli("dispatch-plan", "--case-root", str(case_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", "context-routing", "--decision-kind", "routing", "--work-method", "compound_engineering")
        rows.append(("compound-engineering-authority-role-refused", authority_code != 0 and authority.get("code") == "WORK_METHOD_POLICY_INVALID", "CE cannot receive Council authority or final-decision roles"))

        for label, mutation in (("missing", lambda p: p.pop("user_notice")), ("tampered", lambda p: p["user_notice"].__setitem__("cost_class", "economical"))):
            tamper_root = root / f"case-notice-{label}"
            prepared = prepare_decisions(tamper_root)
            plan_code, tamper_plan = cli("dispatch-plan", "--case-root", str(tamper_root), "--provider", "codex", "--role", "technical_tactical_intelligence", "--context-id", "context-implementation")
            state = json.loads((tamper_root / "case.json").read_text(encoding="utf-8"))
            mutation(state["dispatch_plans"][tamper_plan["plan_nonce"]])
            (tamper_root / "case.json").write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
            before = (tamper_root / "case.json").read_bytes()
            refused_code, refused = cli("dispatch-capture", "--case-root", str(tamper_root), "--provider", "codex", "--plan-nonce", tamper_plan["plan_nonce"], "--task-id", f"task-notice-{label}", "--model-id", "gpt-5.6-terra", "--effort", "high", "--context-id", "context-implementation", "--output-ref", f"output-notice-{label}")
            unchanged = (tamper_root / "case.json").read_bytes() == before
            rows.append((f"dispatch-plan-{label}-notice-refused-atomically", prepared and plan_code == 0 and refused_code != 0 and refused.get("code") == "SCHEMA_VALIDATION_FAILED" and unchanged, "a missing or altered immutable notice refuses capture before plan consumption"))

        legacy_root = root / "case-legacy-profile"
        legacy_init_code, _ = cli("init-case", "--case-root", str(legacy_root), "--case-id", "case-legacy-profile", "--route", "R1")
        legacy_state = json.loads((legacy_root / "case.json").read_text(encoding="utf-8")) if legacy_init_code == 0 else {}
        original_candidate = legacy_state.get("engineering_candidate")
        original_events = legacy_state.get("events")
        legacy_state.pop("project_profile", None)
        legacy_state.pop("handoff_lifecycle", None)
        (legacy_root / "case.json").chmod(0o600)
        (legacy_root / "case.json").write_text(json.dumps(legacy_state, sort_keys=True), encoding="utf-8")
        legacy_capture_code, _ = cli("capability-capture", "--case-root", str(legacy_root), "--provider", "codex", "--model-id", "gpt-5.6-terra", "--efforts-json", '["high"]', "--context-id", "context-legacy")
        migrated = json.loads((legacy_root / "case.json").read_text(encoding="utf-8")) if legacy_root.exists() else {}
        rows.append(("legacy-authoring-state-default-on-read-migration", legacy_init_code == 0 and legacy_capture_code == 0 and migrated.get("project_profile", {}).get("profile_id") == "legacy-default" and migrated.get("handoff_lifecycle") == {} and migrated.get("engineering_candidate") == original_candidate and migrated.get("events", [])[:1] == original_events, "pre-profile v2 state safely gains a deterministic legacy profile without changing candidate identity or prior event history"))
    return rows


def test_binding_effort_contracts() -> list[tuple[str, bool, str]]:
    """Exercise v3 policy using qualified local fixtures, never qualifying a provider."""
    rows: list[tuple[str, bool, str]] = []
    spec = importlib.util.spec_from_file_location("agent_council_effort_contracts", RUNTIME)
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    catalog = json.loads((PACKAGE / "standards/agent-model-registry.v3.yaml").read_text())

    def seal_registry(value):
        for item in value["bindings"]:
            item["binding_sha256"] = digest({key: nested for key, nested in item.items() if key != "binding_sha256"})
        value["registry_sha256"] = digest({key: nested for key, nested in value.items() if key != "registry_sha256"})
        return value

    def registry_valid(value):
        return runtime._registry_valid(value, {"registry_version": value["registry_version"], "registry_sha256": value["registry_sha256"]})

    rows.append(("v3-candidate-registry-valid", registry_valid(catalog), "v3 catalog has valid reasoning policy and hashes"))
    expected_defaults = {
        ("codex", "ultimate_intelligence"): "xhigh", ("codex", "operational_intelligence"): "xhigh",
        ("codex", "technical_tactical_intelligence"): "medium", ("codex", "worker_intelligence"): "low",
        ("claude_code", "ultimate_intelligence"): "high", ("claude_code", "operational_intelligence"): "medium",
        ("claude_code", "technical_tactical_intelligence"): "medium", ("claude_code", "worker_intelligence"): None,
    }
    rows.append(("v3-per-binding-defaults", {(item["provider"], item["tier"]): item["reasoning"]["default_effort"] for item in catalog["bindings"]} == expected_defaults, "every provider role has its explicit default"))
    for label, mutate in (
        ("missing-policy", lambda value: value["bindings"][0].pop("reasoning")),
        ("default-not-allowed", lambda value: value["bindings"][0]["reasoning"].update(default_effort="ultra", allowed_efforts=["high"])),
        ("unsupported-with-efforts", lambda value: value["bindings"][0]["reasoning"].update(supported=False, default_effort=None, allowed_efforts=["high"])),
        ("unsupported-with-default", lambda value: value["bindings"][0]["reasoning"].update(supported=False, default_effort="high", allowed_efforts=[])),
        ("supported-with-null", lambda value: value["bindings"][0]["reasoning"].update(default_effort=None)),
        ("duplicate-efforts", lambda value: value["bindings"][0]["reasoning"].update(allowed_efforts=["xhigh", "xhigh"])),
        ("unknown-effort", lambda value: value["bindings"][0]["reasoning"].update(default_effort="invented", allowed_efforts=["invented"])),
        ("unknown-policy-field", lambda value: value["bindings"][0]["reasoning"].update(arbitrary=True)),
        ("undeclared-provider", lambda value: value["bindings"][0].update(provider="arbitrary")),
    ):
        invalid = json.loads(json.dumps(catalog)); mutate(invalid); seal_registry(invalid)
        rows.append((f"v3-{label}-refused", not registry_valid(invalid), "even resealed invalid binding policy is refused"))
    rows.append(("no-effort-capability-exact-null", runtime._capability_efforts_valid([None]) and all(not runtime._capability_efforts_valid(value) for value in ([], [None, "high"], ["none"], ["null"], [None, None], None, {})), "no-effort attestation is exactly [null], never absent, mixed or a string"))

    real_material = runtime._pinned_artifact_material

    runtime._promotion_verifier()
    fixture_spec = importlib.util.spec_from_file_location("agent_council_promotion_fixtures", PACKAGE / "scripts/Test-AgentCouncilPromotion.py")
    fixture_module = importlib.util.module_from_spec(fixture_spec)
    fixture_spec.loader.exec_module(fixture_module)
    promotion_files, _ = fixture_module.fixture(registry_value=candidate_v3_registry())

    def fixture_material(registry_version="v2"):
        pins, material, value = real_material(registry_version)
        if registry_version == "v3":
            snapshot = dict(material) | promotion_files
            material = tuple(sorted(snapshot.items()))
            pins = {name: hashlib.sha256(raw).hexdigest() for name, raw in material}
            value = json.loads(snapshot["standards/agent-model-registry.v3.yaml"])
        return pins, material, value

    def refused(root, expected, *args, **kwargs):
        before = (root / "case.json").read_bytes()
        try:
            runtime.dispatch_plan(root, *args, **kwargs)
        except runtime.AuthoringError as exc:
            return exc.code == expected and (root / "case.json").read_bytes() == before
        return False

    with tempfile.TemporaryDirectory(prefix="agent-council-effort-") as temporary:
        root = Path(temporary).resolve()
        candidate_root = root / "candidate"
        runtime.init_case(candidate_root, root, "case-candidate-effort", "R1")
        candidate_state = json.loads((candidate_root / "case.json").read_text())
        rows.append(("new-case-defaults-to-v3", candidate_state["registry"]["registry_version"] == "v3", "new cases cannot silently select the historical v2 catalog"))
        rows.append(("v3-init-pins-catalog-and-policy", all(path in candidate_state["policy_bundle"]["artifact_pins"] for path in ("standards/agent-model-registry.v3.yaml", "standards/agent-model-registry.schema.v3.yaml", "standards/model-qualifications/provider-catalog-refresh.v3.yaml")), "new v3 cases pin exact catalog, schema and catalog policy bytes"))
        try:
            runtime.dispatch_plan(candidate_root, "codex", "ultimate_intelligence", "context-candidate")
            candidate_refused = False
        except runtime.AuthoringError:
            candidate_refused = True
        rows.append(("v3-candidate-binding-fails-closed", candidate_refused, "catalog availability never grants dispatch authority"))

        with patch.object(runtime, "_pinned_artifact_material", fixture_material):
            case_root = root / "qualified-fixture"
            runtime.init_case(case_root, root, "case-qualified-effort", "R1", registry_version="v3")
            for provider in ("codex", "claude_code"):
                for role in ROLES:
                    selected = next(item for item in catalog["bindings"] if item["provider"] == provider and item["tier"] == role)
                    effort = expected_defaults[(provider, role)]
                    context_id = f"context-{provider}-{role}"
                    kind = "routing" if role == "ultimate_intelligence" else "review" if role == "operational_intelligence" else "implementation"
                    runtime.capture_capability(case_root, provider, selected["model_id"], [effort], context_id, None)
                    plan = runtime.dispatch_plan(case_root, provider, role, context_id)
                    rows.append((f"v3-default-{provider}-{role}", plan["effort"] == effort, "omitted effort resolves from exact provider role binding"))
                    result = runtime.dispatch_capture(case_root, provider, plan["plan_nonce"], f"task-{provider}-{role}", selected["model_id"], effort, context_id, "output-effort-contract", kind)
                    saved = json.loads((case_root / "case.json").read_text())
                    payload = saved["events"][-1]["payload"]
                    rows.append((f"v3-capture-{provider}-{role}", result["code"] == "DISPATCH_CAPTURED" and payload["selected_effort"] == payload["attested_effort"] == effort and payload["capability_efforts"] == [effort], "receipt preserves exact effort, including explicit null"))
                    if role in {"technical_tactical_intelligence", "worker_intelligence"}:
                        case_view = {key: saved[key] for key in ("registry", "route", "engineering_candidate", "cycle_id")}
                        case_view.update(provider_capability_receipt=saved["capabilities"][context_id], provider_dispatch_receipt=result["receipt"])
                        reduced = {"active": {"dispatch": saved["events"][-1]}, "history": {"packet": {"record_type": "packet", "payload": {"bounded_worker": True}}}}
                        selected_effort, problem = runtime._route_and_provider(case_view, reduced)
                        rows.append((f"v3-role-policy-resolution-{provider}-{role}", problem is None and selected_effort == effort, "implementation resolves the requested role even when one model holds two roles"))
                    if role == "worker_intelligence" and provider == "claude_code":
                        rows.append(("v3-haiku-worker-effort-refused", refused(case_root, "EFFORT_POLICY_INVALID", provider, role, context_id, "high"), "unsupported worker effort cannot be requested"))
                    if role == "technical_tactical_intelligence" and provider == "codex":
                        rows.append(("v3-sol-effort-downgrade-refused", refused(case_root, "EFFORT_POLICY_INVALID", provider, role, context_id, "low"), "binding default remains a minimum"))
                        rows.append(("v3-sol-null-effort-refused", refused(case_root, "EFFORT_POLICY_INVALID", provider, role, context_id, None), "null is not a bypass for a model with effort controls"))
                        rows.append(("v3-sol-unevidenced-escalation-refused", refused(case_root, "EFFORT_POLICY_INVALID", provider, role, context_id, "high"), "effort above a binding default requires evidence"))
                context_id = f"context-unavailable-{provider}"
                rows.append((f"v3-missing-capability-{provider}", refused(case_root, "CAPABILITY_REQUIRED", provider, "ultimate_intelligence", context_id), "v3 plans require capability evidence before selecting effort"))
            runtime.capture_capability(case_root, "codex", "gpt-6-sol", ["high"], "context-wrong-effort", None)
            rows.append(("v3-capability-effort-mismatch", refused(case_root, "PROVIDER_RECEIPT_MISMATCH", "codex", "operational_intelligence", "context-wrong-effort"), "native capability must include the selected binding default"))
            runtime.capture_capability(case_root, "codex", "gpt-6-astra", ["xhigh"], "context-freshness", None)
            fresh_plan = runtime.dispatch_plan(case_root, "codex", "ultimate_intelligence", "context-freshness")
            def capture_refused(expected):
                before = (case_root / "case.json").read_bytes()
                try:
                    runtime.dispatch_capture(case_root, "codex", fresh_plan["plan_nonce"], "task-freshness", "gpt-6-astra", "xhigh", "context-freshness", "output-freshness", "routing")
                except runtime.AuthoringError as exc:
                    return exc.code == expected and (case_root / "case.json").read_bytes() == before
                return False
            class Tomorrow(datetime):
                @classmethod
                def now(cls, tz=None):
                    return datetime.now(tz) + timedelta(days=2)
            with patch.object(runtime, "datetime", Tomorrow):
                rows.append(("v3-plan-rechecks-capability-freshness", refused(case_root, "CAPABILITY_STALE", "codex", "ultimate_intelligence", "context-freshness"), "a once-valid capability cannot authorize a dispatch after its TTL"))
                rows.append(("v3-capture-rechecks-capability-freshness", capture_refused("CAPABILITY_STALE"), "capability expiry before capture refuses without consuming the plan"))
            runtime.capture_capability(case_root, "codex", "gpt-6-astra", ["xhigh"], "context-freshness", None)
            rows.append(("v3-capability-refresh-invalidates-existing-plan", capture_refused("DISPATCH_PLAN_IDENTITY_MISMATCH"), "even an identical model/effort observation cannot replace the exact planned capability receipt"))
            fresh_plan = runtime.dispatch_plan(case_root, "codex", "ultimate_intelligence", "context-freshness")
            retired = json.loads(json.dumps(catalog))
            retired["bindings"][0]["status"] = "retired"
            retired["bindings"][0]["lifecycle"] = {"retired_at": FIXTURE_NOW, "reason": "Provider retired this model", "replacement_binding_id": None}
            seal_registry(retired)
            read_text = Path.read_text
            live_catalog = PACKAGE / "standards/agent-model-registry.v3.yaml"
            def current_catalog(path, *args, **kwargs):
                return json.dumps(retired) if path == live_catalog else read_text(path, *args, **kwargs)
            with patch.object(Path, "read_text", current_catalog):
                rows.append(("v3-current-retirement-vetoes-pinned-case", refused(case_root, "BINDING_RETIRED", "codex", "ultimate_intelligence", "context-freshness"), "current exact-binding retirement blocks new execution without rewriting pinned history"))
                rows.append(("v3-current-retirement-vetoes-pending-capture", capture_refused("DISPATCH_PLAN_STALE"), "retirement after planning invalidates capture and leaves the plan unconsumed"))
    rows.append(("v3-null-outcome-preserved", runtime._outcome("accepted", "CASE_ACCEPTED", None).get("effort", "missing") is None, "an accepted no-effort result serializes an explicit null"))
    return rows


def test_model_resilience_contracts() -> list[tuple[str, bool, str]]:
    """Synthetic selector contracts do not supply native qualification evidence."""
    rows = []
    spec = importlib.util.spec_from_file_location("agent_council_resilience_contracts", RUNTIME)
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    catalog = candidate_v3_registry()
    role = "operational_intelligence"
    primary = next(item for item in catalog["bindings"] if item["provider"] == "codex" and item["tier"] == role)
    primary["status"] = "qualified"
    primary["selection"] = {"role": "primary", "priority": 0, "fallback_for": []}
    reserve = json.loads(json.dumps(primary))
    reserve.update(binding_id="codex-reserve-a", model_id="qualified-reserve-model", selection={"role": "reserve", "priority": 1, "fallback_for": []})
    second = json.loads(json.dumps(reserve)); second.update(binding_id="codex-reserve-b", model_id="qualified-second-reserve")
    higher = next(item for item in catalog["bindings"] if item["provider"] == "codex" and item["tier"] == "ultimate_intelligence")
    higher["status"] = "qualified"
    higher["qualified_roles"] = [role, higher["tier"]]
    higher["selection"] = {"role": "primary", "priority": 0, "fallback_for": [primary["binding_id"]]}
    catalog["bindings"].extend([reserve, second])
    catalog["provider_states"]["codex"]["council_status"] = "partially_qualified"
    for item in catalog["bindings"]:
        item["binding_sha256"] = digest({key: value for key, value in item.items() if key != "binding_sha256"})
    catalog["registry_sha256"] = digest({key: value for key, value in catalog.items() if key != "registry_sha256"})
    rows.append(("resilience-registry-selection-valid", runtime._registry_valid(catalog, catalog), "partial provider qualification and explicit fallback edges retain exact binding qualification"))
    def capability(models, **changes):
        value = {"receipt_type": "provider_capability", "receipt_id": "capability-resilience", "provider": "codex", "observed_at": FIXTURE_NOW, "context_id": "context-resilience", "models": models, "efforts": ["xhigh"]} | changes
        value["receipt_sha256"] = digest(value)
        return value
    def resolve(value, selected_catalog=None):
        return runtime._resolve_binding(selected_catalog or catalog, "codex", role, value, "context-resilience")
    def refuses(value, expected, selected_catalog=None):
        try:
            resolve(value, selected_catalog)
        except runtime.AuthoringError as exc:
            return exc.code == expected
        return False
    selected, resolution = resolve(capability([primary["model_id"], reserve["model_id"], higher["model_id"]]))
    rows.append(("resilience-primary-preferred", selected == primary and resolution["kind"] == "primary", "available primary wins over qualified reserves and higher tiers"))
    available = capability([reserve["model_id"], second["model_id"], higher["model_id"]])
    selected, resolution = resolve(available)
    rows.append(("resilience-deterministic-same-role", selected == reserve and resolution["kind"] == "same_role_fallback", "same-role reserve wins before higher tier with binding ID breaking equal priorities"))
    reversed_catalog = dict(catalog, bindings=list(reversed(catalog["bindings"])))
    rows.append(("resilience-order-independent", resolve(available, reversed_catalog)[0] == reserve, "registry array order cannot change dispatch selection"))
    selected, resolution = resolve(capability([higher["model_id"]]))
    rows.append(("resilience-explicit-higher-tier", selected == higher and resolution["kind"] == "higher_tier_fallback" and resolution["requested_binding_id"] == primary["binding_id"], "higher tier requires an explicit edge to the requested primary"))
    for label, coverage in (("missing", None), ("wrong-role", [higher["tier"]]), ("empty", [])):
        denied = json.loads(json.dumps(catalog))
        binding = next(item for item in denied["bindings"] if item["binding_id"] == higher["binding_id"])
        if coverage is None:
            binding.pop("qualified_roles")
        else:
            binding["qualified_roles"] = coverage
        binding["binding_sha256"] = digest({key: value for key, value in binding.items() if key != "binding_sha256"})
        denied["registry_sha256"] = digest({key: value for key, value in denied.items() if key != "registry_sha256"})
        rows.append(("resilience-" + label + "-role-coverage-refused", refuses(capability([higher["model_id"]]), "ROLE_QUALIFICATION_REQUIRED", denied), "a higher-tier fallback edge never supplies missing requested-role qualification"))
        forged_payload = dict(binding, selected_effort="xhigh", model_resolution=resolution)
        rows.append(("resilience-" + label + "-role-coverage-replay-refused", not runtime._resolution_matches(denied, forged_payload, role, capability([higher["model_id"]])), "replay cannot recover authority from an uncovered fallback"))
    for label, coverage in (("duplicate", [higher["tier"], higher["tier"]]), ("unknown", [higher["tier"], "invented_role"]), ("own-tier-missing", [role]), ("wrong-shape", higher["tier"])):
        denied = json.loads(json.dumps(catalog))
        binding = next(item for item in denied["bindings"] if item["binding_id"] == higher["binding_id"])
        binding["qualified_roles"] = coverage
        binding["binding_sha256"] = digest({key: value for key, value in binding.items() if key != "binding_sha256"})
        denied["registry_sha256"] = digest({key: value for key, value in denied.items() if key != "registry_sha256"})
        rows.append(("resilience-" + label + "-coverage-registry-refused", not runtime._registry_valid(denied, denied), "resealed coverage must name unique known roles including the binding tier"))
    try:
        runtime._resolve_binding(catalog, "codex", role, capability([higher["model_id"]], efforts=["ultra"]), "context-resilience", "ultra")
        fallback_effort_refused = False
    except runtime.AuthoringError as exc:
        fallback_effort_refused = exc.code == "EFFORT_POLICY_INVALID"
    rows.append(("resilience-fallback-nondefault-effort-refused", fallback_effort_refused, "requested-role coverage proves only the binding default effort even if capability advertises another effort"))
    denied = json.loads(json.dumps(catalog))
    next(item for item in denied["bindings"] if item["binding_id"] == higher["binding_id"])["selection"]["fallback_for"] = []
    rows.append(("resilience-implicit-higher-tier-refused", refuses(capability([higher["model_id"]]), "PROVIDER_RECEIPT_MISMATCH", denied), "model rank alone cannot grant a role substitution"))
    for status in ("candidate", "revoked", "hard_expired", "retired"):
        denied = json.loads(json.dumps(catalog))
        next(item for item in denied["bindings"] if item["binding_id"] == reserve["binding_id"])["status"] = status
        rows.append(("resilience-" + status + "-reserve-refused", refuses(capability([reserve["model_id"]]), "PROVIDER_RECEIPT_MISMATCH", denied), "available models must hold a currently qualified binding"))
    for label, changes, code in (
        ("stale", {"observed_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()}, "CAPABILITY_STALE"),
        ("future", {"observed_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}, "CAPABILITY_STALE"),
        ("offset-missing", {"observed_at": "2026-10-01T12:00:00"}, "SCHEMA_VALIDATION_FAILED"),
        ("wrong-context", {"context_id": "context-other"}, "PROVIDER_RECEIPT_MISMATCH"),
        ("wrong-provider", {"provider": "claude_code"}, "PROVIDER_RECEIPT_MISMATCH"),
        ("wrong-effort", {"efforts": ["low"]}, "PROVIDER_RECEIPT_MISMATCH"),
    ):
        rows.append(("resilience-" + label + "-refused", refuses(capability([reserve["model_id"]], **changes), code), "capability identity, freshness and exact effort remain dispatch prerequisites"))
    selected, resolution = resolve(available)
    payload = dict(selected, selected_effort="xhigh", model_resolution=resolution)
    rows.append(("resilience-fallback-replay", runtime._resolution_matches(catalog, payload, role, available), "captured fallback replays against exact capability and pinned policy"))
    payload["model_resolution"] = dict(resolution, kind="higher_tier_fallback")
    rows.append(("resilience-fallback-tamper-refused", not runtime._resolution_matches(catalog, payload, role, available), "caller cannot relabel fallback provenance"))
    different = json.loads(json.dumps(catalog))
    different_primary = next(item for item in different["bindings"] if item["binding_id"] == primary["binding_id"])
    different_primary["reasoning"]["default_effort"] = "medium"
    different_primary["binding_sha256"] = digest({key: value for key, value in different_primary.items() if key != "binding_sha256"})
    different["registry_sha256"] = digest({key: value for key, value in different.items() if key != "registry_sha256"})
    different_available = capability([primary["model_id"], higher["model_id"]])
    selected, resolution = resolve(different_available, different)
    payload = dict(selected, selected_effort="xhigh", model_resolution=resolution)
    rows.append(("resilience-different-defaults-replay", resolution["requested_effort"] == "binding_default" and resolution["kind"] == "higher_tier_fallback" and runtime._resolution_matches(different, payload, role, different_available), "omitted effort intent survives a higher-tier fallback with a different binding default"))
    selected, explicit = runtime._resolve_binding(catalog, "codex", role, available, "context-resilience", "xhigh")
    rows.append(("resilience-explicit-effort-preserved", explicit["requested_effort"] == "xhigh" and runtime._resolution_matches(catalog, dict(selected, selected_effort="xhigh", model_resolution=explicit), role, available), "explicit caller effort is retained separately from the resolved effort"))
    v2 = json.loads((PACKAGE / "standards/agent-model-registry.v2.yaml").read_text())
    historical = dict(next(item for item in v2["bindings"] if item["status"] == "revoked"), status="qualified")
    try:
        runtime._require_current_binding_eligible(historical, "v2")
        vetoed = False
    except runtime.AuthoringError as exc:
        vetoed = exc.code == "BINDING_RETIRED"
    rows.append(("resilience-v2-current-revocation-veto", vetoed, "a historical qualified v2 binding cannot override its current packaged revocation"))
    retired_registry = json.loads(json.dumps(catalog))
    retired_primary = next(item for item in retired_registry["bindings"] if item["binding_id"] == primary["binding_id"])
    retired_primary["status"] = "retired"
    retired_primary["lifecycle"] = {"retired_at": FIXTURE_NOW, "reason": "Provider retired this binding", "replacement_binding_id": reserve["binding_id"]}
    retired_primary["binding_sha256"] = digest({key: value for key, value in retired_primary.items() if key != "binding_sha256"})
    retired_registry["registry_sha256"] = digest({key: value for key, value in retired_registry.items() if key != "registry_sha256"})
    all_available = capability([primary["model_id"], reserve["model_id"], higher["model_id"]])
    selected, resolution = runtime._resolve_binding(catalog, "codex", role, all_available, "context-resilience", current_registry=retired_registry)
    rows.append(("resilience-current-retirement-selects-qualified-reserve", selected == reserve and resolution["kind"] == "same_role_fallback" and resolution["current_registry_sha256"] == retired_registry["registry_sha256"], "a still-visible retired primary is skipped before testing the qualified reserve"))
    payload = dict(selected, selected_effort="xhigh", model_resolution=resolution)
    rows.append(("resilience-retirement-snapshot-replays", runtime._resolution_matches(catalog, payload, role, all_available), "historical fallback replays against the captured eligibility snapshot without package reads"))
    tampered = json.loads(json.dumps(payload))
    next(item for item in tampered["model_resolution"]["eligibility_registry"]["bindings"] if item["binding_id"] == primary["binding_id"])["status"] = "qualified"
    rows.append(("resilience-eligibility-snapshot-tamper-refused", not runtime._resolution_matches(catalog, tampered, role, all_available), "eligibility snapshot content must match its registry and binding hashes"))
    fixture_spec = importlib.util.spec_from_file_location("agent_council_resilience_promotion_fixtures", PACKAGE / "scripts/Test-AgentCouncilPromotion.py")
    fixture_module = importlib.util.module_from_spec(fixture_spec)
    fixture_spec.loader.exec_module(fixture_module)
    candidate = json.loads(json.dumps(catalog))
    for item in candidate["bindings"]:
        item["status"] = "candidate"
        item.pop("qualified_roles", None)
        item["binding_sha256"] = digest({key: value for key, value in item.items() if key != "binding_sha256"})
    for summary in candidate["provider_states"].values():
        summary["council_status"] = "fail_closed_until_qualified"
    candidate["registry_sha256"] = digest({key: value for key, value in candidate.items() if key != "registry_sha256"})
    proof_files, _ = fixture_module.fixture(registry_value=candidate)
    real_material = runtime._pinned_artifact_material
    def fixture_material(registry_version="v3"):
        _, material, _ = real_material(registry_version)
        snapshot = dict(material) | proof_files
        return {name: hashlib.sha256(raw).hexdigest() for name, raw in snapshot.items()}, tuple(sorted(snapshot.items())), json.loads(snapshot["standards/agent-model-registry.v3.yaml"])
    with tempfile.TemporaryDirectory(prefix="agent-council-resilience-") as temporary:
        root = Path(temporary).resolve()
        case_root = root / "case"
        with patch.object(runtime, "_pinned_artifact_material", fixture_material):
            runtime.init_case(case_root, root, "case-resilience", "R1")
        for label, expected in (("same-role", reserve),):
            context = "context-" + label
            runtime.capture_capability(case_root, "codex", expected["model_id"], ["xhigh"], context, None)
            plan = runtime.dispatch_plan(case_root, "codex", role, context)
            result = runtime.dispatch_capture(case_root, "codex", plan["plan_nonce"], "task-" + label, expected["model_id"], "xhigh", context, "output-" + label, "review")
            saved = runtime._read_local_case(case_root)
            rows.append(("resilience-" + label + "-dispatch-capture-replay", result["code"] == "DISPATCH_CAPTURED" and plan["binding_id"] == expected["binding_id"] and runtime._authority_dispatch_valid(saved["events"][-1], saved, role), "qualified fallback traverses immutable planning, capture and authority replay with pinned promotion proof"))
            rows.append(("resilience-" + label + "-notice-selected-cost", plan["user_notice"]["cost_class"] == runtime._NOTICE_COST_CLASS[expected["tier"]] and plan["user_notice"]["role"] == role, "notice retains requested responsibility while exposing selected model cost class"))
        context = "context-retirement-reserve"
        runtime.capture_capability(case_root, "codex", reserve["model_id"], ["xhigh"], context, None)
        read_text = Path.read_text
        catalog_path = PACKAGE / "standards/agent-model-registry.v3.yaml"
        def retired_catalog(path, *args, **kwargs):
            return json.dumps(retired_registry) if path == catalog_path else read_text(path, *args, **kwargs)
        with patch.object(Path, "read_text", retired_catalog):
            plan = runtime.dispatch_plan(case_root, "codex", role, context)
            result = runtime.dispatch_capture(case_root, "codex", plan["plan_nonce"], "task-retired-primary", reserve["model_id"], "xhigh", context, "output-retired-primary", "review")
        saved = runtime._read_local_case(case_root)
        rows.append(("resilience-retirement-reserve-persisted-replay", plan["model_resolution"]["current_registry_sha256"] == retired_registry["registry_sha256"] and result["code"] == "DISPATCH_CAPTURED" and runtime._authority_dispatch_valid(saved["events"][-1], saved, role), "retirement-selected reserve preserves its exact eligibility snapshot after current package changes"))
        plan = runtime.dispatch_plan(case_root, "codex", role, context)
        before = (case_root / "case.json").read_bytes()
        with patch.object(Path, "read_text", retired_catalog):
            try:
                runtime.dispatch_capture(case_root, "codex", plan["plan_nonce"], "task-package-changed", reserve["model_id"], "xhigh", context, "output-package-changed", "review")
                changed_refused = False
            except runtime.AuthoringError as exc:
                changed_refused = exc.code == "DISPATCH_PLAN_STALE"
        rows.append(("resilience-package-change-invalidates-unaffected-reserve-plan", changed_refused and (case_root / "case.json").read_bytes() == before, "any changed eligibility registry invalidates capture even when the selected reserve remains eligible"))
        role_candidate = candidate_v3_registry()
        role_primary = next(item for item in role_candidate["bindings"] if item["provider"] == "claude_code" and item["tier"] == role)
        role_higher = next(item for item in role_candidate["bindings"] if item["provider"] == "claude_code" and item["tier"] == "ultimate_intelligence")
        role_higher["selection"] = {"role": "primary", "priority": 0, "fallback_for": [role_primary["binding_id"]]}
        role_higher["binding_sha256"] = digest({key: value for key, value in role_higher.items() if key != "binding_sha256"})
        role_candidate["registry_sha256"] = digest({key: value for key, value in role_candidate.items() if key != "registry_sha256"})
        proof_files, _ = fixture_module.fixture(registry_value=role_candidate, binding_ids=[item["binding_id"] for item in role_candidate["bindings"] if item["provider"] == "claude_code"], role_protocol=True)
        role_root = root / "role-protocol-case"
        with patch.object(runtime, "_pinned_artifact_material", fixture_material):
            runtime.init_case(role_root, root, "case-role-protocol-resilience", "R1")
        context = "context-role-protocol-fallback"
        runtime.capture_capability(role_root, "claude_code", role_higher["model_id"], ["high"], context, None)
        plan = runtime.dispatch_plan(role_root, "claude_code", role, context)
        result = runtime.dispatch_capture(role_root, "claude_code", plan["plan_nonce"], "task-role-protocol-fallback", role_higher["model_id"], "high", context, "output-role-protocol-fallback", "review")
        saved = runtime._read_local_case(role_root)
        rows.append(("resilience-higher-tier-dispatch-capture-replay", result["code"] == "DISPATCH_CAPTURED" and plan["binding_id"] == role_higher["binding_id"] and runtime._authority_dispatch_valid(saved["events"][-1], saved, role), "cumulative role-protocol proof authorizes higher fallback through planning, capture and protected authority replay"))
        rows.append(("resilience-higher-tier-notice-selected-cost", plan["user_notice"]["cost_class"] == runtime._NOTICE_COST_CLASS[role_higher["tier"]] and plan["user_notice"]["role"] == role, "notice retains requested responsibility while exposing qualified fallback model cost"))
    return rows


def test_promotion_runtime_contracts() -> list[tuple[str, bool, str]]:
    """Synthetic structural proof enables tests only, never native qualification."""
    rows: list[tuple[str, bool, str]] = []
    spec = importlib.util.spec_from_file_location("agent_council_promotion_runtime", RUNTIME)
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    promotion = runtime._promotion_verifier()
    fixture_spec = importlib.util.spec_from_file_location("agent_council_promotion_fixture_runtime", PACKAGE / "scripts/Test-AgentCouncilPromotion.py")
    fixtures = importlib.util.module_from_spec(fixture_spec)
    fixture_spec.loader.exec_module(fixtures)
    _, baseline, _ = runtime._pinned_artifact_material()

    with tempfile.TemporaryDirectory(prefix="agent-council-public-promotion-") as temporary:
        root = Path(temporary).resolve()
        package = root / "public-package"
        private_files, private_proof = fixtures.fixture(package, binding_ids=["claude-code-v3-ultimate"], registry_value=candidate_v3_registry())
        closure = promotion.export_public_promotion_bytes(private_files,
            expected_package_sha256=private_proof["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"],
            expected_proof_sha256=promotion.sha256(private_files[promotion.PROOF_PATH]), candidate_root=package)
        public_files = dict(baseline) | {name: private_files[name] for name in private_proof["promoted_release_binding"]["behavioral_identity"]["paths"]}
        public_files[promotion.INVENTORY_PATH] = private_files[promotion.INVENTORY_PATH]
        public_files.update(closure)
        for name, raw in public_files.items():
            target = package / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        with patch.object(runtime, "_PACKAGE", package):
            case_root = root / "public-case"
            runtime.init_case(case_root, root, "case-public-promotion", "R1")
            state = json.loads((case_root / "case.json").read_text())
            pins = state["policy_bundle"]["artifact_pins"]
            private_only = set(private_files) - set(public_files)
            rows.append(("v3-public-proof-creates-offline-case-without-private-evidence", not private_only.intersection(pins) and set(closure) <= set(pins), "public proof and candidate archive suffice; private transcripts and loader roots are absent"))
            package.rename(root / "unavailable-installed-package")
            runtime._require_case_promotion(state, case_root)
            rows.append(("v3-public-pinned-proof-survives-unavailable-package", True, "public verification uses pinned package bytes after installed package removal"))

    def rejects(call, code: str | None = None) -> bool:
        try:
            call()
        except runtime.AuthoringError as exc:
            return exc.code == code if code else exc.code.startswith("PROMOTION_")
        return False

    # Defense at the runtime boundary also refuses a legacy verifier success
    # result when the frozen package declares the role qualification protocol.
    legacy_files, legacy_proof = fixtures.fixture(binding_ids=["claude-code-v3-ultimate"], registry_value=candidate_v3_registry())
    legacy_registry = json.loads(legacy_files[promotion.REGISTRY_PATH])
    legacy_result = {"promoted_release_binding": legacy_proof["promoted_release_binding"],
                     "promotion_proof_sha256": promotion.sha256(legacy_files[promotion.PROOF_PATH]),
                     "qualification_protocol_version": None}
    for label, declared_files, version in (
        ("legacy-proof", list(promotion.protocol.PROTOCOL_FILES), None),
        ("wrong-version", list(promotion.protocol.PROTOCOL_FILES), "agent-council.role-qualification/v0"),
        ("partial-marker", [promotion.protocol.PROTOCOL_FILES[0]], promotion.ROLE_PROTOCOL),
        ("missing-coverage", list(promotion.protocol.PROTOCOL_FILES), promotion.ROLE_PROTOCOL),
    ):
        declared = json.loads(json.dumps(legacy_result))
        declared["promoted_release_binding"]["behavioral_identity"]["paths"].extend(declared_files)
        declared["qualification_protocol_version"] = version
        with patch.object(promotion, "verify_promotion_bytes", return_value=declared):
            denied = rejects(lambda: runtime._verify_promotion_snapshot(legacy_registry, legacy_files, runtime._promotion_binding(declared), PACKAGE), "PROMOTION_ROLE_PROTOCOL_REQUIRED")
        rows.append(("v3-runtime-protocol-downgrade-" + label + "-refused", denied, "a verifier success cannot grant runtime authority when frozen package protocol and qualified-role evidence disagree"))

    with tempfile.TemporaryDirectory(prefix="agent-council-role-downgrade-") as temporary:
        root = Path(temporary).resolve()
        for label in ("private", "public"):
            package = root / (label + "-package")
            downgrade_files, downgrade_proof = fixtures.fixture(package, binding_ids=["claude-code-v3-ultimate"], include_protocol_package=True, registry_value=candidate_v3_registry())
            if label == "public":
                # Reproduce a proof emitted by the historical exporter before
                # the package-driven protocol gate existed. Verification below
                # is entirely real and runs after this fixture-only patch ends.
                with patch.object(promotion, "required_protocol", return_value=None):
                    downgrade_files.update(promotion.export_public_promotion_bytes(downgrade_files,
                        expected_package_sha256=downgrade_proof["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"],
                        expected_proof_sha256=promotion.sha256(downgrade_files[promotion.PROOF_PATH]), candidate_root=package))
            for name, raw in (dict(baseline) | downgrade_files).items():
                target = package / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            case_root = root / (label + "-case")
            with patch.object(runtime, "_PACKAGE", package):
                denied = rejects(lambda: runtime.init_case(case_root, root, "case-" + label + "-protocol-downgrade", "R1"))
            rows.append(("v3-" + label + "-legacy-proof-over-role-package-refused", denied and not case_root.exists(), "self-consistent legacy proof over a role-protocol package cannot create runtime authority or publish a case"))

    with tempfile.TemporaryDirectory(prefix="agent-council-promotion-runtime-") as temporary:
        root = Path(temporary).resolve()
        package = root / "package"
        fixture_files, proof = fixtures.fixture(package, registry_value=candidate_v3_registry())
        files = dict(baseline) | fixture_files
        alias_document = write_case("resolver_default_effort", root / "legacy-version-alias")
        alias_document["registry"]["registry_version"] = "v3"
        alias_document["registry"]["registry_sha256"] = digest({key: value for key, value in alias_document["registry"].items() if key != "registry_sha256"})
        alias_document["identity"].update(registry_version="v3", registry_sha256=alias_document["registry"]["registry_sha256"])
        previous = None
        for item in alias_document["events"]:
            item["identity"] = dict(alias_document["identity"])
            item["payload"]["previous_event_sha256"] = previous
            item["event_sha256"] = digest({key: value for key, value in item.items() if key != "event_sha256"})
            previous = item["event_sha256"]
            path = Path(alias_document["case_root"]) / "events" / (item["event_id"] + ".json")
            path.chmod(0o600); path.write_bytes(canonical(item) + b"\n"); path.chmod(0o400)
        rows.append(("v3-version-label-cannot-alias-historical-schema", structural_refusal(runtime.evaluate_contract_case(alias_document), "SCHEMA_VALIDATION_FAILED"), "resealed imported v2 records cannot use the reserved v3 registry label to bypass promotion"))
        for name, raw in files.items():
            path = package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        with patch.object(runtime, "_PACKAGE", package):
            proof_path = package / promotion.PROOF_PATH
            original_proof = proof_path.read_bytes()
            proof_path.unlink()
            refused_root = root / "self-declared"
            rows.append(("v3-fresh-self-declared-qualification-refused", rejects(lambda: runtime.init_case(refused_root, root, "case-self-declared", "R1")) and not refused_root.exists(), "rehashed qualified registry cannot create a case without promotion proof"))
            proof_path.write_bytes(original_proof)
            registry_path = package / promotion.REGISTRY_PATH
            registry_path.write_bytes(canonical(registry("historical")))
            rows.append(("v3-fresh-historical-registry-substitution-refused", rejects(lambda: runtime.init_case(refused_root, root, "case-version-substitution", "R1"), "PINNED_ARTIFACT_MISSING") and not refused_root.exists(), "fresh v3 pin path cannot carry a historical registry"))
            registry_path.write_bytes(files[promotion.REGISTRY_PATH])
            case_root = root / "verified"
            runtime.init_case(case_root, root, "case-promoted-runtime", "R1")
            recovery_root = root / "promotion-recovery"
            runtime.init_case(recovery_root, root, "case-promoted-recovery", "R1")
            saved = runtime._read_local_case(case_root)
            pins = saved["policy_bundle"]["artifact_pins"]
            rows.append(("v3-qualified-case-pins-complete-promotion", set(fixture_files) <= set(pins) and saved["policy_bundle"]["promotion_binding"]["proof_sha256"] == promotion.sha256(original_proof), "case binds every synthetic promotion artifact and its exact proof"))
            runtime.evidence_add(case_root, "evidence-escalation", "behavioral_test", behavioral_evidence(saved["engineering_candidate"], cycle_id=saved["cycle_id"]))
            for role, kind in (("ultimate_intelligence", "routing"), ("technical_tactical_intelligence", "implementation")):
                binding = next(item for item in saved["registry"]["bindings"] if item["provider"] == "codex" and item["tier"] == role)
                effort = binding["reasoning"]["default_effort"]
                context = "context-promotion-" + kind
                runtime.capture_capability(case_root, "codex", binding["model_id"], list(binding["reasoning"]["allowed_efforts"]), context, None)
                plan = runtime.dispatch_plan(case_root, "codex", role, context)
                runtime.dispatch_capture(case_root, "codex", plan["plan_nonce"], "task-promotion-" + kind, binding["model_id"], effort, context, "output-promotion-" + kind, kind)
            state = runtime._read_local_case(case_root)
            document = runtime._authoring_document(state, case_root)
            result = runtime.evaluate_contract_case(document)
            rows.append(("v3-qualified-import-evaluates-pinned-proof", result.get("code") == "BINDING_EFFORT_RESOLVED", "imported evaluation verifies the same pinned promotion evidence; observed " + result.get("code", "missing")))
            rows.append(("v3-qualified-bundle-builds", runtime.build_bundle(case_root)["code"] == "EXECUTING_BUNDLE_BUILT", "bundle creation verifies promotion before writing"))
            # A valid escalation gate cannot authorize an unqualified effort.
            runtime.gate_record(case_root, "ultimate-routing", "evidence-escalation", "complexity_escalation")
            rows.append(("v3-evidenced-nondefault-effort-refused", rejects(lambda: runtime.dispatch_plan(case_root, "codex", "ultimate_intelligence", "context-promotion-routing", "ultra"), "EFFORT_POLICY_INVALID"), "default-only promotion never grants another supported effort"))
            # The saved case consumes only its snapshot after package rotation.
            (package / promotion.REGISTRY_PATH).write_bytes(b"later installed registry\n")
            proof_path.write_bytes(b"later installed proof\n")
            rotated = runtime.evaluate_contract_case(runtime._authoring_document(runtime._read_local_case(case_root), case_root))
            rows.append(("v3-promotion-survives-installed-package-rotation", runtime.build_bundle(case_root)["code"] == "EXECUTING_BUNDLE_BUILT" and rotated.get("result") != "refused", "later installed evidence cannot replace or invalidate pinned bytes; observed " + rotated.get("code", "missing")))
            implementation = next(item for item in runtime._read_local_case(case_root)["dispatch_plans"].values() if item["decision_kind"] == "implementation")
            runtime.packet_result(case_root, implementation["packet_id"], "completed", [{"gate_id": "implementation", "status": "passed"}])
            runtime.test_record(case_root, "test-normative", "evidence-escalation", "passed")
            for role, kind in (("operational_intelligence", "review"), ("ultimate_intelligence", "final")):
                binding = next(item for item in saved["registry"]["bindings"] if item["provider"] == "codex" and item["tier"] == role)
                effort = binding["reasoning"]["default_effort"]
                context = "context-promotion-" + kind
                runtime.capture_capability(case_root, "codex", binding["model_id"], [effort], context, None)
                plan = runtime.dispatch_plan(case_root, "codex", role, context, decision_kind=kind)
                runtime.dispatch_capture(case_root, "codex", plan["plan_nonce"], "task-promotion-" + kind, binding["model_id"], effort, context, "output-promotion-" + kind, kind)
            for gate_id in ROUTE_GATES["R1"][1:]:
                runtime.gate_record(case_root, gate_id, "evidence-escalation")
            pinned_proof = case_root / "pinned" / promotion.PROOF_PATH
            pinned_proof.chmod(0o600); pinned_proof.write_bytes(original_proof + b" ")
            before_close = (case_root / "case.json").read_bytes()
            before_events = sorted(path.name for path in (case_root / "events").iterdir())
            rows.append(("v3-close-tampered-promotion-atomic", rejects(lambda: runtime.close_local_case(case_root)) and (case_root / "case.json").read_bytes() == before_close and sorted(path.name for path in (case_root / "events").iterdir()) == before_events, "invalid pinned promotion refuses closure without publishing any event or state"))
            pinned_proof.write_bytes(original_proof); pinned_proof.chmod(0o400)
            try:
                closed = runtime.close_local_case(case_root)
            except runtime.AuthoringError as exc:
                closed = {"code": exc.code}
            rows.append(("v3-complete-case-closes-after-package-rotation", closed.get("code") == "CASE_CLOSED", "closure dry-run uses verified pinned promotion bytes; observed " + closed.get("code", "missing")))
            closed_state = runtime._read_local_case(case_root)
            evaluated_closed = runtime.evaluate_contract_case(runtime._authoring_document(closed_state, case_root))
            rows.append(("v3-closed-case-retains-verifiable-promotion", closed.get("code") == "CASE_CLOSED" and evaluated_closed.get("code") == "CASE_ACCEPTED" and sum(event["record_type"] == "closure" for event in closed_state["events"]) == 1 and not (case_root / runtime._PENDING_JOURNAL).exists(), "one durable closure remains evaluable against the original pinned promotion"))

        recovery_state = runtime._read_local_case(recovery_root)
        recovery_before = (recovery_root / "case.json").read_bytes()
        fault_code, _, fault_stderr = cli_fault("journal", "evidence-add", "--case-root", str(recovery_root), "--evidence-id", "evidence-recovery", "--evidence-kind", "behavioral_test", "--content-json", json.dumps(behavioral_evidence(recovery_state["engineering_candidate"], cycle_id=recovery_state["cycle_id"])))
        journal_path = recovery_root / runtime._PENDING_JOURNAL
        original_journal = journal_path.read_bytes()
        damaged_journal = json.loads(original_journal)
        proposed = json.loads(base64.b64decode(damaged_journal["state"]["bytes_b64"]))
        proposed["policy_bundle"].pop("promotion_binding")
        proposed_bytes = canonical(proposed) + b"\n"
        damaged_journal["state"].update(sha256=hashlib.sha256(proposed_bytes).hexdigest(), bytes_b64=base64.b64encode(proposed_bytes).decode("ascii"))
        journal_path.write_bytes(canonical(damaged_journal) + b"\n")
        recovery_inventory = filesystem_inventory(recovery_root)
        recover_code, recover_result, recover_stderr = cli_detail("recover-case", "--case-root", str(recovery_root))
        recovery_preserved = filesystem_inventory(recovery_root) == recovery_inventory and (recovery_root / "case.json").read_bytes() == recovery_before
        rows.append(("v3-recovery-invalid-promotion-refused-before-publication", fault_code != 0 and "Traceback" not in fault_stderr and recover_code != 0 and structural_refusal(recover_result, "PROMOTION_EVIDENCE_REQUIRED") and "Traceback" not in recover_stderr and recovery_preserved, "rehashed pending state without promotion cannot publish targets, replace state, or remove its journal"))
        retry_succeeded = False
        if recovery_preserved:
            journal_path.write_bytes(original_journal)
            retry_code, retry_result, retry_stderr = cli_detail("recover-case", "--case-root", str(recovery_root))
            retry_succeeded = retry_code == 0 and retry_result.get("code") == "CASE_RECOVERED" and "Traceback" not in retry_stderr and not journal_path.exists() and (recovery_root / "case.json").read_bytes() == base64.b64decode(json.loads(original_journal)["state"]["bytes_b64"])
        rows.append(("v3-recovery-valid-promotion-retry-publishes", retry_succeeded, "restoring the exact qualified transaction allows normal durable recovery"))

        state_path = case_root / "case.json"
        saved_bytes = state_path.read_bytes()
        state = json.loads(saved_bytes)
        def alter_state(value: dict[str, Any]) -> None:
            state_path.chmod(0o600)
            state_path.write_bytes(canonical(value) + b"\n")
        for label, mutate in (
            ("missing-binding", lambda value: value["policy_bundle"].pop("promotion_binding")),
            ("missing-artifact-pins", lambda value: value["policy_bundle"].pop("artifact_pins")),
            ("changed-package-pin", lambda value: value["policy_bundle"]["promotion_binding"].update(package_sha256="0" * 64)),
            ("changed-proof-pin", lambda value: value["policy_bundle"]["promotion_binding"].update(proof_sha256="0" * 64)),
            ("unsafe-artifact-path", lambda value: value["policy_bundle"]["artifact_pins"].update({"../escaped": "0" * 64})),
        ):
            damaged = json.loads(saved_bytes); mutate(damaged); alter_state(damaged)
            before = state_path.read_bytes()
            expected_code = "SCHEMA_VALIDATION_FAILED" if label == "missing-artifact-pins" else None
            rows.append(("v3-dispatch-" + label + "-refused", rejects(lambda: runtime.dispatch_plan(case_root, "codex", "ultimate_intelligence", "context-promotion-routing"), expected_code) and state_path.read_bytes() == before, "invalid promotion cannot mutate dispatch state"))
            imported = dict(document, policy_bundle=damaged["policy_bundle"])
            rows.append(("v3-import-" + label + "-refused", runtime.evaluate_contract_case(imported).get("result") == "refused", "imported qualified registry must carry valid pinned promotion"))
            alter_state(state)

        # Even internally consistent alternate registry hashes must match proof.
        damaged = json.loads(saved_bytes)
        changed = next(item for item in damaged["registry"]["bindings"] if item["tier"] == "worker_intelligence")
        changed["qualified_roles"] = ["worker_intelligence", "operational_intelligence"]
        changed["binding_sha256"] = digest({key: value for key, value in changed.items() if key != "binding_sha256"})
        damaged["registry"]["registry_sha256"] = digest({key: value for key, value in damaged["registry"].items() if key != "registry_sha256"})
        alter_state(damaged)
        rows.append(("v3-resealed-role-coverage-forgery-refused", rejects(lambda: runtime.dispatch_plan(case_root, "codex", "ultimate_intelligence", "context-promotion-routing"), "PROMOTION_REGISTRY_MISMATCH"), "declaring requested-role coverage and recomputing hashes cannot bypass the pinned qualification proof"))
        damaged = json.loads(saved_bytes)
        damaged["registry"]["bindings"][0]["model_id"] = "unqualified-model"
        changed = damaged["registry"]["bindings"][0]
        changed["binding_sha256"] = digest({key: value for key, value in changed.items() if key != "binding_sha256"})
        damaged["registry"]["registry_sha256"] = digest({key: value for key, value in damaged["registry"].items() if key != "registry_sha256"})
        alter_state(damaged)
        rows.append(("v3-resealed-registry-substitution-refused", rejects(lambda: runtime.build_bundle(case_root), "PROMOTION_REGISTRY_MISMATCH"), "case registry must equal the exact verified promoted registry"))
        damaged["registry"] = registry("historical")
        alter_state(damaged)
        rows.append(("v3-pinned-registry-version-downgrade-refused", rejects(lambda: runtime.build_bundle(case_root), "PROMOTION_REGISTRY_MISMATCH"), "v3 case cannot evade promotion through historical registry substitution"))
        alter_state(state)

        artifact = case_root / "pinned" / proof["binding_evidence"][0]["runs"][0]["transcript"]["path"]
        raw = artifact.read_bytes()
        artifact.chmod(0o600); artifact.write_bytes(raw + b"{}\n")
        rows.append(("v3-pinned-transcript-tamper-refused", rejects(lambda: runtime.build_bundle(case_root)), "pinned transcript hash is checked on every authority boundary"))
        artifact.write_bytes(raw)
        alias = root / "external-transcript.jsonl"; alias.write_bytes(raw)
        artifact.unlink(); artifact.symlink_to(alias)
        rows.append(("v3-pinned-symlink-refused", rejects(lambda: runtime.build_bundle(case_root)), "equal bytes through a symlink remain unsafe"))
        artifact.unlink(); os.link(alias, artifact)
        second = case_root / "pinned" / proof["binding_evidence"][0]["runs"][1]["transcript"]["path"]
        second.unlink(); os.link(alias, second)
        rows.append(("v3-pinned-file-alias-refused", rejects(lambda: runtime.build_bundle(case_root)), "aliased evidence files cannot satisfy distinct references"))
    return rows


def run(group: str) -> dict[str, Any]:
    if group not in GROUPS: raise ValueError(f"Unknown group: {group}")
    if group == "schema": rows = test_schema()
    elif group == "registry-schema": rows = test_registry_role_schema()
    elif group == "authoring": rows = test_authoring(group)
    elif group == "dispatch-contracts": rows = test_dispatch_contracts() + test_binding_effort_contracts() + test_model_resilience_contracts() + test_promotion_runtime_contracts()
    else: rows = runtime_red_cases(group)
    passed = sum(ok for _, ok, _ in rows)
    return {"group": group, "result": "passed" if passed == len(rows) else "failed", "observed": {"total": len(rows), "passed": passed, "failed": len(rows) - passed}, "assertions": [{"name": name, "passed": ok, "expectation": expectation} for name, ok, expectation in rows]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", required=True, choices=GROUPS)
    args = parser.parse_args(argv)
    result = run(args.group)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
