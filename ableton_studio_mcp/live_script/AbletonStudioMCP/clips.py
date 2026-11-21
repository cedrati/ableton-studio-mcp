"""Clips: creation, names, launching, deletion, loop and markers, Arrangement placement, audio files."""
from __future__ import absolute_import, print_function, unicode_literals

import os

from .registry import command


class ClipCommands(object):

    @command("create_clip")
    def _create_clip(self, track_index, clip_index, length):
        """An empty MIDI clip of ``length`` beats in an empty slot."""
        if float(length) <= 0:
            raise ValueError("A clip needs a positive length, not %s" % length)
        _track, slot = self._empty_slot(track_index, clip_index)
        slot.create_clip(float(length))
        return {"name": slot.clip.name, "length": float(slot.clip.length)}

    @command("create_audio_clip")
    def _create_audio_clip(self, track_index, clip_index, path):
        """Import an audio file into an empty slot of an audio track
        (ClipSlot.create_audio_clip exists since Live 12.0.5)."""
        if not path or not os.path.isabs(path):
            raise ValueError("Give the audio file's absolute path (got %r)" % (path,))
        if not os.path.isfile(path):
            raise ValueError("No file at %s" % path)
        track, slot = self._empty_slot(track_index, clip_index)
        if getattr(track, "has_midi_input", False):
            raise ValueError("Track %d is a MIDI track; audio clips go on audio tracks" % track_index)
        if not hasattr(slot, "create_audio_clip"):
            raise RuntimeError("This Live cannot create audio clips from a script (Live 12.0.5+ needed)")
        slot.create_audio_clip(path)
        clip = slot.clip
        return {"name": clip.name, "length": float(clip.length), "is_audio_clip": bool(clip.is_audio_clip)}

    def _midi_clip(self, track_index, clip_index, location="session"):
        clip, label = self._resolve_clip(track_index, clip_index, location)
        if not getattr(clip, "is_midi_clip", False):
            raise ValueError("%s is not a MIDI clip" % label.capitalize())
        return clip, label

    def _clip_location_info(self, clip, location):
        """Where a clip sits, so its notes (in clip time) can be placed in the song."""
        info = {"location": (location or "session").lower()}
        if info["location"] == "arrangement":
            info["arrangement_start"] = float(clip.start_time)
            info["arrangement_end"] = float(clip.end_time)
            info["start_marker"] = float(getattr(clip, "start_marker", 0.0) or 0.0)
            info["looping"] = bool(getattr(clip, "looping", False))
        return info

    @command("set_clip_name")
    def _set_clip_name(self, track_index, clip_index, name):
        _track, slot = self._filled_slot(track_index, clip_index)
        slot.clip.name = name
        return {"name": slot.clip.name}

    @command("set_arrangement_clip_name")
    def _set_arrangement_clip_name(self, track_index, clip_index, name):
        _track, clip = self._arrangement_clip(track_index, clip_index)
        clip.name = name
        return {"name": clip.name}

    @command("fire_clip")
    def _fire_clip(self, track_index, clip_index):
        _track, slot = self._filled_slot(track_index, clip_index)
        slot.fire()
        return {"fired": True, "name": slot.clip.name}

    @command("stop_clip")
    def _stop_clip(self, track_index, clip_index):
        _track, slot = self._slot(track_index, clip_index)
        slot.stop()
        return {"stopped": True}

    @command("delete_clip")
    def _delete_clip(self, track_index, clip_index):
        _track, slot = self._slot(track_index, clip_index)
        if not slot.has_clip:
            return {"deleted": False, "reason": "the slot was already empty"}
        name = slot.clip.name
        slot.delete_clip()
        return {"deleted": True, "name": name}

    @command("delete_arrangement_clip")
    def _delete_arrangement_clip(self, track_index, clip_index):
        """Track.delete_clip exists since Live 11."""
        track, clip = self._arrangement_clip(track_index, clip_index)
        gone = {"name": clip.name, "start_time": float(clip.start_time), "end_time": float(clip.end_time)}
        track.delete_clip(clip)
        gone["deleted"] = True
        return gone

    def _resolve_clip(self, track_index, clip_index, location="session"):
        """(clip, label) for a Session slot or for the Nth Arrangement clip of a
        track (N as listed by get_arrangement_clips)."""
        where = (location or "session").lower()
        if where == "session":
            return (self._filled_slot(track_index, clip_index)[1].clip,
                    "session clip %d/%d" % (track_index, clip_index))
        if where == "arrangement":
            return (self._arrangement_clip(track_index, clip_index)[1],
                    "arrangement clip %d/%d" % (track_index, clip_index))
        raise ValueError("location must be 'session' or 'arrangement'")

    def _clip_time_range(self, clip):
        """(start, end) of the clip's content in clip time (beats)."""
        start = float(getattr(clip, "start_marker", 0.0) or 0.0)
        end = getattr(clip, "end_marker", None)
        end = float(end) if end is not None else start + float(clip.length)
        if end <= start:
            end = start + float(clip.length)
        return start, end

    # ------------------------------------------------------- loop / markers
    def _clip_loop_info(self, clip, label):
        audio = bool(getattr(clip, "is_audio_clip", False))
        unwarped = audio and not bool(getattr(clip, "warping", True))
        info = {
            "clip": label,
            "name": clip.name,
            "looping": bool(clip.looping),
            "loop_start": float(clip.loop_start),
            "loop_end": float(clip.loop_end),
            "start_marker": float(clip.start_marker),
            "end_marker": float(clip.end_marker),
            "length": float(clip.length),
            # Live measures an unwarped audio clip's loop and markers in
            # seconds of the file, every other clip in beats.
            "units": "seconds" if unwarped else "beats",
        }
        # What actually plays (Live 12.4.5). Looping: from the start marker,
        # then the brace repeats. Not looping: Live plays loop_start ->
        # loop_end; start_marker mirrors loop_start and end_marker is unused.
        if info["looping"]:
            info["playback"] = {"starts_at": info["start_marker"],
                                "repeats": [info["loop_start"], info["loop_end"]]}
        else:
            info["playback"] = {"plays_once": [info["loop_start"], info["loop_end"]]}
        return info

    @command("get_clip_loop")
    def _get_clip_loop(self, track_index, clip_index, location="session"):
        clip, label = self._resolve_clip(track_index, clip_index, location)
        info = self._clip_loop_info(clip, label)
        if (location or "session").lower() == "arrangement":
            info["arrangement_start"] = float(clip.start_time)
            info["arrangement_end"] = float(clip.end_time)
        return info

    def _set_pair(self, clip, start_attr, end_attr, start, end):
        """Set a start/end pair without ever making start >= end on the way.

        Live refuses a start at or past the current end (and an end at or
        before the current start), so the order depends on the move.
        """
        current_start = float(getattr(clip, start_attr))
        current_end = float(getattr(clip, end_attr))
        start = current_start if start is None else float(start)
        end = current_end if end is None else float(end)
        if start >= end:
            raise ValueError("%s (%g) must be before %s (%g)" % (start_attr, start, end_attr, end))
        if start >= current_end:
            setattr(clip, end_attr, end)
            setattr(clip, start_attr, start)
        else:
            setattr(clip, start_attr, start)
            setattr(clip, end_attr, end)

    @command("set_clip_loop")
    def _set_clip_loop(self, track_index, clip_index, location="session", looping=None,
                       loop_start=None, loop_end=None, start_marker=None, end_marker=None,
                       loop_length=None):
        """Change a clip's loop switch, loop brace and start/end markers.

        Arguments left as None are untouched. loop_length sets loop_end to
        loop_start + loop_length. Units are beats (seconds for an unwarped
        audio clip, see get_clip_loop). The reply reports what Live applied;
        `adjusted` lists any value Live changed (it snaps or clamps some).
        """
        clip, label = self._resolve_clip(track_index, clip_index, location)
        notes = []
        final_looping = bool(clip.looping) if looping is None else bool(looping)
        if not final_looping and (start_marker is not None or end_marker is not None):
            # Unlooped, Live plays loop_start -> loop_end and ignores a
            # start_marker write (end_marker is accepted but unused).
            if loop_start is not None or loop_end is not None or loop_length is not None:
                raise ValueError("This clip doesn't loop: Live plays it from loop_start to "
                                 "loop_end. Give either start/end markers or loop values")
            loop_start, loop_end = start_marker, end_marker
            start_marker = end_marker = None
            notes.append("Clip not looping: start/end written to loop_start/loop_end, "
                         "which is what Live plays")
        if loop_length is not None:
            if float(loop_length) <= 0:
                raise ValueError("loop_length must be positive")
            base = float(clip.loop_start) if loop_start is None else float(loop_start)
            if loop_end is not None and abs(float(loop_end) - (base + float(loop_length))) > 1e-9:
                raise ValueError("Give loop_end or loop_length, not both")
            loop_end = base + float(loop_length)
        # Check both pairs before writing anything.
        for start_attr, end_attr, start, end in (
                ("loop_start", "loop_end", loop_start, loop_end),
                ("start_marker", "end_marker", start_marker, end_marker)):
            s_val = float(getattr(clip, start_attr)) if start is None else float(start)
            e_val = float(getattr(clip, end_attr)) if end is None else float(end)
            if s_val >= e_val:
                raise ValueError("%s (%g) must be before %s (%g)"
                                 % (start_attr, s_val, end_attr, e_val))
        if looping is not None:
            clip.looping = bool(looping)
        if loop_start is not None or loop_end is not None:
            self._set_pair(clip, "loop_start", "loop_end", loop_start, loop_end)
        if start_marker is not None or end_marker is not None:
            self._set_pair(clip, "start_marker", "end_marker", start_marker, end_marker)
        info = self._get_clip_loop(track_index, clip_index, location)
        if notes:
            info["notes"] = notes
        requested = {"looping": looping, "loop_start": loop_start, "loop_end": loop_end,
                     "start_marker": start_marker, "end_marker": end_marker}
        adjusted = {}
        for key, wanted in requested.items():
            if wanted is None:
                continue
            got = info[key]
            if (bool(got) != bool(wanted)) if key == "looping" else abs(float(got) - float(wanted)) > 1e-6:
                adjusted[key] = {"requested": wanted, "applied": got}
        if adjusted:
            info["adjusted"] = adjusted
        return info

    @command("get_arrangement_clips")
    def _get_arrangement_clips(self, track_index):
        """The track's Arrangement clips in time order: their position in this
        list is the clip_index the other commands take."""
        track, _label = self._resolve_track(track_index, "track")
        read = self._safe_attr
        clips = [{
            "name": clip.name,
            "start_time": float(clip.start_time),
            "end_time": float(clip.end_time),
            "length": float(clip.length),
            "color": read(clip, "color", int, 0),
            "is_midi_clip": bool(read(clip, "is_midi_clip", bool, False)),
            "is_audio_clip": bool(read(clip, "is_audio_clip", bool, False)),
            "is_playing": bool(read(clip, "is_playing", bool, False)),
        } for clip in track.arrangement_clips]
        return {"track_index": track_index, "track_name": track.name,
                "clip_count": len(clips), "clips": clips}

    @command("duplicate_session_clip_to_arrangement")
    def _duplicate_session_clip_to_arrangement(self, track_index, clip_index, destination_time):
        """Copy a Session clip into the Arrangement of its own track
        (Track.duplicate_clip_to_arrangement, Live 11+)."""
        if float(destination_time) < 0:
            raise ValueError("The Arrangement starts at beat 0, not %s" % destination_time)
        track, slot = self._filled_slot(track_index, clip_index)
        track.duplicate_clip_to_arrangement(slot.clip, float(destination_time))
        return {"success": True, "track_index": track_index, "track_name": track.name,
                "clip_name": slot.clip.name, "destination_time": float(destination_time)}

    @command("get_audio_clip_file")
    def _get_audio_clip_file(self, track_index, clip_index, location="arrangement"):
        """File behind an audio clip (e.g. a freshly recorded take)."""
        clip, label = self._resolve_clip(track_index, clip_index, location)
        if not getattr(clip, "is_audio_clip", False):
            raise ValueError("%s is not an audio clip" % label)
        return {
            "clip": label,
            "name": clip.name,
            "file_path": self._safe_attr(clip, "file_path", str, None),
            "length": self._safe_attr(clip, "length", float, None),
            "start_time": self._safe_attr(clip, "start_time", float, None),
            "end_time": self._safe_attr(clip, "end_time", float, None),
            "sample_rate": self._safe_attr(clip, "sample_rate", float, None),
            "sample_length": self._safe_attr(clip, "sample_length", int, None),
            "warping": self._safe_attr(clip, "warping", bool, None),
        }

    def _slot(self, track_index, clip_index):
        """The Session clip slot at (track, scene)."""
        track, label = self._resolve_track(track_index, "track")
        slots = list(track.clip_slots)
        if not 0 <= clip_index < len(slots):
            raise IndexError("%s has %d slot(s); there is no slot %d" % (label, len(slots), clip_index))
        return track, slots[clip_index]

    def _filled_slot(self, track_index, clip_index):
        track, slot = self._slot(track_index, clip_index)
        if not slot.has_clip:
            raise ValueError("Slot %d of track %d is empty" % (clip_index, track_index))
        return track, slot

    def _empty_slot(self, track_index, clip_index):
        track, slot = self._slot(track_index, clip_index)
        if slot.has_clip:
            raise ValueError("Slot %d of track %d already holds '%s' (delete_clip frees it)"
                             % (clip_index, track_index, slot.clip.name))
        return track, slot

    def _arrangement_clip(self, track_index, clip_index):
        track, label = self._resolve_track(track_index, "track")
        clips = list(track.arrangement_clips)
        if not 0 <= clip_index < len(clips):
            raise IndexError("%s has %d clip(s) in the Arrangement; there is no clip %d"
                             % (label, len(clips), clip_index))
        return track, clips[clip_index]
