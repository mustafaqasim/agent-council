#!/usr/bin/env python3
"""Offline assembly tests use synthetic evidence, never provider calls."""
import importlib.util
import json
from pathlib import Path
import runpy
import tempfile
import unittest
import uuid
from unittest.mock import patch

import AgentCouncilPromotion as promotion

SCRIPT = Path(__file__).with_name("Assemble-AgentCouncilPromotion.py")
spec = importlib.util.spec_from_file_location("assembler", SCRIPT)
assembler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assembler)
fixture = runpy.run_path(str(SCRIPT.with_name("Test-AgentCouncilPromotion.py")))["fixture"]


class AssemblyTests(unittest.TestCase):
    def setUp(self, role_protocol=False, include_protocol_package=False):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.candidate = self.root / "candidate"
        self.evidence = self.root / "evidence"
        self.files, self.proof = fixture(self.candidate, binding_ids=["claude-code-v3-ultimate"], role_protocol=role_protocol,
                                       include_protocol_package=include_protocol_package)
        self.paths = set(self.proof["candidate_release_binding"]["behavioral_identity"]["paths"]) | {promotion.INVENTORY_PATH}
        for name, raw in self.files.items():
            if name in (promotion.PROOF_PATH, promotion.ARCHIVE_PATH):
                continue
            target = (self.candidate if name in self.paths else self.evidence) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.files[promotion.ARCHIVE_PATH] if name == promotion.REGISTRY_PATH else raw)
        self.binding = self.root / "binding.json"
        self.binding.write_bytes(promotion.canonical(self.proof["candidate_release_binding"]))
        self.manifest = self.root / "manifest.json"
        self.manifest.write_bytes(promotion.canonical({
            "schema_version": assembler.ROLE_MANIFEST_SCHEMA if role_protocol else assembler.MANIFEST_SCHEMA,
            "candidate_release_binding": self.proof["candidate_release_binding"],
            "binding_evidence": self.proof["binding_evidence"],
        }))
        self.private = self.root / "private"
        self.public = self.root / "public"

    def assemble(self, *, release=False):
        return assembler.assemble(self.candidate, self.binding, self.evidence, self.manifest,
                                  self.private, self.public, require_all_current_bindings=release)

    def test_subset_assembly_is_private_and_source_immutable(self):
        before = {str(path): path.read_bytes() for source in (self.candidate, self.evidence)
                  for path in source.rglob("*") if path.is_file()}
        (self.evidence / "secret-prompt.txt").write_text("never copy me")
        receipt = self.assemble()
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(receipt["binding_ids"], ["claude-code-v3-ultimate"])
        self.assertFalse(receipt["release_gate_complete"])
        self.assertTrue((self.private / assembler.RECEIPT_PATH).is_file())
        public_paths = {p.relative_to(self.public).as_posix() for p in self.public.rglob("*") if p.is_file()}
        self.assertEqual(public_paths, self.paths | {promotion.PROOF_PATH, promotion.ARCHIVE_PATH})
        self.assertFalse((self.private / "secret-prompt.txt").exists())
        public_proof = (self.public / promotion.PROOF_PATH).read_text()
        for secret in ("session-0-1", "Synthetic parser test.", "loader_root", '"parent_transcript":', "Synthetic test."):
            self.assertNotIn(secret, public_proof)
        self.assertEqual(json.loads(public_proof)["schema_version"], promotion.PUBLIC_SCHEMA)
        for output in (self.private, self.public):
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            for path in output.rglob("*"):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)
        for name, raw in before.items():
            self.assertEqual(Path(name).read_bytes(), raw)

    def test_existing_output_overlap_and_symlink_are_rejected(self):
        self.private.mkdir()
        with self.assertRaises(ValueError):
            self.assemble()

        self.private.rmdir()
        self.public = self.candidate / "nested"
        with self.assertRaises(ValueError):
            self.assemble()
        self.public = self.root / "public"
        artifact = self.evidence / self.proof["binding_evidence"][0]["pair"]["path"]
        saved = artifact.with_suffix(".saved")
        artifact.rename(saved)
        artifact.symlink_to(saved)
        with self.assertRaises(ValueError):
            self.assemble()
        self.assertFalse(self.private.exists())

    def test_stale_binding_is_rejected(self):
        self.binding.write_bytes(b"{}")
        with self.assertRaises(ValueError):
            self.assemble()
        self.assertFalse(self.private.exists())

    def test_role_manifest_assembles_private_and_allowlisted_public_proofs(self):
        self.setUp(role_protocol=True)
        receipt = self.assemble()
        self.assertEqual(receipt["status"], "complete")
        private = json.loads((self.private / promotion.PROOF_PATH).read_text())
        public = json.loads((self.public / promotion.PROOF_PATH).read_text())
        self.assertEqual(private["schema_version"], promotion.ROLE_SCHEMA)
        self.assertEqual(public["schema_version"], promotion.ROLE_PUBLIC_SCHEMA)
        self.assertEqual(public["qualification_protocol_version"], promotion.ROLE_PROTOCOL)
        self.assertFalse(public["full_context_blindness_verified"])
        self.assertIn("case_outcomes", public["binding_evidence"][0]["runs"][0])
        self.assertNotIn("output", public["binding_evidence"][0]["runs"][0])

    def test_manifest_cannot_relabel_historical_or_role_evidence(self):
        for role_protocol in (False, True):
            self.setUp(role_protocol=role_protocol)
            manifest = json.loads(self.manifest.read_text())
            manifest["schema_version"] = assembler.MANIFEST_SCHEMA if role_protocol else assembler.ROLE_MANIFEST_SCHEMA
            self.manifest.write_bytes(promotion.canonical(manifest))
            with self.assertRaisesRegex(ValueError, "MIXED_PROTOCOL_VERSIONS|ROLE_PROTOCOL_REQUIRED"):
                self.assemble()
            self.assertFalse(self.private.exists())

    def test_role_package_cannot_assemble_consistent_legacy_evidence(self):
        self.setUp(include_protocol_package=True)
        with self.assertRaisesRegex(ValueError, "ROLE_PROTOCOL_REQUIRED"):
            self.assemble()
        self.assertFalse(self.private.exists())
        self.assertFalse(self.public.exists())

    def test_public_package_excludes_archival_session_uuid_canary(self):
        self.setUp(role_protocol=True)
        canary = str(uuid.uuid4())
        names = ["standards/model-qualifications/claude-opus-5-5-native-qualification.v1.yaml",
                 "standards/model-qualifications/claude-opus-5-5-native-run-1.v1.json",
                 "standards/model-qualifications/claude-opus-5-5-native-run-2.v1.json"]
        current_inventory = promotion.decode((promotion.ROOT / promotion.INVENTORY_PATH).read_bytes())
        self.assertFalse(set(names) & set(current_inventory["paths"]))
        for name in names:
            source = self.candidate / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(promotion.canonical({"session_id": canary}))
        self.assemble()
        for path in self.public.rglob("*"):
            if path.is_file():
                self.assertNotIn(canary.encode(), path.read_bytes())
        for name in names:
            self.assertTrue((self.candidate / name).is_file())
            self.assertFalse((self.public / name).exists())

    def test_partial_evidence_and_stale_binding_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "EXACT_EIGHT_EVIDENCE_REQUIRED"):
            self.assemble(release=True)
        manifest = json.loads(self.manifest.read_text())
        manifest["binding_evidence"].pop()
        self.manifest.write_bytes(promotion.canonical(manifest))
        with self.assertRaises(ValueError):
            self.assemble()

    def test_cli_has_no_subset_gate_bypass(self):
        import subprocess
        result = subprocess.run(["python3", str(SCRIPT), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("--allow-subset", result.stdout)

    def test_deterministic_reassembly(self):
        first = self.assemble()
        first_public = {p.relative_to(self.public).as_posix(): p.read_bytes()
                        for p in self.public.rglob("*") if p.is_file()}
        self.private = self.root / "private-second"
        self.public = self.root / "public-second"
        self.assertEqual(self.assemble(), first)
        self.assertEqual({p.relative_to(self.public).as_posix(): p.read_bytes()
                          for p in self.public.rglob("*") if p.is_file()}, first_public)

    def test_native_host_selected_codex_fixture_assembles(self):
        files, proof = runpy.run_path(str(SCRIPT.with_name("Test-AgentCouncilPromotion.py")))["host_fixture"]()
        candidate = self.root / "host-candidate"
        evidence = self.root / "host-evidence"
        paths = set(proof["candidate_release_binding"]["behavioral_identity"]["paths"]) | {promotion.INVENTORY_PATH}
        for name, raw in files.items():
            if name in (promotion.PROOF_PATH, promotion.ARCHIVE_PATH):
                continue
            target = (candidate if name in paths else evidence) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(files[promotion.ARCHIVE_PATH] if name == promotion.REGISTRY_PATH else raw)
        binding = self.root / "host-binding.json"
        binding.write_bytes(promotion.canonical(proof["candidate_release_binding"]))
        manifest = self.root / "host-manifest.json"
        manifest.write_bytes(promotion.canonical({"schema_version": assembler.ROLE_MANIFEST_SCHEMA,
                                                 "candidate_release_binding": proof["candidate_release_binding"],
                                                 "binding_evidence": proof["binding_evidence"]}))
        result = assembler.assemble(candidate, binding, evidence, manifest, self.private, self.public,
                                    require_all_current_bindings=False)
        self.assertEqual(result["binding_ids"], ["codex-v3-ultimate"])
        public = json.loads((self.public / promotion.PROOF_PATH).read_text())
        self.assertEqual(public["binding_evidence"][0]["identity_assurance"], "host_selected")

    def test_tampered_evidence_never_writes_completion_receipt(self):
        artifact = self.evidence / self.proof["binding_evidence"][0]["pair"]["path"]
        artifact.write_bytes(b"{}")
        with self.assertRaises(ValueError):
            self.assemble()
        self.assertFalse((self.private / assembler.RECEIPT_PATH).exists())

    def test_failed_public_disk_verification_never_writes_completion_receipt(self):
        verify = assembler.promotion.verify_promotion
        def fail_public(root, **kwargs):
            if root.name.startswith(".assembly-public-"):
                raise ValueError("public disk failure")
            return verify(root, **kwargs)
        with patch.object(assembler.promotion, "verify_promotion", side_effect=fail_public) as verifier:
            with self.assertRaises(ValueError):
                self.assemble()
        self.assertEqual(verifier.call_count, 2)
        self.assertFalse((self.private / assembler.RECEIPT_PATH).exists())
        self.assertFalse(self.private.exists())
        self.assertFalse(self.public.exists())
        self.assertEqual(self.assemble()["status"], "complete")

    def test_failed_second_publish_allows_same_path_retry(self):
        rename = assembler.os.rename
        def fail_second(source, target):
            if target == self.public:
                raise OSError("injected second publish failure")
            return rename(source, target)
        with patch.object(assembler.os, "rename", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "second publish failure"):
                self.assemble()
        self.assertFalse(self.private.exists())
        self.assertFalse(self.public.exists())
        self.assertEqual(self.assemble()["status"], "complete")

    def test_changed_source_before_writes_is_rejected(self):
        export = assembler.promotion.export_public_promotion_bytes
        def mutate_source(*args, **kwargs):
            result = export(*args, **kwargs)
            (self.candidate / promotion.REGISTRY_PATH).write_bytes(b"changed")
            return result
        with patch.object(assembler.promotion, "export_public_promotion_bytes", side_effect=mutate_source):
            with self.assertRaisesRegex(ValueError, "SOURCE_CHANGED"):
                self.assemble()
        self.assertFalse(self.private.exists())


if __name__ == "__main__":
    unittest.main()
