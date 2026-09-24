#!/usr/bin/env python3
"""Read-only local observations for Agent Council activation diagnosis."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ROUTING_EVENTS = ("SessionStart", "UserPromptSubmit")


def read_manifest(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "present": path.is_file(), "valid_json": False}
    if not path.is_file():
        return result
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return result
    if not isinstance(document, dict):
        return result
    result.update(valid_json=True, name=document.get("name"), version=document.get("version"))
    return result


def marker(name: str, environ: dict[str, str]) -> dict[str, Any]:
    value = environ.get(name)
    result: dict[str, Any] = {"set": name in environ, "nonempty": bool(value), "absolute": False,
                              "matches_package_root": False}
    if not value:
        return result
    candidate = Path(value)
    result["absolute"] = candidate.is_absolute()
    if candidate.is_absolute():
        try:
            result["matches_package_root"] = candidate.resolve() == ROOT
        except OSError:
            pass
    return result


def hook_observation(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "present": path.is_file(), "valid_json": False,
                              "events": {}, "root_fallback_configured": False}
    if not path.is_file():
        return result
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return result
    if not isinstance(document, dict):
        return result
    result["valid_json"] = True
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        return result
    commands: list[str] = []
    for event in ROUTING_EVENTS:
        event_commands: list[str] = []
        for group in hooks.get(event, []):
            if not isinstance(group, dict):
                continue
            for item in group.get("hooks", []):
                if isinstance(item, dict) and isinstance(item.get("command"), str):
                    event_commands.append(item["command"])
        commands.extend(event_commands)
        result["events"][event] = {"configured": bool(event_commands), "command_count": len(event_commands),
                                   "routing_command_configured": any("agent-council-routing.sh" in command for command in event_commands),
                                   "updater_command_configured": any("Manage-AgentCouncilUpdates.py" in command for command in event_commands)}
    result["root_fallback_configured"] = bool(commands) and all(
        "PLUGIN_ROOT:-" in command and "CLAUDE_PLUGIN_ROOT:-" in command and "else exit 0" in command
        for command in commands
    )
    return result


def updater_observation(environ: dict[str, str]) -> dict[str, Any]:
    manager = ROOT / "scripts" / "Manage-AgentCouncilUpdates.py"
    plugin_root = marker("PLUGIN_ROOT", environ)
    plugin_data = marker("PLUGIN_DATA", environ)
    data_value = environ.get("PLUGIN_DATA")
    data_is_external = False
    if data_value and Path(data_value).is_absolute():
        try:
            data_path = Path(data_value).resolve()
            data_is_external = data_path != ROOT and ROOT not in data_path.parents
        except OSError:
            pass
    eligible = bool(plugin_root["matches_package_root"] and plugin_data["absolute"] and data_is_external)
    return {
        "manager_present": manager.is_file(),
        "codex_cli_on_path": shutil.which("codex") is not None,
        "current_environment_eligible": eligible,
        "capability": "potentially_available" if manager.is_file() and eligible else "not_available_in_current_environment",
        "diagnostic_invoked_updater": False,
        "network_or_install_attempted": False,
    }


def build_report(environ: dict[str, str]) -> dict[str, Any]:
    plugin_marker = marker("PLUGIN_ROOT", environ)
    claude_marker = marker("CLAUDE_PLUGIN_ROOT", environ)
    plugin_data_marker = marker("PLUGIN_DATA", environ)
    codex_claimed = bool(plugin_marker["nonempty"] or plugin_data_marker["nonempty"])
    claude_claimed = bool(claude_marker["nonempty"])
    observed_host = "ambiguous" if codex_claimed and claude_claimed else ("codex" if codex_claimed else ("claude_code" if claude_claimed else "unknown"))
    return {
        "schema_version": "agent-council.activation-diagnostic/v1",
        "guarantees": {"read_only": True, "network_used": False, "files_created": False, "locks_created": False,
                       "install_commands_run": False},
        "package": {
            "root": str(ROOT),
            "root_present": ROOT.is_dir(),
            "codex_manifest": read_manifest(ROOT / ".codex-plugin" / "plugin.json"),
            "claude_manifest": read_manifest(ROOT / ".claude-plugin" / "plugin.json"),
        },
        "runtime": {"python_executable": sys.executable, "python_available": bool(sys.executable),
                    "bash_available": shutil.which("bash") is not None},
        "root_and_host_markers": {
            "observed_host": observed_host,
            "markers": {"PLUGIN_ROOT": plugin_marker, "CLAUDE_PLUGIN_ROOT": claude_marker, "PLUGIN_DATA": plugin_data_marker},
            "interpretation": "Environment markers are observations only; they do not prove installation, trust, or hook execution.",
        },
        "hook_configuration": hook_observation(ROOT / "hooks" / "hooks.json"),
        "fallback_availability": {
            "packaged_skill": (ROOT / "skills" / "agent-council" / "SKILL.md").is_file(),
            "codex_routing_directive": (ROOT / "codex" / "routing-directive.md").is_file(),
            "host_instruction_fallback": "unknown",
            "interpretation": "Packaged artifacts can be observed, but this diagnostic cannot determine whether a host loaded them.",
        },
        "updater_capability": updater_observation(environ),
        "trust": {"status": "unknown", "reason": "No authoritative host trust attestation is available to this diagnostic."},
        "actual_agent_compliance": {"status": "unknown", "reason": "Configuration and hook output cannot prove an agent followed routing policy."},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pretty", action="store_true", help="indent the JSON report")
    args = parser.parse_args(argv)
    print(json.dumps(build_report(dict(os.environ)), indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
