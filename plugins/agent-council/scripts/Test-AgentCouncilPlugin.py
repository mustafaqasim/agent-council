#!/usr/bin/env python3
"""Focused standalone-plugin contract checks."""
from __future__ import annotations

import json
import hashlib
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


def canonical_sha256(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def main() -> int:
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    claude_manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    repository_root = ROOT.parents[1]
    marketplace_path = repository_root / ".claude-plugin" / "marketplace.json"
    readme_path = repository_root / "README.md"
    source_checkout = (repository_root / "plugins" / "agent-council").resolve() == ROOT
    skill = (ROOT / "skills" / "agent-council" / "SKILL.md").read_text(encoding="utf-8")
    adapters = (ROOT / "skills" / "agent-council" / "references" / "model-adapters.yaml").read_text(encoding="utf-8")
    registry = json.loads((ROOT / "standards" / "agent-model-registry.v2.yaml").read_text(encoding="utf-8"))
    initial_claude_designation = json.loads((ROOT / "standards" / "model-qualifications" / "initial-claude-code-designation.v2.yaml").read_text(encoding="utf-8"))
    opus_55_correction = json.loads((ROOT / "standards" / "model-qualifications" / "claude-opus-5-5-catalog-correction.v1.yaml").read_text(encoding="utf-8"))
    integration = (ROOT / "skills" / "agent-council" / "references" / "compound-engineering.yaml").read_text(encoding="utf-8")
    forward_tests = (ROOT / "skills" / "agent-council" / "references" / "forward-tests.yaml").read_text(encoding="utf-8")
    openai_agent = (ROOT / "skills" / "agent-council" / "agents" / "openai.yaml").read_text(encoding="utf-8")
    claude_agent = (ROOT / "skills" / "agent-council" / "agents" / "claude-code.yaml").read_text(encoding="utf-8")
    profile = (ROOT / "profiles" / "default.yaml").read_text(encoding="utf-8")
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    routing_hook = (ROOT / "hooks" / "agent-council-routing.sh").read_text(encoding="utf-8")
    update_manager = ROOT / "scripts" / "Manage-AgentCouncilUpdates.py"
    update_tests = ROOT / "scripts" / "Test-AgentCouncilUpdates.py"
    activation_diagnostic = ROOT / "scripts" / "Diagnose-AgentCouncil.py"
    activation_tests = ROOT / "scripts" / "Test-AgentCouncilActivation.py"
    routing_tests = ROOT / "scripts" / "Test-RoutingPolicyPacketD.py"
    benchmark_runner = ROOT / "scripts" / "Invoke-AgentCouncilBenchmark.py"
    benchmark_tests = ROOT / "scripts" / "Test-AgentCouncilBenchmark.py"
    runtime = ROOT / "scripts" / "core" / "agent-council" / "0.2.0" / "Invoke-AgentCouncil.py"

    require(manifest["name"] == "agent-council", "plugin identity mismatch")
    require(claude_manifest["name"] == "agent-council", "Claude plugin identity mismatch")
    require(manifest["version"] == claude_manifest["version"] == "0.8.1", "plugin manifest versions are not aligned")
    if source_checkout:
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        readme = readme_path.read_text(encoding="utf-8")
        security = (repository_root / "SECURITY.md").read_text(encoding="utf-8")
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
    selection_text = "Stop manually switching AI models. Send each task to the right model tier and add independent review when the work is risky."
    selection_prompt = "Use $agent-council to choose the right model tier for each part of this task, escalating only when complexity or risk warrants it."
    require(manifest["description"] == selection_text and claude_manifest["description"] == selection_text, "plugin manifest selection metadata is not aligned")
    require(openai_agent == claude_agent, "Codex and Claude agent metadata is not aligned")
    require('short_description: "Match each task to the right AI model"' in openai_agent, "agent selection metadata is not concise")
    require(f'default_prompt: "{selection_prompt}"' in openai_agent, "agent applicability prompt is incomplete")
    require(25 <= len(manifest["interface"]["shortDescription"].rstrip(".")) <= 64, "Codex short description must be 25 to 64 characters")
    require(manifest["interface"]["defaultPrompt"] == [selection_prompt.replace("$agent-council", "Agent Council")], "plugin applicability prompt is incomplete")
    require("interface" not in claude_manifest, "Claude manifest contains unsupported Codex interface metadata")
    session_commands = [item["command"] for group in hooks["hooks"]["SessionStart"] for item in group["hooks"]]
    prompt_commands = [item["command"] for group in hooks["hooks"]["UserPromptSubmit"] for item in group["hooks"]]
    update_command = "Manage-AgentCouncilUpdates.py\" hook --event"
    require(any(update_command in command and "SessionStart" in command for command in session_commands), "daily update checker is missing from SessionStart")
    require(any(update_command in command and "UserPromptSubmit" in command for command in prompt_commands), "update preference handler is missing from UserPromptSubmit")
    require(update_manager.is_file() and update_tests.is_file(), "update manager or its behavioral test is missing")
    require(activation_diagnostic.is_file() and activation_tests.is_file(), "activation diagnostic or its behavioral test is missing")
    require(routing_tests.is_file(), "routing policy behavioral test is missing")
    require(benchmark_runner.is_file() and benchmark_tests.is_file(), "paired benchmark harness or its behavioral test is missing")
    require("PLUGIN_ROOT" in " ".join(session_commands + prompt_commands), "Codex plugin root is not passed to the update manager")
    require(chr(0x2014) not in routing_hook, "routing hook contains a prohibited em dash")
    require("Before each lightweight or governed delegation" in skill, "visible dispatch notice is missing")
    require("Do not create a Council case, immutable dispatch plan, or durable Council receipt solely for lightweight routing." in adapters, "lightweight native dispatch is incorrectly case-bound")
    require("governed_case_required_receipt" in adapters, "governed dispatch receipt requirements are not scoped")
    if source_checkout:
        require("codex plugin marketplace add mustafaqasim/agent-council --ref main" in readme, "public GitHub marketplace install command is missing")
        require("codex plugin add agent-council@agent-council" in readme, "public marketplace plugin selector is missing")
        require("Do not install the repository root as a personal plugin." in readme, "repo-root installation warning is missing")
        require(all(command in readme for command in ("agent-council update now", "agent-council update-check on", "agent-council update-check off", "agent-council update status", "agent-council update cleanup")), "documented update controls are incomplete")
        require("Automatic installation is unavailable." in security, "security policy does not state the automatic-installation boundary")
        require(marketplace["plugins"][0]["source"] == "./plugins/agent-council", "marketplace source must resolve the packaged plugin directory")
    require(all(item in adapters for item in ("ultimate_intelligence", "operational_intelligence", "technical_tactical_intelligence", "worker_intelligence")), "cost classes are incomplete")
    require(registry["registry_sha256"] == canonical_sha256({key: value for key, value in registry.items() if key != "registry_sha256"}), "registry hash is invalid")
    require(all(binding["binding_sha256"] == canonical_sha256({key: value for key, value in binding.items() if key != "binding_sha256"}) for binding in registry["bindings"]), "binding hash is invalid")
    qualified_claude_operational = [binding for binding in registry["bindings"] if binding["provider"] == "claude_code" and binding["tier"] == "operational_intelligence" and binding["status"] == "qualified"]
    require(len(qualified_claude_operational) == 1 and qualified_claude_operational[0]["binding_id"] == "claude-code-v2-operational" and qualified_claude_operational[0]["model_id"] == "claude-opus-5", "Claude Code operational route must remain qualified for Opus 5 only")
    opus_55_candidates = [binding for binding in registry["bindings"] if binding["binding_id"] == "claude-code-v2-operational-opus-5-5"]
    require(len(opus_55_candidates) == 1 and opus_55_candidates[0]["model_id"] == "claude-opus-5-5" and opus_55_candidates[0]["tier"] == "operational_intelligence" and opus_55_candidates[0]["status"] == "candidate", "Opus 5.5 candidate binding is missing or invalid")
    initial_operational = [designation for designation in initial_claude_designation["designations"] if designation["binding_id"] == "claude-code-v2-operational"]
    require(initial_claude_designation["recorded_at"] == "2026-09-21T00:00:00Z" and len(initial_operational) == 1 and initial_operational[0]["model_id"] == "claude-opus-5", "initial Claude designation must not be backdated to Opus 5.5")
    require(opus_55_correction["recorded_at"] == "2026-09-24T03:42:36Z" and opus_55_correction["subject"]["status"] == "candidate" and opus_55_correction["evidence"]["official_release_url"] == "https://platform.claude.com/docs/en/models/opus-5-5/overview", "Opus 5.5 correction record is incomplete")
    require("Two fresh native qualification runs on identical candidate bytes." in opus_55_correction["promotion_requirements"] and "Each run records the observed Claude Code model identity as claude-opus-5-5." in opus_55_correction["promotion_requirements"], "Opus 5.5 promotion requirements are incomplete")
    require('operational_intelligence: "claude-code-v2-operational -> claude-opus-5"' in adapters and "claude-code-v2-operational-opus-5-5 -> claude-opus-5-5, intended successor awaiting qualification" in adapters, "Claude adapter route or candidate notice is invalid")
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
    update_test = subprocess.run([sys.executable, str(update_tests)], text=True, capture_output=True, check=False)
    require(update_test.returncode == 0, f"update manager tests failed: {update_test.stdout[-500:]} {update_test.stderr[-500:]}")
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
        claude_capability = subprocess.run([sys.executable, str(runtime), "capability-capture", "--case-root", str(case_root), "--project-root", str(project_root), "--provider", "claude_code", "--model-id", "claude-opus-5", "--efforts-json", '["high"]', "--context-id", "context-plugin-claude-operational"], text=True, capture_output=True, check=False)
        require(claude_capability.returncode == 0, "Claude Code Opus 5 capability capture failed")
        claude_planned = subprocess.run([sys.executable, str(runtime), "dispatch-plan", "--case-root", str(case_root), "--project-root", str(project_root), "--provider", "claude_code", "--role", "operational_intelligence", "--context-id", "context-plugin-claude-operational", "--decision-kind", "review"], text=True, capture_output=True, check=False)
        require(claude_planned.returncode == 0, "Claude Code operational dispatch plan failed")
        claude_plan = json.loads(claude_planned.stdout)
        require(claude_plan["binding_id"] == "claude-code-v2-operational" and claude_plan["model_id"] == "claude-opus-5", "runtime selected the Opus 5.5 candidate for a qualified operational dispatch")
        candidate_capture = subprocess.run([sys.executable, str(runtime), "dispatch-capture", "--case-root", str(case_root), "--project-root", str(project_root), "--provider", "claude_code", "--plan-nonce", claude_plan["plan_nonce"], "--task-id", "task-plugin-claude-operational", "--model-id", "claude-opus-5-5", "--effort", "high", "--context-id", "context-plugin-claude-operational", "--output-ref", "output-plugin-claude-operational", "--decision-kind", "review"], text=True, capture_output=True, check=False)
        require(candidate_capture.returncode != 0 and "PROVIDER_RECEIPT_MISMATCH" in candidate_capture.stdout, "Opus 5.5 candidate bypassed the qualified dispatch gate")
    print(json.dumps({"result": "passed", "assertions": ASSERTION_COUNT, "source_checkout": source_checkout}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
