"""Scales, chords, key/chord detection, transformations, progressions, styles."""

import pytest

from MCP_Server import music_styles as ms
from MCP_Server import music_theory as mt


def N(pitch, start, dur=1.0, vel=100):
    return {"pitch": pitch, "start_time": start, "duration": dur, "velocity": vel, "mute": False}


def scale_run(root_pitch, scale, beats=1.0):
    ivs = mt.SCALES[mt.scale_key(scale)]["intervals"]
    return [N(root_pitch + i, k * beats) for k, i in enumerate(list(ivs) + [12])]


# ------------------------------------------------------------- scales/chords

def test_scale_spelling_and_aliases():
    assert mt.scale_info("D", "dorian")["notes"] == ["D", "E", "F", "G", "A", "B", "C"]
    assert mt.scale_info("Eb", "major")["notes"] == ["Eb", "F", "G", "Ab", "Bb", "C", "D"]
    assert mt.scale_key("Phrygian Dominant") == mt.scale_key("hijaz") == "phrygian_dominant"
    assert mt.scale_key("aeolian") == "minor"
    with pytest.raises(mt.TheoryError):
        mt.scale_key("lydian flat 13 imaginary")


def test_every_scale_is_well_formed():
    for key, s in mt.SCALES.items():
        ivs = s["intervals"]
        assert ivs[0] == 0 and list(ivs) == sorted(set(ivs)) and ivs[-1] < 12, key
        if s["characteristic"] is not None:
            assert s["characteristic"] in ivs, key


def test_diatonic_chords_of_c_major_and_a_harmonic_minor():
    c = mt.diatonic_chords("C", "major")
    assert [x["roman"] for x in c] == ["Imaj7", "ii7", "iii7", "IVmaj7", "V7", "vi7", "viiø7"]
    assert c[4]["symbol"] == "G7" and c[4]["function"] == "dominante"
    a = mt.diatonic_chords("A", "harmonic_minor", sevenths=False)
    assert [x["triad"] for x in a] == ["Am", "Bdim", "Caug", "Dm", "E", "F", "G#dim"]


def test_relative_modes_listed():
    same = mt.scale_info("C", "major")["same_notes_as"]
    assert "D dorian" in same and "A minor" in same and "B locrian" in same


def test_parse_chord_and_numerals():
    assert mt.parse_chord("Bbmaj7/D")[:2] == (10, "maj7")
    assert mt.parse_chord("F#ø")[1] == "m7b5"
    chords = mt.progression("C", "major", ["ii7", "V7", "Imaj7", "bVII", "iv", "V/V", "N6"])
    assert [c["symbol"] for c in chords] == ["Dm7", "G7", "Cmaj7", "A#", "Fm", "D", "C#/F"]
    minor = mt.progression("A", "minor", ["i", "VI", "III", "VII", "V7"])
    assert [c["symbol"] for c in minor] == ["Am", "F", "C", "G", "E7"]


# --------------------------------------------------------------- detection

def test_detect_key_major_and_harmonic_minor():
    assert mt.detect_key(scale_run(60, "major"))["best"]["root"] == "C"
    cm = mt.detect_key(scale_run(57, "harmonic_minor") + [N(57, 9, 4), N(45, 9, 4)])["best"]
    assert (cm["root"], cm["scale"]) == ("A", "harmonic_minor")


def test_detect_dorian_vamp():
    notes = []
    for bar in range(4):  # D dorian vamp: Dm7 - G (the B natural)
        t = bar * 8
        notes += [N(p, t, 4) for p in (38, 50, 53, 57, 60)] + [N(p, t + 4, 4) for p in (43, 55, 59, 62)]
        notes += [N(62, t, 1), N(64, t + 1, 1), N(65, t + 2, 1), N(71, t + 3, 1)]
    best = mt.detect_key(notes)["best"]
    assert (best["root"], best["scale"]) == ("D", "dorian")


def test_chord_detection_and_analysis():
    notes = [N(p, 0, 4) for p in (48, 64, 67, 71)] + [N(p, 4, 4) for p in (43, 65, 67, 71, 74)]
    a = mt.analyze_notes(notes, segment_beats=4)
    assert [c["chord"] for c in a["chords"]] == ["Cmaj7", "G7"]
    ninth = notes + [N(69, 4, 4)]  # add the A: G9 in the jazz vocabulary only
    assert [c["chord"] for c in mt.analyze_notes(ninth, 4, vocabulary="jazz")["chords"]] == ["Cmaj7", "G9"]
    assert [c["chord"] for c in mt.analyze_notes(ninth, 4)["chords"]] == ["Cmaj7", "G7"]
    assert [c["roman"] for c in a["chords"]] == ["Imaj7", "V7"]
    assert a["range"]["lowest"] == "G2"


# ------------------------------------------------------------- transforms

def test_change_mode_major_to_dorian_and_minor():
    run = scale_run(60, "major")
    dor = mt.change_mode(run, "C", "major", "dorian")
    assert [n["pitch"] for n in dor] == [60, 62, 63, 65, 67, 69, 70, 72]
    minor = mt.change_mode(run, "C", "major", "minor")
    assert [n["pitch"] for n in minor] == [60, 62, 63, 65, 67, 68, 70, 72]


def test_diatonic_transpose_and_snap():
    up3 = mt.transpose_diatonic([N(60, 0), N(64, 1), N(67, 2)], 2, "C", "major")
    assert [n["pitch"] for n in up3] == [64, 67, 71]
    snapped = mt.snap_to_scale([N(61, 0), N(66, 1)], "C", "major")
    assert [n["pitch"] for n in snapped] == [60, 65]  # ties go down
    assert [n["pitch"] for n in mt.snap_to_scale([N(61, 0)], "C", "major", "up")] == [62]


def test_invert_retrograde_and_time():
    inv = mt.invert([N(64, 0), N(67, 1)], "C4")
    assert [n["pitch"] for n in inv] == [56, 53]
    dia = mt.invert([N(64, 0)], 60, root="C", scale="major")
    assert dia[0]["pitch"] == 57  # E mirrored around C by scale steps -> A
    ret = mt.retrograde([N(60, 0, 1), N(62, 1, 2)])
    assert [(n["pitch"], n["start_time"]) for n in ret] == [(62, 0.0), (60, 2.0)]
    assert mt.time_scale([N(60, 1, 1)], 2)[0]["start_time"] == 2


def test_swing_quantize_humanize():
    straight = [N(60, k * 0.5, 0.5) for k in range(4)]
    sw = mt.swing(straight, 66.7, 0.5)
    assert [round(n["start_time"], 3) for n in sw] == [0.0, 0.667, 1.0, 1.667]
    q = mt.quantize([N(60, 0.27), N(62, 0.49)], 0.25)
    assert [n["start_time"] for n in q] == [0.25, 0.5]
    h1 = mt.humanize(straight, seed=3)
    assert h1 == mt.humanize(straight, seed=3) and h1 != straight


def test_harmonize_arpeggiate_strum_voicing():
    h = mt.harmonize([N(60, 0)], "C", "major", steps=(2, 4))
    assert sorted(n["pitch"] for n in h) == [60, 64, 67]
    arp = mt.arpeggiate([N(p, 0, 1) for p in (60, 64, 67)], rate=0.25, pattern="updown")
    assert [n["pitch"] for n in arp] == [60, 64, 67, 64]
    st = mt.strum([N(p, 0, 1) for p in (60, 64, 67)], spread=0.05)
    assert [round(n["start_time"], 2) for n in sorted(st, key=lambda n: n["pitch"])] == [0.0, 0.05, 0.1]
    drop2 = mt.voice_chords([N(p, 0) for p in (48, 52, 55, 59)], "drop2")
    assert sorted(n["pitch"] for n in drop2) == [43, 48, 52, 59]


def test_apply_operations_chain():
    out = mt.apply_operations(scale_run(60, "major", 0.5), [
        {"op": "change_mode", "root": "C", "from_scale": "major", "to_scale": "phrygian"},
        {"op": "transpose", "semitones": 2},
        {"op": "swing", "amount_pct": 60}])
    assert out[0]["pitch"] == 62 and out[1]["pitch"] == 63
    with pytest.raises(mt.TheoryError):
        mt.apply_operations([N(60, 0)], [{"op": "explode"}])


# ------------------------------------------------------------ progressions

def test_render_progression_voice_leads_smoothly():
    chords = mt.progression("C", "major", ["I", "vi", "IV", "V"])
    notes = mt.render_progression(chords, pattern="block", bass=False, voices=3)
    bars = [sorted(n["pitch"] for n in notes if n["start_time"] == b * 4) for b in range(4)]
    moves = [sum(abs(a - b) for a, b in zip(x, y)) for x, y in zip(bars, bars[1:])]
    assert all(m <= 8 for m in moves), bars  # common tones kept, small steps


@pytest.mark.parametrize("pattern", sorted(mt.PATTERNS))
def test_every_pattern_renders(pattern):
    chords = mt.progression("A", "minor", ["i", "iv", "V7", "i"])
    notes = mt.render_progression(chords, pattern=pattern)
    assert notes and all(0 <= n["pitch"] <= 127 for n in notes)
    assert max(n["start_time"] for n in notes) < 16


def test_substitutions():
    subs = [s["chord"] for s in mt.substitutions("G7", "C")]
    assert "C#7" in subs  # tritone substitution
    assert any("Fm" == s for s in [x["chord"] for x in mt.substitutions("F", "C")])


# ------------------------------------------------------------------ styles

def test_styles_are_consistent():
    for key, st in ms.STYLES.items():
        for scale in st["scales"]:
            mt.scale_key(scale)
        for prog in st["progressions"]:
            mt.progression("C", st["scales"][0], prog)
        for p in st["patterns"]:
            assert p in mt.PATTERNS, (key, p)
    assert ms.style_key("Bach") == "baroque" and ms.style_key("lo-fi") == "lofi"


# ------------------------------------------------------------ server tools

import json

import MCP_Server.server as server
from test_clip_notes import call


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


def test_scale_and_style_tools():
    info = json.loads(call(server.music_scales, None, root="E", scale="phrygian dominant"))
    assert info["notes"] == ["E", "F", "G#", "A", "B", "C", "D"] and info["live_scale_name"] == "Phrygian Dominant"
    assert any(s["scale"] == "phrygian_dominant" for s in json.loads(call(server.music_scales, None, query="flamenco")))
    assert json.loads(call(server.music_styles, None, style="Bach"))["style"] == "baroque"
    ideas = json.loads(call(server.music_chord_ideas, None, "G7", key_root="C"))
    assert ideas["roman_in_key"] == "V7" and ideas["notes"] == ["G", "B", "D", "F"]


def test_transform_clip_into_new_slot(conn):
    src = [N(60 + i, k * 0.5, 0.5) for k, i in enumerate((0, 2, 4, 5, 7, 9, 11, 12))]
    c = conn({"get_clip_notes": {"notes": src, "length": 4.0, "clip_name": "run"}})
    out = json.loads(call(server.transform_clip, None, 0, 0,
                          [{"op": "change_mode", "root": "C", "from_scale": "major", "to_scale": "dorian"}],
                          target_clip_index=1))
    assert out["written_to"] == "slot 1"
    assert ("create_clip", {"track_index": 0, "clip_index": 1, "length": 4.0}) in c.sent
    written = [n["pitch"] for cmd, p in c.sent if cmd == "add_notes_to_clip" for n in p["notes"]]
    assert written == [60, 62, 63, 65, 67, 69, 70, 72]
    assert not any(cmd == "clear_notes_from_clip" for cmd, _ in c.sent)


def test_transform_clip_in_place_clears_first(conn):
    c = conn({"get_clip_notes": {"notes": [N(60, 0)], "length": 4.0}})
    call(server.transform_clip, None, 2, 3, [{"op": "transpose", "semitones": 5}])
    cmds = [cmd for cmd, _ in c.sent]
    assert cmds[:3] == ["get_clip_notes", "clear_notes_from_clip", "add_notes_to_clip"]


def test_write_progression_from_style(conn):
    c = conn({"get_track_info": {"clip_slots": [{"has_clip": False}] * 4}})
    out = json.loads(call(server.write_progression, None, 1, 0, "A", style="house", repeat=2))
    assert out["key"] == "A minor" and out["pattern"] == "offbeat"
    assert [ch["symbol"] for ch in out["chords"]] == ["Am7", "Dm7", "Am7", "Dm7"]
    assert ("create_clip", {"track_index": 1, "clip_index": 0, "length": 32.0}) in c.sent


def test_set_song_scale_maps_names(conn):
    c = conn({"set_song_scale": {"scale_name": "Phrygian Dominant"}})
    call(server.set_song_scale, None, root="E", scale="hijaz")
    assert c.sent[-1] == ("set_song_scale", {"root_note": 4, "scale_name": "Phrygian Dominant"})
    assert "Live has no" in call(server.set_song_scale, None, scale="bebop dominant")



def test_counterpoint_with_picardy_ending_reads_minor():
    """A two-voice C minor line over a pedal ending on a long C major chord:
    the held Picardy third must not turn the key major."""
    line = [N(p, i * 0.25, 0.25) for i, p in enumerate([72, 75, 74, 72, 71, 72, 74, 67] * 8)]
    bass = [N(48, 0, 8), N(43, 8, 8)]
    final = [N(p, 16, 12) for p in (48, 55, 60, 64, 67, 72)]
    key = mt.analyze_notes(line + bass + final)["key"]["best"]
    assert key["root"] == "C" and "minor" in key["scale"]



def test_arpeggio_stops_at_the_next_chord():
    notes = [N(36, 0, 4)] + [N(p, 0, 1) for p in (60, 64, 67)] + [N(p, 1, 1) for p in (62, 65, 69)]
    arp = mt.arpeggiate(notes, rate=0.25)
    first = [n for n in arp if n["start_time"] < 1]
    assert [n["pitch"] for n in first] == [36, 60, 64, 67]
    assert all(n["start_time"] + n["duration"] <= 1.0 + 1e-6 for n in first)
