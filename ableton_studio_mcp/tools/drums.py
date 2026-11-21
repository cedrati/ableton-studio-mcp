"""Drum programming and the Groove Pool."""

from __future__ import annotations

import logging
from typing import Any, Dict

from .. import live
from ..app import as_json, clip_target, tool, write_notes

log = logging.getLogger("ableton_studio_mcp")


def _kit_roles(ableton, track_index: int):
    """(roles, rack info or None) from the track's Drum Rack pad names."""
    from .. import drums
    if not live.supports("get_drum_rack_map"):
        return {}, None
    try:
        kit = ableton.call("get_drum_rack_map", {"track_index": track_index})
    except Exception:
        return {}, None
    return drums.infer_roles(kit.get("pads", [])), kit


@tool()
def drum_patterns(style: str = None, euclid_hits: int = None, euclid_steps: int = 16,
                  euclid_rotate: int = 0) -> str:
    """
    Drum pattern library for electronic music. Without arguments, lists the
    styles (techno_four, techno_rolling, techno_hypnotic, minimal_techno,
    dub_techno, hard_techno, acid_techno, detroit_techno, house_classic,
    deep_house, tech_house, afro_house, uk_garage, breakbeat, electro,
    drum_and_bass, dubstep, trap, ebm). With `style`, its grids per role,
    tempo, swing, production notes and the available fills. With
    `euclid_hits`, returns a Euclidean rhythm grid, e.g. 3/8 = tresillo.

    Grid language (one string per role, 16 steps = one bar of 16ths):
    x hit · X accent · o ghost · . rest · 2 3 4 ratchet · ? 50 % chance · * 25 % chance ghost.

    Parameters:
    - style: Pattern style (optional)
    - euclid_hits / euclid_steps / euclid_rotate: Euclidean rhythm (optional)
    """
    from .. import drums

    if euclid_hits is not None:
        return as_json({"grid": drums.euclid(euclid_hits, euclid_steps, euclid_rotate)})
    return as_json(drums.describe(style) if style else drums.list_patterns())


@tool()
def get_drum_map(track_index: int) -> str:
    """
    The Drum Rack on a track: every filled pad (MIDI note, name, devices)
    and the role each one plays (kick, clap, closed_hat, open_hat, rim,
    ride, perc...), read from the pad names, as used by write_drum_pattern.

    Parameters:
    - track_index: Track holding the Drum Rack
    """
    live.require("get_drum_rack_map")
    roles, kit = _kit_roles(live.client(), track_index)
    if kit is None:
        return "No Drum Rack found on track %d" % track_index
    kit["roles"] = roles
    return as_json(kit)


@tool(undo_step="Write drum pattern")
def write_drum_pattern(track_index: int,
    clip_index: int,
    style: str = None,
    layers: Dict[str, Any] = None,
    bars: int = 4,
    steps_per_bar: int = 16,
    swing_pct: float = None,
    fill: str = None,
    fill_every: int = 4,
    variation: float = 0.0,
    humanize: float = 0.0,
    replace: bool = False,
    seed: int = 0,
) -> str:
    """
    Program drums into a Session slot (clip created to fit) on a track with
    a Drum Rack. Roles are mapped to the kit's pads by their names (a
    similar free pad stands in for a missing role; missing ones are
    reported); without a Drum Rack, General MIDI notes are used.

    Start from a library `style` and/or give `layers`: {role: grid} or
    {role: {"euclid": [hits, steps, rotate]}}; layers override or extend the
    style. Roles: kick, clap, snare, rim, closed_hat, open_hat, pedal_hat,
    ride, crash, tom_low, tom_mid, tom_high, perc, shaker, tambourine, conga,
    bongo, clave, cowbell, fx. A grid shorter or longer than a bar cycles
    over the whole clip (a 12-step loop drifts against 16-step bars).
    Grid: x hit · X accent · o ghost · . rest · 2/3/4 ratchet · ? 50 % · * 25 % ghost
    (probabilities use Live 12's per-note chance, so the loop varies as it plays).

    Parameters:
    - track_index / clip_index: Drum track and Session slot
    - style: Library pattern (see drum_patterns)
    - layers: Extra or replacement grids per role
    - bars: Clip length in bars (4/4)
    - steps_per_bar: Grid resolution (16 = 16ths, 12 = 8th-note triplets, 32)
    - swing_pct: Swing on odd steps, 50 = straight (default: the style's)
    - fill: Every `fill_every` bars: roll, drop, open_hat, ratchet or crash
    - variation: 0-1, chance of extra ghost hats (written with low probability)
    - humanize: Timing spread in beats (e.g. 0.005), with small velocity changes
    - replace: Clear an existing clip in the slot first
    - seed: Random seed for variation/humanize
    """
    from .. import drums
    grids: Dict[str, str] = {}
    swing = 50.0
    if style:
        grids.update(drums.pattern_layers(style))
        swing = drums.PATTERNS[style]["swing"]
    for role, spec in (layers or {}).items():
        if isinstance(spec, dict) and "euclid" in spec:
            e = list(spec["euclid"]) + [0] * (3 - len(spec["euclid"]))
            grids[role] = drums.euclid(int(e[0]), int(e[1]), int(e[2]))
        elif spec in (None, "", False):
            grids.pop(role, None)
        else:
            grids[role] = str(spec)
    if not grids:
        return "Give a style or layers"
    if swing_pct is not None:
        swing = swing_pct
    ableton = live.client()
    roles, kit = _kit_roles(ableton, track_index)
    result = drums.render(grids, roles, bars=bars, steps_per_bar=steps_per_bar, swing_pct=swing,
                          fill=fill, fill_every=fill_every, humanize=humanize, variation=variation,
                          seed=seed, use_gm=kit is None)
    notes = result["notes"]
    if any("probability" in n for n in notes) and not live.supports("note_probability"):
        for n in notes:  # an older script would drop the field anyway
            n.pop("probability", None)
    info = ableton.call("get_track_info", {"track_index": track_index})
    slots = info.get("clip_slots", [])
    if clip_index < 0 or clip_index >= len(slots):
        return f"Clip slot {clip_index} out of range ({len(slots)} slots)"
    length = result["length_beats"]
    if slots[clip_index].get("has_clip"):
        if not replace:
            return "Slot %d already has a clip; pass replace=true or pick an empty slot" % clip_index
        ableton.call("clear_notes_from_clip", clip_target(track_index, clip_index, "session"))
        ableton.call("set_clip_loop", {"track_index": track_index, "clip_index": clip_index,
                                               "loop_start": 0.0, "loop_end": length})
    else:
        ableton.call("create_clip", {"track_index": track_index, "clip_index": clip_index,
                                             "length": length})
    write_notes(track_index, clip_index, notes, "session")
    return as_json({
        "kit": kit.get("rack_name") if kit else "no Drum Rack: General MIDI notes",
        "style": style, "bars": bars, "swing_pct": swing,
        "mapping": result["mapping"], "missing_roles": result["missing_roles"],
        "grids": grids, "notes_written": len(notes),
        "with_probability": sum(1 for n in notes if "probability" in n),
    })


@tool()
def get_groove_pool() -> str:
    """
    Live's Groove Pool: the grooves loaded in the set (name, base, timing,
    random, velocity and quantization amounts) and the global Groove amount.
    Grooves live in the browser under Packs (e.g.
    get_browser_items_at_path("packs/Core Library/Grooves")) and in the User
    Library; apply one with set_clip_groove. A groove only acts when the
    global amount is above 0 (set_groove_params global_amount).
    """
    live.require("get_groove_pool")
    return as_json(live.client().call("get_groove_pool"))


@tool()
def set_clip_groove(track_index: int, clip_index: int, groove_index: int = None,
                    location: str = "session") -> str:
    """
    Apply a Groove Pool groove to a clip (Live's own swing/groove engine,
    non-destructive), or remove it with groove_index omitted.

    Parameters:
    - track_index / clip_index: The clip
    - groove_index: Index from get_groove_pool (omit to remove the groove)
    - location: "session" (default) or "arrangement"
    """
    live.require("set_clip_groove")
    return as_json(live.client().call("set_clip_groove", {
        "track_index": track_index, "clip_index": clip_index, "groove_index": groove_index,
        "location": (location or "session").lower()}))


@tool()
def set_groove_params(groove_index: int = None, timing_amount: float = None,
                      random_amount: float = None, velocity_amount: float = None,
                      quantization_amount: float = None, global_amount: float = None) -> str:
    """
    Adjust a groove in the Groove Pool (amounts in %, as in Live) and/or the
    global Groove amount (0-1.3, i.e. 0-130 %).

    Parameters:
    - groove_index: Groove to change (from get_groove_pool)
    - timing_amount / random_amount / velocity_amount / quantization_amount: New amounts
    - global_amount: Global Groove amount
    """
    live.require("set_groove_params")
    values = {k: v for k, v in (("timing_amount", timing_amount), ("random_amount", random_amount),
                                ("velocity_amount", velocity_amount),
                                ("quantization_amount", quantization_amount)) if v is not None}
    return as_json(live.client().call("set_groove_params", {
        "groove_index": groove_index, "values": values, "global_amount": global_amount}))
