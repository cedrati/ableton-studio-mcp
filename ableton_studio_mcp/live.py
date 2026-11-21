"""Talking to the AbletonStudioMCP control surface running inside Live.

One TCP connection, opened lazily and reopened when Live restarts. Every
request is a JSON object ``{"type": command, "params": {...}}`` and gets one
JSON reply ``{"status": "success", "result": ...}`` or
``{"status": "error", "message": ...}``.

Right after connecting, the client asks the control surface for its version
and command list, so a tool can tell "Live is closed" apart from "Live runs
an older control surface" before sending anything.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from dataclasses import dataclass, field
from typing import Any

from . import __version__

log = logging.getLogger("ableton_studio_mcp")

DEFAULT_TIMEOUT = 20.0
# Commands whose work in Live can outlast the default (decoding a long file).
SLOW_COMMANDS = {"create_audio_clip": 65.0}
CONNECT_TIMEOUT = 3.0
CONNECT_ATTEMPTS = 3

INSTALL_HINT = "run `ableton-studio-mcp install`, then restart Live"


class LiveUnavailable(Exception):
    """Nothing answers: Live is closed, or the control surface isn't selected."""


class LiveRefused(Exception):
    """Live received the command and refused it; the message is Live's own."""


class MissingCapability(Exception):
    """The control surface in Live is too old for this command."""


@dataclass
class ScriptInfo:
    version: str | None = None          # None: unknown, "legacy": pre-handshake script
    capabilities: frozenset = frozenset()
    raw: dict = field(default_factory=dict)

    @property
    def up_to_date(self) -> bool:
        return self.version == __version__


# Commands that scripts older than the handshake already understood.
_PRE_HANDSHAKE_COMMANDS = frozenset({
    "get_session_info", "get_track_info", "create_midi_track", "create_clip",
    "add_notes_to_clip", "set_tempo", "set_track_name", "set_clip_name",
    "fire_clip", "stop_clip", "start_playback", "stop_playback",
    "load_instrument_or_effect", "get_browser_tree", "get_browser_items_at_path",
})


class LiveClient:
    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self._sock: socket.socket | None = None
        self._lock = threading.RLock()   # one request/reply exchange at a time
        self.info = ScriptInfo()

    # ── connection ──────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def _open(self) -> None:
        last_error: Exception | None = None
        for _ in range(CONNECT_ATTEMPTS):
            try:
                self._sock = socket.create_connection((self.host, self.port), timeout=CONNECT_TIMEOUT)
                break
            except OSError as e:
                last_error = e
        else:
            raise LiveUnavailable(
                f"Live is not responding on {self.host}:{self.port} ({last_error}). Make sure "
                "Live is open with the AbletonStudioMCP control surface selected.")
        log.info("Connected to Live on %s:%s", self.host, self.port)
        self._handshake()

    def _handshake(self) -> None:
        try:
            reply = self._exchange("get_script_info", {})
            self.info = ScriptInfo(reply.get("script_version"),
                                   frozenset(reply.get("capabilities") or ()), reply)
        except LiveRefused as e:
            # Scripts from before the handshake answer "Unknown command".
            legacy = "unknown command" in str(e).lower()
            self.info = ScriptInfo("legacy" if legacy else None, _PRE_HANDSHAKE_COMMANDS,
                                   {"script_version": "legacy"} if legacy else {})
        if not self.info.up_to_date:
            log.warning("Control surface in Live is %s, this server is %s: %s",
                        self.info.version, __version__, INSTALL_HINT)

    def _socket_is_stale(self) -> bool:
        """True if Live closed our socket since the last exchange."""
        sock = self._sock
        try:
            sock.setblocking(False)
            try:
                return sock.recv(1, socket.MSG_PEEK) == b""
            except BlockingIOError:
                return False
            finally:
                sock.setblocking(True)
        except OSError:
            return True

    def _ensure_open(self) -> None:
        if self._sock is not None and self._socket_is_stale():
            self.close()
        if self._sock is None:
            self._open()

    def connect(self) -> ScriptInfo:
        """Open the connection if needed and return what the control surface reported."""
        with self._lock:
            self._ensure_open()
            return self.info

    def close(self) -> None:
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None

    # ── requests ────────────────────────────────────────────────────────────

    def _read_reply(self, timeout: float) -> dict:
        self._sock.settimeout(timeout)
        data = b""
        while True:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("Live closed the connection")
            data += chunk
            try:
                return json.loads(data)
            except ValueError:
                continue   # reply not complete yet

    def _exchange(self, command: str, params: dict) -> Any:
        payload = json.dumps({"type": command, "params": params}).encode()
        try:
            self._sock.sendall(payload)
            reply = self._read_reply(SLOW_COMMANDS.get(command, DEFAULT_TIMEOUT))
        except socket.timeout:
            self.close()
            raise LiveUnavailable(f"Live did not answer '{command}' in time")
        except OSError as e:
            self.close()
            raise LiveUnavailable(f"Connection to Live lost during '{command}': {e}")
        if reply.get("status") == "error":
            raise LiveRefused(reply.get("message") or f"Live refused '{command}'")
        return reply.get("result", {})

    def call(self, command: str, params: dict | None = None) -> Any:
        """Send one command and return its result (raises on failure)."""
        with self._lock:
            self._ensure_open()
            log.debug("→ %s %s", command, params or "")
            return self._exchange(command, params or {})

    # ── compatibility ───────────────────────────────────────────────────────

    def require(self, capability: str) -> None:
        """Raise unless the control surface in Live supports ``capability``."""
        with self._lock:
            if self.info.version is None:
                self._ensure_open()   # first use, or Live started after us
        if capability in self.info.capabilities:
            return
        if self.info.version is None:
            raise LiveUnavailable(
                f"Could not check the control surface for '{capability}': Live is not "
                "responding. Make sure Live is open with AbletonStudioMCP selected.")
        raise MissingCapability(
            f"The control surface in Live ({self.info.version}) does not support "
            f"'{capability}' (this server is {__version__}): {INSTALL_HINT}.")


_client: LiveClient | None = None


def client() -> LiveClient:
    """The shared connection to Live."""
    global _client
    if _client is None:
        _client = LiveClient(os.environ.get("ABLETON_HOST", "localhost"),
                             int(os.environ.get("ABLETON_PORT", "9877")))
    return _client


def call(command: str, params: dict | None = None) -> Any:
    return client().call(command, params)


def require(capability: str) -> None:
    client().require(capability)


def supports(capability: str) -> bool:
    """Whether Live's control surface has ``capability`` (False if Live is unreachable)."""
    try:
        require(capability)
        return True
    except (LiveUnavailable, MissingCapability):
        return False
