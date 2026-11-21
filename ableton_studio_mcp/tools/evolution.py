"""Long-form evolution and arrangement building."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .. import live
from ..app import as_json, clip_target, tool, write_notes

log = logging.getLogger("ableton_studio_mcp")


@tool()
def arrangement_templates(template: str = None) -> str:
    """
    Arrangement templates for electronic music and the automation curve
    shapes. Without `template`: the list (techno_dj, techno_64, minimal,
    house) and the shapes. With it: its sections (name, bars, energy 0-1,
    roles that play, production tip).

    Parameters:
    - template: Template name (optional)
    """
    from .. import arrangement as ar

    if template:
        return as_json({"template": template, "label": ar.TEMPLATES[template]["label"]
                      if template in ar.TEMPLATES else None,
                      "sections": ar.template_sections(template)})
    return as_json({"templates": {k: v["label"] for k, v in ar.TEMPLATES.items()},
                  "shapes": ar.SHAPES, "track_roles": [r for r, _ in ar.ROLE_WORDS]})


@tool()
def write_clip_evolution(track_index: int,
    clip_index: int,
    lanes: List[Dict[str, Any]],
    bars: int = None,
    resolution: float = 1.0,
) -> str:
    """
    Make a Session clip evolve over many bars: optionally extend it to `bars`
    (a MIDI loop is tiled, e.g. 4 -> 64 bars), then write one automation
    envelope per lane with a musical curve. Copied to the Arrangement (e.g.
    by build_arrangement), the envelopes become the track's automation there.

    Each lane: {"mixer_parameter": "volume" | "panning" | "send:N"} or
    {"device_index": d, "parameter_index": p}, plus "start", "end" (in the
    parameter's units, see get_device_parameters: min/max/display), "shape"
    (linear, exp, log, s_curve, swell, sine, triangle, steps, random_walk,
    hold), optional "cycles" (sine/triangle), "steps" (steps), "power"
    (exp/log curvature, default 2.5), "from_bar"/"to_bar" to limit the curve
    to part of the clip (the value holds outside), "seed".

    Example, a 64-bar techno build: filter cutoff exp from 0.3 to 0.9, reverb
    send swell, hats volume in 8 steps.

    Parameters:
    - track_index / clip_index: Session clip
    - lanes: Curves to write (see above)
    - bars: Extend the clip to this many bars first (MIDI clips; 4/4)
    - resolution: Envelope step in beats (1 = a point per beat)
    """
    from .. import arrangement as ar
    live.require("set_clip_automation")
    ableton = live.client()
    data = ableton.call("get_clip_notes", {"track_index": track_index, "clip_index": clip_index})
    length = float(data.get("length") or 0.0)
    report = {"clip_length_before": length}
    if bars:
        target = bars * 4.0
        if target > length + 1e-6:
            notes = data.get("notes", [])
            tiled = ar.tile_notes(notes, length, target)
            ableton.call("clear_notes_from_clip", clip_target(track_index, clip_index, "session"))
            ableton.call("set_clip_loop", {"track_index": track_index, "clip_index": clip_index,
                                                   "loop_start": 0.0, "loop_end": target,
                                                   "end_marker": target})
            write_notes(track_index, clip_index, tiled, "session")
            length = target
            report["extended_to_beats"] = target
            report["notes_after_tiling"] = len(tiled)
    report["lanes"] = []
    for lane in lanes:
        a = float(lane.get("from_bar", 0)) * 4.0
        z = float(lane["to_bar"]) * 4.0 if lane.get("to_bar") is not None else length
        z = min(z, length)
        pts = ar.curve_points(z - a, float(lane["start"]), float(lane["end"]),
                              shape=lane.get("shape", "linear"), resolution=resolution,
                              cycles=float(lane.get("cycles", 1.0)), steps=int(lane.get("steps", 4)),
                              power=float(lane.get("power", 2.5)), offset=a, seed=int(lane.get("seed", 0)))
        if a > 0:
            pts.insert(0, {"time": 0.0, "value": pts[0]["value"]})
        res = ableton.call("set_clip_automation", {
            "track_index": track_index, "clip_index": clip_index, "location": "session",
            "device_index": int(lane.get("device_index", -1)),
            "parameter_index": int(lane.get("parameter_index", 0)),
            "mixer_parameter": lane.get("mixer_parameter", ""), "points": pts,
            "interpolation": "step" if lane.get("shape") in ("steps", "hold") else "linear",
            "resolution": resolution, "clear_first": True})
        report["lanes"].append({"parameter": res.get("parameter"), "shape": lane.get("shape", "linear"),
                                "from_beat": a, "to_beat": z, "points": len(pts),
                                "start": lane["start"], "end": lane["end"]})
    report["clip_length_beats"] = length
    return as_json(report)


def _session_tracks(ableton) -> List[Dict[str, Any]]:
    count = int(ableton.call("get_session_info").get("track_count", 0))
    tracks = []
    for i in range(count):
        info = ableton.call("get_track_info", {"track_index": i})
        slots = {s["index"]: float(s["clip"]["length"]) for s in info.get("clip_slots", [])
                 if s.get("has_clip") and s.get("clip")}
        tracks.append({"index": i, "name": info.get("name", ""), "slots": slots})
    return tracks


@tool()
def build_arrangement(template: str = None,
    sections: List[Dict[str, Any]] = None,
    track_roles: Dict[str, str] = None,
    start_bar: int = 0,
    default_slot: int = 0,
    section_slots: Dict[str, Dict[str, int]] = None,
    locators: bool = True,
    dry_run: bool = False,
) -> str:
    """
    Build the Arrangement from Session clips, section by section, like a
    producer laying out a track: each section plays the clips of the tracks
    whose role is active there, tiled to fill it, with a named locator at its
    start. Clip envelopes (see write_clip_evolution) come along as track
    automation, so a filter build or a reverb swell plays in the Arrangement.

    Use a `template` (techno_dj, techno_64, minimal, house; see
    arrangement_templates) or your own `sections`: [{"name", "bars",
    "roles": [...]} or {"name", "bars", "play": {"track_index": slot}}].
    Track roles come from track names (kick, drums, hats, perc, rumble, bass,
    chords, pad, lead, vocal, fx) unless `track_roles` {"track_index": role}
    overrides them. `section_slots` {"Section name": {"track_index": slot}}
    picks another clip for a section (e.g. the automated build variant).
    Run with dry_run=true first to see the plan.

    Parameters:
    - template / sections: Structure to build
    - track_roles: Role per track index, overriding names
    - start_bar: Arrangement bar to start at (0 = beginning)
    - default_slot: Session slot used by default for every track
    - section_slots: Per-section slot overrides
    - locators: Add a locator at each section (transport must be stopped)
    - dry_run: Only return the plan
    """
    from .. import arrangement as ar

    if sections is None:
        if not template:
            return "Give a template or sections"
        sections = ar.template_sections(template)
    if section_slots:
        for sec in sections:
            over = section_slots.get(sec["name"])
            if over:
                sec["slots"] = {int(k): int(v) for k, v in over.items()}
    ableton = live.client()
    tracks = _session_tracks(ableton)
    roles = ar.infer_track_roles(tracks)
    for k, v in (track_roles or {}).items():
        roles[int(k)] = v
    info = ableton.call("get_session_info")
    bpb = float(info.get("signature_numerator", 4)) * 4.0 / float(info.get("signature_denominator", 4))
    plan = ar.plan_arrangement(sections, tracks, roles, beats_per_bar=bpb, start_bar=start_bar,
                               default_slot=default_slot)
    summary = {"track_roles": {tracks[i]["name"]: r for i, r in roles.items() if i < len(tracks)},
               "sections": plan["sections"], "total_bars": plan["total_bars"],
               "placements": len(plan["placements"]), "warnings": plan["warnings"]}
    unassigned = [t["name"] for t in tracks if t["index"] not in roles and t["slots"]]
    if unassigned:
        summary["tracks_without_role"] = unassigned
    if dry_run:
        summary["dry_run"] = True
        return as_json(summary)
    if ableton.call("get_session_info").get("is_playing"):
        ableton.call("stop_playback")
    for p in plan["placements"]:
        ableton.call("duplicate_session_clip_to_arrangement", {
            "track_index": p["track_index"], "clip_index": p["clip_index"],
            "destination_time": p["start"]})
    made = 0
    if locators:
        if live.supports("create_locator"):
            for loc in plan["locators"]:
                try:
                    ableton.call("create_locator", {"name": loc["name"], "time": loc["beat"]})
                    made += 1
                except Exception as e:
                    summary.setdefault("warnings", []).append("locator %s: %s" % (loc["name"], e))
    summary["locators_created"] = made
    return as_json(summary)


@tool()
def arrangement_overview(block_bars: int = 8) -> str:
    """
    A map of the Arrangement: for every track, one character per block of
    `block_bars` bars ('#' = a clip plays, '.' = silent), so the structure,
    the entries and exits of each element and the phrasing are visible at a
    glance.

    Parameters:
    - block_bars: Bars per character (default 8)
    """
    from .. import arrangement as ar

    ableton = live.client()
    info = ableton.call("get_session_info")
    bpb = float(info.get("signature_numerator", 4)) * 4.0 / float(info.get("signature_denominator", 4))
    clips_by_track, end = {}, 0.0
    for i in range(int(info.get("track_count", 0))):
        data = ableton.call("get_arrangement_clips", {"track_index": i})
        clips = data.get("clips", [])
        clips_by_track["%d %s" % (i, data.get("track_name", ""))] = clips
        for c in clips:
            end = max(end, float(c["end_time"]))
    rows = ar.activity_map(clips_by_track, block_bars * bpb, end)
    blocks = len(next(iter(rows.values()), ""))
    return as_json({"block_bars": block_bars, "length_bars": round(end / bpb, 2),
                  "block_start_bars": [1 + b * block_bars for b in range(blocks)],
                  "tracks": rows})
