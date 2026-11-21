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


@tool(undo_step="Write clip evolution")
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


@tool(undo_step="Automation gesture")
def automation_gesture(track_index: int,
    clip_index: int,
    gesture: str,
    target: str = None,
    rest: float = None,
    peak: float = None,
    low: float = None,
    phrase_bars: int = 4,
    tail_beats: float = 1.0,
    protect: str = "auto",
) -> str:
    """
    Draw a producer's automation move in a Session clip, aimed at the right
    parameter automatically:

    - delay_throw: the delay send jumps up on the last beat(s) of each phrase
    - reverb_swell: the reverb send rises and falls back over the clip
    - filter_rise / filter_fall: the track's filter opens (build-up) or closes
    - drop_cut: silence on the last beat(s), the breath before a drop
    - stutter: volume gated in 16ths on the last beat(s)
    - fade_in / fade_out: volume from / to silence

    The send gestures find the return named like a delay (delay, echo) or a
    reverb (reverb, verb, hall, room...); the filter gestures the track's
    cutoff (Auto Filter first, then the synth's own filter). The parameter's
    current value is the resting value the move starts from and comes back to.

    Live leaves a parameter where a clip's envelope ends, and a clip without
    an envelope doesn't reset it. When the move ends away from the resting
    value (drop_cut, filter_fall, fade_out), the track's other clips get the
    resting value held, or the next section would stay silent or filtered.
    Rebuild the Arrangement (build_arrangement) afterwards: its clips are
    copies.

    Parameters:
    - track_index / clip_index: The Session clip
    - gesture: One of the moves above
    - target: Override the parameter: "send:N" (return N) or "device:D:P"
    - rest / peak / low: Override the resting, high and low values (parameter units)
    - phrase_bars: Phrase length for delay_throw (default 4 bars)
    - tail_beats: Length of the throw, cut or stutter at the end (default 1 beat)
    - protect: "auto" (hold the resting value on the other clips when needed),
      "yes" or "no"
    """
    from .. import gestures as g

    kind = g.gesture_target(gesture)
    ableton = live.client()
    snap = ableton.call("get_session_snapshot", {"include_notes": False, "include_params": False})
    tracks = snap.get("tracks", [])
    if not 0 <= track_index < len(tracks):
        return "There is no track %d" % track_index
    track = tracks[track_index]
    slots = [s for s in track.get("clip_slots", []) if s.get("has_clip")]
    clip = next((s["clip"] for s in slots if s["index"] == clip_index), None)
    if clip is None:
        return "Slot %d of '%s' is empty" % (clip_index, track.get("name"))
    length = float(clip.get("length") or 0.0)

    param: Dict[str, Any] = {"device_index": -1, "parameter_index": 0, "mixer_parameter": ""}
    lo = 0.0
    if target and target.startswith("send:") or (not target and kind == "send"):
        if target:
            send = int(target.split(":")[1])
        else:
            words = g.DELAY_WORDS if gesture == "delay_throw" else g.REVERB_WORDS
            send = g.find_return([r.get("name", "") for r in snap.get("return_tracks", [])], words)
            if send is None:
                return ("No return track named like a %s; give target='send:N'"
                        % ("delay" if gesture == "delay_throw" else "reverb"))
        sends = track.get("sends", [])
        if not 0 <= send < len(sends):
            return "'%s' has no send %d" % (track.get("name"), send)
        param["mixer_parameter"] = "send:%d" % send
        current = float(sends[send]["value"])
        label = sends[send].get("name") or "send %d" % send
        r = current if rest is None else float(rest)
        default_peak = 0.9 if gesture == "delay_throw" else min(1.0, r + 0.3)
        p = default_peak if peak is None else float(peak)
        lw = 0.0 if low is None else float(low)
    elif target and target.startswith("device:") or (not target and kind == "filter"):
        if target:
            _, d, i = target.split(":")
            found = _parameter(ableton, track_index, int(d), int(i))
        else:
            found = _find_cutoff(ableton, track_index, track.get("devices", []))
        if found is None:
            return ("No filter cutoff found on '%s' (Auto Filter, or a synth's filter); "
                    "give target='device:D:P'" % track.get("name"))
        param["device_index"], param["parameter_index"] = found["device_index"], found["index"]
        lo, current, label = float(found["min"]), float(found["value"]), found["name"]
        r = current if rest is None else float(rest)
        lw = lo + 0.3 * (r - lo) if low is None else float(low)
        p = r if peak is None else float(peak)
    else:
        param["mixer_parameter"] = "volume"
        current, label = float(track.get("volume", 0.85)), "Volume"
        r = current if rest is None else float(rest)
        lw = 0.0 if low is None else float(low)
        p = r if peak is None else float(peak)

    drawn = g.gesture_points(gesture, length, rest=r, peak=p, low=lw,
                             phrase_beats=float(phrase_bars) * 4.0, tail_beats=tail_beats)
    ableton.call("set_clip_automation", dict(param, track_index=track_index, clip_index=clip_index,
                 location="session", points=drawn["points"], interpolation=drawn["interpolation"],
                 resolution=0.125 if drawn["interpolation"] == "step" else 0.5, clear_first=True))
    report = {"gesture": gesture, "clip": "%s, slot %d" % (track.get("name"), clip_index),
              "parameter": label, "rest": r, "points": len(drawn["points"]),
              "clip_length_beats": length}

    ends_elsewhere = abs(drawn["end_value"] - r) > 1e-6
    others = [s["index"] for s in slots if s["index"] != clip_index]
    bare = [i for i in others if not ableton.call("get_clip_automation", dict(
        param, track_index=track_index, clip_index=i, location="session")).get("has_envelope")]
    hold = protect == "yes" or (protect == "auto" and ends_elsewhere)
    if hold and bare:
        for i in bare:
            ableton.call("set_clip_automation", dict(param, track_index=track_index, clip_index=i,
                         location="session", points=[{"time": 0.0, "value": r}],
                         interpolation="step", resolution=1.0, clear_first=True))
        report["held_at_rest"] = {"slots": bare, "value": r,
                                  "why": "this move ends away from the resting value; these clips "
                                         "now bring it back when they play"}
    elif ends_elsewhere and bare:
        report["warning"] = ("This move ends at %g; clips %s have no envelope for it and will "
                             "start there. Use protect='yes' to hold %g on them." % (drawn["end_value"], bare, r))
    report["next"] = "Rebuild the Arrangement (build_arrangement) to carry this into it."
    return as_json(report)


def _parameter(ableton, track_index: int, device_index: int, parameter_index: int) -> Dict[str, Any] | None:
    dev = ableton.call("get_device_parameters", {"track_index": track_index,
                                                 "device_index": device_index}).get("device", {})
    for prm in dev.get("parameters", []):
        if int(prm.get("index", -1)) == parameter_index:
            return dict(prm, device_index=device_index)
    return None


def _find_cutoff(ableton, track_index: int, devices: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    """The track's filter cutoff: an Auto Filter first, then a synth's filter."""
    from .. import gestures as g

    def is_auto_filter(d):
        return "AutoFilter" in str(d.get("class_name", ""))

    for dev in sorted(devices, key=lambda d: 0 if is_auto_filter(d) else 1):
        di = int(dev["index"])
        params = ableton.call("get_device_parameters", {"track_index": track_index,
                                                        "device_index": di}).get("device", {}).get("parameters", [])
        by_name = {p.get("name"): p for p in params}
        if is_auto_filter(dev):
            kind = str(by_name.get("Filter Type", {}).get("display", ""))
            if "High" in kind:          # a high-pass cleaning the lows, not the sound's filter
                continue
        for name in g.CUTOFF_NAMES:
            if name == "Frequency" and not is_auto_filter(dev):
                continue                # Corpus, EQs... have a "Frequency" too
            if name in by_name:
                return dict(by_name[name], device_index=di)
    return None


def _session_tracks(ableton) -> List[Dict[str, Any]]:
    count = int(ableton.call("get_session_info").get("track_count", 0))
    tracks = []
    for i in range(count):
        info = ableton.call("get_track_info", {"track_index": i})
        slots = {s["index"]: float(s["clip"]["length"]) for s in info.get("clip_slots", [])
                 if s.get("has_clip") and s.get("clip")}
        tracks.append({"index": i, "name": info.get("name", ""), "slots": slots})
    return tracks


def _clips_in_range(ableton, tracks: List[Dict[str, Any]], start: float,
                    end: float) -> Dict[int, List[Dict[str, Any]]]:
    """{track_index: [{"index", "start_time"}]} for the Arrangement clips
    that start in [start, end)."""
    found = {}
    for t in tracks:
        clips = ableton.call("get_arrangement_clips", {"track_index": t["index"]}).get("clips", [])
        hits = [{"index": i, "start_time": float(c["start_time"])} for i, c in enumerate(clips)
                if start - 1e-6 <= float(c["start_time"]) < end - 1e-6]
        if hits:
            found[t["index"]] = hits
    return found


def _delete_clips(ableton, existing: Dict[int, List[Dict[str, Any]]]) -> int:
    """Delete them, last first so the earlier indexes stay valid."""
    removed = 0
    for ti, hits in existing.items():
        for h in reversed(hits):
            ableton.call("delete_arrangement_clip", {"track_index": ti, "clip_index": h["index"]})
            removed += 1
    return removed


def _crop_arrangement_clip(ableton, track_index: int, start: float, length: float) -> None:
    """Shorten the Arrangement clip that starts at `start` to `length` beats.

    Measured in Live 12.4: an Arrangement clip's length follows its loop
    brace once looping is off, so the copy is unlooped and its brace set to
    `length` from where it starts playing.
    """
    clips = ableton.call("get_arrangement_clips", {"track_index": track_index}).get("clips", [])
    index = next((i for i, c in enumerate(clips) if abs(float(c["start_time"]) - start) < 1e-6), None)
    if index is None:
        raise RuntimeError("no clip found at that position after the copy")
    ableton.call("set_clip_loop", {"track_index": track_index, "clip_index": index,
                                   "location": "arrangement", "looping": False,
                                   "loop_length": float(length)})


@tool(undo_step="Build arrangement")
def build_arrangement(template: str = None,
    sections: List[Dict[str, Any]] = None,
    track_roles: Dict[str, str] = None,
    start_bar: int = 0,
    default_slot: int = 0,
    section_slots: Dict[str, Dict[str, int]] = None,
    locators: bool = True,
    dry_run: bool = False,
    clear: bool = False,
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
    - clear: Delete the Arrangement clips already in the rebuilt range first
      (default false). Copies only overwrite where they land, so without it
      older clips stay where a track no longer plays; `existing_clips` lists
      them. Deleting is the artist's call: show the list and ask before
      passing clear=true.

    A clip that doesn't divide its section (or is longer than it) is placed
    once more and cropped at the section's end; `cropped` lists them.
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
    if plan.get("cropped"):
        summary["cropped"] = plan["cropped"]
    unassigned = [t["name"] for t in tracks if t["index"] not in roles and t["slots"]]
    if unassigned:
        summary["tracks_without_role"] = unassigned
    existing = _clips_in_range(ableton, tracks, start_bar * bpb, plan["end_beat"])
    if existing and not clear:
        summary["existing_clips"] = {
            "count": sum(len(v) for v in existing.values()),
            "per_track": {tracks[ti]["name"]: [c["start_time"] for c in v] for ti, v in existing.items()},
            "note": "Already in this range and kept: copies overwrite only where they land. "
                    "Ask the artist before rebuilding with clear=true, which deletes them."}
    if dry_run:
        summary["dry_run"] = True
        return as_json(summary)
    if ableton.call("get_session_info").get("is_playing"):
        ableton.call("stop_playback")
    if clear:
        summary["cleared"] = _delete_clips(ableton, existing)
    for p in plan["placements"]:
        ableton.call("duplicate_session_clip_to_arrangement", {
            "track_index": p["track_index"], "clip_index": p["clip_index"],
            "destination_time": p["start"]})
        if p.get("length"):
            try:
                _crop_arrangement_clip(ableton, p["track_index"], p["start"], p["length"])
            except Exception as e:      # the copy stays whole: say so
                summary["warnings"].append("track %d at beat %g: could not crop the clip to %g beats (%s)"
                                           % (p["track_index"], p["start"], p["length"], e))
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
