"""Producer automation gestures: the envelopes, the target finding, and the
resting value held on the other clips of the track."""

import json

import pytest

from ableton_studio_mcp import gestures as g
from ableton_studio_mcp import live, tools
from test_clip_notes import call


def test_delay_throw_at_the_end_of_each_phrase():
    d = g.gesture_points("delay_throw", 32, rest=0.4, peak=0.9, low=0.0, phrase_beats=16, tail_beats=1)
    assert d["points"] == [{"time": 0.0, "value": 0.4}, {"time": 15.0, "value": 0.9},
                           {"time": 16.0, "value": 0.4}, {"time": 31.0, "value": 0.9},
                           {"time": 32.0, "value": 0.4}]
    assert d["interpolation"] == "step" and d["end_value"] == 0.4


def test_moves_that_end_away_from_rest_say_so():
    for name in ("drop_cut", "filter_fall", "fade_out"):
        d = g.gesture_points(name, 16, rest=0.8, peak=0.8, low=0.0)
        assert d["end_value"] != d["rest"], name
    for name in ("delay_throw", "reverb_swell", "filter_rise", "stutter", "fade_in"):
        d = g.gesture_points(name, 16, rest=0.8, peak=0.95, low=0.0)
        assert abs(d["points"][-1]["value"] - 0.8) < 1e-6 and d["end_value"] == 0.8, name


def test_drop_cut_and_stutter_shapes():
    cut = g.gesture_points("drop_cut", 32, rest=0.8, peak=0.8, low=0.0, tail_beats=1)
    assert cut["points"] == [{"time": 0.0, "value": 0.8}, {"time": 31.0, "value": 0.0}]
    st = g.gesture_points("stutter", 16, rest=0.8, peak=0.8, low=0.0, tail_beats=1)
    gate = [p["value"] for p in st["points"] if 15.0 <= p["time"] < 16.0]
    assert gate == [0.0, 0.8] * 4                  # a 16th-note gate on the last beat


def test_unknown_gesture_and_return_finding():
    with pytest.raises(g.GestureError):
        g.gesture_points("wobble", 16, 0.5, 0.5, 0.0)
    assert g.find_return(["A-Reverb", "B-Delay | Saturator"], g.DELAY_WORDS) == 1
    assert g.find_return(["A-Reverb", "B-Delay"], g.REVERB_WORDS) == 0
    assert g.find_return(["A", "B"], g.REVERB_WORDS) is None


# ── the tool ─────────────────────────────────────────────────────────────────

class _Conn:
    def __init__(self, answers):
        self.answers, self.sent = answers, []

    def call(self, cmd, params=None):
        self.sent.append((cmd, params or {}))
        a = self.answers.get(cmd, {})
        return a(params or {}) if callable(a) else a


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setattr(live, "require", lambda name: None)

    def make(answers):
        c = _Conn(answers)
        monkeypatch.setattr(live, "client", lambda: c)
        return c
    return make


def _snapshot(devices=()):
    return {"tracks": [{"name": "Vox", "volume": 0.7,
                        "sends": [{"index": 0, "value": 0.3, "name": "A-Reverb"},
                                  {"index": 1, "value": 0.5, "name": "B-Delay"}],
                        "devices": list(devices),
                        "clip_slots": [{"index": 0, "has_clip": True, "clip": {"length": 16.0}},
                                       {"index": 1, "has_clip": True, "clip": {"length": 32.0}},
                                       {"index": 2, "has_clip": False, "clip": None}]}],
            "return_tracks": [{"name": "A-Reverb"}, {"name": "B-Delay"}]}


def test_delay_throw_finds_the_delay_return_and_leaves_other_clips(conn):
    c = conn({"get_session_snapshot": _snapshot(), "get_clip_automation": {"has_envelope": False}})
    out = json.loads(call(tools.automation_gesture, 0, 0, "delay_throw"))
    writes = [p for cmd, p in c.sent if cmd == "set_clip_automation"]
    assert len(writes) == 1 and writes[0]["mixer_parameter"] == "send:1"
    assert writes[0]["points"][0] == {"time": 0.0, "value": 0.5}     # starts from the current send
    assert out["rest"] == 0.5 and "held_at_rest" not in out and "warning" not in out


def test_drop_cut_holds_the_fader_on_the_other_clips(conn):
    # Measured in Live 12.4: a clip without an envelope doesn't reset the
    # parameter, so after the cut the next section would stay silent.
    c = conn({"get_session_snapshot": _snapshot(), "get_clip_automation": {"has_envelope": False}})
    out = json.loads(call(tools.automation_gesture, 0, 0, "drop_cut"))
    writes = [p for cmd, p in c.sent if cmd == "set_clip_automation"]
    assert writes[0]["mixer_parameter"] == "volume" and writes[0]["points"][-1]["value"] == 0.0
    assert writes[1]["clip_index"] == 1 and writes[1]["points"] == [{"time": 0.0, "value": 0.7}]
    assert out["held_at_rest"]["slots"] == [1]
    c = conn({"get_session_snapshot": _snapshot(), "get_clip_automation": {"has_envelope": False}})
    out = json.loads(call(tools.automation_gesture, 0, 0, "drop_cut", protect="no"))
    assert len([1 for cmd, _ in c.sent if cmd == "set_clip_automation"]) == 1
    assert "protect='yes'" in out["warning"]


def test_filter_rise_skips_a_highpass_and_uses_the_synth_filter(conn):
    devices = [{"index": 0, "name": "Drift", "class_name": "Drift"},
               {"index": 1, "name": "Auto Filter", "class_name": "AutoFilter2"}]
    params = {0: [{"index": 5, "name": "LP Freq", "value": 1000.0, "min": 20.0, "max": 20000.0}],
              1: [{"index": 1, "name": "Frequency", "value": 0.3, "min": 0.0, "max": 1.0},
                  {"index": 4, "name": "Filter Type", "value": 1.0, "display": "High-pass"}]}
    c = conn({"get_session_snapshot": _snapshot(devices),
              "get_device_parameters": lambda p: {"device": {"parameters": params[p["device_index"]]}},
              "get_clip_automation": {"has_envelope": False}})
    out = json.loads(call(tools.automation_gesture, 0, 1, "filter_rise"))
    w = [p for cmd, p in c.sent if cmd == "set_clip_automation"][0]
    assert (w["device_index"], w["parameter_index"]) == (0, 5) and out["parameter"] == "LP Freq"
    assert w["points"][0]["value"] == pytest.approx(20 + 0.3 * 980) and w["points"][-1]["value"] == 1000.0


def test_a_missing_return_is_explained(conn):
    snap = _snapshot()
    snap["return_tracks"] = [{"name": "A"}, {"name": "B"}]
    conn({"get_session_snapshot": snap})
    assert "send:N" in call(tools.automation_gesture, 0, 0, "reverb_swell")
