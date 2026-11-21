"""Long-form evolution curves, clip tiling, arrangement templates and plans."""

import json

import pytest

import MCP_Server.server as server
from MCP_Server import arrangement as ar
from test_clip_notes import call


def test_curve_shapes():
    lin = ar.curve_points(16, 0.0, 1.0, "linear", resolution=4)
    assert [p["value"] for p in lin] == [0.0, 0.25, 0.5, 0.75, 1.0]
    exp = ar.curve_points(16, 0.0, 1.0, "exp", resolution=4)
    assert exp[2]["value"] < 0.5 and exp[-1]["value"] == 1.0  # slow start: a build-up
    log = ar.curve_points(16, 0.0, 1.0, "log", resolution=4)
    assert log[2]["value"] > 0.5
    swell = ar.curve_points(16, 0.0, 1.0, "swell", resolution=4)
    assert swell[0]["value"] == 0 and swell[2]["value"] == 1.0 and abs(swell[-1]["value"]) < 1e-6
    sine = ar.curve_points(16, 0.0, 1.0, "sine", resolution=2, cycles=2)
    assert [round(p["value"], 3) for p in sine][::2] == [0.0, 1.0, 0.0, 1.0, 0.0]
    steps = ar.curve_points(256, 0.2, 1.0, "steps", resolution=8, steps=8)
    assert len({p["value"] for p in steps}) == 8 and steps[-1]["value"] == 1.0
    walk = ar.curve_points(64, 0.0, 1.0, "random_walk", seed=4)
    assert walk == ar.curve_points(64, 0.0, 1.0, "random_walk", seed=4)
    assert ar.curve_points(8, 0, 1, offset=32, resolution=4)[0]["time"] == 32
    with pytest.raises(ar.ArrangementError):
        ar.curve_points(16, 0, 1, "zigzag")


def test_tile_notes_to_64_bars():
    loop = [{"pitch": 36, "start_time": k, "duration": 0.25, "velocity": 100, "mute": False,
             "probability": 0.5 if k == 3 else 1.0} for k in range(4)]
    tiled = ar.tile_notes(loop, 4.0, 256.0)
    assert len(tiled) == 256 and tiled[-1]["start_time"] == 255
    assert tiled[7]["probability"] == 0.5


def test_track_roles_from_names():
    tracks = [{"index": 0, "name": "Kick"}, {"index": 1, "name": "909 Hats"}, {"index": 2, "name": "Rumble"},
              {"index": 3, "name": "Acid 303"}, {"index": 4, "name": "Dub Chords"}, {"index": 5, "name": "Riser FX"},
              {"index": 6, "name": "Audio 7"}]
    assert ar.infer_track_roles(tracks) == {0: "kick", 1: "hats", 2: "rumble", 3: "bass", 4: "chords", 5: "fx"}


def test_templates_are_phrased_and_complete():
    for name, t in ar.TEMPLATES.items():
        for sec in t["sections"]:
            assert sec["bars"] % 8 == 0, (name, sec["name"])
            assert set(sec["roles"]) <= set(ar.ALL)
    assert sum(s["bars"] for s in ar.template_sections("techno_64")) == 64


TRACKS = [{"index": 0, "name": "Kick", "slots": {0: 16.0}},
          {"index": 1, "name": "Hats", "slots": {0: 4.0, 1: 64.0}},
          {"index": 2, "name": "Bass", "slots": {0: 16.0}},
          {"index": 3, "name": "Chords", "slots": {0: 12.0}}]


def test_plan_tiles_clips_and_reports_gaps():
    roles = ar.infer_track_roles(TRACKS)
    sections = [{"name": "Intro", "bars": 8, "roles": ["kick", "hats"]},
                {"name": "Drop", "bars": 16, "roles": ["kick", "hats", "bass", "chords"], "slots": {1: 1}}]
    plan = ar.plan_arrangement(sections, TRACKS, roles)
    intro = [p for p in plan["placements"] if p["start"] < 32]
    assert sorted((p["track_index"], p["start"]) for p in intro if p["track_index"] == 0) == [(0, 0.0), (0, 16.0)]
    assert len([p for p in intro if p["track_index"] == 1]) == 8
    drop_hats = [p for p in plan["placements"] if p["track_index"] == 1 and p["start"] >= 32]
    assert drop_hats == [{"track_index": 1, "clip_index": 1, "start": 32.0}]  # the 64-beat variant
    assert any("Chords" in w and "does not divide" in w for w in plan["warnings"])
    assert plan["locators"] == [{"beat": 0.0, "name": "Intro"}, {"beat": 32.0, "name": "Drop"}]
    assert plan["total_bars"] == 24


def test_activity_map():
    rows = ar.activity_map({"Kick": [{"start_time": 0, "end_time": 32}],
                            "Bass": [{"start_time": 32, "end_time": 64}]}, 32, 64)
    assert rows == {"Kick": "#.", "Bass": ".#"}


# ------------------------------------------------------------- server tools

class _Conn:
    def __init__(self, answers):
        self.answers, self.sent = answers, []

    def send_command(self, cmd, params=None):
        self.sent.append((cmd, params or {}))
        a = self.answers.get(cmd, {})
        return a(params or {}) if callable(a) else a


@pytest.fixture
def conn(monkeypatch):
    import MCP_Server.script_handshake as sh
    monkeypatch.setattr(sh, "require_capability", lambda name: None)

    def make(answers):
        c = _Conn(answers)
        monkeypatch.setattr(server, "get_ableton_connection", lambda: c)
        return c
    return make


def test_write_clip_evolution_extends_and_automates(conn):
    loop = [{"pitch": 36, "start_time": k, "duration": 0.25, "velocity": 100, "mute": False} for k in range(16)]
    c = conn({"get_clip_notes": {"length": 16.0, "notes": loop},
              "set_clip_automation": {"parameter": "Frequency"}})
    out = json.loads(call(server.write_clip_evolution, None, 2, 0, [
        {"device_index": 1, "parameter_index": 4, "start": 0.2, "end": 0.9, "shape": "exp"},
        {"mixer_parameter": "send:0", "start": 0.0, "end": 0.6, "shape": "swell", "from_bar": 32}], bars=64))
    assert out["extended_to_beats"] == 256 and out["notes_after_tiling"] == 256
    autos = [p for cmd, p in c.sent if cmd == "set_clip_automation"]
    assert autos[0]["points"][-1] == {"time": 256.0, "value": 0.9}
    assert autos[1]["points"][0] == {"time": 0.0, "value": 0.0} and autos[1]["points"][1]["time"] == 128.0
    assert ("set_clip_loop", {"track_index": 2, "clip_index": 0, "loop_start": 0.0, "loop_end": 256.0,
                              "end_marker": 256.0}) in c.sent


def _session(tracks):
    def track_info(p):
        t = tracks[p["track_index"]]
        return {"name": t["name"], "clip_slots": [
            {"index": s, "has_clip": True, "clip": {"length": L}} for s, L in t["slots"].items()]}
    return {"get_session_info": {"track_count": len(tracks), "signature_numerator": 4,
                                 "signature_denominator": 4, "is_playing": False},
            "get_track_info": track_info}


def test_build_arrangement_dry_run_and_build(conn):
    c = conn(_session(TRACKS))
    dry = json.loads(call(server.build_arrangement, None, template="techno_64", dry_run=True))
    assert dry["dry_run"] and dry["total_bars"] == 64
    assert dry["track_roles"] == {"Kick": "kick", "Hats": "hats", "Bass": "bass", "Chords": "chords"}
    assert not any(cmd == "duplicate_session_clip_to_arrangement" for cmd, _ in c.sent)
    out = json.loads(call(server.build_arrangement, None, template="techno_64",
                          section_slots={"Peak": {"1": 1}}))
    dups = [p for cmd, p in c.sent if cmd == "duplicate_session_clip_to_arrangement"]
    assert len(dups) == out["placements"] > 0
    assert any(p["track_index"] == 1 and p["clip_index"] == 1 for p in dups)
    assert out["locators_created"] == 6
