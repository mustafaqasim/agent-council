#!/usr/bin/env python3
"""Offline successor migration tests, not native qualification evidence."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("migration", Path(__file__).with_name("Migrate-AgentCouncilCase.py"))
assert SPEC is not None and SPEC.loader is not None
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)
core = migration.core


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        self.source = self.project / "historical"
        self.destination = self.project / "successor"
        # Historical fixture creation is isolated from the public init command,
        # which correctly refuses creating new v2 cases.
        historical = core._pinned_artifact_material("v2")
        with patch.object(core, "_pinned_artifact_material", return_value=historical):
            core.init_case(self.source, self.project, "historical-case", "R1")
        core._write_exclusive(self.source / "evidence/historical.json", b'{"old":true}\n')
        self.before = migration._snapshot(self.source)

    def migrate(self, **kwargs):
        return migration.migrate_case(self.source, self.destination, self.project, "successor-case", **kwargs)

    def assert_refused(self, code, callback=None):
        with self.assertRaises(core.AuthoringError) as error:
            (callback or self.migrate)()
        self.assertEqual(error.exception.code, code)
        self.assertFalse(self.destination.exists())

    def test_successor_uses_current_pins_and_carries_no_authority(self):
        old = core._read_local_case(self.source)
        result = self.migrate()
        self.assertEqual(result["code"], "CASE_MIGRATED")
        self.assertFalse(result["authority_transferred"])
        self.assertEqual(migration._snapshot(self.source), self.before)
        new = core._read_local_case(self.destination)
        self.assertEqual(new["case_root"], str(self.destination))
        self.assertNotIn(".agent-council-migration-", (self.destination / "case.json").read_text())
        for event_path in (self.destination / "events").glob("*.json"):
            self.assertNotIn(".agent-council-migration-", event_path.read_text())
        self.assertEqual(new["registry"]["registry_version"], "v3")
        self.assertNotEqual(new["registry"], old["registry"])
        self.assertEqual(new["route"], old["route"])
        self.assertEqual(new["cycle_id"], "cycle-000001")
        self.assertEqual(len(new["events"]), 1)
        self.assertFalse((self.destination / "evidence").exists())
        for field in ("capabilities", "dispatch_plans", "dispatch_receipts", "handoff_lifecycle"):
            self.assertEqual(new[field], {})
        for field in core._CANDIDATE_HASH_FIELDS:
            self.assertEqual(new["engineering_candidate"][field], old["engineering_candidate"][field])
        self.assertNotEqual(new["engineering_candidate"]["candidate_sha256"], old["engineering_candidate"]["candidate_sha256"])
        proof = json.loads((self.destination / "migration-provenance.json").read_text())
        self.assertEqual(proof["source"]["file_sha256"], self.before)
        self.assertEqual(proof["successor"]["initial_case_sha256"], core._file_sha(self.destination / "case.json"))
        self.assertEqual(proof["provenance_sha256"], core._digest({key: value for key, value in proof.items() if key != "provenance_sha256"}))
        core.build_bundle(self.destination)

    def test_explicit_engineering_candidate(self):
        candidate = {field: "1" * 64 for field in core._CANDIDATE_HASH_FIELDS}
        self.migrate(candidate=candidate)
        new = core._read_local_case(self.destination)
        for field in core._CANDIDATE_HASH_FIELDS:
            self.assertEqual(new["engineering_candidate"][field], candidate[field])

    def test_changed_source_cycle_retains_current_engineering_inputs(self):
        candidate = {field: "2" * 64 for field in core._CANDIDATE_HASH_FIELDS}
        core.cycle_start(self.source, candidate)
        self.migrate()
        new = core._read_local_case(self.destination)
        for field in core._CANDIDATE_HASH_FIELDS:
            self.assertEqual(new["engineering_candidate"][field], candidate[field])
        self.assertEqual(len(new["events"]), 1)

    def test_unresolved_interruption_cannot_be_discarded(self):
        core.interrupt_case(self.source, [])
        self.assert_refused("INTERRUPTION_UNRESOLVED")

    def test_source_route_cannot_diverge_from_immutable_intake(self):
        state = core._read_local_case(self.source)
        state["route"] = "R2"
        core._write_atomic(self.source / "case.json", core._canonical(state) + b"\n")
        self.assert_refused("ROUTE_CLASSIFICATION_MISSING")

    def test_source_pending_recovery_is_not_modified(self):
        core._pending_path(self.source).write_text("pending")
        before = migration._snapshot(self.source)
        self.assert_refused("MIGRATION_SOURCE_RECOVERY_REQUIRED")
        self.assertEqual(migration._snapshot(self.source), before)

    def test_existing_destination_is_preserved(self):
        self.destination.mkdir()
        marker = self.destination / "owned.txt"
        marker.write_text("user content")
        with self.assertRaises(core.AuthoringError) as error:
            self.migrate()
        self.assertEqual(error.exception.code, "DUPLICATE_EVENT_REFUSED")
        self.assertEqual(marker.read_text(), "user content")

    def test_concurrently_created_empty_destination_is_never_replaced(self):
        publish = migration._publish_exclusive
        created_inode = None
        def raced(staged, destination):
            nonlocal created_inode
            destination.mkdir()
            created_inode = destination.stat().st_ino
            publish(staged, destination)
        with patch.object(migration, "_publish_exclusive", side_effect=raced):
            with self.assertRaises(core.AuthoringError) as error:
                self.migrate()
        self.assertEqual(error.exception.code, "DUPLICATE_EVENT_REFUSED")
        self.assertEqual(self.destination.stat().st_ino, created_inode)
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assertEqual(migration._snapshot(self.source), self.before)
        self.assertFalse(list(self.project.glob(".agent-council-migration-*")))

    def test_concurrently_created_destination_symlink_is_never_replaced(self):
        publish = migration._publish_exclusive
        def raced(staged, destination):
            destination.symlink_to(self.source)
            publish(staged, destination)
        with patch.object(migration, "_publish_exclusive", side_effect=raced):
            with self.assertRaises(core.AuthoringError) as error:
                self.migrate()
        self.assertEqual(error.exception.code, "DUPLICATE_EVENT_REFUSED")
        self.assertTrue(self.destination.is_symlink())
        self.assertEqual(migration._snapshot(self.source), self.before)

    @unittest.skipIf(migration.os.name == "nt", "Windows rename is already exclusive")
    def test_missing_exclusive_api_does_not_fall_back_to_replacing_rename(self):
        with patch.object(migration.ctypes, "CDLL", return_value=object()):
            self.assert_refused("MIGRATION_ATOMIC_PUBLICATION_UNAVAILABLE")
        self.assertEqual(migration._snapshot(self.source), self.before)

    def test_overlapping_source_and_destination_are_refused(self):
        for destination in (self.source, self.source / "child", self.project):
            self.assert_refused("MIGRATION_CASE_ROOT_OVERLAP", lambda: migration.migrate_case(
                self.source, destination, self.project, "successor-case"))

    def test_case_id_must_change(self):
        self.assert_refused("MIGRATION_NEW_CASE_ID_REQUIRED", lambda: migration.migrate_case(
            self.source, self.destination, self.project, "historical-case"))

    def test_destination_outside_project_is_refused(self):
        self.assert_refused("CASE_ROOT_OUTSIDE_PROJECT_BOUNDARY", lambda: migration.migrate_case(
            self.source, self.project.parent / "outside-migration", self.project, "successor-case"))

    def test_cli_migrates_and_reports_structured_failure_on_repeat(self):
        args = [sys.executable, str(Path(migration.__file__)), "--source-case-root", str(self.source),
                "--case-root", str(self.destination), "--project-root", str(self.project),
                "--case-id", "successor-case"]
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["code"], "CASE_MIGRATED")
        repeated = subprocess.run(args, capture_output=True, text=True, check=False)
        self.assertEqual(repeated.returncode, 1)
        self.assertEqual(json.loads(repeated.stdout)["code"], "DUPLICATE_EVENT_REFUSED")
        self.assertEqual(repeated.stderr, "")

    def test_pin_tampering_refused(self):
        state = core._read_local_case(self.source)
        relative = next(iter(state["policy_bundle"]["artifact_pins"]))
        (self.source / "pinned" / relative).chmod(0o600)
        (self.source / "pinned" / relative).write_text("tampered")
        with self.assertRaises(core.AuthoringError):
            self.migrate()
        self.assertFalse(self.destination.exists())

    def test_event_tampering_refused(self):
        event = next((self.source / "events").glob("*.json"))
        event.chmod(0o600)
        event.write_text("{}")
        self.assert_refused("MIGRATION_SOURCE_HISTORY_INVALID")

    def test_symlink_refused(self):
        (self.source / "redirect").symlink_to(self.project)
        self.assert_refused("CASE_PATH_SYMLINK_REFUSED")

    def test_failure_before_publication_leaves_no_destination(self):
        with patch.object(core, "_write_exclusive", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.migrate()
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.project.glob(".agent-council-migration-*")))
        self.assertEqual(migration._snapshot(self.source), self.before)

    def test_concurrent_source_change_refuses_publication(self):
        original = core.init_case
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.source / "changed.txt").write_text("concurrent change")
            return result
        with patch.object(core, "init_case", side_effect=changed):
            self.assert_refused("MIGRATION_SOURCE_CHANGED")

    def test_successor_binding_follows_current_pinned_registry(self):
        self.migrate()
        state = core._read_local_case(self.destination)
        qualified = [binding for binding in state["registry"]["bindings"]
                     if binding["provider"] == "codex"
                     and binding["tier"] == "operational_intelligence"
                     and binding["status"] == "qualified"]
        provider_qualified = state["registry"]["provider_states"]["codex"]["council_status"] == "qualified"
        if provider_qualified and len(qualified) == 1:
            self.assertEqual(core._binding(state, "codex", "operational_intelligence"), qualified[0])
        else:
            with self.assertRaises(core.AuthoringError) as error:
                core._binding(state, "codex", "operational_intelligence")
            self.assertEqual(error.exception.code, "REQUIRED_TIER_BINDING_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
