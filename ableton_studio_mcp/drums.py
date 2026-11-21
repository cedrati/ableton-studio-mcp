"""Drum programming for electronic music (no dependency).

* Roles (kick, clap, closed_hat...) resolved from a Drum Rack's pad names
  (English and French keywords), falling back to General MIDI notes.
* A step-grid language, one string per role:
    x hit · X accent · o ghost · . or - rest · 2 3 4 ratchet (that many hits
    in the step) · ? 50 % probability · * 25 % probability ghost
  Spaces and | are ignored, so "x... x... | x... x..." is fine.
* Euclidean rhythms (Bjorklund) with rotation, for polyrhythmic percussion.
* A pattern library focused on techno and electronic styles, with tempo,
  swing and production notes.
* Bars, fills (roll, drop, open-hat lift, crash) and variation through
  Live 12's per-note probability.
"""

import random
import re
from typing import Dict, List, Optional, Tuple

GM_NOTES = {
    "kick": 36, "rim": 37, "snare": 38, "clap": 39, "closed_hat": 42, "pedal_hat": 44,
    "open_hat": 46, "tom_low": 45, "tom_mid": 47, "tom_high": 50, "crash": 49, "ride": 51,
    "cowbell": 56, "conga": 63, "bongo": 61, "clave": 75, "shaker": 70, "tambourine": 54,
    "perc": 67, "fx": 49,
}

# Pad-name keywords per role, most specific first.
ROLE_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("open_hat", ["open hat", "open hh", "openhat", "ohh", "oh ", " oh", "hh open", "hat open", "hihat open",
                  "charley ouvert", "hat ouvert"]),
    ("closed_hat", ["closed hat", "closed hh", "closedhat", "chh", "ch ", "hh closed", "hat closed", "hihat",
                    "hi-hat", "hi hat", "hat", "hh", "charley"]),
    ("pedal_hat", ["pedal"]),
    ("kick", ["kick", "kik", "bd", "bass drum", "bassdrum", "grosse caisse", "808 kick", "909 kick"]),
    ("clap", ["clap", "cp", "handclap"]),
    ("snare", ["snare", "sd", "caisse claire", "snr"]),
    ("rim", ["rim", "rimshot", "sidestick", "side stick", "stick"]),
    ("ride", ["ride"]),
    ("crash", ["crash", "cymbal", "cymbale", "splash"]),
    ("tom_low", ["low tom", "tom low", "floor tom", "tom 1", "lt"]),
    ("tom_high", ["high tom", "hi tom", "tom high", "tom 3", "ht"]),
    ("tom_mid", ["mid tom", "tom mid", "tom 2", "tom", "mt"]),
    ("cowbell", ["cowbell", "bell", "cloche"]),
    ("shaker", ["shaker", "shake", "maraca", "cabasa"]),
    ("tambourine", ["tambourine", "tamb", "tambourin"]),
    ("conga", ["conga", "tumba"]),
    ("bongo", ["bongo"]),
    ("clave", ["clave", "wood", "block"]),
    ("perc", ["perc", "percussion", "zap", "blip", "tick", "click"]),
    ("fx", ["fx", "noise", "sweep", "riser", "impact", "rev"]),
]

# Similar sounds to fall back on when a kit lacks a role.
ROLE_FALLBACKS = {
    "clap": ["snare", "rim"], "snare": ["clap", "rim"], "rim": ["clave", "perc", "snare"],
    "open_hat": ["ride", "closed_hat"], "closed_hat": ["shaker", "pedal_hat", "tambourine"],
    "ride": ["open_hat", "closed_hat"], "shaker": ["closed_hat", "tambourine"],
    "perc": ["conga", "bongo", "clave", "cowbell", "tom_high", "tom_mid", "tom_low", "rim"],
    "conga": ["bongo", "perc", "tom_high", "tom_mid"],
    "bongo": ["conga", "perc", "tom_high"], "clave": ["rim", "perc"], "cowbell": ["perc", "clave", "ride"],
    "tom_low": ["tom_mid", "perc"], "tom_mid": ["tom_low", "tom_high", "perc"], "tom_high": ["tom_mid", "perc"],
    "crash": ["ride", "open_hat", "fx"], "tambourine": ["shaker", "closed_hat"], "fx": ["crash", "perc"],
}

VELOCITY = {"x": 100, "X": 124, "o": 58, "?": 96, "*": 52}
ROLE_LEVEL = {"closed_hat": 0.88, "shaker": 0.8, "pedal_hat": 0.8, "ride": 0.85, "perc": 0.9, "rim": 0.92}


class DrumError(ValueError):
    pass


def infer_roles(pads: List[Dict]) -> Dict[str, int]:
    """role -> pad note, from pad names (first match wins per role)."""
    roles: Dict[str, int] = {}
    hat_words = ("hat", "hh", "hihat", "charley")
    for pad in pads:
        name = " %s " % str(pad.get("name", "")).lower().replace("_", " ").replace("-", " ")
        # "Open Hi Hat", "OH 909", "Charley ouvert": open before any closed-hat keyword
        if (("open" in name or "ouvert" in name) and any(w in name for w in hat_words)) or " oh " in name:
            roles.setdefault("open_hat", int(pad["note"]))
            continue
        for role, words in ROLE_KEYWORDS:
            if any((" %s " % w.strip()) in name if len(w.strip()) <= 3 else w in name for w in words):
                roles.setdefault(role, int(pad["note"]))
                break
    return roles


def resolve_note(role: str, roles: Dict[str, int], use_gm: bool,
                 taken: Optional[set] = None) -> Optional[Tuple[int, str]]:
    """(note, how) for a role: the kit's pad, else a similar pad not already
    used by another layer, else (only without a kit) General MIDI."""
    if role in roles:
        return roles[role], "pad"
    taken = taken or set()
    alts = [a for a in ROLE_FALLBACKS.get(role, []) if a in roles]
    for alt in sorted(alts, key=lambda a: roles[a] in taken):
        return roles[alt], "substitute:%s" % alt + (" (shared)" if roles[alt] in taken else "")
    if use_gm and role in GM_NOTES:
        return GM_NOTES[role], "general_midi"
    return None


# --------------------------------------------------------------- rhythm

def euclid(hits: int, steps: int, rotate: int = 0, accent_first: bool = False) -> str:
    """Bjorklund's algorithm: ``hits`` onsets spread as evenly as possible
    over ``steps`` (E(3,8) = tresillo, E(5,16) = bossa-like)."""
    if steps <= 0 or hits < 0 or hits > steps:
        raise DrumError("Need 0 <= hits <= steps")
    # Bresenham form of Bjorklund: E(3,8) = x..x..x., E(5,16) = x...x..x..x..x..
    pattern = ["x" if (i * hits) % steps < hits else "." for i in range(steps)]
    r = rotate % steps
    pattern = pattern[-r:] + pattern[:-r] if r else pattern
    if accent_first and pattern[0] == "x":
        pattern[0] = "X"
    return "".join(pattern)


def clean_grid(grid: str) -> str:
    g = re.sub(r"[\s|]", "", grid)
    bad = set(g) - set("xXo.-234?*")
    if bad:
        raise DrumError("Unknown step characters %s in '%s'" % (sorted(bad), grid))
    return g.replace("-", ".")


def grid_notes(grid: str, note: int, step: float, offset: float = 0.0, level: float = 1.0) -> List[Dict]:
    """Notes for one grid string starting at ``offset`` beats."""
    out = []
    for i, ch in enumerate(clean_grid(grid)):
        if ch == ".":
            continue
        t = offset + i * step
        if ch in "234":
            n = int(ch)
            for k in range(n):
                out.append({"pitch": note, "start_time": t + k * step / n, "duration": step / n * 0.9,
                            "velocity": int(max(1, min(127, (100 - 12 * (n - 1 - k)) * level))), "mute": False})
            continue
        note_d = {"pitch": note, "start_time": t, "duration": step * 0.9,
                  "velocity": int(max(1, min(127, VELOCITY[ch] * level))), "mute": False}
        if ch == "?":
            note_d["probability"] = 0.5
        elif ch == "*":
            note_d["probability"] = 0.25
        out.append(note_d)
    return out


def apply_swing(notes: List[Dict], swing_pct: float, step: float) -> List[Dict]:
    """Delay odd steps (16ths by default): 50 % straight, 66.7 % triplet."""
    if not swing_pct or swing_pct <= 50:
        return notes
    shift = (swing_pct / 100.0 - 0.5) * 2 * step
    out = []
    for n in notes:
        pos = n["start_time"] / step
        k = int(round(pos))
        m = dict(n)
        if abs(pos - k) < 1e-6 and k % 2 == 1:
            m["start_time"] = n["start_time"] + shift
        out.append(m)
    return out


# -------------------------------------------------------------- library

def _p(label, bpm, swing, layers, notes, euclids=None):
    return {"label": label, "bpm": bpm, "swing": swing, "layers": layers, "euclid": euclids or {},
            "notes": notes}


PATTERNS: Dict[str, Dict] = {
    "techno_four": _p(
        "Techno de base (four-on-the-floor)", "125-135", 50,
        {"kick": "x...x...x...x...", "open_hat": "..x...x...x...x.", "clap": "....x.......x...",
         "closed_hat": "o.o.o.o.o.o.o.o."},
        "Le squelette : kick sur chaque temps, charley ouvert sur les contretemps. Tout le reste se joue au son "
        "(saturation du kick, decay du charley) et à l'évolution sur 16-32 mesures."),
    "techno_rolling": _p(
        "Techno roulante berlinoise", "130-138", 52,
        {"kick": "x...x...x...x...", "closed_hat": "oXoooXoooXoooXoo", "open_hat": "..x...x...x...x.",
         "rim": "......x.......x.", "perc": "...x..x....x..x."},
        "Charleys en doubles croches accentués sur les contretemps, rim syncopé, percussions qui tournent. "
        "Ajouter un rumble (kick envoyé dans une longue réverbe, filtrée et compressée en sidechain)."),
    "techno_hypnotic": _p(
        "Techno hypnotique / polyrythmique", "128-135", 50,
        {"kick": "x...x...x...x...", "open_hat": "..x...x...x...x.", "closed_hat": "o.oo.o.oo.o.oo.o"},
        "Des boucles de longueurs différentes se décalent : percussions en E(3,8) et E(5,16) contre le 4/4, "
        "ou une boucle de 3 temps contre une mesure de 4. Le groove naît du déphasage.",
        {"perc": [3, 8, 0], "rim": [5, 16, 2], "cowbell": [7, 16, 3]}),
    "minimal_techno": _p(
        "Minimal techno", "122-128", 54,
        {"kick": "x...x...x...x...", "closed_hat": "..x...x...x...x.", "rim": "...x..x....x..x.",
         "shaker": "*o*o*o*o*o*o*o*o", "perc": "......?........?"},
        "Peu d'éléments, beaucoup de micro-variations : probabilités, petits clics, swing léger, "
        "automation de decay et de filtre."),
    "dub_techno": _p(
        "Dub techno", "118-126", 52,
        {"kick": "x...x...x...x...", "closed_hat": "..x...x...x...x.", "rim": "......x.......x.",
         "shaker": "oooooooooooooooo"},
        "Batterie discrète et feutrée ; l'essentiel est dans les accords mineurs (m7/m9) envoyés dans "
        "Echo / delay à bande avec filtre et réverbe longue."),
    "hard_techno": _p(
        "Hard techno / industrial", "140-155", 50,
        {"kick": "X...X...X...X...", "clap": "....x.......x...", "closed_hat": "xoXoxoXoxoXoxoXo",
         "ride": "x.x.x.x.x.x.x.x.", "perc": "..x..x..x..x..x."},
        "Kick saturé (Roar, Saturator) très présent, claps en couches, ride en croches, percussions métalliques "
        "en 3 contre 4. Montées par roulements de clap en doubles croches."),
    "acid_techno": _p(
        "Acid techno", "130-140", 50,
        {"kick": "x...x...x...x...", "clap": "....x.......x...", "closed_hat": "o.xoo.xoo.xoo.xo",
         "cowbell": "x..x..x...x..x.."},
        "Batterie directe ; la vedette est la ligne de basse acid (303 : doubles croches, accents, glissés, "
        "résonance du filtre automatisée)."),
    "detroit_techno": _p(
        "Detroit techno", "125-132", 56,
        {"kick": "x...x...x...x...", "clap": "....x.......x...", "closed_hat": "oxoxoxoxoxoxoxox",
         "open_hat": "..x...x...x...x.", "tom_mid": ".......x.x......"},
        "Boîte 909, charleys swingués, toms syncopés ; nappes et cordes soul, accords m7/m9."),
    "house_classic": _p(
        "House classique (909)", "120-126", 56,
        {"kick": "x...x...x...x...", "clap": "....x.......x...", "open_hat": "..x...x...x...x.",
         "closed_hat": "o.o.o.o.o.o.o.o."},
        "Swing 16e autour de 56 %, piano ou orgue en stabs, basse sur les contretemps."),
    "deep_house": _p(
        "Deep house", "118-124", 58,
        {"kick": "x...x...x...x...", "rim": "....x.......x...", "shaker": "oxoooxoooxoooxoo",
         "open_hat": "..x...x...x...x.", "closed_hat": "........*......."},
        "Kick rond et doux, rim plutôt que clap, shaker très swingué, accords m9 / maj9 en Rhodes."),
    "tech_house": _p(
        "Tech house", "124-128", 54,
        {"kick": "x...x...x...x...", "clap": "....x.......x...", "closed_hat": "..x...xx..x...x.",
         "open_hat": "..x.......x.....", "perc": "...x.x.....x.x.."},
        "Groove de charley et de percussions syncopées, basse en doubles croches funky."),
    "afro_house": _p(
        "Afro house", "118-124", 56,
        {"kick": "x...x...x...x...", "shaker": "xooxooxoxooxooxo", "rim": "x..x..x...x..x..",
         "conga": "..x..x.x..x..x.x", "clap": "....x.......x..."},
        "Couches de percussions organiques (congas, shakers), tresillo 3-3-2 au rim, chants, swing marqué."),
    "uk_garage": _p(
        "UK garage / 2-step", "130-136", 66,
        {"kick": "x......x..x.....", "clap": "....x.......x...", "closed_hat": "..x...x...x...x.",
         "shaker": "oooooooooooooooo"},
        "Kick en 2-step (pas sur tous les temps), shuffle très swingué, basse wobble, vocaux découpés."),
    "breakbeat": _p(
        "Breakbeat", "125-140", 52,
        {"kick": "x.....x...x.....", "snare": "....x.......x...", "closed_hat": "x.x.x.x.x.x.x.x.",
         "open_hat": "..............x."},
        "Kick syncopé, snare 2 et 4 ; souvent un break samplé découpé dans Simpler (mode Slice)."),
    "electro": _p(
        "Electro (808)", "125-135", 50,
        {"kick": "x......x..x.....", "snare": "....x.......x...", "closed_hat": "xxxxxxxxxxxxxxxx",
         "cowbell": "...x.......x...."},
        "Boîte 808, kick syncopé, charleys mécaniques, basses et leads synthétiques, robotique."),
    "drum_and_bass": _p(
        "Drum and bass", "170-176", 50,
        {"kick": "x.........x.....", "snare": "....x.......x...", "closed_hat": "x.x.x.x.x.x.x.x.",
         "rim": ".......o......o."},
        "2-step à 174 BPM ; souvent un break (Amen, Think) découpé et resamplé par-dessus."),
    "dubstep": _p(
        "Dubstep / halftime", "140", 50,
        {"kick": "x.........x.....", "snare": "........x.......", "closed_hat": "..x...x...x...x."},
        "Demi-temps : snare sur le 3. L'énergie vient des basses (wobbles, resampling)."),
    "trap": _p(
        "Trap", "130-160 (demi-temps)", 50,
        {"kick": "x......x..x.....", "clap": "........x.......", "closed_hat": "x.x.x.x.x.x.3.x.",
         "open_hat": "..............x."},
        "Charleys avec roulements (ratchets 3 ou 4), 808 longue accordée, clap sur le 3."),
    "ebm": _p(
        "EBM / body music", "115-130", 50,
        {"kick": "x...x...x...x...", "snare": "....X.......X...", "closed_hat": "x.x.x.x.x.x.x.x."},
        "Batterie martiale ; basse séquencée en doubles croches qui pulse, voix déclamées."),
}

FILLS = {
    "roll": "Roulement de clap/snare en doubles croches sur le dernier temps (crescendo)",
    "drop": "Kick coupé sur les deux derniers temps (respiration avant la reprise)",
    "open_hat": "Charley ouvert sur chaque double croche du dernier temps (lift)",
    "crash": "Crash au premier temps de la mesure suivante",
    "ratchet": "Ratchets sur les charleys au dernier temps",
}


def list_patterns() -> List[Dict]:
    return [{"style": k, "label": v["label"], "bpm": v["bpm"], "swing": v["swing"]} for k, v in PATTERNS.items()]


def pattern_layers(style: str) -> Dict[str, str]:
    if style not in PATTERNS:
        raise DrumError("Unknown pattern style '%s'. Known: %s" % (style, ", ".join(PATTERNS)))
    p = PATTERNS[style]
    layers = dict(p["layers"])
    for role, (h, s, r) in p["euclid"].items():
        layers[role] = euclid(h, s, r)
    return layers


def describe(style: str) -> Dict:
    p = PATTERNS[style]
    return {"style": style, "label": p["label"], "bpm": p["bpm"], "swing": p["swing"],
            "layers": pattern_layers(style), "notes": p["notes"], "fills": FILLS}


# --------------------------------------------------------------- render

def _fill(bar_notes: List[Dict], kind: str, notes_for: Dict[str, Optional[int]], step: float,
          bar_start: float, bar_len: float) -> List[Dict]:
    last_beat = bar_start + bar_len - 1.0
    out = list(bar_notes)
    if kind == "drop":
        kick = notes_for.get("kick")
        out = [n for n in out if not (n["pitch"] == kick and n["start_time"] >= bar_start + bar_len - 2.0)]
    elif kind == "roll":
        snare = notes_for.get("clap") or notes_for.get("snare")
        if snare is not None:
            out = [n for n in out if not (n["pitch"] == snare and n["start_time"] >= last_beat)]
            for k in range(int(round(1.0 / step))):
                out.append({"pitch": snare, "start_time": last_beat + k * step, "duration": step * 0.9,
                            "velocity": 70 + int(50 * k * step), "mute": False})
    elif kind == "open_hat":
        oh = notes_for.get("open_hat")
        if oh is not None:
            for k in range(int(round(1.0 / step))):
                out.append({"pitch": oh, "start_time": last_beat + k * step, "duration": step * 0.9,
                            "velocity": 80 + 10 * k, "mute": False})
    elif kind == "ratchet":
        ch = notes_for.get("closed_hat")
        if ch is not None:
            out = [n for n in out if not (n["pitch"] == ch and n["start_time"] >= last_beat)]
            for k in range(int(round(1.0 / step)) * 2):
                out.append({"pitch": ch, "start_time": last_beat + k * step / 2, "duration": step / 2 * 0.9,
                            "velocity": 70 + 6 * k, "mute": False})
    elif kind == "crash":
        pass  # handled on the next bar's downbeat by the caller
    else:
        raise DrumError("Unknown fill '%s'. Known: %s" % (kind, ", ".join(FILLS)))
    return out


def render(layers: Dict[str, str], roles: Dict[str, int], bars: int = 4, steps_per_bar: int = 16,
           beats_per_bar: float = 4.0, swing_pct: float = 50.0, fill: Optional[str] = None,
           fill_every: int = 4, humanize: float = 0.0, variation: float = 0.0, seed: int = 0,
           use_gm: bool = True, levels: Optional[Dict[str, float]] = None) -> Dict:
    """Notes for ``bars`` bars, plus a report of how each role was mapped."""
    rnd = random.Random(seed)
    step = beats_per_bar / steps_per_bar
    mapping, missing = {}, []
    notes_for: Dict[str, Optional[int]] = {}
    # With a real kit, General MIDI notes would hit empty (silent) pads.
    use_gm = use_gm and not roles
    taken = {roles[r] for r in layers if r in roles}
    for role in sorted(layers, key=lambda r: r not in roles):  # direct pads first
        found = resolve_note(role, roles, use_gm, taken)
        if found is not None:
            taken.add(found[0])
        if found is None:
            missing.append(role)
            notes_for[role] = None
            continue
        notes_for[role] = found[0]
        mapping[role] = {"note": found[0], "source": found[1]}
    for extra in ("kick", "clap", "snare", "open_hat", "closed_hat", "crash"):
        if extra not in notes_for:
            f = resolve_note(extra, roles, use_gm)
            notes_for[extra] = f[0] if f else None
    out: List[Dict] = []
    for bar in range(bars):
        start = bar * beats_per_bar
        bar_notes: List[Dict] = []
        for role, grid in layers.items():
            note = notes_for.get(role)
            if note is None:
                continue
            g = clean_grid(grid)
            # A grid of any length cycles on the global step count, so a
            # 12-step loop drifts against a 16-step bar (polyrhythm) and a
            # 64-step grid spells out four different bars.
            chunk = "".join(g[(bar * steps_per_bar + i) % len(g)] for i in range(steps_per_bar))
            level = (levels or {}).get(role, ROLE_LEVEL.get(role, 1.0))
            bar_notes += grid_notes(chunk, note, step, start, level)
        if fill and fill_every and (bar + 1) % fill_every == 0:
            bar_notes = _fill(bar_notes, fill, notes_for, step, start, beats_per_bar)
        if fill == "crash" and fill_every and bar % fill_every == 0 and bar > 0 and notes_for.get("crash"):
            bar_notes.append({"pitch": notes_for["crash"], "start_time": start, "duration": 2.0,
                              "velocity": 100, "mute": False})
        out += bar_notes
    if variation > 0:
        ch = notes_for.get("closed_hat")
        if ch is not None:
            taken = {round(n["start_time"], 4) for n in out if n["pitch"] == ch}
            for k in range(int(bars * steps_per_bar)):
                t = round(k * step, 4)
                if t not in taken and rnd.random() < variation:
                    out.append({"pitch": ch, "start_time": t, "duration": step * 0.9, "velocity": 50,
                                "mute": False, "probability": 0.35})
    out = apply_swing(out, swing_pct, step)
    if humanize > 0:
        for n in out:
            n["start_time"] = max(0.0, n["start_time"] + rnd.gauss(0, humanize))
            n["velocity"] = int(max(1, min(127, n["velocity"] + rnd.randint(-6, 6))))
    # Live keeps one note per pitch and start: merge, keeping the loudest.
    merged: Dict[tuple, Dict] = {}
    for n in out:
        key = (n["pitch"], round(n["start_time"], 5))
        if key not in merged or n["velocity"] > merged[key]["velocity"]:
            merged[key] = n
    out = sorted(merged.values(), key=lambda n: (n["start_time"], n["pitch"]))
    for n in out:
        n["start_time"] = round(n["start_time"], 6)
        n["duration"] = round(n["duration"], 6)
    return {"notes": out, "mapping": mapping, "missing_roles": missing,
            "length_beats": bars * beats_per_bar}
