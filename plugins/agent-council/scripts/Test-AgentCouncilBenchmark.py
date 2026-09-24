#!/usr/bin/env python3
"""Hermetic contract tests for the local paired benchmark reporter."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).with_name("Invoke-AgentCouncilBenchmark.py")
FIXTURE = ROOT / "skills" / "agent-council" / "references" / "benchmark-fixtures.json"
SPEC = importlib.util.spec_from_file_location("benchmark_runner", RUNNER)
BENCHMARK = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(BENCHMARK)


class BenchmarkReporterTests(unittest.TestCase):
    def fixture_document(self):
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_synthetic_fixture_proves_pair_deltas_without_claiming_performance(self):
        report = BENCHMARK.build_report(self.fixture_document())
        self.assertEqual(report["performance_claim"], "none")
        self.assertEqual(report["complete_comparable_pair_count"], 2)
        self.assertEqual(report["excluded_or_incomplete_pairs"], [{"pair_id": "synthetic-incomplete", "reason": "expected exactly two records"}])
        first = report["complete_comparable_pairs"][0]
        self.assertEqual(first["pair_id"], "synthetic-a")
        self.assertEqual(first["deltas"], {"elapsed_ms": -300, "retries": -1})
        self.assertEqual(first["usage_deltas"]["orchestrator.input_tokens"], 100)
        self.assertEqual(first["usage_deltas"]["worker.output_tokens"], 200)
        self.assertEqual(report["order_metadata"], {"direct_first_pairs": 1, "council_first_pairs": 1, "balanced_within_one_pair": True})
        self.assertEqual(report["quality_failures"], [{"pair_id": "synthetic-b", "condition": "direct", "verdict": "quality", "record_id": "synthetic-b-direct"}])

    def test_unknown_values_never_create_a_delta(self):
        document = {
            "runs": [
                {"pair_id": "p", "fixture_id": "f", "scope_id": "s", "rubric_id": "r", "condition": "direct", "order": "direct_first"},
                {"pair_id": "p", "fixture_id": "f", "scope_id": "s", "rubric_id": "r", "condition": "council", "order": "direct_first", "elapsed_ms": 10},
            ]
        }
        pair = BENCHMARK.build_report(document)["complete_comparable_pairs"][0]
        self.assertEqual(pair["deltas"], {})
        self.assertIn("elapsed_ms", pair["unknown_metrics"])
        self.assertEqual(pair["runs"]["direct"]["observed"], {"model": "unknown", "effort": "unknown"})

    def test_mismatched_identifiers_and_duplicate_conditions_are_excluded(self):
        document = {
            "runs": [
                {"pair_id": "mismatch", "fixture_id": "f1", "scope_id": "s", "rubric_id": "r", "condition": "direct", "order": "direct_first", "verdict": {"correctness": "fail", "quality": "pass"}},
                {"pair_id": "mismatch", "fixture_id": "f2", "scope_id": "s", "rubric_id": "r", "condition": "council", "order": "direct_first"},
                {"pair_id": "duplicate", "fixture_id": "f", "scope_id": "s", "rubric_id": "r", "condition": "direct", "order": "direct_first"},
                {"pair_id": "duplicate", "fixture_id": "f", "scope_id": "s", "rubric_id": "r", "condition": "direct", "order": "direct_first"},
            ]
        }
        excluded = BENCHMARK.build_report(document)["excluded_or_incomplete_pairs"]
        self.assertEqual(excluded, [
            {"pair_id": "duplicate", "reason": "expected one direct and one council record"},
            {"pair_id": "mismatch", "reason": "mismatched fixture_id"},
        ])
        self.assertEqual(BENCHMARK.build_report(document)["quality_failures"], [])

    def test_loader_rejects_duplicate_json_keys_and_oversized_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            duplicate = Path(temporary) / "duplicate.json"
            duplicate.write_text('{"runs": [], "runs": []}', encoding="utf-8")
            with self.assertRaisesRegex(BENCHMARK.BenchmarkInputError, "duplicate JSON key"):
                BENCHMARK.load_document(duplicate)
            non_json = Path(temporary) / "non-json.json"
            non_json.write_text('{"runs": [], "value": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(BENCHMARK.BenchmarkInputError, "non-JSON numeric constant"):
                BENCHMARK.load_document(non_json)
            oversized = Path(temporary) / "oversized.json"
            oversized.write_bytes(b" " * (BENCHMARK.MAX_INPUT_BYTES + 1))
            with self.assertRaisesRegex(BENCHMARK.BenchmarkInputError, "input exceeds"):
                BENCHMARK.load_document(oversized)

    def test_cli_writes_only_local_deterministic_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.json"
            completed = subprocess.run(
                [sys.executable, str(RUNNER), "report", "--input", str(FIXTURE), "--output", str(output)],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout, "")
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["mode"], "local_deterministic_comparison_only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
