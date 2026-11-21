"""Recording the Arrangement."""
from __future__ import absolute_import, print_function, unicode_literals

from .constants import PLAYHEAD_SETTLE_TICKS, RECORDING_POLL_TICKS, RECORD_PREROLL_BEATS, TIME_TOLERANCE
from .deferred import Deferred
from .registry import command


class RecordingCommands(object):

    # ------------------------------------------------- arrangement recording
    def _armed_tracks(self):
        armed = []
        for i, track in enumerate(self._song.tracks):
            if self._safe_arm(track):
                armed.append({"index": i, "name": track.name})
        return armed

    # Transport and loop settings a recording changes and puts back.
    _SAVED_TRANSPORT = ("loop", "loop_start", "loop_length", "punch_in", "punch_out")

    @command("record_arrangement")
    def _record_arrangement(self, start_time, end_time):
        """Record armed tracks into the Arrangement, exactly from start_time to
        end_time, and reply once recording is under way.

        Measured in Live 12.4: playback started by a script does not reliably
        begin where current_song_time was set (start_playing() uses Live's
        start marker), and moving the playhead while recording splits the
        take. So the passage is set as the punch-in/out range, playback
        starts, the playhead jumps one beat before the range (a jump during
        playback is reliable), and Arrangement Record is switched on only
        once the playhead is confirmed in that pre-roll: Live then records
        exactly the range. Loop and punch settings are put back afterwards.
        A watcher stops at end_time (or when playback is stopped by hand).
        """
        song = self._song
        start, end = float(start_time), (float(end_time) if end_time is not None else None)
        if start < 0 or end is None or end <= start:
            raise ValueError("end_time must be after start_time (and start_time >= 0)")
        armed = self._armed_tracks()
        if not armed:
            raise ValueError("No armed track: arm the track(s) to record first")
        if getattr(self, "_recording", None) and not self._recording.get("finished"):
            raise RuntimeError("A recording is already running")
        if song.is_playing:
            song.stop_playing()
        song.record_mode = False
        saved = dict((k, getattr(song, k)) for k in self._SAVED_TRANSPORT if hasattr(song, k))
        if hasattr(song, "punch_in"):
            song.loop = False
            song.loop_start = start
            song.loop_length = end - start
            song.punch_in = True
            song.punch_out = True
        preroll = max(0.0, start - RECORD_PREROLL_BEATS)
        (song.continue_playing if hasattr(song, "continue_playing") else song.start_playing)()
        self._recording = {"start_time": start, "end_time": end, "armed": armed, "finished": False,
                           "stopped_at": None, "saved_transport": saved, "recording": False}

        def start_deferred(resolve, reject):
            def in_preroll():
                now = float(song.current_song_time)
                if song.is_playing and preroll - TIME_TOLERANCE <= now < max(start, preroll + 0.25):
                    return True
                song.current_song_time = preroll      # not there yet: jump (again)
                return False

            def armed_now():
                song.record_mode = True
                self._recording["recording"] = True
                self.schedule_message(RECORDING_POLL_TICKS, self._recording_watch)
                resolve(dict(self._recording, status="recording", saved_transport=None))

            def give_up():
                self._finish_recording("could not position the playhead before beat %s" % start)
                reject("Live did not move the playhead before beat %s; nothing was recorded" % start)

            self._poll_until(in_preroll, on_ready=armed_now, on_timeout=give_up,
                             reject=reject, max_ticks=PLAYHEAD_SETTLE_TICKS)

        return Deferred(start_deferred)

    def _recording_watch(self):
        rec = getattr(self, "_recording", None)
        if not rec or rec.get("finished"):
            return
        try:
            song = self._song
            if not song.is_playing or float(song.current_song_time) >= rec["end_time"]:
                self._finish_recording("end_reached" if song.is_playing else "stopped")
            else:
                self.schedule_message(RECORDING_POLL_TICKS, self._recording_watch)
        except Exception as e:
            self.log_message("Recording watcher error: " + str(e))
            self._finish_recording("error: %s" % e)

    def _finish_recording(self, reason):
        rec = getattr(self, "_recording", None) or {}
        song = self._song
        rec["stopped_at"] = float(song.current_song_time)
        try:
            song.record_mode = False
        finally:
            if song.is_playing:
                song.stop_playing()
            for key, value in (rec.pop("saved_transport", None) or {}).items():
                try:
                    setattr(song, key, value)
                except Exception as e:    # never hide the outcome behind this
                    self.log_message("could not restore %s: %s" % (key, e))
        rec["finished"] = True
        rec["reason"] = reason
        self._recording = rec
        return rec

    @command("stop_arrangement_recording")
    def _stop_arrangement_recording(self):
        rec = getattr(self, "_recording", None)
        if not rec or rec.get("finished"):
            self._song.record_mode = False
            return {"finished": True, "reason": "nothing_running"}
        return dict(self._finish_recording("stopped_by_command"))

    @command("get_recording_status")
    def _get_recording_status(self):
        rec = getattr(self, "_recording", None)
        return {
            "record_mode": self._safe_attr(self._song, "record_mode", bool, False),
            "is_playing": self._safe_attr(self._song, "is_playing", bool, False),
            "current_song_time": self._safe_attr(self._song, "current_song_time", float, 0.0),
            "recording": dict(rec) if rec else None,
            "armed_tracks": self._armed_tracks(),
        }
