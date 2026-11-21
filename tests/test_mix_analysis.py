"""Mix / master analysis against reference signals.

Loudness is checked on EBU Tech 3341-style signals (a 1 kHz sine at -20 dBFS
on both channels reads -23.0 LUFS); true peak on a sine whose samples miss
its crest; the tonal and stereo diagnostics on synthetic mixes.
"""

import struct

import numpy as np
import pytest

from ableton_studio_mcp.mix_analysis import (
    analyze_mix, k_weighting_response, loudness, peaks, stereo, tonal_balance,
    third_octave_levels, long_term_spectrum)

SR = 48000


def _wav(path, left, right=None, sr=SR):
    """32-bit float WAV (no clipping of test signals above 0 dBFS)."""
    chans = [left] if right is None else [left, right]
    data = np.stack(chans, axis=1).astype("<f4").tobytes()
    ch = len(chans)
    fmt = struct.pack("<HHIIHH", 3, ch, sr, sr * 4 * ch, 4 * ch, 32)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(data)) + data
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return str(path)


def _sine(freq, dbfs, seconds, sr=SR, phase=0.0):
    t = np.arange(int(sr * seconds)) / sr
    return 10 ** (dbfs / 20) * np.sin(2 * np.pi * freq * t + phase)


def test_k_weighting_matches_the_standard_at_48k():
    f = np.array([20.0, 100.0, 1000.0, 10000.0])
    db = 20 * np.log10(k_weighting_response(f, 48000))
    # BS.1770: ~-13 dB at 20 Hz, ~0 dB at 1 kHz, ~+4 dB high shelf
    assert db[0] == pytest.approx(-13.0, abs=1.5)
    assert db[2] == pytest.approx(0.7, abs=0.3)
    assert db[3] == pytest.approx(4.0, abs=0.3)


@pytest.mark.parametrize("sr", [44100, 48000])
def test_ebu_reference_sine_reads_minus_23_lufs(sr):
    s = _sine(1000, -23, 20, sr=sr)  # EBU Tech 3341 case 1
    loud = loudness([s, s], sr)
    assert loud["integrated_lufs"] == pytest.approx(-23.0, abs=0.1)
    assert loud["short_term_max_lufs"] == pytest.approx(-23.0, abs=0.1)
    assert loud["loudness_range_lu"] == pytest.approx(0.0, abs=0.2)


def test_gating_ignores_silence():
    s = np.concatenate([_sine(1000, -23, 10), np.zeros(SR * 10)])
    # The blocks straddling the cut sit just inside the relative gate.
    assert loudness([s, s], SR)["integrated_lufs"] == pytest.approx(-23.0, abs=0.15)


def test_loudness_range_of_two_levels():
    # EBU 3342 case: -20 then -30 dBFS -> LRA 10 LU
    s = np.concatenate([_sine(1000, -20, 20), _sine(1000, -30, 20)])
    assert loudness([s, s], SR)["loudness_range_lu"] == pytest.approx(10.0, abs=1.0)


def test_true_peak_finds_inter_sample_overs():
    # fs/4 sine with a 45 degree phase: samples sit 3 dB below the crest.
    s = _sine(SR / 4, 0.0, 0.5, phase=np.pi / 4)
    p = peaks([s])
    assert p["sample_peak_dbfs"] == pytest.approx(-3.01, abs=0.05)
    assert p["true_peak_dbtp"] == pytest.approx(0.0, abs=0.3)


def test_tilt_of_pink_like_noise():
    rng = np.random.default_rng(1)
    white = rng.standard_normal(SR * 10)
    spec = np.fft.rfft(white)
    f = np.fft.rfftfreq(len(white), 1 / SR)
    pink = np.fft.irfft(spec / np.sqrt(np.maximum(f, 1.0)), len(white))
    freqs, power = long_term_spectrum(pink, SR)
    tilt = tonal_balance(third_octave_levels(freqs, power))["tilt_db_per_octave"]
    # Pink noise: -3 dB/octave of power spectral density
    assert tilt == pytest.approx(-3.0, abs=0.6)


def test_stereo_mono_vs_wide_vs_inverted():
    rng = np.random.default_rng(2)
    a, b = rng.standard_normal(SR * 2), rng.standard_normal(SR * 2)
    assert stereo(a, a, SR)["overall"]["correlation"] == pytest.approx(1.0, abs=1e-6)
    assert stereo(a, b, SR)["overall"]["correlation"] == pytest.approx(0.0, abs=0.05)
    assert stereo(a, -a, SR)["overall"]["correlation"] == pytest.approx(-1.0, abs=1e-6)


def _findings(result, topic=None):
    return [f for f in result["assessment"]["findings"] if topic is None or f["topic"] == topic]


def test_report_flags_hot_clipped_master(tmp_path):
    rng = np.random.default_rng(3)
    noise = rng.standard_normal(SR * 6) * 0.6
    hot = np.clip(noise, -1.0, 1.0)
    r = analyze_mix(_wav(tmp_path / "hot.wav", hot, hot), target="streaming")
    sev = {f["severity"] for f in _findings(r, "crêtes")}
    assert "problème" in sev
    assert r["peaks"]["clipped_samples"] > 0
    assert r["assessment"]["summary"]["problème"] >= 1


def test_report_on_a_balanced_streaming_master(tmp_path):
    rng = np.random.default_rng(4)
    white = rng.standard_normal(SR * 12)
    spec = np.fft.rfft(white)
    f = np.fft.rfftfreq(len(white), 1 / SR)
    # -4.5 dB/oct overall slope relative to pink -> reference curve
    shaped = np.fft.irfft(spec / np.maximum(f, 20.0) ** (0.5 + 1.5 / 6.02), len(white))
    shaped *= 10 ** (-14.0 / 20) / np.sqrt(np.mean(shaped ** 2)) * 0.9
    side = rng.standard_normal(len(shaped)) * 0.05 * np.sqrt(np.mean(shaped ** 2))
    left, right = shaped + side, shaped - side
    r = analyze_mix(_wav(tmp_path / "ok.wav", left, right), target="streaming",
                    spectrogram_path=str(tmp_path / "spec.png"))
    tilt = r["tonal_balance"]["tilt_db_per_octave"]
    assert tilt == pytest.approx(-4.5, abs=1.0)
    assert not [f for f in _findings(r, "équilibre") if f["severity"] == "problème"]
    png = (tmp_path / "spec.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and r["spectrogram"]["width"] > 1000


def test_low_end_not_mono_is_flagged(tmp_path):
    rng = np.random.default_rng(5)
    bass_l = _sine(60, -12, 6)
    bass_r = _sine(60, -12, 6, phase=np.pi * 0.8)  # out of phase lows
    mids = rng.standard_normal(SR * 6) * 0.05
    r = analyze_mix(_wav(tmp_path / "w.wav", bass_l + mids, bass_r + mids))
    msgs = " ".join(f["finding"] for f in _findings(r, "stéréo"))
    assert "120 Hz" in msgs


def test_dark_mix_is_called_dark(tmp_path):
    s = _sine(110, -12, 6) + _sine(220, -16, 6) + _sine(440, -24, 6)
    r = analyze_mix(_wav(tmp_path / "d.wav", s, s), target="classical")
    assert r["tonal_balance"]["tilt_db_per_octave"] < -6.5
    assert any("sombre" in f["finding"] for f in _findings(r, "équilibre"))
