"""MIDI file reader and audio analysis (Remote Script 1.12.0 server tools).

Files are built byte by byte in a temp dir: no fixtures on disk, no Ableton.
"""

import math
import struct
import wave

import pytest

from ableton_studio_mcp.audio_analysis import AudioFileError, analyze_audio, read_audio
from ableton_studio_mcp.midi_file import MidiFileError, read_midi_file, select_notes, summarize


# ------------------------------------------------------------------ MIDI

def _vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def _track(events):
    body = b"".join(_vlq(dt) + data for dt, data in events) + b"\x00\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(body)) + body


def _smf(tracks, fmt=1, division=480):
    return (b"MThd" + struct.pack(">IHHH", 6, fmt, len(tracks), division)
            + b"".join(tracks))


@pytest.fixture
def midi_path(tmp_path):
    name = b"Melodie"
    t0 = _track([(0, b"\xff\x51\x03\x07\xa1\x20")])  # tempo only
    t1 = _track([
        (0, b"\xff\x03" + bytes([len(name)]) + name),
        (0, b"\x90\x3c\x64"),        # C4 on, beat 0
        (480, b"\x3e\x50"),          # running status: D4 on, beat 1
        (0, b"\x3c\x00"),            # C4 off by velocity 0, beat 1
        (240, b"\x80\x3e\x00"),      # D4 off, beat 1.5
        (0, b"\x91\x24\x70"),        # channel 1: C2 on
        (960, b"\x81\x24\x00"),      # off at beat 3.5
    ])
    p = tmp_path / "test.mid"
    p.write_bytes(_smf([t0, t1]))
    return str(p)


def test_reads_notes_in_beats_with_running_status(midi_path):
    parsed = read_midi_file(midi_path)
    assert parsed["format"] == 1 and parsed["division"] == 480
    notes = sorted(parsed["tracks"][1]["notes"], key=lambda n: (n["start_time"], n["pitch"]))
    assert [(n["pitch"], n["start_time"], n["duration"], n["channel"]) for n in notes] == [
        (60, 0.0, 1.0, 0), (62, 1.0, 0.5, 0), (36, 1.5, 2.0, 1)]
    assert parsed["tracks"][1]["name"] == "Melodie"


def test_select_filters_channel_and_transposes(midi_path):
    parsed = read_midi_file(midi_path)
    notes = select_notes(parsed, channel=0, transpose=12)
    assert [(n["pitch"], n["start_time"]) for n in notes] == [(72, 0.0), (74, 1.0)]
    assert all(set(n) == {"pitch", "start_time", "duration", "velocity", "mute"} for n in notes)


def test_select_drops_pitches_pushed_out_of_range(midi_path):
    notes = select_notes(read_midi_file(midi_path), transpose=-40)
    assert [n["pitch"] for n in notes] == [20, 22]  # C2 (36) - 40 < 0 is dropped


def test_summary_lists_tracks(midi_path):
    summary = summarize(read_midi_file(midi_path))
    assert summary[0]["notes"] == 0
    assert summary[1] == {"index": 1, "name": "Melodie", "notes": 3,
                          "channels": [0, 1], "end_beats": 3.5}


def test_midi_track_out_of_range(midi_path):
    with pytest.raises(MidiFileError):
        select_notes(read_midi_file(midi_path), midi_track=5)


def test_rejects_non_midi_and_smpte(tmp_path):
    bad = tmp_path / "x.mid"
    bad.write_bytes(b"RIFF....")
    with pytest.raises(MidiFileError):
        read_midi_file(str(bad))
    smpte = tmp_path / "s.mid"
    smpte.write_bytes(b"MThd" + struct.pack(">IHHH", 6, 0, 0, 0xE728))
    with pytest.raises(MidiFileError):
        read_midi_file(str(smpte))


# ----------------------------------------------------------------- audio

SR = 48000


def _sine(freq, amp, seconds, sr=SR):
    return [amp * math.sin(2 * math.pi * freq * i / sr) for i in range(int(sr * seconds))]


def _write_wav16(path, left, right=None):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2 if right is not None else 1)
        w.setsampwidth(2)
        w.setframerate(SR)
        frames = bytearray()
        for i, l in enumerate(left):
            frames += struct.pack("<h", int(max(-1, min(1, l)) * 32767))
            if right is not None:
                frames += struct.pack("<h", int(max(-1, min(1, right[i])) * 32767))
        w.writeframes(bytes(frames))


def _riff(fmt_tag, bits, channels, payload):
    block = channels * bits // 8
    fmt = struct.pack("<HHIIHH", fmt_tag, channels, SR, SR * block, block, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(payload)) + payload
    return b"RIFF" + struct.pack("<I", len(body)) + body


def test_wav16_levels_and_stereo(tmp_path):
    p = tmp_path / "s.wav"
    tone = _sine(440, 0.5, 0.5)
    _write_wav16(p, tone, tone)
    a = analyze_audio(str(p))
    assert a["channels"] == 2 and a["sample_rate"] == SR
    assert a["peak_dbfs"] == pytest.approx(-6.02, abs=0.1)
    assert a["rms_dbfs"] == pytest.approx(-9.03, abs=0.1)  # sine RMS = peak - 3 dB
    assert a["stereo"]["correlation"] == pytest.approx(1.0, abs=1e-3)
    assert a["warnings"] == []


def test_clipping_is_reported(tmp_path):
    p = tmp_path / "c.wav"
    _write_wav16(p, _sine(100, 1.5, 0.2))
    a = analyze_audio(str(p))
    assert a["per_channel"][0]["clipped_samples"] > 0
    assert any("clipping" in w for w in a["warnings"])


def test_spectral_balance_separates_low_and_high(tmp_path):
    low, high = tmp_path / "low.wav", tmp_path / "high.wav"
    _write_wav16(low, _sine(60, 0.5, 0.5))
    _write_wav16(high, _sine(9000, 0.5, 0.5))
    lo = analyze_audio(str(low))["spectral_balance"]
    hi = analyze_audio(str(high))["spectral_balance"]
    assert lo["low_below_250hz_pct"] > 70 and lo["high_above_4khz_pct"] < 5
    assert hi["high_above_4khz_pct"] > 70 and hi["low_below_250hz_pct"] < 5


def test_silence_and_segments(tmp_path):
    p = tmp_path / "t.wav"
    _write_wav16(p, [0.0] * SR + _sine(440, 0.5, 1.0) + [0.0] * (SR // 2))
    a = analyze_audio(str(p), segment_seconds=0.5)
    assert a["leading_silence_s"] == pytest.approx(1.0, abs=0.01)
    assert a["trailing_silence_s"] == pytest.approx(0.5, abs=0.01)
    assert len(a["segments"]) == 5
    assert a["segments"][0]["rms_dbfs"] == -200.0
    assert a["loudest_segment"]["t"] in (1.0, 1.5)


def test_wav24_and_float32(tmp_path):
    tone = _sine(1000, 0.25, 0.1)
    pcm24 = b"".join(struct.pack("<i", int(v * (2 ** 23 - 1)))[:3] for v in tone)
    p24 = tmp_path / "a24.wav"
    p24.write_bytes(_riff(1, 24, 1, pcm24))
    f32 = b"".join(struct.pack("<f", v) for v in tone)
    pf = tmp_path / "af.wav"
    pf.write_bytes(_riff(3, 32, 1, f32))
    for p in (p24, pf):
        assert analyze_audio(str(p))["peak_dbfs"] == pytest.approx(-12.04, abs=0.1)


def _ieee80(x):
    exp = int(math.floor(math.log2(x)))
    mant = int(x / 2.0 ** exp * 2 ** 63)
    return struct.pack(">HQ", exp + 16383, mant)


def test_aiff16_big_endian(tmp_path):
    tone = _sine(440, 0.5, 0.1)
    ssnd = b"".join(struct.pack(">h", int(v * 32767)) for v in tone)
    comm = struct.pack(">hIh", 1, len(tone), 16) + _ieee80(SR)
    body = b"AIFF" + b"COMM" + struct.pack(">I", len(comm)) + comm
    ssnd_chunk = struct.pack(">II", 0, 0) + ssnd
    body += b"SSND" + struct.pack(">I", len(ssnd_chunk)) + ssnd_chunk
    p = tmp_path / "a.aif"
    p.write_bytes(b"FORM" + struct.pack(">I", len(body)) + body)
    info = read_audio(str(p))
    assert info["sample_rate"] == SR
    assert analyze_audio(str(p))["peak_dbfs"] == pytest.approx(-6.02, abs=0.1)


def test_rejects_unknown_audio(tmp_path):
    p = tmp_path / "x.wav"
    p.write_bytes(b"not audio")
    with pytest.raises(AudioFileError):
        analyze_audio(str(p))


def test_duplicates_are_merged_like_live_does():
    from ableton_studio_mcp.midi_file import merge_duplicates
    notes = [
        {"pitch": 64, "start_time": 1.0, "duration": 0.5, "velocity": 80, "mute": False},
        {"pitch": 64, "start_time": 1.0, "duration": 1.0, "velocity": 60, "mute": False},
        {"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 90, "mute": False},
    ]
    out, merged = merge_duplicates(notes)
    assert merged == 1
    assert [(n["pitch"], n["duration"], n["velocity"]) for n in out] == [(60, 1.0, 90), (64, 1.0, 80)]
