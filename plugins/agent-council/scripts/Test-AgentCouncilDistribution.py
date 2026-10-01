#!/usr/bin/env python3
"""Offline release-package checks; packet YAML uses the JSON-compatible subset."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
DOCS = REPO / "docs" / "distribution"
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
VERSION = "0.9.0"
PACKETS = ("openai-universal-directory.yaml", "anthropic-directory.yaml")
RELEASE_EVIDENCE_FIELDS = (
    "commit_sha", "tag", "archive_sha256", "artifact_path", "validation_receipt",
    "native_host_receipts", "cross_plugin_receipts",
)
RECEIPT_LIST_FIELDS = {"native_host_receipts", "cross_plugin_receipts"}
HISTORICAL_NATIVE_RECEIPTS = {
    "standards/model-qualifications/claude-opus-5-5-native-qualification.v1.yaml",
    "standards/model-qualifications/claude-opus-5-5-native-run-1.v1.json",
    "standards/model-qualifications/claude-opus-5-5-native-run-2.v1.json",
}


def load(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate key: {key}")
            result[key] = value
        return result
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(data, dict):
        raise ValueError(f"Expected object: {path}")
    return data


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def confined(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and relative.startswith("./"), "Path must start with ./")
    require(".." not in Path(relative).parts, "Parent traversal is forbidden")
    resolved = (root / relative).resolve(strict=True)
    require(resolved.is_relative_to(root.resolve()), "Path escapes package root")
    return resolved


def validate_manifest(data: dict) -> None:
    allowed = {"$schema", "name", "version", "description", "author", "homepage", "repository", "license", "keywords", "extensions"}
    require(set(data) <= allowed, "Unsupported portable manifest field")
    require(data.get("$schema") == SCHEMA, "Portable schema mismatch")
    name = data.get("name")
    require(isinstance(name, str) and 1 <= len(name) <= 64 and re.fullmatch(r"(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", name) is not None, "Invalid portable name")
    require(name == "agent-council" and data.get("version") == VERSION, "Release identity mismatch")
    for key in ("version", "description", "homepage", "repository", "license"):
        if key in data:
            require(isinstance(data[key], str), f"Invalid {key}")
    if "author" in data:
        require(isinstance(data["author"], dict) and set(data["author"]) <= {"name", "email", "url"}, "Invalid author")
        require(all(isinstance(value, str) for value in data["author"].values()), "Invalid author value")
    if "keywords" in data:
        require(isinstance(data["keywords"], list) and all(isinstance(value, str) for value in data["keywords"]), "Invalid keywords")
    if "extensions" in data:
        require(isinstance(data["extensions"], dict) and all(isinstance(value, dict) for value in data["extensions"].values()), "Invalid extensions")


def validate_packet(data: dict, shared: dict) -> None:
    for key in ("packet_id", "directory", "status", "plugin", "description", "install_source", "component_inventory", "permissions", "network_behavior", "local_data_handling", "compatibility", "support_url", "security_url", "asset", "release_evidence", "publisher_prerequisites", "sources", "test_cases"):
        require(key in data and data[key] not in (None, "", {}, []), f"Incomplete packet field: {key}")
    require(data["status"] == "local_draft_not_submitted", "Packet must not claim submission")
    require(data["plugin"] == {"name": "agent-council", "version": VERSION}, "Packet identity mismatch")
    source = data["install_source"]
    require(source["package_path"] == "./plugins/agent-council", "Wrong install root")
    require(confined(REPO, source["package_path"]) == ROOT, "Install source does not resolve to package")
    for entry in data["component_inventory"]:
        require(set(entry) >= {"kind", "path", "portable"}, "Incomplete component inventory entry")
        confined(ROOT, entry["path"])
    require(data["release_evidence"] == "./docs/distribution/readiness.yaml#release_evidence", "Release evidence reference mismatch")
    for key in ("permissions", "network_behavior", "local_data_handling", "compatibility"):
        require(data[key] == f"./docs/distribution/readiness.yaml#{key}" and bool(shared.get(key)), f"Missing shared section: {key}")
    confined(REPO, data["asset"]["repository_path"])
    require(data["asset"]["status"] == "existing_reference_pending_directory_acceptance", "Asset acceptance must be pending")
    require(all(item.get("status") == "pending" and item.get("requirement") for item in data["publisher_prerequisites"]), "Publisher prerequisites must be explicit and pending")
    for case in data["test_cases"]:
        require(all(case.get(key) for key in ("id", "kind", "prompt", "expected", "fixture", "status")), "Incomplete reviewer test case")
        require(case["status"] == "pending_host_execution", "Reviewer cases must not claim observed success")
    require(sum(case["kind"] == "positive" for case in data["test_cases"]) >= 5, "Need five positive reviewer cases")
    require(sum(case["kind"] == "negative" for case in data["test_cases"]) >= 3, "Need three negative reviewer cases")


def validate_release_evidence(evidence: dict) -> None:
    """Check evidence-record shape, not the authenticity of completed receipts."""
    require(isinstance(evidence, dict), "Release evidence must be an object")
    for key in RELEASE_EVIDENCE_FIELDS:
        item = evidence.get(key)
        require(isinstance(item, dict), f"Missing release evidence: {key}")
        require({"status", "value", "required_evidence"} <= set(item), f"Incomplete release evidence: {key}")
        require(isinstance(item["required_evidence"], str) and bool(item["required_evidence"].strip()), f"Missing evidence requirement: {key}")
        require(item["status"] in ("pending", "complete"), f"Unknown evidence status: {key}")
        value = item["value"]
        if item["status"] == "pending":
            require(value == [] if key in RECEIPT_LIST_FIELDS else value is None, f"Pending evidence must have no value: {key}")
            continue
        if key in RECEIPT_LIST_FIELDS:
            require(isinstance(value, list) and bool(value), f"Completed evidence needs receipts: {key}")
            require(all(isinstance(receipt, str) and bool(receipt.strip()) for receipt in value), f"Completed receipts must be references: {key}")
        else:
            require(isinstance(value, str) and bool(value.strip()), f"Completed evidence needs a value: {key}")
            if key in ("commit_sha", "archive_sha256"):
                length = 40 if key == "commit_sha" else 64
                require(re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None, f"Invalid completed digest: {key}")


class DistributionTests(unittest.TestCase):
    def test_public_distribution_records_omit_native_session_identifiers(self):
        uuid = re.compile(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", re.I)
        identifier_field = re.compile(r"\b(?:session_ids?|agent_id)\s*:")
        for path in DOCS.rglob("*"):
            if path.suffix not in {".yaml", ".yml", ".md", ".json"}:
                continue
            content = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(REPO)):
                self.assertIsNone(uuid.search(content))
                self.assertIsNone(identifier_field.search(content))

    def test_portable_manifest(self):
        self.assertFalse((REPO / "plugin.json").exists(), "Do not make the marketplace root installable")
        validate_manifest(load(confined(ROOT, "./plugin.json")))

    def test_compatibility_identity(self):
        portable = load(ROOT / "plugin.json")
        for path in ("./.codex-plugin/plugin.json", "./.claude-plugin/plugin.json"):
            compatibility = load(confined(ROOT, path))
            self.assertEqual((compatibility["name"], compatibility["version"]), (portable["name"], portable["version"]))

    def test_package_paths(self):
        # Inspect every packaged symlink, not only the declared entry points.
        for path in ROOT.rglob("*"):
            if path.is_symlink():
                confined(ROOT, "./" + path.relative_to(ROOT).as_posix())
        self.assertTrue(confined(ROOT, "./skills/agent-council/SKILL.md").is_file())
        self.assertFalse((ROOT / "mcp.json").exists(), "Inventory must be revised when MCP is added")

    def test_package_readme_and_license(self):
        prose = re.sub(r"```.*?```", "", (ROOT / "README.md").read_text(), flags=re.S)
        self.assertGreaterEqual(len(prose.split()), 40)
        self.assertEqual((ROOT / "LICENSE").read_bytes(), (REPO / "LICENSE").read_bytes())
        self.assertEqual(load(ROOT / ".claude-plugin/plugin.json")["license"], "MIT")

    def test_current_inventory_covers_behavior(self):
        paths = load(ROOT / "standards/behavioral-inventory.v1.json")["paths"]
        inventory = set(paths)
        self.assertEqual(len(paths), len(inventory), "Behavioral inventory contains duplicate paths")
        required = {"plugin.json", "README.md", "LICENSE", "evals/.gitignore",
                    ".claude-plugin/plugin.json", ".codex-plugin/plugin.json"}
        for folder in ("agents", "skills", "scripts", "hooks", "codex", "profiles", "standards", "evals"):
            for path in (ROOT / folder).rglob("*"):
                relative = path.relative_to(ROOT).as_posix()
                if path.is_file() and "__pycache__" not in path.parts and not {"results", "local"}.intersection(path.relative_to(ROOT).parts) and path.suffix != ".pyc" and relative not in {"standards/behavioral-inventory.v1.json", "standards/model-qualifications/promotion.v1.json", "standards/model-qualifications/candidate-registry.v3.json"}:
                    required.add(relative)
        self.assertEqual(required, inventory, "Behavioral inventory must cover exactly the distributable behavior files")

    def test_private_archival_receipts_are_absent_from_marketplace_source(self):
        inventory = set(load(ROOT / "standards/behavioral-inventory.v1.json")["paths"])
        self.assertFalse(inventory & HISTORICAL_NATIVE_RECEIPTS)
        for relative in HISTORICAL_NATIVE_RECEIPTS:
            self.assertFalse((ROOT / relative).exists(), "Private native receipts must not ship through marketplace source")

    def test_shared_readiness(self):
        shared = load(DOCS / "readiness.yaml")
        self.assertEqual(shared["version"], VERSION)
        self.assertIn(shared["status"], ("local_preparation_only", "release_complete"))
        validate_release_evidence(shared["release_evidence"])
        if shared["status"] == "release_complete":
            self.assertTrue(all(shared["release_evidence"][key]["status"] == "complete"
                                for key in RELEASE_EVIDENCE_FIELDS))

    def completed_evidence(self):
        evidence = copy.deepcopy(load(DOCS / "readiness.yaml")["release_evidence"])
        values = {
            "commit_sha": "a" * 40,
            "tag": "v0.9.0",
            "archive_sha256": "b" * 64,
            "artifact_path": "./release/agent-council-0.9.0.zip",
            "validation_receipt": "./release/validation.yaml",
            "native_host_receipts": ["./release/claude-native.yaml", "./release/codex-native.yaml"],
            "cross_plugin_receipts": ["./release/cross-plugin.yaml"],
        }
        for key, value in values.items():
            evidence[key].update(status="complete", value=value)
        return evidence

    def test_accepts_complete_and_partially_collected_release_evidence(self):
        complete = self.completed_evidence()
        validate_release_evidence(complete)
        for key in RELEASE_EVIDENCE_FIELDS:
            candidate = copy.deepcopy(complete)
            candidate[key].update(status="pending", value=[] if key in RECEIPT_LIST_FIELDS else None)
            with self.subTest(field=key):
                validate_release_evidence(candidate)

    def test_rejects_missing_release_evidence_fields(self):
        for key in RELEASE_EVIDENCE_FIELDS:
            for field in (None, "status", "value", "required_evidence"):
                candidate = self.completed_evidence()
                if field is None:
                    candidate.pop(key)
                else:
                    candidate[key].pop(field)
                with self.subTest(evidence=key, field=field), self.assertRaises(ValueError):
                    validate_release_evidence(candidate)

    def test_rejects_invalid_release_evidence(self):
        for key in RELEASE_EVIDENCE_FIELDS:
            for patch in ({"status": "verified"}, {"status": "pending"}, {"value": None}, {"value": " "}, {"value": []}, {"value": {}}, {"value": True}, {"required_evidence": " "}):
                candidate = self.completed_evidence()
                candidate[key].update(patch)
                with self.subTest(evidence=key, patch=patch), self.assertRaises(ValueError):
                    validate_release_evidence(candidate)
        for key, value in (("commit_sha", "short"), ("commit_sha", "g" * 40), ("archive_sha256", "a" * 63), ("archive_sha256", "g" * 64), ("native_host_receipts", [""]), ("cross_plugin_receipts", [{}])):
            candidate = self.completed_evidence()
            candidate[key]["value"] = value
            with self.subTest(evidence=key, value=value), self.assertRaises(ValueError):
                validate_release_evidence(candidate)

    def test_packets(self):
        shared = load(DOCS / "readiness.yaml")
        for name in PACKETS:
            with self.subTest(packet=name):
                validate_packet(load(DOCS / name), shared)

    def test_rejects_bad_identity_and_fields(self):
        original = {"$schema": SCHEMA, "name": "agent-council", "version": VERSION}
        for field, value in (("name", "elsewhere"), ("version", "0.8.2"), ("$schema", "https://invalid.example/schema"), ("skills", "./skills/"), ("hooks", "./hooks/hooks.json"), ("author", {"unexpected": True})):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_manifest(dict(original, **{field: value}))

    def test_rejects_escape_missing_and_symlink(self):
        with tempfile.TemporaryDirectory(prefix="council-distribution-") as temporary:
            parent = Path(temporary)
            package = parent / "package"
            package.mkdir()
            (package / "valid").mkdir()
            (parent / "outside").mkdir()
            (package / "escape").symlink_to(parent / "outside", target_is_directory=True)
            (package / "inside").symlink_to(package / "valid", target_is_directory=True)
            self.assertEqual(confined(package, "./inside"), (package / "valid").resolve())
            for path in ("./../outside", str(parent / "outside"), "./escape", "./missing", "valid"):
                with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                    confined(package, path)

    def test_rejects_incomplete_packets(self):
        shared = load(DOCS / "readiness.yaml")
        original = load(DOCS / PACKETS[0])
        for field in original:
            if field in ("starter_prompt", "release_notes", "category", "portal_url"):
                continue
            candidate = copy.deepcopy(original)
            candidate.pop(field)
            with self.subTest(field=field), self.assertRaises((ValueError, KeyError)):
                validate_packet(candidate, shared)


if __name__ == "__main__":
    unittest.main(verbosity=2)
