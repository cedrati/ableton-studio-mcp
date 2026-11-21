"""Devices: parameters, what is loaded in the set, knowledge sheets, and
device-specific controls (sidechain, plug-in presets, Simpler, racks, choke)."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from .. import live
from ..app import as_json, tool, track_target

log = logging.getLogger("ableton_studio_mcp")


@tool()
def get_device_parameters(track_index: int, device_index: int, track_type: str = "track") -> str:
    """
    Every parameter of a device with its index, value, range and the value
    as Live displays it (dB, Hz, %, mode names).

    Parameters:
    - track_index: The track (return index for "return", ignored for "master")
    - device_index: Position of the device in the chain
    - track_type: "track" (default), "return" or "master"
    """
    return as_json(live.call("get_device_parameters",
                             track_target(track_index, track_type, device_index=device_index)))


@tool()
def set_device_parameter(track_index: int, device_index: int, parameter_index: int,
                         value: float, track_type: str = "track") -> str:
    """
    Change one device parameter. Look up indexes and ranges with
    get_device_parameters; the reply shows the old and new values as Live
    displays them.

    Parameters:
    - track_index: The track (return index for "return", ignored for "master")
    - device_index: Position of the device in the chain
    - parameter_index: The parameter's index
    - value: New value, in the parameter's own range
    - track_type: "track" (default), "return" or "master"
    """
    reply = live.call("set_device_parameter", track_target(
        track_index, track_type, device_index=device_index, parameter_index=parameter_index, value=value))
    before = reply.get("old_display") or reply.get("old_value")
    after = reply.get("display") or reply.get("value")
    return f"{reply.get('name', 'Parameter')}: {before} → {after}"


@tool()
def device_inventory(installed_plugins: bool = False) -> str:
    """
    Everything loaded in the set — every device on every track, return track
    and the main track, racks with their chains — with what each one is and
    what it is for (native devices from the Live 12 manual, Max for Live
    devices, known plug-in families such as Arturia emulations), plus, with
    installed_plugins=true, the VST/VST3/AU plug-ins installed, by vendor.

    Parameters:
    - installed_plugins: Also list the installed plug-ins
    """
    try:
        from .. import device_knowledge as dk

        ableton = live.client()
        info = ableton.call("get_session_info")
        targets = [(i, "track") for i in range(int(info.get("track_count", 0)))]
        targets += [(i, "return") for i in range(int(info.get("return_track_count", 0)))]
        targets.append((0, "master"))
        tracks = []
        for index, tt in targets:
            params: Dict[str, Any] = {"track_index": index}
            if tt != "track":
                params["track_type"] = tt
            t = ableton.call("get_track_info", params)
            devices = []
            for d in t.get("devices", []):
                card = dk.describe_device(d)
                card["index"] = d.get("index")
                if d.get("class_name") in ("InstrumentGroupDevice", "AudioEffectGroupDevice",
                                           "MidiEffectGroupDevice", "DrumGroupDevice"):
                    try:
                        dp = dict(params, device_index=d["index"])
                        full = ableton.call("get_device_parameters", dp).get("device", {})
                        chains = full.get("chains") or []
                        card["chains"] = [{"name": c.get("chain_name") or c.get("name"),
                                           "devices": [x.get("name") for x in c.get("devices", [])]}
                                          for c in chains][:32]
                    except Exception:
                        pass
                devices.append(card)
            tracks.append({"track": t.get("name"), "type": tt, "index": index, "devices": devices})
        result: Dict[str, Any] = {"tracks": tracks, "midi_tools_note": dk.MIDI_TOOLS_NOTE}
        if installed_plugins:
            by_vendor: Dict[str, List[str]] = {}
            for fmt in ("VST3", "VST", "AUv2"):
                try:
                    root = ableton.call("get_browser_items_at_path", {"path": "plugins/" + fmt})
                except Exception:
                    continue
                for item in root.get("items", []):
                    if item.get("is_folder"):
                        sub = ableton.call("get_browser_items_at_path",
                                                   {"path": "plugins/%s/%s" % (fmt, item["name"])})
                        vendor = item["name"]
                        for x in sub.get("items", []):
                            by_vendor.setdefault(vendor, [])
                            if x["name"] not in by_vendor[vendor]:
                                by_vendor[vendor].append(x["name"])
            result["installed_plugins"] = {v: sorted(n) for v, n in sorted(by_vendor.items())}
        return as_json(result)
    except Exception as e:
        log.error(f"Error building the device inventory: {str(e)}")
        return f"Error building the device inventory: {str(e)}"


@tool()
def device_knowledge(name: str = None, kind: str = None) -> str:
    """
    What a device does: a native Live device (from the Live 12 manual: kind,
    category, purpose, key parameters, electronic/techno uses, sidechain,
    tip), a bundled Max for Live device, or a known plug-in (e.g. "Acid V",
    "Comp FET-76", "Cthulhu"). Without `name`, the catalogue of native
    devices, optionally filtered by kind (instrument, audio_effect,
    midi_effect, max_for_live). Also says what Live 12's MIDI Tools are and
    that the API can't drive them.

    Parameters:
    - name: Device or plug-in name
    - kind: Filter for the catalogue
    """
    from .. import device_knowledge as dk

    if name:
        entry = dk.lookup(name)
        return as_json(entry) if entry else "No sheet for '%s' (maybe a third-party plug-in: check its parameters)" % name
    return as_json({"devices": dk.catalog(kind), "midi_tools": dk.MIDI_TOOLS_NOTE})


def _device_call(command: str, params: Dict[str, Any], track_type: str = "track") -> Dict[str, Any]:
    """Send a device command to a track, return track or the main track."""
    live.require(command)
    return live.call(command, track_target(params.pop("track_index"), track_type, **params))


@tool()
def get_device_info(track_index: int, device_index: int, track_type: str = "track") -> str:
    """
    One device's identity (Live's real device name even when a preset renamed
    it, kind, latency) and its specific API: sidechain routing and options
    (Compressor), plug-in presets, Simpler sample/slicing state, rack chains
    and variations.

    Parameters:
    - track_index / device_index: The device
    - track_type: "track", "return" or "master"
    """
    return as_json(_device_call("get_device_info", {"track_index": track_index, "device_index": device_index},
                       track_type))


@tool()
def set_device_sidechain(track_index: int, device_index: int, source: str,
                         channel: str = None, enable: bool = True, track_type: str = "track") -> str:
    """
    Feed a Compressor's sidechain from another track (e.g. duck the bass or
    pads with the kick) and switch its sidechain on. `source` is the name of
    the track as Live lists it (see get_device_info: sidechain.available_types),
    `channel` e.g. "Post FX" / "Pre FX". Live's API exposes sidechain routing
    on the Compressor; other devices with a sidechain (Gate, Glue, Auto
    Filter...) are routed in the interface.

    Parameters:
    - track_index / device_index: The Compressor
    - source: Sidechain source track name (exact, or a unique part of it)
    - channel: Source tap (optional)
    - enable: Turn the sidechain on (default) or off
    - track_type: "track", "return" or "master"
    """
    params = {"track_index": track_index, "device_index": device_index, "source_type": source,
              "enable": enable}
    if channel is not None:
        params["source_channel"] = channel
    return as_json(_device_call("set_device_sidechain", params, track_type))


@tool()
def plugin_presets(track_index: int, device_index: int, preset_index: int = None,
                   preset_name: str = None, track_type: str = "track") -> str:
    """
    A VST/AU plug-in's preset list (as the plug-in exposes it to Live), or
    select one by index or name (exact, else first containing the text).

    Parameters:
    - track_index / device_index: The plug-in
    - preset_index / preset_name: Preset to load (omit both to list)
    - track_type: "track", "return" or "master"
    """
    if preset_index is None and preset_name is None:
        info = _device_call("get_device_info", {"track_index": track_index, "device_index": device_index},
                            track_type)
        return as_json(info.get("plugin") or {"error": "not a plug-in"})
    params = {"track_index": track_index, "device_index": device_index}
    if preset_index is not None:
        params["preset_index"] = preset_index
    if preset_name is not None:
        params["preset_name"] = preset_name
    return as_json(_device_call("select_plugin_preset", params, track_type))


@tool()
def simpler_sample(track_index: int, device_index: int, file_path: str = None,
                   playback_mode: str = None, slicing_style: str = None, slicing_sensitivity: float = None,
                   slicing_beat_division: int = None, slicing_region_count: int = None, voices: int = None,
                   warp_as_beats: int = None, crop: bool = False, reverse: bool = False) -> str:
    """
    Load a sample into a Simpler and set it up: playback mode (classic,
    one_shot, slicing), slicing by transient / beat / region / manual with
    sensitivity, beat division or region count (e.g. chop a break into 16
    slices playable from a Drum Rack-like MIDI layout), voices, warp the
    sample as N beats, crop, reverse.

    Parameters:
    - track_index / device_index: The Simpler
    - file_path: Absolute path of an audio file to load (optional)
    - playback_mode: classic | one_shot | slicing
    - slicing_style: transient | beat | region | manual
    - slicing_sensitivity: 0-1 (transient mode)
    - slicing_beat_division: Live's beat division index (beat mode)
    - slicing_region_count: Number of slices (region mode)
    - voices: Polyphony
    - warp_as_beats: Warp the sample to this many beats
    - crop / reverse: Destructive edits of the sample in Simpler
    """
    out = {}
    if file_path:
        loaded = _device_call("simpler_replace_sample", {"track_index": track_index, "device_index": device_index,
                                                         "file_path": os.path.expanduser(file_path)})
        out["loaded"] = loaded.get("loaded")
    settings: Dict[str, Any] = {}
    for key, value in (("playback_mode", playback_mode), ("slicing_style", slicing_style),
                       ("slicing_sensitivity", slicing_sensitivity),
                       ("slicing_beat_division", slicing_beat_division),
                       ("slicing_region_count", slicing_region_count), ("voices", voices),
                       ("warp_as", warp_as_beats)):
        if value is not None:
            settings[key] = value
    if crop:
        settings["crop"] = True
    if reverse:
        settings["reverse"] = True
    if settings:
        out.update(_device_call("simpler_configure", {"track_index": track_index, "device_index": device_index,
                                                      "settings": settings}))
    return as_json(out) if out else "Nothing to do: give file_path and/or settings"


@tool()
def rack_variation(track_index: int, device_index: int, action: str = "list",
                   index: int = None, track_type: str = "track") -> str:
    """
    A rack's macro variations (Live 11+): list them with the current macro
    values, recall one, store the current macros as a new variation, or
    randomize the macros (great for happy accidents, then store the result).

    Parameters:
    - track_index / device_index: The rack
    - action: list | recall | store | randomize
    - index: Variation to recall
    - track_type: "track", "return" or "master"
    """
    return as_json(_device_call("rack_variation", {"track_index": track_index, "device_index": device_index,
                                          "action": action, "index": index}, track_type))


@tool()
def set_drum_choke(track_index: int, notes: List[int], group: int = 1) -> str:
    """
    Put Drum Rack pads in a choke group so they cut each other — the classic:
    closed and open hi-hat together (e.g. notes [42, 46], group 1). Group 0
    removes the choke.

    Parameters:
    - track_index: Track with the Drum Rack
    - notes: Pad MIDI notes (see get_drum_map)
    - group: Choke group 1-16, or 0 for none
    """
    return as_json(_device_call("set_drum_choke", {"track_index": track_index, "notes": notes, "group": group}))


# Main execution
