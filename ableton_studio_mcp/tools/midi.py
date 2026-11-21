"""Importing standard MIDI files into clips."""

from __future__ import annotations

import json
import logging
import math
import os

from .. import live
from ..app import clip_target, tool, write_notes

log = logging.getLogger("ableton_studio_mcp")



@tool(undo_step="Import MIDI file")
def import_midi_file(file_path: str,
    track_index: int = None,
    clip_index: int = 0,
    midi_track: int = None,
    channel: int = None,
    transpose: int = 0,
    location: str = "session",
    replace: bool = False,
    clip_length: float = None,
) -> str:
    """
    Import the notes of a Standard MIDI File (.mid) into a clip. Without
    track_index, only describes the file (tracks, note counts, channels,
    length) so you can pick midi_track / channel first.

    Session: an empty slot gets a new clip as long as the notes (rounded up to
    a 4-beat bar) or clip_length; an existing clip receives the notes (after
    clearing it when replace=True). Arrangement: the clip must exist
    (index from get_arrangement_clips). Times are in beats; the file's tempo
    is ignored.

    Parameters:
    - file_path: Absolute path of the .mid file
    - track_index: Target MIDI track (omit to only describe the file)
    - clip_index: Session slot, or Arrangement clip index
    - midi_track: Track of the MIDI file to import (default: all, merged)
    - channel: MIDI channel to keep, 0-15 (default: all)
    - transpose: Semitones to add to every pitch
    - location: "session" (default) or "arrangement"
    - replace: Clear the target clip's notes first
    - clip_length: Length in beats of a newly created Session clip
    """
    from ..midi_file import merge_duplicates, read_midi_file, select_notes, summarize

    path = os.path.expanduser(file_path)
    parsed = read_midi_file(path)
    if track_index is None:
        return json.dumps({"file": path, "format": parsed["format"],
                           "ticks_per_beat": parsed["division"],
                           "tracks": summarize(parsed)}, indent=2, ensure_ascii=False)
    notes = select_notes(parsed, midi_track=midi_track, channel=channel,
                         transpose=transpose)
    if not notes:
        return "No notes to import with these filters"
    notes, merged = merge_duplicates(notes)
    location = (location or "session").lower()
    ableton = live.client()
    created = False
    if location == "session":
        info = ableton.call("get_track_info", {"track_index": track_index})
        slots = info.get("clip_slots", [])
        if clip_index < 0 or clip_index >= len(slots):
            return f"Clip slot {clip_index} out of range ({len(slots)} slots)"
        if not slots[clip_index].get("has_clip"):
            end = max(n["start_time"] + n["duration"] for n in notes)
            length = clip_length or max(4.0, 4.0 * math.ceil(end / 4.0 - 1e-9))
            ableton.call("create_clip", {"track_index": track_index,
                                                 "clip_index": clip_index,
                                                 "length": length})
            created = True
    if replace and not created:
        ableton.call("clear_notes_from_clip",
                             clip_target(track_index, clip_index, location))
    write_notes(track_index, clip_index, notes, location)
    where = (f"new clip in slot {clip_index}" if created
             else f"{location} clip {clip_index}")
    return (f"Imported {len(notes)} notes from {os.path.basename(path)} into "
            f"{where} on track {track_index}"
            + (" (replaced existing notes)" if replace and not created else "")
            + (f"; {merged} duplicate note(s) (same pitch and start in two voices) "
               f"merged, as Live keeps one" if merged else ""))
