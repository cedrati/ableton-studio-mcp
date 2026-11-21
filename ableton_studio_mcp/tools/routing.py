"""Tracks' audio/MIDI routing and monitoring."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from .. import live
from ..app import tool, track_target

log = logging.getLogger("ableton_studio_mcp")


@tool()
def get_track_routing(track_index: int, track_type: str = "track") -> str:
    """
    Read a track's input/output routing and monitoring, with the options Live
    offers for each (names as shown in Live's I/O section, in Live's language).

    Parameters:
    - track_index: Index of the track (return index for "return", ignored for "master")
    - track_type: "track" (default), "return" or "master" (these two only have an output)
    """
    try:
        live.require("get_track_routing")
        params: Dict[str, Any] = {"track_index": track_index}
        params = track_target(params.pop("track_index"), track_type, **params)
        result = live.client().call("get_track_routing", params)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        log.error(f"Error getting track routing: {str(e)}")
        return f"Error getting track routing: {str(e)}"


@tool()
def set_track_routing(track_index: int,
    input_type: str = None,
    input_channel: str = None,
    output_type: str = None,
    output_channel: str = None,
    monitoring: str = None,
    track_type: str = "track",
) -> str:
    """
    Set a track's input/output routing and monitoring. Arguments left out are
    untouched. Names are matched against the options get_track_routing lists:
    exact (case-insensitive) first, else a unique substring.

    Examples:
    - Layer one MIDI part on several instruments: on each extra MIDI track,
      input_type="<name of the source MIDI track>", monitoring="in".
    - Record the main output (resampling): on an audio track,
      input_type="Resampling" (French Live: "Rééchantillonnage").
    - Send a track to a return or another track: output_type="<track name>".

    Parameters:
    - track_index: Index of the track (return index for "return")
    - input_type / input_channel: Input routing ("MIDI From" / "Audio From")
    - output_type / output_channel: Output routing ("MIDI To" / "Audio To")
    - monitoring: "in", "auto" or "off"
    - track_type: "track" (default), "return" or "master" (output only)
    """
    try:
        live.require("set_track_routing")
        params: Dict[str, Any] = {"track_index": track_index}
        for key, value in (("input_type", input_type), ("input_channel", input_channel),
                           ("output_type", output_type), ("output_channel", output_channel),
                           ("monitoring", monitoring)):
            if value is not None:
                params[key] = value
        params = track_target(params.pop("track_index"), track_type, **params)
        result = live.client().call("set_track_routing", params)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        log.error(f"Error setting track routing: {str(e)}")
        return f"Error setting track routing: {str(e)}"
