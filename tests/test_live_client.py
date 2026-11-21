"""The connection to Live, against a fake control surface on a real socket.

Covers what goes wrong in practice: Live closed, Live restarted, a slow
command, a reply split over several packets, an outdated control surface,
two tools calling at once.
"""

import json
import socket
import threading
import time

import pytest

from ableton_studio_mcp import __version__, app, live

CAPS = ["get_session_info", "set_tempo", "get_scenes"]


class FakeLive:
    """A minimal control surface: answers JSON requests on 127.0.0.1."""

    def __init__(self, version=__version__, caps=CAPS, handshake=True, newline=True):
        self.version, self.caps, self.handshake = version, caps, handshake
        self.newline = newline   # False: a pre-2.0 control surface (no line framing)
        self.requests = []
        self.connections = 0
        self.handlers = {}
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(5)
        self.port = self.server.getsockname()[1]
        self.clients = []
        self._stop = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self._stop:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self.connections += 1
            self.clients.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        buf = b""
        while True:
            try:
                chunk = conn.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            try:
                request = json.loads(buf)
            except ValueError:
                continue
            buf = b""
            self.requests.append(request["type"])
            reply = self._answer(request)
            if reply is None:
                continue
            data = reply if isinstance(reply, bytes) else json.dumps(reply).encode()
            if self.newline:
                data += b"\n"
            for i in range(0, len(data), 7):      # deliberately fragmented
                conn.sendall(data[i:i + 7])

    def _answer(self, request):
        kind = request["type"]
        if kind == "get_script_info":
            if not self.handshake:
                return {"status": "error", "message": "Unknown command: get_script_info"}
            return {"status": "success", "result": {"script_version": self.version, "capabilities": self.caps}}
        if kind in self.handlers:
            return self.handlers[kind](request.get("params", {}))
        return {"status": "success", "result": {"echo": kind, "params": request.get("params", {})}}

    def drop_clients(self):
        for c in self.clients:
            try:
                c.shutdown(socket.SHUT_RDWR)
                c.close()
            except OSError:
                pass
        self.clients.clear()

    def close(self):
        self._stop = True
        self.drop_clients()
        self.server.close()


@pytest.fixture
def fake():
    servers = []

    def make(**kw):
        s = FakeLive(**kw)
        servers.append(s)
        return s
    yield make
    for s in servers:
        s.close()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ── basic exchange ───────────────────────────────────────────────────────────

def test_call_returns_result_and_handshakes_once(fake):
    f = fake()
    c = live.LiveClient("127.0.0.1", f.port)
    assert c.call("set_tempo", {"tempo": 128}) == {"echo": "set_tempo", "params": {"tempo": 128}}
    c.call("get_scenes")
    assert f.requests == ["get_script_info", "set_tempo", "get_scenes"]
    assert c.info.up_to_date and "set_tempo" in c.info.capabilities


def test_refusal_keeps_the_connection_and_live_s_words(fake):
    f = fake()
    f.handlers["set_tempo"] = lambda p: {"status": "error", "message": "Tempo out of range"}
    c = live.LiveClient("127.0.0.1", f.port)
    with pytest.raises(live.LiveRefused, match="^Tempo out of range$"):
        c.call("set_tempo", {"tempo": 5000})
    assert c.connected
    c.call("get_scenes")
    assert f.connections == 1


def test_large_fragmented_reply_is_reassembled(fake):
    f = fake()
    notes = [{"pitch": 60 + i % 12, "start_time": i / 4} for i in range(3000)]
    f.handlers["get_clip_notes"] = lambda p: {"status": "success", "result": {"notes": notes}}
    assert live.LiveClient("127.0.0.1", f.port).call("get_clip_notes")["notes"] == notes


# ── Live not there, or going away ────────────────────────────────────────────

def test_live_closed_gives_a_clear_message(monkeypatch):
    monkeypatch.setattr(live, "CONNECT_ATTEMPTS", 1)
    c = live.LiveClient("127.0.0.1", free_port())
    with pytest.raises(live.LiveUnavailable, match="AbletonStudioMCP control surface selected"):
        c.call("get_session_info")
    assert not c.connected


def test_live_restart_is_picked_up_transparently(fake):
    f = fake()
    c = live.LiveClient("127.0.0.1", f.port)
    c.call("get_scenes")
    f.drop_clients()               # Live quits / restarts: our socket is dead
    time.sleep(0.05)
    assert c.call("get_scenes")["echo"] == "get_scenes"
    assert f.connections == 2
    assert f.requests.count("get_script_info") == 2   # version checked again


def test_connection_lost_mid_request_is_reported_and_recovered(fake):
    f = fake()
    def hang_up(params):
        f.drop_clients()
        return None
    f.handlers["fire_scene"] = hang_up
    c = live.LiveClient("127.0.0.1", f.port)
    with pytest.raises(live.LiveUnavailable, match="lost during 'fire_scene'"):
        c.call("fire_scene")
    assert not c.connected
    assert c.call("get_scenes")["echo"] == "get_scenes"


def test_slow_command_times_out_then_recovers(fake, monkeypatch):
    monkeypatch.setattr(live, "DEFAULT_TIMEOUT", 0.2)
    f = fake()
    f.handlers["get_scenes"] = lambda p: None      # never answers
    c = live.LiveClient("127.0.0.1", f.port)
    with pytest.raises(live.LiveUnavailable, match="did not answer 'get_scenes' in time"):
        c.call("get_scenes")
    f.handlers.clear()
    assert c.call("get_scenes")["echo"] == "get_scenes"


def test_slow_commands_get_a_longer_timeout():
    assert live.SLOW_COMMANDS["create_audio_clip"] > live.DEFAULT_TIMEOUT


# ── version and capabilities ─────────────────────────────────────────────────

def test_outdated_control_surface_is_named_with_the_fix(fake):
    f = fake(version="1.17.0")
    c = live.LiveClient("127.0.0.1", f.port)
    c.require("set_tempo")
    with pytest.raises(live.MissingCapability) as e:
        c.require("delete_locator")
    assert "1.17.0" in str(e.value) and __version__ in str(e.value) and "ableton-studio-mcp install" in str(e.value)


def test_pre_handshake_script_still_gets_its_basic_commands(fake):
    f = fake(handshake=False)
    c = live.LiveClient("127.0.0.1", f.port)
    c.require("set_tempo")
    assert c.info.version == "legacy"
    with pytest.raises(live.MissingCapability):
        c.require("get_scenes")


def test_live_started_after_the_server(monkeypatch):
    monkeypatch.setattr(live, "CONNECT_ATTEMPTS", 1)
    port = free_port()
    c = live.LiveClient("127.0.0.1", port)
    with pytest.raises(live.LiveUnavailable):
        c.require("set_tempo")
    f = FakeLive()                       # Live comes up later on that port
    f.server.close()
    f.server = socket.socket()
    f.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    f.server.bind(("127.0.0.1", port))
    f.server.listen(5)
    threading.Thread(target=f._accept, daemon=True).start()
    try:
        c.require("set_tempo")           # no stale "unknown version" left behind
        assert c.info.up_to_date
    finally:
        f.close()


# ── concurrency ──────────────────────────────────────────────────────────────

def test_parallel_calls_never_read_each_other_s_reply(fake):
    f = fake()
    c = live.LiveClient("127.0.0.1", f.port)
    errors = []

    def worker(n):
        for i in range(20):
            reply = c.call("set_tempo", {"tempo": n * 100 + i})
            if reply["params"]["tempo"] != n * 100 + i:
                errors.append((n, i, reply))
    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


# ── how tools report failures ────────────────────────────────────────────────

def _tool_raising(exc):
    def body():
        raise exc
    body.__name__ = "demo_tool"
    return app.guard(body)


@pytest.mark.parametrize("exc, expected", [
    (live.LiveUnavailable("Live is not responding"), "Live is not responding"),
    (live.MissingCapability("too old"), "too old"),
    (live.LiveRefused("No clip in slot 3"), "demo_tool failed: No clip in slot 3"),
    (ValueError("location must be 'session' or 'arrangement'"),
     "demo_tool failed: location must be 'session' or 'arrangement'"),
    (KeyError("boom"), "demo_tool failed unexpectedly: 'boom'"),
])
def test_tool_failures_become_one_readable_line(exc, expected):
    assert _tool_raising(exc)() == expected


def test_tool_checks_capabilities_before_running(monkeypatch):
    ran = []

    def require(name):
        raise live.MissingCapability(f"needs {name}")
    monkeypatch.setattr(live, "require", require)

    def body():
        ran.append(1)
    body.__name__ = "needs_demo"
    assert app.guard(body, ["fancy_command"])() == "needs fancy_command"
    assert ran == []


def test_supports_is_false_when_live_is_unreachable(monkeypatch):
    def require(name):
        raise live.LiveUnavailable("closed")
    monkeypatch.setattr(live, "require", require)
    assert live.supports("anything") is False


# ── framing ──────────────────────────────────────────────────────────────────

def test_requests_are_sent_as_json_lines(fake):
    f = fake()
    seen = []
    f.handlers["get_scenes"] = lambda p: seen.append(p) or {"status": "success", "result": {}}
    c = live.LiveClient("127.0.0.1", f.port)
    c.call("get_scenes", {"name": "a\nb"})       # a newline inside a value stays escaped
    assert seen == [{"name": "a\nb"}]


def test_pre_2_0_control_surface_without_newlines_still_works(fake):
    f = fake(version="1.17.0", newline=False)
    c = live.LiveClient("127.0.0.1", f.port)
    assert c.call("get_scenes")["echo"] == "get_scenes"
    assert c.info.version == "1.17.0"


def test_garbled_reply_closes_the_connection(fake):
    f = fake()
    f.handlers["get_scenes"] = lambda p: b"<html>oops</html>"
    c = live.LiveClient("127.0.0.1", f.port)
    with pytest.raises(live.LiveUnavailable, match="Unreadable reply"):
        c.call("get_scenes")
    assert not c.connected


def test_older_patch_of_the_same_series_is_accepted(fake):
    """A patch release of the server alone must not make users reinstall the
    control surface in Live."""
    from ableton_studio_mcp import SCRIPT_SERIES
    f = fake(version=SCRIPT_SERIES + ".0")
    c = live.LiveClient("127.0.0.1", f.port)
    c.require("set_tempo")
    assert c.info.up_to_date
