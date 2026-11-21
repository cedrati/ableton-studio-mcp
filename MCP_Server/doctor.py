"""``ableton-studio-mcp doctor``: check the installation and say what to fix.

Read-only: it never installs, edits or restarts anything. Each check returns
a status ("ok", "warn", "fail" or "skip"), what it found, and a fix.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .remote_script_install import (
    EXPECTED_REMOTE_SCRIPT_VERSION,
    REMOTE_SCRIPT_FOLDER_NAME,
    _live_preference_dirs,
    discover_user_library_remote_script_dirs,
)

INSTALL_CMD = "uvx ableton-studio-mcp-install-script"
_VERSION_RE = re.compile(r'^SCRIPT_VERSION\s*=\s*["\']([^"\']+)["\']', re.M)


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail | skip
    found: str
    fix: str = ""


def _package_version() -> str:
    try:
        from importlib.metadata import version
        return version("ableton-studio-mcp")
    except Exception:
        return "unknown (running from a source checkout?)"


def check_python() -> Check:
    v = sys.version_info
    found = f"Python {v.major}.{v.minor}.{v.micro}, ableton-studio-mcp {_package_version()}"
    if v < (3, 10):
        return Check("Python", "fail", found, "Python 3.10 or newer is required; install it with `uv python install 3.12`.")
    return Check("Python", "ok", found)


def check_uv() -> Check:
    uv = shutil.which("uv")
    if not uv:
        return Check("uv", "warn", "uv not found on PATH",
                     "Install uv (https://docs.astral.sh/uv/) — MCP clients start the server with `uvx`.")
    try:
        out = subprocess.run([uv, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception as e:
        out = f"{uv} (version unknown: {e})"
    return Check("uv", "ok", out)


def installed_script_versions() -> list[tuple[Path, str | None]]:
    """(path to installed __init__.py, its SCRIPT_VERSION) for each User Library."""
    found = []
    for root in discover_user_library_remote_script_dirs():
        init = root / REMOTE_SCRIPT_FOLDER_NAME / "__init__.py"
        if init.is_file():
            m = _VERSION_RE.search(init.read_text(encoding="utf-8", errors="replace"))
            found.append((init, m.group(1) if m else None))
    return found


def check_installed_script() -> Check:
    roots = discover_user_library_remote_script_dirs()
    if not roots:
        return Check("Remote Script installed", "fail", "No Ableton User Library found",
                     f"Open Live once so it creates its User Library, then run `{INSTALL_CMD}`.")
    installed = installed_script_versions()
    if not installed:
        return Check("Remote Script installed", "fail",
                     f"No {REMOTE_SCRIPT_FOLDER_NAME} script in {', '.join(str(r) for r in roots)}",
                     f"Run `{INSTALL_CMD}`, then restart Live.")
    bad = [(p, v) for p, v in installed if v != EXPECTED_REMOTE_SCRIPT_VERSION]
    found = "; ".join(f"{v or 'unknown'} at {p}" for p, v in installed)
    if bad:
        return Check("Remote Script installed", "fail", found,
                     f"This server expects {EXPECTED_REMOTE_SCRIPT_VERSION}: run `{INSTALL_CMD}`, then restart Live.")
    return Check("Remote Script installed", "ok", found)


def control_surface_selected() -> bool | None:
    """Whether the newest Live's preferences name AbletonMCP (None: unknown)."""
    for pref_dir in _live_preference_dirs():
        cfg = pref_dir / "Preferences.cfg"
        if cfg.is_file():
            data = cfg.read_bytes()
            name = REMOTE_SCRIPT_FOLDER_NAME
            return name.encode("utf-16-le") in data or name.encode() in data
    return None


def check_control_surface() -> Check:
    selected = control_surface_selected()
    if selected is None:
        return Check("Control surface", "skip", "Live preferences not found")
    if selected:
        return Check("Control surface", "ok", "AbletonMCP is selected in Live's preferences")
    return Check("Control surface", "warn", "AbletonMCP does not appear in Live's preferences",
                 "In Live: Settings → Link, Tempo & MIDI → Control Surface → AbletonMCP (Input/Output: None).")


def live_log_errors(max_lines: int = 3) -> list[str]:
    """Last Remote Script errors in the newest Live's Log.txt."""
    for pref_dir in _live_preference_dirs():
        log = pref_dir / "Log.txt"
        if log.is_file():
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            hits = [l for l in lines
                    if REMOTE_SCRIPT_FOLDER_NAME in l and re.search(r"error|traceback|exception", l, re.I)
                    and "read failed" not in l]
            return hits[-max_lines:]
    return []


def query_live(host: str, port: int, timeout: float = 3.0) -> dict:
    """Ask the running Remote Script for its info (raises if unreachable)."""
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(json.dumps({"type": "get_script_info", "params": {}}).encode())
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            try:
                reply = json.loads(buf.decode())
                break
            except ValueError:
                continue
    if reply.get("status") != "success":
        raise RuntimeError(reply.get("message", "unexpected reply"))
    return reply.get("result", {})


def check_live(host: str, port: int) -> Check:
    try:
        info = query_live(host, port)
    except Exception as e:
        fix = ("Start Live with AbletonMCP selected as control surface. "
               "If Live is open, restart it: the script loads at startup.")
        errors = live_log_errors()
        if errors:
            fix += " Live's log shows: " + " | ".join(errors)
        return Check("Live connection", "fail", f"Nothing answers on {host}:{port} ({e})", fix)
    loaded = info.get("script_version")
    found = f"Remote Script {loaded} answering on {host}:{port}"
    if loaded != EXPECTED_REMOTE_SCRIPT_VERSION:
        installed = {v for _, v in installed_script_versions()}
        if EXPECTED_REMOTE_SCRIPT_VERSION in installed:
            fix = "The new script is installed but Live still runs the old one: restart Live."
        else:
            fix = f"Run `{INSTALL_CMD}`, then restart Live."
        return Check("Live connection", "fail", found + f" (expected {EXPECTED_REMOTE_SCRIPT_VERSION})", fix)
    return Check("Live connection", "ok", found)


def run_checks(host: str | None = None, port: int | None = None) -> list[Check]:
    host = host or os.environ.get("ABLETON_HOST", "localhost")
    port = port or int(os.environ.get("ABLETON_PORT", "9877"))
    return [check_python(), check_uv(), check_installed_script(),
            check_control_surface(), check_live(host, port)]


_ICONS = {"ok": "✓", "warn": "!", "fail": "✗", "skip": "-"}


def format_report(checks: list[Check]) -> str:
    lines = [f"Ableton Studio MCP doctor (expects Remote Script {EXPECTED_REMOTE_SCRIPT_VERSION})", ""]
    for c in checks:
        lines.append(f" {_ICONS.get(c.status, '?')} {c.name}: {c.found}")
        if c.fix and c.status in ("warn", "fail"):
            lines.append(f"     → {c.fix}")
    failed = sum(c.status == "fail" for c in checks)
    lines += ["", "All good." if not failed else f"{failed} problem(s) to fix."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    checks = run_checks()
    print(format_report(checks))
    return 1 if any(c.status == "fail" for c in checks) else 0
