"""Drum programming: Euclidean rhythms, kit role mapping, grids, fills,
pattern library, server tools and the Live-side drum/groove commands."""

import json

import pytest

import ableton_studio_mcp.server as server
from ableton_studio_mcp import drums as d
from test_clip_notes import call
from test_remote_script_bridge import _load_script_module, make_instance

KIT_909 = [{"note": 36, "name": "Kick 909"}, {"note": 37, "name": "Rim 909"},
           {"note": 38, "name": "Snare 909"}, {"note": 39, "name": "Clap 909"},
           {"note": 42, "name": "Hihat Closed 909"}, {"note": 46, "name": "Hihat Open 909"},
           {"note": 49, "name": "Crash"}, {"note": 51, "name": "Ride 909"}, {"note": 45, "name": "Tom Low"}]


def test_euclidean_rhythms_are_the_canonical_ones():
    assert d.euclid(3, 8) == "x..x..x."          # tresillo
    assert d.euclid(5, 16) == "x...x..x..x..x.."
    assert d.euclid(4, 16) == "x...x...x...x..."  # four on the floor
    assert d.euclid(3, 8, rotate=1) == ".x..x..x"
    assert d.euclid(0, 8) == "........"
    with pytest.raises(d.DrumError):
        d.euclid(9, 8)


def test_roles_from_pad_names_english_and_french():
    roles = d.infer_roles(KIT_909)
    assert roles["kick"] == 36 and roles["closed_hat"] == 42 and roles["open_hat"] == 46
    assert roles["clap"] == 39 and roles["rim"] == 37 and roles["tom_low"] == 45
    fr = d.infer_roles([{"note": 36, "name": "Grosse caisse"}, {"note": 42, "name": "Charley"},
                        {"note": 46, "name": "Charley ouvert"}, {"note": 38, "name": "Caisse claire"}])
    assert fr == {"kick": 36, "closed_hat": 42, "open_hat": 46, "snare": 38}
    # Live's 808 Core Kit names
    core = d.infer_roles([{"note": 36, "name": "Bass Drum"}, {"note": 42, "name": "Closed Hi Hat"},
                          {"note": 46, "name": "Open Hi Hat"}, {"note": 39, "name": "Hand Clap"},
                          {"note": 48, "name": "Maracas"}, {"note": 50, "name": "Cow Bell"}])
    assert core == {"kick": 36, "closed_hat": 42, "open_hat": 46, "clap": 39, "shaker": 48, "cowbell": 50}


def test_notes_on_the_same_pad_and_step_are_merged():
    r = d.render({"closed_hat": "x...", "shaker": "X..."}, {"closed_hat": 42}, bars=1)
    hits = [n for n in r["notes"] if n["start_time"] == 0]
    # the louder of the two survives: shaker accent 124 x 0.8 level > hat 100 x 0.88
    assert len(hits) == 1 and hits[0]["velocity"] == int(124 * d.ROLE_LEVEL["shaker"])


def test_grid_language():
    notes = d.grid_notes("xXo.2?*", 36, 0.25)
    assert [round(n["start_time"], 3) for n in notes] == [0, 0.25, 0.5, 1.0, 1.125, 1.25, 1.5]
    assert notes[1]["velocity"] > notes[0]["velocity"] > notes[2]["velocity"]
    assert notes[5]["probability"] == 0.5 and notes[6]["probability"] == 0.25
    with pytest.raises(d.DrumError):
        d.grid_notes("x..z", 36, 0.25)


def test_render_with_a_kit_substitutes_and_reports():
    roles = d.infer_roles(KIT_909)
    r = d.render({"kick": "x...", "perc": "..x.", "cowbell": "...x", "rim": "x..."}, roles, bars=1)
    assert r["mapping"]["kick"] == {"note": 36, "source": "pad"}
    assert r["mapping"]["perc"]["note"] != 37  # rim is taken by its own layer: use another pad
    assert "cowbell" not in r["mapping"] or r["mapping"]["cowbell"]["source"] != "general_midi"
    # no General MIDI notes with a real kit (they would hit empty pads)
    assert all(n["pitch"] in {p["note"] for p in KIT_909} for n in r["notes"])


def test_render_without_kit_uses_general_midi():
    r = d.render({"kick": "x...", "cowbell": "..x."}, {}, bars=1)
    assert r["mapping"]["cowbell"] == {"note": 56, "source": "general_midi"}


def test_polyrhythm_drifts_across_bars():
    r = d.render({"perc": "x.." * 4}, {}, bars=2)  # a 12-step loop against 16-step bars
    starts = sorted(n["start_time"] for n in r["notes"])
    bar1 = [s for s in starts if s < 4]
    bar2 = [s - 4 for s in starts if s >= 4]
    assert bar1 != bar2


def test_swing_fills_variation():
    roles = d.infer_roles(KIT_909)
    straight = d.render({"closed_hat": "xxxxxxxxxxxxxxxx"}, roles, bars=1)["notes"]
    swung = d.render({"closed_hat": "xxxxxxxxxxxxxxxx"}, roles, bars=1, swing_pct=60)["notes"]
    assert swung[1]["start_time"] == pytest.approx(0.25 + 0.05) and swung[0]["start_time"] == 0
    assert straight[1]["start_time"] == 0.25
    layers = d.pattern_layers("techno_four")
    drop = d.render(layers, roles, bars=4, fill="drop")["notes"]
    assert not [n for n in drop if n["pitch"] == 36 and 14 <= n["start_time"] < 16]
    roll = d.render(layers, roles, bars=4, fill="roll")["notes"]
    assert len([n for n in roll if n["pitch"] == 39 and 15 <= n["start_time"] < 16]) == 4
    var = d.render(layers, roles, bars=4, variation=0.3, seed=1)["notes"]
    assert any(n.get("probability") == 0.35 for n in var)


@pytest.mark.parametrize("style", sorted(d.PATTERNS))
def test_every_library_pattern_renders(style):
    r = d.render(d.pattern_layers(style), d.infer_roles(KIT_909), bars=4)
    assert r["notes"] and r["length_beats"] == 16
    assert d.describe(style)["notes"]


# ----------------------------------------------------------- server tools

class _Conn:
    def __init__(self, answers):
        self.answers, self.sent = answers, []

    def send_command(self, cmd, params=None):
        self.sent.append((cmd, params or {}))
        a = self.answers.get(cmd, {})
        if isinstance(a, Exception):
            raise a
        return a(params or {}) if callable(a) else a


@pytest.fixture
def conn(monkeypatch):
    import ableton_studio_mcp.script_handshake as sh
    caps = {"value": None}
    monkeypatch.setattr(sh, "require_capability", lambda name: caps["value"](name) if caps["value"] else None)

    def make(answers, missing=()):
        caps["value"] = lambda name: ("missing " + name) if name in missing else None
        c = _Conn(answers)
        monkeypatch.setattr(server, "get_ableton_connection", lambda: c)
        return c
    return make


def test_write_drum_pattern_maps_the_kit(conn):
    c = conn({"get_drum_rack_map": {"rack_name": "909 Core Kit", "pads": KIT_909},
              "get_track_info": {"clip_slots": [{"has_clip": False}] * 4}})
    out = json.loads(call(server.write_drum_pattern, None, 0, 1, style="techno_rolling", bars=2,
                          layers={"cowbell": {"euclid": [3, 8, 0]}, "rim": None}))
    assert out["kit"] == "909 Core Kit" and out["swing_pct"] == 52
    assert "rim" not in out["grids"] and out["grids"]["cowbell"] == "x..x..x."
    assert ("create_clip", {"track_index": 0, "clip_index": 1, "length": 8.0}) in c.sent
    written = [n for cmd, p in c.sent if cmd == "add_notes_to_clip" for n in p["notes"]]
    assert len(written) == out["notes_written"] and {36, 42, 46} <= {n["pitch"] for n in written}


def test_write_drum_pattern_refuses_to_overwrite(conn):
    conn({"get_drum_rack_map": {"pads": KIT_909}, "get_track_info": {"clip_slots": [{"has_clip": True}]}})
    assert "replace=true" in call(server.write_drum_pattern, None, 0, 0, style="techno_four")


def test_old_script_gets_no_probability_and_gm_notes(conn):
    c = conn({"get_track_info": {"clip_slots": [{"has_clip": False}]}},
             missing=("get_drum_rack_map", "note_probability"))
    out = json.loads(call(server.write_drum_pattern, None, 0, 0, style="minimal_techno"))
    assert out["kit"].startswith("no Drum Rack") and out["with_probability"] == 0
    written = [n for cmd, p in c.sent if cmd == "add_notes_to_clip" for n in p["notes"]]
    assert not any("probability" in n for n in written)


def test_drum_patterns_tool():
    assert json.loads(call(server.drum_patterns, None, euclid_hits=3, euclid_steps=8))["grid"] == "x..x..x."
    assert any(p["style"] == "techno_hypnotic" for p in json.loads(call(server.drum_patterns, None)))


# ------------------------------------------------------- Live-side commands

@pytest.fixture(scope="module")
def script_module():
    return _load_script_module()


class Pad:
    def __init__(self, note, name, filled=True):
        self.note, self.name = note, name
        self.chains = [type("C", (), {"devices": [type("D", (), {"name": "Simpler"})()]})()] if filled else []
        self.mute = self.solo = False


class Rack:
    can_have_drum_pads, can_have_chains, name = True, True, "909 Core Kit"

    def __init__(self):
        self.drum_pads = [Pad(n, "Pad %d" % n, filled=False) for n in range(128)]
        for p in KIT_909:
            self.drum_pads[p["note"]] = Pad(p["note"], p["name"])


class Groove:
    def __init__(self, name):
        self.name, self.base = name, 1.0
        self.timing_amount, self.random_amount, self.velocity_amount, self.quantization_amount = 100.0, 0.0, 0.0, 0.0


class Clip:
    is_midi_clip, name, groove = True, "beat", None

    def __init__(self):
        self.added = None

    def add_new_notes(self, specs):
        self.added = specs


def _live(script_module):
    track = type("T", (), {})()
    track.name, track.devices = "Drums", [Rack()]
    slot = type("S", (), {"has_clip": True, "clip": Clip()})()
    track.clip_slots = [slot]
    song = type("Song", (), {})()
    song.tracks, song.return_tracks = [track], []
    song.groove_pool = type("GP", (), {"grooves": [Groove("MPC 16 Swing-58"), Groove("Logic Swing 8")]})()
    song.groove_amount = 1.0
    inst = make_instance(script_module)
    inst._song = song
    return inst, slot.clip


def test_drum_rack_map_lists_filled_pads(script_module):
    inst, _ = _live(script_module)
    out = inst._get_drum_rack_map(0)
    assert out["rack_name"] == "909 Core Kit" and len(out["pads"]) == len(KIT_909)
    assert out["pads"][0] == {"note": 36, "name": "Kick 909", "devices": ["Simpler"], "mute": False, "solo": False}


def test_groove_pool_and_clip_groove(script_module):
    inst, clip = _live(script_module)
    pool = inst._get_groove_pool()
    assert [g["name"] for g in pool["grooves"]] == ["MPC 16 Swing-58", "Logic Swing 8"]
    assert inst._set_clip_groove(0, 0, 0)["groove"]["name"] == "MPC 16 Swing-58"
    assert clip.groove.name == "MPC 16 Swing-58"
    assert inst._set_clip_groove(0, 0, None)["groove"] is None and clip.groove is None
    out = inst._set_groove_params(1, {"timing_amount": 70.0}, global_amount=0.8)
    assert out["groove"]["timing_amount"] == 70.0 and out["global_amount"] == 0.8
    with pytest.raises(ValueError):
        inst._set_groove_params(1, {"swing": 1})


def test_notes_with_probability_use_the_extended_api(script_module, monkeypatch):
    inst, clip = _live(script_module)

    class Spec:
        def __init__(self, **kw):
            self.kw = kw
    monkeypatch.setattr(script_module, "MidiNoteSpecification", Spec)
    inst._midi_clip = lambda t, c, loc: (clip, "session clip 0/0")
    inst._clip_location_info = lambda c, loc: {}
    inst._add_notes_to_clip(0, 0, [{"pitch": 42, "start_time": 0.5, "duration": 0.2, "velocity": 50,
                                    "probability": 0.25}])
    assert clip.added[0].kw["probability"] == 0.25 and clip.added[0].kw["pitch"] == 42
