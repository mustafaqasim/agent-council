#!/usr/bin/env python3
"""Check-only Agent Council update notices for Codex hooks."""
from __future__ import annotations

import contextlib
import functools
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ID = "agent-council@agent-council"
MARKETPLACE_URL = "https://raw.githubusercontent.com/mustafaqasim/agent-council/main/.claude-plugin/marketplace.json"
MARKETPLACE_SOURCE = "https://github.com/mustafaqasim/agent-council.git"
DAY = 24 * 60 * 60
MAX_BYTES = 128 * 1024
NETWORK_TIMEOUT = 4
CLI_TIMEOUT = 12
SETTINGS_FILE = "updates-settings.json"
STATE_FILE = "updates-state.json"
LOCK_FILE = "updates.lock"
SETTINGS_LOCK_FILE = "updates-settings.lock"
OWNED_DATA_FILES = (SETTINGS_FILE, STATE_FILE)
HANDOFF_ARGV = ("codex", "plugin", "marketplace", "upgrade", "agent-council", "--json")
HANDOFF_COMMAND = " ".join(HANDOFF_ARGV)
INSTALL_ARGV = ("codex", "plugin", "add", "agent-council@agent-council", "--json")
INSTALL_COMMAND = " ".join(INSTALL_ARGV)
COMMANDS = {
    "agent-council auto-update on": "auto-on",
    "agent-council auto-update off": "auto-off",
    "agent-council update now": "now",
    "agent-council update-check on": "check-on",
    "agent-council update-check off": "check-off",
    "agent-council update status": "status",
    "agent-council update cleanup": "cleanup",
}
REASONS = {
    "network": "the marketplace could not be reached within the update-check limit",
    "marketplace": "the marketplace response was invalid or did not identify Agent Council",
    "local": "the loaded plugin metadata was invalid",
    "storage": "private updater state could not be read or written safely",
    "cli": "the host-managed CLI handoff was unavailable",
    "unknown": "an unexpected updater error occurred",
}


class UpdateError(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason if reason in REASONS else "unknown"


@functools.total_ordering
class SemVer:
    pattern = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?")

    def __init__(self, value: str):
        if not isinstance(value, str) or len(value) > 256:
            raise ValueError("Invalid version")
        match = self.pattern.fullmatch(value)
        if match is None:
            raise ValueError("Invalid version")
        self.core = tuple(int(part) for part in match.group(1, 2, 3))
        self.pre = tuple(match.group(4).split(".")) if match.group(4) else ()
        if any(part.isascii() and part.isdigit() and len(part) > 1 and part[0] == "0" for part in self.pre):
            raise ValueError("Invalid numeric prerelease")

    def __eq__(self, other):
        if not isinstance(other, SemVer):
            return NotImplemented
        return self.core == other.core and self.pre == other.pre

    def __lt__(self, other):
        if not isinstance(other, SemVer):
            return NotImplemented
        if self.core != other.core:
            return self.core < other.core
        if not self.pre or not other.pre:
            return bool(self.pre) and not other.pre
        for left, right in zip(self.pre, other.pre):
            if left == right:
                continue
            if left.isdigit() and right.isdigit():
                return int(left) < int(right)
            if left.isdigit() != right.isdigit():
                return left.isdigit()
            return left < right
        return len(self.pre) < len(other.pre)


def decode_object(raw: bytes):
    if len(raw) > MAX_BYTES:
        raise ValueError("Response too large")
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError("Non-finite JSON value")
    value = json.loads(raw, object_pairs_hook=unique_keys, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("Expected an object")
    return value


def read_object(path: Path):
    try:
        with path.open("rb") as stream:
            return decode_object(stream.read(MAX_BYTES + 1))
    except (OSError, ValueError, UnicodeError):
        return {}


def atomic_write(path: Path, value: dict):
    fd, temporary = tempfile.mkstemp(prefix=".updates-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


@contextlib.contextmanager
def update_lock(path: Path):
    """Acquire a non-blocking, private advisory lock without unlinking it."""
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    acquired = False
    try:
        os.fchmod(fd, 0o600)
        try:
            if os.name == "nt":
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except (BlockingIOError, PermissionError):
            pass
        yield acquired
    finally:
        os.close(fd)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise UpdateError("marketplace")


def download_marketplace():
    opener = urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(MARKETPLACE_URL, headers={"Accept": "application/json"})
    with opener.open(request, timeout=NETWORK_TIMEOUT) as response:
        return response.read(MAX_BYTES + 1)


def fetch_version():
    """Bound DNS, connection setup, and read time as one network operation."""
    output, errors = [], []
    def download():
        try:
            output.append(download_marketplace())
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=download, daemon=True)
    worker.start()
    worker.join(NETWORK_TIMEOUT)
    if worker.is_alive() or errors or not output:
        raise UpdateError("network")
    try:
        document = decode_object(output[0])
        if document.get("name") != "agent-council" or not isinstance(document.get("plugins"), list):
            raise ValueError("identity")
        matches = [item for item in document["plugins"] if isinstance(item, dict) and item.get("name") == "agent-council"]
        if len(matches) != 1 or matches[0].get("source") != "./plugins/agent-council":
            raise ValueError("identity")
        version = matches[0].get("version")
        SemVer(version)
        metadata = document.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("version") != version:
            raise ValueError("metadata")
        return version
    except (TypeError, ValueError, UnicodeError) as exc:
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError("marketplace") from exc


def _remaining(deadline):
    return max(0.0, deadline - time.monotonic())


def _terminate_process_group(process, deadline):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        remaining = _remaining(deadline)
        if remaining:
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=remaining)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            remaining = _remaining(deadline)
            if remaining:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=remaining)
    except (AttributeError, OSError, subprocess.SubprocessError) as exc:
        raise UpdateError("cli") from exc


def run_cli(argv, timeout=CLI_TIMEOUT):
    """Run a fixed host command with a bounded POSIX process-tree lifetime."""
    if os.name == "nt" or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise UpdateError("cli")
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(argv, shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    output, errors = [], []
    def read():
        try:
            output.append(process.stdout.read(MAX_BYTES + 1))
        except Exception as exc:
            errors.append(exc)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        reader.join(_remaining(deadline))
        if reader.is_alive() or errors or not output or len(output[0]) > MAX_BYTES:
            raise UpdateError("cli")
        remaining = _remaining(deadline)
        if remaining <= 0 or process.wait(timeout=remaining) != 0:
            raise UpdateError("cli")
        return output[0]
    except subprocess.TimeoutExpired as exc:
        raise UpdateError("cli") from exc
    finally:
        try:
            _terminate_process_group(process, deadline)
        finally:
            reader.join(_remaining(deadline))
            if not reader.is_alive():
                process.stdout.close()


def resolve_codex():
    candidate = shutil.which("codex")
    if not candidate:
        raise UpdateError("cli")
    executable = Path(candidate).resolve()
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise UpdateError("cli")
    return str(executable)


def verify_installation(raw, version):
    """Host callers may verify an install, but hooks never call a CLI."""
    installed = decode_object(raw).get("installed")
    if not isinstance(installed, list):
        raise ValueError("Missing installation list")
    matches = [item for item in installed if isinstance(item, dict) and item.get("pluginId") == PLUGIN_ID]
    if len(matches) != 1:
        raise ValueError("Ambiguous installation identity")
    plugin = matches[0]
    if (plugin.get("name") != "agent-council" or plugin.get("marketplaceName") != "agent-council"
            or plugin.get("installed") is not True or plugin.get("enabled") is not True
            or plugin.get("version") != version
            or plugin.get("marketplaceSource") != {"sourceType": "git", "source": MARKETPLACE_SOURCE}):
        raise ValueError("Installation verification failed")


def local_version():
    try:
        local = read_object(ROOT / ".codex-plugin" / "plugin.json")
        if local.get("name") != "agent-council":
            raise ValueError("identity")
        version = local.get("version")
        SemVer(version)
        return version
    except (TypeError, ValueError) as exc:
        raise UpdateError("local") from exc


def settings_value(data: Path):
    """Only literal false disables automatic checks. Legacy auto_update is inert."""
    settings = read_object(data / SETTINGS_FILE)
    return {"update_check": settings.get("update_check") is not False, "auto_update": False}


def write_settings(data: Path, **changes):
    """Settings locking is independent of the bounded network-check lock."""
    with update_lock(data / SETTINGS_LOCK_FILE) as acquired:
        if not acquired:
            raise UpdateError("storage")
        settings = settings_value(data)
        settings.update(changes)
        settings["auto_update"] = False
        atomic_write(data / SETTINGS_FILE, settings)


def notice(event, message):
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "Visibly tell the user: " + message + " Continue normal Agent Council routing."}}


def codex_data(environ):
    if not environ.get("PLUGIN_ROOT") or not environ.get("PLUGIN_DATA"):
        return None
    supplied, data = Path(environ["PLUGIN_ROOT"]), Path(environ["PLUGIN_DATA"])
    if not supplied.is_absolute() or supplied.resolve() != ROOT or not data.is_absolute():
        return None
    data = data.resolve()
    return None if data == ROOT or ROOT in data.parents else data


def failure_reason(exc):
    return exc.reason if isinstance(exc, UpdateError) else "unknown"


def status_notice(event, data):
    """Read-only: no directory, lock, state, or network writes occur here."""
    version = local_version()
    state = read_object(data / STATE_FILE)
    status = state.get("status") if isinstance(state.get("status"), str) else "no recorded check"
    checked = state.get("checked_version")
    if checked != version:
        detail = "No check is recorded for this loaded version."
    elif status == "available" and isinstance(state.get("available_version"), str):
        detail = f"{state['available_version']} is available."
    elif status == "failed":
        detail = REASONS.get(state.get("reason"), REASONS["unknown"])
    else:
        detail = f"Last check status: {status}."
    return notice(event, f"Agent Council update status, loaded version {version}. {detail}")


def cleanup(data):
    """Remove only known updater settings and state after both locks are held."""
    with update_lock(data / SETTINGS_LOCK_FILE) as settings_acquired:
        if not settings_acquired:
            return False
        with update_lock(data / LOCK_FILE) as check_acquired:
            if not check_acquired:
                return False
            for name in OWNED_DATA_FILES:
                with contextlib.suppress(FileNotFoundError):
                    (data / name).unlink()
            return True


def check_for_update(event, data, manual=False):
    """Network check only. No code path here invokes a CLI or changes plugin files."""
    current = local_version()
    with update_lock(data / LOCK_FILE) as acquired:
        if not acquired:
            return notice(event, "An Agent Council update check is already running. This task continues.") if manual else None
        if not manual and not settings_value(data)["update_check"]:
            return None
        state, now = read_object(data / STATE_FILE), time.time()
        previous = state.get("last_check_at")
        if not manual and state.get("checked_version") == current and type(previous) in (int, float) and math.isfinite(previous):
            if previous > now:
                atomic_write(data / STATE_FILE, {"last_check_at": now, "status": state.get("status", "unknown"), "checked_version": current})
                return None
            if now - previous < DAY:
                return None
        state = {"last_check_at": now, "status": "checking", "checked_version": current}
        atomic_write(data / STATE_FILE, state)
        try:
            target = fetch_version()
            if SemVer(target) <= SemVer(current):
                state.update(status="current")
                result = notice(event, "Agent Council is up to date.") if manual else None
            else:
                state.update(status="available", available_version=target)
                if manual:
                    result = notice(event, f"Agent Council {target} is available. Run these host-managed CLI commands in order: `{HANDOFF_COMMAND}` then `{INSTALL_COMMAND}`. This hook did not install or modify the plugin.")
                else:
                    result = notice(event, f"Agent Council {current} is installed and {target} is available. Automatic installation is unavailable. Use the exact command `agent-council update now` for a fresh check and host-managed handoff.")
        except Exception as exc:
            reason = failure_reason(exc)
            state.update(status="failed", reason=reason)
            result = notice(event, f"The Agent Council update check could not be completed because {REASONS[reason]}. This task continues normally.") if manual else None
        atomic_write(data / STATE_FILE, state)
        return result


def handle_action(event, action, data):
    if action == "status":
        try:
            return status_notice(event, data)
        except Exception:
            return notice(event, "Agent Council update status is unavailable because the loaded plugin metadata could not be read safely.")
    if action == "auto-on":
        return notice(event, "Automatic installation is unavailable. No executable update consent was saved. Use `agent-council update now` for a fresh check and the host-managed CLI handoff.")
    try:
        data.mkdir(mode=0o700, parents=True, exist_ok=True)
        if action == "auto-off":
            write_settings(data, auto_update=False)
            return notice(event, "Automatic installation remains disabled. This opt-out was saved immediately and does not wait for an update check.")
        if action == "check-on":
            write_settings(data, update_check=True)
            return notice(event, "Automatic daily update checks are enabled. Hooks will only notify, never install.")
        if action == "check-off":
            write_settings(data, update_check=False)
            return notice(event, "Automatic daily update checks are disabled. Hooks will make no automatic marketplace requests; `agent-council update now` still checks on demand.")
        if action == "cleanup":
            return notice(event, "Updater-owned settings and check state were removed. No plugin files were changed.") if cleanup(data) else notice(event, "Updater cleanup could not safely acquire its private locks. No files were removed.")
        return check_for_update(event, data, manual=True)
    except Exception:
        return notice(event, "Agent Council could not safely access its private updater settings or state. This task continues normally.")


def handle_hook(event, payload, environ):
    if event not in ("SessionStart", "UserPromptSubmit"):
        return None
    data = codex_data(environ)
    if data is None:
        return None
    prompt = payload.get("prompt") if isinstance(payload.get("prompt"), str) else None
    action = COMMANDS.get(prompt)
    if event == "UserPromptSubmit":
        if action is not None:
            return handle_action(event, action, data)
        if prompt is not None and prompt.lower().startswith("agent-council"):
            return notice(event, "That is not an executable updater command. Use an exact command: `agent-council update now`, `agent-council update-check on`, `agent-council update-check off`, `agent-council update status`, `agent-council update cleanup`, or `agent-council auto-update off`.")
        return None
    try:
        if not settings_value(data)["update_check"]:
            return None
        data.mkdir(mode=0o700, parents=True, exist_ok=True)
        return check_for_update(event, data, manual=False)
    except Exception:
        return None


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    event = args[2] if len(args) == 3 and args[:2] == ["hook", "--event"] else (args[0] if len(args) == 1 else "")
    try:
        if codex_data(os.environ) is None:
            return 0
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        payload = decode_object(raw) if raw.strip() else {}
        result = handle_hook(event, payload, os.environ)
        if result is not None:
            print(json.dumps(result))
    except Exception:
        if event in ("SessionStart", "UserPromptSubmit"):
            print(json.dumps(notice(event, "Agent Council skipped an unavailable update check. This task continues normally.")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
