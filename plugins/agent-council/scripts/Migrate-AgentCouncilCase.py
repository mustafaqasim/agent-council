#!/usr/bin/env python3
"""Create a fresh governed successor against the installed registry.

The source remains an immutable historical record. Provenance is informational,
not transferable approval, qualification, dispatch, or test evidence.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any


CORE_PATH = Path(__file__).resolve().parent / "core/agent-council/0.2.0/Invoke-AgentCouncil.py"
_SPEC = importlib.util.spec_from_file_location("agent_council_migration_core", CORE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
core = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(core)


def _publish_exclusive(staged_case: Path, destination: Path) -> None:
    """Atomically rename without replacing even a concurrently created empty directory.

    Refuse unsupported systems/filesystems rather than fall back to a replacing
    POSIX rename. macOS and Linux expose their exclusive flags through libc;
    Windows os.rename already refuses an existing destination.
    """
    try:
        if os.name == "nt":
            os.rename(staged_case, destination)
            return
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform == "darwin":
            rename = libc.renamex_np
            rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
            args = (os.fsencode(staged_case), os.fsencode(destination), 0x00000004)  # RENAME_EXCL
        elif sys.platform.startswith("linux"):
            rename = libc.renameat2
            rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            args = (-100, os.fsencode(staged_case), -100, os.fsencode(destination), 1)  # RENAME_NOREPLACE
        else:
            raise core.AuthoringError("MIGRATION_ATOMIC_PUBLICATION_UNAVAILABLE")
        rename.restype = ctypes.c_int
        if rename(*args) != 0:
            number = ctypes.get_errno()
            raise OSError(number, os.strerror(number), str(destination))
    except AttributeError as exc:
        raise core.AuthoringError("MIGRATION_ATOMIC_PUBLICATION_UNAVAILABLE") from exc
    except OSError as exc:
        if exc.errno in {errno.EEXIST, errno.ENOTEMPTY}:
            raise core.AuthoringError("DUPLICATE_EVENT_REFUSED") from exc
        if exc.errno in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
            raise core.AuthoringError("MIGRATION_ATOMIC_PUBLICATION_UNAVAILABLE") from exc
        raise


def _snapshot(root: Path) -> dict[str, str]:
    """Hash source bytes without acquiring a write lock or creating sidecars."""
    core._safe_case_tree(root)
    result = {}
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise core.AuthoringError("MIGRATION_SOURCE_FILE_INVALID")
        result[path.relative_to(root).as_posix()] = core._file_sha(path)
    return result


def _source_state(root: Path, project_root: Path) -> dict[str, Any]:
    if core._pending_path(root).exists():
        raise core.AuthoringError("MIGRATION_SOURCE_RECOVERY_REQUIRED")
    state = core._read_local_case(root)
    if state.get("case_root") != str(root) or state.get("project_root") != str(project_root):
        raise core.AuthoringError("MIGRATION_SOURCE_PATH_MISMATCH")
    core._require_no_pending_compound_engineering_handoff(state)
    identity = core._local_identity(state)
    candidate = state["engineering_candidate"]
    if (not core._identity(identity) or not core._registry_valid(state["registry"], identity)
            or core._candidate_input_problem(candidate)
            or candidate.get("policy_sha256") != identity["policy_bundle_sha256"]
            or candidate.get("candidate_sha256") != core._candidate_digest(candidate)
            or candidate.get("candidate_id") != f"candidate-{core._candidate_digest(candidate)[:24]}"):
        raise core.AuthoringError("MIGRATION_SOURCE_IDENTITY_INVALID")
    pins = state["policy_bundle"].get("artifact_pins")
    if not isinstance(pins, dict) or not pins:
        raise core.AuthoringError("PINNED_ARTIFACT_MISSING")
    material = core._artifact_snapshot(root / "pinned", pins, pins)
    registry_path = f"standards/agent-model-registry.{identity['registry_version']}.yaml"
    if registry_path not in material or core._decode_json(material[registry_path].decode("utf-8")) != state["registry"]:
        raise core.AuthoringError("MIGRATION_SOURCE_IDENTITY_INVALID")
    policy = {key: value for key, value in pins.items() if key.startswith("standards/") or key.startswith("skills/")}
    if core._digest(policy) != identity["policy_bundle_sha256"]:
        raise core.AuthoringError("MIGRATION_SOURCE_IDENTITY_INVALID")
    previous = None
    seen = set()
    if not state["events"]:
        raise core.AuthoringError("MIGRATION_SOURCE_HISTORY_INVALID")
    for event in state["events"]:
        if (not core._event_valid(event, {"case_id": state["case_id"], "identity": identity})
                or core._authoring_payload_problem(event.get("record_type"), event.get("payload"))
                or event["payload"].get("previous_event_sha256") != previous
                or event["event_id"] in seen):
            raise core.AuthoringError("MIGRATION_SOURCE_HISTORY_INVALID")
        if (root / "events" / f"{event['event_id']}.json").read_bytes() != core._canonical(event) + b"\n":
            raise core.AuthoringError("MIGRATION_SOURCE_HISTORY_INVALID")
        previous = event["event_sha256"]
        seen.add(event["event_id"])
    document = dict(state, identity=identity)
    reduced, issue = core.reduce_events(document)
    if issue:
        raise core.AuthoringError(issue)
    _, issue = core._activation_and_route(document, reduced)
    if issue:
        raise core.AuthoringError(issue)
    active_intake = next(event for event in reduced["active"].values()
                         if event["record_type"] == "case" and event["cycle_id"] == state["cycle_id"]
                         and event["candidate_id"] == candidate["candidate_id"])
    if any(active_intake["payload"].get(key) != state.get(key)
           for key in ("route", "activation_class", "case_kind")):
        raise core.AuthoringError("MIGRATION_SOURCE_IDENTITY_INVALID")
    return state


def migrate_case(source_root: Path, destination_root: Path, project_root: Path,
                 case_id: str, candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    """Publish a complete new case plus provenance; never mutate the source."""
    project_root = project_root.resolve(strict=True)
    source = core._confined_case_root(source_root, project_root)
    destination = core._confined_case_root(destination_root, project_root)
    if source == destination or source in destination.parents or destination in source.parents:
        raise core.AuthoringError("MIGRATION_CASE_ROOT_OVERLAP")
    if destination.exists() or destination.is_symlink():
        raise core.AuthoringError("DUPLICATE_EVENT_REFUSED")
    before = _snapshot(source)
    state = _source_state(source, project_root)
    if case_id == state["case_id"]:
        raise core.AuthoringError("MIGRATION_NEW_CASE_ID_REQUIRED")
    if candidate is None:
        candidate = {key: state["engineering_candidate"][key] for key in core._CANDIDATE_HASH_FIELDS}
    else:
        issue = core._candidate_input_problem(candidate)
        if issue:
            raise core.AuthoringError(issue)
        candidate = {key: candidate[key] for key in core._CANDIDATE_HASH_FIELDS}
    # Build outside the public destination, then publish the complete directory.
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".agent-council-migration-", dir=destination.parent))
    try:
        staged_case = staging / "case"
        core.init_case(staged_case, project_root, case_id, state["route"], candidate,
                       state["activation_class"], state["case_kind"])
        successor = core._read_local_case(staged_case)
        successor["case_root"] = str(destination)
        successor_bytes = core._canonical(successor) + b"\n"
        core._write_atomic(staged_case / "case.json", successor_bytes)
        provenance = {
            "schema_version": "agent-council.case-migration/v1",
            "recorded_at": core._utc_now(),
            "assurance": "structural_only",
            "authority_transferred": False,
            "source": {
                "case_root": str(source), "identity": core._local_identity(state),
                "cycle_id": state["cycle_id"], "candidate_id": state["engineering_candidate"]["candidate_id"],
                "candidate_sha256": state["engineering_candidate"]["candidate_sha256"],
                "event_count": len(state["events"]), "last_event_sha256": state["events"][-1]["event_sha256"],
                "file_sha256": before,
            },
            "successor": {
                "case_root": str(destination), "identity": core._local_identity(successor),
                "candidate_id": successor["engineering_candidate"]["candidate_id"],
                "candidate_sha256": successor["engineering_candidate"]["candidate_sha256"],
                "initial_case_sha256": hashlib.sha256(successor_bytes).hexdigest(),
            },
        }
        provenance["provenance_sha256"] = core._digest(provenance)
        core._write_exclusive(staged_case / "migration-provenance.json", core._canonical(provenance) + b"\n")
        if _snapshot(source) != before:
            raise core.AuthoringError("MIGRATION_SOURCE_CHANGED")
        # Recheck the path after preparing pins, in case a parent was replaced.
        if core._confined_case_root(destination, project_root) != destination:
            raise core.AuthoringError("CASE_ROOT_SYMLINK_REFUSED")
        if destination.exists() or destination.is_symlink():
            raise core.AuthoringError("DUPLICATE_EVENT_REFUSED")
        _publish_exclusive(staged_case, destination)
        core._sync_parent(destination)
        return {"status": "accepted", "code": "CASE_MIGRATED", "source_case_id": state["case_id"],
                "case_id": successor["case_id"], "case_root": str(destination),
                "registry_sha256": successor["registry"]["registry_sha256"],
                "provenance_sha256": provenance["provenance_sha256"],
                "authority_transferred": False, "fresh_evidence_required": True}
    finally:
        shutil.rmtree(staging)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-case-root", type=Path, required=True)
    parser.add_argument("--case-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--candidate-json", help="optional new engineering input hashes as JSON")
    args = parser.parse_args(argv)
    try:
        candidate = core._candidate_json_argument(args.candidate_json) if args.candidate_json is not None else None
        result = migrate_case(args.source_case_root, args.case_root, args.project_root, args.case_id, candidate)
    except core.AuthoringError as exc:
        result = {"status": "refused", "code": exc.code}
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        result = {"status": "refused", "code": "MIGRATION_SOURCE_OR_DESTINATION_INVALID"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
