#!/usr/bin/env python3
"""Behavioral checks for packaged Agent Council activation commands."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ASSERTION_COUNT = 0


def require(condition: bool, message: str) -> None:
    global ASSERTION_COUNT
    ASSERTION_COUNT += 1
    if not condition:
        raise AssertionError(message)


def commands(kind: str) -> dict[str, str]:
    document = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    selected: dict[str, str] = {}
    marker = "agent-council-routing.sh" if kind == "routing" else "Manage-AgentCouncilUpdates.py"
    for event in ("SessionStart", "UserPromptSubmit"):
        event_commands = [item["command"] for group in document["hooks"][event] for item in group["hooks"] if marker in item["command"]]
        require(len(event_commands) == 1, f"{event} must have exactly one {kind} command")
        selected[event] = event_commands[0]
    return selected


def run(command: str, environ: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ.get("PATH", ""), **environ}
    return subprocess.run(["bash", "-c", command], text=True, capture_output=True, env=env, check=False)


def hook_root(path: Path, label: str | None = None) -> Path:
    target = path / "hooks"
    target.mkdir(parents=True)
    source = ROOT / "hooks" / "agent-council-routing.sh"
    if label is None:
        shutil.copy2(source, target / source.name)
    else:
        (target / source.name).write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\nevent=\"${1:-UserPromptSubmit}\"\n"
            f"printf '{{\"selected_root\":\"{label}\",\"event\":\"%s\"}}\\n' \"$event\"\n", encoding="utf-8"
        )
    return path


def report(process: subprocess.CompletedProcess[str], label: str) -> dict[str, object]:
    require(process.returncode == 0, f"{label} failed: {process.stderr}")
    require(bool(process.stdout.strip()), f"{label} did not emit hook JSON")
    result = json.loads(process.stdout)
    require(isinstance(result, dict), f"{label} did not emit a JSON object")
    return result


def main() -> int:
    routing = commands("routing")
    updater = commands("updater")
    for command in [*routing.values(), *updater.values()]:
        require("if [ -n \"${PLUGIN_ROOT:-}\" ]" in command, "hook command does not prefer PLUGIN_ROOT")
        require("elif [ -n \"${CLAUDE_PLUGIN_ROOT:-}\" ]" in command, "hook command lacks Claude fallback")
        require("else exit 0" in command, "hook command does not safely handle missing roots")
        require('"$agent_council_root/' in command, "hook command does not quote its resolved root")

    with tempfile.TemporaryDirectory(prefix="agent-council activation ") as temporary:
        base = Path(temporary)
        codex_root = hook_root(base / "codex root")
        claude_root = hook_root(base / "claude root")
        spaced_root = hook_root(base / "root with spaces")

        for event, command in routing.items():
            codex = report(run(command, {"PLUGIN_ROOT": str(codex_root)}), f"Codex-only {event}")
            require(codex["hookSpecificOutput"]["hookEventName"] == event, f"Codex-only {event} reported the wrong event")
            claude = report(run(command, {"CLAUDE_PLUGIN_ROOT": str(claude_root)}), f"Claude-only {event}")
            require(claude["hookSpecificOutput"]["hookEventName"] == event, f"Claude-only {event} reported the wrong event")
            spaced = report(run(command, {"PLUGIN_ROOT": str(spaced_root)}), f"spaced root {event}")
            require(spaced["hookSpecificOutput"]["hookEventName"] == event, f"spaced root {event} reported the wrong event")
            missing = run(command, {})
            require(missing.returncode == 0 and not missing.stdout and not missing.stderr, f"missing markers {event} must be a silent no-op")

        preferred_codex = hook_root(base / "preferred codex", "codex")
        fallback_claude = hook_root(base / "fallback claude", "claude")
        for event, command in routing.items():
            both = report(run(command, {"PLUGIN_ROOT": str(preferred_codex), "CLAUDE_PLUGIN_ROOT": str(fallback_claude)}), f"both roots {event}")
            require(both == {"selected_root": "codex", "event": event}, f"PLUGIN_ROOT was not preferred for {event}")

        data_dir = base / "non-codex data"
        for event, command in updater.items():
            non_codex = run(command, {"CLAUDE_PLUGIN_ROOT": str(ROOT), "PLUGIN_DATA": str(data_dir)})
            require(non_codex.returncode == 0 and not non_codex.stdout and not non_codex.stderr, f"non-Codex updater must be a silent no-op for {event}")
            require(not data_dir.exists(), f"non-Codex updater created data for {event}")

        diagnostic = ROOT / "scripts" / "Diagnose-AgentCouncil.py"
        before = set(base.iterdir())
        diagnosis = subprocess.run([sys.executable, str(diagnostic)], text=True, capture_output=True,
                                   env={"PATH": os.environ.get("PATH", ""), "PLUGIN_ROOT": str(ROOT), "PLUGIN_DATA": str(data_dir)}, check=False)
        require(diagnosis.returncode == 0, f"diagnostic failed: {diagnosis.stderr}")
        payload = json.loads(diagnosis.stdout)
        require(payload["guarantees"] == {"files_created": False, "install_commands_run": False, "locks_created": False, "network_used": False, "read_only": True}, "diagnostic mutation guarantees are incomplete")
        require(payload["trust"]["status"] == payload["actual_agent_compliance"]["status"] == "unknown", "diagnostic overstates trust or compliance")
        require(payload["root_and_host_markers"]["markers"]["PLUGIN_ROOT"]["matches_package_root"], "diagnostic did not observe PLUGIN_ROOT")
        require(payload["hook_configuration"]["root_fallback_configured"], "diagnostic did not observe root fallback")
        require(set(base.iterdir()) == before and not data_dir.exists(), "diagnostic created a file, directory, or lock")

    print(json.dumps({"result": "passed", "assertions": ASSERTION_COUNT}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
