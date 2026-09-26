#!/usr/bin/env python3
"""Validate and run the package's native Claude eval suite without publication."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

PLUGIN = Path(__file__).resolve().parents[1]
EVAL_DIR = PLUGIN / "evals"
REQUIRED = {
    "lightweight-positive", "R1", "R2", "R3", "trivial-negative",
    "known-cause-local-repair-negative", "read-only-architecture-negative",
    "diagnosis-only-authority", "council-reentry-denied",
    "required-tier-unavailable", "identity-mismatch", "lightweight-fallback",
    "escalation-new-shared-contract", "no-escalation-unchanged-narration",
    "ordinary-vs-qualification-failure", "domain-skill-coexistence",
    "no-nested-council", "ce-absence",
}
DETERMINISTIC = {"regex", "tool_used", "tool_order", "file_exists"}


def load_suite(directory):
    # JSON is a YAML subset. Restrict authored cases to that subset so the
    # release preflight has no PyYAML or other third-party dependency.
    return {"cases": [json.loads(path.read_text()) for path in sorted(directory.glob("*/case.yaml"))]}


def validate_suite(suite):
    errors = []
    cases = suite["cases"]
    covered = {tag for case in cases for tag in case.get("tags", [])}
    errors.extend("missing coverage: " + tag for tag in sorted(REQUIRED - covered))
    names = set()
    for case in cases:
        name = case.get("name", "<unnamed>")
        if name in names:
            errors.append(name + ": duplicate case")
        names.add(name)
        execution = case.get("execution", {})
        if case.get("schema_version") != "1.1" or not execution.get("prompt"):
            errors.append(name + ": invalid schema or missing prompt")
        if execution.get("artifact_publish") is not False:
            errors.append(name + ": artifact_publish must be false")
        if case.get("runs", 0) < 3:
            errors.append(name + ": release cases require at least three runs")
        if not 1 <= execution.get("max_turns", 0) <= 20:
            errors.append(name + ": bounded max_turns required")
        graders = case.get("graders", [])
        if not graders or any(grader.get("type") not in DETERMINISTIC for grader in graders):
            errors.append(name + ": deterministic graders required")
        if not any(grader.get("type") in {"regex", "file_exists"} for grader in graders):
            errors.append(name + ": outcome grader required")
        for grader in graders:
            if grader.get("type") == "tool_order":
                for key in ("before", "after"):
                    matcher = grader.get(key)
                    if not isinstance(matcher, str) and (
                        not isinstance(matcher, dict) or not matcher.get("tool")
                        or set(matcher) - {"tool", "input_match"}
                    ):
                        errors.append(name + ": invalid tool matcher")
        grader_names = [grader.get("name") for grader in graders]
        if len(set(grader_names)) != len(grader_names):
            errors.append(name + ": duplicate grader names")
        if any(grader.get("type") == "tool_used" and grader.get("tool") == "Skill"
               and grader.get("arm") != "both" for grader in graders):
            errors.append(name + ": skill invocation must remain scored during ablation")
        if "lightweight-positive" in case.get("tags", []) and not any(
            grader.get("type") == "tool_used" and grader.get("tool") == "Agent"
            and grader.get("min", 1) >= 1 for grader in graders
        ):
            errors.append(name + ": observed delegation grader required")
        if "domain-skill-coexistence" in case.get("tags", []):
            for token in ("agent-council", "fixture-domain"):
                if not any(grader.get("type") == "tool_used" and grader.get("tool") == "Skill"
                           and token in grader.get("input_match", "")
                           and grader.get("min", 1) >= 1 for grader in graders):
                    errors.append(name + ": observed skill invocation missing: " + token)
            if len(case.get("plugins", [])) != 2:
                errors.append(name + ": coexistence must load both local plugins")
        for plugin in case.get("plugins", []):
            resolved = (EVAL_DIR / name / plugin).resolve()
            if not resolved.is_relative_to(PLUGIN) or not (resolved / ".claude-plugin/plugin.json").is_file():
                errors.append(name + ": fixture plugin is missing or outside package")
    return errors


def validate_command_text(text):
    errors = []
    # Documentation keeps each runnable native command on one physical line.
    for line in text.splitlines():
        if re.search(r"\bclaude\s+plugin\s+eval\b", line):
            if "--no-publish" not in line or "--publish-report" in line:
                errors.append("unsafe documented eval command: publication must be disabled")
    return errors


def validate_tracked_files(paths):
    errors = []
    for path in paths:
        parts = Path(path).parts
        if "evals" not in parts:
            continue
        tail = parts[parts.index("evals") + 1:]
        if any(part in {"results", "local"} for part in tail) or Path(path).name in {
            "aggregate-result.json", "report.html"
        } or path.endswith(".jsonl") or (path.endswith(".json") and tail != (
            "domain-skill-coexistence", "fixture-domain", ".claude-plugin", "plugin.json"
        )):
            errors.append("tracked private eval output: " + path)
    return errors


def check_output_ignores():
    errors = []
    for name in ("results/check/aggregate-result.json", "results/check/report.html", "local/check.json", "accidental-response.json"):
        path = EVAL_DIR / name
        result = subprocess.run(["git", "check-ignore", "--quiet", str(path)], cwd=PLUGIN, capture_output=True)
        if result.returncode != 0:
            errors.append("eval output is not ignored: " + name)
    return errors


def check_native_cli():
    if shutil.which("claude") is None:
        return ["native Claude eval CLI unavailable: claude not on PATH"]
    try:
        result = subprocess.run(["claude", "plugin", "eval", "--help", "--no-publish"],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ["native Claude eval CLI unavailable: " + str(exc)]
    help_text = result.stdout + result.stderr
    required_flags = ("--no-publish", "--ablation", "--runs", "--threshold", "--case", "--max-cost-usd")
    if result.returncode or any(flag not in help_text for flag in required_flags):
        return ["native Claude eval CLI unavailable or required interface unsupported"]
    return []


def validate_all():
    errors = validate_suite(load_suite(EVAL_DIR))
    errors.extend(check_output_ignores())
    errors.extend(check_native_cli())
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=PLUGIN, capture_output=True, text=True, check=True)
    errors.extend(validate_tracked_files(tracked.stdout.split("\0")))
    for path in EVAL_DIR.rglob("*.md"):
        if not {"results", "local"}.intersection(path.relative_to(EVAL_DIR).parts):
            errors.extend(validate_command_text(path.read_text()))
    return errors


def build_command(mode, case=None):
    output = EVAL_DIR / "results" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + mode)
    command = ["claude", "plugin", "eval", str(PLUGIN), "--no-publish", "--trust-plugin",
               "--no-scaffold", "--threshold", "1.0", "--concurrency", "1", "--model", "opus",
               "--output-dir", str(output)]
    if mode == "iterate":
        names = {item["name"] for item in load_suite(EVAL_DIR)["cases"]}
        if case not in names:
            raise ValueError("iterate requires one exact existing --case name")
        command += ["--case", case, "--runs", "1", "--ablation", "none"]
    elif mode == "release":
        command += ["--runs", "3", "--ablation", "with-without"]
    elif mode == "probe":
        command += ["--runs", "1", "--ablation", "none", "--max-cost-usd", "0"]
    else:
        raise ValueError("unknown run mode: " + mode)
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["validate", "iterate", "release", "probe"])
    parser.add_argument("--case")
    parser.add_argument("--print-command", action="store_true", help="show the command without running it")
    args = parser.parse_args()
    try:
        errors = validate_all()
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        if args.mode == "validate":
            print("Native eval structure valid; native CLI available; behavioral qualification not run.")
            return 0
        command = build_command(args.mode, args.case)
        if args.print_command:
            print(shlex.join(command))
            return 0
        # Native output locations are package-local and covered by evals/.gitignore.
        return subprocess.run(command, cwd=PLUGIN).returncode
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
