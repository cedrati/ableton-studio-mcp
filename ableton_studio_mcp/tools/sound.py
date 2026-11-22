"""Sound design: Live's presets, musical parameter values, recipes, auditioning and saved sounds."""

from __future__ import annotations

from typing import Dict, Union

from .. import live, presets, recipes, sounds
from ..app import as_json, tool, track_target


@tool()
def find_presets(query: str = "", device: str = "", kind: str = "", library: str = "",
                 limit: int = 40) -> str:
    """
    Search the presets of Live's native instruments, effects and racks: the
    Core Library, installed packs and the User Library (several thousand
    files). Every word of the query must appear in the preset's name, device,
    category or library. Read one with read_preset.

    Parameters:
    - query: Words to look for, e.g. "dark bass", "plate", "909"
    - device: Only this device's presets, e.g. "Drift", "Operator", "Wavetable", "Reverb"
    - kind: instrument, audio_effect, midi_effect, rack, drum_rack
    - library: "Core Library", "User Library", or part of a pack name
    - limit: Maximum results (default 40)
    """
    found = presets.find_presets(query, device, kind, library, max(1, min(limit, 200)))
    if not found:
        return f"No preset matches '{query}'" + (f" for {device}" if device else "")
    return as_json({"count": len(found), "presets": found})


@tool()
def read_preset(preset: str, detail: str = "changes") -> str:
    """
    What a native device or rack preset does, read from its file: the device,
    the parameters that make the sound (compared with the device's default
    preset, in the device's own units: Hz, seconds, dB, percent or 0–1),
    samples used, and for racks the named macros and every chain with its
    devices. Use it to learn from factory sounds before designing new ones.

    Parameters:
    - preset: A preset name ("Star Dust Strings") or the path of a .adv / .adg file
    - detail: "changes" (default: what differs from the default device) or "full"
    """
    if detail not in ("changes", "full"):
        raise ValueError("detail must be 'changes' or 'full'")
    return as_json(presets.read_preset(presets.resolve(preset), detail))


# ── loading presets into Live ────────────────────────────────────────────────

_SECTION_FOR_FOLDER = {"instruments": "instruments", "audio effects": "audio_effects",
                       "midi effects": "midi_effects"}
# Core Library rack folders: where the browser shows them, and which section
# to search when the category folder has another name in the browser.
_RACK_PLACES = {
    "instrument racks": (["sounds/{cat}", "instruments/Instrument Rack/{cat}"], "sounds"),
    "audio effect racks": (["audio_effects/Audio Effect Rack/{cat}"], "audio_effects"),
    "midi effect racks": (["midi_effects/MIDI Effect Rack/{cat}"], "midi_effects"),
    "drum racks": (["drums"], "drums"),
}
_SECTION_FOR_KIND = {"instrument": "instruments", "audio_effect": "audio_effects",
                     "midi_effect": "midi_effects", "drum_rack": "drums", "rack": "sounds"}


def _browser_places(found: presets.PresetFile) -> tuple[list[str], list[str]]:
    """(folders of Live's browser that may hold the preset, sections to search
    if none does)."""
    for label, root in presets.libraries():
        if label != found.library:
            continue
        parts = list(found.path.relative_to(root).parts)
        if label == "User Library":
            return ["/".join(["user_library"] + parts[:-1])], ["user_library"]
        if label.startswith("Pack: "):
            return ["/".join(["packs", root.name] + parts[:-1])], ["packs"]
        if parts[:1] == ["Devices"] and len(parts) > 2:
            section = _SECTION_FOR_FOLDER.get(parts[1].lower())
            if section:
                return ["/".join([section] + parts[2:-1])], [section]
        if parts[:1] == ["Racks"] and len(parts) > 2:
            folders, section = _RACK_PLACES.get(parts[1].lower(), ([], "sounds"))
            category = parts[2] if len(parts) > 3 else ""
            return [f.format(cat=category).rstrip("/") for f in folders], [section]
    section = _SECTION_FOR_KIND.get(found.kind)
    return [], [section] if section else []


def _preset_entry(preset: str) -> presets.PresetFile:
    path = presets.resolve(preset)
    for entry in presets.index():
        if entry.path == path:
            return entry
    return presets._describe_path(path, path.parent, "file")


@tool(needs="load_browser_item")
def load_preset(track_index: int, preset: str, track_type: str = "track") -> str:
    """
    Load a native device or rack preset onto a track by its name or file path
    (find names with find_presets). Effects can go on a return track or the
    main track.

    Parameters:
    - track_index: The track (return index for "return", ignored for "master")
    - preset: Preset name ("Star Dust Strings") or .adv / .adg path
    - track_type: "track" (default), "return" or "master"
    """
    from . import browser as browser_tools   # load_instrument_or_effect does the loading
    entry = _preset_entry(preset)
    filename = entry.path.name.lower()
    folders, sections = _browser_places(entry)
    uri = None
    for folder in folders:
        listing = live.call("get_browser_items_at_path", {"path": folder})
        uri = next((i["uri"] for i in listing.get("items", []) if i["name"].lower() == filename), None)
        if uri:
            break
    if uri is None:
        live.require("find_browser_items")
        hits = live.call("find_browser_items", {"name": entry.path.name, "sections": sections or None,
                                                "limit": 1}).get("items", [])
        if not hits:
            raise ValueError(f"Live's browser has no item called '{entry.path.name}'"
                             + (f" in {', '.join(sections)}" if sections else ""))
        uri = hits[0]["uri"]
    return browser_tools.load_instrument_or_effect.__wrapped__(track_index, uri, track_type)


@tool(needs="set_device_parameters")
def set_device_parameters(track_index: int, device_index: int,
                          values: Dict[str, Union[float, str]], track_type: str = "track") -> str:
    """
    Set several parameters of a device at once, by name, with musical values:
    "800 Hz", "2.5 kHz", "5 ms", "1.2 s", "-6 dB", "30 %", "+7 st", a named
    setting ("Bell", "Alg. 11", "Sine") or a number in the parameter's own
    range. Names come from get_device_parameters ("LP Freq", "Attack"); a
    unique part of a name is enough. Every value is checked before anything
    changes, and the reply shows each parameter as Live displays it.

    Parameters:
    - track_index: The track (return index for "return", ignored for "master")
    - device_index: The device's position in the chain
    - values: {"LP Freq": "800 Hz", "LP Res": "35 %", "Env 1 Attack": "5 ms"}
    - track_type: "track" (default), "return" or "master"
    """
    reply = live.call("set_device_parameters", track_target(
        track_index, track_type, device_index=device_index, values=values))
    lines = [f"{c['name']}: {c['was']} → {c['now']}" for c in reply.get("changes", [])]
    return f"{reply.get('device', 'Device')}:\n" + "\n".join(lines)


# ── the assistant's own sounds ───────────────────────────────────────────────

@tool(needs="get_device_parameters")
def save_sound(track_index: int, device_index: int, name: str, description: str = "",
               overwrite: bool = False, track_type: str = "track") -> str:
    """
    Save the current settings of a native device as a named sound, to load it
    again later on any track with load_sound. (Live's API can't write real
    presets; to keep one as a Live preset too, click the device's Save Preset
    button in Live.) Racks aren't supported yet: save the devices inside them.

    Parameters:
    - track_index / device_index: The device to save
    - name: The sound's name ("Rolling Sub", "Dub Chord Stab")
    - description: What it is for, how it sounds
    - overwrite: Replace a sound saved earlier under the same name
    - track_type: "track" (default), "return" or "master"
    """
    info = live.call("get_device_parameters", track_target(track_index, track_type, device_index=device_index))
    device = info["device"]
    if device.get("type") in ("rack", "drum_machine") or device.get("chains"):
        raise ValueError(f"'{device['name']}' is a rack: save the devices inside it one by one")
    listing = live.call("get_track_info", track_target(track_index, track_type))["devices"]
    real = next((d for d in listing if d["index"] == device_index), {})
    kind = real.get("class_display_name") or device["class_name"]
    path = sounds.save(name, kind, device["class_name"], device.get("parameters", []), description, overwrite)
    return f"Saved '{name}' ({kind}, {len(device.get('parameters', []))} parameters) to {path}"


@tool()
def list_sounds(query: str = "", device: str = "") -> str:
    """
    The sounds saved with save_sound, optionally filtered.

    Parameters:
    - query: Words to look for in the name, device or description
    - device: Only sounds for this device ("Drift", "Operator")
    """
    found = sounds.list_sounds(query, device)
    return as_json({"count": len(found), "sounds": found}) if found else "No saved sound matches"


def _device_uri(display_name: str, device_class: str) -> str:
    for section in ("instruments", "audio_effects", "midi_effects"):
        items = live.call("get_browser_items_at_path", {"path": section}).get("items", [])
        hit = next((i for i in items if i["is_loadable"] and i["name"].lower() == display_name.lower()), None)
        if hit:
            return hit["uri"]
    raise ValueError(f"Live's browser has no device called '{display_name}' ({device_class})")


@tool(needs=("load_browser_item", "apply_device_state"), undo_step="Load sound")
def load_sound(track_index: int, name: str, track_type: str = "track") -> str:
    """
    Put a sound saved with save_sound on a track: loads its device, then
    restores every parameter. One undo takes it all back.

    Parameters:
    - track_index: The track (return index for "return", ignored for "master")
    - name: The sound's name (see list_sounds)
    - track_type: "track" (default), "return" or "master"
    """
    data = sounds.load(name)
    uri = _device_uri(data["device"], data["device_class"])
    loaded = live.call("load_browser_item", track_target(track_index, track_type, item_uri=uri))
    if not loaded.get("loaded"):
        raise ValueError(f"Live did not load {data['device']}")
    devices = live.call("get_track_info", track_target(track_index, track_type))["devices"]
    target = [d for d in devices if d["class_name"] == data["device_class"]]
    if not target:
        raise ValueError(f"{data['device']} did not appear on the track")
    index = target[-1]["index"]
    applied = live.call("apply_device_state", track_target(
        track_index, track_type, device_index=index, parameters=data["parameters"]))
    skipped = f" ({len(applied['skipped'])} not restored: {', '.join(applied['skipped'][:5])})" if applied["skipped"] else ""
    return f"'{data['name']}' loaded: {data['device']} at position {index}, {applied['applied']} parameters restored{skipped}"


# ── recipes and the listen-and-tune loop ─────────────────────────────────────

@tool()
def sound_recipes(name: str = "") -> str:
    """
    Starting points for classic electronic sounds on Live's native synths
    (sub bass, acid bass, reese, dub chord stab, pluck, warm pad, supersaw,
    FM bell): device, parameter values, how to play it, what to listen for.
    Without a name, lists them.

    Parameters:
    - name: A recipe ("acid_bass") to see in full
    """
    if name:
        return as_json(dict(recipes.recipe(name), name=name))
    return as_json([{"name": k, "device": r["device"], "role": r["role"], "description": r["description"]}
                    for k, r in sorted(recipes.RECIPES.items())])


@tool(needs=("load_browser_item", "set_device_parameters"), undo_step="Design sound")
def design_sound(track_index: int, recipe: str, tweaks: Union[Dict[str, Union[float, str]], None] = None) -> str:
    """
    Build a sound from a recipe on a MIDI track: loads the recipe's synth and
    sets its parameters, then applies your tweaks (musical values, as for
    set_device_parameters). One undo step. Then audition_sound it, adjust
    with set_device_parameters, and save_sound when it's right.

    Parameters:
    - track_index: A MIDI track (the synth is added to its chain)
    - recipe: A recipe name (see sound_recipes)
    - tweaks: Extra values on top of the recipe, e.g. {"LP Freq": "500 Hz"}
    """
    r = recipes.recipe(recipe)
    loaded = live.call("load_browser_item", {"track_index": track_index, "item_uri": r["uri"]})
    if not loaded.get("loaded"):
        raise ValueError(f"Live did not load {r['device']}")
    devices = live.call("get_track_info", {"track_index": track_index})["devices"]
    index = max(d["index"] for d in devices if d["name"] == r["device"] or d.get("class_display_name") == r["device"])
    values = dict(r["values"], **(tweaks or {}))
    reply = live.call("set_device_parameters", {"track_index": track_index, "device_index": index, "values": values})
    return as_json({"recipe": recipe, "device": r["device"], "device_index": index,
                    "set": {c["name"]: c["now"] for c in reply["changes"]},
                    "play": r["play"], "listen_for": r["listen"]})


@tool(needs=("create_clip", "duplicate_session_clip_to_arrangement", "record_arrangement"),
      undo_step="Audition sound")
def audition_sound(track_index: int, role: str = "melody", root: Union[int, None] = None,
                   bars: int = 1, report: str = "mix"):
    """
    Listen to a track's sound: plays a short test phrase on it (a bass line,
    chords or an arpeggio) in an empty stretch after the end of the song,
    records and analyses it like listen_to_arrangement (loudness, spectrum,
    spectrogram), then removes everything it added. Use the report to adjust
    the sound with set_device_parameters, and audition again.

    Parameters:
    - track_index: The MIDI track to audition
    - role: "bass", "chords" or "melody": picks the phrase and its register
    - root: MIDI note of the phrase's root (default C1 for bass, C3 chords, C4 melody)
    - bars: How many bars to play (1–4)
    - report: "mix" (full report and spectrogram) or "basic"
    """
    from . import listening
    if role not in recipes.PHRASES:
        raise ValueError("role must be 'bass', 'chords' or 'melody'")
    bars = max(1, min(int(bars), 4))
    track = live.call("get_track_info", {"track_index": track_index})
    slot = next((s["index"] for s in track["clip_slots"] if not s["has_clip"]), None)
    if slot is None:
        raise ValueError(f"Track {track_index} has no empty clip slot for the test phrase")
    length = 4.0 * bars
    notes = [dict(n, start_time=n["start_time"] + 4.0 * b) for b in range(bars) for n in recipes.phrase(role, root)]
    song_end = float(live.call("get_session_info").get("song_length") or 0.0)
    start = (int(song_end // 4) + 2) * 4.0          # two bars after the last bar of the song
    live.call("create_clip", {"track_index": track_index, "clip_index": slot, "length": length})
    try:
        live.call("add_notes_to_clip", {"track_index": track_index, "clip_index": slot, "notes": notes})
        live.call("duplicate_session_clip_to_arrangement",
                  {"track_index": track_index, "clip_index": slot, "destination_time": start})
        result = listening.listen_to_arrangement.__wrapped__(start, start + length + 2.0, report=report)
    finally:
        clips = live.call("get_arrangement_clips", {"track_index": track_index}).get("clips", [])
        for i, clip in reversed(list(enumerate(clips))):
            if abs(clip["start_time"] - start) < 1e-3:
                live.call("delete_arrangement_clip", {"track_index": track_index, "clip_index": i})
        live.call("delete_clip", {"track_index": track_index, "clip_index": slot})
    header = (f"Auditioned track {track_index} ({track['name']}): {role} phrase, {bars} bar(s), "
              f"root {notes[0]['pitch']}, played after the song at beat {start:g}.")
    if isinstance(result, list):
        return [header + "\n" + result[0]] + result[1:]
    return header + "\n" + result
