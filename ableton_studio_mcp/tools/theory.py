"""Music theory: scales, styles, chord ideas, clip analysis and transformations, progressions, song scale."""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List

from .. import live
from ..app import as_json, clip_target, tool, write_notes

log = logging.getLogger("ableton_studio_mcp")


@tool()
def music_scales(query: str = None, root: str = None, scale: str = None) -> str:
    """
    Scales and modes knowledge. Without arguments, lists all ~50 scales
    (church modes, harmonic/melodic minor families, pentatonics, blues,
    bebop, symmetric, Japanese, gamelan, flamenco...) with their character
    and typical styles; `query` filters (e.g. "flamenco", "jazz", "sombre").
    With `root` and `scale`, details one scale: notes spelled in the key,
    degrees, characteristic note, character, styles, diatonic seventh chords
    with roman numerals and functions, the other modes with the same notes,
    and Live 12's scale name (for set_song_scale).

    Parameters:
    - query: Text to filter the list
    - root: Tonic (e.g. "D", "Eb") to detail one scale
    - scale: Scale name (e.g. "dorian", "phrygian dominant", "hijaz", "harmonic minor")
    """
    from .. import music_theory as mt

    if root is not None and scale is not None:
        return as_json(mt.scale_info(root, scale))
    return as_json(mt.search_scales(query))


@tool()
def music_styles(style: str = None) -> str:
    """
    Style sheets for composing or re-arranging: without `style`, the list;
    with it, what makes the style: tempo, metre, scales/modes, harmonic
    language, typical progressions (roman numerals for write_progression),
    rhythm/groove and swing amount, bass, melody, arrangement, accompaniment
    patterns, and which Live devices/tools help. Styles: baroque,
    classical_romantic, jazz, bossa_nova, blues, gospel_neo_soul, funk, pop,
    rock, house, techno, trance, drum_and_bass, hip_hop_boom_bap, lofi, trap,
    rnb, reggae, reggaeton, afrobeat, flamenco, film_epic, ambient, synthwave
    (aliases such as "Bach", "lo-fi", "dnb" work).

    Parameters:
    - style: Style name (optional)
    """
    from .. import music_styles as ms

    return as_json(ms.get_style(style) if style else ms.list_styles())


@tool()
def music_chord_ideas(chord: str, key_root: str = None) -> str:
    """
    Reharmonisation ideas for a chord (tritone substitution, ii-V
    preparation, relative chords, extensions, borrowed chords in the key),
    with the reason for each, plus the chord's notes.

    Parameters:
    - chord: Chord symbol, e.g. "G7", "Fmaj7", "Am", "Bø", "Ebmaj7/G"
    - key_root: Key tonic, to suggest borrowed chords (optional)
    """
    from .. import music_theory as mt

    r, q, ivs, bass = mt.parse_chord(chord)
    kr = mt.parse_pitch_class(key_root) if key_root else None
    return as_json({
        "chord": chord,
        "notes": [mt.pc_name((r + i) % 12, kr) for i in ivs],
        "roman_in_key": mt.roman_numeral(r, q, kr) if kr is not None else None,
        "ideas": mt.substitutions(chord, key_root),
    })


def _read_clip_notes(ableton, track_index: int, clip_index: int, location: str):
    data = ableton.call("get_clip_notes", clip_target(track_index, clip_index, location))
    return data.get("notes", []), data


@tool()
def analyze_clip_music(track_index: int,
    clip_index: int,
    location: str = "session",
    segment_beats: float = 2.0,
    key_root: str = None,
    key_scale: str = None,
    vocabulary: str = "basic",
) -> str:
    """
    Musical analysis of a MIDI clip: key and mode candidates (with coverage
    and outside notes; relative modes are told apart by the harmony, e.g. a
    V7 pointing to its tonic), chords per segment with roman numerals,
    out-of-scale notes, range, rhythm (density, offbeat share, polyphony) and
    melodic motion of the top line. Also reports Live's song scale.

    Parameters:
    - track_index / clip_index: The clip (Session slot or Arrangement index)
    - location: "session" (default) or "arrangement"
    - segment_beats: Chord detection window (2 = two chords per bar by default,
      4 = one per bar, 1 per beat); identical neighbours are merged
    - key_root / key_scale: Force the key used for roman numerals (optional)
    - vocabulary: "basic" (triads and sevenths: classical, pop, counterpoint)
      or "jazz" (adds 6, 9, sus and extended chords)
    """
    from .. import music_theory as mt

    ableton = live.client()
    notes, data = _read_clip_notes(ableton, track_index, clip_index, location)
    result = mt.analyze_notes(notes, segment_beats=segment_beats, key_root=key_root,
                              key_scale=key_scale, vocabulary=vocabulary)
    result["clip"] = {"name": data.get("clip_name"), "length": data.get("length")}
    if live.supports("get_song_scale"):
        try:
            result["live_song_scale"] = ableton.call("get_song_scale")
        except Exception:
            pass
    return as_json(result)


@tool()
def transform_clip(track_index: int,
    clip_index: int,
    operations: List[Dict[str, Any]],
    location: str = "session",
    target_clip_index: int = None,
) -> str:
    """
    Re-arrange a MIDI clip with a chain of music-theory operations, applied in
    order. Writes the result back into the clip, or into an empty Session slot
    `target_clip_index` (keeps the original: safer for trying ideas).

    Each operation is {"op": name, ...arguments}:
    - transpose: semitones
    - transpose_diatonic: steps, root, scale (moves along the scale)
    - change_mode: root, from_scale, to_scale[, to_root] (C major -> C dorian...)
    - snap_to_scale: root, scale[, direction nearest|up|down]
    - invert: axis ("C4" or 60)[, root, scale for a diatonic mirror]
    - retrograde: [length]
    - time_scale: factor (2 = half speed, 0.5 = double)
    - quantize: [grid=0.25, strength=1.0, durations=false]
    - swing: [amount_pct=60 (50 straight, 66.7 triplet), grid=0.5]
    - humanize: [timing=0.01 beats, velocity=8, seed=0]
    - accent: [pattern=[1,0.7,0.85,0.7], grid=1.0, base=110]
    - articulate: factor (0.5 = staccato) or legato=true
    - fold_range: low, high (e.g. "C3", "C5")
    - harmonize: root, scale[, steps=[2] (2 = third above, -2 below, 4 fifth, 5 sixth), keep_original=true]
    - arpeggiate: [rate=0.25, pattern up|down|updown|random, octaves=1, gate=0.9]
    - strum: [spread=0.03, direction down|up]
    - voice_chords: voicing close|drop2|open|spread
    Notes are written as C4 = MIDI 60 (Live displays it as C3).

    Parameters:
    - track_index / clip_index: Source clip
    - operations: List of operations (see above)
    - location: "session" (default) or "arrangement"
    - target_clip_index: Empty Session slot on the same track for the result (optional)
    """
    from .. import music_theory as mt

    ableton = live.client()
    notes, data = _read_clip_notes(ableton, track_index, clip_index, location)
    if not notes:
        return "The clip has no notes"
    result = mt.apply_operations(notes, operations)
    if target_clip_index is not None:
        if location != "session":
            return "target_clip_index is for Session clips"
        end = max(n["start_time"] + n["duration"] for n in result)
        length = max(float(data.get("length") or 4.0), 4.0 * math.ceil(end / 4.0 - 1e-9))
        ableton.call("create_clip", {"track_index": track_index,
                                             "clip_index": target_clip_index, "length": length})
        dest = target_clip_index
    else:
        ableton.call("clear_notes_from_clip", clip_target(track_index, clip_index, location))
        dest = clip_index
    write_notes(track_index, dest, result, location)
    after = mt.analyze_notes(result)
    return as_json({
        "written_to": ("slot %d" % dest) if target_clip_index is not None else "same clip",
        "notes_before": len(notes), "notes_after": len(result),
        "operations": [o.get("op") or o.get("operation") for o in operations],
        "key_after": after.get("key", {}).get("best"),
        "chords_after": after.get("chords", [])[:16],
    })


@tool()
def write_progression(track_index: int,
    clip_index: int,
    root: str,
    scale: str = "major",
    numerals: List[str] = None,
    style: str = None,
    progression_index: int = 0,
    beats_per_chord: float = 4.0,
    pattern: str = None,
    low: str = "E3",
    high: str = "G4",
    bass: bool = True,
    repeat: int = 1,
    voices: int = 4,
) -> str:
    """
    Write a chord progression into an empty Session slot (clip created to
    fit) or an existing clip, voiced with smooth voice leading and played
    with an accompaniment pattern.

    Give `numerals` (roman numerals in the key: "ii7", "V7", "Imaj7",
    "bVII", "iv", "V/V", "N6", "viiø7"...) or a `style` (its typical
    progression number `progression_index`, its scale and pattern are used
    unless given). Patterns: block, pulse, pulse8, offbeat, arp8, arp16,
    alberti, bossa, waltz, ballad, stabs.

    Parameters:
    - track_index / clip_index: Target MIDI track and Session slot
    - root: Key tonic ("C", "F#", "Bb")
    - scale: Scale/mode of the key (default major)
    - numerals: Roman numerals (optional if style)
    - style: Style name (see music_styles)
    - progression_index: Which of the style's progressions
    - beats_per_chord: Harmonic rhythm (4 = one chord per bar)
    - pattern: Accompaniment pattern (default: the style's first, else block)
    - low / high: Range of the chord voicings
    - bass: Add a bass line (root, an octave or two below)
    - repeat: Times to repeat the progression
    - voices: Notes per chord voicing (3-5)
    """
    from .. import music_styles as ms
    from .. import music_theory as mt

    st = ms.get_style(style) if style else None
    if numerals is None:
        if not st:
            return "Give numerals or a style"
        numerals = st["progressions"][progression_index % len(st["progressions"])]
        if scale == "major" and st["scales"]:
            first = numerals[0]
            scale = st["scales"][0] if first[:1].islower() or first.startswith(("b", "#")) else scale
    pattern = pattern or (st["patterns"][0] if st else "block")
    chords = mt.progression(root, scale, list(numerals) * max(repeat, 1))
    notes = mt.render_progression(chords, beats_per_chord=beats_per_chord, pattern=pattern,
                                  low=low, high=high, bass=bass, voices=voices)
    ableton = live.client()
    info = ableton.call("get_track_info", {"track_index": track_index})
    slots = info.get("clip_slots", [])
    if clip_index < 0 or clip_index >= len(slots):
        return f"Clip slot {clip_index} out of range ({len(slots)} slots)"
    length = beats_per_chord * len(chords)
    if not slots[clip_index].get("has_clip"):
        ableton.call("create_clip", {"track_index": track_index, "clip_index": clip_index,
                                             "length": length})
    write_notes(track_index, clip_index, notes, "session")
    return as_json({
        "key": "%s %s" % (root, mt.scale_key(scale)),
        "style": st["style"] if st else None,
        "pattern": pattern,
        "chords": [{"numeral": c["numeral"], "symbol": c["symbol"]} for c in chords[:len(numerals)]],
        "notes_written": len(notes),
        "clip_length_beats": length,
        "swing_hint_pct": st["swing"] if st else None,
    })


@tool()
def get_song_scale() -> str:
    """
    Live 12's song scale: root, scale name, intervals and the Scale Mode
    switch (which highlights the scale in the piano roll and drives devices
    set to "Use Current Scale", e.g. the Scale, Arpeggiator and Chord devices).
    """
    live.require("get_song_scale")
    return as_json(live.client().call("get_song_scale"))


@tool()
def set_song_scale(root: str = None, scale: str = None, scale_mode: bool = None) -> str:
    """
    Set Live 12's song scale so the piano roll shows it and scale-aware
    devices follow it. `scale` accepts this server's names (dorian, hijaz,
    harmonic minor...) and maps them to Live's name when Live has the scale.

    Parameters:
    - root: Tonic ("C", "Eb", "F#")
    - scale: Scale name
    - scale_mode: Turn Live's Scale Mode on/off
    """
    from .. import music_theory as mt
    live.require("set_song_scale")
    params: Dict[str, Any] = {}
    if root is not None:
        params["root_note"] = mt.parse_pitch_class(root)
    if scale is not None:
        try:
            live_name = mt.SCALES[mt.scale_key(scale)]["live_name"]
        except mt.TheoryError:
            live_name = scale  # maybe one of Live's own names
        if not live_name:
            return ("Live has no '%s' scale; set the closest one or keep it out of Live's "
                    "scale and use snap_to_scale on the clips" % scale)
        params["scale_name"] = live_name
    if scale_mode is not None:
        params["scale_mode"] = scale_mode
    return as_json(live.client().call("set_song_scale", params))
