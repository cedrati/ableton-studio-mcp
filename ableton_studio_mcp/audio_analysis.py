"""Read a WAV/AIFF file and measure it (no dependency).

Gives the model a way to "listen" to a render or a recorded take: levels,
clipping, loudness over time, stereo width and a coarse spectral balance.
"""

import math
import struct
from array import array
from typing import Dict, List, Tuple


class AudioFileError(ValueError):
    """The file is not an audio file this reader handles."""


SILENCE_DB = -60.0


def _db(x: float) -> float:
    return round(20 * math.log10(x), 2) if x > 1e-10 else -200.0


def _int24_to_array(raw: bytes, big_endian: bool) -> array:
    """24-bit PCM -> int32 array scaled by 256 (sign kept)."""
    n = len(raw) // 3
    out = bytearray(n * 4)
    if big_endian:
        out[0::4], out[1::4], out[2::4] = raw[0::3], raw[1::3], raw[2::3]
        arr = array("i", bytes(out))
        if arr.itemsize == 4 and struct.pack("=i", 1) != struct.pack(">i", 1):
            arr.byteswap()
    else:
        out[1::4], out[2::4], out[3::4] = raw[0::3], raw[1::3], raw[2::3]
        arr = array("i", bytes(out))
        if struct.pack("=i", 1) != struct.pack("<i", 1):
            arr.byteswap()
    return arr


def _decode(raw: bytes, bits: int, is_float: bool, big_endian: bool) -> Tuple[array, float]:
    """Return (samples, full_scale)."""
    native_big = struct.pack("=h", 1) == struct.pack(">h", 1)
    swap = big_endian != native_big
    if is_float:
        code = {32: "f", 64: "d"}.get(bits)
        if not code:
            raise AudioFileError("Unsupported float width: %d bits" % bits)
        arr = array(code, raw[: len(raw) - len(raw) % (bits // 8)])
        if swap:
            arr.byteswap()
        return arr, 1.0
    if bits == 8:
        arr = array("b", bytes((b - 128) & 0xFF for b in raw)) if not big_endian else array("b", raw)
        return arr, 128.0
    if bits == 16:
        arr = array("h", raw[: len(raw) - len(raw) % 2])
        if swap:
            arr.byteswap()
        return arr, 32768.0
    if bits == 24:
        return _int24_to_array(raw[: len(raw) - len(raw) % 3], big_endian), float(2 ** 31)
    if bits == 32:
        arr = array("i", raw[: len(raw) - len(raw) % 4])
        if swap:
            arr.byteswap()
        return arr, float(2 ** 31)
    raise AudioFileError("Unsupported PCM width: %d bits" % bits)


def _ieee_extended(b: bytes) -> float:
    """80-bit IEEE 754 extended (AIFF sample rate)."""
    exp = ((b[0] & 0x7F) << 8) | b[1]
    mant = struct.unpack(">Q", b[2:10])[0]
    if exp == 0 and mant == 0:
        return 0.0
    return mant * 2.0 ** (exp - 16383 - 63)


def read_audio(path: str) -> Dict:
    """Return {"sample_rate", "channels", "bits", "samples" (interleaved), "full_scale"}."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        i, fmt, raw = 12, None, None
        while i + 8 <= len(data):
            cid, size = data[i:i + 4], struct.unpack("<I", data[i + 4:i + 8])[0]
            body = data[i + 8:i + 8 + size]
            if cid == b"fmt ":
                tag, ch, sr, _, _, bits = struct.unpack("<HHIIHH", body[:16])
                if tag == 0xFFFE and len(body) >= 26:  # WAVE_FORMAT_EXTENSIBLE
                    tag = struct.unpack("<H", body[24:26])[0]
                fmt = (tag, ch, sr, bits)
            elif cid == b"data":
                raw = body
            i += 8 + size + (size & 1)
        if not fmt or raw is None:
            raise AudioFileError("WAV file without fmt or data chunk")
        tag, ch, sr, bits = fmt
        if tag not in (1, 3):
            raise AudioFileError("Unsupported WAV encoding (format tag %d)" % tag)
        samples, fs = _decode(raw, bits, tag == 3, big_endian=False)
        return {"sample_rate": sr, "channels": ch, "bits": bits, "float": tag == 3,
                "samples": samples, "full_scale": fs}
    if data[:4] == b"FORM" and data[8:12] in (b"AIFF", b"AIFC"):
        i, comm, raw, compression = 12, None, None, b"NONE"
        while i + 8 <= len(data):
            cid, size = data[i:i + 4], struct.unpack(">I", data[i + 4:i + 8])[0]
            body = data[i + 8:i + 8 + size]
            if cid == b"COMM":
                ch, _, bits = struct.unpack(">hIh", body[:8])
                sr = _ieee_extended(body[8:18])
                if data[8:12] == b"AIFC" and len(body) >= 22:
                    compression = body[18:22]
                comm = (ch, int(round(sr)), bits)
            elif cid == b"SSND":
                offset = struct.unpack(">I", body[:4])[0]
                raw = body[8 + offset:]
            i += 8 + size + (size & 1)
        if not comm or raw is None:
            raise AudioFileError("AIFF file without COMM or SSND chunk")
        ch, sr, bits = comm
        if compression in (b"NONE", b"twos"):
            samples, fs = _decode(raw, bits, False, big_endian=True)
        elif compression == b"sowt":
            samples, fs = _decode(raw, bits, False, big_endian=False)
        elif compression in (b"fl32", b"FL32"):
            samples, fs = _decode(raw, 32, True, big_endian=True)
        elif compression in (b"fl64", b"FL64"):
            samples, fs = _decode(raw, 64, True, big_endian=True)
        else:
            raise AudioFileError("Unsupported AIFF-C compression %r" % compression)
        return {"sample_rate": sr, "channels": ch, "bits": bits,
                "float": compression.lower().startswith(b"fl"),
                "samples": samples, "full_scale": fs}
    raise AudioFileError("Not a WAV or AIFF file")


def _biquad(kind: str, cutoff: float, sr: float) -> Tuple[float, float, float, float, float]:
    """2nd-order Butterworth low/high-pass coefficients (RBJ cookbook),
    normalised: (b0, b1, b2, a1, a2)."""
    w0 = 2.0 * math.pi * min(cutoff, sr * 0.45) / sr
    alpha = math.sin(w0) / (2.0 * math.sqrt(0.5))
    cos_w0 = math.cos(w0)
    if kind == "low":
        b0 = b2 = (1.0 - cos_w0) / 2.0
        b1 = 1.0 - cos_w0
    else:
        b0 = b2 = (1.0 + cos_w0) / 2.0
        b1 = -(1.0 + cos_w0)
    a0 = 1.0 + alpha
    return b0 / a0, b1 / a0, b2 / a0, (-2.0 * cos_w0) / a0, (1.0 - alpha) / a0


def _band_energy(x: List[float], coeffs) -> float:
    b0, b1, b2, a1, a2 = coeffs
    x1 = x2 = y1 = y2 = 0.0
    energy = 0.0
    for v in x:
        y = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, v, y1, y
        energy += y * y
    return energy


def analyze_audio(path: str, segment_seconds: float = 1.0, max_segments: int = 240) -> Dict:
    """Levels, clipping, loudness over time, stereo and spectral balance."""
    info = read_audio(path)
    sr, ch, fs = info["sample_rate"], max(info["channels"], 1), info["full_scale"]
    s = info["samples"]
    frames = len(s) // ch
    if frames == 0:
        raise AudioFileError("The file has no audio frames")
    duration = frames / float(sr)
    scale = 1.0 / fs

    chans = [s[c::ch] for c in range(ch)]
    per_channel = []
    clip_level = 0.999 * fs
    for c, x in enumerate(chans):
        peak = max(max(x), -min(x)) * scale
        sumsq = math.fsum(v * v for v in x) * scale * scale
        clipped = sum(1 for v in x if v >= clip_level or v <= -clip_level)
        per_channel.append({
            "channel": c,
            "peak_dbfs": _db(peak),
            "rms_dbfs": _db(math.sqrt(sumsq / len(x))),
            "clipped_samples": clipped,
            "dc_offset": round(sum(x) * scale / len(x), 6),
        })

    # Mono mix, used for time and spectral analysis.
    if ch == 1:
        mono = [v * scale for v in chans[0]]
    else:
        mono = [sum(fr) * scale / ch for fr in zip(*chans)]

    peak = max(pc["peak_dbfs"] for pc in per_channel)
    total_rms = _db(math.sqrt(math.fsum(v * v for v in mono) / frames))

    # Loudness over time (RMS per segment of the mono mix).
    seg = max(int(sr * segment_seconds), 1)
    nseg = int(math.ceil(frames / float(seg)))
    if nseg > max_segments:
        seg = int(math.ceil(frames / float(max_segments)))
        nseg = int(math.ceil(frames / float(seg)))
    segments: List[Dict] = []
    for k in range(nseg):
        part = mono[k * seg:(k + 1) * seg]
        if not part:
            break
        rms = math.sqrt(math.fsum(v * v for v in part) / len(part))
        segments.append({
            "t": round(k * seg / float(sr), 2),
            "rms_dbfs": _db(rms),
            "peak_dbfs": _db(max(max(part), -min(part))),
        })

    # Leading / trailing silence.
    thr = 10 ** (SILENCE_DB / 20)
    first = next((i for i, v in enumerate(mono) if abs(v) > thr), None)
    last = next((i for i in range(frames - 1, -1, -1) if abs(mono[i]) > thr), None)

    # Coarse spectral balance with 2nd-order Butterworth filters:
    # low < 250 Hz, high > 4 kHz, mid = the rest of the energy.
    e_all = math.fsum(v * v for v in mono)
    e_lo = _band_energy(mono, _biquad("low", 250.0, sr))
    e_hi = _band_energy(mono, _biquad("high", 4000.0, sr))
    e_mid = max(e_all - e_lo - e_hi, 0.0)
    bands = {}
    if e_all > 0:
        bands = {
            "low_below_250hz_pct": round(100 * e_lo / e_all, 1),
            "mid_pct": round(100 * e_mid / e_all, 1),
            "high_above_4khz_pct": round(100 * e_hi / e_all, 1),
        }

    stereo = None
    if ch >= 2:
        l, r = chans[0], chans[1]
        sll = math.fsum(v * v for v in l)
        srr = math.fsum(v * v for v in r)
        slr = math.fsum(a * b for a, b in zip(l, r))
        corr = slr / math.sqrt(sll * srr) if sll > 0 and srr > 0 else None
        stereo = {
            "correlation": round(corr, 3) if corr is not None else None,
            "balance_db_left_minus_right": round(
                per_channel[0]["rms_dbfs"] - per_channel[1]["rms_dbfs"], 2),
        }

    loud = [sg for sg in segments if sg["rms_dbfs"] > SILENCE_DB]
    loudest = max(loud, key=lambda sg: sg["rms_dbfs"]) if loud else None
    warnings = []
    if any(pc["clipped_samples"] for pc in per_channel) or peak >= -0.1:
        warnings.append("clipping: peak at or near 0 dBFS")
    if peak < -18:
        warnings.append("quiet: peak below -18 dBFS")
    if stereo and stereo["correlation"] is not None and stereo["correlation"] < 0:
        warnings.append("phase: negative stereo correlation (mono-incompatible)")
    if first is None:
        warnings.append("silent: nothing above %d dBFS" % SILENCE_DB)

    return {
        "file": path,
        "sample_rate": sr,
        "channels": ch,
        "bits": info["bits"],
        "float": info["float"],
        "duration_s": round(duration, 3),
        "peak_dbfs": peak,
        "rms_dbfs": total_rms,
        "crest_factor_db": round(peak - total_rms, 2) if total_rms > -200 else None,
        "per_channel": per_channel,
        "stereo": stereo,
        "spectral_balance": bands,
        "leading_silence_s": round(first / float(sr), 3) if first is not None else None,
        "trailing_silence_s": round((frames - 1 - last) / float(sr), 3) if last is not None else None,
        "loudest_segment": loudest,
        "segment_seconds": round(seg / float(sr), 3),
        "segments": segments,
        "warnings": warnings,
    }
