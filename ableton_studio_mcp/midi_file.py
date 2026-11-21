"""Minimal Standard MIDI File reader (no dependency).

Reads format 0 and 1 files with a ticks-per-quarter-note division and returns
notes in beats (quarter notes), ready for add_notes_to_clip. Tempo changes are
ignored on purpose: Live clip time is in beats, so a note's beat position does
not depend on the tempo.
"""

import struct
from typing import Dict, List, Optional


class MidiFileError(ValueError):
    """The file is not a MIDI file this reader handles."""


def _read_vlq(data: bytes, i: int):
    value = 0
    while True:
        if i >= len(data):
            raise MidiFileError("Truncated variable-length quantity")
        b = data[i]
        i += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, i


def _parse_track(data: bytes, division: int, track_number: int) -> Dict:
    i, ticks, running = 0, 0, None
    open_notes: Dict[tuple, List[tuple]] = {}
    notes, name = [], None
    while i < len(data):
        delta, i = _read_vlq(data, i)
        ticks += delta
        status = data[i]
        if status == 0xFF:  # meta event
            meta_type = data[i + 1]
            length, j = _read_vlq(data, i + 2)
            if meta_type == 0x03 and name is None:
                name = data[j:j + length].decode("latin-1", "replace")
            i = j + length
            if meta_type == 0x2F:
                break
            continue
        if status in (0xF0, 0xF7):  # sysex
            length, j = _read_vlq(data, i + 1)
            i = j + length
            continue
        if status & 0x80:
            running = status
            i += 1
        elif running is None:
            raise MidiFileError("Data byte without a status byte")
        kind, channel = running & 0xF0, running & 0x0F
        if kind in (0x80, 0x90):
            pitch, velocity = data[i], data[i + 1]
            i += 2
            key = (channel, pitch)
            if kind == 0x90 and velocity > 0:
                open_notes.setdefault(key, []).append((ticks, velocity))
            elif open_notes.get(key):
                start, vel = open_notes[key].pop(0)
                notes.append({
                    "pitch": pitch,
                    "start_time": start / division,
                    "duration": max(ticks - start, 1) / division,
                    "velocity": vel,
                    "channel": channel,
                    "track": track_number,
                })
        elif kind in (0xC0, 0xD0):
            i += 1
        else:
            i += 2
    # Notes never switched off end where the track ends.
    for (channel, pitch), starts in open_notes.items():
        for start, vel in starts:
            notes.append({
                "pitch": pitch, "start_time": start / division,
                "duration": max(ticks - start, 1) / division, "velocity": vel,
                "channel": channel, "track": track_number,
            })
    return {"index": track_number, "name": name, "notes": notes, "end": ticks / division}


def read_midi_file(path: str) -> Dict:
    """Parse ``path``; return {"format", "division", "tracks": [...]}.

    Each track has index, name, notes (pitch, start_time and duration in
    beats, velocity, channel) and end (beats).
    """
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"MThd":
        raise MidiFileError("Not a Standard MIDI File (missing MThd header)")
    header_len = struct.unpack(">I", data[4:8])[0]
    fmt, ntracks, division = struct.unpack(">HHH", data[8:14])
    if division & 0x8000:
        raise MidiFileError("SMPTE time division is not supported")
    if fmt not in (0, 1):
        raise MidiFileError("MIDI format %d is not supported (only 0 and 1)" % fmt)
    i = 8 + header_len
    tracks = []
    while i + 8 <= len(data) and len(tracks) < ntracks:
        chunk_type = data[i:i + 4]
        length = struct.unpack(">I", data[i + 4:i + 8])[0]
        body = data[i + 8:i + 8 + length]
        i += 8 + length
        if chunk_type != b"MTrk":
            continue  # unknown chunk, skip
        tracks.append(_parse_track(body, division, len(tracks)))
    return {"format": fmt, "division": division, "tracks": tracks}


def select_notes(parsed: Dict, midi_track: Optional[int] = None,
                 channel: Optional[int] = None, transpose: int = 0) -> List[Dict]:
    """Notes of one MIDI track (or all), optionally one channel, transposed.

    Returns add_notes_to_clip dictionaries sorted by time. Pitches pushed out
    of 0-127 by the transposition are dropped.
    """
    tracks = parsed["tracks"]
    if midi_track is not None:
        if midi_track < 0 or midi_track >= len(tracks):
            raise MidiFileError("midi_track %d out of range (%d tracks)" % (midi_track, len(tracks)))
        tracks = [tracks[midi_track]]
    out = []
    for track in tracks:
        for n in track["notes"]:
            if channel is not None and n["channel"] != channel:
                continue
            pitch = n["pitch"] + transpose
            if not 0 <= pitch <= 127:
                continue
            out.append({
                "pitch": pitch,
                "start_time": round(n["start_time"], 6),
                "duration": round(n["duration"], 6),
                "velocity": n["velocity"],
                "mute": False,
            })
    out.sort(key=lambda n: (n["start_time"], n["pitch"]))
    return out


def merge_duplicates(notes: List[Dict]):
    """Live keeps one note per (pitch, start): two voices hitting the same
    note at once collapse into one. Merge them up front, keeping the longest
    duration and the loudest velocity, so the count reported is the count
    Live ends up with. Returns (notes, merged_count)."""
    merged: Dict[tuple, Dict] = {}
    for n in notes:
        key = (n["pitch"], n["start_time"])
        if key in merged:
            kept = merged[key]
            kept["duration"] = max(kept["duration"], n["duration"])
            kept["velocity"] = max(kept["velocity"], n["velocity"])
        else:
            merged[key] = dict(n)
    out = sorted(merged.values(), key=lambda n: (n["start_time"], n["pitch"]))
    return out, len(notes) - len(out)


def summarize(parsed: Dict) -> List[Dict]:
    """One line per track: index, name, note count, channels, end."""
    return [{
        "index": t["index"],
        "name": t["name"],
        "notes": len(t["notes"]),
        "channels": sorted({n["channel"] for n in t["notes"]}),
        "end_beats": t["end"],
    } for t in parsed["tracks"]]
