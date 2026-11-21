"""Undo / redo (#37): one undo step per change, groups, and the tools.

Measured in Live 12.4: Live merges every change a script makes into a single
undo step until something closes it, so the control surface gives each
change its own step.
"""

import types

import pytest

from ableton_studio_mcp import live, tools
from ableton_studio_mcp.app import guard
from test_clip_notes import call
from test_remote_script_bridge import _load_script_module, make_instance


@pytest.fixture(scope="module")
def script_module():
    return _load_script_module()


class UndoSong(object):
    """Records undo-step boundaries and changes; undo/redo pop whole steps."""

    def __init__(self):
        self.events = []
        self.steps, self.redo_stack = [], []
        self._open = None
        self.tempo = 120.0

    # Live's API
    def begin_undo_step(self):
        self.events.append("begin")
        self._open = []

    def end_undo_step(self):
        self.events.append("end")
        if self._open:
            self.steps.append(self._open)
        self._open = None

    @property
    def can_undo(self):
        return bool(self.steps)

    @property
    def can_redo(self):
        return bool(self.redo_stack)

    def undo(self):
        step = self.steps.pop()
        for name, old, _new in reversed(step):
            setattr(self, "_" + name, old)
        self.redo_stack.append(step)

    def redo(self):
        step = self.redo_stack.pop()
        for name, _old, new in step:
            setattr(self, "_" + name, new)
        self.steps.append(step)

    @property
    def tempo(self):
        return self._tempo

    @tempo.setter
    def tempo(self, value):
        if hasattr(self, "_tempo") and self._open is not None:
            self._open.append(("tempo", self._tempo, value))
            self.redo_stack = []
        self.events.append("tempo=%s" % value)
        self._tempo = value


@pytest.fixture
def surface(script_module):
    inst = make_instance(script_module)
    inst._song = UndoSong()
    inst._song.events.clear()
    return inst


def run(inst, command, **params):
    return inst._process_command({"type": command, "params": params})


# ── control surface ──────────────────────────────────────────────────────────

def test_each_change_is_its_own_step(surface):
    for bpm in (128, 126, 124):
        assert run(surface, "set_tempo", tempo=bpm)["status"] == "success"
    assert surface._song.events == ["begin", "tempo=128.0", "end", "begin", "tempo=126.0", "end",
                                    "begin", "tempo=124.0", "end"]
    assert run(surface, "undo")["result"]["done"] == 1 and surface._song.tempo == 126.0
    assert run(surface, "undo", steps=5)["result"]["done"] == 2 and surface._song.tempo == 120.0
    assert run(surface, "redo")["result"]["done"] == 1 and surface._song.tempo == 128.0


def test_reads_and_undo_commands_open_no_step(surface):
    surface._song.tempo = 128
    surface._song.events.clear()
    run(surface, "get_undo_state")
    run(surface, "undo")
    assert "begin" not in surface._song.events


def test_a_group_makes_one_step_and_only_one(surface):
    run(surface, "begin_undo_group", name="drums")
    run(surface, "set_tempo", tempo=128)
    run(surface, "set_tempo", tempo=126)
    assert run(surface, "get_undo_state")["result"]["undo_group_open"] is True
    assert run(surface, "end_undo_group")["result"] == {
        "can_undo": True, "can_redo": False, "undo_group_open": False, "ended": True, "name": "drums"}
    assert surface._song.events.count("begin") == 1 and surface._song.events.count("end") == 1
    run(surface, "undo")
    assert surface._song.tempo == 120.0


def test_group_rules(surface):
    run(surface, "begin_undo_group")
    assert "already open" in run(surface, "begin_undo_group")["message"]
    assert "end it first" in run(surface, "undo")["message"]
    run(surface, "end_undo_group")
    assert run(surface, "end_undo_group")["result"]["ended"] is False
    assert "1 to 50" in run(surface, "undo", steps=0)["message"]


def test_a_failing_change_still_closes_its_step(surface):
    assert run(surface, "set_tempo", tempo=5)["status"] == "error"     # out of range
    assert surface._song.events == ["begin", "end"]


def test_a_deferred_change_closes_its_step_when_it_settles(surface, script_module):
    class LaggingSong(UndoSong):
        """Like Live: a playhead move shows up a tick later."""
        shown, is_playing = 0.0, False

        @property
        def current_song_time(self):
            return self.shown

        @current_song_time.setter
        def current_song_time(self, value):
            self.requested = value

    surface._song = LaggingSong()
    surface._song.events.clear()
    pending = []
    surface.schedule_message = lambda delay, cb: pending.append(cb)   # ticks run later
    replies = []
    surface._execute({"type": "set_current_song_time", "params": {"time": 8.0}}, replies.append)
    assert surface._song.events == ["begin"] and replies == []
    surface._song.shown = surface._song.requested                     # the next tick
    while pending:
        pending.pop(0)()
    assert surface._song.events == ["begin", "end"] and replies[0]["status"] == "success"


def test_a_forgotten_group_is_closed(surface, script_module, monkeypatch):
    run(surface, "begin_undo_group", name="forgotten")
    surface._undo_group_since -= script_module.constants.UNDO_GROUP_MAX_SECONDS + 1
    surface._close_stale_undo_group()
    assert run(surface, "get_undo_state")["result"]["undo_group_open"] is False


def test_live_without_undo_steps_still_runs_commands(script_module):
    inst = make_instance(script_module)
    inst._song = types.SimpleNamespace(tempo=120.0)
    assert run(inst, "set_tempo", tempo=128)["status"] == "success"
    assert "Live 11+" in run(inst, "begin_undo_group")["message"]


# ── server ───────────────────────────────────────────────────────────────────

class Recorder(object):
    def __init__(self, replies=None, refuse=()):
        self.sent, self.replies, self.refuse = [], replies or {}, refuse

    def call(self, name, params=None):
        self.sent.append(name)
        if name in self.refuse:
            raise live.LiveRefused("An undo group is already open ('outer')")
        return self.replies.get(name, {})


@pytest.fixture
def recorder(monkeypatch):
    def make(**kw):
        r = Recorder(**kw)
        monkeypatch.setattr(live, "client", lambda: r)
        monkeypatch.setattr(live, "require", lambda name: None)
        return r
    return make


@pytest.mark.undo_groups
def test_undo_group_wraps_and_closes_even_on_error(recorder):
    r = recorder()
    with pytest.raises(RuntimeError):
        with live.undo_group("x"):
            live.call("set_tempo")
            raise RuntimeError("boom")
    assert r.sent == ["begin_undo_group", "set_tempo", "end_undo_group"]


@pytest.mark.undo_groups
def test_undo_group_joins_an_open_group(recorder):
    r = recorder(refuse=("begin_undo_group",))
    with live.undo_group("inner"):
        live.call("set_tempo")
    assert r.sent == ["begin_undo_group", "set_tempo"]          # no end: not ours


@pytest.mark.undo_groups
def test_a_multi_change_tool_is_one_undo_step(recorder):
    r = recorder()

    def body():
        live.call("create_clip")
        live.call("add_notes_to_clip")
        return "ok"
    body.__name__ = "demo"
    assert guard(body, undo_step="Demo")() == "ok"
    assert r.sent == ["begin_undo_group", "create_clip", "add_notes_to_clip", "end_undo_group"]


def test_undo_and_redo_tools_report(recorder):
    recorder(replies={"undo": {"done": 2, "can_undo": False}, "redo": {"done": 1, "can_redo": True}})
    assert call(tools.undo, steps=2) == "Undid 2 step(s). Nothing left to undo."
    assert call(tools.redo) == "Redid 1 step(s)."
    recorder(replies={"end_undo_group": {"ended": True, "name": "beat"}})
    assert "one undo takes it all back" in call(tools.end_undo_group)


# ── browser loads split Live's undo steps (measured in Live 12.4) ────────────

class Device(object):
    class_name = "Drift"
    name = "Drift"
    parameters = ()


class LoadingSong(UndoSong):
    """UndoSong plus one track whose device chain can change. Like Live, a
    browser load commits the open step and records a step of its own; later
    changes land in a fresh automatic step."""

    def __init__(self):
        UndoSong.__init__(self)
        self.track = types.SimpleNamespace(name="1-MIDI", devices=[])
        self.tracks = [self.track]

    def change(self, name, old, new, apply):
        apply(new)
        step = ("custom", old, new, apply)
        if self._open is not None:
            self._open.append(step)
        else:                                      # Live's automatic step
            self.steps.append([step])
        self.redo_stack = []

    def browser_load(self):
        if self._open:                             # the open step is committed...
            self.steps.append(self._open)
        self._open = None
        before = list(self.track.devices)
        self.track.devices = before + [Device()]    # ...and the load is its own step
        self.steps.append([("custom", before, list(self.track.devices),
                            lambda v: setattr(self.track, "devices", v))])
        self.redo_stack = []

    def undo(self):
        step = self.steps.pop()
        for _kind, old, _new, apply in reversed(step):
            apply(old)
        self.redo_stack.append(step)

    def redo(self):
        step = self.redo_stack.pop()
        for _kind, _old, new, apply in step:
            apply(new)
        self.steps.append(step)

    def set_tempo(self, value):
        self.change("tempo", self._tempo, value, lambda v: setattr(self, "_tempo", v))

    @property
    def tempo(self):
        return self._tempo

    @tempo.setter
    def tempo(self, value):      # the control surface's set_tempo goes through here
        if not hasattr(self, "_tempo"):
            self._tempo = value
        else:
            self.set_tempo(value)


@pytest.fixture
def loading(script_module):
    inst = make_instance(script_module)
    inst._song = LoadingSong()
    return inst


def test_an_action_with_a_load_is_undone_completely(loading):
    song = loading._song
    song.set_tempo(100.0)                          # an earlier change by hand
    run(loading, "begin_undo_group", name="new sound")
    song.set_tempo(125.0)
    loading._note_browser_load()
    song.browser_load()
    song.set_tempo(126.0)
    run(loading, "end_undo_group")
    assert len(song.steps) == 4                    # by hand | A | load | B
    reply = run(loading, "undo")["result"]
    assert (reply["done"], reply["live_steps"]) == (1, 3)
    assert song.tempo == 100.0 and song.track.devices == []
    assert len(song.steps) == 1                    # the change by hand is untouched
    reply = run(loading, "redo")["result"]
    assert reply["live_steps"] == 3 and song.tempo == 126.0 and len(song.track.devices) == 1


def test_a_load_first_never_undoes_the_step_before(loading):
    song = loading._song
    song.set_tempo(100.0)                          # must survive
    run(loading, "begin_undo_group", name="load first")
    loading._note_browser_load()
    song.browser_load()                            # nothing open yet: no empty step
    song.set_tempo(126.0)
    run(loading, "end_undo_group")
    reply = run(loading, "undo")["result"]
    assert reply["live_steps"] == 2                # stops at the fingerprint, not at 1 + 2 × 1
    assert song.tempo == 100.0 and song.track.devices == []


def test_plain_actions_stay_one_step_each(loading):
    run(loading, "set_tempo", tempo=128)
    run(loading, "set_tempo", tempo=126)
    assert run(loading, "undo")["result"]["live_steps"] == 1
    assert loading._song.tempo == 128.0
