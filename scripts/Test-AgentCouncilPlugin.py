#!/usr/bin/env python3
"""Focused standalone-plugin contract checks."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    skill = (ROOT / "skills" / "agent-council" / "SKILL.md").read_text(encoding="utf-8")
    adapters = yaml.safe_load((ROOT / "skills" / "agent-council" / "references" / "model-adapters.yaml").read_text(encoding="utf-8"))
    integration = yaml.safe_load((ROOT / "skills" / "agent-council" / "references" / "compound-engineering.yaml").read_text(encoding="utf-8"))
    profile = yaml.safe_load((ROOT / "profiles" / "default.yaml").read_text(encoding="utf-8"))
    runtime = ROOT / "scripts" / "core" / "agent-council" / "0.2.0" / "Invoke-CyberRangeAgentCouncil.py"

    require(manifest["name"] == "agent-council", "plugin identity mismatch")
    require("name: agent-council" in skill, "skill identity mismatch")
    require("Before each delegation" in skill, "visible dispatch notice is missing")
    require(set(adapters["common"]["user_notice"]["cost_classes"]) == {"ultimate_intelligence", "operational_intelligence", "technical_tactical_intelligence", "worker_intelligence"}, "cost classes are incomplete")
    require(integration["orchestration_lease"]["rule"].startswith("Only one outer orchestrator"), "orchestration lease is missing")
    require("mode:return-to-caller" in " ".join(integration["boundary"]["forbidden_overlap"]), "CE return-to-caller boundary is missing")
    require(profile["profile_id"] == "default" and profile["route_floors"]["architecture_change"] == "R3", "default profile route floor is invalid")

    test = subprocess.run([sys.executable, str(runtime), "init-case", "--help"], text=True, capture_output=True, check=False)
    require(test.returncode == 0 and "--case-root" in test.stdout, "runtime CLI is unavailable")
    print(json.dumps({"result": "passed", "assertions": 8}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
