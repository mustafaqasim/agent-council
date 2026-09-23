#!/usr/bin/env python3
"""Codex hooks for consent-controlled updates; all durable data stays in PLUGIN_DATA."""
from __future__ import annotations

import contextlib
import functools
import json
import math
import os
from pathlib import Path
import re
import shutil
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
INSTALL_TIMEOUT = 42
HOOK_TIMEOUT = 60
SETTINGS_FILE = "updates-settings.json"
STATE_FILE = "updates-state.json"
LOCK_FILE = "updates.lock"
COMMANDS = {
    "agent-council auto-update on": "on",
    "agent-council auto-update off": "off",
    "agent-council update now": "now",
}
UPGRADE_ARGV = ["codex", "plugin", "marketplace", "upgrade", "agent-council", "--json"]
ADD_ARGV = ["codex", "plugin", "add", PLUGIN_ID, "--json"]
LIST_ARGV = ["codex", "plugin", "list", "--json"]


@functools.total_ordering
class SemVer:
    """SemVer 2.0 precedence, including prereleases and ignored build metadata."""

    pattern = re.compile(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
        r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
        r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    )

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
    """OS-owned locks release on process death; never unlink an active lock inode."""
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
        # Closing the descriptor releases the kernel lock, even after exceptions.
        os.close(fd)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Marketplace redirects are not allowed")


def download_marketplace():
    opener = urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(MARKETPLACE_URL, headers={"Accept": "application/json"})
    with opener.open(request, timeout=NETWORK_TIMEOUT) as response:
        return response.read(MAX_BYTES + 1)


def fetch_version():
    # urllib's socket timeout alone permits a slow trickle to extend a read.
    # A daemon worker also bounds DNS, connection setup, and the entire read.
    output = []
    errors = []

    def download():
        try:
            output.append(download_marketplace())
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=download, daemon=True)
    worker.start()
    worker.join(NETWORK_TIMEOUT)
    if worker.is_alive() or errors or not output:
        raise ValueError("Marketplace request failed or timed out")
    document = decode_object(output[0])
    if document.get("name") != "agent-council" or not isinstance(document.get("plugins"), list):
        raise ValueError("Marketplace identity mismatch")
    matches = [item for item in document["plugins"] if isinstance(item, dict) and item.get("name") == "agent-council"]
    if len(matches) != 1 or matches[0].get("source") != "./plugins/agent-council":
        raise ValueError("Plugin identity mismatch")
    version = matches[0].get("version")
    SemVer(version)
    metadata = document.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("version") != version:
        raise ValueError("Marketplace version mismatch")
    return version


def run_cli(argv, timeout=CLI_TIMEOUT):
    """Bound memory and wall time, without interpreting CLI output as instructions."""
    process = subprocess.Popen(argv, shell=False, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = []
    errors = []

    def read():
        try:
            output.append(process.stdout.read(MAX_BYTES + 1))
        except Exception as exc:
            errors.append(exc)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    try:
        reader.join(timeout)
        if reader.is_alive() or errors or not output or len(output[0]) > MAX_BYTES:
            raise ValueError("CLI timeout or output limit")
        remaining = deadline - time.monotonic()
        if remaining <= 0 or process.wait(timeout=remaining) != 0:
            raise ValueError("CLI failed")
        return output[0]
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)
        reader.join(2)
        if not reader.is_alive():
            process.stdout.close()


def resolve_codex():
    """Resolve the CLI once to an absolute executable path before any update action."""
    candidate = shutil.which("codex")
    if not candidate:
        raise ValueError("Codex CLI not found")
    executable = Path(candidate).resolve()
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("Codex CLI is not an executable file")
    return str(executable)


def verify_installation(raw, version):
    installed = decode_object(raw).get("installed")
    if not isinstance(installed, list):
        raise ValueError("Missing installation list")
    matches = [item for item in installed if isinstance(item, dict) and item.get("pluginId") == PLUGIN_ID]
    if len(matches) != 1:
        raise ValueError("Ambiguous installation identity")
    plugin = matches[0]
    if (plugin.get("name") != "agent-council" or plugin.get("marketplaceName") != "agent-council"
            or plugin.get("installed") is not True or plugin.get("version") != version
            or plugin.get("marketplaceSource") != {"sourceType": "git", "source": MARKETPLACE_SOURCE}):
        raise ValueError("Installation verification failed")


def install_version(current, target):
    executable = resolve_codex()
    list_argv = [executable, *LIST_ARGV[1:]]
    deadline = time.monotonic() + INSTALL_TIMEOUT

    def bounded(argv):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Aggregate installation timeout")
        return run_cli(argv, timeout=min(CLI_TIMEOUT, remaining))

    # Confirm that the installed marketplace alias still points to the fixed
    # public repository before asking Codex to upgrade or install anything.
    verify_installation(bounded(list_argv), current)
    bounded([executable, *UPGRADE_ARGV[1:]])
    bounded([executable, *ADD_ARGV[1:]])
    verify_installation(bounded(list_argv), target)


def notice(event, message):
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext":
            "Visibly tell the user: " + message + " Continue normal Agent Council routing."}}


def codex_data(environ):
    # PLUGIN_ROOT is Codex's documented marker. Codex may also supply the Claude
    # compatibility marker; CLAUDE_PLUGIN_ROOT or CODEX_HOME alone proves nothing.
    if not environ.get("PLUGIN_ROOT") or not environ.get("PLUGIN_DATA"):
        return None
    supplied = Path(environ["PLUGIN_ROOT"])
    data = Path(environ["PLUGIN_DATA"])
    if not supplied.is_absolute() or supplied.resolve() != ROOT or not data.is_absolute():
        return None
    data = data.resolve()
    if data == ROOT or ROOT in data.parents:
        return None
    return data


def handle_hook(event, payload, environ):
    if event not in ("SessionStart", "UserPromptSubmit"):
        return None
    data = codex_data(environ)
    if data is None:
        return None
    action = COMMANDS.get(payload.get("prompt")) if isinstance(payload.get("prompt"), str) else None
    if event == "UserPromptSubmit" and action is None:
        return None
    try:
        data.mkdir(mode=0o700, parents=True, exist_ok=True)
        with update_lock(data / LOCK_FILE) as acquired:
            if not acquired:
                return notice(event, "An Agent Council update check is already running; this task continues.") if action else None
            settings = read_object(data / SETTINGS_FILE)
            if action in ("on", "off"):
                atomic_write(data / SETTINGS_FILE, {"auto_update": action == "on"})
                message = ("Agent Council automatic updates are enabled. Daily task-start checks may install updates; changes apply to the next task."
                           if action == "on" else "Agent Council automatic updates are disabled. Daily checks only notify you about updates.")
                return notice(event, message)
            state = read_object(data / STATE_FILE)
            now = time.time()
            previous = state.get("last_check_at")
            if action != "now" and state.get("status") == "checking":
                state["status"] = "interrupted"
                atomic_write(data / STATE_FILE, state)
                return notice(event, "The previous Agent Council update check was interrupted. This task continues normally. Use `agent-council update now` to retry immediately.")
            if action != "now" and type(previous) in (int, float) and math.isfinite(previous):
                if previous > now:
                    # Rebase a future timestamp once, without triggering repeated requests.
                    state["last_check_at"] = now
                    atomic_write(data / STATE_FILE, state)
                    return None
                if now - previous < DAY:
                    return None
            # Record attempts before I/O, so failures and interrupted attempts also
            # respect the rolling daily limit. Consent lives in a separate file.
            state = {"last_check_at": now, "status": "checking"}
            atomic_write(data / STATE_FILE, state)
            try:
                local = read_object(ROOT / ".codex-plugin" / "plugin.json")
                if local.get("name") != "agent-council":
                    raise ValueError("Local identity mismatch")
                current = local.get("version")
                SemVer(current)
                target = fetch_version()
                if SemVer(target) <= SemVer(current):
                    state["status"] = "current"
                    result = notice(event, "Agent Council is up to date.") if action else None
                elif action == "now" or settings.get("auto_update") is True:
                    install_version(current, target)
                    state.update(status="installed", installed_version=target)
                    result = notice(event, f"Agent Council {target} was installed and verified. It applies to the next task; this task continues using its loaded version.")
                else:
                    state.update(status="available", available_version=target)
                    result = notice(event, f"Agent Council {current} is installed and {target} is available. Automatic updates are off. Use the exact command `agent-council update now` for a one-time update or `agent-council auto-update on` to enable automatic updates.")
            except Exception:
                state["status"] = "failed"
                result = notice(event, "The Agent Council update check or installation could not be completed. This task continues normally. The next automatic check is in 24 hours; `agent-council update now` retries immediately.")
            atomic_write(data / STATE_FILE, state)
            return result
    except Exception:
        return notice(event, "Agent Council could not access its update settings or state. This task continues normally.")


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
        # Hook failures must never interrupt routing or turn into CLI tracebacks.
        if event in ("SessionStart", "UserPromptSubmit"):
            print(json.dumps(notice(event, "Agent Council skipped an unavailable update check. This task continues normally.")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
