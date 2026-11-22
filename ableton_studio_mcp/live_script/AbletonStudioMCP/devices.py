"""Devices: parameters, identity, sidechain, plug-in presets, Simpler, racks, drum racks."""
from __future__ import absolute_import, print_function, unicode_literals

import difflib
import os

from .registry import command
from .values import resolve_value


class DeviceCommands(object):

    # ── reading devices safely ──────────────────────────────────────────────

    @staticmethod
    def _safe_attr(obj, attr, cast=None, default=None):
        """``obj.attr`` (cast if asked), or ``default`` when Live won't give it.
        Methods are not values: a callable attribute also yields ``default``."""
        try:
            value = getattr(obj, attr)
            if callable(value):
                return default
            return value if cast is None else cast(value)
        except Exception:   # Live raises various errors for unavailable properties
            return default

    @staticmethod
    def _param_display(param, value=None):
        """The value as Live writes it ("-6.0 dB", "Bell", "1.56 kHz"), or None."""
        try:
            return str(param.str_for_value(param.value if value is None else value))
        except Exception:
            try:
                return str(param)
            except Exception:
                return None

    def _get_device_type(self, device):
        """A coarse family: drum_machine, rack, instrument, audio_effect,
        midi_effect, or unknown."""
        read = self._safe_attr
        if read(device, "can_have_drum_pads", bool, False):
            return "drum_machine"
        if read(device, "can_have_chains", bool, False):
            return "rack"
        family = (read(device, "class_display_name", str, "") + " " + read(device, "class_name", str, "")).lower()
        for marker, kind in (("instrument", "instrument"), ("audio_effect", "audio_effect"),
                             ("midi_effect", "midi_effect")):
            if marker in family:
                return kind
        kind = read(device, "type", int, None)    # Live.Device.DeviceType: 1, 2, 4
        return {1: "instrument", 2: "audio_effect", 4: "midi_effect"}.get(kind, "unknown")

    def _automated_params_for_device(self, device):
        """Names of the device's parameters that carry automation."""
        names = []
        for param in self._safe_attr(device, "parameters", list, []):
            state = self._safe_attr(param, "automation_state", int, None)
            if state is None:
                state = 1 if self._safe_attr(param, "is_automated", bool, False) else 0
            if state:
                names.append(self._safe_attr(param, "name", str, "?"))
        return names

    def _device_on(self, track_index, device_index, track_type):
        track, label = self._resolve_track(track_index, track_type)
        devices = list(track.devices)
        if not 0 <= device_index < len(devices):
            raise IndexError("%s has %d device(s); there is no device %d"
                             % (label, len(devices), device_index))
        return devices[device_index]

    # ── parameters ──────────────────────────────────────────────────────────

    @command("get_device_parameters")
    def _get_device_parameters(self, track_index, device_index, track_type="track"):
        device = self._device_on(track_index, device_index, track_type)
        return {"track_index": track_index, "track_type": (track_type or "track").lower(),
                "device": self._device_state(device, device_index, with_params=True)}

    @command("set_device_parameter")
    def _set_device_parameter(self, track_index, device_index, parameter_index, value,
                              track_type="track"):
        device = self._device_on(track_index, device_index, track_type)
        params = list(device.parameters)
        if not 0 <= parameter_index < len(params):
            raise IndexError("%s has %d parameter(s); there is no parameter %d"
                             % (device.name, len(params), parameter_index))
        param = params[parameter_index]
        low, high = float(param.min), float(param.max)
        target = float(value)
        if not low <= target <= high:
            raise ValueError("%s takes %s to %s, not %s" % (param.name, low, high, target))
        before, before_shown = float(param.value), self._param_display(param)
        param.value = target
        return {"track_index": track_index, "device_index": device_index,
                "parameter_index": parameter_index, "name": param.name,
                "old_value": before, "old_display": before_shown,
                "value": float(param.value), "display": self._param_display(param),
                "min": low, "max": high}

    @staticmethod
    def _find_parameter(params, name):
        """A device parameter by name: exact (any case), else the only one
        containing ``name``."""
        wanted = str(name).strip().lower()
        exact = [p for p in params if p.name.lower() == wanted]
        if exact:
            return exact[0]
        partial = [p for p in params if wanted in p.name.lower()]
        if len(partial) == 1:
            return partial[0]
        if partial:
            raise ValueError("'%s' matches several parameters: %s" % (name, ", ".join(p.name for p in partial[:12])))
        close = difflib.get_close_matches(str(name), [p.name for p in params], n=6, cutoff=0.5)
        raise ValueError("No parameter '%s'%s" % (name, (" (did you mean %s?)" % ", ".join(close)) if close else ""))

    @command("set_device_parameters")
    def _set_device_parameters(self, track_index, device_index, values, track_type="track"):
        """Set several parameters by name, each from a number in its own range
        or a musical value ("800 Hz", "-6 dB", "Bell"). Every value is checked
        before anything changes."""
        if not isinstance(values, dict) or not values:
            raise ValueError("values must map parameter names to values")
        device = self._device_on(track_index, device_index, track_type)
        params = list(device.parameters)
        plan = []
        for name, wanted in values.items():
            param = self._find_parameter(params, name)
            plan.append((param, wanted, resolve_value(param, wanted)))
        changes = []
        for param, wanted, value in plan:
            before = self._param_display(param)
            param.value = value
            changes.append({"name": param.name, "requested": wanted, "was": before,
                            "now": self._param_display(param), "value": float(param.value)})
        return {"device": device.name, "changes": changes}

    # ── the device chain ────────────────────────────────────────────────────

    @staticmethod
    def _chain_names(track):
        return [d.name for d in track.devices]

    @command("delete_device")
    def _delete_device(self, track_index, device_index, track_type="track"):
        """Remove a device from a track, a return track or the main track."""
        track, label = self._resolve_track(track_index, track_type)
        device = self._device_on(track_index, device_index, track_type)
        name = device.name
        track.delete_device(device_index)
        return {"deleted": name, "device_index": device_index, "on": label,
                "devices": self._chain_names(track)}

    @command("move_device")
    def _move_device(self, track_index, device_index, new_index, track_type="track"):
        """Move a device to another position in the same chain (Live 11+)."""
        track, label = self._resolve_track(track_index, track_type)
        device = self._device_on(track_index, device_index, track_type)
        count = len(list(track.devices))
        if not 0 <= new_index < count:
            raise IndexError("%s has %d device(s): new_index goes from 0 to %d, not %d"
                             % (label, count, count - 1, new_index))
        if not hasattr(self._song, "move_device"):
            raise RuntimeError("Moving devices needs Live 11 or later")
        if new_index != device_index:
            # Live counts the target position with the device still in the
            # chain (measured in Live 12.4): moving right needs one more.
            position = new_index + 1 if new_index > device_index else new_index
            self._song.move_device(device, track, position)
        return {"moved": device.name, "from": device_index, "to": new_index, "on": label,
                "devices": self._chain_names(track)}

    @command("apply_device_state")
    def _apply_device_state(self, track_index, device_index, parameters, track_type="track"):
        """Restore saved parameter values: [{index, name, value}, ...]. Each
        entry is matched by index and checked by name (by name alone when
        the index moved); values outside a parameter's range are clamped."""
        device = self._device_on(track_index, device_index, track_type)
        params = list(device.parameters)
        by_name = dict((p.name, p) for p in params)
        applied, skipped = 0, []
        for entry in parameters or []:
            index, name = entry.get("index"), entry.get("name")
            param = params[index] if isinstance(index, int) and 0 <= index < len(params) \
                and params[index].name == name else by_name.get(name)
            if param is None or not self._safe_attr(param, "is_enabled", bool, True):
                skipped.append(name)
                continue
            value = min(max(float(entry["value"]), float(param.min)), float(param.max))
            if abs(float(param.value) - value) > 1e-9:
                param.value = value
            applied += 1
        return {"device": device.name, "applied": applied, "skipped": skipped}

    # -------------------------------------------------------------- drums
    def _find_drum_rack(self, devices, depth=0):
        for i, d in enumerate(devices):
            if getattr(d, "can_have_drum_pads", False):
                return d, i
            if depth < 2 and getattr(d, "can_have_chains", False):
                for chain in getattr(d, "chains", []):
                    found = self._find_drum_rack(getattr(chain, "devices", []), depth + 1)
                    if found[0] is not None:
                        return found[0], i
        return None, None

    @command("get_drum_rack_map")
    def _get_drum_rack_map(self, track_index):
        """Filled pads of the track's Drum Rack: note, name, what they hold."""
        track, label = self._resolve_track(track_index, "track")
        rack, index = self._find_drum_rack(list(track.devices))
        if rack is None:
            raise ValueError("No Drum Rack on %s" % label)
        pads = []
        for pad in rack.drum_pads:
            chains = list(getattr(pad, "chains", []) or [])
            if not chains:
                continue
            devices = []
            for chain in chains:
                devices += [dv.name for dv in getattr(chain, "devices", [])]
            pads.append({
                "note": int(pad.note),
                "name": str(pad.name),
                "devices": devices,
                "mute": self._safe_attr(pad, "mute", bool, False),
                "solo": self._safe_attr(pad, "solo", bool, False),
            })
        return {"track": label, "device_index": index, "rack_name": rack.name, "pads": pads}

    # ------------------------------------------------------------ devices
    def _resolve_device(self, track_index, device_index, track_type="track"):
        track, label = self._resolve_track(track_index, track_type)
        devices = list(track.devices)
        if device_index < 0 or device_index >= len(devices):
            raise IndexError("Device index out of range (%d devices on %s)" % (len(devices), label))
        return devices[device_index], "%s device %d" % (label, device_index)

    @staticmethod
    def _routing_dict(obj):
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get("display_name")
        return getattr(obj, "display_name", None)

    def _sidechain_info(self, device):
        if not hasattr(device, "available_input_routing_types"):
            return None
        info = {
            "source_type": self._routing_dict(self._safe_attr(device, "input_routing_type")),
            "source_channel": self._routing_dict(self._safe_attr(device, "input_routing_channel")),
            "available_types": [self._routing_dict(o) for o in
                                self._safe_attr(device, "available_input_routing_types", list, [])],
            "available_channels": [self._routing_dict(o) for o in
                                   self._safe_attr(device, "available_input_routing_channels", list, [])],
        }
        for p in device.parameters:
            if p.name.lower().replace(" ", "") in ("s/con", "sidechainon", "sidechain"):
                info["enable_parameter"] = {"name": p.name, "value": float(p.value)}
        return info

    @command("get_device_info")
    def _get_device_info(self, track_index, device_index, track_type="track"):
        """Identity and the device-specific API: sidechain routing (Compressor),
        plugin presets, Simpler sample and slicing, rack chains/variations."""
        device, label = self._resolve_device(track_index, device_index, track_type)
        info = {
            "device": label,
            "name": device.name,
            "class_name": device.class_name,
            "class_display_name": self._safe_attr(device, "class_display_name", str, None),
            "type": {0: "undefined", 1: "instrument", 2: "audio_effect", 4: "midi_effect"}.get(
                self._safe_attr(device, "type", int, 0), "undefined"),
            "is_active": self._safe_attr(device, "is_active", bool, True),
            "parameter_count": len(device.parameters),
            "latency_ms": self._safe_attr(device, "latency_in_ms", float, None),
        }
        sc = self._sidechain_info(device)
        if sc is not None:
            info["sidechain"] = sc
        if hasattr(device, "presets") and hasattr(device, "selected_preset_index"):
            presets = [str(p) for p in self._safe_attr(device, "presets", list, [])]
            info["plugin"] = {"presets": presets[:200], "preset_count": len(presets),
                              "selected_preset_index": self._safe_attr(device, "selected_preset_index", int, None)}
        if hasattr(device, "playback_mode") and hasattr(device, "sample"):
            sample = self._safe_attr(device, "sample")
            info["simpler"] = {
                "playback_mode": {0: "classic", 1: "one_shot", 2: "slicing"}.get(
                    self._safe_attr(device, "playback_mode", int, None)),
                "voices": self._safe_attr(device, "voices", int, None),
                "sample": None if sample is None else {
                    "file_path": self._safe_attr(sample, "file_path", str, None),
                    "length_frames": self._safe_attr(sample, "length", int, None),
                    "sample_rate": self._safe_attr(sample, "sample_rate", int, None),
                    "warping": self._safe_attr(sample, "warping", bool, None),
                    "slicing_style": {0: "transient", 1: "beat", 2: "region", 3: "manual"}.get(
                        self._safe_attr(sample, "slicing_style", int, None)),
                    "slice_count": len(self._safe_attr(sample, "slices", list, []) or []),
                },
            }
        if getattr(device, "can_have_chains", False):
            info["rack"] = {
                "chains": [str(c.name) for c in getattr(device, "chains", [])][:128],
                "drum_rack": bool(getattr(device, "can_have_drum_pads", False)),
                "visible_macros": self._safe_attr(device, "visible_macro_count", int, None),
                "variation_count": self._safe_attr(device, "variation_count", int, None),
                "selected_variation": self._safe_attr(device, "selected_variation_index", int, None),
            }
        return info

    @command("set_device_sidechain")
    def _set_device_sidechain(self, track_index, device_index, track_type="track",
                              source_type=None, source_channel=None, enable=True):
        """Route a device's sidechain input (Compressor in Live's API) from
        another track, by the names Live shows, and switch the sidechain on."""
        device, label = self._resolve_device(track_index, device_index, track_type)
        if not hasattr(device, "available_input_routing_types"):
            raise ValueError("%s (%s) has no sidechain routing in Live's API" % (label, device.class_name))
        if source_type is not None:
            options = list(device.available_input_routing_types)
            device.input_routing_type = self._match_routing(options, source_type, "sidechain source")
        if source_channel is not None:
            options = list(device.available_input_routing_channels)
            device.input_routing_channel = self._match_routing(options, source_channel, "sidechain channel")
        if enable is not None:
            for p in device.parameters:
                if p.name.lower().replace(" ", "") in ("s/con", "sidechainon", "sidechain"):
                    p.value = p.max if enable else p.min
        return dict(self._sidechain_info(device) or {}, device=label)

    @command("select_plugin_preset")
    def _select_plugin_preset(self, track_index, device_index, track_type="track",
                              preset_index=None, preset_name=None):
        device, label = self._resolve_device(track_index, device_index, track_type)
        if not hasattr(device, "selected_preset_index"):
            raise ValueError("%s is not a plug-in" % label)
        presets = [str(p) for p in list(device.presets)]
        if preset_name is not None:
            wanted = str(preset_name).lower()
            matches = [i for i, p in enumerate(presets) if p.lower() == wanted] or \
                      [i for i, p in enumerate(presets) if wanted in p.lower()]
            if not matches:
                raise ValueError("No preset matching '%s'" % preset_name)
            preset_index = matches[0]
        if preset_index is None or preset_index < 0 or preset_index >= len(presets):
            raise IndexError("Preset index out of range (%d presets)" % len(presets))
        device.selected_preset_index = int(preset_index)
        return {"device": label, "preset_index": int(preset_index), "preset": presets[int(preset_index)]}

    def _simpler(self, track_index, device_index):
        device, label = self._resolve_device(track_index, device_index, "track")
        if not hasattr(device, "playback_mode"):
            raise ValueError("%s is not a Simpler" % label)
        return device, label

    @command("simpler_replace_sample")
    def _simpler_replace_sample(self, track_index, device_index, file_path):
        device, label = self._simpler(track_index, device_index)
        if not file_path or not os.path.isabs(file_path) or not os.path.exists(file_path):
            raise ValueError("file_path must be an existing absolute path")
        device.replace_sample(file_path)
        return {"device": label, "loaded": file_path}

    @command("simpler_configure")
    def _simpler_configure(self, track_index, device_index, settings):
        """playback_mode classic|one_shot|slicing, slicing_style
        transient|beat|region|manual, slicing_sensitivity 0-1,
        slicing_beat_division, slicing_region_count, voices, warp_as (beats),
        crop/reverse (true)."""
        device, label = self._simpler(track_index, device_index)
        modes = {"classic": 0, "one_shot": 1, "slicing": 2}
        styles = {"transient": 0, "beat": 1, "region": 2, "manual": 3}
        sample = getattr(device, "sample", None)
        done = []
        for key, value in settings.items():
            if key == "playback_mode":
                device.playback_mode = modes[str(value)]
            elif key == "voices":
                device.voices = int(value)
            elif key in ("slicing_style", "slicing_sensitivity", "slicing_beat_division",
                         "slicing_region_count"):
                if sample is None:
                    raise ValueError("No sample loaded")
                setattr(sample, key, styles[str(value)] if key == "slicing_style" else value)
            elif key == "warp_as":
                device.warp_as(int(value))
            elif key in ("crop", "reverse") and value:
                getattr(device, key)()
            else:
                raise ValueError("Unknown Simpler setting '%s'" % key)
            done.append(key)
        info = self._get_device_info(track_index, device_index)
        info["changed"] = done
        return info

    @command("rack_variation")
    def _rack_variation(self, track_index, device_index, track_type="track", action="list", index=None):
        device, label = self._resolve_device(track_index, device_index, track_type)
        if not getattr(device, "can_have_chains", False):
            raise ValueError("%s is not a rack" % label)
        if action == "recall":
            device.selected_variation_index = int(index)
            device.recall_selected_variation()
        elif action == "store":
            device.store_variation()
        elif action == "randomize":
            device.randomize_macros()
        elif action != "list":
            raise ValueError("action must be list, recall, store or randomize")
        return {"device": label, "action": action,
                "variation_count": self._safe_attr(device, "variation_count", int, None),
                "selected_variation": self._safe_attr(device, "selected_variation_index", int, None),
                "macros": [{"name": p.name, "value": float(p.value)} for p in list(device.parameters)[1:17]]}

    @command("set_drum_choke")
    def _set_drum_choke(self, track_index, notes, group):
        """Put Drum Rack pads (by MIDI note) in a choke group (0 = none):
        the classic is closed and open hi-hat in the same group."""
        track, label = self._resolve_track(track_index, "track")
        rack, _ = self._find_drum_rack(list(track.devices))
        if rack is None:
            raise ValueError("No Drum Rack on %s" % label)
        done = []
        for pad in rack.drum_pads:
            if int(pad.note) in [int(n) for n in notes]:
                for chain in getattr(pad, "chains", []):
                    chain.choke_group = int(group)
                done.append({"note": int(pad.note), "name": str(pad.name), "choke_group": int(group)})
        return {"track": label, "pads": done}
