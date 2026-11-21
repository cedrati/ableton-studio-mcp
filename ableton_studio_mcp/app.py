"""The MCP application and the helpers every tool module shares.

A tool is a plain function decorated with :func:`tool`. The decorator
registers it with the MCP server, checks that the control surface in Live
supports the commands it needs, and turns failures into one readable line
for the assistant instead of a stack trace.
"""

from __future__ import annotations

import functools
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Callable, Iterable

from mcp.server.fastmcp import FastMCP

from . import live

log = logging.getLogger("ableton_studio_mcp")


@asynccontextmanager
async def _lifespan(_server: FastMCP):
    # Live is reached lazily, by the first tool that needs it: the server
    # starts and answers instantly even when Live is closed or unreachable
    # (an MCP client listing tools, a directory checking the server).
    try:
        yield {}
    finally:
        live.client().close()


mcp = FastMCP("Ableton Studio MCP", lifespan=_lifespan)

# Failures the assistant can act on: the message itself is the answer.
_EXPECTED = (live.LiveUnavailable, live.MissingCapability)


def guard(fn: Callable, needs: Iterable[str] = ()) -> Callable:
    """Wrap a tool body: check the commands it needs, then run it, turning
    failures into one readable line. Live refusing a command, or a bad
    argument (ValueError), comes back as "<tool> failed: <reason>"."""
    required = tuple(needs)

    @functools.wraps(fn)
    def run(*args, **kwargs):
        try:
            for capability in required:
                live.require(capability)
            return fn(*args, **kwargs)
        except _EXPECTED as e:
            return str(e)
        except (live.LiveRefused, ValueError) as e:
            return f"{fn.__name__} failed: {e}"
        except Exception as e:  # last resort: keep the session alive
            log.exception("%s crashed", fn.__name__)
            return f"{fn.__name__} failed unexpectedly: {e}"

    return run


def tool(needs: str | Iterable[str] | None = None) -> Callable[[Callable], Callable]:
    """Register a function as an MCP tool, guarded by :func:`guard`.

    ``needs`` names the control-surface commands the tool relies on.
    """
    required = (needs,) if isinstance(needs, str) else tuple(needs or ())

    def register(fn: Callable) -> Callable:
        run = guard(fn, required)
        mcp.tool()(run)
        return run

    return register


# ── small shared helpers ─────────────────────────────────────────────────────

def as_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def compact(**values: Any) -> dict:
    """The given keyword arguments, minus the ones left at None."""
    return {k: v for k, v in values.items() if v is not None}


TRACK_TYPES = ("track", "return", "master")


def track_target(track_index: int, track_type: str = "track", **extra: Any) -> dict:
    """Params addressing a regular track, a return track or the main track.

    ``track_type`` is only sent for returns and the main track: control
    surfaces that predate them would otherwise act on the regular track with
    the same index, so those require the ``return_master_devices`` command.
    """
    kind = (track_type or "track").lower()
    if kind not in TRACK_TYPES:
        raise ValueError("track_type must be 'track', 'return' or 'master'")
    params = {"track_index": track_index, **extra}
    if kind != "track":
        live.require("return_master_devices")
        params["track_type"] = kind
    return params


def describe_target(track_index: int, track_type: str = "track") -> str:
    kind = (track_type or "track").lower()
    return {"master": "the main track", "return": f"return track {track_index}"}.get(
        kind, f"track {track_index}")


LOCATIONS = ("session", "arrangement")


def clip_target(track_index: int, clip_index: int, location: str = "session", **extra: Any) -> dict:
    """Params addressing a Session slot or an Arrangement clip.

    ``location`` is only sent for the Arrangement, which needs the
    ``arrangement_notes`` command (older control surfaces would silently edit
    the Session clip in the same slot).
    """
    where = (location or "session").lower()
    if where not in LOCATIONS:
        raise ValueError("location must be 'session' or 'arrangement'")
    params = {"track_index": track_index, "clip_index": clip_index, **extra}
    if where == "arrangement":
        live.require("arrangement_notes")
        params["location"] = where
    return params


NOTES_PER_REQUEST = 1000   # keeps each request well under the control surface's size limit


def write_notes(track_index: int, clip_index: int, notes: list, location: str = "session") -> None:
    """Add notes to a clip, splitting long lists over several requests."""
    for start in range(0, len(notes), NOTES_PER_REQUEST):
        live.call("add_notes_to_clip", clip_target(
            track_index, clip_index, location, notes=notes[start:start + NOTES_PER_REQUEST]))


def describe_clip(track_index: int, clip_index: int, location: str = "session") -> str:
    if (location or "session").lower() == "arrangement":
        return f"arrangement clip {clip_index} on track {track_index}"
    return f"slot {clip_index} on track {track_index}"
