"""Chopping samples: tempo and key from names, chop patterns, and the tool."""

import json

import pytest

from ableton_studio_mcp import chops, live, tools
from test_clip_notes import call


def test_tempo_and_key_from_splice_style_names():
    assert chops.tempo_from_name("dhs_127_vocal_loop_moov_Fmin.wav") == 127
    assert chops.tempo_from_name("SS_UAH2_122_guitar_electric_smile_muted_melody_D#min.wav") == 122
    assert chops.tempo_from_name("loop 120bpm.wav") == 120
    assert chops.tempo_from_name("KA_LHV_wet_vocal_one_shot_uh.wav") is None
    assert chops.key_from_name("dhs_127_vocal_loop_moov_Fmin.wav") == {"root": "F", "minor": True}
    assert chops.key_from_name("x_D#min.wav") == {"root": "D#", "minor": True}
    assert chops.key_from_name("pad_Ebmaj.wav") == {"root": "D#", "minor": False}
    assert chops.key_from_name("VOX_LCH_128_top_tribal.wav") is None


def test_transpose_the_shortest_way_and_warp_to_whole_bars():
    assert chops.transpose_to("D#", "F") == 2
    assert chops.transpose_to("C", "A") == -3
    assert chops.transpose_to("F", "F") == 0
    assert chops.warp_beats(7.559, 127) == 16      # a 4-bar loop at 127 BPM
    assert chops.warp_beats(15.738, 122) == 32
    assert chops.warp_beats(5.0, None) is None


def test_hook_repeats_the_same_grain_at_the_same_place():
    notes = chops.chop_pattern(64, "hook", bars=4, micro=True, seed=3)
    by_bar = [{round(n["start_time"] % 4, 3): n["pitch"] for n in notes if int(n["start_time"] // 4) == b}
              for b in range(3)]
    assert by_bar[0] == by_bar[1] == by_bar[2]      # a hook, not noise
    assert all(36 <= n["pitch"] < 100 for n in notes)
    assert any("probability" in n for n in notes)  # ghost hits breathe
    assert all(n["duration"] <= 0.1 for n in notes)  # micro-chops are short


def test_other_styles_and_errors():
    re = chops.chop_pattern(16, "rearrange", bars=2, seed=1)
    assert re and max(n["start_time"] for n in re) < 8
    st = chops.chop_pattern(16, "stutter", bars=2)
    assert [n["pitch"] for n in st[:4]] == [36, 37, 38, 39]
    assert sum(1 for n in st if 3.5 <= n["start_time"] < 4) == 4   # ratchet at the bar's end
    with pytest.raises(chops.ChopError):
        chops.chop_pattern(16, "jazz")


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
        monkeypatch.setattr(live, "call", c.call)
        return c
    return make


def test_chop_sample_warps_transposes_and_writes(conn, tmp_path):
    f = tmp_path / "dhs_127_vocal_loop_moov_D#min.wav"
    f.write_bytes(b"RIFF")
    track = {"devices": [{"index": 0, "class_name": "OriginalSimpler"}],
             "clip_slots": [{"index": 0, "has_clip": True}, {"index": 1, "has_clip": False}]}
    c = conn({"get_track_info": track,
              # Live 12.4: the load reply has no length; the configure reply does
              "simpler_replace_sample": {"loaded": str(f)},
              "simpler_configure": {"simpler": {"sample": {"length_frames": 333355, "sample_rate": 44100}}},
              "get_song_scale": {"root_name": "F", "scale_mode": True},
              "set_device_parameters": {"changes": []}})
    out = json.loads(call(tools.chop_sample, 0, str(f), mode="micro"))
    cfg = [p["settings"] for cmd, p in c.sent if cmd == "simpler_configure"]
    assert cfg == [{"playback_mode": "slicing", "slicing_style": "region", "slicing_region_count": 64},
                   {"warp_as": 16}]
    assert out["warped_as_beats"] == 16
    vals = [p for cmd, p in c.sent if cmd == "set_device_parameters"][0]["values"]
    assert vals["Transpose"] == "+2 st" and vals["Trigger Mode"] == "Gate"
    assert [p for cmd, p in c.sent if cmd == "create_clip"][0] == {"track_index": 0, "clip_index": 1,
                                                                  "length": 16.0}
    assert out["transposed"].startswith("+2") and out["notes"] > 0


def test_chop_sample_refuses_a_missing_file_and_a_full_slot(conn, tmp_path):
    conn({})
    assert "No file" in call(tools.chop_sample, 0, "/nope.wav")
    f = tmp_path / "a.wav"
    f.write_bytes(b"RIFF")
    conn({"get_track_info": {"devices": [{"index": 0, "class_name": "OriginalSimpler"}],
                             "clip_slots": [{"index": 0, "has_clip": True}]},
          "set_device_parameters": {}})
    assert "already has a clip" in call(tools.chop_sample, 0, str(f), clip_index=0)
