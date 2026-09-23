#!/usr/bin/env python3
"""Focused standalone-plugin contract checks."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSERTION_COUNT = 0


def require(condition: bool, message: str) -> None:
    global ASSERTION_COUNT
    ASSERTION_COUNT += 1
    if not condition:
        raise AssertionError(message)


def main() -> int:
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    claude_manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    repository_root = ROOT.parents[1]
    marketplace_path = repository_root / ".claude-plugin" / "marketplace.json"
    readme_path = repository_root / "README.md"
    source_checkout = (repository_root / "plugins" / "agent-council").resolve() == ROOT
    skill = (ROOT / "skills" / "agent-council" / "SKILL.md").read_text(encoding="utf-8")
    adapters = (ROOT / "skills" / "agent-council" / "references" / "model-adapters.yaml").read_text(encoding="utf-8")
    integration = (ROOT / "skills" / "agent-council" / "references" / "compound-engineering.yaml").read_text(encoding="utf-8")
    forward_tests = (ROOT / "skills" / "agent-council" / "references" / "forward-tests.yaml").read_text(encoding="utf-8")
    openai_agent = (ROOT / "skills" / "agent-council" / "agents" / "openai.yaml").read_text(encoding="utf-8")
    claude_agent = (ROOT / "skills" / "agent-council" / "agents" / "claude-code.yaml").read_text(encoding="utf-8")
    profile = (ROOT / "profiles" / "default.yaml").read_text(encoding="utf-8")
    runtime = ROOT / "scripts" / "core" / "agent-council" / "0.2.0" / "Invoke-AgentCouncil.py"

    require(manifest["name"] == "agent-council", "plugin identity mismatch")
    require(claude_manifest["name"] == "agent-council", "Claude plugin identity mismatch")
    require(manifest["version"] == claude_manifest["version"] == "0.6.0", "plugin manifest versions are not aligned")
    if source_checkout:
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        readme = readme_path.read_text(encoding="utf-8")
        require(marketplace["metadata"]["version"] == marketplace["plugins"][0]["version"] == manifest["version"], "marketplace version is not aligned")
    require(isinstance(manifest["interface"]["defaultPrompt"], list) and all(isinstance(item, str) for item in manifest["interface"]["defaultPrompt"]), "default prompt must be a list of strings")
    require("name: agent-council" in skill, "skill identity mismatch")
    activation_classes = ("debugging", "implementation", "refactoring", "planning", "architecture", "integration", "code review", "research", "analysis", "strategy", "business planning", "document creation", "editorial review")
    require(all(item in skill for item in activation_classes), "skill omits a substantive routing class")
    require("read-only applicability check" in skill, "skill lacks the first-stage applicability check")
    require("Explicit invocation guarantees the applicability check, not delegation or automatic case creation." in skill, "explicit invocation contract is incomplete")
    require("Lightweight routing creates no Council case or receipts." in skill, "lightweight routing boundary is missing")
    require("developing a consulting offer from existing research" in skill, "separable consulting work does not default to lightweight routing")
    require("If the preferred lightweight tier is unavailable" in skill, "lightweight availability fallback is missing")
    require("Lightweight routing may select an independently qualified higher tier" in adapters, "lightweight higher-tier fallback conflicts with governed substitution rules")
    require("Council check: direct execution" in skill and "Council check: lightweight routing" in skill and "Council check: governed case" in skill, "observable applicability outcomes are incomplete")
    require("Reconsider formal governance only when material new evidence changes risk." in skill, "risk reconsideration boundary is missing")
    require("council_reentry: denied" in skill and "do not invoke Agent Council" in skill, "nested Council reentry protection is missing")
    require("Native standalone workflow is primary" in skill, "native standalone path is not primary")
    require("optional interoperability path" in skill, "Compound Engineering optionality is unclear")
    require("formatting-only changes" in skill and "deterministic checks using already-qualified components" in skill, "explicit negative activation cases are missing")
    selection_text = "Route substantive work to cost-effective model tiers and add evidence gates when risk warrants them."
    selection_prompt = "Use $agent-council to route this work cost-effectively and apply governance only when risk warrants it."
    require(manifest["description"] == selection_text and claude_manifest["description"] == selection_text, "plugin manifest selection metadata is not aligned")
    require(openai_agent == claude_agent, "Codex and Claude agent metadata is not aligned")
    require('short_description: "Route substantive work to the right model tier"' in openai_agent, "agent selection metadata is not concise")
    require(f'default_prompt: "{selection_prompt}"' in openai_agent, "agent applicability prompt is incomplete")
    require(25 <= len(manifest["interface"]["shortDescription"].rstrip(".")) <= 64, "Codex short description must be 25 to 64 characters")
    require(manifest["interface"]["defaultPrompt"] == [selection_prompt.replace("$agent-council", "Agent Council")], "plugin applicability prompt is incomplete")
    require("interface" not in claude_manifest, "Claude manifest contains unsupported Codex interface metadata")
    require("Before each lightweight or governed delegation" in skill, "visible dispatch notice is missing")
    require("Do not create a Council case, immutable dispatch plan, or durable Council receipt solely for lightweight routing." in adapters, "lightweight native dispatch is incorrectly case-bound")
    require("governed_case_required_receipt" in adapters, "governed dispatch receipt requirements are not scoped")
    if source_checkout:
        require("codex plugin marketplace add mustafaqasim/agent-council --ref main" in readme, "public GitHub marketplace install command is missing")
        require("codex plugin add agent-council@agent-council" in readme, "public marketplace plugin selector is missing")
        require("Do not install the repository root as a personal plugin." in readme, "repo-root installation warning is missing")
        require(marketplace["plugins"][0]["source"] == "./plugins/agent-council", "marketplace source must resolve the packaged plugin directory")
    require(all(item in adapters for item in ("ultimate_intelligence", "operational_intelligence", "technical_tactical_intelligence", "worker_intelligence")), "cost classes are incomplete")
    require("Only one outer orchestrator" in integration, "orchestration lease is missing")
    require("mode:return-to-caller" in integration, "CE return-to-caller boundary is missing")
    require("Native standalone workflow is primary" in integration, "CE integration lacks a native standalone path")
    require("optional interoperability path" in integration, "CE integration is not explicitly optional")
    require("not a required dependency, command, hook, skill, installation check, runtime assumption, or gate" in integration, "CE absence can still appear to block a Council gate")
    require("continue with the native standalone workflow" in integration, "CE-absent operation is not explicit")
    require("structural test" in forward_tests and "fresh-chat selection evidence" in forward_tests, "forward tests do not distinguish structural and fresh-chat evidence")
    require(all(item in forward_tests for item in ("debugging", "routine refactor", "council_reentry: denied", "Compound Engineering is absent", "CrowdStrike research", "Correct one typo", 'id: "GFT22"')), "forward tests lack engineering, general-work, negative, nested, standalone, or availability scenarios")
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
    print(json.dumps({"result": "passed", "assertions": ASSERTION_COUNT, "source_checkout": source_checkout}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
