"""Long-form evolution and arrangement for electronic music.

* Automation curves over many bars (linear, exponential build, ease-out,
  S-curve, slow sine/triangle LFO, phrase steps, random walk, swell) turned
  into clip-envelope points.
* Clip extension: tile a short MIDI loop to 32/64 bars so a long envelope
  can ride on it.
* Arrangement templates (DJ-friendly techno, compact 64-bar techno,
  house, minimal) as sections with an energy level and the roles that play.
* Track roles from track names, and an arrangement plan: which Session clip
  goes where in the Arrangement, tiled to fill each section, plus locators.

Live's API cannot write Arrangement automation, but a Session clip's
envelopes become track automation when the clip is copied to the
Arrangement (checked by ear in Live 12): automate a Session clip, then
place it with build_arrangement.
"""

import math
import random
from typing import Dict, List, Optional, Sequence


class ArrangementError(ValueError):
    pass


# ------------------------------------------------------------------ curves

def _shape(shape: str, t: float, cycles: float, steps: int, power: float, rnd: random.Random,
           state: Dict) -> float:
    """0..1 for position t in 0..1."""
    if shape == "linear":
        return t
    if shape in ("exp", "build", "ease_in"):  # slow start, fast end: classic build-up
        return t ** power
    if shape in ("log", "ease_out", "release"):
        return 1 - (1 - t) ** power
    if shape in ("s_curve", "smooth"):
        return t * t * (3 - 2 * t)
    if shape == "swell":  # up then back down
        return math.sin(math.pi * t)
    if shape == "sine":
        return 0.5 - 0.5 * math.cos(2 * math.pi * cycles * t)
    if shape == "triangle":
        x = (cycles * t) % 1.0
        return 2 * x if x < 0.5 else 2 * (1 - x)
    if shape == "steps":  # rises in equal stairs (e.g. one step per 8-bar phrase)
        return min(math.floor(t * steps) / max(steps - 1, 1), 1.0)
    if shape == "random_walk":
        v = state.get("v", 0.5) + rnd.gauss(0, 0.06)
        state["v"] = min(1.0, max(0.0, v))
        return state["v"]
    if shape == "hold":
        return 0.0
    raise ArrangementError("Unknown shape '%s'. Known: %s" % (shape, ", ".join(SHAPES)))


SHAPES = {
    "linear": "Rampe régulière",
    "exp": "Montée lente puis rapide (build-up classique ; power règle la courbure)",
    "log": "Montée rapide puis douce (ouverture, release)",
    "s_curve": "Départ et arrivée en douceur",
    "swell": "Monte puis redescend (vague sur la durée)",
    "sine": "LFO lent sinusoïdal (cycles = nombre d'allers-retours sur la durée)",
    "triangle": "LFO lent triangulaire",
    "steps": "Paliers (steps = nombre de paliers, ex. un par phrase de 8 mesures)",
    "random_walk": "Dérive aléatoire douce (vie organique, seed)",
    "hold": "Valeur fixe (start)",
}


def curve_points(length_beats: float, start: float, end: float, shape: str = "linear",
                 resolution: float = 1.0, cycles: float = 1.0, steps: int = 4, power: float = 2.5,
                 offset: float = 0.0, seed: int = 0) -> List[Dict[str, float]]:
    """Envelope points {time, value} every ``resolution`` beats."""
    if length_beats <= 0 or resolution <= 0:
        raise ArrangementError("length and resolution must be positive")
    rnd, state = random.Random(seed), {}
    n = int(round(length_beats / resolution))
    pts = []
    for i in range(n + 1):
        t = i / n if n else 1.0
        y = _shape(shape, t, cycles, steps, power, rnd, state)
        pts.append({"time": round(offset + i * resolution, 6), "value": round(start + (end - start) * y, 6)})
    return pts


def tile_notes(notes: List[Dict], loop_length: float, target_length: float) -> List[Dict]:
    """Repeat a loop's notes until target_length (beats)."""
    if loop_length <= 0:
        raise ArrangementError("loop length must be positive")
    out, k = [], 0
    while k * loop_length < target_length - 1e-9:
        for n in notes:
            s = n["start_time"] + k * loop_length
            if s < target_length - 1e-9 and n["start_time"] < loop_length - 1e-9:
                m = {key: n[key] for key in ("pitch", "start_time", "duration", "velocity", "mute") if key in n}
                for opt in ("probability", "velocity_deviation", "release_velocity"):
                    if opt in n and n[opt] is not None:
                        m[opt] = n[opt]
                m["start_time"] = round(s, 6)
                m["duration"] = min(n["duration"], target_length - s)
                out.append(m)
        k += 1
    return out


# ------------------------------------------------------------------- roles

ROLE_WORDS = [
    ("kick", ["kick", "kik", "bd", "grosse caisse"]),
    ("hats", ["hat", "hh", "hihat", "charley", "ride", "shaker", "top"]),
    ("perc", ["perc", "conga", "bongo", "tom", "rim", "clap", "snare", "cowbell", "clave"]),
    ("drums", ["drum", "beat", "batterie", "groove", "loop", "break"]),
    ("rumble", ["rumble"]),
    ("bass", ["bass", "basse", "sub", "303", "acid"]),
    ("chords", ["chord", "accord", "stab", "dub", "keys", "piano", "rhodes", "organ", "orgue"]),
    ("pad", ["pad", "nappe", "drone", "atmo", "ambience", "texture", "string"]),
    ("lead", ["lead", "synth", "arp", "melod", "hook", "seq"]),
    ("vocal", ["vocal", "vox", "voix", "voice", "chant"]),
    ("fx", ["fx", "riser", "sweep", "noise", "impact", "crash", "uplifter", "downlifter", "reverse"]),
]


def infer_track_roles(tracks: List[Dict]) -> Dict[int, str]:
    """track index -> role from its name (first matching role wins)."""
    roles = {}
    for t in tracks:
        name = " %s " % str(t.get("name", "")).lower().replace("_", " ").replace("-", " ")
        for role, words in ROLE_WORDS:
            if any(w in name for w in words):
                roles[int(t["index"])] = role
                break
    return roles


# --------------------------------------------------------------- templates

def _sec(name, bars, energy, roles, tip=""):
    return {"name": name, "bars": bars, "energy": energy, "roles": list(roles), "tip": tip}


ALL = ["kick", "drums", "hats", "perc", "rumble", "bass", "chords", "pad", "lead", "vocal", "fx"]

TEMPLATES: Dict[str, Dict] = {
    "techno_dj": {
        "label": "Techno, structure DJ (≈ 6-7 min à 130 BPM)",
        "sections": [
            _sec("Intro DJ", 32, 0.35, ["kick", "drums", "hats"],
                 "Kick + charleys seuls : le DJ cale sa transition. Varier les charleys tous les 8 mesures."),
            _sec("Groove", 32, 0.6, ["kick", "drums", "hats", "perc", "rumble", "bass"],
                 "Entrée de la basse/rumble ; ouvrir lentement un filtre sur 32 mesures."),
            _sec("Break 1", 16, 0.3, ["hats", "chords", "pad", "fx"],
                 "Kick coupé, l'harmonie respire ; réverbe et delay en hausse."),
            _sec("Montée", 16, 0.75, ["drums", "hats", "perc", "chords", "fx"],
                 "Tension : filtre et résonance en courbe exp, roulement de clap, riser."),
            _sec("Peak 1", 32, 1.0, ALL, "Tout entre ; garder un élément en réserve pour le peak 2."),
            _sec("Break 2", 16, 0.4, ["perc", "chords", "pad", "lead", "fx"],
                 "Variation de l'accord ou du motif lead."),
            _sec("Peak 2", 32, 1.0, ALL, "Version la plus intense (élément gardé en réserve, ouverture max)."),
            _sec("Outro DJ", 32, 0.35, ["kick", "drums", "hats"],
                 "Retirer les éléments par 8 mesures, finir kick + charleys pour le mix."),
        ],
    },
    "techno_64": {
        "label": "Techno compacte en 64 mesures (≈ 2 min à 130 BPM)",
        "sections": [
            _sec("Intro", 8, 0.35, ["kick", "drums", "hats"]),
            _sec("Groove", 16, 0.65, ["kick", "drums", "hats", "perc", "rumble", "bass"]),
            _sec("Break", 8, 0.3, ["hats", "chords", "pad", "fx"]),
            _sec("Montée", 8, 0.75, ["drums", "hats", "perc", "chords", "fx"]),
            _sec("Peak", 16, 1.0, ALL),
            _sec("Outro", 8, 0.35, ["kick", "drums", "hats"]),
        ],
    },
    "minimal": {
        "label": "Minimal / hypnotique (évolution par ajouts subtils)",
        "sections": [
            _sec("Intro", 16, 0.3, ["kick", "drums", "hats"]),
            _sec("Couche 1", 16, 0.45, ["kick", "drums", "hats", "perc"]),
            _sec("Couche 2", 16, 0.6, ["kick", "drums", "hats", "perc", "bass"]),
            _sec("Couche 3", 32, 0.75, ["kick", "drums", "hats", "perc", "bass", "chords", "rumble"]),
            _sec("Respiration", 8, 0.4, ["hats", "perc", "chords", "pad"]),
            _sec("Plein", 32, 0.85, ALL),
            _sec("Outro", 16, 0.3, ["kick", "drums", "hats"]),
        ],
    },
    "house": {
        "label": "House (intro/outro 16 mesures, couplets-refrains)",
        "sections": [
            _sec("Intro", 16, 0.4, ["kick", "drums", "hats"]),
            _sec("Groove", 16, 0.6, ["kick", "drums", "hats", "perc", "bass"]),
            _sec("Partie A", 16, 0.75, ["kick", "drums", "hats", "perc", "bass", "chords"]),
            _sec("Break", 16, 0.35, ["chords", "pad", "vocal", "fx"]),
            _sec("Partie B", 32, 1.0, ALL),
            _sec("Outro", 16, 0.4, ["kick", "drums", "hats"]),
        ],
    },
}


def template_sections(name: str) -> List[Dict]:
    if name not in TEMPLATES:
        raise ArrangementError("Unknown template '%s'. Known: %s" % (name, ", ".join(TEMPLATES)))
    return [dict(s) for s in TEMPLATES[name]["sections"]]


# -------------------------------------------------------------------- plan

def plan_arrangement(sections: Sequence[Dict], tracks: List[Dict], track_roles: Dict[int, str],
                     beats_per_bar: float = 4.0, start_bar: int = 0, default_slot: int = 0) -> Dict:
    """Placements of Session clips in the Arrangement.

    ``tracks``: [{index, name, slots: {slot: length_beats}}].
    Each section either lists ``roles`` (tracks whose role is in it play
    their ``default_slot`` clip, or the section's ``slots`` override
    {track_index: slot}) or gives ``play`` {track_index: slot or None}.
    A clip is tiled to fill the section; a clip longer than the section is
    placed once if it fits exactly, otherwise reported.
    """
    by_index = {int(t["index"]): t for t in tracks}
    placements, locators, warnings, table = [], [], [], []
    bar = start_bar
    for sec in sections:
        bars = int(sec["bars"])
        start = bar * beats_per_bar
        end = start + bars * beats_per_bar
        locators.append({"beat": start, "name": sec["name"]})
        if "play" in sec and sec["play"] is not None:
            plays = {int(k): v for k, v in sec["play"].items()}
        else:
            roles = set(sec.get("roles", []))
            plays = {i: default_slot for i, r in track_roles.items() if r in roles}
            for k, v in (sec.get("slots") or {}).items():
                plays[int(k)] = v
        playing = []
        for ti, slot in sorted(plays.items()):
            if slot is None:
                continue
            t = by_index.get(ti)
            if t is None:
                warnings.append("%s: track %d does not exist" % (sec["name"], ti))
                continue
            length = (t.get("slots") or {}).get(int(slot))
            if not length:
                warnings.append("%s: no clip in slot %d of '%s'" % (sec["name"], slot, t["name"]))
                continue
            pos = start
            while pos + length <= end + 1e-6:
                placements.append({"track_index": ti, "clip_index": int(slot), "start": pos})
                pos += length
            if pos < end - 1e-6:
                warnings.append("%s: '%s' clip (%g beats) does not divide the section (%g beats); "
                                "%g beats left empty" % (sec["name"], t["name"], length, end - start, end - pos))
            playing.append(t["name"])
        table.append({"section": sec["name"], "bar": bar + 1, "bars": bars,
                      "energy": sec.get("energy"), "tracks": playing, "tip": sec.get("tip", "")})
        bar += bars
    return {"placements": placements, "locators": locators, "warnings": warnings, "sections": table,
            "total_bars": bar - start_bar, "end_beat": bar * beats_per_bar}


def activity_map(clips_by_track: Dict[str, List[Dict]], block_beats: float, end_beat: float) -> Dict[str, str]:
    """One character per block: '#' if the track has a clip sounding there."""
    blocks = int(math.ceil(end_beat / block_beats)) if end_beat > 0 else 0
    out = {}
    for name, clips in clips_by_track.items():
        row = []
        for b in range(blocks):
            a, z = b * block_beats, (b + 1) * block_beats
            row.append("#" if any(c["start_time"] < z and c["end_time"] > a for c in clips) else ".")
        out[name] = "".join(row)
    return out
