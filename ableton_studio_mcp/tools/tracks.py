"""Tracks and the mixer: creating, naming, faders, sends, mute, solo, arm."""

from __future__ import annotations

from .. import live
from ..app import as_json, tool, track_target


@tool()
def get_track_info(track_index: int, track_type: str = "track") -> str:
    """
    One track in detail: name, mixer state, clip slots and device chain. Works
    for return tracks and the main track too.

    Parameters:
    - track_index: The track (for "return", its position among returns; ignored for "master")
    - track_type: "track" (default), "return" or "master"
    """
    return as_json(live.call("get_track_info", track_target(track_index, track_type)))


@tool()
def create_midi_track(index: int = -1) -> str:
    """
    Add a MIDI track (for instruments and drum racks).

    Parameters:
    - index: Where to insert it (-1 = after the last track)
    """
    reply = live.call("create_midi_track", {"index": index})
    return f"MIDI track '{reply.get('name', '?')}' created at index {reply.get('index', index)}"


@tool()
def create_audio_track(index: int = -1) -> str:
    """
    Add an audio track (for samples, stems, recordings).

    Parameters:
    - index: Where to insert it (-1 = after the last track)
    """
    reply = live.call("create_audio_track", {"index": index})
    return f"Audio track '{reply.get('name', '?')}' created at index {reply.get('index', index)}"


@tool()
def set_track_name(track_index: int, name: str) -> str:
    """
    Rename a track.

    Parameters:
    - track_index: The track to rename
    - name: Its new name
    """
    reply = live.call("set_track_name", {"track_index": track_index, "name": name})
    return f"Track {track_index} is now '{reply.get('name', name)}'"


@tool(needs="delete_track")
def delete_track(track_index: int) -> str:
    """
    Remove a track and everything on it. Ask the user first. Tracks after it
    move up one index.

    Parameters:
    - track_index: The track to remove
    """
    return as_json(live.call("delete_track", {"track_index": track_index}))


@tool(needs="duplicate_track")
def duplicate_track(track_index: int) -> str:
    """
    Copy a track with its clips and devices; the copy goes right after it.

    Parameters:
    - track_index: The track to copy
    """
    return as_json(live.call("duplicate_track", {"track_index": track_index}))


# ── mixer ────────────────────────────────────────────────────────────────────

def _mixer(command: str, track_index: int, track_type: str, **values) -> str:
    return as_json(live.call(command, {"track_index": track_index, "track_type": track_type, **values}))


@tool(needs="set_track_volume")
def set_track_volume(track_index: int, volume: float, track_type: str = "track") -> str:
    """
    Move a track's fader.

    Parameters:
    - track_index: The track (ignored for "master")
    - volume: Fader position 0.0–1.0 (0.85 is 0 dB, 0.0 is silence)
    - track_type: "track" (default), "return" or "master"
    """
    return _mixer("set_track_volume", track_index, track_type, volume=volume)


@tool(needs="set_track_panning")
def set_track_panning(track_index: int, panning: float, track_type: str = "track") -> str:
    """
    Pan a track.

    Parameters:
    - track_index: The track (ignored for "master")
    - panning: -1.0 hard left, 0.0 centre, 1.0 hard right
    - track_type: "track" (default), "return" or "master"
    """
    return _mixer("set_track_panning", track_index, track_type, panning=panning)


@tool(needs="set_track_send")
def set_track_send(track_index: int, send_index: int, value: float, track_type: str = "track") -> str:
    """
    Set how much of a track goes to a return track.

    Parameters:
    - track_index: The sending track
    - send_index: Which send (0 = A, the first return track)
    - value: Send amount 0.0–1.0
    - track_type: "track" (default) or "return"
    """
    return _mixer("set_track_send", track_index, track_type, send_index=send_index, value=value)


@tool(needs="set_track_mute")
def set_track_mute(track_index: int, mute: bool, track_type: str = "track") -> str:
    """
    Mute or unmute a track.

    Parameters:
    - track_index: The track
    - mute: true mutes, false unmutes
    - track_type: "track" (default) or "return"
    """
    return _mixer("set_track_mute", track_index, track_type, mute=mute)


@tool(needs="set_track_solo")
def set_track_solo(track_index: int, solo: bool, track_type: str = "track") -> str:
    """
    Solo or unsolo a track.

    Parameters:
    - track_index: The track
    - solo: true solos, false unsolos
    - track_type: "track" (default) or "return"
    """
    return _mixer("set_track_solo", track_index, track_type, solo=solo)


@tool(needs="set_track_arm")
def set_track_arm(track_index: int, arm: bool) -> str:
    """
    Arm a track for recording, or disarm it.

    Parameters:
    - track_index: The track
    - arm: true arms, false disarms
    """
    return as_json(live.call("set_track_arm", {"track_index": track_index, "arm": arm}))
