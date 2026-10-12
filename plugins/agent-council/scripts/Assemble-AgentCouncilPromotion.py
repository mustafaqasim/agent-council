#!/usr/bin/env python3
"""Assemble exact-eight promotion evidence privately and a verified public package.

Role packages require agent-council.promotion-evidence-manifest/v2, with
candidate_release_binding and binding_evidence in the private v3 proof format.
Manifest v1 and private proof v1 remain valid only for historical packages
whose frozen behavioral inventory does not contain the role protocol.
Reference paths are relative to --evidence-root. Only those references are read.
Both outputs must be new, disjoint directories outside all source locations.
No native runs, source changes, uploads, or qualification authenticity claims.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import tempfile

import AgentCouncilPromotion as promotion

MANIFEST_SCHEMA = "agent-council.promotion-evidence-manifest/v1"
ROLE_MANIFEST_SCHEMA = "agent-council.promotion-evidence-manifest/v2"
RECEIPT_PATH = "assembly-complete.json"


def reject(code):
    raise ValueError("ASSEMBLY_" + code)


def safe_path(path):
    path = Path(os.path.abspath(path))
    if any(part.is_symlink() for part in (path, *path.parents)):
        reject("SYMLINK")
    return path


class Snapshot:
    """Read regular files once and detect aliases and concurrent source changes."""
    def __init__(self):
        self.observations = {}
        self.identities = {}

    @staticmethod
    def metadata(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def read(self, path):
        path = safe_path(path)
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            reject("NOT_REGULAR")
        identity = before.st_dev, before.st_ino
        if identity in self.identities and self.identities[identity] != path:
            reject("FILE_ALIAS")
        with path.open("rb") as stream:
            if self.metadata(os.fstat(stream.fileno())) != self.metadata(before):
                reject("SOURCE_CHANGED")
            raw = stream.read()
        if self.metadata(path.stat()) != self.metadata(before):
            reject("SOURCE_CHANGED")
        if path in self.observations and self.observations[path] != self.metadata(before):
            reject("SOURCE_CHANGED")
        self.identities[identity] = path
        self.observations[path] = self.metadata(before)
        return raw

    def check(self):
        for path, metadata in self.observations.items():
            if self.metadata(safe_path(path).stat()) != metadata:
                reject("SOURCE_CHANGED")


def references(rows):
    """Select only evidence slots understood by the promotion verifier."""
    for row in rows:
        promotion.fields(row, {"binding_id", "pair", "runs", "probe", "probe_files"} |
                         ({"host_selection"} if "host_selection" in row else set()) |
                         ({"qualification_protocol"} if "qualification_protocol" in row else set()), "EVIDENCE_INVALID")
        yield row["pair"]
        yield row["probe"]
        if not isinstance(row["runs"], list) or len(row["runs"]) != 2:
            reject("RUN_SET_INVALID")
        for run in row["runs"]:
            promotion.fields(run, {"receipt", "transcript"} |
                             ({"parent_transcript"} if "host_selection" in row else set()), "RUN_INVALID")
            yield from run.values()
        files = row["probe_files"]
        required = {"release_binding", "parent_transcript", "child_transcript"}
        if "host_selection" in row:
            required |= {"preparation", "prompt"}
            selection = promotion.fields(row["host_selection"], {"preparation", "prompt"}, "HOST_PREPARATION_INVALID")
            yield from selection.values()
        elif row["binding_id"].startswith("claude-code-"):
            required.add("loader_debug_log")
        promotion.fields(files, required, "PROBE_FILES_INVALID")
        yield from files.values()


def write_new_tree(root, files):
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name, raw in sorted(files.items()):
            parts = Path(promotion.path_name(name)).parts
            parent_fd = os.dup(root_fd)
            try:
                for part in parts[:-1]:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=parent_fd)
                    except FileExistsError:
                        pass
                    next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                    os.close(parent_fd)
                    parent_fd = next_fd
                descriptor = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o600, dir_fd=parent_fd)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(raw)
            finally:
                os.close(parent_fd)
    finally:
        os.close(root_fd)


def remove_owned_tree(root, names):
    """Remove only the staged files and directories this assembly created."""
    if not root.exists():
        return
    directories = {Path(".")}
    for name in names:
        directories.update(Path(name).parents)
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in names:
            parts = Path(name).parts
            fd = os.dup(directory_fd)
            try:
                for part in parts[:-1]:
                    next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = next_fd
                try:
                    os.unlink(parts[-1], dir_fd=fd)
                except FileNotFoundError:
                    pass
            finally:
                os.close(fd)
        for directory in sorted(directories - {Path(".")}, key=lambda path: len(path.parts), reverse=True):
            parts = directory.parts
            fd = os.dup(directory_fd)
            try:
                for part in parts[:-1]:
                    next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = next_fd
                try:
                    os.rmdir(parts[-1], dir_fd=fd)
                except FileNotFoundError:
                    pass
            finally:
                os.close(fd)
    finally:
        os.close(directory_fd)
    root.rmdir()


def assemble(candidate_root, release_binding_file, evidence_root, manifest_file,
             private_output, public_output, *, require_all_current_bindings=True):
    candidate_root, evidence_root, release_binding_file, manifest_file, private_output, public_output = map(
        safe_path, (candidate_root, evidence_root, release_binding_file, manifest_file, private_output, public_output))
    for root in (candidate_root, evidence_root):
        if not root.is_dir():
            reject("SOURCE_ROOT_INVALID")
    for output in (private_output, public_output):
        if output.exists() or not output.parent.is_dir():
            reject("OUTPUT_EXISTS_OR_PARENT_MISSING")
        for source in (candidate_root, evidence_root, release_binding_file, manifest_file):
            if output.is_relative_to(source) or source.is_relative_to(output):
                reject("OUTPUT_SOURCE_OVERLAP")
    if private_output.is_relative_to(public_output) or public_output.is_relative_to(private_output):
        reject("OUTPUT_OVERLAP")
    snapshot = Snapshot()
    expected = promotion.decode(snapshot.read(release_binding_file))
    manifest = promotion.fields(promotion.decode(snapshot.read(manifest_file)),
                                {"schema_version", "candidate_release_binding", "binding_evidence"}, "MANIFEST_INVALID")
    if manifest["schema_version"] not in {MANIFEST_SCHEMA, ROLE_MANIFEST_SCHEMA} or manifest["candidate_release_binding"] != expected:
        reject("MANIFEST_BINDING_MISMATCH")
    role_protocol = manifest["schema_version"] == ROLE_MANIFEST_SCHEMA
    declaration = promotion.decode(snapshot.read(candidate_root / promotion.INVENTORY_PATH))
    if not isinstance(declaration, dict) or not isinstance(declaration.get("paths"), list):
        reject("INVENTORY_INVALID")
    names = [promotion.path_name(name) for name in declaration["paths"]]
    if set(names) & {promotion.PROOF_PATH, promotion.ARCHIVE_PATH, RECEIPT_PATH}:
        reject("RESERVED_PACKAGE_PATH")
    package = {name: snapshot.read(candidate_root / name) for name in names}
    package[promotion.INVENTORY_PATH] = snapshot.read(candidate_root / promotion.INVENTORY_PATH)
    if promotion.release_binding(package.__getitem__) != expected:
        reject("CANDIDATE_BINDING_MISMATCH")
    if promotion.required_protocol(package.__getitem__) is not None and not role_protocol:
        reject("ROLE_PROTOCOL_REQUIRED")
    archived = package[promotion.REGISTRY_PATH]
    candidate = promotion.registry(archived, "candidate")
    if require_all_current_bindings and {row["binding_id"] for row in candidate["bindings"]} != set(promotion.BINDINGS):
        reject("EXACT_EIGHT_BINDINGS_REQUIRED")
    rows = manifest["binding_evidence"]
    if (not isinstance(rows, list) or not rows or any(not isinstance(row, dict) or not isinstance(row.get("binding_id"), str) for row in rows)):
        reject("EVIDENCE_INVALID")
    binding_ids = sorted(row["binding_id"] for row in rows)
    if require_all_current_bindings and binding_ids != sorted(promotion.BINDINGS):
        reject("EXACT_EIGHT_EVIDENCE_REQUIRED")
    rows = sorted(rows, key=lambda row: row["binding_id"])
    if any(("qualification_protocol" in row) != role_protocol for row in rows):
        reject("MIXED_PROTOCOL_VERSIONS")
    protocols = {row["binding_id"]: row["qualification_protocol"] for row in rows} if role_protocol else None
    private = dict(package)
    private[promotion.REGISTRY_PATH] = promotion.promote_registry(archived, binding_ids,
                                                                qualification_protocols=protocols)
    private[promotion.ARCHIVE_PATH] = archived
    for reference in references(rows):
        promotion.fields(reference, {"path", "sha256"}, "REFERENCE_INVALID")
        name = promotion.path_name(reference["path"])
        if name in package or name in {promotion.PROOF_PATH, promotion.ARCHIVE_PATH, RECEIPT_PATH}:
            reject("REFERENCE_COLLISION")
        raw = snapshot.read(evidence_root / name)
        if promotion.sha256(raw) != promotion.hash_value(reference["sha256"]):
            reject("EVIDENCE_HASH_MISMATCH")
        private[name] = raw
    promoted_binding = promotion.release_binding(private.__getitem__)
    proof = {"schema_version": promotion.ROLE_SCHEMA if role_protocol else promotion.SCHEMA, "evidence_assurance": "structural_only",
             "candidate_registry": {"path": promotion.ARCHIVE_PATH, "sha256": promotion.sha256(archived)},
             "candidate_release_binding": expected, "promoted_release_binding": promoted_binding,
             "binding_evidence": rows}
    if role_protocol:
        proof["qualification_protocol_version"] = promotion.ROLE_PROTOCOL
    private[promotion.PROOF_PATH] = promotion.canonical(proof) + b"\n"
    package_pin = promoted_binding["behavioral_identity"]["behavioral_sha256"]
    private_pin = promotion.sha256(private[promotion.PROOF_PATH])
    promotion.verify_promotion_bytes(private, expected_package_sha256=package_pin,
                                     expected_proof_sha256=private_pin, candidate_root=candidate_root)
    public = {name: private[name] for name in package}
    public.update(promotion.export_public_promotion_bytes(private, expected_package_sha256=package_pin,
                                                          expected_proof_sha256=private_pin, candidate_root=candidate_root))
    public_pin = promotion.sha256(public[promotion.PROOF_PATH])
    promotion.verify_promotion_bytes(public, expected_package_sha256=package_pin,
                                     expected_proof_sha256=public_pin, candidate_root=candidate_root)
    snapshot.check()
    receipt = {"schema_version": "agent-council.promotion-assembly/v1", "status": "complete",
               "binding_ids": binding_ids, "release_gate_complete": require_all_current_bindings,
               "candidate_release_binding": expected,
               "promoted_release_binding": promoted_binding, "private_proof_sha256": private_pin,
               "public_proof_sha256": public_pin, "qualification_claimed": False,
               "public_paths": sorted(public),
               "interpretation": "Verified structural promotion and public projection. Native authenticity and release behavior require independent acceptance."}
    staged_private = Path(tempfile.mkdtemp(prefix=".assembly-private-", dir=private_output.parent))
    staged_public = None
    published_private = False
    try:
        staged_public = Path(tempfile.mkdtemp(prefix=".assembly-public-", dir=public_output.parent))
        write_new_tree(staged_private, private)
        write_new_tree(staged_public, public)
        for root, pin in ((staged_private, private_pin), (staged_public, public_pin)):
            promotion.verify_promotion(root, expected_package_sha256=package_pin,
                                       expected_proof_sha256=pin, candidate_root=candidate_root)
        snapshot.check()
        descriptor = os.open(staged_private / RECEIPT_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(promotion.canonical(receipt) + b"\n")
        os.rename(staged_private, private_output)
        published_private = True
        os.rename(staged_public, public_output)
    except BaseException:
        if published_private:
            os.rename(private_output, staged_private)
        remove_owned_tree(staged_private, list(private) + [RECEIPT_PATH])
        if staged_public is not None:
            remove_owned_tree(staged_public, list(public))
        raise
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate-root", "release-binding", "evidence-root", "evidence-manifest", "private-output", "public-output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = assemble(args.candidate_root, args.release_binding, args.evidence_root,
                           args.evidence_manifest, args.private_output, args.public_output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, "Promotion assembly refused: " + str(exc) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
