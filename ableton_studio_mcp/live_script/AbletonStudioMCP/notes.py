"""MIDI notes: reading, adding, clearing and removing ranges."""
from __future__ import absolute_import, print_function, unicode_literals

try:  # Live 11+: probability, velocity deviation, release velocity
    from Live.Clip import MidiNoteSpecification
except ImportError:  # outside Live, or an older Live
    MidiNoteSpecification = None

from .registry import command

# Note fields beyond pitch/time/duration/velocity/mute (Live 11+).
EXTENDED_NOTE_FIELDS = ("probability", "velocity_deviation", "release_velocity")
NOTE_DETAIL_FIELDS = tuple((f, float) for f in EXTENDED_NOTE_FIELDS) + (
    ("note_id", int), ("pitch_bend_range", float), ("pressure", float),
    ("timbre", float), ("slide", float))


class NoteCommands(object):

    @command("add_notes_to_clip")
    def _add_notes_to_clip(self, track_index, clip_index, notes, location="session"):
        """Add notes to a Session or Arrangement clip (times in clip beats).
        Probability, velocity deviation and release velocity need Live 11's
        MidiNoteSpecification; without them the classic set_notes is used."""
        clip, _label = self._midi_clip(track_index, clip_index, location)
        checked = [self._checked_note(i, n) for i, n in enumerate(notes or [])]
        if any(extras for *_, extras in checked) and MidiNoteSpecification is not None \
                and hasattr(clip, "add_new_notes"):
            clip.add_new_notes(tuple(
                MidiNoteSpecification(pitch=p, start_time=s, duration=d, velocity=v, mute=m, **extras)
                for p, s, d, v, m, extras in checked))
        elif checked:
            clip.set_notes(tuple((p, s, d, v, m) for p, s, d, v, m, _ in checked))
        reply = {"note_count": len(checked), "clip_name": clip.name}
        reply.update(self._clip_location_info(clip, location))
        return reply

    def _note_time_span(self, clip):
        """A time range that covers every note of the clip, wherever its markers are."""
        ends = [float(clip.length)]
        for attr in ("end_marker", "loop_end"):
            value = getattr(clip, attr, None)
            if value is not None:
                ends.append(float(value))
        return 0.0, max(ends) + 1.0

    def _count_notes(self, clip, from_pitch, pitch_span, from_time, time_span):
        try:
            getter = getattr(clip, "get_notes_extended", None)
            if getter is not None:
                return len(list(getter(from_pitch, pitch_span, from_time, time_span)))
            return len(list(clip.get_notes(from_time, from_pitch, time_span, pitch_span)))
        except Exception:
            return None

    def _remove_note_range(self, clip, from_pitch, pitch_span, from_time, time_span):
        # remove_notes_extended(from_pitch, pitch_span, from_time, time_span)
        # (Live 11+) vs the legacy remove_notes(from_time, from_pitch,
        # time_span, pitch_span).
        remover = getattr(clip, "remove_notes_extended", None)
        if remover is not None:
            remover(from_pitch, pitch_span, from_time, time_span)
        else:
            clip.remove_notes(from_time, from_pitch, time_span, pitch_span)

    @command("clear_notes_from_clip")
    def _clear_notes_from_clip(self, track_index, clip_index, location="session"):
        """Remove every note of a clip; with add_notes_to_clip this makes a true
        replace (the API only appends). Reports how many notes went."""
        clip, _label = self._midi_clip(track_index, clip_index, location)
        start, span = self._note_time_span(clip)
        count = self._count_notes(clip, 0, 128, start, span) or 0
        self._remove_note_range(clip, 0, 128, start, span)
        reply = {"track_index": track_index, "clip_index": clip_index,
                 "clip_name": clip.name, "cleared_count": count}
        reply.update(self._clip_location_info(clip, location))
        return reply

    @command("remove_notes")
    def _remove_notes(self, track_index, clip_index, location="session", from_time=0.0,
                      time_span=None, from_pitch=0, pitch_span=128):
        """Remove the notes that start in a time range and pitch range.

        Times are in clip beats; time_span None means to the end of the clip.
        """
        clip, label = self._midi_clip(track_index, clip_index, location)
        from_time = float(from_time)
        if time_span is None:
            _, full_span = self._note_time_span(clip)
            time_span = max(0.0, full_span - from_time)
        time_span = float(time_span)
        from_pitch, pitch_span = int(from_pitch), int(pitch_span)
        if time_span <= 0 or pitch_span <= 0:
            raise ValueError("time_span and pitch_span must be positive")
        if from_pitch < 0 or from_pitch > 127:
            raise ValueError("from_pitch must be 0-127")
        pitch_span = min(pitch_span, 128 - from_pitch)
        removed = self._count_notes(clip, from_pitch, pitch_span, from_time, time_span)
        self._remove_note_range(clip, from_pitch, pitch_span, from_time, time_span)
        result = {
            "clip": label,
            "clip_name": clip.name,
            "removed_count": removed,
            "from_time": from_time,
            "time_span": time_span,
            "from_pitch": from_pitch,
            "pitch_span": pitch_span,
            "remaining_count": self._count_notes(clip, 0, 128, *self._note_time_span(clip)),
        }
        result.update(self._clip_location_info(clip, location))
        return result

    def _notes_from_clip(self, clip):
        """Every note of a MIDI clip as a dict; Live 11+ adds probability,
        velocity deviation, release velocity, note id and MPE fields."""
        if clip is None or not getattr(clip, "is_midi_clip", False):
            return []
        start, span = self._note_time_span(clip)
        reader = getattr(clip, "get_notes_extended", None)
        if reader is not None:
            try:
                return [self._note_dict(n) for n in reader(0, 128, start, span)]
            except (RuntimeError, TypeError) as e:
                self.log_message("get_notes_extended failed (%s); using get_notes" % e)
        return [{"pitch": int(n[0]), "start_time": float(n[1]), "duration": float(n[2]),
                 "velocity": float(n[3]), "mute": bool(n[4]) if len(n) > 4 else False}
                for n in clip.get_notes(start, 0, span, 128)]

    @command("get_clip_notes")
    def _get_clip_notes(self, track_index, clip_index, location="session"):
        clip, _label = self._midi_clip(track_index, clip_index, location)
        notes = self._notes_from_clip(clip)
        reply = {"track_index": track_index, "clip_index": clip_index, "clip_name": clip.name,
                 "length": float(clip.length), "note_count": len(notes), "notes": notes}
        reply.update(self._clip_location_info(clip, location))
        return reply

    @staticmethod
    def _checked_note(index, note):
        """One note from a request, validated: (pitch, start, duration, velocity,
        mute, extras). Bad notes are refused with their position in the list."""
        try:
            pitch = int(note.get("pitch", 60))
            start = float(note.get("start_time", 0.0))
            duration = float(note.get("duration", 0.25))
            velocity = float(note.get("velocity", 100))
        except (TypeError, ValueError, AttributeError):
            raise ValueError("note %d is not a valid note: %r" % (index, note))
        if not 0 <= pitch <= 127:
            raise ValueError("note %d: pitch %d is outside 0-127" % (index, pitch))
        if start < 0 or duration <= 0:
            raise ValueError("note %d: needs start_time >= 0 and duration > 0" % index)
        extras = dict((k, float(note[k])) for k in EXTENDED_NOTE_FIELDS if k in note)
        return pitch, start, duration, min(max(velocity, 0.0), 127.0), bool(note.get("mute", False)), extras

    @staticmethod
    def _note_dict(note):
        out = {"pitch": int(note.pitch), "start_time": float(note.start_time),
               "duration": float(note.duration), "velocity": float(note.velocity),
               "mute": bool(getattr(note, "mute", False))}
        for field, cast in NOTE_DETAIL_FIELDS:
            value = getattr(note, field, None)
            if value is not None:
                try:
                    out[field] = cast(value)
                except (TypeError, ValueError):
                    pass
        return out
