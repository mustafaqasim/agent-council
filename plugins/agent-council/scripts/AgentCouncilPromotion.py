#!/usr/bin/env python3
"""Verify bounded candidate-to-qualified promotion from frozen package bytes.

This module proves a constrained transformation and evidence consistency only.
JSON, transcript hashes, and an unkeyed proof digest do not authenticate a
provider. Native collection and independent acceptance remain external gates.
Claude transcript scoring replays bounded answers and observed identity only;
its workspace preparation and clean-context checks are not replayed here.
No files are changed, no providers are invoked, and Council reentry is denied.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from ClaudeQualificationHarness import (CLAIM_VOCABULARY, CURRENT_ALLOWED_ADDITIONAL_CLAIMS,
                                        V3_CANDIDATE_FILES, EXPECTED_CLAIMS, transcript_effort_matches,
                                        extract_qualification_json, validate_qualification_tail)
from ClaudeAgentProbe import verify_async_completion, verify_loader_log
import CodexQualificationHarness as codex
import QualificationProtocol as protocol


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = "standards/agent-model-registry.v3.yaml"
INVENTORY_PATH = "standards/behavioral-inventory.v1.json"
PROOF_PATH = "standards/model-qualifications/promotion.v1.json"
ARCHIVE_PATH = "standards/model-qualifications/candidate-registry.v3.json"
SCHEMA = "agent-council.promotion-proof/v1"
PUBLIC_SCHEMA = "agent-council.promotion-proof/v2"
ROLE_SCHEMA = "agent-council.promotion-proof/v3"
ROLE_PUBLIC_SCHEMA = "agent-council.promotion-proof/v4"
ROLE_PROTOCOL = protocol.VERSION
RUN_IDS = {"native-forward-run-1", "native-forward-run-2"}
TIERS = {"ultimate": "ultimate_intelligence", "operational": "operational_intelligence",
         "technical": "technical_tactical_intelligence", "worker": "worker_intelligence"}
BINDINGS = {f"{prefix}-v3-{role}": (provider, tier)
            for prefix, provider in (("codex", "codex"), ("claude-code", "claude_code"))
            for role, tier in TIERS.items()}
EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}


def fail(code: str) -> None:
    raise ValueError("PROMOTION_" + code)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def decode(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                          parse_constant=lambda _: fail("JSON_NONFINITE"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("PROMOTION_JSON_INVALID") from exc


def fields(value: Any, required: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != required:
        fail(code)
    return value


def path_name(value: Any) -> str:
    if (not isinstance(value, str) or not value or value.startswith("/") or
            "\\" in value or ":" in value or
            any(ord(char) < 32 or ord(char) == 127 for char in value) or
            any(part in {"", ".", ".."} for part in value.split("/"))):
        fail("PATH_UNSAFE")
    return value


def hash_value(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        fail("HASH_INVALID")
    return value


def text_value(value: Any) -> str:
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        fail("TEXT_INVALID")
    return value


def registry(raw: bytes, status: str | None = None) -> dict[str, Any]:
    value = fields(decode(raw), {"schema_version", "registry_version", "registry_sha256",
                                "reasoning", "provider_states", "bindings"}, "REGISTRY_INVALID")
    if (value["schema_version"] != "agent-council.model-registry/v3" or
            value["registry_version"] != "v3" or value["reasoning"] != {"policy": "per_binding"}):
        fail("REGISTRY_INVALID")
    states = value["provider_states"]
    if (not isinstance(states, dict) or not states or
            any(provider not in {"codex", "claude_code"} or not isinstance(state, dict) or
                set(state) != {"council_status"} or state["council_status"] not in
                {"qualified", "partially_qualified", "fail_closed_until_qualified"}
                for provider, state in states.items())):
        fail("PROVIDER_STATE_INVALID")
    bindings = value["bindings"]
    if not isinstance(bindings, list) or not bindings:
        fail("BINDING_SET_INVALID")
    seen = set()
    for binding in bindings:
        required = {"binding_id", "binding_sha256", "provider", "model_id", "tier", "status", "reasoning"}
        if not isinstance(binding, dict) or not required <= binding.keys() or set(binding) - required - {"selection", "lifecycle", "qualified_roles"}:
            fail("BINDING_INVALID")
        binding_id = text_value(binding["binding_id"])
        if binding_id in seen or re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{2,127}", binding_id) is None:
            fail("BINDING_SET_INVALID")
        seen.add(binding_id)
        if (binding["provider"] not in states or binding["tier"] not in TIERS.values() or
                binding["status"] not in {"candidate", "qualified", "revoked", "hard_expired", "retired"} or
                status is not None and binding["status"] != status):
            fail("BINDING_INVALID")
        if "selection" in binding:
            selection = fields(binding["selection"], {"role", "priority", "fallback_for"}, "SELECTION_INVALID")
            fallbacks = selection["fallback_for"]
            if (selection["role"] not in {"primary", "reserve"} or
                    type(selection["priority"]) is not int or selection["priority"] < 0 or
                    not isinstance(fallbacks, list) or any(not isinstance(item, str) for item in fallbacks) or
                    len(fallbacks) != len(set(fallbacks))):
                fail("SELECTION_INVALID")
        if "lifecycle" in binding:
            lifecycle = fields(binding["lifecycle"], {"retired_at", "reason", "replacement_binding_id"}, "LIFECYCLE_INVALID")
            if binding["status"] == "retired":
                text_value(lifecycle["reason"])
                try:
                    retired_at = datetime.fromisoformat(text_value(lifecycle["retired_at"]).replace("Z", "+00:00"))
                except ValueError:
                    fail("LIFECYCLE_INVALID")
                if retired_at.tzinfo is None:
                    fail("LIFECYCLE_INVALID")
            elif any(item is not None for item in lifecycle.values()):
                fail("LIFECYCLE_INVALID")
        elif binding["status"] == "retired":
            fail("LIFECYCLE_INVALID")
        text_value(binding["model_id"])
        if "qualified_roles" in binding:
            roles = binding["qualified_roles"]
            if (binding["status"] not in {"qualified", "retired"} or not isinstance(roles, list) or
                    not roles or any(role not in TIERS.values() for role in roles) or
                    len(roles) != len(set(roles)) or binding["tier"] not in roles):
                fail("QUALIFIED_ROLES_INVALID")
        reasoning = fields(binding["reasoning"], {"supported", "default_effort", "allowed_efforts"}, "REASONING_INVALID")
        efforts = reasoning["allowed_efforts"]
        if (not isinstance(efforts, list) or any(not isinstance(e, str) or e not in EFFORTS for e in efforts)
                or len(efforts) != len(set(efforts))):
            fail("REASONING_INVALID")
        if reasoning["supported"] is True:
            if not isinstance(reasoning["default_effort"], str) or reasoning["default_effort"] not in efforts:
                fail("REASONING_INVALID")
        elif reasoning["supported"] is not False or reasoning["default_effort"] is not None or efforts:
            fail("REASONING_INVALID")
        if binding["binding_sha256"] != sha256(canonical({k: v for k, v in binding.items() if k != "binding_sha256"})):
            fail("BINDING_HASH_MISMATCH")
    by_id = {binding["binding_id"]: binding for binding in bindings}
    rank = {tier: index for index, tier in enumerate(TIERS.values())}
    for binding in bindings:
        for target in binding.get("selection", {}).get("fallback_for", []):
            if (target not in by_id or target == binding["binding_id"] or
                    by_id[target]["provider"] != binding["provider"] or
                    rank[binding["tier"]] > rank[by_id[target]["tier"]]):
                fail("FALLBACK_INVALID")
        replacement = binding.get("lifecycle", {}).get("replacement_binding_id")
        if replacement is not None and (not isinstance(replacement, str) or replacement not in by_id or
                replacement == binding["binding_id"] or by_id[replacement]["provider"] != binding["provider"] or
                by_id[replacement]["tier"] != binding["tier"] or by_id[replacement]["status"] == "retired"):
            fail("LIFECYCLE_INVALID")
    if states != provider_states(bindings, states):
        fail("PROVIDER_STATE_INVALID")
    if value["registry_sha256"] != sha256(canonical({k: v for k, v in value.items() if k != "registry_sha256"})):
        fail("REGISTRY_HASH_MISMATCH")
    return value


def provider_states(bindings: list[dict[str, Any]], providers: Mapping[str, Any]) -> dict[str, Any]:
    """Provider summaries never make another provider a qualification dependency."""
    result = {}
    for provider in providers:
        active = [binding for binding in bindings if binding["provider"] == provider and
                  binding["status"] not in {"retired", "revoked", "hard_expired"}]
        qualified = sum(binding["status"] == "qualified" for binding in active)
        state = ("qualified" if active and qualified == len(active) else
                 "partially_qualified" if qualified else "fail_closed_until_qualified")
        result[provider] = {"council_status": state}
    return result


def promote_registry(candidate_bytes: bytes, binding_ids: list[str] | None = None, *,
                     qualification_protocols: Mapping[str, Any] | None = None,
                     read: Callable[[str], bytes] | None = None) -> bytes:
    """Promote selected candidates, preserving every unselected binding exactly."""
    promoted = copy.deepcopy(registry(candidate_bytes))
    candidates = {binding["binding_id"] for binding in promoted["bindings"] if binding["status"] == "candidate"}
    selected = sorted(candidates) if binding_ids is None else binding_ids
    if (not isinstance(selected, list) or not selected or any(not isinstance(item, str) for item in selected) or
            len(set(selected)) != len(selected) or not set(selected) <= candidates):
        fail("PROMOTION_SET_INVALID")
    if qualification_protocols is not None and set(qualification_protocols) != set(selected):
        fail("PROTOCOL_SET_INVALID")
    for binding in promoted["bindings"]:
        if binding["binding_id"] not in selected:
            continue
        if qualification_protocols is not None:
            expected = protocol.protocol_binding(binding, read)
            if qualification_protocols[binding["binding_id"]] != expected:
                fail("QUALIFICATION_PROTOCOL_MISMATCH")
            binding["qualified_roles"] = list(expected["role_coverage"])
        binding["status"] = "qualified"
        binding["binding_sha256"] = sha256(canonical({k: v for k, v in binding.items() if k != "binding_sha256"}))
    promoted["provider_states"] = provider_states(promoted["bindings"], promoted["provider_states"])
    promoted["registry_sha256"] = sha256(canonical({k: v for k, v in promoted.items() if k != "registry_sha256"}))
    return (json.dumps(promoted, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def named_digest(names: list[str], read: Callable[[str], bytes]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(names):
        name, raw = relative.encode("utf-8"), read(relative)
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def release_binding(read: Callable[[str], bytes], registry_override: bytes | None = None) -> dict[str, Any]:
    """Reproduce current release identity, substituting only registry bytes for B."""
    declaration = fields(decode(read(INVENTORY_PATH)), {"schema_version", "identity_version", "paths"}, "INVENTORY_INVALID")
    if (declaration["schema_version"] != "agent-council.behavioral-inventory/v1" or
            not isinstance(declaration["identity_version"], str) or
            re.fullmatch(r"[a-z0-9][a-z0-9._/-]*", declaration["identity_version"]) is None):
        fail("INVENTORY_INVALID")
    paths = declaration["paths"]
    if not isinstance(paths, list) or not paths:
        fail("INVENTORY_INVALID")
    paths = [path_name(item) for item in paths]
    if len(set(paths)) != len(paths) or INVENTORY_PATH in paths or REGISTRY_PATH not in paths:
        fail("INVENTORY_INVALID")
    paths = sorted(paths)
    inventory_sha = sha256(json.dumps({**declaration, "paths": paths}, sort_keys=True,
                                     separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    def overridden(relative: str) -> bytes:
        return registry_override if relative == REGISTRY_PATH and registry_override is not None else read(relative)
    files_sha = named_digest(paths, overridden)
    identity_sha = sha256(b"agent-council.behavioral-identity/v1\0" + bytes.fromhex(inventory_sha) + bytes.fromhex(files_sha))
    evals = [path for path in paths if path.startswith("evals/")]
    if not evals:
        fail("EVAL_INVENTORY_EMPTY")
    return {"schema_version": "agent-council.release-binding/v1", "behavioral_identity": {
        "schema_version": "agent-council.behavioral-identity/v1", "identity_version": declaration["identity_version"],
        "inventory_sha256": inventory_sha, "files_sha256": files_sha, "behavioral_sha256": identity_sha, "paths": paths},
        "eval_suite_sha256": named_digest(evals, overridden)}


def json_lines(raw: bytes) -> list[dict[str, Any]]:
    if not raw or not raw.endswith(b"\n"):
        fail("TRANSCRIPT_INCOMPLETE")
    result = [decode(line) for line in raw.splitlines()]
    if not result or any(not isinstance(row, dict) for row in result):
        fail("TRANSCRIPT_INVALID")
    return result


def native_fields(value: dict[str, Any], expected: dict[str, Any], code: str) -> None:
    if any(key not in value or value[key] != item or
           (type(item) is bool and value[key] is not item) for key, item in expected.items()):
        fail(code)


def public_identifier(candidate_sha: str, domain: str, value: str) -> str:
    """Commit identifiers consistently across roles without publishing raw IDs."""
    if domain not in {"session", "agent", "turn"} or not isinstance(value, str) or not value:
        fail("PUBLIC_IDENTIFIER_INVALID")
    return sha256(canonical(["agent-council.public-promotion-identifier/v1",
                             hash_value(candidate_sha), domain, value]))


def _public_claims(value: Any) -> None:
    if not isinstance(value, list) or len(value) != len(EXPECTED_CLAIMS):
        fail("PUBLIC_CLAIMS_INVALID")
    seen = set()
    for item in value:
        fields(item, {"scenario_id", "claims"}, "PUBLIC_CLAIMS_INVALID")
        scenario, claims = item["scenario_id"], item["claims"]
        if (not isinstance(scenario, str) or scenario not in EXPECTED_CLAIMS or scenario in seen or
                not isinstance(claims, list) or any(not isinstance(claim, str) for claim in claims) or
                len(set(claims)) != len(claims) or not set(claims) <= set(CLAIM_VOCABULARY) or
                not EXPECTED_CLAIMS[scenario] <= set(claims) or
                not set(claims) <= EXPECTED_CLAIMS[scenario] | CURRENT_ALLOWED_ADDITIONAL_CLAIMS.get(scenario, set())):
            fail("PUBLIC_CLAIMS_INVALID")
        seen.add(scenario)


def _role_protocols(rows: list[dict[str, Any]], bindings: Mapping[str, Any],
                    read: Callable[[str], bytes]) -> dict[str, Any]:
    """Bind the normative suite and role contracts to the frozen package too."""
    inventory = decode(read(INVENTORY_PATH))["paths"]
    for relative in protocol.PROTOCOL_FILES:
        if relative not in inventory:
            fail("QUALIFICATION_PROTOCOL_PACKAGE_MISMATCH")
    result = {}
    for row in rows:
        binding = bindings.get(row["binding_id"])
        if binding is None:
            fail("EVIDENCE_SET_INVALID")
        expected = protocol.protocol_binding(binding, read)
        if row.get("qualification_protocol") != expected:
            fail("QUALIFICATION_PROTOCOL_MISMATCH")
        for role, expected_sha in expected["role_contract_sha256"].items():
            relative = protocol.ROLE_FILES[role]
            if relative not in inventory or sha256(read(relative)) != expected_sha:
                fail("QUALIFICATION_ROLE_CONTRACT_MISMATCH")
        result[row["binding_id"]] = expected
    return result


def required_protocol(read: Callable[[str], bytes]) -> str | None:
    """Protocol authority comes from the frozen package, never its evidence."""
    paths = set(decode(read(INVENTORY_PATH))["paths"])
    markers = set(protocol.PROTOCOL_FILES)
    if paths & markers:
        if not markers <= paths:
            fail("QUALIFICATION_PROTOCOL_PACKAGE_INCOMPLETE")
        return ROLE_PROTOCOL
    return None


def export_public_promotion_bytes(files: Mapping[str, bytes], *, expected_package_sha256: str,
                                  expected_proof_sha256: str, candidate_root: Path = ROOT) -> dict[str, bytes]:
    """Return only public proof and archive after full private v1 verification.

    The source proof hash is an integrity commitment, never a signature. The
    public verifier cannot replay native harness scoring from these projections.
    """
    snapshot = dict(files)
    source = decode(snapshot[PROOF_PATH])
    if not isinstance(source, dict) or source.get("schema_version") not in {SCHEMA, ROLE_SCHEMA}:
        fail("PRIVATE_PROOF_REQUIRED")
    role_protocol = source["schema_version"] == ROLE_SCHEMA
    outcome_key = "case_outcomes" if role_protocol else "scenario_claims"
    verified = verify_promotion_bytes(snapshot, expected_package_sha256=expected_package_sha256,
                                      expected_proof_sha256=expected_proof_sha256,
                                      candidate_root=candidate_root)
    archived = snapshot[source["candidate_registry"]["path"]]
    bindings = {row["binding_id"]: row for row in registry(archived)["bindings"]}
    candidate_sha = verified["candidate_release_binding"]["behavioral_identity"]["behavioral_sha256"]
    def token(domain, value):
        return public_identifier(candidate_sha, domain, value)
    def claims(receipt):
        if role_protocol:
            return [{key: item[key] for key in ("scenario_id", "status", "assertion_failures", "prohibited_actions")}
                    for item in receipt["scenario_results"]]
        return [{"scenario_id": item["scenario_id"],
                 "claims": sorted(EXPECTED_CLAIMS[item["scenario_id"]] | set(item["additional_claims"]))}
                for item in receipt["scenario_results"]]
    def native(receipt):
        evidence = receipt["native_evidence"]
        return {"session_sha256": token("session", receipt["session_id"]),
                "parent_session_sha256": token("session", evidence["parent_session_id"]),
                "agent_sha256": token("agent", evidence["parent_session_id"] + "\0" + evidence["agent_path"]),
                "turn_sha256": token("turn", evidence["turn_id"]),
                "parent_transcript_sha256": evidence["parent_transcript_sha256"],
                "transcript_sha256": evidence["child_transcript_sha256"]}
    rows = []
    for private in source["binding_evidence"]:
        binding = bindings[private["binding_id"]]
        host = binding["provider"] == "codex"
        if host and "host_selection" not in private:
            fail("PUBLIC_CODEX_HOST_SELECTION_REQUIRED")
        row = {"binding_id": binding["binding_id"], "model_id": binding["model_id"],
               "effort": binding["reasoning"]["default_effort"],
               "identity_assurance": "host_selected" if host else "transcript_reported", "runs": []}
        if role_protocol:
            row["qualification_protocol"] = protocol.protocol_binding(binding, snapshot.__getitem__)
        for run in private["runs"]:
            receipt = decode(snapshot[run["receipt"]["path"]])
            run_value = native(receipt) if host else {
                "session_sha256": token("session", receipt["session_id"]),
                "parent_session_sha256": None, "agent_sha256": None, "turn_sha256": None,
                "parent_transcript_sha256": None, "transcript_sha256": run["transcript"]["sha256"]}
            row["runs"].append({**run_value, "run_id": receipt["run_id"], outcome_key: claims(receipt)})
        probe = decode(snapshot[private["probe"]["path"]])
        if host:
            row["probe"] = {**native(probe), outcome_key: claims(probe),
                            "agent_definition_sha256": None, "loader_debug_log_sha256": None}
        else:
            row["probe"] = {"session_sha256": token("session", probe["child_session_id"]),
                "parent_session_sha256": token("session", probe["parent_session_id"]),
                "agent_sha256": token("agent", probe["agent_id"]), "turn_sha256": None,
                "parent_transcript_sha256": probe["parent_transcript_sha256"],
                "transcript_sha256": probe["child_transcript_sha256"], outcome_key: None,
                "agent_definition_sha256": probe["agent_definition_sha256"],
                "loader_debug_log_sha256": probe["loader_debug_log_sha256"]}
        rows.append(row)
    public = {"schema_version": ROLE_PUBLIC_SCHEMA if role_protocol else PUBLIC_SCHEMA, "evidence_assurance": "structural_only",
              "provider_authenticity_verified": False, "native_harness_scoring_replayed": False,
              "source_proof_sha256": verified["promotion_proof_sha256"],
              "candidate_registry": {"path": ARCHIVE_PATH, "sha256": sha256(archived)},
              "candidate_release_binding": verified["candidate_release_binding"],
              "promoted_release_binding": verified["promoted_release_binding"], "binding_evidence": rows}
    if role_protocol:
        public["qualification_protocol_version"] = ROLE_PROTOCOL
        public["full_context_blindness_verified"] = False
    closure = {PROOF_PATH: canonical(public) + b"\n", ARCHIVE_PATH: archived}
    projected = {**snapshot, **closure}
    verify_promotion_bytes(projected, expected_package_sha256=expected_package_sha256,
                           expected_proof_sha256=sha256(closure[PROOF_PATH]))
    return closure


def _verify_public(read: Callable[[str], bytes], proof_path: str, proof: Any,
                   expected_package_sha256: str | None, proof_sha: str) -> dict[str, Any]:
    role_protocol = proof.get("schema_version") == ROLE_PUBLIC_SCHEMA
    if required_protocol(read) is not None and not role_protocol:
        fail("ROLE_PROTOCOL_REQUIRED")
    outcome_key = "case_outcomes" if role_protocol else "scenario_claims"
    fields(proof, {"schema_version", "evidence_assurance", "provider_authenticity_verified",
                   "native_harness_scoring_replayed", "source_proof_sha256", "candidate_registry",
                   "candidate_release_binding", "promoted_release_binding", "binding_evidence"} |
           ({"qualification_protocol_version", "full_context_blindness_verified"} if role_protocol else set()), "PUBLIC_PROOF_INVALID")
    if (proof["schema_version"] not in {PUBLIC_SCHEMA, ROLE_PUBLIC_SCHEMA} or proof["evidence_assurance"] != "structural_only" or
            proof["provider_authenticity_verified"] is not False or proof["native_harness_scoring_replayed"] is not False):
        fail("PUBLIC_ASSURANCE_INVALID")
    if role_protocol and (proof["qualification_protocol_version"] != ROLE_PROTOCOL or
                          proof["full_context_blindness_verified"] is not False):
        fail("QUALIFICATION_PROTOCOL_MISMATCH")
    hash_value(proof["source_proof_sha256"])
    archive = fields(proof["candidate_registry"], {"path", "sha256"}, "REFERENCE_INVALID")
    if archive["path"] != ARCHIVE_PATH or proof_path != PROOF_PATH:
        fail("PUBLIC_PATH_INVALID")
    candidate_bytes = read(ARCHIVE_PATH)
    if sha256(candidate_bytes) != hash_value(archive["sha256"]):
        fail("ARTIFACT_HASH_MISMATCH")
    candidate = registry(candidate_bytes)
    if any(row["status"] == "qualified" for row in candidate["bindings"]):
        fail("PRIOR_QUALIFICATION_UNPROVEN")
    promoted_bytes = read(REGISTRY_PATH)
    promoted = registry(promoted_bytes)
    before = {row["binding_id"]: row for row in candidate["bindings"]}
    ids = sorted(row["binding_id"] for row in promoted["bindings"] if row["status"] == "qualified")
    rows = proof["binding_evidence"]
    if (not isinstance(rows, list) or not rows or
            any(not isinstance(row, dict) or not isinstance(row.get("binding_id"), str) for row in rows) or
            sorted(row["binding_id"] for row in rows) != ids):
        fail("EVIDENCE_SET_INVALID")
    protocols = _role_protocols(rows, before, read) if role_protocol else None
    if promoted_bytes != promote_registry(candidate_bytes, ids, qualification_protocols=protocols, read=read):
        fail("TRANSFORMATION_MISMATCH")
    candidate_release, promoted_release = release_binding(read, candidate_bytes), release_binding(read)
    if proof["candidate_release_binding"] != candidate_release or proof["promoted_release_binding"] != promoted_release:
        fail("RELEASE_BINDING_MISMATCH")
    if set((PROOF_PATH, ARCHIVE_PATH)) & set(promoted_release["behavioral_identity"]["paths"]):
        fail("PROOF_IN_BEHAVIORAL_INVENTORY")
    if expected_package_sha256 is not None and hash_value(expected_package_sha256) != promoted_release["behavioral_identity"]["behavioral_sha256"]:
        fail("PACKAGE_PIN_MISMATCH")
    sessions, parents, agents, turns, children = set(), set(), set(), set(), set()
    def unique(value, collection, code):
        hash_value(value)
        if value in collection:
            fail(code)
        collection.add(value)
    def session(value):
        if value in parents:
            fail("SESSION_REUSED")
        unique(value, sessions, "SESSION_REUSED")
    def parent(value):
        hash_value(value)
        if value in sessions:
            fail("SESSION_REUSED")
        parents.add(value)
    def host_identity(item):
        parent(item["parent_session_sha256"])
        session(item["session_sha256"])
        unique(item["agent_sha256"], agents, "PUBLIC_AGENT_REUSED")
        unique(item["turn_sha256"], turns, "PUBLIC_TURN_REUSED")
        unique(item["transcript_sha256"], children, "PUBLIC_TRANSCRIPT_REUSED")
        hash_value(item["parent_transcript_sha256"])
    identity = {"session_sha256", "parent_session_sha256", "agent_sha256", "turn_sha256",
                "parent_transcript_sha256", "transcript_sha256"}
    host_ids = []
    for row in rows:
        fields(row, {"binding_id", "model_id", "effort", "identity_assurance", "runs", "probe"} |
               ({"qualification_protocol"} if role_protocol else set()), "PUBLIC_ROW_INVALID")
        binding = before[row["binding_id"]]
        host = binding["provider"] == "codex"
        if (row["model_id"] != binding["model_id"] or row["effort"] != binding["reasoning"]["default_effort"] or
                row["identity_assurance"] != ("host_selected" if host else "transcript_reported")):
            fail("PUBLIC_BINDING_MISMATCH")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", row["model_id"]) is None:
            fail("PUBLIC_MODEL_INVALID")
        runs = row["runs"]
        if not isinstance(runs, list) or len(runs) != 2:
            fail("RUN_SET_INVALID")
        run_ids = set()
        for run in runs:
            fields(run, identity | {"run_id", outcome_key}, "PUBLIC_RUN_INVALID")
            if not isinstance(run["run_id"], str) or run["run_id"] not in RUN_IDS or run["run_id"] in run_ids:
                fail("RUN_SET_INVALID")
            run_ids.add(run["run_id"])
            if role_protocol:
                protocol.validate_results(run[outcome_key], binding, read)
            else:
                _public_claims(run[outcome_key])
            if host:
                host_identity(run)
            else:
                if any(run[key] is not None for key in identity - {"session_sha256", "transcript_sha256"}):
                    fail("PUBLIC_RUN_INVALID")
                session(run["session_sha256"])
                unique(run["transcript_sha256"], children, "PUBLIC_TRANSCRIPT_REUSED")
        probe = fields(row["probe"], identity | {outcome_key, "agent_definition_sha256", "loader_debug_log_sha256"}, "PUBLIC_PROBE_INVALID")
        if host:
            host_ids.append(row["binding_id"])
            if probe["agent_definition_sha256"] is not None or probe["loader_debug_log_sha256"] is not None:
                fail("PUBLIC_PROBE_INVALID")
            host_identity(probe)
            if role_protocol:
                protocol.validate_results(probe[outcome_key], binding, read)
            else:
                _public_claims(probe[outcome_key])
        else:
            if probe["turn_sha256"] is not None or probe[outcome_key] is not None:
                fail("PUBLIC_PROBE_INVALID")
            parent(probe["parent_session_sha256"])
            if probe["session_sha256"] != probe["parent_session_sha256"]:
                session(probe["session_sha256"])
            unique(probe["agent_sha256"], agents, "PUBLIC_AGENT_REUSED")
            unique(probe["transcript_sha256"], children, "PUBLIC_TRANSCRIPT_REUSED")
            hash_value(probe["parent_transcript_sha256"])
            hash_value(probe["loader_debug_log_sha256"])
            agent = ("council-" + row["binding_id"].removeprefix("claude-code-v3-")
                     if row["binding_id"] in BINDINGS else row["binding_id"])
            definition = "agents/" + agent + ".md"
            if (definition not in promoted_release["behavioral_identity"]["paths"] or
                    sha256(read(definition)) != hash_value(probe["agent_definition_sha256"])):
                fail("PROBE_AGENT_MISMATCH")
    return {"schema_version": "agent-council.promotion-binding/v1", "result": "verified",
            "promotion_proof_sha256": proof_sha, "candidate_release_binding": candidate_release,
            "promoted_release_binding": promoted_release,
            "candidate_registry_sha256": candidate["registry_sha256"],
            "promoted_registry_sha256": promoted["registry_sha256"], "evidence_assurance": "structural_only",
            "provider_authenticity_verified": False, "native_harness_scoring_replayed": False,
            "claude_workspace_preparation_replayed": False, "claude_clean_context_replayed": False,
            "host_selected_native_scoring_replayed": False, "claims_scoring_replayed": not role_protocol,
            "qualification_protocol_version": ROLE_PROTOCOL if role_protocol else None,
            "host_selected_binding_ids": sorted(host_ids), "binding_ids": ids,
            "artifact_paths": sorted([PROOF_PATH, ARCHIVE_PATH])}


def _verify(read: Callable[[str], bytes], proof_path: str, expected_package_sha256: str | None,
            expected_proof_sha256: str | None, candidate_root: Path) -> dict[str, Any]:
    proof_path = path_name(proof_path)
    proof_bytes = read(proof_path)
    proof_sha = sha256(proof_bytes)
    if expected_proof_sha256 is not None and proof_sha != hash_value(expected_proof_sha256):
        fail("PROOF_PIN_MISMATCH")
    decoded = decode(proof_bytes)
    if isinstance(decoded, dict) and decoded.get("schema_version") in {PUBLIC_SCHEMA, ROLE_PUBLIC_SCHEMA}:
        return _verify_public(read, proof_path, decoded, expected_package_sha256, proof_sha)
    role_protocol = isinstance(decoded, dict) and decoded.get("schema_version") == ROLE_SCHEMA
    if required_protocol(read) is not None and not role_protocol:
        fail("ROLE_PROTOCOL_REQUIRED")
    proof = fields(decode(proof_bytes), {"schema_version", "evidence_assurance", "candidate_registry",
                   "candidate_release_binding", "promoted_release_binding", "binding_evidence"} |
                   ({"qualification_protocol_version"} if role_protocol else set()), "PROOF_INVALID")
    if proof["schema_version"] not in {SCHEMA, ROLE_SCHEMA} or proof["evidence_assurance"] != "structural_only":
        fail("PROOF_INVALID")
    if role_protocol and proof["qualification_protocol_version"] != ROLE_PROTOCOL:
        fail("QUALIFICATION_PROTOCOL_MISMATCH")
    promoted_release = release_binding(read)
    paths = set(promoted_release["behavioral_identity"]["paths"])
    if proof_path in paths:
        fail("PROOF_IN_BEHAVIORAL_INVENTORY")
    used_paths = {proof_path}
    shared_paths: dict[str, str] = {}
    def reference(value: Any, *, transcript: bool = False, shared_kind: str | None = None,
                  raw_only: bool = False) -> tuple[Any, bytes]:
        fields(value, {"path", "sha256"}, "REFERENCE_INVALID")
        path = path_name(value["path"])
        if ((path in used_paths and (shared_kind is None or shared_paths.get(path) != shared_kind)) or
                path in paths or path == INVENTORY_PATH):
            fail("REFERENCE_DUPLICATE_OR_BEHAVIORAL")
        used_paths.add(path)
        if shared_kind is not None:
            shared_paths[path] = shared_kind
        raw = read(path)
        if sha256(raw) != hash_value(value["sha256"]):
            fail("ARTIFACT_HASH_MISMATCH")
        return (raw if raw_only else json_lines(raw) if transcript else decode(raw)), raw
    _, candidate_bytes = reference(proof["candidate_registry"])
    candidate_registry = registry(candidate_bytes)
    # A hash-consistent archive cannot confer inherited qualification authority.
    # Incremental proofs accumulate evidence against the same frozen baseline.
    if any(binding["status"] == "qualified" for binding in candidate_registry["bindings"]):
        fail("PRIOR_QUALIFICATION_UNPROVEN")
    promoted_registry = registry(read(REGISTRY_PATH))
    before = {binding["binding_id"]: binding for binding in candidate_registry["bindings"]}
    promoted_ids = sorted(binding["binding_id"] for binding in promoted_registry["bindings"]
                          if binding["status"] == "qualified" and
                          before.get(binding["binding_id"], {}).get("status") == "candidate")
    rows = proof["binding_evidence"]
    if (not isinstance(rows, list) or not rows or
            any(not isinstance(row, dict) or not isinstance(row.get("binding_id"), str) for row in rows) or
            sorted(row["binding_id"] for row in rows) != promoted_ids):
        fail("EVIDENCE_SET_INVALID")
    protocols = _role_protocols(rows, before, read) if role_protocol else None
    if read(REGISTRY_PATH) != promote_registry(candidate_bytes, promoted_ids, qualification_protocols=protocols, read=read):
        fail("TRANSFORMATION_MISMATCH")
    candidate_release = release_binding(read, candidate_bytes)
    if (proof["candidate_release_binding"] != candidate_release or
            proof["promoted_release_binding"] != promoted_release):
        fail("RELEASE_BINDING_MISMATCH")
    promoted_sha = promoted_release["behavioral_identity"]["behavioral_sha256"]
    if expected_package_sha256 is not None and promoted_sha != hash_value(expected_package_sha256):
        fail("PACKAGE_PIN_MISMATCH")
    seen_bindings: set[str] = set()
    seen_sessions: set[str] = set()
    parent_sessions: set[str] = set()
    probe_agents: set[str] = set()
    host_selected_bindings: set[str] = set()
    def claim_session(session: Any) -> None:
        value = text_value(session)
        if value in seen_sessions or value in parent_sessions:
            fail("SESSION_REUSED")
        seen_sessions.add(value)
    policy_sha = named_digest(list(V3_CANDIDATE_FILES),
                              lambda relative: candidate_bytes if relative == REGISTRY_PATH else read(relative))
    for row in rows:
        host_selected = "host_selection" in row
        fields(row, {"binding_id", "pair", "runs", "probe", "probe_files"} |
               ({"host_selection"} if host_selected else set()) |
               ({"qualification_protocol"} if role_protocol else set()), "EVIDENCE_INVALID")
        binding_id = text_value(row["binding_id"])
        if binding_id not in before or binding_id in seen_bindings:
            fail("EVIDENCE_SET_INVALID")
        seen_bindings.add(binding_id)
        binding = next(item for item in candidate_registry["bindings"] if item["binding_id"] == binding_id)
        model, effort = binding["model_id"], binding["reasoning"]["default_effort"]
        provider = binding["provider"]
        if role_protocol and provider == "codex" and not host_selected:
            fail("ROLE_CODEX_HOST_SELECTION_REQUIRED")
        if host_selected:
            if provider != "codex":
                fail("HOST_PROVIDER_INVALID")
            evidence = _codex_host_evidence(row, binding, read, reference, candidate_bytes, candidate_release)
            for item in evidence:
                if role_protocol:
                    native_fields(item, {"qualification_protocol": protocols[binding_id]}, "QUALIFICATION_PROTOCOL_MISMATCH")
                    protocol.validate_results(item.get("scenario_results"), binding, read)
                elif "qualification_protocol" in item:
                    fail("MIXED_PROTOCOL_VERSIONS")
                parent_id = item["native_evidence"]["parent_session_id"]
                if parent_id in seen_sessions:
                    fail("SESSION_REUSED")
                parent_sessions.add(parent_id)
                claim_session(item["session_id"])
            host_selected_bindings.add(binding_id)
            continue
        provider_label = "claude" if provider == "claude_code" else "codex"
        common = {"binding_id": binding_id, "binding_sha256": binding["binding_sha256"],
                  "registry_sha256": candidate_registry["registry_sha256"], "release_binding": candidate_release}
        qualification = {**common, "registry_version": "v3", "candidate_sha256": policy_sha,
                         "eval_suite_sha256": candidate_release["eval_suite_sha256"]}
        if role_protocol:
            qualification["qualification_protocol"] = protocols[binding_id]
        pair, _ = reference(row["pair"])
        if not isinstance(pair, dict):
            fail("PAIR_INVALID")
        if not role_protocol and "qualification_protocol" in pair:
            fail("MIXED_PROTOCOL_VERSIONS")
        native_fields(pair, {**qualification, "schema_version": f"agent-council.{provider_label}-qualification-pair/v3",
                             "result": "passed", "model_id": model, "effort": effort,
                             "run_ids": sorted(RUN_IDS)}, "PAIR_INVALID")
        if provider == "codex":
            _codex_attestation(pair, model, effort)
        hash_value(pair.get("evaluation_bundle_sha256"))
        sessions = pair.get("session_ids")
        if not isinstance(sessions, list) or len(sessions) != 2:
            fail("PAIR_SESSIONS_INVALID")
        for session in sessions:
            claim_session(session)
        if sessions != sorted(sessions):
            fail("PAIR_SESSIONS_INVALID")
        runs = row["runs"]
        if not isinstance(runs, list) or len(runs) != 2:
            fail("RUN_SET_INVALID")
        run_ids, run_sessions = set(), set()
        for run in runs:
            fields(run, {"receipt", "transcript"}, "RUN_INVALID")
            receipt, _ = reference(run["receipt"])
            transcript, raw = reference(run["transcript"], transcript=True)
            if not isinstance(receipt, dict):
                fail("RUN_INVALID")
            if not role_protocol and "qualification_protocol" in receipt:
                fail("MIXED_PROTOCOL_VERSIONS")
            native_fields(receipt, {**qualification,
                "schema_version": f"agent-council.{provider_label}-qualification-receipt/v3",
                "result": "passed", "requested_model_id": model, "actual_model_id": model,
                "requested_effort": effort, "actual_effort": effort, "clean_context": True, "blind": True,
                "evaluation_bundle_sha256": pair["evaluation_bundle_sha256"], "transcript_sha256": sha256(raw)}, "RUN_INVALID")
            run_id, session_id = receipt.get("run_id"), receipt.get("session_id")
            if not isinstance(run_id, str) or run_id not in RUN_IDS or run_id in run_ids or not isinstance(session_id, str) or session_id not in sessions or session_id in run_sessions:
                fail("RUN_SET_INVALID")
            run_ids.add(run_id)
            run_sessions.add(session_id)
            results = receipt.get("scenario_results")
            if role_protocol:
                protocol.validate_results(results, binding, read)
            elif (not isinstance(results, list) or len(results) != 12 or
                    any(not isinstance(item, dict) or not isinstance(item.get("scenario_id"), str) or item.get("status") != "passed" or
                        item.get("missing_claims") != [] or item.get("disallowed_additional_claims") != [] for item in results) or
                    {item.get("scenario_id") for item in results} != {f"GFT{n:02}" for n in range(1, 13)}):
                fail("SCENARIO_RESULTS_INVALID")
            if provider == "codex":
                _codex_attestation(receipt, model, effort)
            derived = _qualification_transcript(transcript, provider, session_id, model, effort,
                                                 binding=binding if role_protocol else None, read=read)
            if results != derived:
                fail("SCENARIO_TRANSCRIPT_MISMATCH")
        probe, _ = reference(row["probe"])
        if not isinstance(probe, dict):
            fail("PROBE_INVALID")
        native_fields(probe, {**common, "schema_version": f"agent-council.{provider_label}-agent-probe/v1",
                             "result": "passed", "model_id": model, "effort": effort,
                             "registry_file_sha256": sha256(candidate_bytes)}, "PROBE_INVALID")
        parent_session = text_value(probe.get("parent_session_id"))
        if parent_session in seen_sessions:
            fail("SESSION_REUSED")
        parent_sessions.add(parent_session)
        child_session = text_value(probe.get("child_session_id"))
        if child_session != parent_session:
            claim_session(child_session)
        elif provider == "codex":
            fail("CODEX_CHILD_SESSION_NOT_DISTINCT")
        required_files = {"release_binding", "parent_transcript", "child_transcript"}
        if provider == "claude_code":
            required_files.add("loader_debug_log")
        probe_files = fields(row["probe_files"], required_files, "PROBE_FILES_INVALID")
        frozen, frozen_raw = reference(probe_files["release_binding"], shared_kind="release_binding")
        parent, parent_raw = reference(probe_files["parent_transcript"], transcript=True, shared_kind="parent_transcript")
        child, child_raw = reference(probe_files["child_transcript"], transcript=True)
        if frozen != candidate_release:
            fail("PROBE_FROZEN_RELEASE_MISMATCH")
        native_fields(probe, {"release_binding_file_sha256": sha256(frozen_raw),
                             "parent_transcript_sha256": sha256(parent_raw),
                             "child_transcript_sha256": sha256(child_raw)}, "PROBE_FILES_MISMATCH")
        if provider == "codex":
            _codex_attestation(probe, model, effort)
            _codex_probe(probe, parent, child, model, effort)
        else:
            loader_ref = probe_files["loader_debug_log"]
            if not isinstance(loader_ref, dict) or not isinstance(loader_ref.get("path"), str):
                fail("PROBE_LOADER_REFERENCE_INVALID")
            expected_name = parent_session + ".txt"
            if Path(loader_ref["path"]).name != expected_name:
                fail("PROBE_LOADER_SESSION_MISMATCH")
            _, loader_raw = reference(loader_ref, shared_kind="loader_debug_log", raw_only=True)
            native_fields(probe, {"loader_root": str(candidate_root.resolve()),
                                  "loader_debug_log_sha256": sha256(loader_raw)}, "PROBE_LOADER_RECEIPT_MISMATCH")
            try:
                verify_loader_log(loader_raw, candidate_root, parent_session, expected_name)
            except ValueError as exc:
                fail("LOADER_LOG_INVALID:" + str(exc))
            agent_id = text_value(probe.get("agent_id"))
            if agent_id in probe_agents:
                fail("PROBE_CHILD_REUSED")
            probe_agents.add(agent_id)
            agent_name = ("council-" + binding_id.removeprefix("claude-code-v3-")
                          if binding_id in BINDINGS and BINDINGS[binding_id][0] == "claude_code"
                          else binding_id)
            definition_path = "agents/" + agent_name + ".md"
            if definition_path not in paths:
                fail("PROBE_AGENT_NOT_IN_INVENTORY")
            definition = read(definition_path)
            native_fields(probe, {"agent_definition_sha256": sha256(definition),
                                 "subagent_type": "agent-council:" + agent_name}, "PROBE_AGENT_MISMATCH")
            _claude_probe(probe, parent, child, model, effort)
    return {"schema_version": "agent-council.promotion-binding/v1", "result": "verified",
            "promotion_proof_sha256": proof_sha, "candidate_release_binding": candidate_release,
            "promoted_release_binding": promoted_release,
            "candidate_registry_sha256": candidate_registry["registry_sha256"],
            "promoted_registry_sha256": promoted_registry["registry_sha256"],
            "evidence_assurance": "structural_only", "provider_authenticity_verified": False,
            "claude_workspace_preparation_replayed": False, "claude_clean_context_replayed": False,
            "native_harness_scoring_replayed": bool(host_selected_bindings) and host_selected_bindings == seen_bindings,
            "host_selected_binding_ids": sorted(host_selected_bindings),
            "host_selected_native_scoring_replayed": bool(host_selected_bindings),
            "qualification_protocol_version": ROLE_PROTOCOL if role_protocol else None,
            "binding_ids": sorted(seen_bindings), "artifact_paths": sorted(used_paths)}


def _codex_host_evidence(row: dict[str, Any], binding: dict[str, Any], read: Callable[[str], bytes],
                         reference: Callable[..., tuple[Any, bytes]], candidate_bytes: bytes,
                         candidate_release: dict[str, Any]) -> list[dict[str, Any]]:
    """Replay archived native dispatches, not normalized attestation claims.

    The collector requires local session-store files. Archived source records
    are pinned structural evidence, not cryptographic proof of host provenance.
    """
    selection = fields(row["host_selection"], {"preparation", "prompt"}, "HOST_PREPARATION_INVALID")
    _, preparation = reference(selection["preparation"], shared_kind="codex_preparation")
    _, prompt = reference(selection["prompt"], shared_kind="codex_prompt", raw_only=True)
    pair, _ = reference(row["pair"])
    runs = row["runs"]
    if not isinstance(runs, list) or len(runs) != 2:
        fail("RUN_SET_INVALID")
    with tempfile.TemporaryDirectory(prefix="council-host-replay-") as temporary:
        root = Path(temporary).resolve() / "candidate"
        workspace = Path(temporary).resolve() / "prepared"
        workspace.mkdir()
        (workspace / codex.MANIFEST_NAME).write_bytes(preparation)
        (workspace / codex.PROMPT_NAME).write_bytes(prompt)
        for relative in [*candidate_release["behavioral_identity"]["paths"], INVENTORY_PATH]:
            path = root / path_name(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(candidate_bytes if relative == REGISTRY_PATH else read(relative))
        receipts, native_transcripts = [], {}
        for index, run in enumerate(runs):
            fields(run, {"receipt", "transcript", "parent_transcript"}, "HOST_RUN_INVALID")
            receipt, _ = reference(run["receipt"])
            if not isinstance(receipt, dict) or receipt.get("binding_id") != binding["binding_id"]:
                fail("HOST_RECEIPT_MISMATCH")
            parent, child = workspace / f"parent-{index}.jsonl", workspace / f"child-{index}.jsonl"
            _, raw = reference(run["parent_transcript"], transcript=True, shared_kind="parent_transcript")
            parent.write_bytes(raw)
            _, raw = reference(run["transcript"], transcript=True)
            child.write_bytes(raw)
            run_id = receipt.get("run_id")
            if not isinstance(run_id, str) or run_id in native_transcripts:
                fail("RUN_SET_INVALID")
            native_transcripts[run_id] = (parent, child)
            receipts.append(receipt)
        observed_pair = codex.validate_host_pair(receipts, root=root, workspace=workspace,
                                                 native_transcripts=native_transcripts, archived=True)
        if pair != observed_pair:
            fail("HOST_PAIR_MISMATCH")
        # A third independently completed native dispatch is the agent probe.
        # Replaying the same scorer also verifies its prompt, tools and outcome.
        probe, _ = reference(row["probe"])
        if not isinstance(probe, dict) or probe.get("binding_id") != binding["binding_id"]:
            fail("HOST_PROBE_INVALID")
        files = fields(row["probe_files"], {"release_binding", "parent_transcript", "child_transcript",
                                            "preparation", "prompt"}, "PROBE_FILES_INVALID")
        _, probe_preparation = reference(files["preparation"], shared_kind="codex_preparation")
        _, probe_prompt = reference(files["prompt"], shared_kind="codex_prompt", raw_only=True)
        probe_workspace = workspace / "probe-prepared"
        probe_workspace.mkdir()
        (probe_workspace / codex.MANIFEST_NAME).write_bytes(probe_preparation)
        (probe_workspace / codex.PROMPT_NAME).write_bytes(probe_prompt)
        frozen, _ = reference(files["release_binding"], shared_kind="release_binding")
        if frozen != candidate_release:
            fail("PROBE_FROZEN_RELEASE_MISMATCH")
        parent, child = workspace / "probe-parent.jsonl", workspace / "probe-child.jsonl"
        _, raw = reference(files["parent_transcript"], transcript=True, shared_kind="parent_transcript")
        parent.write_bytes(raw)
        _, raw = reference(files["child_transcript"], transcript=True)
        child.write_bytes(raw)
        derived = codex.score(root, probe_workspace, binding["binding_id"], probe.get("run_id"), parent, child)
        if codex.host_selected_receipt(derived, probe.get("host_selection")) != probe or probe.get("promotion_eligible") is not True:
            fail("HOST_PROBE_MISMATCH")
        evidence = [*receipts, probe]
        for key in ("agent_path", "turn_id", "child_transcript_sha256"):
            # The probe may reuse the prepared task name in a different parent.
            identities = [(item["native_evidence"]["parent_session_id"], item["native_evidence"][key])
                          if key == "agent_path" else item["native_evidence"][key] for item in evidence]
            if len(set(identities)) != 3:
                fail("HOST_PROBE_REUSED")
        return evidence


def _codex_attestation(value: dict[str, Any], model: str, effort: str | None) -> None:
    native_fields(value, {"provider": "codex", "provenance": "native_session_export",
                         "requested_model_id": model, "provider_attested_model_id": model,
                         "requested_effort": effort, "provider_attested_effort": effort}, "CODEX_ATTESTATION_INVALID")


def _qualification_transcript(rows: list[dict[str, Any]], provider: str, session: str,
                              model: str, effort: str | None, *, score: bool = True,
                              binding: dict[str, Any] | None = None,
                              read: Callable[[str], bytes] | None = None) -> list[dict[str, Any]]:
    if provider == "codex":
        attested = [row for row in rows if row.get("type") == "provider_attestation"]
        if len(attested) != 1:
            fail("TRANSCRIPT_ATTESTATION_INVALID")
        native_fields(attested[0], {"session_id": session, "model_id": model, "effort": effort,
                                   "status": "completed", "council_reentry": "denied"}, "TRANSCRIPT_ATTESTATION_INVALID")
        if not score:
            return []
        responses = [row.get("response") for row in rows if row.get("type") == "qualification_result" and row.get("session_id") == session]
        if len(responses) != 1:
            fail("TRANSCRIPT_RESPONSE_INVALID")
        response = responses[0]
    else:
        assistants = [row for row in rows if row.get("type") == "assistant"]
        if not assistants:
            fail("TRANSCRIPT_ASSISTANT_MISSING")
        for row in assistants:
            native_fields(row, {"sessionId": session}, "TRANSCRIPT_BINDING_MISMATCH")
            if not transcript_effort_matches(row, effort):
                fail("TRANSCRIPT_BINDING_MISMATCH")
            if not isinstance(row.get("message"), dict) or row["message"].get("model") != model:
                fail("TRANSCRIPT_BINDING_MISMATCH")
        texts = [(index, "\n".join(block.get("text", "") for block in _blocks(row)
                                   if block.get("type") == "text" and isinstance(block.get("text"), str)).strip())
                 for index, row in enumerate(rows) if row.get("type") == "assistant"]
        try:
            response_index, response = extract_qualification_json(texts)
            validate_qualification_tail(rows, response_index)
        except ValueError as error:
            raise ValueError("PROMOTION_TRANSCRIPT_RESPONSE_INVALID") from error
    if binding is not None:
        return protocol.score_response(response, binding, read)
    if not isinstance(response, dict) or response.get("schema_version") != f"agent-council.{'claude' if provider == 'claude_code' else 'codex'}-native-response/v1":
        fail("TRANSCRIPT_RESPONSE_INVALID")
    result_rows = response.get("results")
    if not isinstance(result_rows, list) or len(result_rows) != len(EXPECTED_CLAIMS):
        fail("TRANSCRIPT_RESPONSE_INVALID")
    scored: dict[str, Any] = {}
    for item in result_rows:
        if not isinstance(item, dict):
            fail("TRANSCRIPT_RESPONSE_INVALID")
        scenario_id = item.get("scenario_id")
        claims = item.get("claims")
        if (not isinstance(scenario_id, str) or scenario_id not in EXPECTED_CLAIMS or scenario_id in scored or
                not isinstance(claims, list) or any(not isinstance(claim, str) for claim in claims) or len(set(claims)) != len(claims)):
            fail("TRANSCRIPT_RESPONSE_INVALID")
        missing = sorted(EXPECTED_CLAIMS[scenario_id] - set(claims))
        additional = sorted(set(claims) - EXPECTED_CLAIMS[scenario_id])
        disallowed = sorted(set(additional) - CURRENT_ALLOWED_ADDITIONAL_CLAIMS.get(scenario_id, set()))
        if missing or disallowed:
            fail("TRANSCRIPT_SCENARIO_FAILED")
        scored[scenario_id] = {"scenario_id": scenario_id, "status": "passed", "missing_claims": missing,
                               "additional_claims": additional, "disallowed_additional_claims": disallowed}
    return [scored[key] for key in sorted(scored)]


def _blocks(row: dict[str, Any]) -> list[dict[str, Any]]:
    message = row.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), list):
        return []
    return [block for block in message["content"] if isinstance(block, dict)]


def _claude_probe(probe: dict[str, Any], parent: list[dict[str, Any]], child: list[dict[str, Any]],
                  model: str, effort: str | None) -> None:
    agent_id, tool_id = text_value(probe.get("agent_id")), text_value(probe.get("tool_use_id"))
    calls = [(index, row, block) for index, row in enumerate(parent) if row.get("type") == "assistant"
             for block in _blocks(row) if block.get("type") == "tool_use" and block.get("name") == "Agent"
             and isinstance(block.get("input"), dict) and block["input"].get("subagent_type") == probe["subagent_type"]]
    if len(calls) != 1 or calls[0][2].get("id") != tool_id or calls[0][1].get("sessionId") != probe["parent_session_id"]:
        fail("PROBE_CALL_INVALID")
    results = [(index, row) for index, row in enumerate(parent) if row.get("type") == "user"
               for block in _blocks(row) if block.get("type") == "tool_result" and block.get("tool_use_id") == tool_id
               and block.get("is_error") is not True]
    if len(results) != 1 or results[0][0] <= calls[0][0]:
        fail("PROBE_RESULT_INVALID")
    result = results[0][1].get("toolUseResult")
    if not isinstance(result, dict) or result.get("agentId") != agent_id or result.get("resolvedModel") != model:
        fail("PROBE_RESULT_INVALID")
    if results[0][1].get("sessionId") != probe["parent_session_id"]:
        fail("PROBE_RESULT_INVALID")
    assistants = [row for row in child if row.get("type") == "assistant"]
    if not assistants or type(probe.get("child_assistant_rows")) is not int or probe["child_assistant_rows"] != len(assistants):
        fail("PROBE_CHILD_INVALID")
    for row in assistants:
        native_fields(row, {"sessionId": probe["child_session_id"], "agentId": agent_id,
                           "isSidechain": True}, "PROBE_CHILD_INVALID")
        if not transcript_effort_matches(row, effort):
            fail("PROBE_CHILD_INVALID")
        if not isinstance(row.get("message"), dict) or row["message"].get("model") != model:
            fail("PROBE_CHILD_INVALID")
        if any(block.get("type") == "tool_use" and block.get("name") == "Agent" for block in _blocks(row)):
            fail("COUNCIL_REENTRY")
    outcome = result.get("status")
    if not isinstance(outcome, str):
        fail("PROBE_COMPLETION_INVALID")
    if outcome in {"completed", "success"} and result.get("isAsync") is not True:
        completion = "agent_result"
    elif outcome == "async_launched" and result.get("isAsync") is True:
        verify_async_completion(parent, child, results[0][0], probe["parent_session_id"], agent_id, tool_id)
        completion = "task_notification_handback"
    else:
        fail("PROBE_COMPLETION_INVALID")
    if probe.get("completion_evidence") != completion:
        fail("PROBE_COMPLETION_INVALID")


def _codex_probe(probe: dict[str, Any], parent: list[dict[str, Any]], child: list[dict[str, Any]],
                 model: str, effort: str | None) -> None:
    _qualification_transcript(child, "codex", probe["child_session_id"], model, effort, score=False)
    calls = [row for row in parent if row.get("type") == "native_agent_dispatch" and row.get("binding_id") == probe["binding_id"]]
    if len(calls) != 1:
        fail("CODEX_PROBE_INVALID")
    native_fields(calls[0], {"parent_session_id": probe["parent_session_id"], "child_session_id": probe["child_session_id"],
                            "binding_id": probe["binding_id"], "requested_model_id": model,
                            "requested_effort": effort, "status": "completed", "council_reentry": "denied"}, "CODEX_PROBE_INVALID")


def frozen_candidate_root(files: Mapping[str, bytes], proof_path: str = PROOF_PATH) -> Path:
    """Read the recorded source root for a pinned, detached snapshot."""
    proof = decode(files[path_name(proof_path)])
    if isinstance(proof, dict) and proof.get("schema_version") in {PUBLIC_SCHEMA, ROLE_PUBLIC_SCHEMA}:
        return ROOT  # Public projections contain no private loader root.
    candidate = registry(files[path_name(proof["candidate_registry"]["path"])])
    providers = {binding["binding_id"]: binding["provider"] for binding in candidate["bindings"]}
    roots: set[str] = set()
    for row in proof["binding_evidence"]:
        if providers.get(row["binding_id"]) != "claude_code":
            continue
        probe = decode(files[path_name(row["probe"]["path"])])
        root = text_value(probe.get("loader_root"))
        if not Path(root).is_absolute():
            fail("PROBE_LOADER_ROOT_MISMATCH")
        roots.add(root)
    if not roots:
        return ROOT
    if len(roots) != 1:
        fail("PROBE_LOADER_ROOT_MISMATCH")
    return Path(roots.pop())


def verify_promotion_bytes(files: Mapping[str, bytes], *, expected_package_sha256: str,
                           expected_proof_sha256: str, proof_path: str = PROOF_PATH,
                           candidate_root: Path = ROOT) -> dict[str, Any]:
    """Verify an already pinned snapshot; both pins must come from caller authority."""
    snapshot = dict(files)
    def read(relative: str) -> bytes:
        relative = path_name(relative)
        if relative not in snapshot or not isinstance(snapshot[relative], bytes):
            fail("FILE_MISSING:" + relative)
        return snapshot[relative]
    return _verify(read, proof_path, hash_value(expected_package_sha256), hash_value(expected_proof_sha256), candidate_root)


def verify_promotion(root: Path = ROOT, proof_path: str = PROOF_PATH, *,
                     expected_package_sha256: str | None = None,
                     expected_proof_sha256: str | None = None,
                     candidate_root: Path | None = None) -> dict[str, Any]:
    """Read regular package files once, rejecting symlinks, aliases, and races.

    Without caller pins this is an integrity diagnostic, not authorization to
    trust a package. Runtime acceptance should supply both pins or use the
    byte-snapshot API. Proof and archive must be outside behavioral inventory.
    """
    root = Path(os.path.abspath(root))
    candidate_root = root if candidate_root is None else Path(os.path.abspath(candidate_root))
    if any(item.is_symlink() for item in (root, *root.parents)) or not root.is_dir():
        fail("ROOT_UNSAFE")
    cache: dict[str, bytes] = {}
    identities: dict[tuple[int, int], str] = {}
    observations: dict[str, tuple[int, int, int, int, int]] = {}
    def metadata(value: os.stat_result) -> tuple[int, int, int, int, int]:
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
    def read(relative: str) -> bytes:
        relative = path_name(relative)
        if relative in cache:
            return cache[relative]
        current = root
        for part in relative.split("/"):
            current /= part
            if current.is_symlink():
                fail("PATH_UNSAFE")
        before = current.stat()
        if not stat.S_ISREG(before.st_mode):
            fail("FILE_NOT_REGULAR")
        identity = before.st_dev, before.st_ino
        if identity in identities and identities[identity] != relative:
            fail("FILE_ALIAS")
        raw = current.read_bytes()
        after = current.stat()
        if metadata(before) != metadata(after):
            fail("FILE_CHANGED_DURING_READ")
        identities[identity] = relative
        observations[relative] = metadata(after)
        cache[relative] = raw
        return raw
    result = _verify(read, proof_path, expected_package_sha256, expected_proof_sha256, candidate_root)
    for relative, observed in observations.items():
        current = root
        for part in relative.split("/"):
            current /= part
            if current.is_symlink():
                fail("PATH_UNSAFE")
        if metadata(current.stat()) != observed:
            fail("FILE_CHANGED_DURING_READ")
    return result


def release_proof_binding(result: Mapping[str, Any]) -> dict[str, Any]:
    """Small exact binding for release-eval receipts, after successful verification."""
    if result.get("schema_version") != "agent-council.promotion-binding/v1" or result.get("result") != "verified":
        fail("VERIFICATION_REQUIRED")
    return {"schema_version": "agent-council.release-promotion-binding/v1",
            "promotion_proof_sha256": hash_value(result.get("promotion_proof_sha256")),
            "candidate_behavioral_sha256": result["candidate_release_binding"]["behavioral_identity"]["behavioral_sha256"],
            "promoted_behavioral_sha256": result["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"],
            "evidence_assurance": "structural_only"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--proof", default=PROOF_PATH)
    parser.add_argument("--package-sha256")
    parser.add_argument("--proof-sha256")
    args = parser.parse_args()
    try:
        result = verify_promotion(args.root, args.proof, expected_package_sha256=args.package_sha256,
                                  expected_proof_sha256=args.proof_sha256)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"result": "refused", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
