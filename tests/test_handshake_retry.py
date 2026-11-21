"""The handshake is redone when Live was not running at startup."""

import MCP_Server.script_handshake as sh
from MCP_Server.remote_script_install import EXPECTED_REMOTE_SCRIPT_VERSION


def _reset(monkeypatch):
    monkeypatch.setattr(sh, "_script_info", None)
    monkeypatch.setattr(sh, "_handshake_done", False)


def _live(caps):
    def send(cmd):
        assert cmd == "get_script_info"
        return {"script_version": EXPECTED_REMOTE_SCRIPT_VERSION, "capabilities": caps}
    return send


def _offline(cmd):
    raise ConnectionError("Could not connect to Ableton")


def test_failed_handshake_is_retried_once_live_answers(monkeypatch):
    _reset(monkeypatch)
    sh.handshake(_offline)  # Live closed at startup
    calls = []
    monkeypatch.setattr(sh, "_refresher",
                        lambda: calls.append(1) or sh.handshake(_live(["set_track_routing"])))
    assert sh.require_capability("set_track_routing") is None
    assert calls == [1]


def test_no_retry_when_handshake_already_succeeded(monkeypatch):
    _reset(monkeypatch)
    sh.handshake(_live(["get_session_info"]))
    calls = []
    monkeypatch.setattr(sh, "_refresher", lambda: calls.append(1))
    msg = sh.require_capability("set_track_routing")
    assert "missing capability 'set_track_routing'" in msg and calls == []


def test_live_still_closed_gives_a_clear_message(monkeypatch):
    _reset(monkeypatch)
    sh.handshake(_offline)
    monkeypatch.setattr(sh, "_refresher", lambda: sh.handshake(_offline))
    msg = sh.require_capability("set_track_routing")
    assert "Live is not responding" in msg and "install-script" not in msg


def test_refresher_errors_are_swallowed(monkeypatch):
    _reset(monkeypatch)

    def boom():
        raise ConnectionError("nope")
    monkeypatch.setattr(sh, "_refresher", boom)
    assert "Live is not responding" in sh.require_capability("set_track_routing")


def test_legacy_script_is_not_retried(monkeypatch):
    _reset(monkeypatch)

    def old(cmd):
        raise RuntimeError("Unknown command: get_script_info")
    sh.handshake(old)
    calls = []
    monkeypatch.setattr(sh, "_refresher", lambda: calls.append(1))
    assert "install-script" in sh.require_capability("set_track_routing") and calls == []


def test_server_registers_the_refresher():
    import MCP_Server.server as server
    assert sh._refresher is server._refresh_handshake
