"""Starting points for classic electronic sounds on Live's native synths.

Each recipe names a device, the parameter values that make the sound (as
musical values, see set_device_parameters), how to play it, and what to
listen for. They are starting points: design_sound applies one, the
assistant then auditions it and adjusts.
"""

from __future__ import annotations

RECIPES = {
    "sub_bass": {
        "device": "Drift", "uri": "query:Synths#Drift", "role": "bass",
        "description": "Clean, round sine sub: weight under a kick without mud.",
        "values": {"Osc 1 Wave": "Sine", "Osc 2 On": "Off", "Noise On": "Off",
                   "LP Freq": "400 Hz", "LP Res": "0.1", "LP Mod Amt 1": "0 %", "LP Mod Amt 2": "0 %",
                   "Env 1 Attack": "2 ms", "Env 1 Decay": "300 ms", "Env 1 Sustain": "100 %",
                   "Env 1 Release": "80 ms", "Drift": "0 %", "Spread": "0 %",
                   "Legato On": "On", "Glide Time": "30 ms", "Volume": "-6 dB"},
        "play": "Long notes on the root, C0–C2; one voice at a time (legato).",
        "listen": "Nearly all energy below 120 Hz; no harmonics above ~400 Hz.",
    },
    "acid_bass": {
        "device": "Drift", "uri": "query:Synths#Drift", "role": "bass",
        "description": "Resonant 303-style line: squelchy filter envelope, slides.",
        "values": {"Osc 1 Wave": "Saw", "Osc 2 On": "Off", "Noise On": "Off",
                   "LP Type": "II", "LP Freq": "350 Hz", "LP Res": "0.75", "LP Mod Amt 1": "60 %",
                   "Env 2 Attack": "1 ms", "Env 2 Decay": "180 ms", "Env 2 Sustain": "0 %", "Env 2 Release": "60 ms",
                   "Env 1 Attack": "1 ms", "Env 1 Decay": "300 ms", "Env 1 Sustain": "80 %", "Env 1 Release": "40 ms",
                   "Legato On": "On", "Glide Time": "60 ms", "Drift": "3 %", "Volume": "-6 dB"},
        "play": "16th notes around C1–C2 with accents (velocity) and overlapping notes for slides.",
        "listen": "Strong resonant peak that moves; bright mids. Automate LP Freq for the classic sweep.",
    },
    "reese_bass": {
        "device": "Drift", "uri": "query:Synths#Drift", "role": "bass",
        "description": "Two detuned saws beating against each other: dark, moving drum & bass / techno bass.",
        "values": {"Osc 1 Wave": "Saw", "Osc 2 Wave": "Saw", "Osc 2 On": "On", "Osc 2 Oct": "0",
                   "Osc 2 Detune": "0.3", "Osc 1 Gain": "-6 dB", "Osc 2 Gain": "-6 dB", "Noise On": "Off",
                   "LP Freq": "700 Hz", "LP Res": "0.2", "LP Mod Amt 1": "0 %",
                   "Env 1 Attack": "3 ms", "Env 1 Sustain": "100 %", "Env 1 Release": "120 ms",
                   "Legato On": "On", "Drift": "10 %", "Volume": "-8 dB"},
        "play": "Long held notes, C1–C2.",
        "listen": "Slow phasing between the saws; low-mids full, little above 2 kHz.",
    },
    "dub_chord_stab": {
        "device": "Drift", "uri": "query:Synths#Drift", "role": "chords",
        "description": "Short filtered chord for dub techno; send it to a delay and reverb.",
        "values": {"Osc 1 Wave": "Saw", "Osc 2 Wave": "Saw", "Osc 2 On": "On", "Osc 2 Oct": "0",
                   "Osc 2 Detune": "0.12", "Noise On": "Off",
                   "LP Freq": "900 Hz", "LP Res": "0.25", "LP Mod Amt 1": "35 %",
                   "Env 2 Attack": "1 ms", "Env 2 Decay": "250 ms", "Env 2 Sustain": "0 %",
                   "Env 1 Attack": "2 ms", "Env 1 Decay": "350 ms", "Env 1 Sustain": "0 %", "Env 1 Release": "250 ms",
                   "Spread": "30 %", "Volume": "-8 dB"},
        "play": "Minor 7th / minor 9th chords around C3, short off-beat hits.",
        "listen": "Short, dark-but-present mids (300 Hz–2 kHz); the tail comes from the delay, not the synth.",
    },
    "pluck": {
        "device": "Drift", "uri": "query:Synths#Drift", "role": "melody",
        "description": "Short, percussive pluck for arpeggios and hooks.",
        "values": {"Osc 1 Wave": "Pulse", "Osc 2 Wave": "Triangle", "Osc 2 On": "On", "Osc 2 Oct": "0",
                   "Noise On": "Off", "LP Freq": "1.2 kHz", "LP Res": "0.3", "LP Mod Amt 1": "70 %",
                   "Env 2 Attack": "1 ms", "Env 2 Decay": "220 ms", "Env 2 Sustain": "0 %",
                   "Env 1 Attack": "1 ms", "Env 1 Decay": "450 ms", "Env 1 Sustain": "0 %", "Env 1 Release": "200 ms",
                   "Volume": "-8 dB"},
        "play": "16th-note arpeggios, C3–C5.",
        "listen": "Bright attack that closes quickly; no sustain.",
    },
    "warm_pad": {
        "device": "Drift", "uri": "query:Synths#Drift", "role": "chords",
        "description": "Slow, wide, slightly drifting pad.",
        "values": {"Osc 1 Wave": "Saw", "Osc 2 Wave": "Saw", "Osc 2 On": "On", "Osc 2 Oct": "0",
                   "Osc 2 Detune": "0.15", "Noise On": "Off",
                   "LP Freq": "1.5 kHz", "LP Res": "0.15", "LP Mod Amt 1": "20 %",
                   "Env 1 Attack": "800 ms", "Env 1 Decay": "2 s", "Env 1 Sustain": "85 %", "Env 1 Release": "1.5 s",
                   "Env 2 Attack": "1 s", "Env 2 Sustain": "40 %",
                   "Spread": "60 %", "Drift": "15 %", "Volume": "-10 dB"},
        "play": "Long chords (whole bars), C3–C5.",
        "listen": "Soft attack, broad mids, gentle highs; wide stereo.",
    },
    "supersaw": {
        "device": "Wavetable", "uri": "query:Synths#Wavetable", "role": "chords",
        "description": "Big unison lead/chords for trance and big-room moments.",
        "values": {"Osc 2 On": "On", "Osc 2 Detune": "12 ct", "Osc 1 Detune": "-12 ct",
                   "Flt 1 Type": "Lowpass", "Flt 1 Slope": "24", "Flt 1 Freq": "6 kHz", "Flt 1 Res": "10 %",
                   "Amp Attack": "5 ms", "Amp Sustain": "-3 dB", "Amp Release": "400 ms",
                   "Unison Amount": "60 %", "Volume": "-12 dB"},
        "play": "Chords or a lead, C3–C6.",
        "listen": "Wide and bright; watch the 2–6 kHz harshness and the level (unison adds up).",
    },
    "fm_bell": {
        "device": "Operator", "uri": "query:Synths#Operator", "role": "melody",
        "description": "Glassy FM bell: a sine modulated at a non-integer ratio, long decay.",
        "values": {"Algorithm": "Alg. 1", "B Coarse": "4", "Osc-B Level": "-12 dB",
                   "Be Attack": "0 ms", "Be Decay": "1.2 s", "Be Sustain": "-inf dB",
                   "Ae Attack": "0 ms", "Ae Decay": "2.5 s", "Ae Sustain": "-inf dB", "Ae Release": "1.5 s",
                   "Volume": "-12 dB"},
        "play": "Sparse notes, C4–C6.",
        "listen": "Clear fundamental with inharmonic overtones fading faster than the body.",
    },
}

# Test phrases for auditioning: (pitch offset from the root, start beat, length, velocity)
PHRASES = {
    "bass": [(0, i * 0.5, 0.45, 110 if i % 4 == 0 else 90) for i in range(8)],
    "chords": [(o, s, 1.5, 95) for s in (0.0, 2.0) for o in (0, 3, 7, 10)],
    "melody": [(o, i * 0.25, 0.22, 100) for i, o in enumerate((0, 7, 12, 15, 12, 7, 3, 7, 0, 7, 12, 15, 19, 15, 12, 7))],
}
ROOTS = {"bass": 36, "chords": 60, "melody": 72}   # C1, C3, C4


def recipe(name: str) -> dict:
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    if key not in RECIPES:
        raise ValueError(f"No recipe '{name}'. Recipes: {', '.join(sorted(RECIPES))}")
    return RECIPES[key]


def phrase(role: str, root: int | None = None) -> list[dict]:
    base = ROOTS.get(role, 60) if root is None else int(root)
    return [{"pitch": max(0, min(127, base + o)), "start_time": s, "duration": d, "velocity": v, "mute": False}
            for o, s, d, v in PHRASES.get(role, PHRASES["melody"])]
