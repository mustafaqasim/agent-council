#!/usr/bin/env python3
"""Offline regression tests for native eval coverage and publication guards."""
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest
import tempfile
import json
import re
import runpy
import AgentCouncilPromotion as promotion
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("NativePluginEvals.py")
SPEC = importlib.util.spec_from_file_location("native_plugin_evals", SCRIPT)
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


class NativeEvalTests(unittest.TestCase):
    def setUp(self):
        self.suite = native.load_suite(native.EVAL_DIR)

    def test_packaged_suite_valid(self):
        self.assertEqual(native.validate_suite(self.suite), [])

    def test_critical_response_graders_reject_contradictions(self):
        # Execute the actual case regexes, not copies of their patterns. Tool
        # events remain native-only; these fixtures isolate response scoring.
        fixtures = {
            "lightweight-fallback": {
                "pass": [
                    "Select the active qualified same-tier fallback. No governed case is needed.",
                    "Use the same-tier fallback first. A governed case is not needed. Do not select a higher tier.",
                ],
                "fail": [
                    "Same-tier fallback is available. No governed case is needed. Select the higher-tier model.",
                    "Select the same-tier fallback. No governed case is needed. Instead, choose a higher tier.",
                    "Use the same-tier fallback, but select the higher-tier model. No governed case is needed.",
                    "Use the same-tier fallback. No governed case is needed. Council check: governed case R3.",
                ],
            },
            "required-tier-unavailable": {
                "pass": [
                    "Hold the dependent review gate: ultimate is unavailable. Unrelated authorized work may continue.",
                    "The gate remains blocked until ultimate review. Continue independent authorized work. Do not approve the gate.",
                ],
                "fail": [
                    "Ultimate is unavailable. The dependent gate is approved. Unrelated work may continue.",
                    "Hold the dependent gate; ultimate is unavailable. Unrelated work may continue. Approve the gate.",
                    "Hold the dependent gate for ultimate review. Unrelated work may continue. Use a lower tier.",
                    "Hold the dependent gate for ultimate review. Unrelated work may continue. All work must stop.",
                ],
            },
            "r3-shared-contract": {
                "pass": [
                    "Council check: governed case R3. Require ultimate design review, integration evidence across all consumers, and fault evidence.",
                    "Route: R3. Ultimate review, integration evidence, and fault evidence are mandatory. Do not use R1 or R2.",
                ],
                "fail": [
                    "R3 is unnecessary. Route: R1. Ultimate review, integration and fault evidence were considered.",
                    "Council check: governed case R3. Ultimate review, integration and fault evidence. Route: R2.",
                    "Council check: governed case R3. Ultimate review, integration and fault evidence. Council check: direct execution.",
                    "Council check: governed case R3. Ultimate review, integration and fault evidence. No integration evidence is required.",
                ],
            },
            "identity-mismatch": {
                "pass": [
                    "The required binding qualified-ultimate-A differs from receipt binding unqualified-B. Hold the gate under R3.",
                ],
                "fail": [
                    "The bindings mismatch. Hold the gate under R3.",
                    "The required binding qualified-ultimate-A is unverified. Hold the gate under R3.",
                    "The receipt binding unqualified-B is unverified. Hold the gate under R3.",
                    "The required binding qualified-ultimate-A differs from receipt binding unqualified-B. Hold the gate under R2.",
                ],
            },
        }
        cases = {case["name"]: case for case in self.suite["cases"]}
        for name, outcomes in fixtures.items():
            graders = [grader for grader in cases[name]["graders"] if grader["type"] == "regex"]
            for outcome, responses in outcomes.items():
                for response in responses:
                    with self.subTest(case=name, outcome=outcome, response=response):
                        passed = all(
                            bool(re.search(grader["pattern"], response, re.I if grader.get("flags") == "i" else 0))
                            == (grader["match"] == "contains") for grader in graders
                        )
                        self.assertEqual(passed, outcome == "pass")

    def test_lightweight_positive_has_substantial_independent_work(self):
        case = next(case for case in self.suite["cases"] if case["name"] == "lightweight-positive")
        prompt = case["execution"]["prompt"]
        self.assertEqual(len(re.findall(r"\(\d+\)", prompt)), 15)
        for cohort in ("Cohort Alpha", "Cohort Beta", "Cohort Gamma"):
            self.assertIn(cohort, prompt)
        for constraint in ("denominator", "calendar-versus-business-day", "staff effort", "causal claims"):
            self.assertIn(constraint, prompt)
        self.assertIn("Have a separate analyst audit", prompt)
        self.assertIn("Then synthesize that assessment", prompt)
        self.assertNotIn("Agent Council", prompt)
        self.assertEqual(case["runs"], 3)
        self.assertFalse(any(grader["name"] == "lightweight-route" for grader in case["graders"]))

    def test_invalid_response_grader_rejected(self):
        for field, value in (("pattern", "["), ("pattern", ""), ("match", "missing"), ("target", "unknown"), ("flags", "unsupported")):
            suite = copy.deepcopy(self.suite)
            grader = next(grader for case in suite["cases"] for grader in case["graders"] if grader["type"] == "regex")
            grader[field] = value
            with self.subTest(field=field, value=value):
                self.assertTrue(any("response regex" in error for error in native.validate_suite(suite)))

    def test_missing_coverage_rejected(self):
        suite = copy.deepcopy(self.suite)
        suite["cases"] = [case for case in suite["cases"] if "R3" not in case["tags"]]
        self.assertTrue(any("missing coverage: R3" in error for error in native.validate_suite(suite)))

    def test_paid_grader_rejected(self):
        suite = copy.deepcopy(self.suite)
        suite["cases"][0]["graders"].append({"type": "llm", "name": "claim", "criteria": "looks fine"})
        self.assertTrue(any("deterministic" in error for error in native.validate_suite(suite)))

    def test_ablation_cannot_hide_invocation_requirement(self):
        suite = copy.deepcopy(self.suite)
        grader = next(grader for case in suite["cases"] for grader in case["graders"] if grader.get("tool") == "Skill")
        grader.pop("arm")
        self.assertTrue(any("remain scored" in error for error in native.validate_suite(suite)))

    def test_invalid_nested_tool_matcher_rejected(self):
        suite = copy.deepcopy(self.suite)
        grader = next(grader for case in suite["cases"] for grader in case["graders"] if grader["type"] == "tool_order")
        grader["before"]["arm"] = "both"
        self.assertTrue(any("invalid tool matcher" in error for error in native.validate_suite(suite)))

    def test_tool_claim_without_observed_grader_rejected(self):
        suite = copy.deepcopy(self.suite)
        case = next(case for case in suite["cases"] if "lightweight-positive" in case["tags"])
        case["graders"] = [grader for grader in case["graders"] if grader["type"] != "tool_used"]
        self.assertTrue(any("observed delegation" in error for error in native.validate_suite(suite)))

    def test_lightweight_positive_requires_plugin_agent(self):
        suite = copy.deepcopy(self.suite)
        case = next(case for case in suite["cases"] if "lightweight-positive" in case["tags"])
        case["graders"] = [grader for grader in case["graders"] if grader.get("name") != "qualified-plugin-agent"]
        self.assertTrue(any("qualified plugin agent" in error for error in native.validate_suite(suite)))

    def test_publication_enabled_rejected(self):
        suite = copy.deepcopy(self.suite)
        suite["cases"][0]["execution"]["artifact_publish"] = True
        self.assertTrue(any("artifact_publish" in error for error in native.validate_suite(suite)))

    def test_iteration_command(self):
        command = native.build_command("iterate", case="trivial-negative")
        for flag, value in [("--runs", "1"), ("--ablation", "none"), ("--case", "trivial-negative")]:
            self.assertEqual(command[command.index(flag) + 1], value)
        self.assertIn("--no-publish", command)
        self.assertNotIn("--publish-report", command)
        output = Path(command[command.index("--output-dir") + 1])
        self.assertTrue(output.is_relative_to(native.EVAL_DIR / "results"))

    def test_iteration_requires_exact_case(self):
        for case in [None, "*", "missing-case"]:
            with self.assertRaises(ValueError):
                native.build_command("iterate", case=case)

    def test_release_command(self):
        command = native.build_command("release")
        for flag, value in [("--runs", "3"), ("--ablation", "with-without"), ("--threshold", "1.0"), ("--max-cost-usd", "20"), ("--model", "claude-opus-5-5")]:
            self.assertEqual(command[command.index(flag) + 1], value)
        self.assertIn("--no-publish", command)
        self.assertNotIn("--case", command)

    def campaign_fixture(self, root):
        slots = native.campaign_slots([case["name"] for case in self.suite["cases"]])
        manifest = {"schema_version": native.CAMPAIGN_SCHEMA, "model": native.CAMPAIGN_MODEL,
                    "cost_cap_usd": "20", "cli_version": "Claude Code 2.1.281", "slots": slots,
                    "created_at": "2026-09-30T23:59:59+00:00"}
        (root / "verified-package").mkdir()
        for slot in slots:
            index = slots.index(slot)
            base = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
            stamp = lambda seconds: (base + timedelta(seconds=seconds)).isoformat()
            path = root / "slots" / slot["id"]
            path.mkdir(parents=True)
            result = path / "result"
            result.mkdir()
            grader_names = [grader["name"] for case in self.suite["cases"]
                            if case["name"] == slot["case"] for grader in case["graders"]]
            aggregate = {"schemaVersion": 1, "partial": False, "partialReason": None,
                         "claudeVersion": "2.1.281", "costUsd": 0.1, "startedAt": stamp(1),
                         "suite": {"root": str(root / "verified-package"),
                                   "ablation": "with-without", "modelOverride": native.CAMPAIGN_MODEL,
                                   "threshold": 1, "concurrency": 1},
                         "cases": [{"name": slot["case"], "dir": "evals/" + slot["case"],
                                    "source": "case_yaml", "runsPerCase": 1,
                                    "graders": [{"name": name} for name in grader_names], "arms": {
                                        "with": [{"score": 1, "passed": True, "costUsd": 0.05, "error": None,
                                                  "skippedPaidGraders": False,
                                                  "graders": [{"name": name, "scored": True, "passed": True}
                                                              for name in grader_names]}],
                                        "without": [{"score": 0, "passed": False, "costUsd": 0.05, "error": None,
                                                     "skippedPaidGraders": False,
                                                     "graders": [{"name": name, "scored": True, "passed": False}
                                                                 for name in grader_names]}]}}]}
            (result / "traces").mkdir()
            for arm_index, arm_name in enumerate(("with", "without")):
                session = str(native.uuid.UUID(int=index * 2 + arm_index + 1))
                aggregate["cases"][0]["arms"][arm_name][0].update(
                    startedAt=stamp(2 + arm_index * 10), tracePath=f"/private/tmp/e-{session}/out/trace.jsonl")
                events = [
                    {"type": "system", "subtype": "init", "model": native.CAMPAIGN_MODEL, "session_id": session},
                    {"type": "assistant", "parent_tool_use_id": None, "session_id": session,
                     "timestamp": stamp(3 + arm_index * 10), "request_id": "req_" + session,
                     "message": {"model": native.CAMPAIGN_MODEL, "id": "msg_" + session}},
                    {"type": "result", "subtype": "success", "is_error": False, "session_id": session,
                     "total_cost_usd": 0.05, "modelUsage": {native.CAMPAIGN_MODEL: {"costUSD": 0.05}}},
                ]
                (result / "traces" / (arm_name + ".jsonl")).write_text(
                    "\n".join(json.dumps(event) for event in events) + "\n")
            raw = json.dumps(aggregate).encode()
            (result / "aggregate-result.json").write_bytes(raw)
            prior = slots.index(slot)
            command = native.campaign_command(root / "verified-package", result, slot["case"],
                                              native.CAMPAIGN_CAP - sum((native.Decimal("0.1")
                                                                       for _ in range(prior)), native.Decimal(0)))
            preparation = {"slot": slot, "manifest_sha256": native.canonical_hash(manifest),
                           "command": command, "recorded_at": stamp(0)}
            preparation_raw = json.dumps(preparation).encode()
            (path / "preparation.json").write_bytes(preparation_raw)
            receipt = {"slot": slot, "manifest_sha256": native.canonical_hash(manifest),
                       "command": command, "preparation_sha256": native.digest_bytes(preparation_raw),
                       "aggregate_sha256": native.digest_bytes(raw),
                       "output_sha256": native.output_hashes(result),
                       "cost_usd": "0.1", "exit_code": 0, "completed_at": stamp(30)}
            (path / "receipt.json").write_text(json.dumps(receipt))
        return manifest

    def reseal_campaign_slot(self, path):
        receipt = json.loads((path / "receipt.json").read_text())
        receipt.update(aggregate_sha256=native.digest_bytes((path / "result/aggregate-result.json").read_bytes()),
                       output_sha256=native.output_hashes(path / "result"),
                       preparation_sha256=native.digest_bytes((path / "preparation.json").read_bytes()))
        (path / "receipt.json").write_text(json.dumps(receipt))

    def test_campaign_rejects_replayed_native_output_even_when_resealed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.campaign_fixture(root)
            original = root / "slots" / manifest["slots"][0]["id"]
            replay = root / "slots" / manifest["slots"][16]["id"]
            for relative in ("aggregate-result.json", "traces/with.jsonl", "traces/without.jsonl"):
                (replay / "result" / relative).write_bytes((original / "result" / relative).read_bytes())
            self.reseal_campaign_slot(replay)
            errors = native.campaign_receipts(root, manifest)[1]
            self.assertTrue(any("precedes preparation" in error for error in errors), errors)

    def test_campaign_rejects_duplicate_session_despite_fresh_timestamps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.campaign_fixture(root)
            first = root / "slots" / manifest["slots"][0]["id"]
            second = root / "slots" / manifest["slots"][1]["id"]
            session = json.loads((first / "result/traces/with.jsonl").read_text().splitlines()[0])["session_id"]
            trace = second / "result/traces/with.jsonl"
            events = [json.loads(line) for line in trace.read_text().splitlines()]
            for event in events:
                event["session_id"] = session
            trace.write_text("\n".join(json.dumps(event) for event in events))
            self.reseal_campaign_slot(second)
            errors = native.campaign_receipts(root, manifest)[1]
            self.assertTrue(any("replay detected" in error for error in errors), errors)

    def test_campaign_rejects_rewritten_session_and_time_on_replayed_provider_response(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.campaign_fixture(root)
            first = root / "slots" / manifest["slots"][0]["id"]
            second = root / "slots" / manifest["slots"][16]["id"]
            for arm in ("with", "without"):
                trace = second / "result/traces" / (arm + ".jsonl")
                fresh = [json.loads(line) for line in trace.read_text().splitlines()]
                reused = [json.loads(line) for line in
                          (first / "result/traces" / (arm + ".jsonl")).read_text().splitlines()]
                for event, replacement in zip(reused, fresh):
                    event["session_id"] = replacement["session_id"]
                    if "timestamp" in event:
                        event["timestamp"] = replacement["timestamp"]
                trace.write_text("\n".join(json.dumps(event) for event in reused))
            self.reseal_campaign_slot(second)
            errors = native.campaign_receipts(root, manifest)[1]
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("provider response replay detected across slots", errors[0])

    def test_campaign_provider_ids_repeat_only_inside_the_same_arm(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.campaign_fixture(root)
            path = root / "slots" / manifest["slots"][0]["id"]
            trace = path / "result/traces/with.jsonl"
            rows = [json.loads(line) for line in trace.read_text().splitlines()]
            rows.insert(2, copy.deepcopy(rows[1]))
            trace.write_text("\n".join(json.dumps(row) for row in rows))
            self.reseal_campaign_slot(path)
            self.assertEqual(native.campaign_receipts(root, manifest)[1], [])
            other = path / "result/traces/without.jsonl"
            other_rows = [json.loads(line) for line in other.read_text().splitlines()]
            other_rows[1]["message"]["id"] = rows[1]["message"]["id"]
            other.write_text("\n".join(json.dumps(row) for row in other_rows))
            self.reseal_campaign_slot(path)
            errors = native.campaign_receipts(root, manifest)[1]
            self.assertTrue(any("provider response replay detected across arms" in error for error in errors), errors)

    def test_campaign_rejects_preparation_before_campaign_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.campaign_fixture(root)
            path = root / "slots" / manifest["slots"][0]["id"]
            prep = path / "preparation.json"
            value = json.loads(prep.read_text())
            value["recorded_at"] = "2026-09-30T23:59:58+00:00"
            prep.write_text(json.dumps(value))
            self.reseal_campaign_slot(path)
            errors = native.campaign_receipts(root, manifest)[1]
            self.assertTrue(any("preparation precedes campaign creation" in error for error in errors), errors)

    def test_campaign_rejects_missing_or_wrong_native_model_evidence(self):
        mutations = {
            "alias": lambda rows: rows[0].update(model="opus"),
            "wrong_response_model": lambda rows: rows[1]["message"].update(model="claude-sonnet-4-6"),
            "synthetic": lambda rows: rows[1]["message"].update(model="<synthetic>"),
            "terminal_error": lambda rows: rows[-1].update(is_error=True),
            "missing_usage": lambda rows: rows[-1].update(modelUsage={}),
            "trace_cost": lambda rows: rows[-1].update(total_cost_usd=0.06),
            "session_mismatch": lambda rows: rows[-1].update(session_id=str(native.uuid.uuid4())),
            "stale_response": lambda rows: rows[1].update(timestamp="2025-01-01T00:00:00+00:00"),
            "no_assistant": lambda rows: rows.pop(1),
            "missing_terminal": lambda rows: rows.pop(),
            "missing_provider_message_id": lambda rows: rows[1]["message"].pop("id"),
            "empty_provider_message_id": lambda rows: rows[1]["message"].update(id=" "),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifest = self.campaign_fixture(root)
                path = root / "slots" / manifest["slots"][0]["id"]
                trace = path / "result/traces/with.jsonl"
                rows = [json.loads(line) for line in trace.read_text().splitlines()]
                mutate(rows)
                trace.write_text("\n".join(json.dumps(row) for row in rows))
                self.reseal_campaign_slot(path)
                self.assertTrue(native.campaign_receipts(root, manifest)[1])

    def test_campaign_rejects_unretained_trace_and_aggregate_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.campaign_fixture(root)
            path = root / "slots" / manifest["slots"][0]["id"]
            (path / "result/traces/with.jsonl").unlink()
            self.reseal_campaign_slot(path)
            self.assertTrue(native.campaign_receipts(root, manifest)[1])
            aggregate = json.loads((path / "result/aggregate-result.json").read_text())
            aggregate["suite"]["modelOverride"] = "opus"
            self.assertIn("native suite parameters changed", native.check_slot(aggregate, manifest["slots"][0], manifest))

    def test_preserve_native_trace_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / "result"
            output.mkdir()
            arms = {}
            for arm in ("with", "without"):
                source = root / (arm + ".jsonl")
                source.write_bytes(b'{"original": true}\r\n')
                arms[arm] = [{"tracePath": str(source)}]
            native.preserve_traces({"cases": [{"arms": arms}]}, output)
            for arm in arms:
                self.assertEqual((output / "traces" / (arm + ".jsonl")).read_bytes(), b'{"original": true}\r\n')

    def test_campaign_seals_and_stops_immediately_on_native_cost_overrun(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = {"slots": native.campaign_slots([case["name"] for case in self.suite["cases"]])}
            result_dir = root / "slots" / manifest["slots"][0]["id"] / "result"

            def paid_result(command, **_kwargs):
                self.assertIn("--keep-temp", command)
                self.assertEqual(command[command.index("--max-cost-usd") + 1], "20")
                result_dir.mkdir()
                (result_dir / "aggregate-result.json").write_text(json.dumps({"costUsd": 20.01}))
                return native.subprocess.CompletedProcess(command, 0)

            with patch.object(native, "read_campaign", return_value=manifest), \
                 patch.object(native, "campaign_receipts", return_value=([], [])), \
                 patch.object(native, "preserve_traces"), \
                 patch.object(native.subprocess, "run", side_effect=paid_result) as launch, \
                 patch("builtins.print"):
                with self.assertRaisesRegex(ValueError, "acceptance cap exceeded.*20.01"):
                    native.campaign_step(root)
                launch.assert_called_once()
            receipt = json.loads((result_dir.parent / "receipt.json").read_text())
            self.assertEqual(receipt["cost_usd"], "20.01")
            self.assertTrue((result_dir.parent / "preparation.json").is_file())

    def test_campaign_never_launches_after_invalid_or_overbudget_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = {"slots": native.campaign_slots([case["name"] for case in self.suite["cases"]])}
            with patch.object(native, "read_campaign", return_value=manifest), \
                 patch.object(native, "campaign_receipts", return_value=([], ["global $20 cost cap exceeded"])), \
                 patch.object(native.subprocess, "run") as launch:
                with self.assertRaisesRegex(ValueError, "campaign stopped"):
                    native.campaign_step(Path(temporary))
                launch.assert_not_called()

    def test_campaign_complete_and_missing_slot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.campaign_fixture(root)
            receipts, errors = native.campaign_receipts(root, manifest)
            self.assertEqual((len(receipts), errors), (48, []))
            missing = root / "slots" / manifest["slots"][0]["id"]
            (missing / "receipt.json").unlink()
            self.assertTrue(any("no seal" in error for error in native.campaign_receipts(root, manifest)[1]))

    def test_campaign_init_creates_absent_results_parent_only_for_exact_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            eval_dir = root / "evals"
            eval_dir.mkdir()
            campaign = eval_dir / "results" / "campaign-001"
            self.assertFalse(campaign.parent.exists())
            with patch.object(native, "EVAL_DIR", eval_dir), \
                 patch.object(native, "load_suite", return_value=self.suite), \
                 patch.object(native, "current_release_binding", return_value={"binding": "verified"}), \
                 patch.object(native, "promotion_evidence_for", return_value=({"proof": "verified"}, [])), \
                 patch.object(native, "cli_version", return_value="Claude Code 2.1.281"), \
                 patch.object(native, "frozen_package", side_effect=lambda _root, dest, *_args: dest.mkdir()):
                manifest = native.campaign_init(campaign)
                self.assertEqual(len(manifest["slots"]), 48)
                self.assertTrue((campaign / "campaign.json").is_file())
                with self.assertRaisesRegex(ValueError, "direct child"):
                    native.campaign_init(eval_dir / "results" / "nested" / "campaign-002")
                self.assertFalse((eval_dir / "results" / "nested").exists())

    def test_campaign_rejects_duplicate_tamper_and_native_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.campaign_fixture(root)
            first = root / "slots" / manifest["slots"][0]["id"]
            (root / "slots" / "extra-duplicate").mkdir()
            self.assertTrue(any("unexpected" in error for error in native.campaign_receipts(root, manifest)[1]))
            (root / "slots" / "extra-duplicate").rmdir()
            aggregate = first / "result/aggregate-result.json"
            original = aggregate.read_bytes()
            aggregate.write_bytes(original + b" ")
            self.assertTrue(any("seal mismatch" in error for error in native.campaign_receipts(root, manifest)[1]))
            aggregate.write_bytes(original)
            data = json.loads(original)
            for mutation in (lambda a: a.update(partial=True),
                             lambda a: a["cases"][0]["arms"]["with"][0].update(error="quota"),
                             lambda a: a["cases"][0]["arms"]["with"][0].update(score=0.5),
                             lambda a: a["cases"][0]["arms"]["without"][0].update(skippedPaidGraders=True),
                             lambda a: a["cases"][0]["arms"].pop("without")):
                candidate = copy.deepcopy(data)
                mutation(candidate)
                with self.subTest(candidate=candidate):
                    self.assertTrue(native.check_slot(candidate, manifest["slots"][0], manifest))

    def promotion_fixture(self, root, **kwargs):
        registry = json.loads((native.PLUGIN / promotion.REGISTRY_PATH).read_text())
        for binding in registry["bindings"]:
            binding["status"] = "candidate"
            binding.pop("qualified_roles", None)
            binding["binding_sha256"] = promotion.sha256(promotion.canonical({key: value for key, value in binding.items() if key != "binding_sha256"}))
        for state in registry["provider_states"].values():
            state["council_status"] = "fail_closed_until_qualified"
        registry["registry_sha256"] = promotion.sha256(promotion.canonical({key: value for key, value in registry.items() if key != "registry_sha256"}))
        fixture = runpy.run_path(str(SCRIPT.with_name("Test-AgentCouncilPromotion.py")))["fixture"]
        return fixture(root, registry_value=registry, **kwargs)

    def promoted_package(self, root):
        files, _ = self.promotion_fixture(root)
        for relative, raw in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        return files

    def test_v3_release_receipt_binds_verified_promotion(self):
        with tempfile.TemporaryDirectory(dir=native.PLUGIN) as temporary:
            root = Path(temporary)
            files = self.promoted_package(root)
            command = native.build_command("release")
            command[3] = str(root)
            command[command.index("--output-dir") + 1] = str(root / "output")
            with patch.object(native, "PLUGIN", root), patch.object(native.subprocess, "run") as run:
                run.return_value.returncode = 0
                self.assertEqual(native.execute(command, "release"), 0)
            receipt = json.loads((root / "output/release-run.json").read_text())
            self.assertEqual(receipt["promotion_binding"]["promotion_proof_sha256"], native.digest_bytes(files["standards/model-qualifications/promotion.v1.json"]))
            self.assertEqual(receipt["promotion_binding"]["promoted_behavioral_sha256"], receipt["release_binding"]["behavioral_identity"]["behavioral_sha256"])

    def test_v3_public_targeted_gate_and_frozen_package_need_no_private_evidence(self):
        import AgentCouncilPromotion as promotion
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "public"
            files, proof = self.promotion_fixture(root, binding_ids=["claude-code-v3-worker"])
            closure = promotion.export_public_promotion_bytes(files,
                expected_package_sha256=proof["promoted_release_binding"]["behavioral_identity"]["behavioral_sha256"],
                expected_proof_sha256=promotion.sha256(files[promotion.PROOF_PATH]), candidate_root=root)
            public = {name: files[name] for name in proof["promoted_release_binding"]["behavioral_identity"]["paths"]}
            public[promotion.INVENTORY_PATH] = files[promotion.INVENTORY_PATH]
            public.update(closure)
            for name, raw in public.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            binding = native.current_release_binding(root)
            command = native.build_command("iterate", "lightweight-positive")
            evidence = native.promotion_evidence_for("iterate", command, binding, root)
            self.assertEqual(set(evidence[1]), set(closure))
            frozen = root.parent / "frozen"
            native.frozen_package(root, frozen, binding, evidence, "iterate", command)
            self.assertEqual({path.relative_to(frozen).as_posix() for path in frozen.rglob("*") if path.is_file()}, set(public))

    def test_full_release_refuses_partial_promotion(self):
        with tempfile.TemporaryDirectory(dir=native.PLUGIN) as temporary:
            root = Path(temporary)
            files, _ = self.promotion_fixture(root, binding_ids=["claude-code-v3-worker"])
            for relative, raw in files.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            command = native.build_command("release")
            command[3] = str(root)
            command[command.index("--output-dir") + 1] = str(root / "output")
            with patch.object(native, "PLUGIN", root), patch.object(native.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "all default v3 bindings"):
                    native.execute(command, "release")
                run.assert_not_called()

    def test_role_package_refuses_historical_gft_proof(self):
        import AgentCouncilPromotion as promotion
        binding = {"behavioral_identity": {"paths": ["standards/qualification-protocol.v1.yaml"]}}
        verified = {"binding_ids": list(promotion.BINDINGS), "qualification_protocol_version": None}
        with patch.object(promotion, "verify_promotion", return_value=verified):
            for mode, case in (("release", None), ("iterate", "lightweight-positive")):
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "requires role qualification proof"):
                    native.promotion_evidence_for(mode, native.build_command(mode, case), binding)

    def test_v3_release_and_lightweight_refuse_forged_qualified_registry(self):
        with tempfile.TemporaryDirectory(dir=native.PLUGIN) as temporary:
            root = Path(temporary)
            self.promoted_package(root)
            (root / "standards/model-qualifications/promotion.v1.json").unlink()
            with patch.object(native, "PLUGIN", root), patch.object(native.subprocess, "run") as run:
                for mode, case in (("release", None), ("iterate", "lightweight-positive")):
                    command = native.build_command(mode, case)
                    command[3] = str(root)
                    command[command.index("--output-dir") + 1] = str(root / ("output-" + mode))
                    with self.subTest(mode=mode), self.assertRaises(ValueError):
                        native.execute(command, mode)
                run.assert_not_called()

    def test_v3_release_refuses_stale_proof_after_package_change(self):
        with tempfile.TemporaryDirectory(dir=native.PLUGIN) as temporary:
            root = Path(temporary)
            self.promoted_package(root)
            (root / "scripts/behavior.py").write_text("behavior = 'changed'\n")
            command = native.build_command("release")
            command[3] = str(root)
            command[command.index("--output-dir") + 1] = str(root / "output")
            with patch.object(native, "PLUGIN", root), patch.object(native.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    native.execute(command, "release")
                run.assert_not_called()

    def test_candidate_probe_and_structural_iteration_remain_available(self):
        with tempfile.TemporaryDirectory(dir=native.PLUGIN) as temporary:
            root = Path(temporary)
            files = self.promoted_package(root)
            (root / "standards/agent-model-registry.v3.yaml").write_bytes(files["standards/model-qualifications/candidate-registry.v3.json"])
            (root / "standards/model-qualifications/promotion.v1.json").unlink()
            with patch.object(native, "PLUGIN", root), patch.object(native.subprocess, "run") as run:
                run.return_value.returncode = 0
                for mode, case in (("probe", None), ("iterate", "trivial-negative")):
                    command = native.build_command(mode, case)
                    command[3] = str(root)
                    command[command.index("--output-dir") + 1] = str(root / ("output-" + mode))
                    with self.subTest(mode=mode):
                        self.assertEqual(native.execute(command, mode), 0)
                self.assertEqual(run.call_count, 2)

    def test_v3_release_detects_proof_change_during_run(self):
        with tempfile.TemporaryDirectory(dir=native.PLUGIN) as temporary:
            root = Path(temporary)
            self.promoted_package(root)
            command = native.build_command("release")
            command[3] = str(root)
            command[command.index("--output-dir") + 1] = str(root / "output")
            def change_proof(*args, **kwargs):
                (root / "standards/model-qualifications/promotion.v1.json").write_text("{}\n")
                return type("Result", (), {"returncode": 0})()
            with patch.object(native, "PLUGIN", root), patch.object(native.subprocess, "run", side_effect=change_proof):
                self.assertEqual(native.execute(command, "release"), 1)
            receipt = json.loads((root / "output/release-run.json").read_text())
            self.assertEqual(receipt["status"], "release_changed")

    def test_v3_release_runs_verified_bytes_when_source_changes_and_recovers(self):
        with tempfile.TemporaryDirectory(dir=native.PLUGIN) as temporary:
            root = Path(temporary)
            self.promoted_package(root)
            source = root / "scripts/behavior.py"
            original = source.read_bytes()
            command = native.build_command("release")
            command[3] = str(root)
            command[command.index("--output-dir") + 1] = str(root / "output")
            observed = {}
            def change_and_restore(actual, **kwargs):
                source.write_text("behavior = 'malicious during eval'\n")
                try:
                    observed["cli_bytes"] = (Path(actual[3]) / "scripts/behavior.py").read_bytes()
                finally:
                    source.write_bytes(original)
                return type("Result", (), {"returncode": 0})()
            with patch.object(native, "PLUGIN", root), patch.object(native.subprocess, "run", side_effect=change_and_restore):
                self.assertEqual(native.execute(command, "release"), 0)
            self.assertEqual(observed["cli_bytes"], original)

    def test_v2_release_keeps_historical_gate(self):
        with tempfile.TemporaryDirectory(dir=native.PLUGIN) as temporary:
            root = Path(temporary)
            registry = root / "standards/agent-model-registry.v2.yaml"
            registry.parent.mkdir(parents=True)
            registry.write_bytes((native.PLUGIN / "standards/agent-model-registry.v2.yaml").read_bytes())
            eval_case = root / "evals/fixture.yaml"
            eval_case.parent.mkdir(parents=True)
            eval_case.write_text("synthetic: true\n")
            (root / "standards/behavioral-inventory.v1.json").write_text(json.dumps({
                "schema_version": "agent-council.behavioral-inventory/v1",
                "identity_version": "v2/historical",
                "paths": ["evals/fixture.yaml", "standards/agent-model-registry.v2.yaml"]}))
            command = native.build_command("release")
            command[3] = str(root)
            command[command.index("--output-dir") + 1] = str(root / "output")
            with patch.object(native, "PLUGIN", root), patch.object(native.subprocess, "run") as run:
                run.return_value.returncode = 0
                self.assertEqual(native.execute(command, "release"), 0)
            receipt = json.loads((root / "output/release-run.json").read_text())
            self.assertNotIn("promotion_binding", receipt)

    def test_native_run_receipt_binds_release_and_command(self):
        with tempfile.TemporaryDirectory(dir=native.PLUGIN) as temporary:
            root = Path(temporary)
            self.promoted_package(root)
            command = native.build_command("release")
            command[3] = str(root)
            command[command.index("--output-dir") + 1] = str(root / "output")
            with patch.object(native, "PLUGIN", root), patch.object(native.subprocess, "run") as run:
                run.return_value.returncode = 0
                self.assertEqual(native.execute(command, "release"), 0)
            receipt = json.loads((root / "output/release-run.json").read_text())
            self.assertEqual(receipt["release_binding"], native.current_release_binding(root))
            self.assertEqual(receipt["source_command"], command)
            self.assertEqual(receipt["command"][3], str(root / "output/verified-package"))
            self.assertEqual(run.call_args.args[0], receipt["command"])
            self.assertEqual(run.call_args.kwargs["cwd"], root / "output/verified-package")
            self.assertEqual(receipt["status"], "command_completed")
            self.assertFalse(receipt["qualification_claimed"])

    def test_cost_ceiling_partial_result_cannot_claim_qualification(self):
        with tempfile.TemporaryDirectory(dir=native.PLUGIN) as temporary:
            root = Path(temporary)
            self.promoted_package(root)
            command = native.build_command("release")
            command[3] = str(root)
            command[command.index("--output-dir") + 1] = str(root / "output")
            def partial_result(*args, **kwargs):
                (root / "output/partial.json").write_text(json.dumps({"stop_reason": "max_cost_usd", "cases_completed": 1}))
                return type("Result", (), {"returncode": 0})()
            with patch.object(native, "PLUGIN", root), patch.object(native.subprocess, "run", side_effect=partial_result):
                self.assertEqual(native.execute(command, "release"), 0)
            receipt = json.loads((root / "output/release-run.json").read_text())
            self.assertFalse(receipt["qualification_claimed"])
            self.assertIn("partial result does not qualify", receipt["interpretation"])

    def test_native_run_refuses_publication_before_execution(self):
        command = native.build_command("release")
        command.remove("--no-publish")
        with patch.object(native.subprocess, "run") as run, self.assertRaises(ValueError):
            native.execute(command, "release")
        run.assert_not_called()

    def test_native_run_rejects_mode_contract_tampering_before_execution(self):
        mutations = [
            ("release", "--runs", "1"), ("release", "--ablation", "none"),
            ("release", "--threshold", "0.5"), ("release", "--max-cost-usd", "100"),
            ("probe", "--max-cost-usd", "20"), ("release", "--model", "sonnet"),
        ]
        for mode, flag, value in mutations:
            command = native.build_command(mode)
            command[command.index(flag) + 1] = value
            with self.subTest(mode=mode, flag=flag), patch.object(native.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    native.execute(command, mode)
                run.assert_not_called()
        for extra in (["--case", "trivial-negative"], ["--runs", "1"],
                      ["--publish-report"], ["--no-publish=false"], ["--unknown"]):
            command = native.build_command("release") + extra
            with self.subTest(extra=extra), patch.object(native.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    native.execute(command, "release")
                run.assert_not_called()

    def test_native_run_rejects_external_or_symlink_output(self):
        with tempfile.TemporaryDirectory(dir=native.PLUGIN) as temporary:
            root = Path(temporary)
            (root / "linked").symlink_to(root, target_is_directory=True)
            for output in (str(root.parent / "outside"), "relative-output", str(root / "linked/run")):
                command = native.build_command("probe")
                command[3] = str(root)
                command[command.index("--output-dir") + 1] = output
                with self.subTest(output=output), patch.object(native, "PLUGIN", root), patch.object(native.subprocess, "run") as run:
                    with self.assertRaises(ValueError):
                        native.execute(command, "probe")
                    run.assert_not_called()

    def test_native_run_refuses_changed_release(self):
        with tempfile.TemporaryDirectory(dir=native.PLUGIN) as temporary:
            root = Path(temporary)
            self.promoted_package(root)
            command = native.build_command("release")
            command[3] = str(root)
            command[command.index("--output-dir") + 1] = str(root / "output")
            def change_package(*args, **kwargs):
                (root / "scripts/behavior.py").write_text("behavior = 'changed'\n")
                return type("Result", (), {"returncode": 0})()
            with patch.object(native, "PLUGIN", root), patch.object(native.subprocess, "run", side_effect=change_package):
                self.assertEqual(native.execute(command, "release"), 1)
            receipt = json.loads((root / "output/release-run.json").read_text())
            self.assertEqual(receipt["status"], "release_changed")

    def test_probe_never_launches_paid_run(self):
        command = native.build_command("probe")
        self.assertEqual(command[command.index("--max-cost-usd") + 1], "0")
        self.assertIn("--no-publish", command)

    def test_unavailable_cli_is_not_success(self):
        with patch.object(native.shutil, "which", return_value=None):
            self.assertIn("unavailable", native.check_native_cli()[0])

    def test_wrong_cli_is_not_success(self):
        with patch.object(native.shutil, "which", return_value="claude"), patch.object(native.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "Usage: claude plugin"
            run.return_value.stderr = ""
            self.assertTrue(native.check_native_cli())

    def test_tracked_results_rejected(self):
        for path in ["plugins/agent-council/evals/results/run/report.html", "plugins/agent-council/evals/local/run.json", "plugins/agent-council/evals/response.json"]:
            self.assertTrue(native.validate_tracked_files([path]))

    def test_local_output_is_gitignored(self):
        self.assertEqual(native.check_output_ignores(), [])

    def test_unsafe_documented_command_rejected(self):
        self.assertTrue(native.validate_command_text("claude plugin eval ./plugin --runs 1"))
        self.assertTrue(native.validate_command_text("claude plugin eval ./plugin --no-publish --publish-report"))
        self.assertEqual(native.validate_command_text("claude plugin eval ./plugin --no-publish --runs 1"), [])

    def test_coexistence_has_real_fixture_and_two_observed_invocations(self):
        case = next(case for case in self.suite["cases"] if "domain-skill-coexistence" in case["tags"])
        self.assertEqual(len(case["plugins"]), 2)
        used = [grader for grader in case["graders"] if grader["type"] == "tool_used" and grader["tool"] == "Skill" and grader.get("min", 1) >= 1]
        self.assertTrue(any("fixture-domain" in grader.get("input_match", "") for grader in used))
        self.assertTrue(any("agent-council" in grader.get("input_match", "") for grader in used))


if __name__ == "__main__":
    unittest.main()
