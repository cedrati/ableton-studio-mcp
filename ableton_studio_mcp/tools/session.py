"""The song as a whole: overview, tempo, transport, scenes, locators."""

from __future__ import annotations

from .. import SCRIPT_SERIES, __version__, live
from ..app import as_json, compact, tool


@tool()
def get_session_info() -> str:
    """
    Overview of the Live set: tempo, time signature, track and return counts,
    main track, transport state, song length and loop.
    """
    return as_json(live.call("get_session_info"))


@tool()
def get_remote_script_info() -> str:
    """
    Version and command list of the AbletonStudioMCP control surface running
    in Live, compared with this server. Use it when tools say Live is too old
    or not responding (`ableton-studio-mcp doctor` checks the whole setup).
    """
    client = live.client()
    info = dict(client.call("get_script_info"))
    client.info = live.ScriptInfo(info.get("script_version"),
                                  frozenset(info.get("capabilities") or ()), info)
    info["server_version"] = __version__
    info["expected_version"] = f"{SCRIPT_SERIES}.x"
    info["up_to_date"] = client.info.up_to_date
    return as_json(info)


@tool(needs="get_session_snapshot")
def get_session_snapshot(include_notes: bool = True, include_params: bool = True) -> str:
    """
    Everything in the set at once: every track with its mixer, devices,
    Session and Arrangement clips, plus scenes, returns, the main track and
    locators. Handy to compare the set before and after a series of edits.

    Parameters:
    - include_notes: Include the MIDI notes of every clip (default true)
    - include_params: Include every device parameter value (default true)
    """
    return as_json(live.call("get_session_snapshot",
                             {"include_notes": include_notes, "include_params": include_params}))


@tool()
def set_tempo(tempo: float) -> str:
    """
    Change the song tempo.

    Parameters:
    - tempo: Beats per minute (Live accepts 20–999)
    """
    live.call("set_tempo", {"tempo": tempo})
    return f"Tempo is now {tempo} BPM"


@tool()
def start_playback() -> str:
    """Start the transport (plays from the playhead)."""
    live.call("start_playback")
    return "Playing"


@tool()
def stop_playback() -> str:
    """Stop the transport."""
    live.call("stop_playback")
    return "Stopped"


@tool()
def switch_to_arrangement_view() -> str:
    """Bring Live's Arrangement view to the front."""
    live.call("switch_to_arrangement_view")
    return "Arrangement view shown"


@tool()
def set_arrangement_time(time: float) -> str:
    """
    Move the playhead.

    Parameters:
    - time: Song position in beats (0 = start; in 4/4, bar N starts at 4 × (N − 1))
    """
    reply = live.call("set_current_song_time", {"time": time})
    now = reply.get("current_song_time", time)
    if reply.get("settled") is False:
        return f"Asked Live to move the playhead to beat {time}; it still reports beat {now}"
    return f"Playhead at beat {now}"


# ── locators ─────────────────────────────────────────────────────────────────

@tool(needs="create_locator")
def create_locator(name: str, time: float) -> str:
    """
    Put a named locator in the Arrangement. A locator already at that beat is
    renamed rather than removed. Playback must be stopped.

    Parameters:
    - name: Label shown in Live ("Intro", "Drop", "Break"...)
    - time: Song position in beats
    """
    reply = live.call("create_locator", {"name": name, "time": time})
    return f"Locator '{reply.get('name', name)}' at beat {reply.get('time', time)}"


@tool(needs="delete_locator")
def delete_locator(name: str = "", time: float | None = None) -> str:
    """
    Remove a locator, found by position (exact) or by name. When several
    locators share the name nothing is removed and their positions are listed.
    Playback must be stopped.

    Parameters:
    - name: Label of the locator
    - time: Its song position in beats (wins over name)
    """
    if time is None and not name:
        return "Give the locator's name or its time (beat position)."
    reply = live.call("delete_locator", {"time": time} if time is not None else {"name": name})
    return f"Locator '{reply.get('name') or '(unnamed)'}' at beat {reply.get('time')} deleted"


# ── scenes ───────────────────────────────────────────────────────────────────

@tool(needs="get_scenes")
def get_scenes() -> str:
    """List the Session scenes with their index, name and tempo."""
    return as_json(live.call("get_scenes"))


@tool(needs="create_scene")
def create_scene(index: int = -1) -> str:
    """
    Add an empty scene.

    Parameters:
    - index: Where to insert it (-1 = after the last scene)
    """
    return as_json(live.call("create_scene", {"index": index}))


@tool(needs="delete_scene")
def delete_scene(scene_index: int) -> str:
    """
    Remove a scene together with every clip in its row. Ask the user first.

    Parameters:
    - scene_index: The scene to remove
    """
    return as_json(live.call("delete_scene", {"scene_index": scene_index}))


@tool(needs="duplicate_scene")
def duplicate_scene(scene_index: int) -> str:
    """
    Copy a scene and its clips; the copy goes right below it.

    Parameters:
    - scene_index: The scene to copy
    """
    return as_json(live.call("duplicate_scene", {"scene_index": scene_index}))


@tool(needs="fire_scene")
def fire_scene(scene_index: int) -> str:
    """
    Launch every clip in a scene's row.

    Parameters:
    - scene_index: The scene to launch
    """
    return as_json(live.call("fire_scene", {"scene_index": scene_index}))


@tool(needs="set_scene_name")
def set_scene_name(scene_index: int, name: str) -> str:
    """
    Rename a scene.

    Parameters:
    - scene_index: The scene to rename
    - name: Its new name
    """
    return as_json(live.call("set_scene_name", compact(scene_index=scene_index, name=name)))
