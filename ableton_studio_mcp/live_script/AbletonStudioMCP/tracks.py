"""Tracks: information, creation, names, mixer, routing and meters."""
from __future__ import absolute_import, print_function, unicode_literals

from .constants import MONITORING_STATES, MONITORING_BY_NAME
from .registry import command


class TrackCommands(object):

    @command("get_track_info")
    def _get_track_info(self, track_index, track_type="track"):
        """A track, return track or the main track: mixer state, clip slots
        (regular tracks only) and device chain."""
        track, label = self._resolve_track(track_index, track_type)
        read = self._safe_attr
        slots = []
        for i, slot in enumerate(read(track, "clip_slots", list, [])):
            clip = slot.clip if slot.has_clip else None
            slots.append({"index": i, "has_clip": clip is not None,
                          "clip": None if clip is None else {
                              "name": clip.name, "length": float(clip.length),
                              "is_playing": read(clip, "is_playing", bool, False),
                              "is_recording": read(clip, "is_recording", bool, False)}})
        devices = [{"index": i, "name": d.name, "class_name": d.class_name,
                    "class_display_name": read(d, "class_display_name", str, None),
                    "type": self._get_device_type(d)}
                   for i, d in enumerate(track.devices)]
        mixer = track.mixer_device
        return {"index": track_index, "track_type": (track_type or "track").lower(), "label": label,
                "name": track.name,
                "is_audio_track": read(track, "has_audio_input", bool, False),
                "is_midi_track": read(track, "has_midi_input", bool, False),
                "mute": read(track, "mute", bool, False), "solo": read(track, "solo", bool, False),
                "arm": self._safe_arm(track),
                "volume": float(mixer.volume.value), "panning": float(mixer.panning.value),
                "clip_slots": slots, "devices": devices}

    def _safe_arm(self, track):
        """Whether the track is armed; False for tracks that cannot be (returns,
        the main track, groups): reading their ``arm`` raises RuntimeError."""
        if not self._safe_attr(track, "can_be_armed", bool, False):
            return False
        return self._safe_attr(track, "arm", bool, False)

    @command("create_midi_track")
    def _create_midi_track(self, index):
        return self._new_track("midi", index)

    @command("create_audio_track")
    def _create_audio_track(self, index):
        return self._new_track("audio", index)

    @command("set_track_name")
    def _set_track_name(self, track_index, name):
        track, _label = self._resolve_track(track_index, "track")
        track.name = name
        return {"name": track.name}

    def _resolve_track(self, track_index, track_type="track"):
        """Return (track, label) for a regular, return or master track."""
        track_type = (track_type or "track").lower()
        if track_type == "master":
            return self._song.master_track, "master"
        if track_type == "return":
            tracks = self._song.return_tracks
        elif track_type == "track":
            tracks = self._song.tracks
        else:
            raise ValueError("track_type must be 'track', 'return' or 'master'")
        if track_index < 0 or track_index >= len(tracks):
            raise IndexError("%s index out of range" % track_type.capitalize())
        return tracks[track_index], "%s %d" % (track_type, track_index)

    def _set_param_value(self, param, value):
        """Clamp value to the parameter's range and apply it."""
        value = max(param.min, min(param.max, float(value)))
        param.value = value
        return param.value

    @command("set_track_volume")
    def _set_track_volume(self, track_index, volume, track_type="track"):
        """Set track volume (Live's normalized fader value, 0.0–1.0; 0.85 ≈ 0 dB)."""
        track, label = self._resolve_track(track_index, track_type)
        param = track.mixer_device.volume
        new_value = self._set_param_value(param, volume)
        return {"track": label, "name": track.name, "volume": new_value,
                "display": param.str_for_value(new_value)}

    @command("set_track_panning")
    def _set_track_panning(self, track_index, panning, track_type="track"):
        """Set track panning (-1.0 = left, 0.0 = center, 1.0 = right)."""
        track, label = self._resolve_track(track_index, track_type)
        param = track.mixer_device.panning
        new_value = self._set_param_value(param, panning)
        return {"track": label, "name": track.name, "panning": new_value,
                "display": param.str_for_value(new_value)}

    @command("set_track_send")
    def _set_track_send(self, track_index, send_index, value, track_type="track"):
        """Set a send level (0.0–1.0) from a track to a return track."""
        track, label = self._resolve_track(track_index, track_type)
        sends = track.mixer_device.sends
        if send_index < 0 or send_index >= len(sends):
            raise IndexError("Send index out of range (track has %d sends)" % len(sends))
        param = sends[send_index]
        new_value = self._set_param_value(param, value)
        return {"track": label, "name": track.name, "send_index": send_index,
                "send_name": param.name, "value": new_value,
                "display": param.str_for_value(new_value)}

    @command("set_track_mute")
    def _set_track_mute(self, track_index, mute, track_type="track"):
        track, label = self._resolve_track(track_index, track_type)
        if track_type == "master":
            raise ValueError("The master track cannot be muted")
        track.mute = bool(mute)
        return {"track": label, "name": track.name, "mute": track.mute}

    @command("set_track_solo")
    def _set_track_solo(self, track_index, solo, track_type="track"):
        track, label = self._resolve_track(track_index, track_type)
        if track_type == "master":
            raise ValueError("The master track cannot be soloed")
        track.solo = bool(solo)
        return {"track": label, "name": track.name, "solo": track.solo}

    @command("set_track_arm")
    def _set_track_arm(self, track_index, arm):
        track, label = self._resolve_track(track_index, "track")
        if not track.can_be_armed:
            raise ValueError("Track '%s' cannot be armed" % track.name)
        track.arm = bool(arm)
        return {"track": label, "name": track.name, "arm": track.arm}

    @command("delete_track")
    def _delete_track(self, track_index):
        track, _ = self._resolve_track(track_index, "track")
        name = track.name
        self._song.delete_track(track_index)
        return {"deleted": True, "track_index": track_index, "name": name,
                "track_count": len(self._song.tracks)}

    @command("duplicate_track")
    def _duplicate_track(self, track_index):
        track, _ = self._resolve_track(track_index, "track")
        self._song.duplicate_track(track_index)
        new_track = self._song.tracks[track_index + 1]
        return {"duplicated": True, "source_index": track_index,
                "new_index": track_index + 1, "name": new_track.name}

    # ------------------------------------------------------------- routing
    @staticmethod
    def _routing_name(obj):
        return getattr(obj, "display_name", None) if obj is not None else None

    def _routing_side(self, track, side):
        """Current and available routing types/channels for "input" or "output"."""
        info = {}
        for kind in ("type", "channel"):
            current = self._safe_attr(track, "%s_routing_%s" % (side, kind))
            available = self._safe_attr(track, "available_%s_routing_%ss" % (side, kind), list, [])
            info[kind] = self._routing_name(current)
            info["available_%ss" % kind] = [self._routing_name(o) for o in available]
        return info

    @command("get_track_routing")
    def _get_track_routing(self, track_index, track_type="track"):
        """Input/output routing and monitoring of a track (Live 11+)."""
        track, label = self._resolve_track(track_index, track_type)
        result = {
            "track": label,
            "name": track.name,
            "output": self._routing_side(track, "output"),
        }
        if (track_type or "track").lower() == "track":
            result["input"] = self._routing_side(track, "input")
            state = self._safe_attr(track, "current_monitoring_state", int, None)
            result["monitoring"] = MONITORING_STATES.get(state)
            result["can_be_armed"] = self._safe_attr(track, "can_be_armed", bool, False)
        return result

    @staticmethod
    def _match_routing(options, wanted, what):
        """Pick the routing option whose display_name matches ``wanted``:
        exact (case-insensitive) first, else a unique substring match."""
        wanted_l = str(wanted).strip().lower()
        names = [(o.get("display_name", "") if isinstance(o, dict) else getattr(o, "display_name", "")) or ""
                 for o in options]
        for opt, name in zip(options, names):
            if name.lower() == wanted_l:
                return opt
        partial = [opt for opt, name in zip(options, names) if wanted_l in name.lower()]
        if len(partial) == 1:
            return partial[0]
        raise ValueError("%s '%s' not found%s. Available: %s" % (
            what, wanted, " (ambiguous)" if partial else "", ", ".join(names)))

    @command("set_track_routing")
    def _set_track_routing(self, track_index, track_type="track", input_type=None,
                           input_channel=None, output_type=None, output_channel=None,
                           monitoring=None):
        """Set routing by display name, as shown in Live's I/O section.

        Types are written before channels: the available channels depend on
        the type.
        """
        track, label = self._resolve_track(track_index, track_type)
        is_plain = (track_type or "track").lower() == "track"
        if not is_plain and (input_type is not None or input_channel is not None
                             or monitoring is not None):
            raise ValueError("Return and main tracks only have an output routing")
        changed = []
        for side, rtype, rchan in (("input", input_type, input_channel),
                                   ("output", output_type, output_channel)):
            if rtype is not None:
                options = list(getattr(track, "available_%s_routing_types" % side))
                setattr(track, "%s_routing_type" % side,
                        self._match_routing(options, rtype, "%s type" % side))
                changed.append("%s_type" % side)
            if rchan is not None:
                options = list(getattr(track, "available_%s_routing_channels" % side))
                setattr(track, "%s_routing_channel" % side,
                        self._match_routing(options, rchan, "%s channel" % side))
                changed.append("%s_channel" % side)
        if monitoring is not None:
            key = str(monitoring).strip().lower()
            if key not in MONITORING_BY_NAME:
                raise ValueError("monitoring must be 'in', 'auto' or 'off'")
            track.current_monitoring_state = MONITORING_BY_NAME[key]
            changed.append("monitoring")
        result = self._get_track_routing(track_index, track_type)
        result["changed"] = changed
        return result

    @command("get_track_meters")
    def _get_track_meters(self):
        """Output meters of every track, return track and the main track.

        Values are Live's meter readings (0.0-1.0, Live's meter scale, peak
        hold), as shown in the mixer; sample them while playing.
        """
        def meter(track, label, index):
            left = self._safe_attr(track, "output_meter_left", float, None)
            right = self._safe_attr(track, "output_meter_right", float, None)
            level = self._safe_attr(track, "output_meter_level", float, None)
            if level is None and left is not None and right is not None:
                level = max(left, right)
            return {"type": label, "index": index, "name": track.name,
                    "left": left, "right": right, "level": level}

        song = self._song
        out = [meter(t, "track", i) for i, t in enumerate(song.tracks)]
        out += [meter(t, "return", i) for i, t in enumerate(song.return_tracks)]
        out.append(meter(song.master_track, "master", 0))
        return {"current_song_time": self._safe_attr(self._song, "current_song_time", float, 0.0),
                "is_playing": self._safe_attr(self._song, "is_playing", bool, False),
                "meters": out}

    def _new_track(self, kind, index):
        """Create a MIDI or audio track and describe it."""
        tracks = self._song.tracks
        if not -1 <= index <= len(tracks):
            raise IndexError("A new track goes at 0..%d, or -1 for the end; not %d" % (len(tracks), index))
        create = self._song.create_midi_track if kind == "midi" else self._song.create_audio_track
        create(index)
        position = len(self._song.tracks) - 1 if index == -1 else index
        return {"index": position, "name": self._song.tracks[position].name}
