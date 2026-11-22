"""The song: overview, tempo, transport, playhead, view, locators, scenes, song scale."""
from __future__ import absolute_import, print_function, unicode_literals

from .constants import NOTE_NAMES_SHARP, TIME_TOLERANCE, PLAYHEAD_SETTLE_TICKS, CUE_SETTLE_TICKS
from .deferred import Deferred
from .registry import command


class SessionCommands(object):

    @command("get_session_info")
    def _get_session_info(self):
        """Tempo, meter, track counts, main track, transport and loop."""
        song, read = self._song, self._safe_attr
        main = song.master_track
        return {
            "tempo": float(song.tempo),
            "signature_numerator": int(song.signature_numerator),
            "signature_denominator": int(song.signature_denominator),
            "track_count": len(song.tracks),
            "return_track_count": len(song.return_tracks),
            # Live 12 names it "Main", Live 11 "Master": report what Live says.
            "master_track": {"name": read(main, "name", str, None) or "Master",
                             "volume": float(main.mixer_device.volume.value),
                             "panning": float(main.mixer_device.panning.value)},
            "is_playing": read(song, "is_playing", bool, False),
            "current_song_time": read(song, "current_song_time", float, 0.0),
            "song_length": read(song, "song_length", float, 0.0),
            "loop": read(song, "loop", bool, False),
            "loop_start": read(song, "loop_start", float, 0.0),
            "loop_length": read(song, "loop_length", float, 0.0),
            # True while tracks play (or were stopped from) Session clips
            # instead of following the Arrangement: Live lights "Back to
            # Arrangement".
            "back_to_arranger": read(song, "back_to_arranger", bool, False),
        }

    @command("back_to_arrangement")
    def _back_to_arrangement(self):
        """Press Back to Arrangement: every track follows the Arrangement
        again. Session clips playing on those tracks stop, as in Live."""
        song = self._song
        if not hasattr(song, "back_to_arranger"):
            raise RuntimeError("This version of Live has no Back to Arrangement in its API")
        session_tracks = [t.name for t in song.tracks
                          if self._safe_attr(t, "playing_slot_index", int, -1) >= 0]
        was = bool(song.back_to_arranger)
        if not was:
            return {"was_overriding": False, "tracks_playing_session_clips": session_tracks,
                    "back_to_arranger": False}
        song.back_to_arranger = False

        # Live applies it on a later tick: reply once the button is off.
        def start(resolve, reject):
            def report(settled):
                resolve({"was_overriding": True, "tracks_playing_session_clips": session_tracks,
                         "back_to_arranger": bool(song.back_to_arranger), "settled": settled})
            self._poll_until(lambda: not song.back_to_arranger, on_ready=lambda: report(True),
                             on_timeout=lambda: report(False), reject=reject,
                             max_ticks=PLAYHEAD_SETTLE_TICKS)
        return Deferred(start)

    @command("set_tempo")
    def _set_tempo(self, tempo):
        if not 20 <= float(tempo) <= 999:
            raise ValueError("Live's tempo goes from 20 to 999 BPM, not %s" % tempo)
        self._song.tempo = float(tempo)
        return {"tempo": float(self._song.tempo)}

    def _get_scene(self, scene_index):
        scenes = self._song.scenes
        if scene_index < 0 or scene_index >= len(scenes):
            raise IndexError("Scene index out of range (%d scenes)" % len(scenes))
        return scenes[scene_index]

    @command("create_scene")
    def _create_scene(self, index=-1):
        self._song.create_scene(index)
        new_index = len(self._song.scenes) - 1 if index == -1 else index
        return {"created": True, "index": new_index,
                "scene_count": len(self._song.scenes)}

    @command("delete_scene")
    def _delete_scene(self, scene_index):
        scene = self._get_scene(scene_index)
        if len(self._song.scenes) <= 1:
            raise ValueError("Cannot delete the last remaining scene")
        name = scene.name
        self._song.delete_scene(scene_index)
        return {"deleted": True, "index": scene_index, "name": name,
                "scene_count": len(self._song.scenes)}

    @command("duplicate_scene")
    def _duplicate_scene(self, scene_index):
        self._get_scene(scene_index)
        self._song.duplicate_scene(scene_index)
        return {"duplicated": True, "source_index": scene_index,
                "new_index": scene_index + 1}

    @command("fire_scene")
    def _fire_scene(self, scene_index):
        scene = self._get_scene(scene_index)
        scene.fire()
        return {"fired": True, "index": scene_index, "name": scene.name}

    @command("set_scene_name")
    def _set_scene_name(self, scene_index, name):
        scene = self._get_scene(scene_index)
        scene.name = name
        return {"index": scene_index, "name": scene.name}

    @command("get_scenes")
    def _get_scenes(self):
        return {"scenes": [
            {"index": i, "name": s.name,
             "tempo": s.tempo if getattr(s, "tempo_enabled", True) else None}
            for i, s in enumerate(self._song.scenes)
        ]}

    @command("start_playback")
    def _start_playback(self):
        # From the playhead: start_playing() would use Live's start marker,
        # which scripts can't move reliably (see recording.py).
        song = self._song
        (song.continue_playing if hasattr(song, "continue_playing") else song.start_playing)()
        return {"playing": True}

    @command("stop_playback")
    def _stop_playback(self):
        self._song.stop_playing()
        return {"playing": False}

    @command("switch_to_arrangement_view")
    def _switch_to_arrangement_view(self):
        self.application().view.show_view("Arranger")
        return {"view": "Arranger"}

    @command("set_current_song_time", time="time_val")
    def _set_current_song_time(self, time_val):
        """Move the playhead; the reply waits until Live shows it there."""
        song, target = self._song, float(time_val)
        if target < 0:
            raise ValueError("The song starts at beat 0, not %s" % target)
        song.current_song_time = target

        def start(resolve, reject):
            def report(settled):
                resolve({"current_song_time": float(song.current_song_time),
                         "requested_time": target, "settled": settled})
            self._poll_until(lambda: self._playhead_at(target), on_ready=lambda: report(True),
                             on_timeout=lambda: report(False), reject=reject,
                             max_ticks=PLAYHEAD_SETTLE_TICKS)
        return Deferred(start)

    @command("create_locator", time="time_val")
    def _create_locator(self, name, time_val):
        """A named locator at a beat; one already there is renamed (toggling
        would delete it)."""
        target = float(time_val)
        existing = self._find_cue(target)
        if existing is not None:
            return self._name_cue(existing, name)
        return self._toggle_cue_at(target, True,
                                   lambda: self._name_cue(self._find_cue(target), name), "create")

    @command("delete_locator", time="time_val")
    def _delete_locator(self, name=None, time_val=None):
        """Delete the locator at a beat, or the one with this name. A name
        several locators share is refused with their positions."""
        if time_val is not None:
            cue = self._find_cue(float(time_val))
            if cue is None:
                raise ValueError("No locator at beat %s" % time_val)
        elif name:
            same = [c for c in self._song.cue_points if c.name == str(name)]
            if not same:
                raise ValueError("No locator named '%s'" % name)
            if len(same) > 1:
                raise ValueError("%d locators are named '%s' (beats %s); give the time of the one "
                                 "to delete" % (len(same), name, ", ".join(str(c.time) for c in same)))
            cue = same[0]
        else:
            raise ValueError("Give the locator's name or time")
        gone = {"success": True, "deleted": True, "time": float(cue.time), "name": cue.name}
        return self._toggle_cue_at(float(cue.time), False, lambda: gone, "delete")

    def _find_cue(self, target_time):
        return next((c for c in self._song.cue_points
                     if abs(c.time - target_time) < TIME_TOLERANCE), None)

    def _name_cue(self, cue, name):
        if name:
            cue.name = str(name)
        return {"success": True, "time": float(cue.time), "name": cue.name}

    @command("get_song_scale")
    def _get_song_scale(self):
        """Live 12's song scale: root, scale name and intervals, Scale Mode."""
        song, read = self._song, self._safe_attr
        if not hasattr(song, "scale_name"):
            raise RuntimeError("This Live version has no song scale (Live 12+)")
        root = read(song, "root_note", int, None)
        return {"root_note": root,
                "root_name": NOTE_NAMES_SHARP[root % 12] if root is not None else None,
                "scale_name": read(song, "scale_name", str, None),
                "scale_intervals": read(song, "scale_intervals", list, None),
                "scale_mode": read(song, "scale_mode", bool, None)}

    @command("set_song_scale")
    def _set_song_scale(self, root_note=None, scale_name=None, scale_mode=None):
        """Set the song's root (0-11 or a name such as "Eb"), scale name (one
        of Live's, e.g. "Dorian", "Harmonic Minor") and Scale Mode switch."""
        song = self._song
        if not hasattr(song, "scale_name"):
            raise RuntimeError("This Live version has no song scale (Live 12+)")
        if root_note is not None:
            if isinstance(root_note, str):
                flats = {"Db": 1, "Eb": 3, "Gb": 6, "Ab": 8, "Bb": 10, "Cb": 11, "Fb": 4}
                key = root_note.strip()[:1].upper() + root_note.strip()[1:]
                if key in flats:
                    root_note = flats[key]
                elif key in NOTE_NAMES_SHARP:
                    root_note = NOTE_NAMES_SHARP.index(key)
                else:
                    raise ValueError("Unknown root note '%s'" % root_note)
            song.root_note = int(root_note) % 12
        if scale_name is not None:
            song.scale_name = str(scale_name)
            if str(song.scale_name).lower() != str(scale_name).lower():
                raise ValueError("Live did not accept scale '%s' (now '%s')"
                                 % (scale_name, song.scale_name))
        if scale_mode is not None:
            song.scale_mode = bool(scale_mode)
        return self._get_song_scale()

    def _toggle_cue_at(self, target, want_cue, done, verb):
        """Live can only add or remove a cue *at the playhead*
        (Song.set_or_delete_cue). So: move the playhead to ``target``, wait for
        Live to show it there, toggle, wait until the cue exists (``want_cue``)
        or is gone, put the playhead back, then call ``done()`` for the reply."""
        song = self._song
        if getattr(song, "is_playing", False):
            raise RuntimeError("Stop playback before you %s a locator: Live toggles "
                               "cues at the moving playhead" % verb)
        home = song.current_song_time
        song.current_song_time = target

        def start(resolve, reject):
            def go_home():
                try:
                    song.current_song_time = home
                except Exception:   # never hide the real outcome behind this
                    pass

            def fail(message):
                go_home()
                reject(message)

            def settled():
                return (self._find_cue(target) is not None) == want_cue

            def finish():
                result = done()
                go_home()
                resolve(result)

            def toggle():
                if settled():          # nothing to toggle any more
                    return finish()
                song.set_or_delete_cue()
                self._poll_until(settled, on_ready=finish, reject=fail,
                                 on_timeout=lambda: fail("Live did not %s the locator at beat %s"
                                                         % (verb, target)),
                                 max_ticks=CUE_SETTLE_TICKS)

            self._poll_until(lambda: self._playhead_at(target), on_ready=toggle, reject=fail,
                             on_timeout=lambda: fail("Playhead did not reach beat %s (now at %s)"
                                                     % (target, song.current_song_time)),
                             max_ticks=PLAYHEAD_SETTLE_TICKS)
        return Deferred(start)
