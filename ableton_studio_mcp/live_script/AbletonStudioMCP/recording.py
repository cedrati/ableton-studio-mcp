"""Recording the Arrangement."""
from __future__ import absolute_import, print_function, unicode_literals

from .constants import PLAYHEAD_SETTLE_TICKS, RECORDING_POLL_TICKS
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

    @command("record_arrangement")
    def _record_arrangement(self, start_time, end_time):
        """Record armed tracks into the Arrangement from start_time to end_time.

        Moves the playhead, turns on Arrangement Record and starts playback,
        then replies at once: a watcher stops playback and recording when the
        playhead reaches end_time (or when playback is stopped by hand).
        Poll get_recording_status for the outcome.
        """
        song = self._song
        start = float(start_time)
        if end_time is None or float(end_time) <= start:
            raise ValueError("end_time must be after start_time")
        end = float(end_time)
        armed = self._armed_tracks()
        if not armed:
            raise ValueError("No armed track: arm the track(s) to record first")
        if getattr(self, "_recording", None) and not self._recording.get("finished"):
            raise RuntimeError("A recording is already running")
        if song.is_playing:
            song.stop_playing()
        song.current_song_time = start

        def start_deferred(resolve, reject):
            def go(settled):
                song.record_mode = True
                song.start_playing()
                self._recording = {
                    "start_time": start, "end_time": end, "armed": armed,
                    "finished": False, "stopped_at": None,
                    "playhead_settled": settled,
                }
                self.schedule_message(RECORDING_POLL_TICKS, self._recording_watch)
                resolve(dict(self._recording, status="recording"))

            self._poll_until(
                lambda: self._playhead_at(start),
                on_ready=lambda: go(True),
                on_timeout=lambda: go(False),
                reject=reject,
                max_ticks=PLAYHEAD_SETTLE_TICKS,
            )

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
