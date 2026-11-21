"""Live's browser, and loading what it holds onto tracks."""

from __future__ import annotations

from .. import live
from ..app import as_json, describe_target, tool, track_target

BROWSER_ROOTS = ("instruments, sounds, drums, audio_effects, midi_effects, plugins (VST/AU), "
                 "user_library, packs, samples, max_for_live, current_project")


def _outline(node: dict, depth: int = 0) -> list[str]:
    line = "  " * depth + "• " + node.get("name", "?")
    if node.get("path"):
        line += f"  ({node['path']})"
    if node.get("has_more"):
        line += "  …"
    lines = [line]
    for child in node.get("children", []):
        lines += _outline(child, depth + 1)
    return lines


@tool()
def get_browser_tree(category_type: str = "all") -> str:
    """
    The folders of Live's browser, as an indented outline with the path of
    each folder (use the paths with get_browser_items_at_path).

    Parameters:
    - category_type: "all", or one root: instruments, sounds, drums,
      audio_effects, midi_effects, plugins, user_library, packs, samples,
      max_for_live, current_project
    """
    reply = live.call("get_browser_tree", {"category_type": category_type})
    roots = reply.get("categories", [])
    if not roots:
        offered = ", ".join(reply.get("available_categories", [])) or BROWSER_ROOTS
        return f"Nothing under '{category_type}'. Browser roots: {offered}"
    lines = [f"Browser — {category_type} ({reply.get('total_folders', '?')} folders)", ""]
    for root in roots:
        lines += _outline(root) + [""]
    return "\n".join(lines)


@tool()
def get_browser_items_at_path(path: str) -> str:
    """
    What a browser folder contains, with each item's URI and whether it can
    be loaded (load it with load_instrument_or_effect).

    Parameters:
    - path: "root/folder/subfolder", e.g. "drums/Drum Rack" or "plugins/Arturia".
      Roots: instruments, sounds, drums, audio_effects, midi_effects, plugins,
      user_library, packs, samples, max_for_live, current_project
    """
    reply = live.call("get_browser_items_at_path", {"path": path})
    if "error" in reply:
        offered = ", ".join(reply.get("available_categories", [])) or BROWSER_ROOTS
        return f"{reply['error']}. Browser roots: {offered}"
    return as_json(reply)


@tool()
def load_instrument_or_effect(track_index: int, uri: str, track_type: str = "track") -> str:
    """
    Load a browser item — instrument, effect, preset, plug-in, User Library
    file — onto a track, by its URI. Effects can also go on a return track
    (track_type="return", track_index 0 = A) or on the main track
    (track_type="master"). Find URIs with get_browser_items_at_path.

    Parameters:
    - track_index: The track (return index for "return", ignored for "master")
    - uri: The item's URI, e.g. "query:Synths#Operator"
    - track_type: "track" (default), "return" or "master"
    """
    params = track_target(track_index, track_type, item_uri=uri)
    where = describe_target(track_index, track_type)
    reply = live.call("load_browser_item", params)
    if not reply.get("loaded"):
        return f"Live did not load '{uri}' on {where}"
    chain = ", ".join(reply.get("devices_after", [])) or "none"
    if reply.get("in_place"):
        if reply.get("settled"):
            return f"'{uri}' was already on {where}: Live reloaded it in place and reset its parameters"
        return (f"'{uri}' was already on {where}: Live reloads an identical device in place and no "
                f"parameter changed (they may already be at their defaults). Chain: {chain}")
    if reply.get("new_devices"):
        return f"Loaded '{uri}' on {where}: {', '.join(reply['new_devices'])}"
    if reply.get("settled") is False:
        return (f"Asked Live to load '{uri}' on {where}, but the chain had not changed yet "
                f"({chain}); check with get_track_info")
    return f"Loaded '{uri}' on {where}. Chain: {chain}"


@tool()
def load_drum_kit(track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a Drum Rack, then the first loadable kit found in a browser folder.

    Parameters:
    - track_index: A MIDI track
    - rack_uri: URI of the Drum Rack to load first
    - kit_path: Browser folder holding the kits, e.g. "drums/Drum Hits"
    """
    if not live.call("load_browser_item", {"track_index": track_index, "item_uri": rack_uri}).get("loaded"):
        return f"Live did not load the rack '{rack_uri}'"
    folder = live.call("get_browser_items_at_path", {"path": kit_path})
    if "error" in folder:
        return f"Rack loaded, but the kit folder failed: {folder['error']}"
    kit = next((item for item in folder.get("items", []) if item.get("is_loadable")), None)
    if kit is None:
        return f"Rack loaded, but nothing loadable in '{kit_path}'"
    live.call("load_browser_item", {"track_index": track_index, "item_uri": kit["uri"]})
    return f"Rack and kit '{kit.get('name')}' loaded on track {track_index}"
