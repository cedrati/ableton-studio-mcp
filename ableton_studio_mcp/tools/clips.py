"""Clips: creating them, their notes, launching, loop and markers, warp,
automation envelopes, and placing them in the Arrangement."""

from __future__ import annotations

from typing import Dict, List, Union

from .. import live
from ..app import as_json, clip_target, compact, describe_clip, tool

Note = Dict[str, Union[int, float, bool]]


# ── creating and naming ──────────────────────────────────────────────────────

@tool()
def create_clip(track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Make an empty MIDI clip in a Session slot (the slot must be empty).

    Parameters:
    - track_index: A MIDI track
    - clip_index: The Session slot (scene row)
    - length: Clip length in beats (default 4 = one bar in 4/4)
    """
    live.call("create_clip", {"track_index": track_index, "clip_index": clip_index, "length": length})
    return f"{length}-beat MIDI clip created in slot {clip_index} on track {track_index}"


@tool()
def create_audio_clip(track_index: int, clip_index: int, path: str) -> str:
    """
    Put an audio file into an empty Session slot of an audio track
    (Live 12.0.5 or newer).

    Parameters:
    - track_index: An audio track
    - clip_index: The Session slot (must be empty)
    - path: Absolute path of the file (.wav, .aif, .mp3...)
    """
    reply = live.call("create_audio_clip", {"track_index": track_index, "clip_index": clip_index, "path": path})
    return (f"Audio clip '{reply.get('name', 'clip')}' ({reply.get('length', '?')} beats) "
            f"in slot {clip_index} on track {track_index}")


@tool()
def set_clip_name(track_index: int, clip_index: int, name: str) -> str:
    """
    Rename a Session clip.

    Parameters:
    - track_index: The track
    - clip_index: The Session slot
    - name: Its new name
    """
    live.call("set_clip_name", {"track_index": track_index, "clip_index": clip_index, "name": name})
    return f"Clip in slot {clip_index} on track {track_index} renamed '{name}'"


@tool()
def set_arrangement_clip_name(track_index: int, clip_index: int, name: str) -> str:
    """
    Rename a clip in the Arrangement.

    Parameters:
    - track_index: The track
    - clip_index: Position of the clip in get_arrangement_clips (ordered by start time)
    - name: Its new name
    """
    live.call("set_arrangement_clip_name", {"track_index": track_index, "clip_index": clip_index, "name": name})
    return f"Arrangement clip {clip_index} on track {track_index} renamed '{name}'"


@tool(needs="delete_clip")
def delete_clip(track_index: int, clip_index: int) -> str:
    """
    Empty a Session slot (create_clip refuses occupied slots).

    Parameters:
    - track_index: The track
    - clip_index: The Session slot to empty
    """
    return as_json(live.call("delete_clip", {"track_index": track_index, "clip_index": clip_index}))


@tool(needs="delete_arrangement_clip")
def delete_arrangement_clip(track_index: int, clip_index: int) -> str:
    """
    Remove a clip from the Arrangement. Later clips on the track move down one index.

    Parameters:
    - track_index: The track
    - clip_index: Position of the clip in get_arrangement_clips
    """
    return as_json(live.call("delete_arrangement_clip", {"track_index": track_index, "clip_index": clip_index}))


# ── launching ────────────────────────────────────────────────────────────────

@tool()
def fire_clip(track_index: int, clip_index: int) -> str:
    """
    Launch a Session clip.

    Parameters:
    - track_index: The track
    - clip_index: The Session slot
    """
    live.call("fire_clip", {"track_index": track_index, "clip_index": clip_index})
    return f"Launched slot {clip_index} on track {track_index}"


@tool()
def stop_clip(track_index: int, clip_index: int) -> str:
    """
    Stop a playing Session clip.

    Parameters:
    - track_index: The track
    - clip_index: The Session slot
    """
    live.call("stop_clip", {"track_index": track_index, "clip_index": clip_index})
    return f"Stopped slot {clip_index} on track {track_index}"


# ── notes ────────────────────────────────────────────────────────────────────

@tool(needs="get_clip_notes")
def get_clip_notes(track_index: int, clip_index: int, location: str = "session") -> str:
    """
    All the MIDI notes of a clip: pitch, start_time, duration, velocity, mute
    (plus probability and velocity deviation when Live has them). Times are
    in beats from the clip start. For an Arrangement clip the reply also has
    arrangement_start / arrangement_end and start_marker: without looping, a
    note sounds at arrangement_start + (start_time − start_marker).

    Parameters:
    - track_index: The track
    - clip_index: Session slot, or position in get_arrangement_clips
    - location: "session" (default) or "arrangement"
    """
    return as_json(live.call("get_clip_notes", clip_target(track_index, clip_index, location)))


@tool()
def add_notes_to_clip(track_index: int, clip_index: int, notes: List[Note], location: str = "session") -> str:
    """
    Add notes to a clip; existing notes stay. To replace notes, clear the
    clip (clear_notes_from_clip) or a range (remove_notes) first.

    Parameters:
    - track_index: The track
    - clip_index: Session slot, or position in get_arrangement_clips
    - notes: [{"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100, "mute": false}, ...]
      with start_time in beats from the clip start
    - location: "session" (default) or "arrangement"
    """
    live.call("add_notes_to_clip", clip_target(track_index, clip_index, location, notes=notes))
    return f"{len(notes)} note(s) added to {describe_clip(track_index, clip_index, location)}"


@tool(needs="clear_notes_from_clip")
def clear_notes_from_clip(track_index: int, clip_index: int, location: str = "session") -> str:
    """
    Remove every note from a clip. Together with get_clip_notes and
    add_notes_to_clip this gives read → edit → write: read the notes, change
    the list, clear the clip, add the new list. For part of a clip use remove_notes.

    Parameters:
    - track_index: The track
    - clip_index: Session slot, or position in get_arrangement_clips
    - location: "session" (default) or "arrangement"
    """
    reply = live.call("clear_notes_from_clip", clip_target(track_index, clip_index, location))
    return (f"Removed {reply.get('cleared_count', '?')} note(s) from '{reply.get('clip_name', 'clip')}' "
            f"({describe_clip(track_index, clip_index, location)})")


@tool(needs="remove_notes")
def remove_notes(track_index: int, clip_index: int, from_time: float = 0.0,
                 time_span: Union[float, None] = None, from_pitch: int = 0,
                 pitch_span: int = 128, location: str = "session") -> str:
    """
    Remove only the notes starting inside a time window and a pitch range —
    to rewrite one bar, or one drum lane, then add the new notes.

    Parameters:
    - track_index: The track
    - clip_index: Session slot, or position in get_arrangement_clips
    - from_time: Window start, in beats from the clip start
    - time_span: Window length in beats (default: until the clip end)
    - from_pitch: Lowest pitch of the range (0–127)
    - pitch_span: How many pitches from from_pitch (128 = all, 1 = just that note)
    - location: "session" (default) or "arrangement"
    """
    params = clip_target(track_index, clip_index, location, **compact(
        from_time=from_time, time_span=time_span, from_pitch=from_pitch, pitch_span=pitch_span))
    return as_json(live.call("remove_notes", params))


# ── Arrangement ──────────────────────────────────────────────────────────────

@tool()
def get_arrangement_clips(track_index: int) -> str:
    """
    The clips a track has in the Arrangement, in time order, with their
    position, length and type. Their order is the clip_index other tools use.

    Parameters:
    - track_index: The track
    """
    return as_json(live.call("get_arrangement_clips", {"track_index": track_index}))


@tool()
def duplicate_to_arrangement(track_index: int, clip_index: int, destination_time: float) -> str:
    """
    Copy a Session clip into the Arrangement, on the same track. Repeat the
    call for every place the clip should play, then switch_to_arrangement_view
    to look at the result.

    Parameters:
    - track_index: The track holding the Session clip
    - clip_index: Its Session slot
    - destination_time: Song position in beats where the copy starts
    """
    reply = live.call("duplicate_session_clip_to_arrangement", {
        "track_index": track_index, "clip_index": clip_index, "destination_time": destination_time})
    return (f"'{reply.get('clip_name', 'clip')}' copied from slot {clip_index} of "
            f"'{reply.get('track_name', f'track {track_index}')}' to beat {destination_time}")


# ── loop and markers ─────────────────────────────────────────────────────────

@tool(needs="get_clip_loop")
def get_clip_loop(track_index: int, clip_index: int, location: str = "session") -> str:
    """
    A clip's loop switch, loop brace and start/end markers, and what actually
    plays. Beats, except seconds for an unwarped audio clip ("units" says
    which). Arrangement clips also report their place in the song.

    Parameters:
    - track_index: The track
    - clip_index: Session slot, or position in get_arrangement_clips
    - location: "session" (default) or "arrangement"
    """
    return as_json(live.call("get_clip_loop", clip_target(track_index, clip_index, location)))


@tool(needs="set_clip_loop")
def set_clip_loop(track_index: int, clip_index: int, location: str = "session",
                  looping: Union[bool, None] = None, loop_start: Union[float, None] = None,
                  loop_end: Union[float, None] = None, loop_length: Union[float, None] = None,
                  start_marker: Union[float, None] = None, end_marker: Union[float, None] = None) -> str:
    """
    Change a clip's loop and markers; anything left out stays as it is.

    With looping on, playback starts at start_marker and then repeats the
    brace (loop_start → loop_end); e.g. keep only the first bar of a 4-bar
    loop with loop_start=0, loop_length=4. With looping off Live plays
    loop_start → loop_end once, so markers given for such a clip are written
    to the brace. The writes are ordered so the start never passes the end;
    the reply shows what Live applied and lists any value it "adjusted".
    Switching warping off and on again resets an audio clip's warp markers.

    Parameters:
    - track_index: The track
    - clip_index: Session slot, or position in get_arrangement_clips
    - location: "session" (default) or "arrangement"
    - looping: Loop switch
    - loop_start, loop_end: The brace (beats; seconds for unwarped audio)
    - loop_length: Alternative to loop_end: loop_end = loop_start + loop_length
    - start_marker, end_marker: Where playback starts and ends
    """
    params = clip_target(track_index, clip_index, location, **compact(
        looping=looping, loop_start=loop_start, loop_end=loop_end, loop_length=loop_length,
        start_marker=start_marker, end_marker=end_marker))
    return as_json(live.call("set_clip_loop", params))


# ── warp (audio clips) ───────────────────────────────────────────────────────

@tool(needs="get_clip_warp")
def get_clip_warp(track_index: int, clip_index: int, location: str = "session") -> str:
    """
    An audio clip's warp state: warping, warp mode (and the modes on offer),
    warp markers (beat_time ↔ sample_time in seconds), transposition, gain,
    clip length and file duration.

    Parameters:
    - track_index: The track
    - clip_index: Session slot, or position in get_arrangement_clips
    - location: "session" (default) or "arrangement"
    """
    return as_json(live.call("get_clip_warp", clip_target(track_index, clip_index, location)))


@tool(needs="set_clip_warp")
def set_clip_warp(track_index: int, clip_index: int, location: str = "session",
                  warping: Union[bool, None] = None, warp_mode: Union[str, None] = None,
                  original_bpm: Union[float, None] = None, pitch_coarse: Union[int, None] = None,
                  pitch_fine: Union[float, None] = None, gain: Union[float, None] = None) -> str:
    """
    Change an audio clip's warp settings; anything left out stays as it is.
    Give a loop's own tempo as original_bpm (sample names often carry it,
    "..._131_...") and it follows the song tempo: warping goes on and the warp
    markers are rebuilt for that tempo.

    Parameters:
    - track_index: An audio track
    - clip_index: Session slot, or position in get_arrangement_clips
    - location: "session" (default) or "arrangement"
    - warping: Warp on or off
    - warp_mode: "beats" (drums), "tones" (monophonic), "texture",
      "re_pitch" (vinyl-like), "complex" / "complex_pro" (full mixes), or 0–6
    - original_bpm: The loop's own tempo
    - pitch_coarse: Transposition in semitones (−48…48)
    - pitch_fine: Detune in cents (−50…50)
    - gain: Clip gain 0.0–1.0 (the reply shows it in dB)
    """
    params = clip_target(track_index, clip_index, location, **compact(
        warping=warping, warp_mode=warp_mode, original_bpm=original_bpm,
        pitch_coarse=pitch_coarse, pitch_fine=pitch_fine, gain=gain))
    return as_json(live.call("set_clip_warp", params))


@tool(needs="edit_warp_markers")
def edit_warp_markers(track_index: int, clip_index: int, location: str = "session",
                      add: Union[List[Dict[str, float]], None] = None,
                      move: Union[List[Dict[str, float]], None] = None,
                      remove: Union[List[float], None] = None) -> str:
    """
    Edit the warp markers of a warped audio clip (Live 11+), in this order:
    remove, then move, then add. get_clip_warp shows the current ones.

    Parameters:
    - track_index: An audio track
    - clip_index: Session slot, or position in get_arrangement_clips
    - location: "session" (default) or "arrangement"
    - add: [{"beat_time": 8.0, "sample_time": 3.66}] pins a moment of the file (seconds) to a beat
    - move: [{"beat_time": 8.0, "beat_time_distance": 0.25}] shifts that marker by some beats
    - remove: [8.0, 16.0] beat times of markers to delete
    """
    params = clip_target(track_index, clip_index, location, **compact(add=add, move=move, remove=remove))
    return as_json(live.call("edit_warp_markers", params))


# ── automation envelopes ─────────────────────────────────────────────────────

@tool(needs="set_clip_automation")
def set_clip_automation(track_index: int, clip_index: int, points: List[Dict[str, float]],
                        location: str = "session", device_index: int = -1, parameter_index: int = 0,
                        mixer_parameter: str = "", interpolation: str = "linear",
                        resolution: float = 0.25, clear_first: bool = True) -> str:
    """
    Draw an automation envelope inside a Session clip; it plays whenever the
    clip plays. (Live's API does not allow writing envelopes in Arrangement
    clips or the Arrangement's automation lanes.) Target a device parameter
    (device_index + parameter_index, see get_device_parameters) or a mixer
    control (mixer_parameter).

    Parameters:
    - track_index: The track holding the clip and the parameter
    - clip_index: The Session slot
    - points: [{"time": 0, "value": 0.2}, {"time": 16, "value": 0.9}] — time in
      beats from the clip start, value in the parameter's own range (clamped);
      the last value holds to the clip end. [] with clear_first removes the envelope.
    - location: "session" (the only place Live accepts)
    - device_index: Device in the chain (ignored with mixer_parameter)
    - parameter_index: Parameter of that device
    - mixer_parameter: "volume", "panning" or "send:N" (N = return index)
    - interpolation: "linear" (ramps drawn in steps of `resolution`) or "step"
    - resolution: Ramp step in beats (0.25 = a sixteenth)
    - clear_first: Erase this parameter's envelope in the clip first
    """
    return as_json(live.call("set_clip_automation", {
        "track_index": track_index, "clip_index": clip_index, "location": location,
        "device_index": device_index, "parameter_index": parameter_index,
        "mixer_parameter": mixer_parameter, "points": points,
        "interpolation": interpolation, "resolution": resolution, "clear_first": clear_first}))


@tool(needs="get_clip_automation")
def get_clip_automation(track_index: int, clip_index: int, location: str = "session",
                        device_index: int = -1, parameter_index: int = 0,
                        mixer_parameter: str = "", resolution: float = 1.0) -> str:
    """
    Read a clip's envelope for one parameter, sampled every `resolution`
    beats; has_envelope=false when that parameter isn't automated in the clip.

    Parameters:
    - track_index, clip_index, location: as for set_clip_automation
    - device_index, parameter_index, mixer_parameter: as for set_clip_automation
    - resolution: Sampling step in beats (default 1)
    """
    return as_json(live.call("get_clip_automation", {
        "track_index": track_index, "clip_index": clip_index, "location": location,
        "device_index": device_index, "parameter_index": parameter_index,
        "mixer_parameter": mixer_parameter, "resolution": resolution}))
