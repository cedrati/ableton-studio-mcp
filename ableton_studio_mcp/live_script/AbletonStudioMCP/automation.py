"""Clip automation envelopes."""
from __future__ import absolute_import, print_function, unicode_literals

from .constants import MAX_AUTOMATION_STEPS, ENVELOPE_PROBE_OFFSET
from .registry import command


class AutomationCommands(object):

    # ------------------------------------------------------- automation
    def _resolve_automation_parameter(self, track_index, device_index=-1,
                                      parameter_index=0, mixer_parameter=""):
        """A device parameter, or a mixer one: 'volume', 'panning', 'send:N'."""
        track, _ = self._resolve_track(track_index, "track")
        mixer_parameter = (mixer_parameter or "").strip().lower()
        if mixer_parameter:
            mixer = track.mixer_device
            if mixer_parameter == "volume":
                return mixer.volume
            if mixer_parameter in ("panning", "pan"):
                return mixer.panning
            if mixer_parameter.startswith("send:"):
                sends = list(mixer.sends)
                try:
                    send_index = int(mixer_parameter.split(":", 1)[1])
                except ValueError:
                    raise ValueError("Send must be written 'send:N' (N = return index)")
                if send_index < 0 or send_index >= len(sends):
                    raise IndexError("Send index out of range (%d sends)" % len(sends))
                return sends[send_index]
            raise ValueError("mixer_parameter must be 'volume', 'panning' or 'send:N'")
        devices = list(track.devices)
        if device_index < 0 or device_index >= len(devices):
            raise IndexError("Device index out of range (%d devices)" % len(devices))
        params = list(devices[device_index].parameters)
        if parameter_index < 0 or parameter_index >= len(params):
            raise IndexError("Parameter index out of range (%d parameters)" % len(params))
        return params[parameter_index]

    def _automation_steps(self, points, interpolation, resolution, clip_end):
        """Turn sorted (time, value) points into (start, duration, value) steps."""
        steps = []
        for i, (time, value) in enumerate(points):
            next_time = points[i + 1][0] if i + 1 < len(points) else clip_end
            if next_time <= time:
                continue
            if interpolation == "linear" and i + 1 < len(points):
                next_value = points[i + 1][1]
                t = time
                while t < next_time - 1e-9:
                    duration = min(resolution, next_time - t)
                    ratio = (t - time) / (next_time - time)
                    steps.append((t, duration, value + (next_value - value) * ratio))
                    t += duration
            else:
                steps.append((time, next_time - time, value))
        return steps

    @command("set_clip_automation")
    def _set_clip_automation(self, track_index, clip_index, location="session",
                             device_index=-1, parameter_index=0, mixer_parameter="",
                             points=None, interpolation="linear", resolution=0.25,
                             clear_first=True):
        """Write a clip envelope for one parameter.

        points: [{"time": beats in clip time, "value": parameter units}].
        Each point holds until the next one ("step") or ramps to it ("linear",
        drawn as steps of `resolution` beats). The last point holds to the
        clip's end. Values are clamped to the parameter's range.
        """
        if (location or "session").lower() == "arrangement":
            # Live 12 refuses it ("Not a session clip or parameter belongs to
            # another track"): scripts can only write Session clip envelopes.
            raise ValueError("Live only lets scripts write clip automation on Session clips. "
                             "Write it on a Session clip instead; Arrangement automation "
                             "lanes aren't reachable from Live's API")
        clip, label = self._resolve_clip(track_index, clip_index, location)
        param = self._resolve_automation_parameter(
            track_index, device_index, parameter_index, mixer_parameter)
        interpolation = (interpolation or "linear").lower()
        if interpolation not in ("linear", "step"):
            raise ValueError("interpolation must be 'linear' or 'step'")
        resolution = float(resolution)
        if resolution <= 0:
            raise ValueError("resolution must be positive")
        clip_start, clip_end = self._clip_time_range(clip)
        lo, hi = float(param.min), float(param.max)
        parsed = []
        clamped = False
        for point in points or []:
            time = float(point["time"])
            value = float(point["value"])
            if value < lo or value > hi:
                clamped = True
                value = max(lo, min(hi, value))
            parsed.append((max(clip_start, time), value))
        parsed.sort(key=lambda p: p[0])
        steps = self._automation_steps(parsed, interpolation, resolution, clip_end)
        if len(steps) > MAX_AUTOMATION_STEPS:
            raise ValueError("Too many steps (%d > %d): raise resolution or use fewer points"
                             % (len(steps), MAX_AUTOMATION_STEPS))

        if clear_first:
            clip.clear_envelope(param)
        if not parsed:
            return {"clip": label, "parameter": param.name, "cleared": bool(clear_first),
                    "steps_written": 0}

        envelope = clip.automation_envelope(param)
        if envelope is None:
            envelope = clip.create_automation_envelope(param)
        if envelope is None:
            raise RuntimeError("Live refused to create an envelope for '%s'" % param.name)
        for start, duration, value in steps:
            envelope.insert_step(start, duration, value)
        result = {
            "clip": label,
            "parameter": param.name,
            "min": lo,
            "max": hi,
            "interpolation": interpolation,
            "points": len(parsed),
            "steps_written": len(steps),
            "clip_start": clip_start,
            "clip_end": clip_end,
        }
        if clamped:
            result["note"] = "Some values were outside [%g, %g] and were clamped" % (lo, hi)
        return result

    @command("get_clip_automation")
    def _get_clip_automation(self, track_index, clip_index, location="session",
                             device_index=-1, parameter_index=0, mixer_parameter="",
                             resolution=1.0):
        """Sample a clip envelope every `resolution` beats."""
        clip, label = self._resolve_clip(track_index, clip_index, location)
        param = self._resolve_automation_parameter(
            track_index, device_index, parameter_index, mixer_parameter)
        resolution = float(resolution)
        if resolution <= 0:
            raise ValueError("resolution must be positive")
        envelope = clip.automation_envelope(param)
        result = {"clip": label, "parameter": param.name,
                  "min": float(param.min), "max": float(param.max),
                  "has_envelope": envelope is not None, "samples": []}
        if envelope is None:
            return result
        clip_start, clip_end = self._clip_time_range(clip)
        count = min(int((clip_end - clip_start) / resolution + 1e-9) + 1, MAX_AUTOMATION_STEPS)
        # Live's value_at_time() is left-continuous: exactly on a step boundary
        # it returns the previous step (at the clip start, the value the
        # parameter had before automation). Read just after each time so the
        # sample is the value in effect from that time on.
        for i in range(count):
            t = clip_start + i * resolution
            probe = min(t + ENVELOPE_PROBE_OFFSET, clip_end)
            result["samples"].append({"time": t, "value": float(envelope.value_at_time(probe))})
        return result
