"""The whole set as one JSON document: tracks, clips, notes, devices (racks
included), returns, main track, scenes and locators."""
from __future__ import absolute_import, print_function, unicode_literals

from .registry import command

SCHEMA = "ableton_studio_mcp.snapshot/1"
# Racks inside racks: deeper levels are marked, not walked.
RACK_DEPTH = 4


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class SnapshotCommands(object):

    # ── pieces ──────────────────────────────────────────────────────────────

    def _mixer_state(self, track):
        mixer = track.mixer_device
        return {"volume": _float(mixer.volume.value), "panning": _float(mixer.panning.value)}

    def _parameter_state(self, index, param):
        state = {
            "index": index,
            "name": param.name,
            "value": _float(param.value),
            "min": _float(param.min),
            "max": _float(param.max),
            "is_enabled": bool(self._safe_attr(param, "is_enabled", bool, True)),
            "is_quantized": bool(self._safe_attr(param, "is_quantized", bool, False)),
        }
        # Normalised values mean little without what Live shows ("-6.0 dB").
        shown = self._param_display(param)
        if shown is not None:
            state["display"] = shown
        choices = self._safe_attr(param, "value_items", list, None)
        if choices:
            state["value_items"] = [str(c) for c in choices]
        automation = self._safe_attr(param, "automation_state", int, None)
        if automation is not None:
            state["automation_state"] = automation
        return state

    def _device_state(self, device, index, with_params=True, depth=0):
        automated = self._automated_params_for_device(device)
        state = {
            "index": index,
            "name": device.name,
            "class_name": device.class_name,
            "type": self._get_device_type(device),
            "automation_enabled": bool(automated),
        }
        if automated:
            state["automated_parameters"] = automated
        if with_params:
            state["parameters"] = []
            for i, param in enumerate(self._safe_attr(device, "parameters", list, [])):
                try:
                    state["parameters"].append(self._parameter_state(i, param))
                except (AttributeError, RuntimeError, TypeError):
                    continue   # a parameter Live won't describe right now
        # A rack's sound lives in its chains (a drum pad's Operator, a filter
        # inside an Instrument Rack): walk them, within reason.
        if self._safe_attr(device, "can_have_chains", bool, False):
            if depth >= RACK_DEPTH:
                state["chains_truncated"] = True
            else:
                state["chains"] = self._chains_state(device, with_params, depth)
        return state

    def _chains_state(self, rack, with_params, depth):
        groups = [("chains", self._safe_attr(rack, "chains", list, []))]
        returns = self._safe_attr(rack, "return_chains", list, [])
        if returns:
            groups.append(("return_chains", returns))
        out = []
        for kind, chains in groups:
            for i, chain in enumerate(chains):
                entry = {
                    "index": i,
                    "kind": kind,
                    "chain_name": self._safe_attr(chain, "name", str, ""),
                    "mute": bool(self._safe_attr(chain, "mute", bool, False)),
                    "solo": bool(self._safe_attr(chain, "solo", bool, False)),
                }
                try:
                    entry.update(self._mixer_state(chain))
                except (AttributeError, RuntimeError):
                    pass
                pad_note = self._safe_attr(chain, "out_note", int, None)   # drum racks
                if pad_note is not None:
                    entry["out_note"] = pad_note
                entry["devices"] = [self._device_state(d, j, with_params, depth + 1)
                                    for j, d in enumerate(self._safe_attr(chain, "devices", list, []))]
                out.append(entry)
        return out

    def _clip_state(self, clip, with_notes, in_arrangement):
        read = self._safe_attr
        state = {
            "name": clip.name,
            "length": _float(clip.length),
            "color": read(clip, "color", int, 0),
            "is_midi_clip": bool(read(clip, "is_midi_clip", bool, False)),
            "is_audio_clip": bool(read(clip, "is_audio_clip", bool, False)),
            "is_playing": bool(read(clip, "is_playing", bool, False)),
            "looping": bool(read(clip, "looping", bool, False)),
            "warping": bool(read(clip, "warping", bool, False)),
        }
        if in_arrangement:
            state["start_time"] = _float(clip.start_time)
            state["end_time"] = _float(clip.end_time)
        else:
            state["is_recording"] = bool(read(clip, "is_recording", bool, False))
        for attr, cast in (("loop_start", float), ("loop_end", float), ("warp_mode", int),
                           ("gain", float), ("pitch_coarse", int), ("pitch_fine", int),
                           ("launch_mode", int)):
            value = read(clip, attr, cast, None)
            if value is not None:
                state[attr] = value
        path = read(clip, "file_path", str, None) or read(clip, "file_path_relative", str, None)
        if path:
            state["file_path"] = path
        markers = self._warp_markers_from_clip(clip)
        if markers:
            state["warp_markers"] = markers
            state["warp_marker_count"] = len(markers)
        if with_notes and state["is_midi_clip"]:
            state["notes"] = self._notes_from_clip(clip)
            state["note_count"] = len(state["notes"])
        return state

    def _track_state(self, index, track, with_notes, with_params):
        slots = []
        for i, slot in enumerate(track.clip_slots):
            has_clip = bool(slot.has_clip)
            slots.append({"index": i, "has_clip": has_clip,
                          "clip": self._clip_state(slot.clip, with_notes, False) if has_clip else None})
        try:
            arranged = [self._clip_state(c, with_notes, True) for c in track.arrangement_clips]
        except (AttributeError, RuntimeError) as e:   # Live 10, or a group track
            self.log_message("no arrangement clips for track %d: %s" % (index, e))
            arranged = []
        state = {
            "index": index,
            "name": track.name,
            "is_audio_track": bool(track.has_audio_input),
            "is_midi_track": bool(track.has_midi_input),
            "mute": bool(track.mute),
            "solo": bool(track.solo),
            "arm": self._safe_arm(track),
        }
        state.update(self._mixer_state(track))
        state["sends"] = [{"index": i, "value": _float(send.value),
                           "name": self._safe_attr(send, "name", str, "Send %d" % i)}
                          for i, send in enumerate(track.mixer_device.sends)]
        state["clip_slots"] = slots
        state["devices"] = [self._device_state(d, i, with_params) for i, d in enumerate(track.devices)]
        state["arrangement_clips"] = arranged
        return state

    def _bus_state(self, track, with_params):
        state = self._mixer_state(track)
        state["devices"] = [self._device_state(d, i, with_params) for i, d in enumerate(track.devices)]
        return state

    # ── the command ─────────────────────────────────────────────────────────

    @command("get_session_snapshot")
    def _get_session_snapshot(self, include_notes=True, include_params=True):
        song = self._song
        returns = []
        for i, track in enumerate(song.return_tracks):
            state = {"index": i, "name": track.name, "mute": bool(track.mute), "solo": bool(track.solo)}
            state.update(self._bus_state(track, include_params))
            returns.append(state)
        return {
            "schema": SCHEMA,
            "session": self._get_session_info(),
            "tracks": [self._track_state(i, t, include_notes, include_params)
                       for i, t in enumerate(song.tracks)],
            "scenes": [{"index": i, "name": str(s.name),
                        "tempo": self._safe_attr(s, "tempo", float, None),
                        "is_triggered": bool(self._safe_attr(s, "is_triggered", bool, False))}
                       for i, s in enumerate(song.scenes)],
            "return_tracks": returns,
            "master_track": self._bus_state(song.master_track, include_params),
            "cue_points": [{"name": self._safe_attr(c, "name", str, ""), "time": _float(c.time)}
                           for c in song.cue_points],
            "include_notes": bool(include_notes),
            "include_params": bool(include_params),
        }
