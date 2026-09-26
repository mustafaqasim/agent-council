#!/usr/bin/env python3
"""Offline regression tests for native eval coverage and publication guards."""
import copy
import importlib.util
from pathlib import Path
import unittest
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
        for flag, value in [("--runs", "3"), ("--ablation", "with-without"), ("--threshold", "1.0")]:
            self.assertEqual(command[command.index(flag) + 1], value)
        self.assertIn("--no-publish", command)
        self.assertNotIn("--case", command)

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
