"""Remote Script version handshake and capability checks."""

from __future__ import annotations

import logging
import threading
from typing import Any

from .install import SCRIPT_VERSION as EXPECTED_REMOTE_SCRIPT_VERSION

logger = logging.getLogger("AbletonMCPServer")

_lock = threading.Lock()
_script_info: dict[str, Any] | None = None
_handshake_done = False

# Commands present on Remote Scripts before get_script_info existed
_LEGACY_CAPABILITIES = frozenset({
    "get_session_info",
    "get_track_info",
    "create_midi_track",
    "create_clip",
    "add_notes_to_clip",
    "set_tempo",
    "set_track_name",
    "set_clip_name",
    "fire_clip",
    "stop_clip",
    "start_playback",
    "stop_playback",
    "load_instrument_or_effect",
    "get_browser_tree",
    "get_browser_items_at_path",
})


_refresher = None


def set_refresher(fn) -> None:
    """Register how to redo the handshake (connect to Live, then handshake).

    Used when Live was not running at startup, or the last handshake failed,
    so a capability check never trusts a stale "nothing loaded" result."""
    global _refresher
    _refresher = fn


def _needs_refresh() -> bool:
    info = get_cached_script_info()
    return not info or info.get("script_version") is None


def refresh_if_needed() -> None:
    if _refresher is None or not _needs_refresh():
        return
    try:
        _refresher()
    except Exception as e:
        logger.debug("Handshake retry failed: %s", e)


def get_cached_script_info() -> dict[str, Any] | None:
    with _lock:
        return dict(_script_info) if _script_info else None


def script_has_capability(name: str) -> bool:
    info = get_cached_script_info()
    if not info or info.get("script_version") in (None, "legacy"):
        return name in _LEGACY_CAPABILITIES
    caps = info.get("capabilities")
    if isinstance(caps, list):
        return name in caps
    return script_version_ok()


def script_version_ok() -> bool:
    info = get_cached_script_info()
    if not info:
        return False
    return str(info.get("script_version") or "") == EXPECTED_REMOTE_SCRIPT_VERSION


def handshake(send_command) -> dict[str, Any]:
    """Query Live for script info. On old scripts, get_script_info is unknown."""
    global _script_info, _handshake_done
    info: dict[str, Any] = {
        "script_version": None,
        "capabilities": [],
        "expected_version": EXPECTED_REMOTE_SCRIPT_VERSION,
        "up_to_date": False,
        "error": None,
    }
    try:
        result = send_command("get_script_info")
        if isinstance(result, dict):
            info.update(result)
            info["expected_version"] = EXPECTED_REMOTE_SCRIPT_VERSION
            info["up_to_date"] = (
                str(result.get("script_version") or "") == EXPECTED_REMOTE_SCRIPT_VERSION
            )
    except Exception as e:
        msg = str(e)
        info["error"] = msg
        # Old Remote Scripts don't know get_script_info
        if "Unknown command" in msg or "unknown command" in msg.lower():
            info["script_version"] = "legacy"
            info["capabilities"] = []
            info["up_to_date"] = False
            logger.warning(
                "Ableton Remote Script is outdated (no get_script_info). "
                "Expected %s. Run `ableton-studio-mcp install`, then restart "
                "Live.",
                EXPECTED_REMOTE_SCRIPT_VERSION,
            )
        else:
            logger.warning("Remote Script handshake failed: %s", e)

    with _lock:
        _script_info = info
        _handshake_done = True

    if info.get("up_to_date"):
        logger.info(
            "Remote Script handshake OK (v%s, %d capabilities)",
            info.get("script_version"),
            len(info.get("capabilities") or []),
        )
    elif info.get("script_version") and info.get("script_version") != "legacy":
        logger.warning(
            "Remote Script v%s loaded, package expects v%s — run "
            "`ableton-studio-mcp install`, then restart Ableton.",
            info.get("script_version"),
            EXPECTED_REMOTE_SCRIPT_VERSION,
        )

    return info


def require_capability(name: str) -> str | None:
    """Return an error message if capability missing, else None."""
    if script_has_capability(name):
        return None
    refresh_if_needed()
    if script_has_capability(name):
        return None
    info = get_cached_script_info() or {}
    if info.get("script_version") is None:
        return (
            f"Could not check the Ableton Remote Script for '{name}': Live is not "
            f"responding. Make sure Live is open with the AbletonStudioMCP control "
            f"surface selected, then try again."
        )
    return (
        f"Ableton Remote Script missing capability '{name}' "
        f"(loaded={info.get('script_version')!r}, "
        f"expected={EXPECTED_REMOTE_SCRIPT_VERSION}). "
        f"Run `ableton-studio-mcp install` to update the User Remote Script, "
        f"then restart Ableton Live."
    )
