"""Chopping samples: tempo and key from a file name, and chop patterns.

What makes a chop pattern groove (learned building a track with it):

* a grain that comes back at the same place every bar reads as a hook;
  a different random grain on every hit reads as noise;
* accents on the off-beats and ghost hits with a chance under 100 % make it
  breathe, so each pass is a little different;
* the last bar of a phrase varies, so the loop doesn't feel stuck.
"""

from __future__ import annotations

import random
import re
from typing import Dict, List, Optional

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLATS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
STYLES = {
    "hook": "Same grain at the same place every bar, off-beat accents, ghost hits with a chance; "
            "the last bar varies",
    "rearrange": "The slices reshuffled on the grid, with a few ratchets: the loop re-sequenced",
    "stutter": "The slices in order, each bar ending on a ratchet of its last slice",
}


class ChopError(ValueError):
    """A chop that can't be made as asked."""


def tempo_from_name(name: str) -> Optional[float]:
    """The tempo written in a sample's name ("..._127_vocal...", "120bpm")."""
    for match in re.finditer(r"(?<![\d.])(\d{2,3})(?:\s*bpm)?(?![\d.])", name, re.IGNORECASE):
        bpm = float(match.group(1))
        if 60 <= bpm <= 200:
            return bpm
    return None


def key_from_name(name: str) -> Optional[Dict]:
    """The key written in a sample's name ("Fmin", "D#min", "C#m", "Ebmaj")."""
    for token in re.split(r"[\s_\-.()\[\]]+", name):
        m = re.fullmatch(r"([A-G])([#b]?)(min|maj|m|minor|major)", token)
        if m:
            root = m.group(1) + m.group(2)
            root = FLATS.get(root, root)
            if root in NOTE_NAMES:
                return {"root": root, "minor": m.group(3) in ("min", "m", "minor")}
    return None


def transpose_to(sample_root: str, song_root: str) -> int:
    """Semitones from the sample's root to the song's, the shortest way (-6..+5)."""
    a = NOTE_NAMES.index(FLATS.get(sample_root, sample_root))
    b = NOTE_NAMES.index(FLATS.get(song_root, song_root))
    shift = (b - a) % 12
    return shift - 12 if shift > 5 else shift


def warp_beats(duration_s: float, bpm: Optional[float]) -> Optional[int]:
    """Beats the sample lasts at its own tempo, rounded to a whole bar."""
    if not bpm or duration_s <= 0:
        return None
    beats = duration_s * bpm / 60.0
    return max(4, int(round(beats / 4.0)) * 4)


def chop_pattern(slices: int, style: str = "hook", bars: int = 4, micro: bool = False,
                 density: float = 0.5, seed: int = 0, first_note: int = 36) -> List[Dict]:
    """Notes playing a sliced Simpler (slice k = note first_note + k)."""
    if style not in STYLES:
        raise ChopError("Unknown style '%s'. Styles: %s" % (style, ", ".join(STYLES)))
    if slices < 2:
        raise ChopError("Need at least 2 slices")
    rng = random.Random(seed)
    step = 0.125 if micro else 0.25                  # 32nds for micro-chops, 16ths otherwise
    per_bar = int(round(4.0 / step))
    gate = 0.06 if micro else 0.18
    density = min(max(float(density), 0.05), 1.0)
    notes: List[Dict] = []

    def note(slice_k, t, dur, vel, chance=1.0):
        n = {"pitch": first_note + (slice_k % slices), "start_time": round(t, 6),
             "duration": dur, "velocity": int(vel), "mute": False}
        if chance < 1.0:
            n["probability"] = round(chance, 2)
        notes.append(n)

    if style == "hook":
        positions = sorted(rng.sample(range(per_bar), max(2, int(per_bar * density * 0.6))))
        grain = {p: rng.randrange(slices) for p in positions}
        alt = {p: rng.randrange(slices) for p in positions}
        for b in range(bars):
            last = b == bars - 1
            for p in positions:
                accent = (p * step) % 1.0 in (0.5, 0.75)     # the "and" and the "a" of the beat
                k = alt[p] if last and p >= per_bar // 2 else grain[p]
                note(k, b * 4.0 + p * step, gate * (1.6 if accent else 1.0),
                     112 if accent else rng.choice((66, 76, 86)), 1.0 if accent or p == 0 else 0.7)
        return notes

    if style == "rearrange":
        order = list(range(slices))
        for b in range(bars):
            rng.shuffle(order)
            for s in range(per_bar):
                if rng.random() > density + 0.2:
                    continue
                t = b * 4.0 + s * step
                k = order[s % slices]
                if rng.random() < 0.08:              # a ratchet now and then
                    for r in range(3):
                        note(k, t + r * step / 3, step / 3, 80 + 12 * r)
                else:
                    note(k, t, step * 0.9, rng.choice((72, 88, 104, 118)), 1.0 if s % 4 == 0 else 0.85)
        return notes

    # stutter: the sample in order, each bar ending on a ratchet
    per_slice = max(step, 4.0 * bars / slices)
    t, k = 0.0, 0
    end = 4.0 * bars
    while t < end - 1e-6:
        bar_end = (int(t // 4.0) + 1) * 4.0
        if t >= bar_end - 0.5:                       # last half beat of the bar: ratchet
            for r in range(4):
                note(k, t + r * 0.125, 0.1, 80 + 10 * r)
            t = bar_end
            continue
        note(k, t, min(per_slice, bar_end - t) * 0.95, 100)
        t += per_slice
        k += 1
    return notes
