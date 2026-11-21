"""Producer automation gestures, drawn as clip envelope points.

A gesture is a named move a producer makes on one parameter of a clip: a
delay throw at the end of each phrase, a reverb swell, a filter opening, the
cut before a drop... Each returns the envelope points, the interpolation, the
parameter's resting value and the value the clip ends on.

Why the end value matters (measured in Live 12.4): a clip envelope moves the
parameter while its clip plays and leaves it where it ends. A clip without an
envelope for that parameter doesn't reset it, so after a cut to silence the
next section stays silent unless its clips hold the resting value.
"""

from __future__ import annotations

from typing import Dict, List

from .arrangement import curve_points


class GestureError(ValueError):
    """A gesture that can't be drawn as asked."""


# name: (what it touches, what it does)
GESTURES = {
    "delay_throw": ("send", "Send jumps to the delay on the last beat(s) of each phrase, then back"),
    "reverb_swell": ("send", "Reverb send rises to a peak mid-clip and falls back"),
    "filter_rise": ("filter", "Filter opens from closed to the sound as set (a build-up)"),
    "filter_fall": ("filter", "Filter closes over the clip (a fade into a break)"),
    "drop_cut": ("volume", "Silence on the last beat(s), the breath before the drop"),
    "stutter": ("volume", "Volume gated in 16ths on the last beat(s), then back"),
    "fade_in": ("volume", "Volume rises from silence over the clip"),
    "fade_out": ("volume", "Volume falls to silence over the clip"),
}


def gesture_target(gesture: str) -> str:
    if gesture not in GESTURES:
        raise GestureError("Unknown gesture '%s'. Gestures: %s" % (gesture, ", ".join(GESTURES)))
    return GESTURES[gesture][0]


def gesture_points(gesture: str, length: float, rest: float, peak: float, low: float,
                   phrase_beats: float = 16.0, tail_beats: float = 1.0,
                   resolution: float = 0.5) -> Dict:
    """Envelope for one clip.

    - rest: the parameter's normal value (the fader, the send, the open filter)
    - peak: the high point (delay/reverb send)
    - low: the low point (closed filter, silence)
    - phrase_beats: phrase length for delay throws
    - tail_beats: how long the throw, cut or stutter lasts at the end
    """
    gesture_target(gesture)
    if length <= 0:
        raise GestureError("The clip has no length")
    tail = min(max(float(tail_beats), 0.0625), length)
    if gesture == "delay_throw":
        if phrase_beats <= 0:
            raise GestureError("phrase_beats must be positive")
        pts: List[Dict[str, float]] = [{"time": 0.0, "value": rest}]
        end = phrase_beats
        while end <= length + 1e-6:
            pts += [{"time": end - min(tail, phrase_beats), "value": peak}, {"time": end, "value": rest}]
            end += phrase_beats
        return {"points": _clip(pts, length), "interpolation": "step", "rest": rest, "end_value": rest}
    if gesture == "reverb_swell":
        return {"points": curve_points(length, rest, peak, "swell", resolution=resolution),
                "interpolation": "linear", "rest": rest, "end_value": rest}
    if gesture == "filter_rise":
        return {"points": curve_points(length, low, rest, "exp", resolution=resolution),
                "interpolation": "linear", "rest": rest, "end_value": rest}
    if gesture == "filter_fall":
        return {"points": curve_points(length, rest, low, "log", resolution=resolution),
                "interpolation": "linear", "rest": rest, "end_value": low}
    if gesture == "drop_cut":
        return {"points": [{"time": 0.0, "value": rest}, {"time": length - tail, "value": low}],
                "interpolation": "step", "rest": rest, "end_value": low}
    if gesture == "stutter":
        pts = [{"time": 0.0, "value": rest}]
        t, on = length - tail, False
        while t < length - 1e-6:
            pts.append({"time": t, "value": rest if on else low})
            t, on = t + 0.125, not on            # 32nds: on/off pairs make a 16th gate
        pts.append({"time": length, "value": rest})
        return {"points": _clip(pts, length), "interpolation": "step", "rest": rest, "end_value": rest}
    if gesture == "fade_in":
        return {"points": curve_points(length, low, rest, "s_curve", resolution=resolution),
                "interpolation": "linear", "rest": rest, "end_value": rest}
    # fade_out
    return {"points": curve_points(length, rest, low, "s_curve", resolution=resolution),
            "interpolation": "linear", "rest": rest, "end_value": low}


def _clip(points: List[Dict[str, float]], length: float) -> List[Dict[str, float]]:
    """Points inside [0, length], last one at a time wins."""
    out: Dict[float, float] = {}
    for p in points:
        t = round(min(max(p["time"], 0.0), length), 6)
        out[t] = p["value"]
    return [{"time": t, "value": v} for t, v in sorted(out.items())]


# Names Live uses for a filter's cutoff, best first (Auto Filter, Drift,
# Wavetable, Simpler/Sampler, Operator, Analog).
CUTOFF_NAMES = ("Frequency", "LP Freq", "Flt 1 Freq", "Filter Freq", "Filter 1 Freq", "F1 Freq")
DELAY_WORDS = ("delay", "echo")
REVERB_WORDS = ("reverb", "verb", "hall", "room", "plate", "space")


def find_return(names: List[str], words) -> int | None:
    for i, name in enumerate(names):
        low = name.lower()
        if any(w in low for w in words):
            return i
    return None
