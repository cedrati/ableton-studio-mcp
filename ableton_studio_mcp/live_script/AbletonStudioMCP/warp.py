"""Audio clip warping: modes, markers, conforming to a tempo."""
from __future__ import absolute_import, print_function, unicode_literals

try:
    import Live
except ImportError:  # outside Live (tests)
    Live = None

from .constants import WARP_MODE_NAMES, WARP_MODES_BY_NAME, SHADOW_MARKER_GAP, CONFORM_SNAP_BEATS
from .registry import command


class WarpCommands(object):

    # ------------------------------------------------------------- warp
    def _require_audio_clip(self, clip):
        if not getattr(clip, "is_audio_clip", False):
            raise ValueError("Warp settings only apply to audio clips")

    def _warp_mode_name(self, mode):
        try:
            return WARP_MODE_NAMES[int(mode)]
        except (KeyError, TypeError, ValueError):
            return "unknown (%s)" % mode

    def _parse_warp_mode(self, clip, warp_mode):
        """Accept a Live warp mode index or a name such as 'complex_pro'."""
        if isinstance(warp_mode, (int, float)) and not isinstance(warp_mode, bool):
            mode = int(warp_mode)
        else:
            key = str(warp_mode).strip().lower().replace("-", "_").replace(" ", "_")
            if key.isdigit():
                mode = int(key)
            elif key in WARP_MODES_BY_NAME:
                mode = WARP_MODES_BY_NAME[key]
            else:
                raise ValueError("Unknown warp mode '%s' (use one of: %s)"
                                 % (warp_mode, ", ".join(sorted(WARP_MODES_BY_NAME))))
        available = [int(m) for m in list(getattr(clip, "available_warp_modes", []) or [])]
        if available and mode not in available:
            raise ValueError("Warp mode '%s' is not available for this clip (available: %s)"
                             % (self._warp_mode_name(mode),
                                ", ".join(self._warp_mode_name(m) for m in available)))
        return mode

    def _warp_markers(self, clip):
        return [{"beat_time": float(m.beat_time), "sample_time": float(m.sample_time)}
                for m in list(getattr(clip, "warp_markers", []) or [])]

    def _clip_warp_info(self, clip, label):
        self._require_audio_clip(clip)
        info = {
            "clip": label,
            "name": clip.name,
            "warping": bool(clip.warping),
            "warp_mode": self._warp_mode_name(clip.warp_mode),
            "available_warp_modes": [self._warp_mode_name(m) for m in
                                     list(getattr(clip, "available_warp_modes", []) or [])],
            "warp_markers": self._warp_markers(clip),
            "pitch_coarse": int(clip.pitch_coarse),
            "pitch_fine": float(clip.pitch_fine),
            "gain": float(clip.gain),
            "gain_display": getattr(clip, "gain_display_string", None),
            "length_beats": float(clip.length),
            "song_tempo": float(self._song.tempo),
        }
        sample_rate = getattr(clip, "sample_rate", None)
        sample_length = getattr(clip, "sample_length", None)
        if sample_rate and sample_length:
            info["sample_seconds"] = float(sample_length) / float(sample_rate)
        return info

    @command("get_clip_warp")
    def _get_clip_warp(self, track_index, clip_index, location="session"):
        clip, label = self._resolve_clip(track_index, clip_index, location)
        return self._clip_warp_info(clip, label)

    @command("set_clip_warp")
    def _set_clip_warp(self, track_index, clip_index, location="session", warping=None,
                       warp_mode=None, pitch_coarse=None, pitch_fine=None, gain=None,
                       original_bpm=None):
        """Change a clip's warp settings; any argument left as None is untouched.

        original_bpm conforms the clip to the song tempo: warping is turned on
        and the warp markers are rebuilt so the audio is read at that tempo
        (first marker kept, one marker at the last whole beat of the file).
        Everything that can be checked is checked before the clip is touched.
        """
        clip, label = self._resolve_clip(track_index, clip_index, location)
        self._require_audio_clip(clip)
        mode = self._parse_warp_mode(clip, warp_mode) if warp_mode is not None else None
        plan = None
        if original_bpm is not None:
            plan = self._plan_conform(clip, float(original_bpm))
            warping = True
        notes = []
        if mode is not None:
            clip.warp_mode = mode
        if warping is not None:
            clip.warping = bool(warping)
        if pitch_coarse is not None:
            clip.pitch_coarse = int(max(-48, min(48, int(round(pitch_coarse)))))
        if pitch_fine is not None:
            clip.pitch_fine = float(max(-50.0, min(50.0, float(pitch_fine))))
        if gain is not None:
            clip.gain = float(max(0.0, min(1.0, float(gain))))
        if plan is not None:
            notes.extend(self._apply_conform(clip, plan))
        info = self._clip_warp_info(clip, label)
        if notes:
            info["notes"] = notes
        return info

    def _new_warp_marker(self, beat_time, sample_time):
        """Build what Clip.add_warp_marker accepts.

        Live's Python API wants a Live.Clip.WarpMarker, whose constructor is
        WarpMarker(sample_time, beat_time) with both required (Live 12.4.5);
        a dict, which Max for Live accepts, is refused. The object's own
        properties are checked so the two times can't end up swapped.
        Outside Live (tests) a dict is used.
        """
        if sample_time is None:
            raise ValueError("A warp marker needs a sample_time (seconds into the file) as "
                             "well as a beat_time: Live can't create one from a beat alone")
        beat_time, sample_time = float(beat_time), float(sample_time)
        cls = getattr(getattr(Live, "Clip", None), "WarpMarker", None) if Live else None
        if cls is None:
            return {"beat_time": beat_time, "sample_time": sample_time}
        marker = cls(sample_time=sample_time, beat_time=beat_time)
        if (abs(float(marker.beat_time) - beat_time) > 1e-6
                or abs(float(marker.sample_time) - sample_time) > 1e-6):
            raise RuntimeError("Live.Clip.WarpMarker swapped its times (got beat %s, sample %s)"
                               % (marker.beat_time, marker.sample_time))
        return marker

    def _plan_conform(self, clip, bpm):
        """Work out the marker that conforms the clip to bpm, without writing."""
        if bpm <= 0:
            raise ValueError("original_bpm must be positive")
        sample_rate = getattr(clip, "sample_rate", None)
        sample_length = getattr(clip, "sample_length", None)
        if not sample_rate or not sample_length:
            raise ValueError("Live did not report the sample's length; cannot conform to a BPM")
        duration = float(sample_length) / float(sample_rate)
        markers = self._warp_markers(clip)
        if markers:
            start_beat = markers[0]["beat_time"]
            start_sec = markers[0]["sample_time"]
        else:
            start_beat, start_sec = 0.0, 0.0
        seconds_per_beat = 60.0 / bpm
        exact_beats = (duration - start_sec) / seconds_per_beat
        notes = []
        nearest = int(round(exact_beats))
        if nearest >= 1 and abs(exact_beats - nearest) <= CONFORM_SNAP_BEATS:
            # Loops are often a few samples off a whole number of beats
            # (a 16-beat loop at 140 BPM measured 1 ms short): pin the end
            # to that beat rather than rounding down and losing one.
            whole_beats = nearest
        else:
            whole_beats = int(exact_beats + 1e-6)
        if whole_beats < 1:
            raise ValueError("The sample is shorter than one beat at %.2f BPM" % bpm)
        end_beat = start_beat + whole_beats
        end_sec = start_sec + whole_beats * seconds_per_beat
        if end_sec > duration:
            # Never ask for a marker past the end of the file.
            notes.append("The file ends %.1f ms before beat %g at %.2f BPM; that beat is "
                         "pinned to the end of the file" % ((end_sec - duration) * 1000.0,
                                                           end_beat, bpm))
            end_sec = duration
        return {"bpm": bpm, "old_markers": markers, "end_beat": end_beat,
                "end_sec": end_sec, "notes": notes,
                "end_marker": self._new_warp_marker(end_beat, end_sec)}

    def _apply_conform(self, clip, plan):
        """Keep the first marker, drop the others, pin the end; undo on failure.

        Live's shadow marker (1/32 beat after the last one) is left alone.
        """
        notes = list(plan.get("notes", []))
        removed = []
        to_remove = plan["old_markers"][1:]
        # The last marker is usually Live's "shadow marker", 1/32 beat after
        # the real last one. Live refuses to delete it and moves it itself.
        if (len(plan["old_markers"]) >= 2 and plan["old_markers"][-1]["beat_time"]
                - plan["old_markers"][-2]["beat_time"] <= SHADOW_MARKER_GAP + 1e-9):
            to_remove = to_remove[:-1]
        for marker in reversed(to_remove):
            try:
                clip.remove_warp_marker(marker["beat_time"])
                removed.append(marker)
            except Exception as e:
                notes.append("Live kept the warp marker at beat %.3f: %s"
                             % (marker["beat_time"], e))
        try:
            clip.add_warp_marker(plan["end_marker"])
        except Exception as e:
            restored = 0
            for marker in reversed(removed):
                try:
                    clip.add_warp_marker(self._new_warp_marker(
                        marker["beat_time"], marker["sample_time"]))
                    restored += 1
                except Exception:
                    pass
            raise RuntimeError("Live refused the warp marker at beat %.3f (%s); restored %d of "
                               "%d removed markers" % (plan["end_beat"], e, restored, len(removed)))
        notes.append("Conformed to %.2f BPM: beat %.3f = %.3f s"
                     % (plan["bpm"], plan["end_beat"], plan["end_sec"]))
        return notes

    @command("edit_warp_markers")
    def _edit_warp_markers(self, track_index, clip_index, location="session",
                           add=None, move=None, remove=None):
        """Remove, then move, then add warp markers (Live 11+)."""
        clip, label = self._resolve_clip(track_index, clip_index, location)
        self._require_audio_clip(clip)
        if not clip.warping:
            raise ValueError("Turn warping on (set_clip_warp) before editing warp markers")
        new_markers = [self._new_warp_marker(item["beat_time"], item.get("sample_time"))
                       for item in add or []]
        for beat_time in remove or []:
            clip.remove_warp_marker(float(beat_time))
        for item in move or []:
            clip.move_warp_marker(float(item["beat_time"]), float(item["beat_time_distance"]))
        for marker in new_markers:
            clip.add_warp_marker(marker)
        return self._clip_warp_info(clip, label)

    def _warp_markers_from_clip(self, clip):
        """The warp markers of an audio clip for a snapshot; [] for MIDI clips
        (asking Live for theirs raises) and when Live won't list them."""
        if not self._safe_attr(clip, "is_audio_clip", bool, False):
            return []
        try:
            return self._warp_markers(clip)
        except (AttributeError, RuntimeError, TypeError) as e:
            self.log_message("cannot read warp markers of '%s': %s" % (clip.name, e))
            return []
