"""Recording the Arrangement and listening to it like a mastering engineer."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Union

from .. import live
from ..app import tool

log = logging.getLogger("ableton_studio_mcp")


# Extra time allowed past the expected end of a recording.
RECORDING_MARGIN_S = 5.0
RECORDING_POLL_S = 0.5


def _wait_for_recording(ableton, expected_s: float, max_wait_s: float,
                        on_poll=None) -> Dict[str, Any]:
    """Poll get_recording_status until the watcher in Live has finished.
    ``on_poll`` runs at each poll while recording (e.g. to sample meters)."""

    deadline = time.monotonic() + min(expected_s + RECORDING_MARGIN_S, max_wait_s)
    status: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        status = ableton.call("get_recording_status")
        rec = status.get("recording") or {}
        if rec.get("finished"):
            return status
        if on_poll is not None:
            try:
                on_poll()
            except Exception as e:  # metering must never break a take
                log.warning(f"Meter sampling failed: {e}")
                on_poll = None
        time.sleep(RECORDING_POLL_S)
    ableton.call("stop_arrangement_recording")
    status = ableton.call("get_recording_status")
    status["timed_out"] = True
    return status


@tool()
def record_arrangement(start_time: float,
    end_time: float,
    wait: bool = True,
    max_wait_seconds: float = 600.0,
) -> str:
    """
    Record the armed tracks into the Arrangement between two song positions
    (in beats): moves the playhead, turns Arrangement Record on, plays, and
    stops at end_time. Arm tracks first (set_track_arm).

    Parameters:
    - start_time: Song position to start at (beats)
    - end_time: Song position to stop at (beats)
    - wait: Block until the recording ends (default) or return at once
      (then poll get_recording_status)
    - max_wait_seconds: Safety limit when waiting; recording is stopped past it
    """
    live.require("record_arrangement")
    ableton = live.client()
    tempo = float(ableton.call("get_session_info").get("tempo") or 120.0)
    result = ableton.call(
        "record_arrangement", {"start_time": start_time, "end_time": end_time})
    if not wait:
        return json.dumps(result, indent=2, ensure_ascii=False)
    expected = (end_time - start_time) * 60.0 / tempo
    status = _wait_for_recording(ableton, expected, max_wait_seconds)
    return json.dumps(status, indent=2, ensure_ascii=False)


@tool()
def get_recording_status() -> str:
    """
    State of the current or last record_arrangement run (finished, reason,
    stop position), plus Arrangement Record, transport and armed tracks.
    """
    live.require("get_recording_status")
    result = live.client().call("get_recording_status")
    return json.dumps(result, indent=2, ensure_ascii=False)


@tool()
def stop_arrangement_recording() -> str:
    """
    Stop a running record_arrangement now (turns Arrangement Record off and
    stops playback).
    """
    live.require("stop_arrangement_recording")
    result = live.client().call("stop_arrangement_recording")
    return json.dumps(result, indent=2, ensure_ascii=False)


@tool()
def get_audio_clip_file(track_index: int, clip_index: int,
                        location: str = "arrangement") -> str:
    """
    Path of the audio file behind an audio clip (for example a take just
    recorded with record_arrangement), with its length and sample rate.

    Parameters:
    - track_index: The track holding the clip
    - clip_index: Arrangement clip index (get_arrangement_clips) or Session slot
    - location: "arrangement" (default) or "session"
    """
    live.require("get_audio_clip_file")
    result = live.client().call("get_audio_clip_file", {
        "track_index": track_index, "clip_index": clip_index,
        "location": (location or "arrangement").lower()})
    return json.dumps(result, indent=2, ensure_ascii=False)


@tool()
def analyze_audio_file(file_path: str, segment_seconds: float = 1.0) -> str:
    """
    Measure a WAV or AIFF file: peak and RMS levels (dBFS), clipping, crest
    factor, loudness over time (one value per segment), leading/trailing
    silence, stereo correlation and a coarse spectral balance (low < 250 Hz,
    mid, high > 4 kHz), with warnings. Use it to check a mix or a recorded take.

    Parameters:
    - file_path: Absolute path of the audio file
    - segment_seconds: Length of each loudness segment (default 1 s)
    """
    from ..audio_analysis import analyze_audio

    result = analyze_audio(os.path.expanduser(file_path), segment_seconds=segment_seconds)
    return json.dumps(result, indent=2, ensure_ascii=False)


RESAMPLING_NAMES = ("resampling", "rééchantillonnage", "reechantillonnage",
                    "resampling", "neu-sampling", "remuestreo", "ricampionamento")


def _resampling_input_name(routing: Dict[str, Any]) -> Union[str, None]:
    """The localized name Live gives the Resampling input."""
    options = (routing.get("input") or {}).get("available_types") or []
    for name in options:
        low = (name or "").lower()
        if any(key in low for key in RESAMPLING_NAMES) or "sampl" in low:
            return name
    return None


MIX_TARGETS = ("streaming", "club", "classical", "broadcast", "podcast")


LISTEN_TRACK_NAME = "Claude – écoute"
SPECTROGRAMS_KEPT = 20


def _discard_take(path: str) -> bool:
    """Delete a listening take and Live's .asd analysis file next to it.

    Only files Live named after the listening track are touched, so a user's
    own recording can never be removed by mistake."""
    import unicodedata

    if not path:
        return False
    name = unicodedata.normalize("NFC", os.path.basename(path))
    if not name.startswith(LISTEN_TRACK_NAME) or not name.lower().endswith((".wav", ".aif", ".aiff")):
        return False
    removed = False
    for target in (path, path + ".asd"):
        try:
            os.remove(target)
            removed = removed or target == path
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning(f"Could not delete {target}: {e}")
    return removed


def _spectrogram_path(audio_path: str) -> str:
    import tempfile

    folder = os.path.join(tempfile.gettempdir(), "ableton-mcp")
    os.makedirs(folder, exist_ok=True)
    # Keep only the most recent images: older ones have been looked at.
    try:
        pngs = sorted((os.path.join(folder, f) for f in os.listdir(folder) if f.endswith("_spectrogram.png")),
                      key=os.path.getmtime)
        for old in pngs[:-SPECTROGRAMS_KEPT]:
            os.remove(old)
    except OSError:
        pass
    base = os.path.splitext(os.path.basename(audio_path))[0]
    return os.path.join(folder, base + "_spectrogram.png")


def _mix_report(path: str, target: str, spectrogram: bool):
    """(report dict, png path or None) from mix_analysis."""
    from ..mix_analysis import analyze_mix

    png = _spectrogram_path(path) if spectrogram else None
    return analyze_mix(path, target=target, spectrogram_path=png), png


def _with_image(payload: Dict[str, Any], png: Union[str, None]):
    """Tool result: the JSON report, plus the spectrogram as an image the
    model can look at."""
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if png and os.path.exists(png):
        from mcp.server.fastmcp import Image

        return [text, Image(path=png)]
    return text


class _MeterSampler:
    """Samples Live's track meters during a take and summarises them."""

    def __init__(self, ableton, skip_track: int):
        self.ableton, self.skip = ableton, skip_track
        self.samples: Dict[tuple, List[float]] = {}

    def __call__(self):
        data = self.ableton.call("get_track_meters")
        for m in data.get("meters", []):
            if m["type"] == "track" and m["index"] == self.skip:
                continue
            level = m.get("level")
            if level is not None:
                self.samples.setdefault((m["type"], m["index"], m["name"]), []).append(level)

    def summary(self) -> List[Dict[str, Any]]:
        out = []
        for (kind, index, name), vals in self.samples.items():
            active = [v for v in vals if v > 0.01]
            out.append({
                "type": kind, "index": index, "name": name,
                "peak_meter": round(max(vals), 3) if vals else None,
                "mean_meter_when_playing": round(sum(active) / len(active), 3) if active else 0.0,
                "active_pct": round(100.0 * len(active) / len(vals), 0) if vals else 0.0,
            })
        out.sort(key=lambda m: (m["type"] != "master", -m["mean_meter_when_playing"]))
        return out


@tool()
def get_track_meters() -> str:
    """
    Live's output meters right now for every track, return track and the
    main track (0.0-1.0 on Live's meter scale, as in the mixer). Meaningful
    while the song plays; listen_to_arrangement samples them for you.
    """
    live.require("get_track_meters")
    result = live.client().call("get_track_meters")
    return json.dumps(result, indent=2, ensure_ascii=False)


@tool()
def analyze_mix(file_path: str, target: str = "streaming",
                spectrogram: bool = True):
    """
    Mastering-engineer report on a WAV/AIFF mix: loudness per ITU-R BS.1770 /
    EBU R128 (integrated, short-term and momentary max, loudness range), true
    peak (4x oversampled), PLR, crest factor, long-term 1/3-octave spectrum
    with tilt and per-region deviation from a balanced -4.5 dB/oct reference
    (mud, harshness, sibilance, air, sub), narrow resonances (with note names),
    stereo correlation and width overall and per band (low-end mono), DC.
    Returns findings ranked problème / attention / ok with concrete fixes
    against the delivery target, plus a spectrogram image (log frequency,
    with the short-term loudness curve) to look at.

    Parameters:
    - file_path: Absolute path of the audio file
    - target: "streaming" (default, -14 LUFS), "club", "classical", "broadcast"
      (EBU -23 LUFS) or "podcast"
    - spectrogram: Also return the spectrogram image (default True)
    """
    if target not in MIX_TARGETS:
        return "target must be one of: %s" % ", ".join(MIX_TARGETS)
    report, png = _mix_report(os.path.expanduser(file_path), target, spectrogram)
    return _with_image(report, png)


@tool()
def listen_to_arrangement(start_time: float,
    end_time: float,
    target: str = "streaming",
    report: str = "mix",
    keep_track: bool = False,
    keep_audio: bool = False,
    segment_seconds: float = 1.0,
    max_wait_seconds: float = 600.0,
):
    """
    "Listen" to the song like a mastering engineer: record the main output
    between two song positions (beats) onto a temporary resampling audio
    track, sample every track's meter during the take, then analyze it.

    report="mix" (default) returns the full analyze_mix report (LUFS, true
    peak, PLR, tonal balance, resonances, stereo, findings with fixes against
    `target`) plus a spectrogram image, and each track's meter level during
    the take (which tracks carry the mix). report="basic" returns only levels,
    loudness per segment and a coarse spectral balance.
    Plays the song in real time, so it takes as long as the passage.

    Parameters:
    - start_time: Song position to start at (beats)
    - end_time: Song position to stop at (beats); add a few beats to hear reverb tails
    - target: Delivery target for the mix report: "streaming", "club",
      "classical", "broadcast" or "podcast"
    - report: "mix" (default) or "basic"
    - keep_track: Keep the recording track and its take in the set (default:
      delete both once analysed)
    - keep_audio: Keep the recorded file in the project's Samples/Recorded
      folder after deleting the track (default: delete it, so listening never
      piles up audio files in the project)
    - segment_seconds: Length of each loudness segment (basic report)
    - max_wait_seconds: Safety limit for the recording
    """
    for cap in ("set_track_routing", "record_arrangement", "get_audio_clip_file"):
        live.require(cap)
    if report not in ("mix", "basic"):
        return "report must be 'mix' or 'basic'"
    if report == "mix" and target not in MIX_TARGETS:
        return "target must be one of: %s" % ", ".join(MIX_TARGETS)
    ableton = live.client()
    track_index = None
    armed_before = []
    path = None
    try:
        session = ableton.call("get_session_info")
        tempo = float(session.get("tempo") or 120.0)
        # Only the listening track may record: disarm the others for the take.
        status = ableton.call("get_recording_status")
        armed_before = [t["index"] for t in status.get("armed_tracks", [])]
        for idx in armed_before:
            ableton.call("set_track_arm", {"track_index": idx, "arm": False})

        created = ableton.call("create_audio_track", {"index": -1})
        track_index = int(created["index"])
        ableton.call("set_track_name", {"track_index": track_index,
                                                "name": LISTEN_TRACK_NAME})
        routing = ableton.call("get_track_routing", {"track_index": track_index})
        resampling = _resampling_input_name(routing)
        if not resampling:
            raise RuntimeError("No Resampling input found among: %s"
                               % (routing.get("input") or {}).get("available_types"))
        ableton.call("set_track_routing", {
            "track_index": track_index, "input_type": resampling, "monitoring": "off"})
        ableton.call("set_track_arm", {"track_index": track_index, "arm": True})

        ableton.call("record_arrangement",
                             {"start_time": start_time, "end_time": end_time})
        expected = (end_time - start_time) * 60.0 / tempo
        sampler = None
        if report == "mix" and live.supports("get_track_meters"):
            sampler = _MeterSampler(ableton, track_index)
        rec_status = _wait_for_recording(ableton, expected, max_wait_seconds, on_poll=sampler)
        ableton.call("set_track_arm", {"track_index": track_index, "arm": False})

        clips = ableton.call("get_arrangement_clips",
                                     {"track_index": track_index}).get("clips", [])
        if not clips:
            raise RuntimeError("Nothing was recorded (status: %s)" % json.dumps(rec_status))
        file_info = ableton.call("get_audio_clip_file", {
            "track_index": track_index, "clip_index": len(clips) - 1,
            "location": "arrangement"})
        path = file_info.get("file_path")
        if not path:
            raise RuntimeError("Live did not report the recorded file's path")

        from ..audio_analysis import analyze_audio

        # Live finishes writing the file just after recording stops.
        analysis, png, last_error = None, None, None
        for _ in range(10):
            try:
                if report == "mix":
                    analysis, png = _mix_report(path, target, True)
                else:
                    analysis = analyze_audio(path, segment_seconds=segment_seconds)
                break
            except ImportError:  # numpy missing: fall back to the basic report
                report = "basic"
            except Exception as e:  # file still being finalised
                last_error = e
                time.sleep(0.5)
        if analysis is None:
            raise RuntimeError("Could not read the recorded file: %s" % last_error)

        result = {
            "recorded": {"start_time": start_time, "end_time": end_time,
                         "file_path": path, "status": rec_status.get("recording")},
            "analysis": analysis,
        }
        if sampler is not None:
            result["track_meters_during_take"] = {
                "scale": "Live meter scale 0.0-1.0 (as in the mixer), sampled every %.1f s"
                         % RECORDING_POLL_S,
                "tracks": sampler.summary(),
            }
        if not keep_track:
            ableton.call("delete_track", {"track_index": track_index})
            track_index = None
            if keep_audio:
                result["recorded"]["track"] = "deleted (file kept)"
            else:
                removed = _discard_take(path)
                result["recorded"]["track"] = "deleted"
                result["recorded"]["file"] = "deleted" if removed else "kept (could not delete)"
        else:
            result["recorded"]["track_index"] = track_index
        return _with_image(result, png)
    except Exception:
        # Leave the set as it was: no half-recorded listening track or take.
        if track_index is not None and not keep_track:
            try:
                ableton.call("stop_arrangement_recording")
                ableton.call("delete_track", {"track_index": track_index})
                if path and not keep_audio:
                    _discard_take(path)
            except Exception:   # best effort; the original error matters more
                log.warning("Could not clean up the listening track %s", track_index)
        raise
    finally:
        for idx in armed_before:
            try:
                ableton.call("set_track_arm", {"track_index": idx, "arm": True})
            except Exception:
                pass
