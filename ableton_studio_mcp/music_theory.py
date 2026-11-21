"""Music theory for MIDI creation and re-arrangement (no dependency).

* Scales and modes (church modes, harmonic/melodic minor families,
  pentatonics, blues, bebop, symmetric, world scales) with their character,
  characteristic note, typical styles and Live 12's name when Live has it.
* Chords: symbols, diatonic harmony with roman numerals and functions.
* Analysis of notes: key/mode detection (Krumhansl-Kessler profiles refined
  by scale fit), chords per segment with roman numerals, out-of-scale notes,
  range, rhythm and melodic motion.
* Transformations: chromatic/diatonic transposition, mode change, snap to
  scale, inversion, retrograde, time scaling, quantize, swing, humanize,
  accents, legato/staccato, range folding, diatonic harmonization,
  arpeggiation, strumming, chord voicings.
* Progressions from roman numerals (secondary dominants, borrowed chords)
  voiced with smooth voice leading and rendered with a style pattern.

Notes are add_notes_to_clip dictionaries: pitch, start_time, duration
(beats), velocity, mute.
"""

import math
import random
import re
from typing import Dict, List, Optional, Sequence, Tuple

SHARPS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLATS = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
_LETTER = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
FLAT_KEYS = {1, 3, 5, 8, 10}  # Db Eb F Ab Bb: spell with flats


class TheoryError(ValueError):
    """Bad musical input (unknown scale, chord, note...)."""


def parse_pitch_class(name) -> int:
    """"C", "c#", "Eb", "Bb3" or an int -> pitch class 0-11."""
    if isinstance(name, int):
        return name % 12
    m = re.match(r"^\s*([A-Ga-g])([#b♯♭]*)", str(name))
    if not m:
        raise TheoryError("Unknown note name '%s'" % name)
    pc = _LETTER[m.group(1).upper()]
    for acc in m.group(2):
        pc += 1 if acc in "#♯" else -1
    return pc % 12


def parse_note(name) -> int:
    """"C4" (middle C = 60, Live's C3), "Eb2", or an int MIDI pitch."""
    if isinstance(name, int):
        return name
    m = re.match(r"^\s*([A-Ga-g][#b♯♭]*)(-?\d+)\s*$", str(name))
    if not m:
        raise TheoryError("Note needs an octave, e.g. C4 or Eb2: '%s'" % name)
    return parse_pitch_class(m.group(1)) + 12 * (int(m.group(2)) + 1)


def pc_name(pc: int, root: Optional[int] = None) -> str:
    use_flats = root is not None and root % 12 in FLAT_KEYS
    return (FLATS if use_flats else SHARPS)[pc % 12]


def note_name(pitch: int, root: Optional[int] = None) -> str:
    """MIDI pitch -> "C4" (scientific pitch; Live shows the same note as C3)."""
    return "%s%d" % (pc_name(pitch, root), pitch // 12 - 1)


# ------------------------------------------------------------------ scales

def _s(intervals, family, character, styles, characteristic=None, aliases=(), live=None):
    return {"intervals": tuple(intervals), "family": family, "character": character,
            "styles": list(styles), "characteristic": characteristic,
            "aliases": list(aliases), "live_name": live}


SCALES: Dict[str, Dict] = {
    # Major scale modes
    "major": _s((0, 2, 4, 5, 7, 9, 11), "majeur (modes de la gamme majeure)",
                "lumineux, stable, résolu", ["pop", "classique", "folk", "country", "house"],
                None, ["ionian", "ionien", "majeur"], "Major"),
    "dorian": _s((0, 2, 3, 5, 7, 9, 10), "majeur (modes de la gamme majeure)",
                 "mineur mais chaleureux, groovy, la 6te majeure éclaire", ["funk", "jazz modal", "soul",
                 "house", "rock psyché", "folk celtique", "lofi"], 9, ["dorien"], "Dorian"),
    "phrygian": _s((0, 1, 3, 5, 7, 8, 10), "majeur (modes de la gamme majeure)",
                   "sombre, tendu, hispanisant par la 2de mineure", ["metal", "flamenco", "techno sombre",
                   "musique de film"], 1, ["phrygien"], "Phrygian"),
    "lydian": _s((0, 2, 4, 6, 7, 9, 11), "majeur (modes de la gamme majeure)",
                 "rêveur, flottant, émerveillé (4te augmentée)", ["musique de film", "jazz", "ambient",
                 "pop onirique"], 6, ["lydien"], "Lydian"),
    "mixolydian": _s((0, 2, 4, 5, 7, 9, 10), "majeur (modes de la gamme majeure)",
                     "majeur décontracté, bluesy, rock (7e mineure)", ["rock", "blues", "funk", "folk",
                     "afrobeat", "jam"], 10, ["mixolydien"], "Mixolydian"),
    "minor": _s((0, 2, 3, 5, 7, 8, 10), "majeur (modes de la gamme majeure)",
                "triste, introspectif, épique", ["pop", "rock", "trap", "rnb", "musique de film",
                "drum and bass"], 8, ["aeolian", "éolien", "natural minor", "mineur naturel", "mineur"],
                "Minor"),
    "locrian": _s((0, 1, 3, 5, 6, 8, 10), "majeur (modes de la gamme majeure)",
                  "instable, inquiétant (quinte diminuée)", ["metal", "jazz", "musique expérimentale"], 6,
                  ["locrien"], "Locrian"),
    # Harmonic minor family
    "harmonic_minor": _s((0, 2, 3, 5, 7, 8, 11), "mineur harmonique",
                         "dramatique, classique, orientalisant (7e majeure, seconde augmentée)",
                         ["baroque", "classique", "metal néoclassique", "tango", "musique de film"], 11,
                         ["mineur harmonique"], "Harmonic Minor"),
    "locrian_nat6": _s((0, 1, 3, 5, 6, 9, 10), "mineur harmonique", "locrien adouci, mystérieux",
                       ["jazz", "metal"], 9),
    "ionian_sharp5": _s((0, 2, 4, 5, 8, 9, 11), "mineur harmonique", "majeur augmenté, irréel",
                        ["jazz", "musique de film"], 8),
    "dorian_sharp4": _s((0, 2, 3, 6, 7, 9, 10), "mineur harmonique",
                        "dorien oriental (ukrainien / roumain), klezmer", ["klezmer", "musique d'Europe de l'Est",
                        "jazz"], 6, ["ukrainian dorian", "romanian minor", "dorien #4"], "Dorian #4"),
    "phrygian_dominant": _s((0, 1, 4, 5, 7, 8, 10), "mineur harmonique",
                            "espagnol, arabisant, flamenco (2de mineure + 3ce majeure)",
                            ["flamenco", "musique arabe", "metal", "klezmer", "musique de film"], 4,
                            ["hijaz", "spanish phrygian", "freygish", "phrygien dominant"],
                            "Phrygian Dominant"),
    "lydian_sharp2": _s((0, 3, 4, 6, 7, 9, 11), "mineur harmonique", "lumineux et exotique",
                        ["jazz", "musique de film"], 3),
    "ultralocrian": _s((0, 1, 3, 4, 6, 8, 9), "mineur harmonique", "très sombre, diminué",
                       ["metal", "jazz"], 9, ["superlocrian bb7"]),
    # Melodic minor family
    "melodic_minor": _s((0, 2, 3, 5, 7, 9, 11), "mineur mélodique",
                        "mineur sophistiqué, jazz (6te et 7e majeures)", ["jazz", "neo-soul", "musique de film"],
                        11, ["jazz minor", "mineur mélodique"], "Melodic Minor"),
    "dorian_b2": _s((0, 1, 3, 5, 7, 9, 10), "mineur mélodique", "phrygien éclairci", ["jazz"], 1,
                    ["phrygian nat6"]),
    "lydian_augmented": _s((0, 2, 4, 6, 8, 9, 11), "mineur mélodique", "très ouvert, en suspens",
                           ["jazz", "musique de film"], 8, [], "Lydian Augmented"),
    "lydian_dominant": _s((0, 2, 4, 6, 7, 9, 10), "mineur mélodique",
                          "lydien bluesy, malicieux (#4 + b7)", ["jazz", "fusion", "musique de film",
                          "thèmes de dessin animé"], 6, ["overtone", "acoustic", "lydien dominant"],
                          "Lydian Dominant"),
    "mixolydian_b6": _s((0, 2, 4, 5, 7, 8, 10), "mineur mélodique", "majeur doux-amer", ["pop", "musique de film"],
                        8, ["hindu", "aeolian dominant"]),
    "locrian_nat2": _s((0, 2, 3, 5, 6, 8, 10), "mineur mélodique", "demi-diminué jazz", ["jazz"], 2,
                       ["half-diminished"]),
    "altered": _s((0, 1, 3, 4, 6, 8, 10), "mineur mélodique",
                  "tension maximale sur un accord de dominante", ["jazz", "bebop"], 4,
                  ["super locrian", "super locrien", "altérée"], "Super Locrian"),
    # Other heptatonic
    "harmonic_major": _s((0, 2, 4, 5, 7, 8, 11), "majeur harmonique", "majeur avec une ombre (6te mineure)",
                         ["musique de film", "romantique"], 8, [], "Harmonic Major"),
    "double_harmonic": _s((0, 1, 4, 5, 7, 8, 11), "double harmonique",
                          "oriental, byzantin, très coloré", ["musique arabe", "musique indienne", "musique de film"],
                          1, ["byzantine", "arabic", "bhairav"], "Bhairav"),
    "hungarian_minor": _s((0, 2, 3, 6, 7, 8, 11), "double harmonique", "tzigane, dramatique",
                          ["musique tzigane", "metal néoclassique", "musique de film"], 6,
                          ["gypsy minor", "mineur hongrois"], "Hungarian Minor"),
    "neapolitan_minor": _s((0, 1, 3, 5, 7, 8, 11), "napolitain", "mineur harmonique assombri",
                           ["classique", "musique de film"], 1),
    "neapolitan_major": _s((0, 1, 3, 5, 7, 9, 11), "napolitain", "étrange et lumineux", ["jazz"], 1),
    "enigmatic": _s((0, 1, 4, 6, 8, 10, 11), "autre", "énigmatique (Verdi)", ["musique expérimentale"], 1),
    "persian": _s((0, 1, 4, 5, 6, 8, 11), "autre", "persan, très tendu", ["musique de film"], 6),
    # Pentatonic and blues
    "major_pentatonic": _s((0, 2, 4, 7, 9), "pentatonique",
                           "simple, ouvert, impossible de « se tromper »", ["pop", "country", "folk", "rock",
                           "musique asiatique", "afrobeat"], None, ["pentatonique majeure"], "Major Pentatonic"),
    "minor_pentatonic": _s((0, 3, 5, 7, 10), "pentatonique", "bluesy, rock, soul",
                           ["blues", "rock", "rnb", "hip-hop", "trap", "funk"], None, ["pentatonique mineure"],
                           "Minor Pentatonic"),
    "egyptian": _s((0, 2, 5, 7, 10), "pentatonique", "suspendu, ancien", ["folk", "musique de film"], None,
                   ["suspended pentatonic"]),
    "blues": _s((0, 3, 5, 6, 7, 10), "blues", "blues avec la blue note (quinte diminuée)",
                ["blues", "rock", "jazz", "funk", "hip-hop"], 6, ["minor blues", "blues mineur"], "Minor Blues"),
    "major_blues": _s((0, 2, 3, 4, 7, 9), "blues", "blues majeur, country/gospel", ["blues", "country", "gospel"],
                      3),
    # Bebop
    "bebop_dominant": _s((0, 2, 4, 5, 7, 9, 10, 11), "bebop", "mixolydien + 7e majeure de passage",
                         ["jazz", "bebop"], 11),
    "bebop_major": _s((0, 2, 4, 5, 7, 8, 9, 11), "bebop", "majeur + 6te mineure de passage", ["jazz"], 8),
    "bebop_dorian": _s((0, 2, 3, 4, 5, 7, 9, 10), "bebop", "dorien + 3ce majeure de passage", ["jazz"], 4),
    # Symmetric
    "whole_tone": _s((0, 2, 4, 6, 8, 10), "symétrique", "flou, onirique (Debussy)",
                     ["impressionnisme", "musique de film", "jazz"], None, ["par tons"], "Whole Tone"),
    "diminished_hw": _s((0, 1, 3, 4, 6, 7, 9, 10), "symétrique", "dominante altérée symétrique",
                        ["jazz", "musique de film", "metal"], None, ["half-whole", "octatonic"],
                        "Half-whole Dim."),
    "diminished_wh": _s((0, 2, 3, 5, 6, 8, 9, 11), "symétrique", "diminué, suspense",
                        ["jazz", "musique de film", "thriller"], None, ["whole-half"], "Whole-half Dim."),
    "augmented": _s((0, 3, 4, 7, 8, 11), "symétrique", "hexatonique augmentée, mystérieux",
                    ["jazz", "musique de film"], None),
    "prometheus": _s((0, 2, 4, 6, 9, 10), "autre", "mystique (Scriabine)", ["musique de film"], 6),
    "spanish_8_tone": _s((0, 1, 3, 4, 5, 6, 8, 10), "autre", "flamenco, espagnol", ["flamenco"], 4,
                         [], "8-Tone Spanish"),
    # Japanese / Indonesian
    "hirajoshi": _s((0, 2, 3, 7, 8), "pentatonique japonaise", "japonais, mélancolique (koto)",
                    ["musique japonaise", "musique de film"], 8, [], "Hirajoshi"),
    "in_sen": _s((0, 1, 5, 7, 10), "pentatonique japonaise", "japonais, austère (shakuhachi)",
                 ["musique japonaise", "ambient"], 1, ["insen"], "In-Sen"),
    "iwato": _s((0, 1, 5, 6, 10), "pentatonique japonaise", "japonais très sombre",
                ["musique japonaise", "metal"], 6, [], "Iwato"),
    "kumoi": _s((0, 2, 3, 7, 9), "pentatonique japonaise", "japonais doux", ["musique japonaise"], 3,
                [], "Kumoi"),
    "yo": _s((0, 2, 5, 7, 9), "pentatonique japonaise", "japonais folklorique, lumineux",
             ["musique japonaise", "folk"], None),
    "pelog": _s((0, 1, 3, 7, 8), "gamelan", "gamelan balinais (approximation tempérée)",
                ["gamelan", "ambient", "musique de film"], 1, ["pelog selisir"], "Pelog Selisir"),
    "chromatic": _s(tuple(range(12)), "chromatique", "toutes les notes", ["atonal", "musique de film"], None,
                    ["chromatique"], "Chromatic"),
}

_ALIASES = {}
for _k, _v in SCALES.items():
    for _name in [_k, _k.replace("_", " "), _v["live_name"] or ""] + _v["aliases"]:
        if _name:
            _ALIASES[_name.lower().replace("-", " ").replace("_", " ")] = _k


def scale_key(name: str) -> str:
    key = str(name).lower().replace("-", " ").replace("_", " ").strip()
    if key in _ALIASES:
        return _ALIASES[key]
    raise TheoryError("Unknown scale '%s'. Known: %s" % (name, ", ".join(sorted(SCALES))))


def scale_pcs(root, scale: str) -> List[int]:
    r = parse_pitch_class(root)
    return [(r + i) % 12 for i in SCALES[scale_key(scale)]["intervals"]]


# ------------------------------------------------------------------ chords

CHORD_TYPES: Dict[str, Tuple[int, ...]] = {
    "": (0, 4, 7), "m": (0, 3, 7), "dim": (0, 3, 6), "aug": (0, 4, 8),
    "sus2": (0, 2, 7), "sus4": (0, 5, 7), "5": (0, 7),
    "6": (0, 4, 7, 9), "m6": (0, 3, 7, 9), "7": (0, 4, 7, 10), "maj7": (0, 4, 7, 11),
    "m7": (0, 3, 7, 10), "mMaj7": (0, 3, 7, 11), "m7b5": (0, 3, 6, 10), "dim7": (0, 3, 6, 9),
    "7sus4": (0, 5, 7, 10), "aug7": (0, 4, 8, 10), "add9": (0, 4, 7, 14), "madd9": (0, 3, 7, 14),
    "9": (0, 4, 7, 10, 14), "maj9": (0, 4, 7, 11, 14), "m9": (0, 3, 7, 10, 14),
    "7b9": (0, 4, 7, 10, 13), "7#9": (0, 4, 7, 10, 15), "7#11": (0, 4, 7, 10, 18),
    "11": (0, 4, 7, 10, 14, 17), "m11": (0, 3, 7, 10, 14, 17), "13": (0, 4, 7, 10, 14, 21),
    "maj13": (0, 4, 7, 11, 14, 21), "7alt": (0, 4, 10, 13, 15, 20), "6/9": (0, 4, 7, 9, 14),
}
_CHORD_ALIASES = {"maj": "", "M": "", "min": "m", "-": "m", "°": "dim", "o": "dim", "+": "aug",
                  "M7": "maj7", "Δ": "maj7", "Δ7": "maj7", "-7": "m7", "min7": "m7", "ø": "m7b5",
                  "ø7": "m7b5", "°7": "dim7", "o7": "dim7", "mM7": "mMaj7", "sus": "sus4",
                  "m(maj7)": "mMaj7", "69": "6/9"}

# Chord vocabularies for recognition. "basic" (triads and sevenths) reads
# classical, pop and contrapuntal music; "jazz" adds 6ths, 9ths and
# suspended sevenths for jazz, neo-soul, house chords.
VOCABULARIES = {
    "basic": ["", "m", "7", "maj7", "m7", "dim", "m7b5", "dim7", "aug", "sus4"],
    "jazz": ["", "m", "7", "maj7", "m7", "dim", "m7b5", "dim7", "aug", "sus4", "sus2",
             "6", "m6", "mMaj7", "7sus4", "add9", "9", "m9", "maj9"],
}
_RECOGNIZE = VOCABULARIES["jazz"]


def parse_chord(symbol: str) -> Tuple[int, str, Tuple[int, ...], Optional[int]]:
    """"Cm7", "F#ø", "Bbmaj7/D" -> (root pc, quality, intervals, bass pc)."""
    m = re.match(r"^\s*([A-Ga-g][#b♯♭]?)(.*?)(?:/([A-Ga-g][#b♯♭]?))?\s*$", symbol)
    if not m:
        raise TheoryError("Unknown chord '%s'" % symbol)
    root = parse_pitch_class(m.group(1))
    q = m.group(2).strip()
    q = _CHORD_ALIASES.get(q, q)
    if q not in CHORD_TYPES:
        raise TheoryError("Unknown chord quality '%s' in '%s'. Known: %s"
                          % (m.group(2), symbol, ", ".join(k or "(maj)" for k in CHORD_TYPES)))
    bass = parse_pitch_class(m.group(3)) if m.group(3) else None
    return root, q, CHORD_TYPES[q], bass


def chord_symbol(root: int, quality: str, key_root: Optional[int] = None, bass: Optional[int] = None) -> str:
    s = pc_name(root, key_root) + quality
    if bass is not None and bass != root:
        s += "/" + pc_name(bass, key_root)
    return s


_ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII"]
_MAJOR = (0, 2, 4, 5, 7, 9, 11)


def _quality_from_intervals(ivs: Sequence[int]) -> str:
    s = tuple(sorted({i % 12 for i in ivs}))
    for q in ["", "m", "dim", "aug", "7", "maj7", "m7", "m7b5", "dim7", "mMaj7", "aug7", "sus4", "sus2"]:
        if tuple(sorted({i % 12 for i in CHORD_TYPES[q]})) == s:
            return q
    return "?"


def roman_numeral(chord_root: int, quality: str, key_root: int) -> str:
    """Roman numeral relative to the major scale of key_root (bIII, iv, V7...)."""
    iv = (chord_root - key_root) % 12
    if iv in _MAJOR:
        degree, acc = _MAJOR.index(iv), ""
    elif (iv + 1) % 12 in _MAJOR:
        degree, acc = _MAJOR.index((iv + 1) % 12), "b"
    else:
        degree, acc = _MAJOR.index((iv - 1) % 12), "#"
    numeral = _ROMAN[degree]
    minor_like = quality.startswith("m") and not quality.startswith("maj") or quality in ("dim", "dim7", "m7b5")
    if minor_like:
        numeral = numeral.lower()
    suffix = {"dim": "°", "dim7": "°7", "m7b5": "ø7", "aug": "+", "m": "", "": "", "m7": "7",
              "mMaj7": "(maj7)"}.get(quality, quality)
    return acc + numeral + suffix


_FUNCTIONS = {0: "tonique", 1: "sous-dominante", 2: "tonique", 3: "sous-dominante",
              4: "dominante", 5: "tonique", 6: "dominante"}


def diatonic_chords(root, scale: str, sevenths: bool = True) -> List[Dict]:
    """Chords built in thirds on each degree of a 7-note scale."""
    key = scale_key(scale)
    ivs = SCALES[key]["intervals"]
    if len(ivs) != 7:
        return []
    r = parse_pitch_class(root)
    out = []
    for d in range(7):
        stack = [ivs[(d + k) % 7] + 12 * ((d + k) // 7) for k in ((0, 2, 4, 6) if sevenths else (0, 2, 4))]
        rel = [x - stack[0] for x in stack]
        triad_q = _quality_from_intervals(rel[:3])
        q = _quality_from_intervals(rel) if sevenths else triad_q
        croot = (r + ivs[d]) % 12
        out.append({
            "degree": d + 1,
            "roman": roman_numeral(croot, q, r),
            "symbol": chord_symbol(croot, q, r),
            "triad": chord_symbol(croot, triad_q, r),
            "notes": [pc_name((r + x) % 12, r) for x in stack],
            "function": _FUNCTIONS[d] if key in ("major", "minor", "harmonic_minor", "melodic_minor",
                                                 "harmonic_major") else None,
        })
    return out


def scale_info(root, scale: str) -> Dict:
    key = scale_key(scale)
    data = SCALES[key]
    r = parse_pitch_class(root)
    ivs = data["intervals"]
    degree_names = []
    for i in ivs:
        base = {0: "1", 1: "b2", 2: "2", 3: "b3", 4: "3", 5: "4", 6: "#4/b5", 7: "5", 8: "b6", 9: "6",
                10: "b7", 11: "7"}[i]
        degree_names.append(base)
    char = data["characteristic"]
    parent = None
    if len(ivs) == 7:
        # same notes, other modes (relative modes)
        parent = []
        for k, v in SCALES.items():
            if len(v["intervals"]) != 7:
                continue
            for d in range(7):
                rot = sorted(((ivs[(d + j) % 7] - ivs[d]) % 12) for j in range(7))
                if tuple(rot) == v["intervals"] and k != key:
                    parent.append("%s %s" % (pc_name((r + ivs[d]) % 12, r), k))
    return {
        "root": pc_name(r, r), "scale": key, "family": data["family"],
        "notes": [pc_name((r + i) % 12, r) for i in ivs],
        "intervals": list(ivs), "degrees": degree_names,
        "characteristic_note": (pc_name((r + char) % 12, r) + " (" + degree_names[ivs.index(char)] + ")")
        if char is not None and char in ivs else None,
        "character": data["character"], "styles": data["styles"],
        "live_scale_name": data["live_name"],
        "diatonic_chords": diatonic_chords(r, key),
        "same_notes_as": parent,
    }


def search_scales(query: Optional[str] = None) -> List[Dict]:
    out = []
    q = (query or "").lower()
    for k, v in SCALES.items():
        text = " ".join([k, v["family"], v["character"], " ".join(v["styles"]), " ".join(v["aliases"])]).lower()
        if not q or q in text:
            out.append({"scale": k, "family": v["family"], "character": v["character"],
                        "styles": v["styles"], "notes_from_C": [SHARPS[i] for i in v["intervals"]],
                        "live_scale_name": v["live_name"]})
    return out


# ---------------------------------------------------------------- analysis

# Krumhansl-Kessler key profiles.
_KK_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_KK_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def _corr(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def pitch_class_weights(notes: List[Dict]) -> List[float]:
    w = [0.0] * 12
    for n in notes:
        if not n.get("mute"):
            # Cap long notes: a held final chord (e.g. a Picardy third) or a
            # pedal must not outweigh the whole piece.
            w[n["pitch"] % 12] += min(max(n["duration"], 0.0625), 1.0) * (0.5 + n.get("velocity", 100) / 254.0)
    return w


_DETECT_SCALES = ["major", "minor", "dorian", "phrygian", "lydian", "mixolydian", "locrian",
                  "harmonic_minor", "melodic_minor", "phrygian_dominant", "major_pentatonic",
                  "minor_pentatonic", "blues", "harmonic_major", "double_harmonic", "hungarian_minor",
                  "whole_tone", "lydian_dominant", "dorian_sharp4"]


def detect_key(notes: List[Dict], top: int = 5) -> Dict:
    """Key and mode candidates. Major/minor from Krumhansl-Kessler
    correlation; modes and other scales by how much of the music they cover,
    the tonic's weight (duration, bass, final note) and scale economy."""
    w = pitch_class_weights(notes)
    total = sum(w) or 1.0
    kk = []
    for r in range(12):
        rot = w[r:] + w[:r]
        kk.append((_corr(rot, _KK_MAJOR), r, "major"))
        kk.append((_corr(rot, _KK_MINOR), r, "minor"))
    kk.sort(reverse=True)
    played = [n for n in notes if not n.get("mute")]
    last = max(played, key=lambda n: n["start_time"])["pitch"] % 12 if played else None
    bass_w = [0.0] * 12
    if played:
        starts = {}
        for n in played:
            starts.setdefault(round(n["start_time"], 3), []).append(n)
        for group in starts.values():
            lo = min(group, key=lambda n: n["pitch"])
            bass_w[lo["pitch"] % 12] += lo["duration"]
    bass_total = sum(bass_w) or 1.0
    kk_score = {(r, m): c for c, r, m in kk}
    cands = []
    for name in _DETECT_SCALES:
        ivs = SCALES[name]["intervals"]
        for r in range(12):
            pcs = {(r + i) % 12 for i in ivs}
            cover = sum(w[p] for p in pcs) / total
            tonic = w[r] / total + 0.5 * bass_w[r] / bass_total + (0.08 if last == r else 0.0)
            economy = (7 - len(ivs)) * 0.01 if len(ivs) < 7 else -(len(ivs) - 7) * 0.03
            base = kk_score.get((r, "major" if 4 in ivs else "minor"), 0.0)
            score = 2.0 * cover + 0.9 * tonic + 0.35 * base + economy
            if name not in ("major", "minor"):
                score -= 0.02  # prefer the plain key on ties
            cands.append((score, r, name, cover))
    cands.sort(reverse=True)
    seen, out = set(), []
    for score, r, name, cover in cands:
        if (r, name) in seen:
            continue
        seen.add((r, name))
        outside = [pc_name(p, r) for p in range(12)
                   if w[p] / total > 0.01 and p not in {(r + i) % 12 for i in SCALES[name]["intervals"]}]
        out.append({"root": pc_name(r, r), "scale": name, "score": round(score, 3),
                    "coverage_pct": round(100 * cover, 1), "outside_notes": outside})
        if len(out) >= top:
            break
    best_kk = kk[0]
    return {"best": out[0] if out else None, "candidates": out,
            "major_minor": "%s %s (r=%.2f)" % (pc_name(best_kk[1], best_kk[1]), best_kk[2], best_kk[0]),
            "pitch_class_weight_pct": {SHARPS[i]: round(100 * w[i] / total, 1) for i in range(12) if w[i]}}


def detect_chord(weights: List[float], bass: Optional[int] = None,
                 vocabulary: str = "basic") -> Optional[Dict]:
    """Best chord for a pitch-class weight vector (template matching)."""
    total = sum(weights)
    if total <= 0:
        return None
    if vocabulary not in VOCABULARIES:
        raise TheoryError("vocabulary must be one of: %s" % ", ".join(VOCABULARIES))
    best = None
    for q in VOCABULARIES[vocabulary]:
        tones = {i % 12 for i in CHORD_TYPES[q]}
        for r in range(12):
            pcs = {(r + t) % 12 for t in tones}
            inside = sum(weights[p] for p in pcs)
            outside = total - inside
            missing = sum(1 for p in pcs if weights[p] < 0.06 * total)
            # Each extra chord tone must earn its place: extensions (6, 7, 9)
            # otherwise soak up passing notes in counterpoint.
            score = (inside - 1.2 * outside - 0.35 * missing * total / len(pcs)
                     - 0.06 * max(len(pcs) - 3, 0) * total)
            if bass is not None and bass == r:
                score += 0.15 * total
            if best is None or score > best[0]:
                best = (score, r, q)
    score, r, q = best
    return {"root": r, "quality": q, "confidence": round(max(score / total, 0.0), 2)}


def _segments(notes, seg_len, end):
    k = 0
    while k * seg_len < end - 1e-9:
        a, b = k * seg_len, (k + 1) * seg_len
        w = [0.0] * 12
        bass_w = {}
        for n in notes:
            s, e = n["start_time"], n["start_time"] + n["duration"]
            ov = min(e, b) - max(s, a)
            if ov > 0 and not n.get("mute"):
                # Short notes off the beat are mostly passing tones.
                on_beat = abs(s - round(s)) < 1e-3
                weight = ov * (1.0 if n["duration"] >= 0.5 or on_beat else 0.4)
                w[n["pitch"] % 12] += weight
                bass_w[n["pitch"]] = bass_w.get(n["pitch"], 0.0) + weight
        bass = None
        if bass_w:
            # the lowest note that is really there (not a quick passing note)
            solid = [p for p, x in bass_w.items() if x >= 0.2 * seg_len]
            bass = min(solid or bass_w) % 12
        yield a, w, bass
        k += 1


_TONAL = ("major", "minor", "harmonic_minor", "melodic_minor", "harmonic_major")


def _rerank_with_harmony(key: Dict, notes: List[Dict], segment_beats: float, end: float) -> None:
    """What an ear does with relative modes: a dominant seventh on degree 5
    points to its tonic, and the first/last chords tend to be the tonic."""
    found = [detect_chord(w, b) for _, w, b in _segments(notes, segment_beats, end)]
    found = [c for c in found if c]
    if not found:
        return
    dominant = ("7", "9", "7b9", "13")
    dom_roots = {c["root"] for c in found if c["quality"] in dominant}
    first, last = found[0]["root"], found[-1]["root"]
    # Ending on a dominant seventh is a half cadence, not a rest on the tonic.
    last_is_rest = found[-1]["quality"] not in dominant
    for c in key["candidates"]:
        r = parse_pitch_class(c["root"])
        bonus = 0.0
        if (r + 7) % 12 in dom_roots and c["scale"] in _TONAL:
            bonus += 0.3
        if last == r and last_is_rest:
            bonus += 0.1
        if first == r:
            bonus += 0.15
        c["score"] = round(c["score"] + bonus, 3)
    key["candidates"].sort(key=lambda c: -c["score"])
    key["best"] = key["candidates"][0]


def analyze_notes(notes: List[Dict], segment_beats: float = 2.0, key_root=None, key_scale=None,
                  vocabulary: str = "basic") -> Dict:
    """Key, chords per segment (with roman numerals), range, rhythm, motion."""
    played = [n for n in notes if not n.get("mute")]
    if not played:
        return {"notes": 0}
    end = max(n["start_time"] + n["duration"] for n in played)
    key = detect_key(played, top=8)
    if key_root is not None and key_scale is not None:
        r, scale = parse_pitch_class(key_root), scale_key(key_scale)
    else:
        _rerank_with_harmony(key, played, segment_beats, end)
        r, scale = parse_pitch_class(key["best"]["root"]), key["best"]["scale"]
    pcs = set(scale_pcs(r, scale))
    chords = []
    for start, w, bass in _segments(played, segment_beats, end):
        c = detect_chord(w, bass, vocabulary)
        if not c:
            chords.append({"start": start, "chord": None})
            continue
        sym = chord_symbol(c["root"], c["quality"], r, bass)
        entry = {"start": start, "chord": sym, "roman": roman_numeral(c["root"], c["quality"], r),
                 "confidence": c["confidence"]}
        if chords and chords[-1].get("chord") == sym:
            chords[-1]["length"] = chords[-1].get("length", segment_beats) + segment_beats
        else:
            entry["length"] = segment_beats
            chords.append(entry)
    pitches = sorted(n["pitch"] for n in played)
    durs = [n["duration"] for n in played]
    onsets = sorted({round(n["start_time"], 4) for n in played})
    offbeat = sum(1 for o in onsets if abs(o * 2 - round(o * 2)) > 1e-3 or (round(o * 2) % 2 == 1))
    # melodic motion of the top line
    by_onset = {}
    for n in played:
        by_onset.setdefault(round(n["start_time"], 4), []).append(n["pitch"])
    top = [max(v) for _, v in sorted(by_onset.items())]
    steps = [b - a for a, b in zip(top, top[1:])]
    out_of_scale = sorted({note_name(n["pitch"], r) for n in played if n["pitch"] % 12 not in pcs})
    poly = sum(len(v) for v in by_onset.values()) / len(by_onset)
    return {
        "notes": len(played),
        "length_beats": round(end, 3),
        "key": key,
        "analysed_in": "%s %s" % (pc_name(r, r), scale),
        "chords": chords,
        "out_of_scale_notes": out_of_scale,
        "range": {"lowest": note_name(pitches[0], r), "highest": note_name(pitches[-1], r),
                  "span_semitones": pitches[-1] - pitches[0]},
        "rhythm": {
            "notes_per_beat": round(len(played) / max(end, 1e-9), 2),
            "most_common_duration": max(set(round(d, 3) for d in durs),
                                        key=lambda d: sum(1 for x in durs if round(x, 3) == d)),
            "offbeat_onsets_pct": round(100 * offbeat / len(onsets), 1),
            "average_simultaneous_notes": round(poly, 2),
        },
        "top_line_motion": {
            "steps_pct": round(100 * sum(1 for s in steps if 1 <= abs(s) <= 2) / len(steps), 1) if steps else None,
            "leaps_pct": round(100 * sum(1 for s in steps if abs(s) >= 5) / len(steps), 1) if steps else None,
            "repeats_pct": round(100 * sum(1 for s in steps if s == 0) / len(steps), 1) if steps else None,
            "direction": "montante" if top and top[-1] > top[0] else "descendante" if top and top[-1] < top[0]
            else "stable",
        },
    }


# ---------------------------------------------------------- transformations

def _clean(n: Dict) -> Dict:
    return {"pitch": int(n["pitch"]), "start_time": round(float(n["start_time"]), 6),
            "duration": round(max(float(n["duration"]), 1e-3), 6),
            "velocity": int(max(1, min(127, round(n.get("velocity", 100))))), "mute": bool(n.get("mute", False))}


def _degree_of(pitch: int, root: int, ivs: Sequence[int]) -> Tuple[int, int, int]:
    """(scale step index counting octaves, chromatic offset, octave) of a pitch."""
    rel = pitch - root
    octave, pc = rel // 12, rel % 12
    below = max(i for i in range(len(ivs)) if ivs[i] <= pc)
    return octave * len(ivs) + below, pc - ivs[below], octave


def _pitch_of(step: int, offset: int, root: int, ivs: Sequence[int]) -> int:
    octave, idx = divmod(step, len(ivs))
    return root + 12 * octave + ivs[idx] + offset


def transpose(notes, semitones: int):
    return [dict(_clean(n), pitch=n["pitch"] + semitones) for n in notes]


def transpose_diatonic(notes, steps: int, root, scale: str):
    r, ivs = parse_pitch_class(root), SCALES[scale_key(scale)]["intervals"]
    out = []
    for n in notes:
        st, off, _ = _degree_of(n["pitch"], r, ivs)
        out.append(dict(_clean(n), pitch=_pitch_of(st + steps, off, r, ivs)))
    return out


def change_mode(notes, root, from_scale: str, to_scale: str, to_root=None):
    """Map each scale degree of from_scale to the same degree of to_scale
    (C major -> C dorian lowers E and B; a 5-note to 7-note change maps by
    position). Out-of-scale notes keep their offset from the degree below."""
    r = parse_pitch_class(root)
    r2 = parse_pitch_class(to_root) if to_root is not None else r
    a, b = SCALES[scale_key(from_scale)]["intervals"], SCALES[scale_key(to_scale)]["intervals"]
    out = []
    for n in notes:
        st, off, octave = _degree_of(n["pitch"], r, a)
        idx = st % len(a)
        j = int(round(idx * len(b) / len(a))) % len(b)
        new = r + 12 * octave + (r2 - r) + b[j] + off
        out.append(dict(_clean(n), pitch=new))
    return out


def snap_to_scale(notes, root, scale: str, direction: str = "nearest"):
    pcs = set(scale_pcs(root, scale))
    out = []
    for n in notes:
        p = n["pitch"]
        if p % 12 in pcs:
            out.append(_clean(n))
            continue
        up = next(d for d in range(1, 12) if (p + d) % 12 in pcs)
        down = next(d for d in range(1, 12) if (p - d) % 12 in pcs)
        if direction == "up" or (direction == "nearest" and up < down):
            p += up
        else:
            p -= down
        out.append(dict(_clean(n), pitch=p))
    return out


def invert(notes, axis, root=None, scale: Optional[str] = None):
    """Mirror pitches around an axis note (chromatic, or by scale steps)."""
    ax = parse_note(axis) if not isinstance(axis, int) else axis
    if scale:
        r, ivs = parse_pitch_class(root), SCALES[scale_key(scale)]["intervals"]
        a_st, _, _ = _degree_of(ax, r, ivs)
        out = []
        for n in notes:
            st, off, _ = _degree_of(n["pitch"], r, ivs)
            out.append(dict(_clean(n), pitch=_pitch_of(2 * a_st - st, -off, r, ivs)))
        return out
    return [dict(_clean(n), pitch=2 * ax - n["pitch"]) for n in notes]


def retrograde(notes, length: Optional[float] = None):
    end = length if length is not None else max(n["start_time"] + n["duration"] for n in notes)
    return sorted((dict(_clean(n), start_time=end - n["start_time"] - n["duration"]) for n in notes),
                  key=lambda n: n["start_time"])


def time_scale(notes, factor: float):
    return [dict(_clean(n), start_time=n["start_time"] * factor, duration=n["duration"] * factor) for n in notes]


def quantize(notes, grid: float = 0.25, strength: float = 1.0, durations: bool = False):
    out = []
    for n in notes:
        target = round(n["start_time"] / grid) * grid
        c = dict(_clean(n), start_time=n["start_time"] + (target - n["start_time"]) * strength)
        if durations:
            c["duration"] = max(grid, round(n["duration"] / grid) * grid)
        out.append(c)
    return out


def swing(notes, amount_pct: float = 60.0, grid: float = 0.5):
    """Delay every second grid position: 50 % = straight, 66.7 % = triplet
    swing, 75 % = dotted. ``grid`` is the swung subdivision (0.5 = 8ths)."""
    shift = (amount_pct / 100.0 - 0.5) * 2 * grid
    out = []
    for n in notes:
        pos = n["start_time"] / grid
        k = int(round(pos))
        c = _clean(n)
        if abs(pos - k) < 0.08 and k % 2 == 1:
            c["start_time"] = n["start_time"] + shift
            c["duration"] = max(n["duration"] - shift, 0.01) if n["duration"] > shift else n["duration"]
        out.append(c)
    return out


def humanize(notes, timing: float = 0.01, velocity: int = 8, seed: int = 0):
    rnd = random.Random(seed)
    return [dict(_clean(n), start_time=max(0.0, n["start_time"] + rnd.gauss(0, timing)),
                 velocity=n.get("velocity", 100) + rnd.randint(-velocity, velocity)) for n in notes]


def accent(notes, pattern: Sequence[float] = (1.0, 0.7, 0.85, 0.7), grid: float = 1.0, base: int = 110):
    """Velocity by position: pattern repeats every len(pattern) grid units."""
    out = []
    for n in notes:
        k = int(round(n["start_time"] / grid)) % len(pattern)
        on_grid = abs(n["start_time"] / grid - round(n["start_time"] / grid)) < 0.05
        f = pattern[k] if on_grid else min(pattern) * 0.9
        out.append(dict(_clean(n), velocity=base * f))
    return out


def articulate(notes, factor: Optional[float] = None, legato: bool = False):
    """Scale note lengths (0.5 = staccato) or make each note last to the next onset."""
    if legato:
        onsets = sorted({n["start_time"] for n in notes})
        out = []
        for n in notes:
            nxt = next((o for o in onsets if o > n["start_time"] + 1e-6), None)
            out.append(dict(_clean(n), duration=(nxt - n["start_time"]) if nxt else n["duration"]))
        return out
    return [dict(_clean(n), duration=n["duration"] * (factor or 1.0)) for n in notes]


def fold_range(notes, low, high):
    lo, hi = parse_note(low), parse_note(high)
    if hi - lo < 12:
        raise TheoryError("Range must span at least an octave")
    out = []
    for n in notes:
        p = n["pitch"]
        while p < lo:
            p += 12
        while p > hi:
            p -= 12
        out.append(dict(_clean(n), pitch=p))
    return out


def harmonize(notes, root, scale: str, steps: Sequence[int] = (2,), keep_original: bool = True,
              velocity_factor: float = 0.85):
    """Add diatonic parallel voices: steps 2 = third above, -2 = third
    below, 4 = fifth, 5 = sixth, 7 = octave."""
    r, ivs = parse_pitch_class(root), SCALES[scale_key(scale)]["intervals"]
    out = [_clean(n) for n in notes] if keep_original else []
    for n in notes:
        st, off, _ = _degree_of(n["pitch"], r, ivs)
        for s in steps:
            out.append(dict(_clean(n), pitch=_pitch_of(st + s, 0, r, ivs),
                            velocity=n.get("velocity", 100) * velocity_factor))
    return out


def _groups(notes, tol=0.03):
    groups = []
    for n in sorted(notes, key=lambda n: (n["start_time"], n["pitch"])):
        if groups and abs(groups[-1][0]["start_time"] - n["start_time"]) <= tol:
            groups[-1].append(n)
        else:
            groups.append([n])
    return groups


def arpeggiate(notes, rate: float = 0.25, pattern: str = "up", octaves: int = 1, gate: float = 0.9, seed: int = 0):
    """Turn each chord (notes starting together) into an arpeggio lasting the chord."""
    rnd = random.Random(seed)
    out = []
    groups = _groups(notes)
    for gi, g in enumerate(groups):
        pitches = sorted(n["pitch"] for n in g)
        pitches = [p + 12 * o for o in range(octaves) for p in pitches]
        if pattern == "down":
            seq = pitches[::-1]
        elif pattern in ("updown", "up_down"):
            seq = pitches + pitches[-2:0:-1]
        elif pattern == "random":
            seq = pitches[:]
        else:
            seq = pitches
        start = g[0]["start_time"]
        length = max(n["duration"] for n in g)
        if gi + 1 < len(groups):  # stop where the next chord starts
            length = min(length, groups[gi + 1][0]["start_time"] - start)
        vel = max(n.get("velocity", 100) for n in g)
        k = 0
        while k * rate < length - 1e-6:
            p = rnd.choice(seq) if pattern == "random" else seq[k % len(seq)]
            out.append(_clean({"pitch": p, "start_time": start + k * rate,
                               "duration": min(rate * gate, length - k * rate), "velocity": vel}))
            k += 1
    return out


def strum(notes, spread: float = 0.03, direction: str = "down"):
    """Stagger chord notes like a guitar strum (down = low to high)."""
    out = []
    for g in _groups(notes):
        order = sorted(g, key=lambda n: n["pitch"], reverse=(direction == "up"))
        for i, n in enumerate(order):
            out.append(dict(_clean(n), start_time=n["start_time"] + i * spread,
                            duration=max(n["duration"] - i * spread, 0.05)))
    return out


def voice_chords(notes, voicing: str = "close"):
    """Re-voice each chord: close (within an octave above the bass), drop2
    (2nd highest dropped an octave), open (alternate notes up an octave),
    spread (root low, rest spread over two octaves)."""
    out = []
    for g in _groups(notes):
        if len(g) < 3:
            out.extend(_clean(n) for n in g)
            continue
        pitches = sorted(n["pitch"] for n in g)
        bass = pitches[0]
        # every other chord tone stacked within the octave above the bass
        upper = sorted({bass + ((p - bass) % 12 or 12) for p in pitches[1:]})
        close = [bass] + upper
        if voicing == "drop2" and len(close) >= 4:
            v = close[:]
            v[-2] -= 12
            new = sorted(v)
        elif voicing == "open":
            new = sorted(p + (12 if i % 2 == 1 else 0) for i, p in enumerate(close))
        elif voicing == "spread":
            new = [bass - 12] + [p + 12 * (i % 2) for i, p in enumerate(close[1:])]
        else:
            new = close
        tmpl = g[0]
        for p in sorted(new):
            out.append(dict(_clean(tmpl), pitch=p))
    return out


OPERATIONS = {
    "transpose": (transpose, "semitones"),
    "transpose_diatonic": (transpose_diatonic, "steps, root, scale"),
    "change_mode": (change_mode, "root, from_scale, to_scale[, to_root]"),
    "snap_to_scale": (snap_to_scale, "root, scale[, direction nearest|up|down]"),
    "invert": (invert, "axis (e.g. 'C4' or 60)[, root, scale for a diatonic mirror]"),
    "retrograde": (retrograde, "[length]"),
    "time_scale": (time_scale, "factor (2 = twice as slow)"),
    "quantize": (quantize, "[grid=0.25, strength=1.0, durations=False]"),
    "swing": (swing, "[amount_pct=60, grid=0.5]"),
    "humanize": (humanize, "[timing=0.01 beats, velocity=8, seed=0]"),
    "accent": (accent, "[pattern=(1,0.7,0.85,0.7), grid=1.0, base=110]"),
    "articulate": (articulate, "factor (0.5 = staccato) or legato=True"),
    "fold_range": (fold_range, "low, high (e.g. 'C3', 'C5')"),
    "harmonize": (harmonize, "root, scale[, steps=(2,), keep_original=True]"),
    "arpeggiate": (arpeggiate, "[rate=0.25, pattern up|down|updown|random, octaves=1, gate=0.9]"),
    "strum": (strum, "[spread=0.03, direction down|up]"),
    "voice_chords": (voice_chords, "voicing close|drop2|open|spread"),
}


def apply_operations(notes: List[Dict], operations: List[Dict]) -> List[Dict]:
    out = [_clean(n) for n in notes]
    for op in operations:
        op = dict(op)
        name = op.pop("op", None) or op.pop("operation", None)
        if name not in OPERATIONS:
            raise TheoryError("Unknown operation '%s'. Known: %s" % (name, ", ".join(OPERATIONS)))
        fn = OPERATIONS[name][0]
        for k in ("pattern", "steps"):
            if k in op and isinstance(op[k], list):
                op[k] = tuple(op[k])
        out = fn(out, **op)
    return [n for n in (_clean(n) for n in out) if 0 <= n["pitch"] <= 127 and n["start_time"] >= 0]


# ------------------------------------------------------------- progressions

_NUMERAL_RE = re.compile(r"^(b|#)?(VII|VI|V|IV|III|II|I|vii|vi|v|iv|iii|ii|i)(.*)$")


def parse_numeral(token: str, root, scale: str = "major") -> Dict:
    """"V7", "bVII", "ii7", "V/V", "iv" (borrowed), "N6" -> chord in key.

    Upper case = major-third chord, lower case = minor; suffixes 7, maj7,
    °, ø7, +, sus4, add9, 9... An unaltered numeral takes the scale's
    degree; b/# alter it from the major scale."""
    r = parse_pitch_class(root)
    token = token.strip()
    if token == "N6":
        return {"root": (r + 1) % 12, "quality": "", "symbol": chord_symbol((r + 1) % 12, "", r, (r + 5) % 12),
                "bass": (r + 5) % 12, "numeral": token}
    if "/" in token:
        main, target = token.split("/", 1)
        t = parse_numeral(target, root, scale)
        inner = parse_numeral(main, SHARPS[t["root"]], "major")
        inner["numeral"] = token
        return inner
    m = _NUMERAL_RE.match(token)
    if not m:
        raise TheoryError("Can't read numeral '%s'" % token)
    acc, num, suffix = m.groups()
    degree = [x.upper() for x in _ROMAN].index(num.upper())
    ivs = SCALES[scale_key(scale)]["intervals"]
    if acc:
        iv = _MAJOR[degree] + (-1 if acc == "b" else 1)
    else:
        iv = ivs[degree] if len(ivs) == 7 else _MAJOR[degree]
    croot = (r + iv) % 12
    minor = num.islower()
    suffix = suffix.replace("°", "dim").replace("ø7", "m7b5").replace("ø", "m7b5").replace("+", "aug")
    if suffix == "dim7":
        q = "dim7"
    elif suffix.startswith("dim"):
        q = "dim" + suffix[3:] if suffix[3:] == "7" else "dim"
    elif suffix.startswith("m7b5"):
        q = "m7b5"
    elif suffix.startswith("aug"):
        q = "aug" + ("7" if "7" in suffix else "")
    elif minor:
        q = {"": "m", "7": "m7", "9": "m9", "11": "m11", "6": "m6", "maj7": "mMaj7", "add9": "madd9"}.get(suffix,
                                                                                                        "m" + suffix)
    else:
        q = suffix
    q = _CHORD_ALIASES.get(q, q)
    if q not in CHORD_TYPES:
        raise TheoryError("Unknown chord quality in numeral '%s'" % token)
    return {"root": croot, "quality": q, "symbol": chord_symbol(croot, q, r), "bass": None, "numeral": token}


def _voice_lead(prev: Optional[List[int]], pcs: List[int], low: int, high: int, size: int) -> List[int]:
    """Choose the voicing of ``pcs`` in [low, high] closest to ``prev``."""
    import itertools
    candidates = []
    pcs = pcs[:size] if len(pcs) > size else pcs
    options = [[p for p in range(low, high + 1) if p % 12 == pc] for pc in pcs]
    for combo in itertools.product(*options):
        v = sorted(combo)
        if v[-1] - v[0] > 19:
            continue
        candidates.append(v)
    if not candidates:
        base = low + (pcs[0] - low) % 12
        return sorted(base + ((pc - pcs[0]) % 12) for pc in pcs)
    if prev is None:
        centre = (low + high) / 2
        return min(candidates, key=lambda v: abs(sum(v) / len(v) - centre))

    def cost(v):
        a, b = sorted(prev), v
        if len(a) == len(b):
            return sum(abs(x - y) for x, y in zip(a, b))
        return sum(min(abs(x - y) for y in b) for x in a) + sum(min(abs(x - y) for x in a) for y in b)
    return min(candidates, key=cost)


# Rhythm patterns: (start, length, what) per bar of 4 beats; what = "chord",
# "bass", "arp", "root+5"...
PATTERNS = {
    "block": "Accord tenu toute la mesure + basse",
    "pulse": "Accord à chaque temps (noires) + basse",
    "pulse8": "Accord en croches + basse en noires",
    "offbeat": "Accords sur les contretemps (reggae / house), basse sur les temps",
    "arp8": "Arpège montant en croches + basse",
    "arp16": "Arpège montant en doubles croches + basse",
    "alberti": "Basse d'Alberti (grave-aigu-médium-aigu) en doubles croches",
    "bossa": "Comping bossa nova (syncopé) + basse fondamentale/quinte",
    "waltz": "Valse : basse au 1er temps, accord aux 2e et 3e (3/4)",
    "ballad": "Accord arpégé lent + basse, style ballade piano",
    "stabs": "Accords courts syncopés (funk / house stabs)",
}


def render_progression(chords: List[Dict], beats_per_chord: float = 4.0, pattern: str = "block",
                       low: str = "E3", high: str = "G4", bass: bool = True, bass_octave: int = 2,
                       voices: int = 4, velocity: int = 96) -> List[Dict]:
    lo, hi = parse_note(low), parse_note(high)
    notes, prev = [], None
    for i, c in enumerate(chords):
        tones = [(c["root"] + t) % 12 for t in CHORD_TYPES[c["quality"]]]
        voicing = _voice_lead(prev, tones, lo, hi, voices)
        prev = voicing
        t0 = i * beats_per_chord
        L = beats_per_chord
        bass_pc = c["bass"] if c.get("bass") is not None else c["root"]
        bass_p = bass_pc + 12 * (bass_octave + 1)

        def chord_at(start, length, vel=velocity):
            for p in voicing:
                notes.append(_clean({"pitch": p, "start_time": t0 + start, "duration": length, "velocity": vel}))

        def bass_at(start, length, pitch=None, vel=velocity + 8):
            if bass:
                notes.append(_clean({"pitch": pitch or bass_p, "start_time": t0 + start, "duration": length,
                                     "velocity": vel}))

        if pattern == "block":
            chord_at(0, L * 0.98)
            bass_at(0, L * 0.98)
        elif pattern == "pulse":
            for b in range(int(L)):
                chord_at(b, 0.9, velocity - (0 if b % 2 == 0 else 12))
            bass_at(0, L * 0.98)
        elif pattern == "pulse8":
            for k in range(int(L * 2)):
                chord_at(k * 0.5, 0.42, velocity - (0 if k % 2 == 0 else 18))
            for b in range(int(L)):
                bass_at(b, 0.9)
        elif pattern == "offbeat":
            for b in range(int(L)):
                chord_at(b + 0.5, 0.35)
                bass_at(b, 0.45)
        elif pattern in ("arp8", "arp16"):
            rate = 0.5 if pattern == "arp8" else 0.25
            seq = voicing + [voicing[-1] + 12] if pattern == "arp16" else voicing
            for k in range(int(L / rate)):
                notes.append(_clean({"pitch": seq[k % len(seq)], "start_time": t0 + k * rate,
                                     "duration": rate * 0.95, "velocity": velocity - (0 if k % 4 == 0 else 14)}))
            bass_at(0, L * 0.98)
        elif pattern == "alberti":
            v = sorted(voicing)
            seq = [v[0], v[-1], v[len(v) // 2], v[-1]]
            for k in range(int(L / 0.25)):
                notes.append(_clean({"pitch": seq[k % 4], "start_time": t0 + k * 0.25, "duration": 0.24,
                                     "velocity": velocity - (0 if k % 4 == 0 else 16)}))
            bass_at(0, L * 0.98)
        elif pattern == "bossa":
            for s, l in [(0, 0.45), (1.5, 0.45), (3, 0.45)] + ([(4.5, 0.45), (6, 0.45)] if L >= 8 else []):
                if s < L:
                    chord_at(s, l, velocity - 6)
            fifth_low = bass_p - 5  # the fifth, below the root
            for s, p, l in [(0, bass_p, 1.4), (1.5, fifth_low, 0.45), (2, fifth_low, 1.4), (3.5, bass_p, 0.45)]:
                if s < L:
                    bass_at(s, l, p)
        elif pattern == "waltz":
            for bar in range(int(L // 3) or 1):
                bass_at(bar * 3, 0.9)
                chord_at(bar * 3 + 1, 0.8, velocity - 10)
                chord_at(bar * 3 + 2, 0.8, velocity - 14)
        elif pattern == "ballad":
            v = sorted(voicing)
            for k, p in enumerate(v + v[-2:0:-1]):
                s = k * (L / (2 * len(v)))
                if s < L:
                    notes.append(_clean({"pitch": p, "start_time": t0 + s, "duration": L - s,
                                         "velocity": velocity - 10}))
            bass_at(0, L * 0.98)
        elif pattern == "stabs":
            for s in [0, 0.75, 1.5, 2.5, 3.25]:
                if s < L:
                    chord_at(s, 0.2, velocity + 4)
            bass_at(0, 0.45)
            bass_at(2.5, 0.45)
        else:
            raise TheoryError("Unknown pattern '%s'. Known: %s" % (pattern, ", ".join(PATTERNS)))
    return notes


def progression(root, scale: str, numerals: Sequence[str]) -> List[Dict]:
    return [parse_numeral(tok, root, scale) for tok in numerals]


def substitutions(symbol: str, key_root=None) -> List[Dict]:
    """Reharmonisation ideas for one chord."""
    r, q, ivs, _ = parse_chord(symbol)
    kr = parse_pitch_class(key_root) if key_root is not None else None
    out = []
    if q in ("7", "9", "13", "7b9", "7#9", "7alt"):
        out.append({"chord": chord_symbol((r + 6) % 12, "7", kr), "why": "substitution tritonique (même triton)"})
        out.append({"chord": chord_symbol((r + 7) % 12, "m7", kr) + " " + chord_symbol(r, q, kr),
                    "why": "préparer par le ii (ii-V)"})
        out.append({"chord": chord_symbol(r, "7alt", kr), "why": "dominante altérée, plus de tension"})
        out.append({"chord": chord_symbol((r + 1) % 12, "dim7", kr), "why": "diminué de passage (vii°7 de la cible)"})
    if q in ("", "maj7", "6", "add9", "maj9"):
        out.append({"chord": chord_symbol((r + 9) % 12, "m7", kr), "why": "relatif mineur (vi), même fonction tonique"})
        out.append({"chord": chord_symbol((r + 4) % 12, "m7", kr), "why": "iii, tonique plus douce"})
        out.append({"chord": chord_symbol(r, "maj9", kr), "why": "enrichir (9e) : couleur jazz / neo-soul"})
        out.append({"chord": chord_symbol((r + 7) % 12, "7", kr), "why": "dominante qui y mène (V7)"})
    if q in ("m", "m7", "m9"):
        out.append({"chord": chord_symbol((r + 3) % 12, "maj7", kr), "why": "relatif majeur, même fonction"})
        out.append({"chord": chord_symbol(r, "m9", kr), "why": "enrichir (9e)"})
        out.append({"chord": chord_symbol(r, "m6", kr), "why": "couleur dorienne (6te majeure)"})
        out.append({"chord": chord_symbol((r + 7) % 12, "7", kr), "why": "V7 du mineur (cadence)"})
    if kr is not None:
        iv = (r - kr) % 12
        if iv == 5 and q in ("", "maj7"):
            out.append({"chord": chord_symbol(r, "m", kr), "why": "iv emprunté au mineur (mélancolie)"})
        if iv == 0 and q in ("", "maj7"):
            out.append({"chord": chord_symbol((kr + 8) % 12, "", kr), "why": "bVI emprunté (épique, cinéma)"})
            out.append({"chord": chord_symbol((kr + 10) % 12, "", kr), "why": "bVII emprunté (rock, mixolydien)"})
    return out
