"""Mix / master analysis of a rendered or recorded file (numpy).

What a mastering engineer measures before listening closely:

* Loudness per ITU-R BS.1770-4 / EBU R128: integrated (gated), short-term
  and momentary maxima, loudness range (EBU Tech 3342).
* True peak (4x oversampled around the loudest samples), sample peak,
  clipped samples, PLR (peak-to-loudness ratio), crest factor.
* Long-term spectrum in 1/3-octave bands, its tilt (dB/octave), and the
  deviation of each region from a balanced reference slope.
* Narrow spectral peaks (resonances or dominant notes).
* Stereo: correlation and side/mid ratio overall and per band, low-end mono.
* A spectrogram (log frequency) with the short-term loudness curve, as PNG.

``assess`` turns the numbers into findings with severity and a fix, against
a delivery target (streaming, club, classical, broadcast, podcast).
"""

import math
import struct
import zlib
from typing import Dict, List, Optional

import numpy as np

from .audio_analysis import read_audio

# ----------------------------------------------------------------- targets

TARGETS = {
    # integrated LUFS range considered right, ideal, max true peak, PLR floor
    "streaming": {"lufs": (-16.0, -12.0), "ideal": -14.0, "tp_max": -1.0, "plr_min": 8.0,
                  "label": "Streaming (Spotify/Apple Music/YouTube normalisent vers -14 LUFS)"},
    "club": {"lufs": (-10.0, -6.0), "ideal": -8.0, "tp_max": -0.3, "plr_min": 6.0,
             "label": "Club / électronique"},
    "classical": {"lufs": (-23.0, -16.0), "ideal": -18.0, "tp_max": -1.0, "plr_min": 12.0,
                  "label": "Classique / acoustique / orgue (dynamique préservée)"},
    "broadcast": {"lufs": (-23.5, -22.5), "ideal": -23.0, "tp_max": -1.0, "plr_min": 10.0,
                  "label": "Broadcast EBU R128 (-23 LUFS ±0,5)"},
    "podcast": {"lufs": (-17.0, -15.0), "ideal": -16.0, "tp_max": -1.0, "plr_min": 8.0,
                "label": "Podcast / voix"},
}

# Balanced mixes average around -4.5 dB/octave of long-term spectral slope
# in power spectral density (FFT analyser view, where pink noise is -3);
# most commercial music sits between -3 and -6.
REFERENCE_TILT = -4.5

THIRD_OCTAVES = [25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630,
                 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000,
                 12500, 16000, 20000]

REGIONS = [  # name, low, high, what too much / too little sounds like
    ("sub", 20, 60, "grondement / basses envahissantes", "manque d'assise dans l'extrême grave"),
    ("graves", 60, 200, "graves trop lourds", "manque de corps"),
    ("bas-médium", 200, 500, "son boueux, empâté", "son creux, maigre"),
    ("médium", 500, 2000, "son nasillard / « carton »", "son lointain, creusé"),
    ("haut-médium", 2000, 5000, "dureté, agressivité", "manque de présence, de définition"),
    ("aigus", 5000, 10000, "sifflantes, brillance agressive", "son terne"),
    ("air", 10000, 20000, "souffle, aigus métalliques", "manque d'air, d'ouverture"),
]

STEREO_BANDS = [("sub", 20, 120), ("graves-médium", 120, 500), ("médium", 500, 2000),
                ("aigus", 2000, 8000), ("air", 8000, 20000)]

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _db(x):
    return float(10 * np.log10(np.maximum(x, 1e-20)))


def _note(freq: float) -> str:
    midi = int(round(69 + 12 * math.log2(freq / 440.0)))
    return "%s%d" % (NOTE_NAMES[midi % 12], midi // 12 - 1)


# ------------------------------------------------------------- loudness

def _biquad_response(b, a, freqs, sr):
    z = np.exp(-1j * 2 * np.pi * freqs / sr)
    num = b[0] + b[1] * z + b[2] * z * z
    den = a[0] + a[1] * z + a[2] * z * z
    return np.abs(num / den)


def k_weighting_response(freqs: np.ndarray, sr: float) -> np.ndarray:
    """|H(f)| of the BS.1770 K-weighting (shelf + RLB high-pass) at any rate."""
    # Stage 1: high shelf (+4 dB above ~1.7 kHz)
    G, f0, Q = 3.999843853973347, 1681.974450955533, 0.7071752369554196
    K = math.tan(math.pi * f0 / sr)
    Vh = 10 ** (G / 20.0)
    Vb = Vh ** 0.4996667741545416
    a0 = 1.0 + K / Q + K * K
    b1 = [(Vh + Vb * K / Q + K * K) / a0, 2.0 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0]
    a1 = [1.0, 2.0 * (K * K - 1.0) / a0, (1.0 - K / Q + K * K) / a0]
    # Stage 2: high-pass (RLB)
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = math.tan(math.pi * f0 / sr)
    a0 = 1.0 + K / Q + K * K
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, 2.0 * (K * K - 1.0) / a0, (1.0 - K / Q + K * K) / a0]
    return _biquad_response(b1, a1, freqs, sr) * _biquad_response(b2, a2, freqs, sr)


def _apply_magnitude(x: np.ndarray, sr: float, response_fn) -> np.ndarray:
    """Zero-phase filtering by a magnitude response, in the frequency domain.

    Loudness only depends on the power spectrum, so the phase of the
    reference IIR filters doesn't matter here.
    """
    n = len(x)
    nfft = 1 << (n - 1).bit_length()
    X = np.fft.rfft(x, nfft)
    freqs = np.fft.rfftfreq(nfft, 1.0 / sr)
    return np.fft.irfft(X * response_fn(freqs), nfft)[:n]


def _windowed_power(power: np.ndarray, win: int, hop: int) -> np.ndarray:
    """Mean of ``power`` over windows of ``win`` samples every ``hop``."""
    if len(power) < win:
        return np.array([power.mean()]) if len(power) else np.array([0.0])
    c = np.concatenate([[0.0], np.cumsum(power)])
    starts = np.arange(0, len(power) - win + 1, hop)
    return (c[starts + win] - c[starts]) / win


def loudness(chans: List[np.ndarray], sr: float) -> Dict:
    """Integrated, momentary/short-term max, LRA, and the short-term curve."""
    weighted = [_apply_magnitude(c, sr, lambda f: k_weighting_response(f, sr)) for c in chans]
    # Channel weights: 1.0 for L/R (and mono).
    power = sum(w * w for w in weighted)
    hop = max(int(sr * 0.1), 1)
    to_lufs = lambda p: -0.691 + 10 * np.log10(np.maximum(p, 1e-20))

    blocks = _windowed_power(power, int(sr * 0.4), hop)       # momentary, 75 % overlap
    l_blocks = to_lufs(blocks)
    gated = blocks[l_blocks > -70.0]
    integrated = None
    if len(gated):
        rel = to_lufs(gated.mean()) - 10.0
        gated2 = gated[to_lufs(gated) > rel]
        integrated = float(to_lufs(gated2.mean())) if len(gated2) else None

    short = _windowed_power(power, int(sr * 3.0), hop)
    l_short = to_lufs(short)
    lra = None
    st_abs = short[l_short > -70.0]
    if len(st_abs):
        rel = to_lufs(st_abs.mean()) - 20.0
        st = to_lufs(st_abs)
        st = st[st > rel]
        if len(st) > 1:
            lra = float(np.percentile(st, 95) - np.percentile(st, 10))
    return {
        "integrated_lufs": round(integrated, 1) if integrated is not None else None,
        "momentary_max_lufs": round(float(l_blocks.max()), 1),
        "short_term_max_lufs": round(float(l_short.max()), 1),
        "loudness_range_lu": round(lra, 1) if lra is not None else None,
        "_short_term_curve": l_short,  # every 0.1 s, for the picture
        "_curve_hop_s": hop / sr,
    }


# ----------------------------------------------------------------- peaks

def _sinc_interp_peak(x: np.ndarray, idx: np.ndarray, oversample: int = 4, taps: int = 32) -> float:
    """Max |x| between samples around ``idx`` (windowed-sinc interpolation)."""
    best = 0.0
    k = np.arange(-taps, taps + 1)
    window = np.hanning(2 * taps + 3)[1:-1]
    n = len(x)
    for i in idx:
        lo, hi = i - taps - 1, i + taps + 2
        if lo < 0 or hi > n:
            seg_peak = float(np.abs(x[max(lo, 0):min(hi, n)]).max())
            best = max(best, seg_peak)
            continue
        for frac in np.arange(1, oversample) / oversample:
            for base in (i - 1, i):
                pos = base + frac
                kk = k + base
                vals = x[kk] * np.sinc(pos - kk) * window
                best = max(best, abs(float(vals.sum())))
        best = max(best, abs(float(x[i])))
    return best


def peaks(chans: List[np.ndarray]) -> Dict:
    sample_peak = max(float(np.abs(c).max()) for c in chans)
    true_peak = 0.0
    for c in chans:
        a = np.abs(c)
        thr = a.max() * 0.7  # inter-sample overs only matter near the top
        cand = np.flatnonzero(a >= thr)
        if len(cand) > 4000:
            cand = cand[np.argsort(a[cand])[-4000:]]
        true_peak = max(true_peak, _sinc_interp_peak(c, cand))
    clipped = int(sum(int((np.abs(c) >= 0.9999).sum()) for c in chans))
    return {
        "sample_peak_dbfs": round(20 * math.log10(max(sample_peak, 1e-10)), 2),
        "true_peak_dbtp": round(20 * math.log10(max(true_peak, 1e-10)), 2),
        "clipped_samples": clipped,
    }


# --------------------------------------------------------------- spectrum

def long_term_spectrum(mono: np.ndarray, sr: float, nfft: int = 8192):
    """Welch average power spectrum (Hann, 50 % overlap)."""
    hop = nfft // 2
    if len(mono) < nfft:
        mono = np.pad(mono, (0, nfft - len(mono)))
    frames = np.lib.stride_tricks.sliding_window_view(mono, nfft)[::hop]
    win = np.hanning(nfft)
    spec = np.zeros(nfft // 2 + 1)
    for start in range(0, len(frames), 256):  # bounded memory
        block = frames[start:start + 256] * win
        spec += (np.abs(np.fft.rfft(block, axis=1)) ** 2).sum(axis=0)
    spec /= max(len(frames), 1)
    return np.fft.rfftfreq(nfft, 1.0 / sr), spec


def third_octave_levels(freqs, spec) -> List[Dict]:
    out = []
    for fc in THIRD_OCTAVES:
        lo, hi = fc / 2 ** (1 / 6), fc * 2 ** (1 / 6)
        m = (freqs >= lo) & (freqs < hi)
        if m.any() and hi < freqs[-1]:
            # mean = power spectral density, the convention of FFT analysers
            # (pink noise reads -3 dB/octave, music ~-4.5 as in Voxengo SPAN)
            out.append({"hz": fc, "db": _db(spec[m].mean())})
    if out:
        top = max(b["db"] for b in out)
        for b in out:
            b["db"] = round(b["db"] - top, 1)
    return out


def tonal_balance(bands: List[Dict]) -> Dict:
    """Tilt (dB/oct, fitted 50 Hz-12 kHz) and each region's deviation from a
    reference slope anchored on the 500 Hz-2 kHz level."""
    fit = [(math.log2(b["hz"]), b["db"]) for b in bands if 50 <= b["hz"] <= 12500]
    tilt = None
    if len(fit) > 3:
        xs, ys = np.array([f[0] for f in fit]), np.array([f[1] for f in fit])
        tilt = float(np.polyfit(xs, ys, 1)[0])
    mid = [b for b in bands if 500 <= b["hz"] <= 2000]
    anchor_db = np.mean([b["db"] for b in mid]) if mid else 0.0
    anchor_oct = math.log2(1000.0)
    regions = []
    for name, lo, hi, too_much, too_little in REGIONS:
        inside = [b for b in bands if lo <= b["hz"] < hi]
        if not inside:
            continue
        dev = np.mean([b["db"] - (anchor_db + REFERENCE_TILT * (math.log2(b["hz"]) - anchor_oct))
                       for b in inside])
        regions.append({"region": name, "range_hz": [lo, hi],
                        "deviation_db": round(float(dev), 1),
                        "if_high": too_much, "if_low": too_little})
    return {"tilt_db_per_octave": round(tilt, 2) if tilt is not None else None,
            "reference_tilt": REFERENCE_TILT, "regions": regions}


def narrow_peaks(freqs, spec, max_peaks: int = 8) -> List[Dict]:
    """Peaks standing > 6 dB above their 1-octave neighbourhood (40 Hz-12 kHz)."""
    m = (freqs >= 40) & (freqs <= 12000)
    f, s = freqs[m], _db_array(spec[m])
    logf = np.log2(f)
    found = []
    order = np.argsort(s)[::-1]
    for i in order:
        if len(found) >= max_peaks:
            break
        if i == 0 or i == len(s) - 1 or s[i] < s[i - 1] or s[i] < s[i + 1]:
            continue
        neigh = (np.abs(logf - logf[i]) < 0.5) & (np.abs(logf - logf[i]) > 1 / 12)
        if not neigh.any():
            continue
        prominence = s[i] - float(np.median(s[neigh]))
        if prominence < 6:
            continue
        if any(abs(math.log2(f[i] / p["hz"])) < 1 / 6 for p in found):
            continue
        found.append({"hz": round(float(f[i]), 1), "note": _note(float(f[i])),
                      "prominence_db": round(prominence, 1)})
    return sorted(found, key=lambda p: p["hz"])


def _db_array(x):
    return 10 * np.log10(np.maximum(x, 1e-20))


# ----------------------------------------------------------------- stereo

def stereo(left: np.ndarray, right: np.ndarray, sr: float) -> Dict:
    def stats(l, r):
        ll, rr, lr = float((l * l).sum()), float((r * r).sum()), float((l * r).sum())
        corr = lr / math.sqrt(ll * rr) if ll > 0 and rr > 0 else None
        mid, side = (l + r) / 2, (l - r) / 2
        m2, s2 = float((mid * mid).sum()), float((side * side).sum())
        return {"correlation": round(corr, 3) if corr is not None else None,
                "side_to_mid_db": round(_db(s2 / m2), 1) if m2 > 0 else None}

    out = {"overall": stats(left, right), "bands": []}
    n = len(left)
    nfft = 1 << (n - 1).bit_length()
    L, R = np.fft.rfft(left, nfft), np.fft.rfft(right, nfft)
    freqs = np.fft.rfftfreq(nfft, 1.0 / sr)
    for name, lo, hi in STEREO_BANDS:
        mask = (freqs >= lo) & (freqs < hi)
        if not mask.any():
            continue
        lb = np.fft.irfft(L * mask, nfft)[:n]
        rb = np.fft.irfft(R * mask, nfft)[:n]
        st = stats(lb, rb)
        st.update({"band": name, "range_hz": [lo, hi]})
        out["bands"].append(st)
    return out


# ------------------------------------------------------------- spectrogram

_FONT = {  # 3x5 bitmap glyphs
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111",
    "3": "111001111001111", "4": "101101111001001", "5": "111100111001111",
    "6": "111100111101111", "7": "111001001001001", "8": "111101111101111",
    "9": "111101111001111", "k": "100101110101101", "s": "011100010001110",
    "-": "000000111000000", ".": "000000000000010", "L": "100100100100111",
    "U": "101101101101111", "F": "111100110100100", "S": "011100010001110",
    "H": "101101111101101", "z": "000111001010111", " ": "000000000000000",
    "d": "001001111101111", "B": "110101110101110",
}


def _text(img, x, y, s, color, scale=2):
    for ch in s:
        g = _FONT.get(ch)
        if g:
            for r in range(5):
                for c in range(3):
                    if g[r * 3 + c] == "1":
                        img[y + r * scale:y + (r + 1) * scale, x + c * scale:x + (c + 1) * scale] = color
        x += 4 * scale


def _colormap(v: np.ndarray) -> np.ndarray:
    """0..1 -> RGB, dark purple -> red -> yellow -> white (inferno-like)."""
    stops = np.array([[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99],
                      [212, 72, 66], [245, 125, 21], [250, 193, 39], [252, 255, 164]], float)
    pos = np.clip(v, 0, 1) * (len(stops) - 1)
    i = np.minimum(pos.astype(int), len(stops) - 2)
    t = (pos - i)[..., None]
    return (stops[i] * (1 - t) + stops[i + 1] * t).astype(np.uint8)


def _write_png(path: str, img: np.ndarray) -> None:
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(kind, data):
        c = struct.pack(">I", len(data)) + kind + data
        return c + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        f.write(chunk(b"IEND", b""))


def spectrogram_png(mono: np.ndarray, sr: float, path: str, short_term: Optional[np.ndarray],
                    curve_hop_s: float, target_lufs: Optional[float] = None,
                    width: int = 1200, height: int = 420) -> Dict:
    """Log-frequency spectrogram (20 Hz-20 kHz, 0 to -90 dB) above the
    short-term loudness curve (-40 to 0 LUFS)."""
    duration = len(mono) / sr
    nfft = 4096
    hop = max(int(len(mono) / width), 256)
    if len(mono) < nfft:
        mono = np.pad(mono, (0, nfft - len(mono)))
    frames = np.lib.stride_tricks.sliding_window_view(mono, nfft)[::hop]
    win = np.hanning(nfft)
    cols = []
    for start in range(0, len(frames), 256):
        cols.append(np.abs(np.fft.rfft(frames[start:start + 256] * win, axis=1)) ** 2)
    S = np.concatenate(cols, axis=0)  # time x freq
    freqs = np.fft.rfftfreq(nfft, 1.0 / sr)
    fmin, fmax = 20.0, min(20000.0, sr / 2)
    row_f = fmin * (fmax / fmin) ** (np.arange(height)[::-1] / (height - 1))
    idx = np.clip(np.searchsorted(freqs, row_f), 1, len(freqs) - 1)
    S = S[:, idx].T  # rows = freq (top = high)
    S_db = 10 * np.log10(np.maximum(S, 1e-20))
    S_db -= S_db.max()
    # resample columns to the target width
    col_idx = np.linspace(0, S_db.shape[1] - 1, width).astype(int)
    spec_img = _colormap((S_db[:, col_idx] + 90.0) / 90.0)

    margin_l, margin_b, strip = 64, 22, 130
    H = height + strip + margin_b * 2
    img = np.zeros((H, width + margin_l + 8, 3), np.uint8)
    img[:, :] = (18, 18, 22)
    img[0:height, margin_l:margin_l + width] = spec_img
    grid = (90, 90, 100)
    for fhz, label in [(50, "50"), (100, "100"), (200, "200"), (500, "500"), (1000, "1k"),
                       (2000, "2k"), (5000, "5k"), (10000, "10k")]:
        y = int((height - 1) * (1 - math.log(fhz / fmin) / math.log(fmax / fmin)))
        img[y, margin_l:margin_l + width:3] = grid
        _text(img, 4, max(y - 5, 0), label, (200, 200, 210))
    _text(img, 4, height - 12, "Hz", (200, 200, 210))
    # loudness strip
    top = height + margin_b
    img[top:top + strip, margin_l:margin_l + width] = (28, 28, 34)
    for lufs in (-10, -20, -30):
        y = top + int(strip * (-lufs) / 40.0)
        img[y, margin_l:margin_l + width:4] = grid
        _text(img, 4, y - 5, str(lufs), (200, 200, 210))
    _text(img, 4, top + strip - 10, "LUFS", (200, 200, 210))
    if target_lufs is not None:
        y = top + int(strip * min(max(-target_lufs, 0), 40) / 40.0)
        img[y, margin_l:margin_l + width:2] = (80, 200, 120)
    if short_term is not None and len(short_term):
        xs = np.linspace(0, len(short_term) - 1, width).astype(int)
        vals = np.clip(short_term[xs], -40, 0)
        ys = top + (strip * (-vals) / 40.0).astype(int)
        for x in range(width):
            y = min(max(ys[x], top), top + strip - 1)
            img[y:y + 2, margin_l + x] = (120, 200, 255)
    # time axis
    step = 5 if duration <= 60 else 10 if duration <= 180 else 30
    t = 0
    while t <= duration:
        x = margin_l + int((width - 1) * t / max(duration, 1e-9))
        img[0:height + strip + margin_b, x] = np.maximum(img[0:height + strip + margin_b, x], 0)
        img[height:height + 4, x] = (200, 200, 210)
        _text(img, x - 4, top + strip + 6, "%ds" % t if t else "0", (200, 200, 210))
        t += step
    _write_png(path, img)
    return {"path": path, "width": img.shape[1], "height": img.shape[0],
            "frequency_axis": "log, 20 Hz (bottom) to 20 kHz (top); 0 to -90 dB",
            "loudness_strip": "short-term LUFS, 0 (top) to -40; green line = target"}


# ----------------------------------------------------------------- facade

def analyze_mix(path: str, target: str = "streaming", spectrogram_path: Optional[str] = None) -> Dict:
    info = read_audio(path)
    sr, ch = info["sample_rate"], max(info["channels"], 1)
    s = np.asarray(info["samples"], dtype=np.float64) / info["full_scale"]
    frames = len(s) // ch
    s = s[:frames * ch].reshape(frames, ch)
    chans = [s[:, c] for c in range(min(ch, 2))]
    mono = chans[0] if len(chans) == 1 else (chans[0] + chans[1]) / 2

    loud = loudness(chans, sr)
    pk = peaks(chans)
    freqs, spec = long_term_spectrum(mono, sr)
    bands = third_octave_levels(freqs, spec)
    result = {
        "file": path,
        "duration_s": round(frames / sr, 2),
        "sample_rate": sr,
        "channels": ch,
        "target": target,
        "loudness": {k: v for k, v in loud.items() if not k.startswith("_")},
        "peaks": pk,
        "dynamics": {},
        "tonal_balance": tonal_balance(bands),
        "third_octave_db": bands,
        "narrow_peaks": narrow_peaks(freqs, spec),
        "stereo": stereo(chans[0], chans[1], sr) if len(chans) == 2 else None,
        "dc_offset": [round(float(c.mean()), 5) for c in chans],
    }
    integ = loud["integrated_lufs"]
    rms = math.sqrt(float(np.mean(mono * mono))) if len(mono) else 0.0
    result["dynamics"] = {
        "plr_db": round(pk["true_peak_dbtp"] - integ, 1) if integ is not None else None,
        "crest_factor_db": round(pk["sample_peak_dbfs"] - 20 * math.log10(max(rms, 1e-10)), 1),
    }
    tgt = TARGETS.get(target)
    if spectrogram_path:
        result["spectrogram"] = spectrogram_png(
            mono, sr, spectrogram_path, loud["_short_term_curve"], loud["_curve_hop_s"],
            tgt["ideal"] if tgt else None)
    result["assessment"] = assess(result)
    return result


def assess(r: Dict) -> Dict:
    """Findings with severity (ok / attention / problème) and what to do."""
    findings = []
    tgt = TARGETS.get(r["target"])

    def add(sev, topic, msg, fix=None):
        findings.append({"severity": sev, "topic": topic, "finding": msg, **({"fix": fix} if fix else {})})

    L, P, D = r["loudness"], r["peaks"], r["dynamics"]
    integ = L["integrated_lufs"]
    if integ is None:
        add("problème", "niveau", "Fichier silencieux ou trop faible pour être mesuré.")
    elif tgt:
        lo, hi = tgt["lufs"]
        if integ > hi:
            add("problème" if integ > hi + 2 else "attention", "niveau",
                "%.1f LUFS intégré, plus fort que la cible %s (%.0f à %.0f)." % (integ, tgt["label"], lo, hi),
                "Baisser le gain avant le limiteur de %.1f dB : les plateformes baisseront de toute façon, "
                "et la dynamique perdue ne revient pas." % (integ - tgt["ideal"]))
        elif integ < lo:
            add("attention", "niveau",
                "%.1f LUFS intégré, plus faible que la cible %s (%.0f à %.0f)." % (integ, tgt["label"], lo, hi),
                "Monter de %.1f dB avec un limiteur (ou du gain si la crête le permet : true peak %.1f dBTP)."
                % (tgt["ideal"] - integ, P["true_peak_dbtp"]))
        else:
            add("ok", "niveau", "%.1f LUFS intégré : dans la cible %s." % (integ, tgt["label"]))

    tp_max = tgt["tp_max"] if tgt else -1.0
    if P["clipped_samples"] > 0:
        add("problème", "crêtes", "%d échantillons saturés (écrêtage numérique)." % P["clipped_samples"],
            "Limiteur en fin de chaîne avec plafond à %.1f dBTP, ou baisser le master." % tp_max)
    if P["true_peak_dbtp"] > tp_max:
        add("problème" if P["true_peak_dbtp"] > 0 else "attention", "crêtes",
            "True peak %.2f dBTP, au-dessus de %.1f dBTP : risque de distorsion à l'encodage (MP3/AAC)."
            % (P["true_peak_dbtp"], tp_max),
            "Plafond du limiteur à %.1f dB avec suréchantillonnage (true peak) activé." % tp_max)
    elif P["clipped_samples"] == 0:
        add("ok", "crêtes", "True peak %.2f dBTP : marge suffisante." % P["true_peak_dbtp"])

    plr = D["plr_db"]
    if plr is not None and tgt:
        if plr < tgt["plr_min"] - 2:
            add("problème", "dynamique",
                "PLR %.1f dB : master très compressé/limité pour ce style." % plr,
                "Moins de gain dans le limiteur, ou compression plus douce (ratio plus bas, attaque plus lente).")
        elif plr < tgt["plr_min"]:
            add("attention", "dynamique", "PLR %.1f dB : un peu écrasé pour ce style." % plr)
        else:
            add("ok", "dynamique", "PLR %.1f dB : dynamique respirante." % plr)
    lra = L["loudness_range_lu"]
    if lra is not None:
        if r["target"] in ("streaming", "club") and lra > 12:
            add("attention", "dynamique",
                "Loudness range %.1f LU : écarts de volume importants entre passages, "
                "les parties douces risquent de se perdre en écoute courante." % lra,
                "Automation de volume ou compression lente sur le bus master.")
        elif r["target"] == "broadcast" and lra > 20:
            add("attention", "dynamique", "Loudness range %.1f LU, au-dessus des 20 LU conseillés." % lra)

    tb = r["tonal_balance"]
    tilt = tb["tilt_db_per_octave"]
    if tilt is not None:
        if tilt > -2.5:
            add("attention", "équilibre", "Pente spectrale %.1f dB/octave : mix clair, voire brillant/dur "
                "(référence ≈ %.1f)." % (tilt, REFERENCE_TILT),
                "Adoucir le haut-médium/aigu (shelf -1,5 à -3 dB au-dessus de 4 kHz) ou renforcer le bas.")
        elif tilt < -6.5:
            add("attention", "équilibre", "Pente spectrale %.1f dB/octave : mix sombre, chargé en graves "
                "(référence ≈ %.1f)." % (tilt, REFERENCE_TILT),
                "Shelf aigu +2 à +3 dB vers 8-10 kHz et/ou nettoyer le bas-médium.")
        else:
            add("ok", "équilibre", "Pente spectrale %.1f dB/octave : équilibre général cohérent." % tilt)
    for reg in tb["regions"]:
        dev = reg["deviation_db"]
        if reg["region"] in ("sub", "air"):
            limit_hi, limit_lo = 6.0, 9.0   # these vary most with the style
        else:
            limit_hi, limit_lo = 4.0, 6.0
        lo_hz, hi_hz = reg["range_hz"]
        if dev > limit_hi:
            add("problème" if dev > limit_hi + 3 else "attention", "équilibre",
                "%s (%d-%d Hz) %+.1f dB par rapport à la référence : %s."
                % (reg["region"], lo_hz, hi_hz, dev, reg["if_high"]),
                "EQ en cloche large -%.0f à -%.0f dB vers %d Hz sur les pistes qui chargent cette zone."
                % (min(dev / 2, 4), min(dev - 1, 6), int(math.sqrt(lo_hz * hi_hz))))
        elif dev < -limit_lo:
            add("attention", "équilibre",
                "%s (%d-%d Hz) %+.1f dB par rapport à la référence : %s."
                % (reg["region"], lo_hz, hi_hz, dev, reg["if_low"]),
                "Renfort large +2 à +3 dB vers %d Hz, ou une source qui occupe cette zone."
                % int(math.sqrt(lo_hz * hi_hz)))
    for p in r["narrow_peaks"]:
        if p["prominence_db"] >= 10:
            add("attention", "résonance",
                "Pic étroit à %.0f Hz (%s), %.0f dB au-dessus de son voisinage : résonance ou note "
                "trop présente." % (p["hz"], p["note"], p["prominence_db"]),
                "EQ en cloche étroite (Q 4-8) -3 à -5 dB à %.0f Hz si ce n'est pas voulu." % p["hz"])

    st = r["stereo"]
    if st:
        corr = st["overall"]["correlation"]
        sm = st["overall"]["side_to_mid_db"]
        if corr is not None and corr < 0:
            add("problème", "stéréo", "Corrélation %.2f : problème de phase, le mix se creuse en mono." % corr,
                "Vérifier les effets stéréo larges et les inversions de phase.")
        elif corr is not None and corr < 0.2:
            add("attention", "stéréo", "Corrélation %.2f : stéréo très large, compatibilité mono fragile." % corr)
        if sm is not None and sm < -25:
            add("attention", "stéréo", "Side/mid %.0f dB : mix quasiment mono." % sm,
                "Élargir les éléments médium/aigus (panoramique, doublage, réverbe stéréo).")
        low = next((b for b in st["bands"] if b["band"] == "sub"), None)
        if low and low["correlation"] is not None and (low["correlation"] < 0.8 or
                                                       (low["side_to_mid_db"] or -99) > -12):
            add("attention", "stéréo",
                "Graves sous 120 Hz pas assez mono (corrélation %.2f, side/mid %s dB) : "
                "basses instables en club/mono." % (low["correlation"], low["side_to_mid_db"]),
                "Mettre le bas en mono sous 120 Hz (Utility « Bass Mono » sur le master ou les pistes graves).")
        if corr is not None and corr >= 0.2 and (sm is None or sm >= -25):
            add("ok", "stéréo", "Corrélation %.2f, side/mid %.0f dB : image stéréo saine." % (corr, sm or 0))

    if any(abs(d) > 0.005 for d in r["dc_offset"]):
        add("attention", "technique", "Décalage DC %s." % r["dc_offset"],
            "Filtre passe-haut à 10-20 Hz en fin de chaîne.")

    order = {"problème": 0, "attention": 1, "ok": 2}
    findings.sort(key=lambda f: order[f["severity"]])
    counts = {k: sum(1 for f in findings if f["severity"] == k) for k in order}
    return {"target": tgt["label"] if tgt else r["target"], "summary": counts, "findings": findings}
