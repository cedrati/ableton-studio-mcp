"""Structured humanization: quasi-periodic rhythms and micro-variations."""

import json
import math

import pytest

from ableton_studio_mcp import live, tools
from ableton_studio_mcp import music_theory as mt
from ableton_studio_mcp import quasiperiodic as qp
from test_clip_notes import call
from test_drums import KIT_909, _Conn


# ------------------------------------------------------------- pure module

def test_rotations():
    assert qp.ROTATIONS["cedra"] == pytest.approx(0.6170062246713689)
    assert qp.resolve_rotation("golden") == pytest.approx((math.sqrt(5) - 1) / 2)
    assert qp.resolve_rotation(1.25) == pytest.approx(0.25)
    with pytest.raises(qp.QuasiPeriodicError):
        qp.resolve_rotation("unknown")
    with pytest.raises(qp.QuasiPeriodicError):
        qp.resolve_rotation(2)


def test_cedra_near_periods_are_its_convergents():
    assert qp.continued_fraction(qp.ROTATIONS["cedra"], 9) == [0, 1, 1, 1, 1, 1, 1, 3, 29]
    assert qp.near_periods("cedra", 2000) == [2, 3, 5, 8, 13, 47, 1376, 1423]
    assert qp.near_periods("golden", 100) == [2, 3, 5, 8, 13, 21, 34, 55, 89]


def test_sturmian_word_is_balanced_and_aperiodic():
    w = qp.word(2000)
    assert w[:20] == [0, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1]
    hits = [i for i, b in enumerate(w) if b]
    assert {b - a for a, b in zip(hits, hits[1:])} == {1, 2}
    # balanced: any two windows of the same length differ by at most one hit
    for k in (5, 13, 47):
        counts = {sum(w[i:i + k]) for i in range(len(w) - k)}
        assert max(counts) - min(counts) <= 1
    # factor complexity n + 1 (Sturmian)
    s = "".join(map(str, w))
    assert len({s[i:i + 10] for i in range(len(s) - 10)}) == 11


def test_other_density_keeps_at_most_three_gaps():
    w = qp.word(5000, density=0.3, rotation="cedra")
    hits = [i for i, b in enumerate(w) if b]
    assert len({b - a for a, b in zip(hits, hits[1:])}) <= 3
    assert sum(w) / len(w) == pytest.approx(0.3, abs=0.01)
    with pytest.raises(qp.QuasiPeriodicError):
        qp.word(10, density=1.0)


def test_seam_mismatch_formula_and_near_period_loops():
    w = qp.word(1376 + 1376)
    measured = sum(a != b for a, b in zip(w, w[1376:])) / 1376
    assert measured == pytest.approx(qp.seam_mismatch(1376), abs=2e-3)
    assert qp.seam_mismatch(1376) < 0.002 < 0.1 < qp.seam_mismatch(64)


def test_rhythm_notes_dynamics_and_accents():
    r = qp.rhythm_notes(128, 42, accent_pitch=37, accent_near_period=13)
    hats = [n for n in r["notes"] if n["pitch"] == 42]
    rims = [n for n in r["notes"] if n["pitch"] == 37]
    assert len(hats) == r["hits"] and len(rims) == r["accents"] > 0
    assert r["gap_sizes"] == [1, 2]
    assert all(50 <= n["velocity"] <= 95 for n in hats)
    assert len({n["velocity"] for n in hats}) > 20           # dynamics never settle
    assert all(n["start_time"] == pytest.approx(round(n["start_time"] * 4) / 4) for n in r["notes"])


def test_humanize_structured_is_bounded_deterministic_and_keeps_chords():
    notes = [{"pitch": p, "start_time": t, "duration": 0.25, "velocity": 100}
             for t in [i * 0.25 for i in range(64)] for p in (60, 64)]
    out = qp.humanize_structured(notes, timing=0.02, velocity=10, duration=0.2)
    assert out == qp.humanize_structured(notes, timing=0.02, velocity=10, duration=0.2)
    assert out != qp.humanize_structured(notes, timing=0.02, velocity=10, duration=0.2, phase=0.3)
    for a, b in zip(notes, out):
        assert abs(b["start_time"] - a["start_time"]) <= 0.02 + 1e-9
        assert abs(b["velocity"] - a["velocity"]) <= 10
        assert 0.2 <= b["duration"] <= 0.3
    by_onset = {}
    for a, b in zip(notes, out):
        by_onset.setdefault(a["start_time"], set()).add(round(b["start_time"], 9))
    assert all(len(v) == 1 for v in by_onset.values())    # a chord moves as one


def test_humanize_structured_dimensions_are_uncorrelated():
    notes = [{"pitch": 60, "start_time": i * 0.25, "duration": 0.2, "velocity": 64} for i in range(2000)]
    out = qp.humanize_structured(notes, timing=1.0, velocity=50, drift=0.0)
    dt = [b["start_time"] - a["start_time"] for a, b in zip(notes, out)]
    dv = [b["velocity"] - a["velocity"] for a, b in zip(notes, out)]
    mt_, mv = sum(dt) / len(dt), sum(dv) / len(dv)
    cov = sum((x - mt_) * (y - mv) for x, y in zip(dt, dv))
    corr = cov / math.sqrt(sum((x - mt_) ** 2 for x in dt) * sum((y - mv) ** 2 for y in dv))
    assert abs(corr) < 0.05


def test_transform_clip_operation():
    notes = [{"pitch": 60, "start_time": i * 0.5, "duration": 0.25, "velocity": 90} for i in range(16)]
    out = mt.apply_operations(notes, [{"op": "humanize_structured", "timing": 0.01, "velocity": 6}])
    assert len(out) == 16 and out != notes
    assert "humanize_structured" in mt.OPERATIONS


# --------------------------------------------------------------------- tool

@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setattr(live, "require", lambda name: None)

    def make(answers):
        c = _Conn(answers)
        monkeypatch.setattr(live, "client", lambda: c)
        return c
    return make


def test_quasiperiodic_rhythm_tool_maps_roles_and_writes(conn):
    c = conn({"get_drum_rack_map": {"rack_name": "909 Core Kit", "pads": KIT_909},
              "get_track_info": {"clip_slots": [{"has_clip": False}] * 4}})
    out = json.loads(call(tools.quasiperiodic_rhythm, 0, 2, role="closed_hat", bars=4,
                          accent_role="rim"))
    assert out["note"] == 42 and out["accent_note"] == 37
    assert out["steps"] == 64 and out["length_beats"] == 16.0
    assert out["gap_sizes_in_steps"] == [1, 2] and out["near_periods"][:6] == [2, 3, 5, 8, 13, 47]
    assert ("create_clip", {"track_index": 0, "clip_index": 2, "length": 16.0}) in c.sent
    written = [n for cmd, p in c.sent if cmd == "add_notes_to_clip" for n in p["notes"]]
    assert len(written) == out["hits"] + out["accents"]


def test_quasiperiodic_rhythm_near_period_length_and_refusals(conn):
    conn({"get_drum_rack_map": {"pads": KIT_909}, "get_track_info": {"clip_slots": [{"has_clip": True}]}})
    assert "replace=true" in call(tools.quasiperiodic_rhythm, 0, 0)
    conn({"get_drum_rack_map": {"pads": [{"note": 36, "name": "Kick"}]},
          "get_track_info": {"clip_slots": [{"has_clip": False}]}})
    assert "No pad" in call(tools.quasiperiodic_rhythm, 0, 0, role="closed_hat")
    c = conn({"get_drum_rack_map": {"pads": KIT_909}, "get_track_info": {"clip_slots": [{"has_clip": False}]}})
    out = json.loads(call(tools.quasiperiodic_rhythm, 0, 0, role="42", length_steps=47))
    assert out["steps"] == 47 and out["length_beats"] == 11.75 and out["mapping"] == "note"
    assert ("create_clip", {"track_index": 0, "clip_index": 0, "length": 11.75}) in c.sent
