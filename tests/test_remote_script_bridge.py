"""Regression tests for the Live-side Remote Script's TCP surface.

Each test pins a defect this change fixes:

* the socket bound every interface, exposing an unauthenticated command
  surface to the whole network,
* each recv() chunk was decoded on its own, so a multi-byte UTF-8 character
  split across a chunk boundary desynchronised the connection,
* an incomplete command grew the buffer without bound,
* get_browser_tree never recursed and never reported a folder count.

The script normally runs inside Live's interpreter, so ``_Framework`` is
stubbed and the class is instantiated without ``__init__`` (which would open a
socket). No Ableton, no network.
"""

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_SCRIPT = (REPO_ROOT / "ableton_studio_mcp" / "live_script" / "AbletonStudioMCP"
                  / "__init__.py")


_LOADS = 0


def _load_script_module(fresh=False):
    """Import the Live-side script with _Framework stubbed out.

    Each call re-executes the module, so ``fresh`` is only a readability hint
    at call sites that depend on module-level state being re-evaluated (the
    ABLETON_MCP_HOST lookup).
    """
    framework = types.ModuleType("_Framework")
    control_surface_mod = types.ModuleType("_Framework.ControlSurface")

    class _StubControlSurface(object):
        def __init__(self, *args, **kwargs):
            pass

        def log_message(self, *args, **kwargs):
            pass

        def show_message(self, *args, **kwargs):
            pass

    control_surface_mod.ControlSurface = _StubControlSurface
    framework.ControlSurface = control_surface_mod
    sys.modules.setdefault("_Framework", framework)
    sys.modules.setdefault("_Framework.ControlSurface", control_surface_mod)

    global _LOADS
    _LOADS += 1
    name = "AbletonStudioMCP_under_test_%d" % _LOADS   # a fresh package each time
    spec = importlib.util.spec_from_file_location(
        name, BUNDLED_SCRIPT, submodule_search_locations=[str(BUNDLED_SCRIPT.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script_module():
    return _load_script_module()


def make_instance(script_module, application=None):
    inst = script_module.AbletonStudioMCP.__new__(script_module.AbletonStudioMCP)
    inst.application = lambda: application
    inst.schedule_message = lambda delay, callback: callback()  # run "on the main thread" now
    inst.log_message = lambda *a, **k: None
    inst.show_message = lambda *a, **k: None
    return inst


# ------------------------------------------------------------------ binding

def test_socket_binds_loopback_by_default(script_module):
    """The command surface is unauthenticated: it must not listen publicly
    unless the user opts in via ABLETON_MCP_HOST."""
    assert script_module.HOST == "127.0.0.1"


def test_bind_host_is_overridable_for_remote_setups(monkeypatch):
    """Running Live and the MCP server on separate machines stays possible,
    but only as a deliberate choice."""
    monkeypatch.setenv("ABLETON_MCP_HOST", "0.0.0.0")
    assert _load_script_module(fresh=True).HOST == "0.0.0.0"


def test_script_and_package_versions_match():
    """The server refuses a Live script whose version differs from its own."""
    from ableton_studio_mcp import __version__
    assert _load_script_module().SCRIPT_VERSION == __version__


# ------------------------------------------------------------------ framing

def _reader(script_module, limit=None):
    transport = script_module.transport
    return transport.RequestReader() if limit is None else transport.RequestReader(limit)


def test_request_split_mid_utf8_character_still_parses(script_module):
    """Bytes are only decoded once a whole request is in: an accented name
    cut between the two bytes of 'é' must not break the stream."""
    payload = json.dumps({"type": "set_clip_name", "params": {"name": "café été"}},
                         ensure_ascii=False).encode("utf-8") + b"\n"
    split = payload.index(b"\xc3") + 1
    reader = _reader(script_module)
    assert reader.feed(payload[:split]) == []
    assert reader.feed(payload[split:])[0]["params"]["name"] == "café été"


def test_request_in_many_chunks_parses_once(script_module):
    payload = json.dumps({"type": "get_session_info", "params": {}}).encode("utf-8") + b"\n"
    reader = _reader(script_module)
    found = []
    for i in range(0, len(payload), 3):
        found += reader.feed(payload[i:i + 3])
    assert [r["type"] for r in found] == ["get_session_info"]


def test_several_requests_in_one_packet(script_module):
    packet = b'{"type": "start_playback"}\n{"type": "stop_playback"}\n'
    assert [r["type"] for r in _reader(script_module).feed(packet)] == ["start_playback", "stop_playback"]


def test_protocol_1_request_without_newline_is_accepted(script_module):
    reader = _reader(script_module)
    assert reader.feed(b'{"type": "get_scr') == []
    assert reader.feed(b'ipt_info", "params": {}}')[0]["type"] == "get_script_info"


def test_oversized_request_is_refused_instead_of_buffered_forever(script_module):
    reader = _reader(script_module, limit=1024)
    with pytest.raises(ValueError, match="larger than 1024"):
        reader.feed(b'{"type": "' + b"x" * 4096)


def test_non_object_request_is_refused(script_module):
    with pytest.raises(ValueError, match="JSON object"):
        _reader(script_module).feed(b"[1, 2]\n")


def test_socket_server_answers_one_line_per_request(script_module):
    """End to end on a real socket: newline framing, replies in order,
    a broken request answered with an error before hanging up."""
    import socket as _socket
    seen = []

    def handle(request):
        seen.append(request["type"])
        return {"status": "success", "result": {"echo": request["type"]}}

    server = script_module.transport.SocketServer("127.0.0.1", 0, handle, lambda *_: None)
    server.port = 0
    server.start()
    port = server.listener.getsockname()[1]
    try:
        with _socket.create_connection(("127.0.0.1", port), timeout=3) as c:
            c.sendall(b'{"type": "a"}\n{"type": "b"}\n')
            data = b""
            while data.count(b"\n") < 2:
                data += c.recv(4096)
            replies = [json.loads(line) for line in data.splitlines()]
            assert [r["result"]["echo"] for r in replies] == ["a", "b"]
            c.sendall(b"not json\n")
            error = json.loads(c.recv(4096).splitlines()[0])
            assert error["status"] == "error" and "bad request" in error["message"]
            assert c.recv(4096) == b""          # then the server hangs up
    finally:
        server.stop()
    assert seen == ["a", "b"]


# ------------------------------------------------------------ dispatching

def test_unknown_command_and_parameter_checks(script_module):
    inst = make_instance(script_module)
    assert inst._process_command({"type": "nope"})["message"] == "Unknown command: nope"
    reply = inst._process_command({"type": "set_tempo", "params": {}})
    assert reply == {"status": "error", "message": "set_tempo needs 'tempo'"}
    reply = inst._process_command({"type": "set_tempo", "params": {"tempo": 120, "bpm": 3}})
    assert reply == {"status": "error", "message": "set_tempo does not take 'bpm'"}
    reply = inst._process_command({"type": "create_locator", "params": {"name": "x"}})
    assert reply["message"] == "create_locator needs 'time'"


def test_handler_exception_becomes_an_error_reply(script_module):
    inst = make_instance(script_module)
    class Song(object):
        @property
        def tempo(self):
            raise RuntimeError("no song")
        @tempo.setter
        def tempo(self, v):
            raise RuntimeError("tempo is locked")
    inst._song = Song()
    reply = inst._process_command({"type": "set_tempo", "params": {"tempo": 128}})
    assert reply == {"status": "error", "message": "tempo is locked"}


def test_capabilities_are_generated_from_the_handlers(script_module):
    caps = script_module.SCRIPT_CAPABILITIES
    assert "set_tempo" in caps and "arrangement_notes" in caps
    assert len(caps) == len(set(caps))
    for name in script_module.registry.COMMANDS:
        method = script_module.registry.COMMANDS[name][0]
        assert callable(getattr(script_module.AbletonStudioMCP, method)), name


def test_main_thread_timeout_is_reported(script_module, monkeypatch):
    inst = make_instance(script_module)
    inst.schedule_message = lambda delay, callback: None     # Live never runs it
    monkeypatch.setattr(script_module.surface, "MAIN_THREAD_TIMEOUT", 0.05)
    reply = inst._process_command({"type": "get_scenes", "params": {}})
    assert reply == {"status": "error", "message": "Live did not finish 'get_scenes' in time"}


# ------------------------------------------------------------- browser tree

class FakeBrowserItem(object):
    def __init__(self, name, children=(), loadable=False, uri=None):
        self.name = name
        self.children = list(children)
        self.is_device = False
        self.is_loadable = loadable
        self.uri = uri


class FakeBrowser(object):
    def __init__(self, instruments):
        self.instruments = instruments


class FakeApplication(object):
    def __init__(self, browser=None):
        self.browser = browser


def test_browser_tree_returns_children_and_a_truthful_folder_count(script_module):
    """Regression: process_item never recursed (children was always []) and
    total_folders was never returned, so the server's header always read
    'showing 0 folders'."""
    kits = FakeBrowserItem("Kits", [FakeBrowserItem("808 Core Kit", loadable=True)])
    browser = FakeBrowser(FakeBrowserItem("Instruments", [kits]))
    inst = make_instance(script_module, application=FakeApplication(browser=browser))

    tree = inst.get_browser_tree("instruments")

    assert tree["total_folders"] >= 2  # Instruments and Kits both have children
    category = tree["categories"][0]
    assert [child["name"] for child in category["children"]] == ["Kits"]
    # Depth is capped one level below the category, so Kits reports more.
    assert category["children"][0]["has_more"] is True


def test_browser_tree_caps_a_huge_folder_and_flags_it(script_module):
    many = [FakeBrowserItem("Preset %d" % i, loadable=True) for i in range(200)]
    browser = FakeBrowser(FakeBrowserItem("Instruments", many))
    inst = make_instance(script_module, application=FakeApplication(browser=browser))

    category = inst.get_browser_tree("instruments")["categories"][0]

    assert len(category["children"]) == 64
    assert category["has_more"] is True
