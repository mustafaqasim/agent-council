#!/usr/bin/env python3
"""Deterministic Packet D policy fixtures without creating Council artifacts."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "skills" / "agent-council" / "references" / "routing-policy-packet-d-fixtures.json"
SKILL = ROOT / "skills" / "agent-council" / "SKILL.md"
ADAPTERS = ROOT / "skills" / "agent-council" / "references" / "model-adapters.yaml"

RISK_ROUTES = {
    "asserted_automation_repair": "R1",
    "unexpected_ordinary_failure": "R2",
    "uncertain_composition": "R2",
    "material_design_decision": "R2",
    "architecture_implementation": "R3",
    "shared_contract_change": "R3",
    "lifecycle_authority": "R3",
    "safety_boundary_change": "R3",
    "acceptance_gate_change": "R3",
    "repeated_unresolved_failure": "R3",
    "unqualified_capability_composition": "R3",
    "qualification_failure": "R3",
}
MATERIAL_EVIDENCE = {"scope", "authority", "cause", "contract", "safety", "acceptance", "qualification", "repeated_failure"}


def classify(scenario: dict[str, object]) -> dict[str, object]:
    """Pure classifier: policy checks must not create a case, receipt, or log."""
    if scenario.get("reentry") == "denied":
        return {"outcome": "return_evidence", "case": False, "delegate": False}
    risks = [item for item in scenario.get("risk", []) if item in RISK_ROUTES]
    if risks:
        route = max((RISK_ROUTES[item] for item in risks), key=lambda value: int(value[1:]))
        return {"outcome": route, "case": True, "mutation": scenario.get("authority") != "diagnosis_only"}
    if "new_evidence" in scenario:
        return {"outcome": "lightweight" if scenario.get("economics") == "beneficial" else "direct", "reassess": scenario["new_evidence"] in MATERIAL_EVIDENCE}
    return {"outcome": "lightweight" if scenario.get("economics") == "beneficial" else "direct", "case": False, "mutation": scenario.get("authority") != "diagnosis_only"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    before = {path: path.stat().st_mtime_ns for path in (FIXTURES, SKILL, ADAPTERS)}
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    require(fixtures["schema_version"] == "agent-council.routing-policy-fixtures/v1", "fixture schema mismatch")
    for scenario in fixtures["scenarios"]:
        actual = classify(scenario)
        for key, expected in scenario["expected"].items():
            require(actual.get(key) == expected, f"{scenario['id']}: expected {key}={expected!r}, got {actual.get(key)!r}")
    skill = SKILL.read_text(encoding="utf-8")
    adapters = ADAPTERS.read_text(encoding="utf-8")
    required_skill = (
        "Apply this fixed precedence: user scope, authority, and reentry; qualifying risk; then economics.",
        "A risk trigger overrides task size",
        "known-cause, reversible ordinary local repair",
        "Known cause, reversibility, and line count do not defeat a qualifying trigger",
        "Read-only architecture assessment",
        "Implementing an architecture change is R3.",
        "Diagnosis authorizes diagnosis only",
        "ordinary failure is a failed expected behavior",
        "qualification failure concerns whether a model, binding, capability, or evidence gate is qualified",
        "Reassess only when material evidence changes",
        "compact conversational receipt",
        "Do not create a durable lightweight log, receipt, case, dispatch plan, or invented savings.",
    )
    require(all(item in skill for item in required_skill), "skill omits a Packet D routing boundary")
    required_adapters = (
        "routing_precedence:",
        "lightweight_effort_and_fanout:",
        "Honor an explicit user model or effort preference",
        "Do not persist a lightweight log or claim savings that were not observed.",
    )
    require(all(item in adapters for item in required_adapters), "adapter omits Packet D dispatch guidance")
    after = {path: path.stat().st_mtime_ns for path in before}
    require(after == before, "routing fixture test must not mutate policy files or create Council artifacts")
    print(json.dumps({"result": "passed", "scenarios": len(fixtures["scenarios"]), "side_effects": "none"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
