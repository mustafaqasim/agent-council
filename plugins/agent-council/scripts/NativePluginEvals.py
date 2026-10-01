#!/usr/bin/env python3
"""Validate and run the package's native Claude eval suite without publication."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import uuid

from ClaudeQualificationHarness import current_release_binding, digest_bytes

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
CAMPAIGN_SCHEMA = "agent-council.native-release-campaign/v1"
CAMPAIGN_MODEL = "claude-opus-5-5"
CAMPAIGN_CAP = Decimal("20")


def canonical_hash(value):
    return digest_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False).encode("utf-8"))


def campaign_slots(cases):
    if len(cases) != 16 or len(set(cases)) != 16:
        raise ValueError("release campaign requires exactly 16 unique cases")
    return [{"case": name, "round": round_number,
             "id": f"{round_number:02d}-{name}"}
            for round_number in range(1, 4) for name in sorted(cases)]


def cli_version():
    result = subprocess.run(["claude", "--version"], capture_output=True, text=True,
                            timeout=30, check=True)
    version = (result.stdout or result.stderr).strip()
    if not version:
        raise ValueError("native CLI version unavailable")
    return version


def campaign_command(package, output, case, remaining):
    return ["claude", "plugin", "eval", str(package), "--no-publish", "--trust-plugin",
            "--no-scaffold", "--threshold", "1.0", "--concurrency", "1",
            "--model", CAMPAIGN_MODEL, "--output-dir", str(output), "--case", case,
            "--runs", "1", "--ablation", "with-without", "--keep-temp",
            "--max-cost-usd", str(remaining)]


def campaign_init(directory):
    directory = directory.resolve()
    results_root = EVAL_DIR / "results"
    if results_root.is_symlink() or directory.parent != results_root.resolve():
        raise ValueError("campaign must be a direct child of ignored evals/results")
    cases = [case["name"] for case in load_suite(EVAL_DIR)["cases"]]
    slots = campaign_slots(cases)
    binding = current_release_binding(PLUGIN)
    evidence = promotion_evidence_for("release", build_command("release"), binding)
    if evidence is None:
        raise ValueError("release campaign requires verified eight-binding public promotion")
    version = cli_version()
    results_root.mkdir(exist_ok=True)
    directory.mkdir(parents=False, exist_ok=False)
    package = directory / "verified-package"
    frozen_package(PLUGIN, package, binding, evidence, "release", build_command("release"))
    manifest = {"schema_version": CAMPAIGN_SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
                "release_binding": binding, "promotion_binding": evidence[0],
                "cli_version": version, "model": CAMPAIGN_MODEL,
                "cost_cap_usd": str(CAMPAIGN_CAP), "slots": slots}
    (directory / "campaign.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def read_campaign(directory):
    directory = directory.resolve()
    manifest = json.loads((directory / "campaign.json").read_text())
    if manifest.get("schema_version") != CAMPAIGN_SCHEMA or manifest.get("model") != CAMPAIGN_MODEL or \
            manifest.get("cost_cap_usd") != str(CAMPAIGN_CAP):
        raise ValueError("campaign manifest contract changed")
    slots = campaign_slots([case["name"] for case in load_suite(EVAL_DIR)["cases"]])
    if manifest.get("slots") != slots:
        raise ValueError("campaign slot inventory changed")
    binding = current_release_binding(PLUGIN)
    evidence = promotion_evidence_for("release", build_command("release"), binding)
    if evidence is None or manifest.get("release_binding") != binding or \
            manifest.get("promotion_binding") != evidence[0] or \
            current_release_binding(directory / "verified-package") != binding or \
            promotion_evidence_for("release", build_command("release"), binding,
                                   directory / "verified-package", candidate_root=PLUGIN)[0] != evidence[0]:
        raise ValueError("campaign verified package or promotion changed")
    if manifest.get("cli_version") != cli_version():
        raise ValueError("native CLI version changed during campaign")
    return manifest


def slot_cost(aggregate):
    value = aggregate.get("costUsd")
    try:
        cost = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError("native aggregate cost missing") from None
    if not cost.is_finite() or cost < 0:
        raise ValueError("native aggregate cost invalid")
    return cost


def output_hashes(result_directory):
    if result_directory.is_symlink() or not result_directory.is_dir():
        raise ValueError("native result directory missing")
    hashes = {}
    for path in sorted(result_directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("native output contains symlink")
        if path.is_file():
            hashes[path.relative_to(result_directory).as_posix()] = digest_bytes(path.read_bytes())
    if "aggregate-result.json" not in hashes:
        raise ValueError("native aggregate missing")
    return hashes


def native_time(value):
    if not isinstance(value, str):
        raise ValueError("native timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("native timestamp has no timezone")
    return parsed


def preserve_traces(aggregate, result_directory):
    """Copy original native bytes before sealing; never rewrite the aggregate."""
    destination = result_directory / "traces"
    destination.mkdir(exist_ok=False)
    for arm_name in ("with", "without"):
        arm = aggregate["cases"][0]["arms"][arm_name][0]
        source = Path(arm["tracePath"])
        if not source.is_absolute() or any(part.is_symlink() for part in (source, *source.parents)):
            raise ValueError("native trace source must be absolute without symlinks")
        (destination / (arm_name + ".jsonl")).write_bytes(source.read_bytes())


def session_start_output(package):
    """Read the pinned hook's literal context without executing package code."""
    source = (package / "hooks/agent-council-routing.sh").read_text()
    match = re.search(r'if \[ "\$event" = "SessionStart" \]; then\n  msg="([^"\\$`]+)"\nelse', source)
    if match is None:
        raise ValueError("native SessionStart context is not a supported pinned literal")
    return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                              "additionalContext": match[1]}}) + "\n"


def check_native_prefix(prefix, session, package, allow_package_context=False):
    """Accept only paired startup hook records, not pre-init conversation.

    Hook output is matched to the pinned package, not authenticated as a host
    event. Original bytes remain in the sealed trace and are never filtered.
    """
    common = {"type", "subtype", "hook_id", "hook_name", "hook_event", "session_id", "uuid"}
    response = {"exit_code", "outcome", "output", "stdout", "stderr"}
    started, pending, event_ids = set(), set(), set()
    expected_output = None
    for event in prefix:
        subtype = event.get("subtype")
        if (event.get("type") != "system" or subtype not in {"hook_started", "hook_response"}
                or set(event) != common | (response if subtype == "hook_response" else set())
                or event.get("hook_event") != "SessionStart"
                or event.get("hook_name") != "SessionStart:startup"
                or event.get("session_id") != session):
            raise ValueError("native pre-init event is not exact SessionStart metadata")
        for field in ("hook_id", "uuid"):
            value = event[field]
            if not isinstance(value, str) or str(uuid.UUID(value)) != value:
                raise ValueError("native SessionStart identity invalid")
        if event["uuid"] in event_ids:
            raise ValueError("native SessionStart event identity repeated")
        event_ids.add(event["uuid"])
        hook = event["hook_id"]
        if subtype == "hook_started":
            if hook in started:
                raise ValueError("native SessionStart hook repeated")
            started.add(hook)
            pending.add(hook)
            continue
        if hook not in pending:
            raise ValueError("native SessionStart response has no pending start")
        pending.remove(hook)
        if (type(event["exit_code"]) is not int or event["exit_code"] != 0
                or event["outcome"] != "success" or event["stderr"] != ""
                or not isinstance(event["stdout"], str) or event["stdout"] != event["output"]):
            raise ValueError("native SessionStart response unsuccessful or malformed")
        if event["output"]:
            if not allow_package_context:
                raise ValueError("native without-plugin SessionStart contains package context")
            if expected_output is None:
                expected_output = session_start_output(package)
            if event["output"] != expected_output:
                raise ValueError("native SessionStart output differs from pinned context")
    if pending:
        raise ValueError("native SessionStart hook has no response before init")


def check_native_inventory(initial, arm_name, package):
    """Match reported inventory to the ablation arm, without authenticating it."""
    inventories = {}
    for field in ("agents", "skills", "plugins"):
        entries = initial.get(field)
        if not isinstance(entries, list) or len(entries) > 512:
            raise ValueError("native init " + field + " inventory missing or malformed")
        if field != "plugins":
            if any(not isinstance(entry, str) or not entry or entry != entry.strip()
                   or len(entry) > 256 for entry in entries) or len(set(entries)) != len(entries):
                raise ValueError("native init " + field + " inventory malformed or duplicated")
        else:
            for entry in entries:
                if (not isinstance(entry, dict) or not {"name", "path", "source"} <= set(entry)
                        or set(entry) - {"name", "path", "source", "version"}
                        or any(not isinstance(value, str) or not value or value != value.strip()
                               or len(value) > 4096 for value in entry.values())):
                    raise ValueError("native init plugins inventory malformed")
            if len({entry["name"] for entry in entries}) != len(entries):
                raise ValueError("native init plugins inventory duplicated")
        inventories[field] = entries
    expected_agents = {"agent-council:council-" + tier
                       for tier in ("worker", "technical", "operational", "ultimate")}
    council_agents = {name for name in inventories["agents"]
                      if name.startswith("agent-council:") or name in
                      {"council-worker", "council-technical", "council-operational", "council-ultimate"}}
    council_skills = {name for name in inventories["skills"]
                      if name == "agent-council" or name.startswith("agent-council:")}
    package_path = package.resolve()
    council_plugins = [entry for entry in inventories["plugins"]
                       if entry["name"] == "agent-council" or entry["source"].startswith("agent-council@")
                       or (Path(entry["path"]).is_absolute() and Path(entry["path"]).resolve() == package_path)]
    if arm_name == "without":
        if council_agents or council_skills or council_plugins:
            raise ValueError("native without-plugin inventory contains Council")
        return
    if arm_name != "with":
        raise ValueError("native inventory arm invalid")
    if (council_agents != expected_agents or council_skills != {"agent-council:agent-council"}
            or len(council_plugins) != 1):
        raise ValueError("native with-plugin Council inventory missing or changed")
    plugin = council_plugins[0]
    expected_version = json.loads((package / ".claude-plugin/plugin.json").read_text())["version"]
    if (plugin["name"] != "agent-council" or plugin["source"] != "agent-council@inline"
            or not Path(plugin["path"]).is_absolute() or Path(plugin["path"]).resolve() != package_path
            or plugin.get("version") != expected_version):
        raise ValueError("native with-plugin identity differs from verified package")


def check_native_traces(aggregate, result_directory, preparation, receipt, prior_completed, package=None):
    """Return native identities only after validating the retained stream events."""
    prepared = native_time(preparation.get("recorded_at"))
    completed = native_time(receipt.get("completed_at"))
    started = native_time(aggregate.get("startedAt"))
    if not prepared < started <= completed or (prior_completed is not None and prepared < prior_completed):
        raise ValueError("native run precedes preparation or prior slot completion")
    identities = []
    sources = []
    provider_ids = set()
    previous_start = started
    for arm_name in ("with", "without"):
        arm = aggregate["cases"][0]["arms"][arm_name][0]
        arm_start = native_time(arm.get("startedAt"))
        if not previous_start <= arm_start <= completed:
            raise ValueError("native arms are not ordered within the prepared run")
        previous_start = arm_start
        source = arm.get("tracePath")
        if not isinstance(source, str) or not Path(source).is_absolute():
            raise ValueError("native trace source identity missing")
        sources.append(source)
        raw = (result_directory / "traces" / (arm_name + ".jsonl")).read_bytes()
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if not events or any(not isinstance(event, dict) for event in events):
            raise ValueError("native trace events invalid")
        initial = [event for event in events if event.get("type") == "system" and event.get("subtype") == "init"]
        results = [event for event in events if event.get("type") == "result"]
        if len(initial) != 1 or len(results) != 1 or events[-1] != results[0]:
            raise ValueError("native trace init or terminal result missing or repeated")
        session = initial[0].get("session_id")
        if not isinstance(session, str) or str(uuid.UUID(session)) != session or \
                {event.get("session_id") for event in events} != {session}:
            raise ValueError("native trace session identity inconsistent")
        verified_package = PLUGIN if package is None else package
        check_native_prefix(events[:events.index(initial[0])], session, verified_package,
                            allow_package_context=arm_name == "with")
        check_native_inventory(initial[0], arm_name, verified_package)
        if initial[0].get("model") != CAMPAIGN_MODEL:
            raise ValueError("native trace resolved model mismatch")
        assistants = [event for event in events if event.get("type") == "assistant" and
                      event.get("parent_tool_use_id") is None]
        if not assistants or any(event.get("is_api_error_message") or event.get("error") or
                                 event.get("message", {}).get("model") != CAMPAIGN_MODEL
                                 for event in assistants):
            raise ValueError("native trace lacks exact successful model response")
        previous_message = arm_start
        arm_provider_ids = set()
        for event in assistants:
            message_id = event["message"].get("id")
            if not isinstance(message_id, str) or not message_id.strip():
                raise ValueError("native assistant provider message identity missing")
            arm_provider_ids.add(("message", message_id))
            request_id = event.get("request_id")
            if request_id is not None:
                if not isinstance(request_id, str) or not request_id.strip():
                    raise ValueError("native assistant provider request identity invalid")
                arm_provider_ids.add(("request", request_id))
            timestamp = native_time(event.get("timestamp"))
            if not previous_message <= timestamp <= completed:
                raise ValueError("native trace response timestamp outside prepared run")
            previous_message = timestamp
        # Streaming can repeat one provider message within an arm, but another
        # arm or slot must never reuse that response or provider request.
        if provider_ids.intersection(arm_provider_ids):
            raise ValueError("native provider response replay detected across arms")
        provider_ids.update(arm_provider_ids)
        terminal = results[0]
        if terminal.get("subtype") != "success" or terminal.get("is_error") is not False or \
                CAMPAIGN_MODEL not in terminal.get("modelUsage", {}):
            raise ValueError("native trace terminal result failed or model usage missing")
        if slot_cost({"costUsd": terminal.get("total_cost_usd")}) != slot_cost(arm):
            raise ValueError("native trace cost differs from aggregate arm")
        previous_start = previous_message
        identities.append(session)
    return identities, sources, provider_ids, started, completed


def check_slot(aggregate, slot, manifest, package=None):
    errors = []
    if aggregate.get("schemaVersion") != 1 or aggregate.get("partial") is not False or aggregate.get("partialReason"):
        errors.append("native aggregate partial or invalid")
    suite = aggregate.get("suite", {})
    if suite.get("ablation") != "with-without" or suite.get("modelOverride") != CAMPAIGN_MODEL or \
            suite.get("threshold") != 1 or suite.get("concurrency") != 1:
        errors.append("native suite parameters changed")
    if package is not None and suite.get("root") != str(package):
        errors.append("native suite root changed")
    pinned_version = re.search(r"\d+\.\d+\.\d+", manifest["cli_version"])
    if pinned_version is None or aggregate.get("claudeVersion") != pinned_version.group():
        errors.append("native CLI version mismatch")
    cases = aggregate.get("cases")
    if not isinstance(cases, list) or len(cases) != 1 or cases[0].get("name") != slot["case"]:
        errors.append("native case mismatch")
    else:
        case = cases[0]
        if case.get("runsPerCase") != 1 or case.get("dir") != "evals/" + slot["case"] or \
                case.get("source") != "case_yaml":
            errors.append("native run count mismatch")
        authored = next((item for item in load_suite(EVAL_DIR)["cases"]
                         if item["name"] == slot["case"]), None)
        grader_names = [item.get("name") for item in case.get("graders", [])]
        expected_names = [item.get("name") for item in authored.get("graders", [])] if authored else []
        if not expected_names or grader_names != expected_names:
            errors.append("native grader inventory mismatch")
        arms = case.get("arms", {})
        if set(arms) != {"with", "without"} or any(not isinstance(arms[arm], list) or len(arms[arm]) != 1 for arm in ("with", "without")):
            errors.append("both native arms required")
        else:
            arm_cost = Decimal(0)
            for arm_name in ("with", "without"):
                arm = arms[arm_name][0]
                if type(arm.get("score")) not in {int, float} or not 0 <= arm["score"] <= 1 or \
                        type(arm.get("passed")) is not bool:
                    errors.append(arm_name + " arm score invalid")
                try:
                    run_cost = Decimal(str(arm.get("costUsd")))
                    if not run_cost.is_finite() or run_cost < 0:
                        raise InvalidOperation()
                    arm_cost += run_cost
                except (InvalidOperation, TypeError):
                    errors.append(arm_name + " arm cost invalid")
                graders = arm.get("graders")
                if arm.get("error") is not None or arm.get("skippedPaidGraders") is not False or \
                        not isinstance(graders, list) or [item.get("name") for item in graders] != expected_names or \
                        any(grader.get("scored") is not True or grader.get("passed") not in {True, False}
                            for grader in graders):
                    errors.append(arm_name + " arm error or skipped grader")
                if arm_name == "with" and (arm.get("score") != 1 or arm.get("passed") is not True or
                                            any(grader.get("passed") is not True for grader in graders or [])):
                    errors.append("with arm below 1.0")
            try:
                if abs(slot_cost(aggregate) - arm_cost) > Decimal("0.000001"):
                    errors.append("native cost does not match arms")
            except ValueError:
                pass
    try:
        slot_cost(aggregate)
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def campaign_receipts(directory, manifest):
    slots_dir = directory / "slots"
    expected = {slot["id"] for slot in manifest["slots"]}
    actual = {path.name for path in slots_dir.iterdir()} if slots_dir.exists() else set()
    errors = ["unexpected or duplicate slot directory: " + name for name in sorted(actual - expected)]
    receipts = []
    sessions, sources, provider_ids, starts = set(), set(), set(), set()
    prior_completed = None
    gap = False
    for slot in manifest["slots"]:
        path = slots_dir / slot["id"]
        if not path.exists():
            gap = True
            continue
        if gap:
            errors.append(slot["id"] + ": slot appears after an unattempted gap")
        receipt_path = path / "receipt.json"
        if not receipt_path.is_file():
            errors.append(slot["id"] + ": attempted slot has no seal")
            continue
        try:
            receipt = json.loads(receipt_path.read_text())
            aggregate_path = path / "result/aggregate-result.json"
            aggregate_bytes = aggregate_path.read_bytes()
            aggregate = json.loads(aggregate_bytes)
            preparation_bytes = (path / "preparation.json").read_bytes()
            if receipt.get("slot") != slot or receipt.get("manifest_sha256") != canonical_hash(manifest) or \
                    receipt.get("preparation_sha256") != digest_bytes(preparation_bytes) or \
                    receipt.get("aggregate_sha256") != digest_bytes(aggregate_bytes) or \
                    receipt.get("output_sha256") != output_hashes(path / "result"):
                errors.append(slot["id"] + ": seal mismatch")
            preparation = json.loads(preparation_bytes)
            if preparation.get("slot") != slot or preparation.get("manifest_sha256") != canonical_hash(manifest) or \
                    preparation.get("command") != receipt.get("command"):
                errors.append(slot["id"] + ": preparation mismatch")
            if native_time(preparation.get("recorded_at")) < native_time(manifest.get("created_at")):
                errors.append(slot["id"] + ": preparation precedes campaign creation")
            prior_cost = sum((Decimal(item["cost_usd"]) for item in receipts), Decimal(0))
            expected_command = campaign_command(directory / "verified-package", path / "result",
                                                slot["case"], CAMPAIGN_CAP - prior_cost)
            if receipt.get("command") != expected_command:
                errors.append(slot["id"] + ": native command or cost ceiling changed")
            if receipt.get("exit_code") != 0 or receipt.get("cost_usd") != str(slot_cost(aggregate)) or \
                    receipt.get("trace_preservation_error") is not None:
                errors.append(slot["id"] + ": native command failed or cost mismatch")
            errors.extend(slot["id"] + ": " + item for item in check_slot(
                aggregate, slot, manifest, directory / "verified-package"))
            identities, trace_sources, response_ids, started, completed = check_native_traces(
                aggregate, path / "result", preparation, receipt, prior_completed,
                directory / "verified-package")
            if len(set(identities)) != 2 or sessions.intersection(identities) or \
                    len(set(trace_sources)) != 2 or sources.intersection(trace_sources) or started in starts:
                errors.append(slot["id"] + ": native run or arm replay detected")
            if provider_ids.intersection(response_ids):
                errors.append(slot["id"] + ": native provider response replay detected across slots")
            sessions.update(identities)
            sources.update(trace_sources)
            provider_ids.update(response_ids)
            starts.add(started)
            prior_completed = completed
            receipts.append(receipt)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(slot["id"] + ": invalid sealed output: " + str(exc))
    if sum((Decimal(receipt["cost_usd"]) for receipt in receipts), Decimal(0)) > CAMPAIGN_CAP:
        errors.append("global $20 cost cap exceeded")
    return receipts, errors


def campaign_step(directory):
    manifest = read_campaign(directory)
    receipts, errors = campaign_receipts(directory, manifest)
    if errors:
        raise ValueError("campaign stopped: " + "; ".join(errors))
    if len(receipts) == len(manifest["slots"]):
        raise ValueError("campaign has no unattempted slots")
    spent = sum((Decimal(receipt["cost_usd"]) for receipt in receipts), Decimal(0))
    remaining = CAMPAIGN_CAP - spent
    if remaining <= 0:
        raise ValueError("campaign global cost cap reached")
    slot = manifest["slots"][len(receipts)]
    path = directory / "slots" / slot["id"]
    path.parent.mkdir(exist_ok=True)
    path.mkdir(exist_ok=False)  # A crash leaves an attempted slot, never a retryable gap.
    command = campaign_command(directory / "verified-package", path / "result", slot["case"], remaining)
    preparation = {"slot": slot, "manifest_sha256": canonical_hash(manifest), "command": command,
                   "recorded_at": datetime.now(timezone.utc).isoformat()}
    preparation_path = path / "preparation.json"
    preparation_path.write_text(json.dumps(preparation, indent=2) + "\n")
    print("Native budget is checked before each arm launches; $20 is an acceptance cap, "
          "not a strict spend ceiling. Any observed overrun stops and invalidates the campaign.", flush=True)
    result = subprocess.run(command, cwd=directory / "verified-package")
    aggregate_path = path / "result/aggregate-result.json"
    aggregate_bytes = aggregate_path.read_bytes() if aggregate_path.is_file() else b""
    aggregate = json.loads(aggregate_bytes) if aggregate_bytes else {}
    cost = slot_cost(aggregate) if aggregate_bytes else Decimal(0)
    trace_error = None
    if aggregate_bytes:
        try:
            preserve_traces(aggregate, path / "result")
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            trace_error = str(exc)
    hashes = output_hashes(path / "result") if aggregate_bytes else {}
    receipt = {"slot": slot, "manifest_sha256": canonical_hash(manifest), "command": command,
               "preparation_sha256": digest_bytes(preparation_path.read_bytes()),
               "aggregate_sha256": digest_bytes(aggregate_bytes), "output_sha256": hashes,
               "cost_usd": str(cost), "trace_preservation_error": trace_error,
               "exit_code": result.returncode, "completed_at": datetime.now(timezone.utc).isoformat()}
    (path / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if cost > remaining:
        raise ValueError(f"campaign global $20 acceptance cap exceeded: observed ${spent + cost}; "
                         "native prelaunch budget permitted an in-flight overrun")
    if trace_error:
        raise ValueError("campaign native trace preservation failed: " + trace_error)
    read_campaign(directory)
    _, errors = campaign_receipts(directory, manifest)
    if errors:
        raise ValueError("campaign slot failed: " + "; ".join(errors))
    return slot


def campaign_verify(directory):
    manifest = read_campaign(directory)
    receipts, errors = campaign_receipts(directory, manifest)
    if len(receipts) != 48:
        errors.append(f"campaign has {len(receipts)}/48 complete slots")
    spent = sum((Decimal(receipt["cost_usd"]) for receipt in receipts), Decimal(0))
    if spent > CAMPAIGN_CAP:
        errors.append("global $20 cost cap exceeded")
    return errors, spent


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
            if grader.get("type") == "regex":
                if (grader.get("match") not in {"contains", "not_contains"}
                    or grader.get("target") != "last_message"
                    or not isinstance(grader.get("pattern"), str)
                    or not grader.get("pattern")
                    or grader.get("flags", "") not in {"", "i"}):
                    errors.append(name + ": invalid response regex grader")
                else:
                    try:
                        re.compile(grader["pattern"], re.I if grader.get("flags") == "i" else 0)
                    except re.error:
                        errors.append(name + ": invalid response regex pattern")
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
        if "lightweight-positive" in case.get("tags", []) and not any(
            grader.get("type") == "tool_used" and grader.get("tool") == "Agent"
            and grader.get("input_match") == "agent-council:council-(worker|technical)"
            and grader.get("min", 1) >= 1 for grader in graders
        ):
            errors.append(name + ": qualified plugin agent grader required")
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
               "--no-scaffold", "--threshold", "1.0", "--concurrency", "1", "--model", "claude-opus-5-5",
               "--output-dir", str(output)]
    if mode == "iterate":
        names = {item["name"] for item in load_suite(EVAL_DIR)["cases"]}
        if case not in names:
            raise ValueError("iterate requires one exact existing --case name")
        command += ["--case", case, "--runs", "1", "--ablation", "none", "--keep-temp"]
    elif mode == "release":
        command += ["--runs", "3", "--ablation", "with-without", "--max-cost-usd", "20"]
    elif mode == "probe":
        command += ["--runs", "1", "--ablation", "none", "--max-cost-usd", "0"]
    else:
        raise ValueError("unknown run mode: " + mode)
    return command


def promotion_evidence_for(mode, command, release_binding, root=None, candidate_root=None):
    """Require the v3 proof for behavioral runs that use qualified agents."""
    root = PLUGIN if root is None else root
    selected = command[command.index("--case") + 1] if "--case" in command else None
    release_command = "--ablation" in command and command[command.index("--ablation") + 1] == "with-without"
    needs_promotion = mode == "release" or release_command or any(
        case["name"] == selected and "lightweight-positive" in case.get("tags", [])
        for case in load_suite(EVAL_DIR)["cases"])
    if not needs_promotion:
        return None
    registry = root / "standards/agent-model-registry.v3.yaml"
    if not registry.exists() and not registry.is_symlink():
        return None  # Historical v2 packages did not carry a v3 registry.
    from AgentCouncilPromotion import BINDINGS, ROLE_PROTOCOL, release_proof_binding, verify_promotion
    try:
        verified = verify_promotion(root, candidate_root=candidate_root)
        if ("standards/qualification-protocol.v1.yaml" in release_binding["behavioral_identity"]["paths"] and
                verified.get("qualification_protocol_version") != ROLE_PROTOCOL):
            raise ValueError("current role package requires role qualification proof")
        if (mode == "release" or release_command) and not set(BINDINGS) <= set(verified["binding_ids"]):
            raise ValueError("full release requires all default v3 bindings to be qualified")
        if verified["promoted_release_binding"] != release_binding:
            raise ValueError("promoted package identity changed")
        proof_binding = release_proof_binding(verified)
        if (proof_binding["promoted_behavioral_sha256"] !=
                release_binding["behavioral_identity"]["behavioral_sha256"]):
            raise ValueError("promoted package identity mismatch")
        return proof_binding, verified["artifact_paths"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("verified v3 promotion required: " + str(exc)) from exc


def validate_execution_command(command, mode):
    """Do not let a changed command weaken the wrapper's release contract."""
    if mode not in {"iterate", "release", "probe"}:
        raise ValueError("unknown run mode: " + str(mode))
    if not isinstance(command, list) or any(not isinstance(value, str) for value in command):
        raise ValueError("native eval command must be an argument list")
    if len(command) < 4 or command[:3] != ["claude", "plugin", "eval"]:
        raise ValueError("native eval command must use the native eval entry point")
    if Path(command[3]).resolve() != PLUGIN.resolve():
        raise ValueError("native eval command must target the verified package")
    switches = {"--no-publish", "--trust-plugin", "--no-scaffold", "--keep-temp"}
    values = {"--threshold", "--concurrency", "--model", "--output-dir",
              "--runs", "--ablation", "--max-cost-usd", "--case"}
    observed = {}
    index = 4
    while index < len(command):
        flag = command[index]
        if flag in observed or flag not in switches | values:
            raise ValueError("unsupported or duplicate native eval flag: " + flag)
        if flag in switches:
            observed[flag] = True
            index += 1
        else:
            if index + 1 >= len(command) or command[index + 1].startswith("--"):
                raise ValueError("missing native eval flag value: " + flag)
            observed[flag] = command[index + 1]
            index += 2
    case = observed.get("--case")
    expected = build_command(mode, case)
    expected_flags = expected[4:expected.index("--output-dir")]
    expected_flags += expected[expected.index("--output-dir") + 2:]
    actual_flags = command[4:command.index("--output-dir")] if "--output-dir" in command else []
    if "--output-dir" in command:
        actual_flags += command[command.index("--output-dir") + 2:]
    if actual_flags != expected_flags or not observed.get("--output-dir"):
        raise ValueError("native eval command does not match the selected run mode")
    output = Path(observed["--output-dir"])
    if not output.is_absolute() or output.is_symlink() or output.resolve() != output:
        raise ValueError("native eval output requires an absolute path without symlink components")
    if not output.is_relative_to(PLUGIN.resolve()) or output == PLUGIN.resolve():
        raise ValueError("native eval output must remain inside the local package")


def frozen_package(root, destination, release_binding, promotion_evidence, mode, command):
    """Copy the exact verified inputs, then verify the private CLI package."""
    proof_binding, artifacts = promotion_evidence
    paths = set(release_binding["behavioral_identity"]["paths"])
    paths.update(artifacts)
    paths.add("standards/behavioral-inventory.v1.json")
    destination.mkdir()
    for relative in sorted(paths):
        source, target = root / relative, destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        target.chmod(0o444)
    if (current_release_binding(destination) != release_binding or
            promotion_evidence_for(mode, command, release_binding, destination,
                                   candidate_root=root)[0] != proof_binding):
        raise ValueError("frozen package does not match verified promotion")


def execute(command, mode):
    """Capture exact inputs and local output hashes, without claiming a pass."""
    validate_execution_command(command, mode)
    binding = current_release_binding(PLUGIN)
    promotion_evidence = promotion_evidence_for(mode, command, binding)
    promotion_binding = promotion_evidence[0] if promotion_evidence is not None else None
    output = Path(command[command.index("--output-dir") + 1])
    output.mkdir(parents=True, exist_ok=False)
    run_command = command.copy()
    run_root = PLUGIN
    if promotion_evidence is not None:
        run_root = output / "verified-package"
        frozen_package(PLUGIN, run_root, binding, promotion_evidence, mode, command)
        run_command[3] = str(run_root)
    preparation = {"schema_version": "agent-council.native-eval-preparation/v1",
                   "recorded_at": datetime.now(timezone.utc).isoformat(),
                   "mode": mode, "command": run_command, "release_binding": binding}
    if promotion_binding is not None:
        preparation["promotion_binding"] = promotion_binding
        preparation["source_command"] = command
    (output / "release-preparation.json").write_text(json.dumps(preparation, indent=2) + "\n")
    result = subprocess.run(run_command, cwd=run_root)
    try:
        unchanged = binding == current_release_binding(PLUGIN)
        if unchanged and promotion_binding is not None:
            unchanged = (promotion_binding == promotion_evidence_for(mode, command, binding)[0] and
                         binding == current_release_binding(run_root) and
                         promotion_binding == promotion_evidence_for(mode, command, binding, run_root,
                                                                      candidate_root=PLUGIN)[0])
    except (OSError, ValueError, KeyError, TypeError):
        unchanged = False
    hashes = {path.relative_to(output).as_posix(): digest_bytes(path.read_bytes())
              for path in sorted(output.rglob("*")) if path.is_file() and not path.is_symlink()}
    receipt = {**preparation, "schema_version": "agent-council.native-eval-run/v1",
               "completed_at": datetime.now(timezone.utc).isoformat(), "exit_code": result.returncode,
               "status": "release_changed" if not unchanged else "command_completed" if result.returncode == 0 else "command_failed",
               "qualification_claimed": False, "output_sha256": hashes,
               "interpretation": "Command provenance only. A cost ceiling stop or partial result does not qualify release behavior. Require all 16 cases, three runs per case, both ablation arms, model identity, and thresholds before accepting release behavior."}
    (output / "release-run.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return result.returncode if unchanged else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["validate", "iterate", "release", "probe",
                                         "release-campaign"])
    parser.add_argument("campaign_action", nargs="?", choices=["init", "step", "verify"])
    parser.add_argument("--campaign", type=Path)
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
        if args.mode == "release-campaign":
            if args.campaign_action is None or args.campaign is None or args.case or args.print_command:
                raise ValueError("release-campaign requires init|step|verify and --campaign PATH")
            if args.campaign_action == "init":
                campaign_init(args.campaign)
                print("Campaign initialized: 48 sealed slots")
                return 0
            if args.campaign_action == "step":
                slot = campaign_step(args.campaign.resolve())
                print("Campaign slot complete: " + slot["id"])
                return 0
            errors, spent = campaign_verify(args.campaign.resolve())
            if errors:
                for error in errors:
                    print(error, file=sys.stderr)
                return 1
            print(f"Campaign qualified: 48/48 slots; cost ${spent}")
            return 0
        command = build_command(args.mode, args.case)
        if args.print_command:
            promotion_evidence_for(args.mode, command, current_release_binding(PLUGIN))
            print(shlex.join(command))
            return 0
        # Native output locations are package-local and covered by evals/.gitignore.
        return execute(command, args.mode)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
