#!/usr/bin/env python3
"""Focused standalone-plugin contract checks."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    skill = (ROOT / "skills" / "agent-council" / "SKILL.md").read_text(encoding="utf-8")
    adapters = (ROOT / "skills" / "agent-council" / "references" / "model-adapters.yaml").read_text(encoding="utf-8")
    integration = (ROOT / "skills" / "agent-council" / "references" / "compound-engineering.yaml").read_text(encoding="utf-8")
    profile = (ROOT / "profiles" / "default.yaml").read_text(encoding="utf-8")
    runtime = ROOT / "scripts" / "core" / "agent-council" / "0.2.0" / "Invoke-AgentCouncil.py"

    require(manifest["name"] == "agent-council", "plugin identity mismatch")
    require(isinstance(manifest["interface"]["defaultPrompt"], list) and all(isinstance(item, str) for item in manifest["interface"]["defaultPrompt"]), "default prompt must be a list of strings")
    require("name: agent-council" in skill, "skill identity mismatch")
    require("Before each delegation" in skill, "visible dispatch notice is missing")
    require(all(item in adapters for item in ("ultimate_intelligence", "operational_intelligence", "technical_tactical_intelligence", "worker_intelligence")), "cost classes are incomplete")
    require("Only one outer orchestrator" in integration, "orchestration lease is missing")
    require("mode:return-to-caller" in integration, "CE return-to-caller boundary is missing")
    require('profile_id: "default"' in profile and 'architecture_change: "R3"' in profile, "default profile route floor is invalid")
    require('semantic_policy: "outer_agent_only"' in profile and 'runtime_snapshot: "pinned_hash_only"' in profile, "default profile enforcement boundary is invalid")

    test = subprocess.run([sys.executable, str(runtime), "init-case", "--help"], text=True, capture_output=True, check=False)
    require(test.returncode == 0 and "--case-root" in test.stdout, "runtime CLI is unavailable")
    with tempfile.TemporaryDirectory(prefix="agent-council-plugin-") as temporary:
        project_root = Path(temporary)
        case_root = Path(temporary) / "case"
        initialized = subprocess.run([sys.executable, str(runtime), "init-case", "--case-root", str(case_root), "--project-root", str(project_root), "--case-id", "case-plugin-check", "--route", "R1"], text=True, capture_output=True, check=False)
        require(initialized.returncode == 0, "runtime case initialization failed")
        state = json.loads((case_root / "case.json").read_text(encoding="utf-8"))
        profile_snapshot = state["project_profile"]
        require(profile_snapshot["profile_id"] == "default" and profile_snapshot["profile_sha256"] == state["policy_bundle"]["artifact_pins"]["profiles/default.yaml"], "default profile snapshot is not pinned")
        capability = subprocess.run([sys.executable, str(runtime), "capability-capture", "--case-root", str(case_root), "--project-root", str(project_root), "--provider", "codex", "--model-id", "gpt-6-astra", "--efforts-json", '["high"]', "--context-id", "context-plugin-routing"], text=True, capture_output=True, check=False)
        require(capability.returncode == 0, "capability capture failed")
        planned = subprocess.run([sys.executable, str(runtime), "dispatch-plan", "--case-root", str(case_root), "--project-root", str(project_root), "--provider", "codex", "--role", "ultimate_intelligence", "--context-id", "context-plugin-routing", "--decision-kind", "routing"], text=True, capture_output=True, check=False)
        require(planned.returncode == 0, "dispatch planning failed")
        plan = json.loads(planned.stdout)
        require(plan["user_notice"]["message"].startswith("Council: gpt-6-astra/high (premium) assigned routing task because "), "dispatch plan did not emit the bound visible notice")
        require(plan["work_method"] == "native" and plan["orchestrator_owner"] == "council" and plan["council_reentry"] == "denied" and plan["execution_mode"] == "native", "native method contract is invalid")
    print(json.dumps({"result": "passed", "assertions": 13}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
