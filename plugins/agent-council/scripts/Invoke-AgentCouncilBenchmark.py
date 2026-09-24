#!/usr/bin/env python3
"""Offline, deterministic comparison reporting for paired Council benchmarks.

This tool only reads local JSON records and emits a local JSON report.  It never
dispatches a model, contacts a service, records telemetry, or qualifies a model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


SCHEMA_VERSION = "agent-council.benchmark-runs/v1"
REPORT_SCHEMA_VERSION = "agent-council.benchmark-report/v1"
MAX_INPUT_BYTES = 1_000_000
MAX_RUNS = 1_000
MAX_DEPTH = 32
CONDITIONS = {"direct", "council"}
ORDERS = {"direct_first", "council_first"}
VERDICTS = {"pass", "fail", "unknown"}
USAGE_ACTORS = ("orchestrator", "worker")
USAGE_FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")
UNKNOWN = "unknown"


class BenchmarkInputError(ValueError):
    """Raised when a local benchmark document is malformed or out of bounds."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BenchmarkInputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> None:
    raise BenchmarkInputError(f"non-JSON numeric constant: {value}")


def _check_depth(value: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise BenchmarkInputError(f"JSON nesting exceeds {MAX_DEPTH}")
    if isinstance(value, dict):
        for nested in value.values():
            _check_depth(nested, depth + 1)
    elif isinstance(value, list):
        for nested in value:
            _check_depth(nested, depth + 1)


def load_document(path: Path) -> dict[str, Any]:
    """Read one bounded, duplicate-key-free JSON benchmark document."""
    if not path.is_file():
        raise BenchmarkInputError("input must be a regular file")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise BenchmarkInputError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    try:
        raw = path.read_text(encoding="utf-8")
        document = json.loads(raw, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_non_json_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise BenchmarkInputError(f"invalid JSON input: {error}") from error
    _check_depth(document)
    if not isinstance(document, dict):
        raise BenchmarkInputError("document root must be an object")
    return document


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BenchmarkInputError(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise BenchmarkInputError(f"{name} must be a non-empty string")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BenchmarkInputError(f"{name} must be a non-negative integer")
    return value


def _unknown_string(value: Any, name: str) -> str:
    if value is None:
        return UNKNOWN
    return _string(value, name)


def _known(value: Any) -> bool:
    return value != UNKNOWN


def _validate_keys(value: dict[str, Any], allowed: set[str], name: str) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise BenchmarkInputError(f"{name} has unsupported fields: {', '.join(unexpected)}")


def _normalize_usage(value: Any) -> dict[str, dict[str, int | str]]:
    if value is None:
        return {actor: {field: UNKNOWN for field in USAGE_FIELDS} for actor in USAGE_ACTORS}
    usage = _object(value, "usage")
    _validate_keys(usage, set(USAGE_ACTORS), "usage")
    normalized: dict[str, dict[str, int | str]] = {}
    for actor in USAGE_ACTORS:
        actor_usage = usage.get(actor)
        if actor_usage is None:
            normalized[actor] = {field: UNKNOWN for field in USAGE_FIELDS}
            continue
        actor_usage = _object(actor_usage, f"usage.{actor}")
        _validate_keys(actor_usage, set(USAGE_FIELDS), f"usage.{actor}")
        normalized[actor] = {
            field: UNKNOWN if actor_usage.get(field) is None else _non_negative_int(actor_usage[field], f"usage.{actor}.{field}")
            for field in USAGE_FIELDS
        }
    return normalized


def _normalize_verdict(value: Any) -> dict[str, str]:
    if value is None:
        return {"correctness": UNKNOWN, "quality": UNKNOWN}
    verdict = _object(value, "verdict")
    _validate_keys(verdict, {"correctness", "quality"}, "verdict")
    normalized: dict[str, str] = {}
    for field in ("correctness", "quality"):
        result = UNKNOWN if verdict.get(field) is None else _string(verdict[field], f"verdict.{field}")
        if result not in VERDICTS:
            raise BenchmarkInputError(f"verdict.{field} must be pass, fail, or unknown")
        normalized[field] = result
    return normalized


def _normalize_interventions(value: Any) -> list[str] | str:
    if value is None:
        return UNKNOWN
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise BenchmarkInputError("interventions must be a list of non-empty strings")
    return value


def _normalize_provenance(value: Any) -> dict[str, Any] | str:
    if value is None:
        return UNKNOWN
    provenance = _object(value, "provenance")
    # Provenance is retained verbatim as a local reference map, but its shape is bounded.
    return provenance


def normalize_run(value: Any, index: int) -> dict[str, Any]:
    run = _object(value, f"runs[{index}]")
    allowed = {
        "record_id", "pair_id", "fixture_id", "scope_id", "rubric_id", "condition", "order",
        "observed", "usage", "elapsed_ms", "retries", "verdict", "interventions", "provenance",
    }
    _validate_keys(run, allowed, f"runs[{index}]")
    required = ("pair_id", "fixture_id", "scope_id", "rubric_id", "condition", "order")
    missing = [field for field in required if field not in run]
    if missing:
        raise BenchmarkInputError(f"runs[{index}] is missing required fields: {', '.join(missing)}")
    condition = _string(run["condition"], f"runs[{index}].condition")
    order = _string(run["order"], f"runs[{index}].order")
    if condition not in CONDITIONS:
        raise BenchmarkInputError(f"runs[{index}].condition must be direct or council")
    if order not in ORDERS:
        raise BenchmarkInputError(f"runs[{index}].order must be direct_first or council_first")
    observed = run.get("observed")
    if observed is None:
        observed_normalized = {"model": UNKNOWN, "effort": UNKNOWN}
    else:
        observed = _object(observed, f"runs[{index}].observed")
        _validate_keys(observed, {"model", "effort"}, f"runs[{index}].observed")
        observed_normalized = {
            "model": _unknown_string(observed.get("model"), f"runs[{index}].observed.model"),
            "effort": _unknown_string(observed.get("effort"), f"runs[{index}].observed.effort"),
        }
    return {
        "record_id": _unknown_string(run.get("record_id"), f"runs[{index}].record_id"),
        "pair_id": _string(run["pair_id"], f"runs[{index}].pair_id"),
        "fixture_id": _string(run["fixture_id"], f"runs[{index}].fixture_id"),
        "scope_id": _string(run["scope_id"], f"runs[{index}].scope_id"),
        "rubric_id": _string(run["rubric_id"], f"runs[{index}].rubric_id"),
        "condition": condition,
        "order": order,
        "observed": observed_normalized,
        "usage": _normalize_usage(run.get("usage")),
        "elapsed_ms": UNKNOWN if run.get("elapsed_ms") is None else _non_negative_int(run["elapsed_ms"], f"runs[{index}].elapsed_ms"),
        "retries": UNKNOWN if run.get("retries") is None else _non_negative_int(run["retries"], f"runs[{index}].retries"),
        "verdict": _normalize_verdict(run.get("verdict")),
        "interventions": _normalize_interventions(run.get("interventions")),
        "provenance": _normalize_provenance(run.get("provenance")),
    }


def normalize_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    _validate_keys(document, {"schema_version", "fixture_notice", "runs"}, "document")
    if document.get("schema_version") not in (None, SCHEMA_VERSION):
        raise BenchmarkInputError(f"schema_version must be {SCHEMA_VERSION}")
    if "fixture_notice" in document:
        _string(document["fixture_notice"], "fixture_notice")
    runs = document.get("runs")
    if not isinstance(runs, list):
        raise BenchmarkInputError("runs must be a list")
    if len(runs) > MAX_RUNS:
        raise BenchmarkInputError(f"runs exceeds {MAX_RUNS}")
    return [normalize_run(run, index) for index, run in enumerate(runs)]


def _pair_delta(direct: dict[str, Any], council: dict[str, Any]) -> dict[str, Any]:
    deltas: dict[str, Any] = {}
    unknown_metrics: list[str] = []
    for field in ("elapsed_ms", "retries"):
        if _known(direct[field]) and _known(council[field]):
            deltas[field] = council[field] - direct[field]
        else:
            unknown_metrics.append(field)
    usage_deltas: dict[str, int] = {}
    for actor in USAGE_ACTORS:
        for field in USAGE_FIELDS:
            direct_value = direct["usage"][actor][field]
            council_value = council["usage"][actor][field]
            label = f"{actor}.{field}"
            if _known(direct_value) and _known(council_value):
                usage_deltas[label] = council_value - direct_value
            else:
                unknown_metrics.append(label)
    return {"deltas": deltas, "usage_deltas": usage_deltas, "unknown_metrics": unknown_metrics}


def _run_context(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": run["record_id"],
        "observed": run["observed"],
        "interventions": run["interventions"],
        "provenance": run["provenance"],
        "verdict": run["verdict"],
    }


def build_report(document: dict[str, Any]) -> dict[str, Any]:
    """Return pair-only deltas, exclusions, verdict failures, and order metadata."""
    runs = normalize_document(document)
    groups: dict[str, list[dict[str, Any]]] = {}
    failures: list[dict[str, Any]] = []
    for run in runs:
        groups.setdefault(run["pair_id"], []).append(run)
    complete: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    direct_first = 0
    council_first = 0
    for pair_id in sorted(groups):
        records = groups[pair_id]
        if len(records) != 2:
            excluded.append({"pair_id": pair_id, "reason": "expected exactly two records"})
            continue
        by_condition = {record["condition"]: record for record in records}
        if len(by_condition) != 2:
            excluded.append({"pair_id": pair_id, "reason": "expected one direct and one council record"})
            continue
        direct, council = by_condition["direct"], by_condition["council"]
        identifiers = ("fixture_id", "scope_id", "rubric_id")
        mismatches = [field for field in identifiers if direct[field] != council[field]]
        if mismatches:
            excluded.append({"pair_id": pair_id, "reason": f"mismatched {', '.join(mismatches)}"})
            continue
        if direct["order"] != council["order"]:
            excluded.append({"pair_id": pair_id, "reason": "mismatched order metadata"})
            continue
        if direct["order"] == "direct_first":
            direct_first += 1
        else:
            council_first += 1
        for run in (direct, council):
            for verdict_name, verdict in run["verdict"].items():
                if verdict == "fail":
                    failures.append({"pair_id": pair_id, "condition": run["condition"], "verdict": verdict_name, "record_id": run["record_id"]})
        delta = _pair_delta(direct, council)
        complete.append({
            "pair_id": pair_id,
            "fixture_id": direct["fixture_id"],
            "scope_id": direct["scope_id"],
            "rubric_id": direct["rubric_id"],
            "order": direct["order"],
            "runs": {"direct": _run_context(direct), "council": _run_context(council)},
            **delta,
        })
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "mode": "local_deterministic_comparison_only",
        "performance_claim": "none",
        "input_run_count": len(runs),
        "complete_comparable_pair_count": len(complete),
        "complete_comparable_pairs": complete,
        "excluded_or_incomplete_pairs": excluded,
        "quality_failures": failures,
        "order_metadata": {
            "direct_first_pairs": direct_first,
            "council_first_pairs": council_first,
            "balanced_within_one_pair": abs(direct_first - council_first) <= 1,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report paired local benchmark deltas without model execution.")
    parser.add_argument("report", nargs="?", default="report")
    parser.add_argument("--input", type=Path, required=True, help="bounded local JSON run document")
    parser.add_argument("--output", type=Path, help="optional local JSON report destination")
    args = parser.parse_args(argv)
    if args.report != "report":
        parser.error("only the report command is supported")
    try:
        report = build_report(load_document(args.input))
    except BenchmarkInputError as error:
        parser.error(str(error))
    rendered = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output is None:
        sys.stdout.write(rendered)
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
