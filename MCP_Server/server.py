# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import socket
import json
import logging
import math
import os
import threading
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Union


ABLETON_HOST = os.environ.get("ABLETON_HOST", "localhost")
ABLETON_PORT = int(os.environ.get("ABLETON_PORT", "9877"))

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")


class AbletonCommandError(Exception):
    """Live received the command and refused it (status "error").

    The connection is fine: the message is Live's own explanation
    (out-of-range index, master track can't be muted, ...).
    """


@dataclass
class AbletonConnection:
    host: str
    port: int
    sock: socket.socket = None

    # Serialise requests so concurrent tool calls cannot interleave their
    # sendall/recv pairs on the shared socket.
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def connect(self) -> bool:
        """Connect to the Ableton Remote Script socket server"""
        if self.sock:
            return True

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(None)
            logger.info(f"Connected to Ableton at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ableton at {self.host}:{self.port}: {str(e)}")
            self.sock = None
            return False
    
    def disconnect(self):
        """Disconnect from the Ableton Remote Script"""
        with self._lock:
            if self.sock:
                try:
                    self.sock.close()
                except Exception as e:
                    logger.error(f"Error disconnecting from Ableton: {str(e)}")
                finally:
                    self.sock = None

    def receive_full_response(self, sock, buffer_size=8192):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        sock.settimeout(15.0)  # Increased timeout for operations that might take longer
        
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception("Connection closed before receiving any data")
                        break
                    
                    chunks.append(chunk)
                    
                    # Check if we've received a complete JSON object
                    try:
                        data = b''.join(chunks)
                        json.loads(data.decode('utf-8'))
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except socket.timeout:
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise
            
        # If we get here, we either timed out or broke out of the loop
        if chunks:
            data = b''.join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                json.loads(data.decode('utf-8'))
                return data
            except json.JSONDecodeError:
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to Ableton and return the response.

        Serialised on ``self._lock``: the request and its response are one
        indivisible exchange on a shared socket. Holding the lock across the
        whole round-trip (including reconnect) is what keeps a concurrent
        caller from reading someone else's reply.
        """
        with self._lock:
            return self._send_command_locked(command_type, params)

    def _send_command_locked(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")

        command = {
            "type": command_type,
            "params": params or {}
        }
        
        # Check if this is a state-modifying command
        is_modifying_command = command_type in [
            "create_midi_track", "create_audio_track", "set_track_name",
            "create_clip", "create_audio_clip", "add_notes_to_clip", "set_clip_name",
            "delete_clip",
            "clear_notes_from_clip",
            "set_tempo", "fire_clip", "stop_clip", "set_device_parameter",
            "start_playback", "stop_playback", "load_instrument_or_effect",
            # Arrangement view commands
            "switch_to_arrangement_view", "set_current_song_time",
            "duplicate_session_clip_to_arrangement",
            "create_locator", "delete_locator"
        ]

        # Commands whose work on Live's main thread can take noticeably longer
        # than the default modifying-command budget (e.g. importing/decoding a
        # large audio file). Give them a wider socket timeout so we don't time
        # out before the Remote Script's own queue does.
        long_running_commands = {"create_audio_clip": 65.0}
        
        try:
            logger.info(f"Sending command: {command_type} with params: {params}")
            
            # Send the command
            self.sock.sendall(json.dumps(command).encode('utf-8'))
            logger.info(f"Command sent, waiting for response...")
            
            # Set timeout based on command type
            if command_type in long_running_commands:
                timeout = long_running_commands[command_type]
            else:
                timeout = 15.0 if is_modifying_command else 10.0
            self.sock.settimeout(timeout)

            # Receive the response
            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received {len(response_data)} bytes of data")

            # Parse the response
            response = json.loads(response_data.decode('utf-8'))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")

            if response.get("status") == "error":
                logger.error(f"Ableton error: {response.get('message')}")
                raise AbletonCommandError(response.get("message", "Unknown error from Ableton"))
            
            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Ableton")
            self.sock = None
            raise Exception("Timeout waiting for Ableton response")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Ableton lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Ableton: {str(e)}")
            if 'response_data' in locals() and response_data:
                logger.error(f"Raw response (first 200 bytes): {response_data[:200]}")
            self.sock = None
            raise Exception(f"Invalid response from Ableton: {str(e)}")
        except AbletonCommandError:
            # A refusal from Live, not a transport failure: keep the socket
            # and pass Live's message through unchanged.
            raise
        except Exception as e:
            logger.error(f"Error communicating with Ableton: {str(e)}")
            self.sock = None
            raise Exception(f"Communication error with Ableton: {str(e)}")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        logger.info("AbletonMCP server starting up")

        script_info = None
        try:
            get_ableton_connection()  # handshakes on connect
            logger.info("Successfully connected to Ableton on startup")
            from .script_handshake import get_cached_script_info

            script_info = get_cached_script_info()
        except Exception as e:
            logger.warning(f"Could not connect to Ableton on startup: {str(e)}")
            logger.warning("Make sure the Ableton Remote Script is running")

        yield {"script_info": script_info}
    finally:
        global _ableton_connection
        if _ableton_connection:
            logger.info("Disconnecting from Ableton on shutdown")
            _ableton_connection.disconnect()
            _ableton_connection = None
        logger.info("AbletonMCP server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "AbletonMCP",
    lifespan=server_lifespan
)

# Global connection for resources
_ableton_connection = None

def _refresh_handshake():
    from .script_handshake import _needs_refresh, handshake
    conn = get_ableton_connection()  # a new connection handshakes by itself
    if _needs_refresh():
        handshake(conn.send_command)


from .script_handshake import set_refresher as _set_refresher  # noqa: E402

_set_refresher(_refresh_handshake)


def get_ableton_connection():
    """Get or create a persistent Ableton connection"""
    global _ableton_connection

    if _ableton_connection is not None and _ableton_connection.sock is not None:
        try:
            # Check if the socket is still alive by peeking for data
            # MSG_PEEK + MSG_DONTWAIT will raise BlockingIOError if alive but no data,
            # or return b'' if the remote end has closed the connection.
            _ableton_connection.sock.setblocking(False)
            try:
                data = _ableton_connection.sock.recv(1, socket.MSG_PEEK)
                if data == b'':
                    raise ConnectionError("Remote end closed")
            except BlockingIOError:
                pass  # Socket is alive, just no data waiting — this is normal
            finally:
                _ableton_connection.sock.setblocking(True)
            return _ableton_connection
        except Exception as e:
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _ableton_connection.disconnect()
            except:
                pass
            _ableton_connection = None
    
    # Connection doesn't exist or is invalid, create a new one
    if _ableton_connection is None:
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Connecting to Ableton at {ABLETON_HOST}:{ABLETON_PORT} (attempt {attempt}/{max_attempts})...")
                _ableton_connection = AbletonConnection(host=ABLETON_HOST, port=ABLETON_PORT)
                if _ableton_connection.connect():
                    logger.info("Created new persistent connection to Ableton")
                    # Live may have started (or restarted with another script)
                    # since the last handshake: check the version again.
                    try:
                        from .script_handshake import handshake
                        handshake(_ableton_connection.send_command)
                    except Exception as e:
                        logger.warning(f"Remote Script handshake failed: {e}")
                    return _ableton_connection
                else:
                    _ableton_connection = None
            except Exception as e:
                logger.error(f"Connection attempt {attempt} failed: {str(e)}")
                if _ableton_connection:
                    _ableton_connection.disconnect()
                    _ableton_connection = None

            if attempt < max_attempts:
                import time
                time.sleep(1.0)
        
        # If we get here, all connection attempts failed
        if _ableton_connection is None:
            logger.error("Failed to connect to Ableton after multiple attempts")
            raise Exception("Could not connect to Ableton. Make sure the Remote Script is running.")
    
    return _ableton_connection


# Core Tool endpoints

@mcp.tool()
def get_session_info(ctx: Context) -> str:
    """Get detailed information about the current Ableton session
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_session_info")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting session info from Ableton: {str(e)}")
        return f"Error getting session info: {str(e)}"


@mcp.tool()
def get_remote_script_info(ctx: Context) -> str:
    """
    Report Ableton Remote Script version and capabilities (handshake).

    Use this to verify the Live-side bridge matches this MCP server package.
    """
    try:
        from .remote_script_install import EXPECTED_REMOTE_SCRIPT_VERSION
        from .script_handshake import get_cached_script_info, handshake

        ableton = get_ableton_connection()
        info = handshake(ableton.send_command)
        cached = dict(get_cached_script_info() or info)
        cached["expected_version"] = EXPECTED_REMOTE_SCRIPT_VERSION
        return json.dumps(cached, indent=2)
    except Exception as e:
        logger.error(f"Error getting remote script info: {str(e)}")
        return f"Error getting remote script info: {str(e)}"

def _apply_track_type(params: Dict[str, Any], track_type: str) -> Union[str, None]:
    """Add track_type to the command params for a return or the main track.

    An older Remote Script would ignore track_type and act on the regular
    track with the same index, so refuse unless it advertises
    return_master_devices. Returns an error message, or None when fine.
    """
    track_type = (track_type or "track").lower()
    if track_type not in ("track", "return", "master"):
        return "track_type must be 'track', 'return' or 'master'"
    if track_type == "track":
        return None
    from .script_handshake import require_capability

    missing = require_capability("return_master_devices")
    if missing:
        return missing
    params["track_type"] = track_type
    return None


@mcp.tool()
def get_track_info(ctx: Context, track_index: int, track_type: str = "track") -> str:
    """
    Get detailed information about a track, a return track or the main track
    (name, mixer state, clip slots, device chain).

    Parameters:
    - track_index: Index of the track (index among return tracks for "return",
      ignored for "master")
    - track_type: "track" (default), "return" or "master"
    """
    try:
        params: Dict[str, Any] = {"track_index": track_index}
        missing = _apply_track_type(params, track_type)
        if missing:
            return missing
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_info", params)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting track info from Ableton: {str(e)}")
        return f"Error getting track info: {str(e)}"


def _note_params(track_index: int, clip_index: int, location: str) -> Dict[str, Any]:
    """Command params; location is only sent for the Arrangement, so calls
    on Session clips stay exactly what older Remote Scripts expect."""
    params: Dict[str, Any] = {"track_index": track_index, "clip_index": clip_index}
    location = (location or "session").lower()
    if location not in ("session", "arrangement"):
        raise ValueError("location must be 'session' or 'arrangement'")
    if location == "arrangement":
        params["location"] = "arrangement"
    return params


def _arrangement_notes_missing(location: str) -> Union[str, None]:
    """An older Remote Script would ignore location and edit the Session clip
    instead, so refuse unless it advertises arrangement_notes."""
    if (location or "session").lower() != "arrangement":
        return None
    from .script_handshake import require_capability

    return require_capability("arrangement_notes")


@mcp.tool()
def get_clip_notes(
    ctx: Context,
    track_index: int,
    clip_index: int,
    location: str = "session",
) -> str:
    """
    Read all MIDI notes from a Session clip or an Arrangement clip.

    Returns pitch, start_time, duration, velocity, mute (and extended fields when available).
    Note times are in clip beats (0 = clip start). For an Arrangement clip the
    reply also gives arrangement_start / arrangement_end (song beats) and
    start_marker: a note plays at arrangement_start + (start_time - start_marker)
    when the clip isn't looping.

    Parameters:
    - track_index: Track that owns the clip
    - clip_index: Session slot index, or Arrangement clip index (get_arrangement_clips)
    - location: "session" (default) or "arrangement"
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("get_clip_notes") or _arrangement_notes_missing(location)
        if missing:
            return missing
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_clip_notes", _note_params(track_index, clip_index, location),
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting clip notes: {str(e)}")
        return f"Error getting clip notes: {str(e)}"


@mcp.tool()
def get_device_parameters(
    ctx: Context,
    track_index: int,
    device_index: int,
    track_type: str = "track",
) -> str:
    """
    Read all parameters for a device on a track (name, value, min, max).

    Parameters:
    - track_index: Track that owns the device (index among return tracks for
      "return", ignored for "master")
    - device_index: Index into the track's device chain
    - track_type: "track" (default), "return" or "master"
    """
    try:
        params: Dict[str, Any] = {"track_index": track_index, "device_index": device_index}
        missing = _apply_track_type(params, track_type)
        if missing:
            return missing
        ableton = get_ableton_connection()
        result = ableton.send_command("get_device_parameters", params)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device parameters: {str(e)}")
        return f"Error getting device parameters: {str(e)}"


@mcp.tool()
def set_device_parameter(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameter_index: int,
    value: float,
    track_type: str = "track",
) -> str:
    """
    Set a device parameter to a specific value.

    Use get_device_parameters first to discover parameter indices and ranges.

    Parameters:
    - track_index: Track that owns the device (index among return tracks for
      "return", ignored for "master")
    - device_index: Index into the track's device chain
    - parameter_index: Index into device.parameters
    - value: New parameter value (Live parameter units)
    - track_type: "track" (default), "return" or "master"
    """
    try:
        params: Dict[str, Any] = {
            "track_index": track_index,
            "device_index": device_index,
            "parameter_index": parameter_index,
            "value": value,
        }
        missing = _apply_track_type(params, track_type)
        if missing:
            return missing
        ableton = get_ableton_connection()
        result = ableton.send_command("set_device_parameter", params)
        old_shown = result.get("old_display") or result.get("old_value")
        new_shown = result.get("display") or result.get("value")
        return f"Set {result.get('name', 'parameter')} {old_shown} → {new_shown}"
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return f"Error setting device parameter: {str(e)}"


@mcp.tool()
def get_session_snapshot(
    ctx: Context,
    include_notes: bool = True,
    include_params: bool = True,
) -> str:
    """
    Capture a full project state snapshot.

    Includes session metadata, every track (mixer, devices, session clips,
    arrangement clips), optional MIDI notes, and optional device parameters.
    Useful to compare the set before and after a series of edits.

    Parameters:
    - include_notes: Include MIDI note arrays in clips (default True)
    - include_params: Include device parameter values (default True)
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("get_session_snapshot")
        if missing:
            return missing
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_session_snapshot",
            {
                "include_notes": include_notes,
                "include_params": include_params,
            },
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting session snapshot: {str(e)}")
        return f"Error getting session snapshot: {str(e)}"


@mcp.tool()
def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_midi_track", {"index": index})
        return f"Created new MIDI track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating MIDI track: {str(e)}")
        return f"Error creating MIDI track: {str(e)}"


@mcp.tool()
def create_audio_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new audio track in the Ableton session.

    Use this for recorded or imported audio (samples, stems, vocals). For MIDI
    instruments use create_midi_track instead.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_audio_track", {"index": index})
        return f"Created new audio track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating audio track: {str(e)}")
        return f"Error creating audio track: {str(e)}"


@mcp.tool()
def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.

    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_name", {"track_index": track_index, "name": name})
        return f"Renamed track to: {result.get('name', name)}"
    except Exception as e:
        logger.error(f"Error setting track name: {str(e)}")
        return f"Error setting track name: {str(e)}"

@mcp.tool()
def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.

    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_clip", {
            "track_index": track_index, 
            "clip_index": clip_index, 
            "length": length
        })
        return f"Created new clip at track {track_index}, slot {clip_index} with length {length} beats"
    except Exception as e:
        logger.error(f"Error creating clip: {str(e)}")
        return f"Error creating clip: {str(e)}"

@mcp.tool()
def create_audio_clip(ctx: Context, track_index: int, clip_index: int, path: str) -> str:
    """
    Create a new audio clip in an audio track's clip slot by importing a file.

    Requires Ableton Live 12.0.5 or newer — the underlying
    ClipSlot.create_audio_clip Live API was introduced in 12.0.5 and is not
    available in earlier 12.0.x releases.

    Parameters:
    - track_index: The index of the audio track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - path: Absolute path to a supported audio file (e.g. a .wav). The target
      track must be an audio track and the clip slot must be empty.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_audio_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "path": path
        })
        return f"Created audio clip '{result.get('name', 'clip')}' at track {track_index}, slot {clip_index} (length {result.get('length', '?')} beats)"
    except Exception as e:
        logger.error(f"Error creating audio clip: {str(e)}")
        return f"Error creating audio clip: {str(e)}"

@mcp.tool()
def add_notes_to_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    notes: List[Dict[str, Union[int, float, bool]]],
    location: str = "session"
) -> str:
    """
    Add MIDI notes to a Session clip or an Arrangement clip. Notes are added
    to the existing ones; to replace, clear_notes_from_clip or remove_notes first.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: Session slot index, or Arrangement clip index (get_arrangement_clips)
    - notes: List of note dictionaries, each with pitch, start_time (clip
      beats, 0 = clip start), duration, velocity, and mute
    - location: "session" (default) or "arrangement"
    """
    try:
        missing = _arrangement_notes_missing(location)
        if missing:
            return missing
        params = _note_params(track_index, clip_index, location)
        params["notes"] = notes
        ableton = get_ableton_connection()
        result = ableton.send_command("add_notes_to_clip", params)
        if "location" in params:
            return f"Added {len(notes)} notes to arrangement clip {clip_index} on track {track_index}"
        return f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error adding notes to clip: {str(e)}")
        return f"Error adding notes to clip: {str(e)}"

@mcp.tool()
def clear_notes_from_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    location: str = "session"
) -> str:
    """
    Remove all MIDI notes from a Session clip or an Arrangement clip.

    Writes are additive (add_notes_to_clip only appends), so to truly *modify*
    a clip you clear it first, then add the new notes. Use this with
    get_clip_notes and add_notes_to_clip for a real read -> modify -> write
    loop: read the notes, edit the list, clear_notes_from_clip, then
    add_notes_to_clip the edited notes.

    To change only part of a clip, use remove_notes instead.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: Session slot index, or Arrangement clip index (get_arrangement_clips)
    - location: "session" (default) or "arrangement"
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("clear_notes_from_clip") or _arrangement_notes_missing(location)
        if missing:
            return missing
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "clear_notes_from_clip", _note_params(track_index, clip_index, location))
        return "Cleared {n} note(s) from clip '{name}' (track {t}, {where} {c})".format(
            n=result.get("cleared_count", "?"),
            name=result.get("clip_name", "clip"),
            t=track_index,
            where="arrangement clip" if (location or "").lower() == "arrangement" else "slot",
            c=clip_index,
        )
    except Exception as e:
        logger.error(f"Error clearing notes from clip: {str(e)}")
        return f"Error clearing notes from clip: {str(e)}"


@mcp.tool()
def remove_notes(
    ctx: Context,
    track_index: int,
    clip_index: int,
    from_time: float = 0.0,
    time_span: Union[float, None] = None,
    from_pitch: int = 0,
    pitch_span: int = 128,
    location: str = "session",
) -> str:
    """
    Remove the notes that start inside a time range and a pitch range, leaving
    the others. Use it to rewrite one bar or one drum lane: remove that range,
    then add_notes_to_clip the new notes.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: Session slot index, or Arrangement clip index (get_arrangement_clips)
    - from_time: Start of the range, in clip beats (0 = clip start)
    - time_span: Length of the range in beats (default: to the end of the clip)
    - from_pitch: Lowest MIDI pitch of the range (0-127, default 0)
    - pitch_span: Number of pitches from from_pitch (default 128 = all; 1 = a single pitch)
    - location: "session" (default) or "arrangement"
    """
    try:
        params = _note_params(track_index, clip_index, location)
    except ValueError as e:
        return f"Error removing notes: {e}"
    params.update(_without_none({
        "from_time": from_time, "time_span": time_span,
        "from_pitch": from_pitch, "pitch_span": pitch_span,
    }))
    return _send_with_capability("remove_notes", params, "removing notes")

@mcp.tool()
def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_name", {
            "track_index": track_index,
            "clip_index": clip_index,
            "name": name
        })
        return f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'"
    except Exception as e:
        logger.error(f"Error setting clip name: {str(e)}")
        return f"Error setting clip name: {str(e)}"

@mcp.tool()
def set_arrangement_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip placed in the Arrangement timeline.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip within track.arrangement_clips, in the
      same order returned by get_arrangement_clips (i.e. ordered by start_time)
    - name: The new name for the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_arrangement_clip_name", {
            "track_index": track_index,
            "clip_index": clip_index,
            "name": name
        })
        return f"Renamed arrangement clip at track {track_index}, index {clip_index} to '{name}'"
    except Exception as e:
        logger.error(f"Error setting arrangement clip name: {str(e)}")
        return f"Error setting arrangement clip name: {str(e)}"

@mcp.tool()
def set_tempo(ctx: Context, tempo: float) -> str:
    """
    Set the tempo of the Ableton session.

    Parameters:
    - tempo: The new tempo in BPM
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_tempo", {"tempo": tempo})
        return f"Set tempo to {tempo} BPM"
    except Exception as e:
        logger.error(f"Error setting tempo: {str(e)}")
        return f"Error setting tempo: {str(e)}"


@mcp.tool()
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str,
                              track_type: str = "track") -> str:
    """
    Load an instrument, effect, preset, plugin or User Library item onto a
    track using its browser URI. Audio effects can go on a return track or the
    main track: use track_type="return" (track_index = return index, 0 = A)
    or track_type="master". Plugins (VST/AU) and User Library items are found
    with get_browser_items_at_path("plugins/...") or ("user_library/...").

    Parameters:
    - track_index: The index of the track to load onto (return index for
      "return", ignored for "master")
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    - track_type: "track" (default), "return" or "master"
    """
    try:
        params: Dict[str, Any] = {"track_index": track_index, "item_uri": uri}
        missing = _apply_track_type(params, track_type)
        if missing:
            return missing
        target = (f"track {track_index}" if (track_type or "track").lower() == "track"
                  else "main track" if track_type.lower() == "master"
                  else f"return track {track_index}")
        ableton = get_ableton_connection()
        result = ableton.send_command("load_browser_item", params)
        
        # Check if the instrument was loaded successfully
        if result.get("loaded", False):
            new_devices = result.get("new_devices", [])
            devices = result.get("devices_after", [])
            if result.get("in_place"):
                if result.get("settled"):
                    return (f"Reloaded '{uri}' in place on {target}: "
                            f"Live kept the existing device and reset its parameters")
                return (f"Requested reload of '{uri}' on {target}. Live "
                        f"reloads an identical device in place, and no parameter "
                        f"changed (they may already be at their defaults). "
                        f"Devices on track: {', '.join(devices) or 'none'}")
            if new_devices:
                return f"Loaded instrument with URI '{uri}' on {target}. New devices: {', '.join(new_devices)}"
            elif result.get("settled") is False:
                return (f"Requested load of '{uri}' on {target}, but Live "
                        f"had not changed the device chain yet. Devices on track: "
                        f"{', '.join(devices) or 'none'}. Check with get_track_info.")
            else:
                return f"Loaded instrument with URI '{uri}' on {target}. Devices on track: {', '.join(devices) or 'none'}"
        else:
            return f"Failed to load instrument with URI '{uri}'"
    except Exception as e:
        logger.error(f"Error loading instrument by URI: {str(e)}")
        return f"Error loading instrument by URI: {str(e)}"

@mcp.tool()
def fire_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Started playing clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error firing clip: {str(e)}")
        return f"Error firing clip: {str(e)}"

@mcp.tool()
def stop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Stopped clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error stopping clip: {str(e)}")
        return f"Error stopping clip: {str(e)}"


@mcp.tool()
def delete_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Delete the clip in the given clip slot, freeing it for reuse.

    Use this before create_clip when you want to overwrite an existing clip
    (create_clip itself refuses to write into an occupied slot).

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot to clear
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("delete_clip")
        if missing:
            return missing
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error deleting clip: {str(e)}")
        return f"Error deleting clip: {str(e)}"


# ── Mixer / tracks / scenes ──────────────────────────────────────────────────

def _send_with_capability(command: str, params: Dict[str, Any], label: str) -> str:
    """Send a command after checking the Remote Script supports it."""
    try:
        from .script_handshake import require_capability

        missing = require_capability(command)
        if missing:
            return missing
        ableton = get_ableton_connection()
        result = ableton.send_command(command, params)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error {label}: {str(e)}")
        return f"Error {label}: {str(e)}"


@mcp.tool()
def set_track_volume(
    ctx: Context, track_index: int, volume: float, track_type: str = "track"
) -> str:
    """
    Set a track's volume fader.

    Parameters:
    - track_index: Index of the track (ignored when track_type is "master")
    - volume: Normalized fader value 0.0–1.0 (0.85 ≈ 0 dB, 0.0 = -inf)
    - track_type: "track" (default), "return" or "master"
    """
    return _send_with_capability("set_track_volume", {
        "track_index": track_index, "volume": volume, "track_type": track_type,
    }, "setting track volume")


@mcp.tool()
def set_track_panning(
    ctx: Context, track_index: int, panning: float, track_type: str = "track"
) -> str:
    """
    Set a track's panning.

    Parameters:
    - track_index: Index of the track (ignored when track_type is "master")
    - panning: -1.0 = full left, 0.0 = center, 1.0 = full right
    - track_type: "track" (default), "return" or "master"
    """
    return _send_with_capability("set_track_panning", {
        "track_index": track_index, "panning": panning, "track_type": track_type,
    }, "setting track panning")


@mcp.tool()
def set_track_send(
    ctx: Context, track_index: int, send_index: int, value: float,
    track_type: str = "track"
) -> str:
    """
    Set the level of a send from a track to a return track.

    Parameters:
    - track_index: Index of the track
    - send_index: Index of the send (0 = Send A / first return track)
    - value: Send level 0.0–1.0
    - track_type: "track" (default) or "return"
    """
    return _send_with_capability("set_track_send", {
        "track_index": track_index, "send_index": send_index,
        "value": value, "track_type": track_type,
    }, "setting track send")


@mcp.tool()
def set_track_mute(
    ctx: Context, track_index: int, mute: bool, track_type: str = "track"
) -> str:
    """
    Mute or unmute a track.

    Parameters:
    - track_index: Index of the track
    - mute: True to mute, False to unmute
    - track_type: "track" (default) or "return"
    """
    return _send_with_capability("set_track_mute", {
        "track_index": track_index, "mute": mute, "track_type": track_type,
    }, "setting track mute")


@mcp.tool()
def set_track_solo(
    ctx: Context, track_index: int, solo: bool, track_type: str = "track"
) -> str:
    """
    Solo or unsolo a track.

    Parameters:
    - track_index: Index of the track
    - solo: True to solo, False to unsolo
    - track_type: "track" (default) or "return"
    """
    return _send_with_capability("set_track_solo", {
        "track_index": track_index, "solo": solo, "track_type": track_type,
    }, "setting track solo")


@mcp.tool()
def set_track_arm(ctx: Context, track_index: int, arm: bool) -> str:
    """
    Arm or disarm a track for recording.

    Parameters:
    - track_index: Index of the track
    - arm: True to arm, False to disarm
    """
    return _send_with_capability("set_track_arm", {
        "track_index": track_index, "arm": arm,
    }, "setting track arm")


@mcp.tool()
def delete_track(ctx: Context, track_index: int) -> str:
    """
    Delete a track. Destructive: confirm with the user before calling.
    Indexes of the following tracks shift down by one.

    Parameters:
    - track_index: Index of the track to delete
    """
    return _send_with_capability("delete_track", {"track_index": track_index}, "deleting track")


@mcp.tool()
def duplicate_track(ctx: Context, track_index: int) -> str:
    """
    Duplicate a track (with its clips and devices). The copy is inserted right after it.

    Parameters:
    - track_index: Index of the track to duplicate
    """
    return _send_with_capability("duplicate_track", {"track_index": track_index}, "duplicating track")


@mcp.tool()
def get_scenes(ctx: Context) -> str:
    """
    List the Session view scenes (index, name, tempo).
    """
    return _send_with_capability("get_scenes", {}, "getting scenes")


@mcp.tool()
def create_scene(ctx: Context, index: int = -1) -> str:
    """
    Create a new scene in the Session view.

    Parameters:
    - index: Position to insert the scene (-1 = at the end)
    """
    return _send_with_capability("create_scene", {"index": index}, "creating scene")


@mcp.tool()
def delete_scene(ctx: Context, scene_index: int) -> str:
    """
    Delete a scene and all clips in its row. Destructive: confirm with the user first.

    Parameters:
    - scene_index: Index of the scene to delete
    """
    return _send_with_capability("delete_scene", {"scene_index": scene_index}, "deleting scene")


@mcp.tool()
def duplicate_scene(ctx: Context, scene_index: int) -> str:
    """
    Duplicate a scene (with its clips). The copy is inserted right after it.

    Parameters:
    - scene_index: Index of the scene to duplicate
    """
    return _send_with_capability("duplicate_scene", {"scene_index": scene_index}, "duplicating scene")


@mcp.tool()
def fire_scene(ctx: Context, scene_index: int) -> str:
    """
    Launch a scene (all clips in its row).

    Parameters:
    - scene_index: Index of the scene to launch
    """
    return _send_with_capability("fire_scene", {"scene_index": scene_index}, "firing scene")


@mcp.tool()
def set_scene_name(ctx: Context, scene_index: int, name: str) -> str:
    """
    Rename a scene.

    Parameters:
    - scene_index: Index of the scene
    - name: New scene name
    """
    return _send_with_capability("set_scene_name", {
        "scene_index": scene_index, "name": name,
    }, "renaming scene")


@mcp.tool()
def delete_arrangement_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Delete a clip from the Arrangement timeline (Live 11+).

    Parameters:
    - track_index: Index of the track
    - clip_index: Index of the clip as listed by get_arrangement_clips
      (indexes of later clips shift down after deletion)
    """
    return _send_with_capability("delete_arrangement_clip", {
        "track_index": track_index, "clip_index": clip_index,
    }, "deleting arrangement clip")


def _without_none(params: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in params.items() if v is not None}


@mcp.tool()
def get_clip_loop(
    ctx: Context, track_index: int, clip_index: int, location: str = "session"
) -> str:
    """
    Read a clip's loop switch, loop brace (loop_start / loop_end) and start /
    end markers. Units are beats, except for an unwarped audio clip, where
    Live uses seconds of the file (see "units" in the reply). For an
    Arrangement clip the reply also gives its place in the song.

    Parameters:
    - track_index: Index of the track
    - clip_index: Session slot index, or Arrangement clip index (get_arrangement_clips)
    - location: "session" (default) or "arrangement"
    """
    return _send_with_capability("get_clip_loop", {
        "track_index": track_index, "clip_index": clip_index, "location": location,
    }, "reading clip loop")


@mcp.tool()
def set_clip_loop(
    ctx: Context,
    track_index: int,
    clip_index: int,
    location: str = "session",
    looping: Union[bool, None] = None,
    loop_start: Union[float, None] = None,
    loop_end: Union[float, None] = None,
    loop_length: Union[float, None] = None,
    start_marker: Union[float, None] = None,
    end_marker: Union[float, None] = None,
) -> str:
    """
    Change a clip's loop and markers. Arguments left out are untouched.

    - The loop brace (loop_start → loop_end) is the part that repeats when
      looping is on. Shorten a 4-bar loop to its first bar with
      loop_start=0, loop_length=4.
    - Looping on: playback starts at start_marker, then the brace repeats.
      Looping off: Live plays loop_start -> loop_end once (start_marker
      follows loop_start; end_marker is unused). Markers given for a clip
      that doesn't loop are written to loop_start/loop_end for you.
    - get_clip_loop's "playback" field says what actually plays.
    - Turning warping off then on again resets an audio clip's warp markers.

    Units are beats (seconds for an unwarped audio clip: check get_clip_loop).
    The order of the writes is handled so the start never passes the end on
    the way. The reply shows what Live applied; "adjusted" lists any value
    it changed.

    Parameters:
    - track_index: Index of the track
    - clip_index: Session slot index, or Arrangement clip index (get_arrangement_clips)
    - location: "session" (default) or "arrangement"
    - looping: Loop switch on or off
    - loop_start, loop_end: Loop brace
    - loop_length: Sets loop_end = loop_start + loop_length (instead of loop_end)
    - start_marker, end_marker: Playback start / end markers
    """
    return _send_with_capability("set_clip_loop", _without_none({
        "track_index": track_index, "clip_index": clip_index, "location": location,
        "looping": looping, "loop_start": loop_start, "loop_end": loop_end,
        "loop_length": loop_length, "start_marker": start_marker, "end_marker": end_marker,
    }), "setting clip loop")


@mcp.tool()
def get_clip_warp(
    ctx: Context, track_index: int, clip_index: int, location: str = "session"
) -> str:
    """
    Read an audio clip's warp settings: warping on/off, warp mode, available
    modes, warp markers (beat_time ↔ sample_time in seconds), pitch, gain,
    clip length and the sample's duration.

    Parameters:
    - track_index: Index of the track
    - clip_index: Session slot index, or Arrangement clip index as listed by
      get_arrangement_clips
    - location: "session" (default) or "arrangement"
    """
    return _send_with_capability("get_clip_warp", {
        "track_index": track_index, "clip_index": clip_index, "location": location,
    }, "reading clip warp")


@mcp.tool()
def set_clip_warp(
    ctx: Context,
    track_index: int,
    clip_index: int,
    location: str = "session",
    warping: Union[bool, None] = None,
    warp_mode: Union[str, None] = None,
    original_bpm: Union[float, None] = None,
    pitch_coarse: Union[int, None] = None,
    pitch_fine: Union[float, None] = None,
    gain: Union[float, None] = None,
) -> str:
    """
    Change an audio clip's warp settings. Arguments left out are untouched.

    To make a loop follow the song tempo, pass its original tempo as
    original_bpm (sample packs usually put it in the file name, e.g.
    "..._131_..."): warping is turned on and the warp markers are rebuilt so
    the file is read at that tempo.

    Parameters:
    - track_index: Index of the audio track
    - clip_index: Session slot index, or Arrangement clip index (get_arrangement_clips)
    - location: "session" (default) or "arrangement"
    - warping: Turn warping on or off
    - warp_mode: "beats", "tones", "texture", "re_pitch", "complex",
      "complex_pro" (or Live's index 0–6). Beats suits drums, Complex/Complex
      Pro full mixes, Tones monophonic parts, Re-Pitch vinyl-style speed changes.
    - original_bpm: The loop's own tempo; conforms it to the song tempo
    - pitch_coarse: Transpose in semitones (-48 to 48)
    - pitch_fine: Detune in cents (-50 to 50)
    - gain: Clip gain, normalized 0.0–1.0 (see gain_display in the reply)
    """
    return _send_with_capability("set_clip_warp", _without_none({
        "track_index": track_index, "clip_index": clip_index, "location": location,
        "warping": warping, "warp_mode": warp_mode, "original_bpm": original_bpm,
        "pitch_coarse": pitch_coarse, "pitch_fine": pitch_fine, "gain": gain,
    }), "setting clip warp")


@mcp.tool()
def edit_warp_markers(
    ctx: Context,
    track_index: int,
    clip_index: int,
    location: str = "session",
    add: Union[List[Dict[str, float]], None] = None,
    move: Union[List[Dict[str, float]], None] = None,
    remove: Union[List[float], None] = None,
) -> str:
    """
    Edit an audio clip's warp markers (Live 11+; warping must be on).
    Applied in this order: remove, move, add. Use get_clip_warp to see the
    current markers.

    Parameters:
    - track_index: Index of the audio track
    - clip_index: Session slot index, or Arrangement clip index (get_arrangement_clips)
    - location: "session" (default) or "arrangement"
    - add: [{"beat_time": 8.0, "sample_time": 3.66}] — pin a point of the
      file (sample_time, seconds) to a beat; both are required
    - move: [{"beat_time": 8.0, "beat_time_distance": 0.25}] — shift the
      marker at beat_time by that many beats
    - remove: [8.0, 16.0] — beat times of the markers to remove
    """
    return _send_with_capability("edit_warp_markers", _without_none({
        "track_index": track_index, "clip_index": clip_index, "location": location,
        "add": add, "move": move, "remove": remove,
    }), "editing warp markers")


@mcp.tool()
def set_clip_automation(
    ctx: Context,
    track_index: int,
    clip_index: int,
    points: List[Dict[str, float]],
    location: str = "session",
    device_index: int = -1,
    parameter_index: int = 0,
    mixer_parameter: str = "",
    interpolation: str = "linear",
    resolution: float = 0.25,
    clear_first: bool = True,
) -> str:
    """
    Write a clip automation envelope for one parameter on a Session clip; the
    envelope plays whenever the clip plays. Live's API refuses clip automation
    on Arrangement clips, and Arrangement automation lanes aren't reachable.

    Target either a device parameter (device_index + parameter_index, see
    get_device_parameters) or a track mixer control (mixer_parameter).

    Parameters:
    - track_index: Index of the track that owns the clip and the parameter
    - clip_index: Session slot index
    - points: [{"time": 0, "value": 0.2}, {"time": 16, "value": 0.9}] — time in
      beats in clip time (0 = clip start, like MIDI note start_time), value in
      the parameter's units (clamped to its min/max). The last point holds
      until the clip's end. An empty list with clear_first=true removes the
      envelope.
    - location: "session" (the only location Live accepts for writing)
    - device_index: Device in the track's chain (ignored when mixer_parameter is set)
    - parameter_index: Index into the device's parameters
    - mixer_parameter: "volume", "panning" or "send:N" (N = return track index)
    - interpolation: "linear" ramps between points (drawn as steps of
      `resolution` beats), "step" holds each value until the next point
    - resolution: Step size in beats for linear ramps (default 0.25 = a 16th)
    - clear_first: Remove the parameter's existing envelope in this clip first
    """
    return _send_with_capability("set_clip_automation", {
        "track_index": track_index, "clip_index": clip_index, "location": location,
        "device_index": device_index, "parameter_index": parameter_index,
        "mixer_parameter": mixer_parameter, "points": points,
        "interpolation": interpolation, "resolution": resolution,
        "clear_first": clear_first,
    }, "setting clip automation")


@mcp.tool()
def get_clip_automation(
    ctx: Context,
    track_index: int,
    clip_index: int,
    location: str = "session",
    device_index: int = -1,
    parameter_index: int = 0,
    mixer_parameter: str = "",
    resolution: float = 1.0,
) -> str:
    """
    Read a clip's automation envelope for one parameter, sampled every
    `resolution` beats across the clip. Reports has_envelope=false when the
    parameter isn't automated in this clip.

    Parameters:
    - track_index, clip_index, location: as in set_clip_automation
    - device_index, parameter_index, mixer_parameter: as in set_clip_automation
    - resolution: Sampling step in beats (default 1.0)
    """
    return _send_with_capability("get_clip_automation", {
        "track_index": track_index, "clip_index": clip_index, "location": location,
        "device_index": device_index, "parameter_index": parameter_index,
        "mixer_parameter": mixer_parameter, "resolution": resolution,
    }, "reading clip automation")


@mcp.tool()
def start_playback(ctx: Context) -> str:
    """Start playing the Ableton session.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("start_playback")
        return "Started playback"
    except Exception as e:
        logger.error(f"Error starting playback: {str(e)}")
        return f"Error starting playback: {str(e)}"

@mcp.tool()
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_playback")
        return "Stopped playback"
    except Exception as e:
        logger.error(f"Error stopping playback: {str(e)}")
        return f"Error stopping playback: {str(e)}"

@mcp.tool()
def get_browser_tree(ctx: Context, category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.

    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums',
      'audio_effects', 'midi_effects', or any other browser root Live exposes, such as
      'plugins' (VST/AU), 'user_library', 'packs', 'samples', 'max_for_live', 'current_project')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_tree", {
            "category_type": category_type
        })
        
        # Check if we got any categories
        if "available_categories" in result and len(result.get("categories", [])) == 0:
            available_cats = result.get("available_categories", [])
            return (f"No categories found for '{category_type}'. "
                   f"Available browser categories: {', '.join(available_cats)}")
        
        # Format the tree in a more readable way
        total_folders = result.get("total_folders", 0)
        formatted_output = f"Browser tree for '{category_type}' (showing {total_folders} folders):\n\n"
        
        def format_tree(item, indent=0):
            output = ""
            if item:
                prefix = "  " * indent
                name = item.get("name", "Unknown")
                path = item.get("path", "")
                has_more = item.get("has_more", False)
                
                # Add this item
                output += f"{prefix}• {name}"
                if path:
                    output += f" (path: {path})"
                if has_more:
                    output += " [...]"
                output += "\n"
                
                # Add children
                for child in item.get("children", []):
                    output += format_tree(child, indent + 1)
            return output
        
        # Format each category
        for category in result.get("categories", []):
            formatted_output += format_tree(category)
            formatted_output += "\n"
        
        return formatted_output
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        else:
            logger.error(f"Error getting browser tree: {error_msg}")
            return f"Error getting browser tree: {error_msg}"

@mcp.tool()
def get_browser_items_at_path(ctx: Context, path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.

    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton:
            instruments, sounds, drums, audio_effects, midi_effects, plugins (VST/AU),
            user_library, packs, samples, max_for_live, current_project
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_items_at_path", {
            "path": path
        })
        
        # Check if there was an error with available categories
        if "error" in result and "available_categories" in result:
            error = result.get("error", "")
            available_cats = result.get("available_categories", [])
            return (f"Error: {error}\n"
                   f"Available browser categories: {', '.join(available_cats)}")
        
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        elif "Unknown or unavailable category" in error_msg:
            logger.error(f"Invalid browser category: {error_msg}")
            return f"Error: {error_msg}. Please check the available categories using get_browser_tree."
        elif "Path part" in error_msg and "not found" in error_msg:
            logger.error(f"Path not found: {error_msg}")
            return f"Error: {error_msg}. Please check the path and try again."
        else:
            logger.error(f"Error getting browser items at path: {error_msg}")
            return f"Error getting browser items at path: {error_msg}"

@mcp.tool()
def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.

    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')
    """
    try:
        ableton = get_ableton_connection()
        
        # Step 1: Load the drum rack
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": rack_uri
        })
        
        if not result.get("loaded", False):
            return f"Failed to load drum rack with URI '{rack_uri}'"
        
        # Step 2: Get the drum kit items at the specified path
        kit_result = ableton.send_command("get_browser_items_at_path", {
            "path": kit_path
        })
        
        if "error" in kit_result:
            return f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}"
        
        # Step 3: Find a loadable drum kit
        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]
        
        if not loadable_kits:
            return f"Loaded drum rack but no loadable drum kits found at '{kit_path}'"
        
        # Step 4: Load the first loadable kit
        kit_uri = loadable_kits[0].get("uri")
        load_result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": kit_uri
        })
        
        return f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}"
    except Exception as e:
        logger.error(f"Error loading drum kit: {str(e)}")
        return f"Error loading drum kit: {str(e)}"

# ── Arrangement view tools ────────────────────────────────────────────────────

@mcp.tool()
def switch_to_arrangement_view(ctx: Context) -> str:
    """Switch Ableton's main window to the Arrangement view.
    """
    try:
        ableton = get_ableton_connection()
        ableton.send_command("switch_to_arrangement_view")
        return "Switched to Arrangement view"
    except Exception as e:
        logger.error(f"Error switching to arrangement view: {str(e)}")
        return f"Error switching to arrangement view: {str(e)}"


@mcp.tool()
def set_arrangement_time(ctx: Context, time: float) -> str:
    """
    Move the arrangement playhead to a specific position.

    Parameters:
    - time: Position in beats from the start of the arrangement (e.g. 8.0 = bar 3 in 4/4)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_current_song_time", {"time": time})
        current = result.get('current_song_time', time)
        if result.get("settled") is False:
            return (f"Requested playhead move to beat {time}, but Live still "
                    f"reports beat {current}")
        return f"Playhead moved to beat {current}"
    except Exception as e:
        logger.error(f"Error setting arrangement time: {str(e)}")
        return f"Error setting arrangement time: {str(e)}"


@mcp.tool()
def get_arrangement_clips(ctx: Context, track_index: int) -> str:
    """
    List all clips placed in the Arrangement timeline for a track.

    Returns each clip's name, start_time, end_time, length, and type.

    Parameters:
    - track_index: The index of the track to inspect
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_arrangement_clips", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting arrangement clips: {str(e)}")
        return f"Error getting arrangement clips: {str(e)}"


@mcp.tool()
def duplicate_to_arrangement(
    ctx: Context,
    track_index: int,
    clip_index: int,
    destination_time: float
) -> str:
    """
    Copy a Session-view clip into the Arrangement timeline.

    Uses Live's track.duplicate_clip_to_arrangement() API (Live 11 / 12).
    The clip is placed at destination_time beats from the start of the
    arrangement on the same track it lives in.

    Typical workflow:
      1. create_clip / add_notes_to_clip to build a Session clip
      2. Call duplicate_to_arrangement once per bar/section you need
      3. Call switch_to_arrangement_view to confirm the result in Live

    Parameters:
    - track_index:       Index of the track that owns the Session clip
    - clip_index:        Index of the clip slot in that track (Session view)
    - destination_time:  Beat position in the arrangement to place the clip
                         (e.g. 0.0 = start, 8.0 = bar 3 in 4/4)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "duplicate_session_clip_to_arrangement",
            {
                "track_index": track_index,
                "clip_index": clip_index,
                "destination_time": destination_time
            }
        )
        clip_name = result.get("clip_name", "clip")
        track_name = result.get("track_name", f"track {track_index}")
        return (
            f"Duplicated '{clip_name}' from Session slot {clip_index} "
            f"on '{track_name}' to arrangement at beat {destination_time}"
        )
    except Exception as e:
        logger.error(f"Error duplicating clip to arrangement: {str(e)}")
        return f"Error duplicating clip to arrangement: {str(e)}"


@mcp.tool()
def create_locator(
    ctx: Context,
    name: str,
    time: float
) -> str:
    """
    Create a named locator (cue point) in the Arrangement at a beat position.

    If a locator already exists at that beat (within ~1e-3 tolerance) it is
    renamed instead of toggled off. Time is in beats from the start of the
    arrangement (e.g. 0.0 = start, 16.0 = bar 5 in 4/4).

    Parameters:
    - name: The locator label (e.g. "Chorus", "Verse 1", "Drop")
    - time: Beat position where the locator should sit
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("create_locator")
        if missing:
            return missing
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "create_locator",
            {"name": name, "time": time}
        )
        return (
            f"Locator '{result.get('name', name)}' set at beat "
            f"{result.get('time', time)}"
        )
    except Exception as e:
        logger.error(f"Error creating locator: {str(e)}")
        return f"Error creating locator: {str(e)}"


@mcp.tool()
def delete_locator(
    ctx: Context,
    name: str = "",
    time: float | None = None
) -> str:
    """
    Delete a locator (cue point) from the Arrangement, by beat position or name.

    Give `time` to delete the locator at that beat (most precise), or `name`
    to delete the locator with that label. If several locators share the
    name, nothing is deleted and their positions are listed so you can pick
    one by time. Playback must be stopped.

    Parameters:
    - name: The locator label (e.g. "Drop")
    - time: Beat position of the locator (takes precedence over name)
    """
    if time is None and not name:
        return "Give the locator's name or its time (beat position)."
    try:
        from .script_handshake import require_capability

        missing = require_capability("delete_locator")
        if missing:
            return missing
        params = {"time": time} if time is not None else {"name": name}
        result = get_ableton_connection().send_command("delete_locator", params)
        label = result.get("name") or "(unnamed)"
        return f"Locator '{label}' at beat {result.get('time')} deleted"
    except Exception as e:
        logger.error(f"Error deleting locator: {str(e)}")
        return f"Error deleting locator: {str(e)}"


# ───────────────────────────── Routing ──────────────────────────────

@mcp.tool()
def get_track_routing(ctx: Context, track_index: int, track_type: str = "track") -> str:
    """
    Read a track's input/output routing and monitoring, with the options Live
    offers for each (names as shown in Live's I/O section, in Live's language).

    Parameters:
    - track_index: Index of the track (return index for "return", ignored for "master")
    - track_type: "track" (default), "return" or "master" (these two only have an output)
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("get_track_routing")
        if missing:
            return missing
        params: Dict[str, Any] = {"track_index": track_index}
        missing = _apply_track_type(params, track_type)
        if missing:
            return missing
        result = get_ableton_connection().send_command("get_track_routing", params)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error getting track routing: {str(e)}")
        return f"Error getting track routing: {str(e)}"


@mcp.tool()
def set_track_routing(
    ctx: Context,
    track_index: int,
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
        from .script_handshake import require_capability

        missing = require_capability("set_track_routing")
        if missing:
            return missing
        params: Dict[str, Any] = {"track_index": track_index}
        for key, value in (("input_type", input_type), ("input_channel", input_channel),
                           ("output_type", output_type), ("output_channel", output_channel),
                           ("monitoring", monitoring)):
            if value is not None:
                params[key] = value
        missing = _apply_track_type(params, track_type)
        if missing:
            return missing
        result = get_ableton_connection().send_command("set_track_routing", params)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error setting track routing: {str(e)}")
        return f"Error setting track routing: {str(e)}"


# ─────────────────────── Recording / listening ──────────────────────

# Extra time allowed past the expected end of a recording.
RECORDING_MARGIN_S = 5.0
RECORDING_POLL_S = 0.5


def _wait_for_recording(ableton, expected_s: float, max_wait_s: float,
                        on_poll=None) -> Dict[str, Any]:
    """Poll get_recording_status until the watcher in Live has finished.
    ``on_poll`` runs at each poll while recording (e.g. to sample meters)."""
    import time

    deadline = time.monotonic() + min(expected_s + RECORDING_MARGIN_S, max_wait_s)
    status: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        status = ableton.send_command("get_recording_status")
        rec = status.get("recording") or {}
        if rec.get("finished"):
            return status
        if on_poll is not None:
            try:
                on_poll()
            except Exception as e:  # metering must never break a take
                logger.warning(f"Meter sampling failed: {e}")
                on_poll = None
        time.sleep(RECORDING_POLL_S)
    ableton.send_command("stop_arrangement_recording")
    status = ableton.send_command("get_recording_status")
    status["timed_out"] = True
    return status


@mcp.tool()
def record_arrangement(
    ctx: Context,
    start_time: float,
    end_time: float,
    wait: bool = True,
    max_wait_seconds: float = 600.0,
) -> str:
    """
    Record the armed tracks into the Arrangement between two song positions
    (in beats): moves the playhead, turns Arrangement Record on, plays, and
    stops at end_time. Arm tracks first (set_track_arm).

    Parameters:
    - start_time: Song position to start at (beats)
    - end_time: Song position to stop at (beats)
    - wait: Block until the recording ends (default) or return at once
      (then poll get_recording_status)
    - max_wait_seconds: Safety limit when waiting; recording is stopped past it
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("record_arrangement")
        if missing:
            return missing
        ableton = get_ableton_connection()
        tempo = float(ableton.send_command("get_session_info").get("tempo") or 120.0)
        result = ableton.send_command(
            "record_arrangement", {"start_time": start_time, "end_time": end_time})
        if not wait:
            return json.dumps(result, indent=2, ensure_ascii=False)
        expected = (end_time - start_time) * 60.0 / tempo
        status = _wait_for_recording(ableton, expected, max_wait_seconds)
        return json.dumps(status, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error recording arrangement: {str(e)}")
        return f"Error recording arrangement: {str(e)}"


@mcp.tool()
def get_recording_status(ctx: Context) -> str:
    """
    State of the current or last record_arrangement run (finished, reason,
    stop position), plus Arrangement Record, transport and armed tracks.
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("get_recording_status")
        if missing:
            return missing
        result = get_ableton_connection().send_command("get_recording_status")
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error getting recording status: {str(e)}")
        return f"Error getting recording status: {str(e)}"


@mcp.tool()
def stop_arrangement_recording(ctx: Context) -> str:
    """
    Stop a running record_arrangement now (turns Arrangement Record off and
    stops playback).
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("stop_arrangement_recording")
        if missing:
            return missing
        result = get_ableton_connection().send_command("stop_arrangement_recording")
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error stopping recording: {str(e)}")
        return f"Error stopping recording: {str(e)}"


@mcp.tool()
def get_audio_clip_file(ctx: Context, track_index: int, clip_index: int,
                        location: str = "arrangement") -> str:
    """
    Path of the audio file behind an audio clip (for example a take just
    recorded with record_arrangement), with its length and sample rate.

    Parameters:
    - track_index: Track that owns the clip
    - clip_index: Arrangement clip index (get_arrangement_clips) or Session slot
    - location: "arrangement" (default) or "session"
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("get_audio_clip_file")
        if missing:
            return missing
        result = get_ableton_connection().send_command("get_audio_clip_file", {
            "track_index": track_index, "clip_index": clip_index,
            "location": (location or "arrangement").lower()})
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error getting audio clip file: {str(e)}")
        return f"Error getting audio clip file: {str(e)}"


@mcp.tool()
def analyze_audio_file(ctx: Context, file_path: str, segment_seconds: float = 1.0) -> str:
    """
    Measure a WAV or AIFF file: peak and RMS levels (dBFS), clipping, crest
    factor, loudness over time (one value per segment), leading/trailing
    silence, stereo correlation and a coarse spectral balance (low < 250 Hz,
    mid, high > 4 kHz), with warnings. Use it to check a mix or a recorded take.

    Parameters:
    - file_path: Absolute path of the audio file
    - segment_seconds: Length of each loudness segment (default 1 s)
    """
    try:
        from .audio_analysis import analyze_audio

        result = analyze_audio(os.path.expanduser(file_path), segment_seconds=segment_seconds)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error analyzing audio file: {str(e)}")
        return f"Error analyzing audio file: {str(e)}"


RESAMPLING_NAMES = ("resampling", "rééchantillonnage", "reechantillonnage",
                    "resampling", "neu-sampling", "remuestreo", "ricampionamento")


def _resampling_input_name(routing: Dict[str, Any]) -> Union[str, None]:
    """The localized name Live gives the Resampling input."""
    options = (routing.get("input") or {}).get("available_types") or []
    for name in options:
        low = (name or "").lower()
        if any(key in low for key in RESAMPLING_NAMES) or "sampl" in low:
            return name
    return None


MIX_TARGETS = ("streaming", "club", "classical", "broadcast", "podcast")


LISTEN_TRACK_NAME = "Claude – écoute"
SPECTROGRAMS_KEPT = 20


def _discard_take(path: str) -> bool:
    """Delete a listening take and Live's .asd analysis file next to it.

    Only files Live named after the listening track are touched, so a user's
    own recording can never be removed by mistake."""
    import unicodedata

    if not path:
        return False
    name = unicodedata.normalize("NFC", os.path.basename(path))
    if not name.startswith(LISTEN_TRACK_NAME) or not name.lower().endswith((".wav", ".aif", ".aiff")):
        return False
    removed = False
    for target in (path, path + ".asd"):
        try:
            os.remove(target)
            removed = removed or target == path
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"Could not delete {target}: {e}")
    return removed


def _spectrogram_path(audio_path: str) -> str:
    import tempfile

    folder = os.path.join(tempfile.gettempdir(), "ableton-mcp")
    os.makedirs(folder, exist_ok=True)
    # Keep only the most recent images: older ones have been looked at.
    try:
        pngs = sorted((os.path.join(folder, f) for f in os.listdir(folder) if f.endswith("_spectrogram.png")),
                      key=os.path.getmtime)
        for old in pngs[:-SPECTROGRAMS_KEPT]:
            os.remove(old)
    except OSError:
        pass
    base = os.path.splitext(os.path.basename(audio_path))[0]
    return os.path.join(folder, base + "_spectrogram.png")


def _mix_report(path: str, target: str, spectrogram: bool):
    """(report dict, png path or None) from mix_analysis."""
    from .mix_analysis import analyze_mix

    png = _spectrogram_path(path) if spectrogram else None
    return analyze_mix(path, target=target, spectrogram_path=png), png


def _with_image(payload: Dict[str, Any], png: Union[str, None]):
    """Tool result: the JSON report, plus the spectrogram as an image the
    model can look at."""
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if png and os.path.exists(png):
        from mcp.server.fastmcp import Image

        return [text, Image(path=png)]
    return text


class _MeterSampler:
    """Samples Live's track meters during a take and summarises them."""

    def __init__(self, ableton, skip_track: int):
        self.ableton, self.skip = ableton, skip_track
        self.samples: Dict[tuple, List[float]] = {}

    def __call__(self):
        data = self.ableton.send_command("get_track_meters")
        for m in data.get("meters", []):
            if m["type"] == "track" and m["index"] == self.skip:
                continue
            level = m.get("level")
            if level is not None:
                self.samples.setdefault((m["type"], m["index"], m["name"]), []).append(level)

    def summary(self) -> List[Dict[str, Any]]:
        out = []
        for (kind, index, name), vals in self.samples.items():
            active = [v for v in vals if v > 0.01]
            out.append({
                "type": kind, "index": index, "name": name,
                "peak_meter": round(max(vals), 3) if vals else None,
                "mean_meter_when_playing": round(sum(active) / len(active), 3) if active else 0.0,
                "active_pct": round(100.0 * len(active) / len(vals), 0) if vals else 0.0,
            })
        out.sort(key=lambda m: (m["type"] != "master", -m["mean_meter_when_playing"]))
        return out


@mcp.tool()
def get_track_meters(ctx: Context) -> str:
    """
    Live's output meters right now for every track, return track and the
    main track (0.0-1.0 on Live's meter scale, as in the mixer). Meaningful
    while the song plays; listen_to_arrangement samples them for you.
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("get_track_meters")
        if missing:
            return missing
        result = get_ableton_connection().send_command("get_track_meters")
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error getting track meters: {str(e)}")
        return f"Error getting track meters: {str(e)}"


@mcp.tool()
def analyze_mix(ctx: Context, file_path: str, target: str = "streaming",
                spectrogram: bool = True):
    """
    Mastering-engineer report on a WAV/AIFF mix: loudness per ITU-R BS.1770 /
    EBU R128 (integrated, short-term and momentary max, loudness range), true
    peak (4x oversampled), PLR, crest factor, long-term 1/3-octave spectrum
    with tilt and per-region deviation from a balanced -4.5 dB/oct reference
    (mud, harshness, sibilance, air, sub), narrow resonances (with note names),
    stereo correlation and width overall and per band (low-end mono), DC.
    Returns findings ranked problème / attention / ok with concrete fixes
    against the delivery target, plus a spectrogram image (log frequency,
    with the short-term loudness curve) to look at.

    Parameters:
    - file_path: Absolute path of the audio file
    - target: "streaming" (default, -14 LUFS), "club", "classical", "broadcast"
      (EBU -23 LUFS) or "podcast"
    - spectrogram: Also return the spectrogram image (default True)
    """
    try:
        if target not in MIX_TARGETS:
            return "target must be one of: %s" % ", ".join(MIX_TARGETS)
        report, png = _mix_report(os.path.expanduser(file_path), target, spectrogram)
        return _with_image(report, png)
    except Exception as e:
        logger.error(f"Error analyzing mix: {str(e)}")
        return f"Error analyzing mix: {str(e)}"


@mcp.tool()
def listen_to_arrangement(
    ctx: Context,
    start_time: float,
    end_time: float,
    target: str = "streaming",
    report: str = "mix",
    keep_track: bool = False,
    keep_audio: bool = False,
    segment_seconds: float = 1.0,
    max_wait_seconds: float = 600.0,
):
    """
    "Listen" to the song like a mastering engineer: record the main output
    between two song positions (beats) onto a temporary resampling audio
    track, sample every track's meter during the take, then analyze it.

    report="mix" (default) returns the full analyze_mix report (LUFS, true
    peak, PLR, tonal balance, resonances, stereo, findings with fixes against
    `target`) plus a spectrogram image, and each track's meter level during
    the take (which tracks carry the mix). report="basic" returns only levels,
    loudness per segment and a coarse spectral balance.
    Plays the song in real time, so it takes as long as the passage.

    Parameters:
    - start_time: Song position to start at (beats)
    - end_time: Song position to stop at (beats); add a few beats to hear reverb tails
    - target: Delivery target for the mix report: "streaming", "club",
      "classical", "broadcast" or "podcast"
    - report: "mix" (default) or "basic"
    - keep_track: Keep the recording track and its take in the set (default:
      delete both once analysed)
    - keep_audio: Keep the recorded file in the project's Samples/Recorded
      folder after deleting the track (default: delete it, so listening never
      piles up audio files in the project)
    - segment_seconds: Length of each loudness segment (basic report)
    - max_wait_seconds: Safety limit for the recording
    """
    from .script_handshake import require_capability

    for cap in ("set_track_routing", "record_arrangement", "get_audio_clip_file"):
        missing = require_capability(cap)
        if missing:
            return missing
    if report not in ("mix", "basic"):
        return "report must be 'mix' or 'basic'"
    if report == "mix" and target not in MIX_TARGETS:
        return "target must be one of: %s" % ", ".join(MIX_TARGETS)
    ableton = get_ableton_connection()
    track_index = None
    armed_before = []
    path = None
    try:
        session = ableton.send_command("get_session_info")
        tempo = float(session.get("tempo") or 120.0)
        # Only the listening track may record: disarm the others for the take.
        status = ableton.send_command("get_recording_status")
        armed_before = [t["index"] for t in status.get("armed_tracks", [])]
        for idx in armed_before:
            ableton.send_command("set_track_arm", {"track_index": idx, "arm": False})

        created = ableton.send_command("create_audio_track", {"index": -1})
        track_index = int(created["index"])
        ableton.send_command("set_track_name", {"track_index": track_index,
                                                "name": LISTEN_TRACK_NAME})
        routing = ableton.send_command("get_track_routing", {"track_index": track_index})
        resampling = _resampling_input_name(routing)
        if not resampling:
            raise RuntimeError("No Resampling input found among: %s"
                               % (routing.get("input") or {}).get("available_types"))
        ableton.send_command("set_track_routing", {
            "track_index": track_index, "input_type": resampling, "monitoring": "off"})
        ableton.send_command("set_track_arm", {"track_index": track_index, "arm": True})

        ableton.send_command("record_arrangement",
                             {"start_time": start_time, "end_time": end_time})
        expected = (end_time - start_time) * 60.0 / tempo
        sampler = None
        if report == "mix" and require_capability("get_track_meters") is None:
            sampler = _MeterSampler(ableton, track_index)
        rec_status = _wait_for_recording(ableton, expected, max_wait_seconds, on_poll=sampler)
        ableton.send_command("set_track_arm", {"track_index": track_index, "arm": False})

        clips = ableton.send_command("get_arrangement_clips",
                                     {"track_index": track_index}).get("clips", [])
        if not clips:
            raise RuntimeError("Nothing was recorded (status: %s)" % json.dumps(rec_status))
        file_info = ableton.send_command("get_audio_clip_file", {
            "track_index": track_index, "clip_index": len(clips) - 1,
            "location": "arrangement"})
        path = file_info.get("file_path")
        if not path:
            raise RuntimeError("Live did not report the recorded file's path")

        from .audio_analysis import analyze_audio
        import time

        # Live finishes writing the file just after recording stops.
        analysis, png, last_error = None, None, None
        for _ in range(10):
            try:
                if report == "mix":
                    analysis, png = _mix_report(path, target, True)
                else:
                    analysis = analyze_audio(path, segment_seconds=segment_seconds)
                break
            except ImportError:  # numpy missing: fall back to the basic report
                report = "basic"
            except Exception as e:  # file still being finalised
                last_error = e
                time.sleep(0.5)
        if analysis is None:
            raise RuntimeError("Could not read the recorded file: %s" % last_error)

        result = {
            "recorded": {"start_time": start_time, "end_time": end_time,
                         "file_path": path, "status": rec_status.get("recording")},
            "analysis": analysis,
        }
        if sampler is not None:
            result["track_meters_during_take"] = {
                "scale": "Live meter scale 0.0-1.0 (as in the mixer), sampled every %.1f s"
                         % RECORDING_POLL_S,
                "tracks": sampler.summary(),
            }
        if not keep_track:
            ableton.send_command("delete_track", {"track_index": track_index})
            track_index = None
            if keep_audio:
                result["recorded"]["track"] = "deleted (file kept)"
            else:
                removed = _discard_take(path)
                result["recorded"]["track"] = "deleted"
                result["recorded"]["file"] = "deleted" if removed else "kept (could not delete)"
        else:
            result["recorded"]["track_index"] = track_index
        return _with_image(result, png)
    except Exception as e:
        logger.error(f"Error listening to arrangement: {str(e)}")
        if track_index is not None and not keep_track:
            try:
                ableton.send_command("stop_arrangement_recording")
                ableton.send_command("delete_track", {"track_index": track_index})
                if path and not keep_audio:
                    _discard_take(path)
            except Exception:
                pass
        return f"Error listening to arrangement: {str(e)}"
    finally:
        for idx in armed_before:
            try:
                ableton.send_command("set_track_arm", {"track_index": idx, "arm": True})
            except Exception:
                pass


# ─────────────────────────── MIDI files ─────────────────────────────

ADD_NOTES_CHUNK = 1000


@mcp.tool()
def import_midi_file(
    ctx: Context,
    file_path: str,
    track_index: int = None,
    clip_index: int = 0,
    midi_track: int = None,
    channel: int = None,
    transpose: int = 0,
    location: str = "session",
    replace: bool = False,
    clip_length: float = None,
) -> str:
    """
    Import the notes of a Standard MIDI File (.mid) into a clip. Without
    track_index, only describes the file (tracks, note counts, channels,
    length) so you can pick midi_track / channel first.

    Session: an empty slot gets a new clip as long as the notes (rounded up to
    a 4-beat bar) or clip_length; an existing clip receives the notes (after
    clearing it when replace=True). Arrangement: the clip must exist
    (index from get_arrangement_clips). Times are in beats; the file's tempo
    is ignored.

    Parameters:
    - file_path: Absolute path of the .mid file
    - track_index: Target MIDI track (omit to only describe the file)
    - clip_index: Session slot, or Arrangement clip index
    - midi_track: Track of the MIDI file to import (default: all, merged)
    - channel: MIDI channel to keep, 0-15 (default: all)
    - transpose: Semitones to add to every pitch
    - location: "session" (default) or "arrangement"
    - replace: Clear the target clip's notes first
    - clip_length: Length in beats of a newly created Session clip
    """
    try:
        from .midi_file import merge_duplicates, read_midi_file, select_notes, summarize

        path = os.path.expanduser(file_path)
        parsed = read_midi_file(path)
        if track_index is None:
            return json.dumps({"file": path, "format": parsed["format"],
                               "ticks_per_beat": parsed["division"],
                               "tracks": summarize(parsed)}, indent=2, ensure_ascii=False)
        notes = select_notes(parsed, midi_track=midi_track, channel=channel,
                             transpose=transpose)
        if not notes:
            return "No notes to import with these filters"
        notes, merged = merge_duplicates(notes)
        location = (location or "session").lower()
        missing = _arrangement_notes_missing(location)
        if missing:
            return missing
        ableton = get_ableton_connection()
        created = False
        if location == "session":
            info = ableton.send_command("get_track_info", {"track_index": track_index})
            slots = info.get("clip_slots", [])
            if clip_index < 0 or clip_index >= len(slots):
                return f"Clip slot {clip_index} out of range ({len(slots)} slots)"
            if not slots[clip_index].get("has_clip"):
                end = max(n["start_time"] + n["duration"] for n in notes)
                length = clip_length or max(4.0, 4.0 * math.ceil(end / 4.0 - 1e-9))
                ableton.send_command("create_clip", {"track_index": track_index,
                                                     "clip_index": clip_index,
                                                     "length": length})
                created = True
        if replace and not created:
            ableton.send_command("clear_notes_from_clip",
                                 _note_params(track_index, clip_index, location))
        for i in range(0, len(notes), ADD_NOTES_CHUNK):
            params = _note_params(track_index, clip_index, location)
            params["notes"] = notes[i:i + ADD_NOTES_CHUNK]
            ableton.send_command("add_notes_to_clip", params)
        where = (f"new clip in slot {clip_index}" if created
                 else f"{location} clip {clip_index}")
        return (f"Imported {len(notes)} notes from {os.path.basename(path)} into "
                f"{where} on track {track_index}"
                + (" (replaced existing notes)" if replace and not created else "")
                + (f"; {merged} duplicate note(s) (same pitch and start in two voices) "
                   f"merged, as Live keeps one" if merged else ""))
    except Exception as e:
        logger.error(f"Error importing MIDI file: {str(e)}")
        return f"Error importing MIDI file: {str(e)}"


# ─────────────────────────── Music theory ───────────────────────────

def _json(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp.tool()
def music_scales(ctx: Context, query: str = None, root: str = None, scale: str = None) -> str:
    """
    Scales and modes knowledge. Without arguments, lists all ~50 scales
    (church modes, harmonic/melodic minor families, pentatonics, blues,
    bebop, symmetric, Japanese, gamelan, flamenco...) with their character
    and typical styles; `query` filters (e.g. "flamenco", "jazz", "sombre").
    With `root` and `scale`, details one scale: notes spelled in the key,
    degrees, characteristic note, character, styles, diatonic seventh chords
    with roman numerals and functions, the other modes with the same notes,
    and Live 12's scale name (for set_song_scale).

    Parameters:
    - query: Text to filter the list
    - root: Tonic (e.g. "D", "Eb") to detail one scale
    - scale: Scale name (e.g. "dorian", "phrygian dominant", "hijaz", "harmonic minor")
    """
    try:
        from . import music_theory as mt

        if root is not None and scale is not None:
            return _json(mt.scale_info(root, scale))
        return _json(mt.search_scales(query))
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def music_styles(ctx: Context, style: str = None) -> str:
    """
    Style sheets for composing or re-arranging: without `style`, the list;
    with it, what makes the style: tempo, metre, scales/modes, harmonic
    language, typical progressions (roman numerals for write_progression),
    rhythm/groove and swing amount, bass, melody, arrangement, accompaniment
    patterns, and which Live devices/tools help. Styles: baroque,
    classical_romantic, jazz, bossa_nova, blues, gospel_neo_soul, funk, pop,
    rock, house, techno, trance, drum_and_bass, hip_hop_boom_bap, lofi, trap,
    rnb, reggae, reggaeton, afrobeat, flamenco, film_epic, ambient, synthwave
    (aliases such as "Bach", "lo-fi", "dnb" work).

    Parameters:
    - style: Style name (optional)
    """
    try:
        from . import music_styles as ms

        return _json(ms.get_style(style) if style else ms.list_styles())
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def music_chord_ideas(ctx: Context, chord: str, key_root: str = None) -> str:
    """
    Reharmonisation ideas for a chord (tritone substitution, ii-V
    preparation, relative chords, extensions, borrowed chords in the key),
    with the reason for each, plus the chord's notes.

    Parameters:
    - chord: Chord symbol, e.g. "G7", "Fmaj7", "Am", "Bø", "Ebmaj7/G"
    - key_root: Key tonic, to suggest borrowed chords (optional)
    """
    try:
        from . import music_theory as mt

        r, q, ivs, bass = mt.parse_chord(chord)
        kr = mt.parse_pitch_class(key_root) if key_root else None
        return _json({
            "chord": chord,
            "notes": [mt.pc_name((r + i) % 12, kr) for i in ivs],
            "roman_in_key": mt.roman_numeral(r, q, kr) if kr is not None else None,
            "ideas": mt.substitutions(chord, key_root),
        })
    except Exception as e:
        return f"Error: {str(e)}"


def _read_clip_notes(ableton, track_index: int, clip_index: int, location: str):
    data = ableton.send_command("get_clip_notes", _note_params(track_index, clip_index, location))
    return data.get("notes", []), data


@mcp.tool()
def analyze_clip_music(
    ctx: Context,
    track_index: int,
    clip_index: int,
    location: str = "session",
    segment_beats: float = 2.0,
    key_root: str = None,
    key_scale: str = None,
    vocabulary: str = "basic",
) -> str:
    """
    Musical analysis of a MIDI clip: key and mode candidates (with coverage
    and outside notes; relative modes are told apart by the harmony, e.g. a
    V7 pointing to its tonic), chords per segment with roman numerals,
    out-of-scale notes, range, rhythm (density, offbeat share, polyphony) and
    melodic motion of the top line. Also reports Live's song scale.

    Parameters:
    - track_index / clip_index: The clip (Session slot or Arrangement index)
    - location: "session" (default) or "arrangement"
    - segment_beats: Chord detection window (2 = two chords per bar by default,
      4 = one per bar, 1 per beat); identical neighbours are merged
    - key_root / key_scale: Force the key used for roman numerals (optional)
    - vocabulary: "basic" (triads and sevenths: classical, pop, counterpoint)
      or "jazz" (adds 6, 9, sus and extended chords)
    """
    try:
        from . import music_theory as mt

        missing = _arrangement_notes_missing(location)
        if missing:
            return missing
        ableton = get_ableton_connection()
        notes, data = _read_clip_notes(ableton, track_index, clip_index, location)
        result = mt.analyze_notes(notes, segment_beats=segment_beats, key_root=key_root,
                                  key_scale=key_scale, vocabulary=vocabulary)
        result["clip"] = {"name": data.get("clip_name"), "length": data.get("length")}
        from .script_handshake import require_capability

        if require_capability("get_song_scale") is None:
            try:
                result["live_song_scale"] = ableton.send_command("get_song_scale")
            except Exception:
                pass
        return _json(result)
    except Exception as e:
        logger.error(f"Error analyzing clip: {str(e)}")
        return f"Error analyzing clip: {str(e)}"


@mcp.tool()
def transform_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    operations: List[Dict[str, Any]],
    location: str = "session",
    target_clip_index: int = None,
) -> str:
    """
    Re-arrange a MIDI clip with a chain of music-theory operations, applied in
    order. Writes the result back into the clip, or into an empty Session slot
    `target_clip_index` (keeps the original: safer for trying ideas).

    Each operation is {"op": name, ...arguments}:
    - transpose: semitones
    - transpose_diatonic: steps, root, scale (moves along the scale)
    - change_mode: root, from_scale, to_scale[, to_root] (C major -> C dorian...)
    - snap_to_scale: root, scale[, direction nearest|up|down]
    - invert: axis ("C4" or 60)[, root, scale for a diatonic mirror]
    - retrograde: [length]
    - time_scale: factor (2 = half speed, 0.5 = double)
    - quantize: [grid=0.25, strength=1.0, durations=false]
    - swing: [amount_pct=60 (50 straight, 66.7 triplet), grid=0.5]
    - humanize: [timing=0.01 beats, velocity=8, seed=0]
    - accent: [pattern=[1,0.7,0.85,0.7], grid=1.0, base=110]
    - articulate: factor (0.5 = staccato) or legato=true
    - fold_range: low, high (e.g. "C3", "C5")
    - harmonize: root, scale[, steps=[2] (2 = third above, -2 below, 4 fifth, 5 sixth), keep_original=true]
    - arpeggiate: [rate=0.25, pattern up|down|updown|random, octaves=1, gate=0.9]
    - strum: [spread=0.03, direction down|up]
    - voice_chords: voicing close|drop2|open|spread
    Notes are written as C4 = MIDI 60 (Live displays it as C3).

    Parameters:
    - track_index / clip_index: Source clip
    - operations: List of operations (see above)
    - location: "session" (default) or "arrangement"
    - target_clip_index: Empty Session slot on the same track for the result (optional)
    """
    try:
        from . import music_theory as mt

        missing = _arrangement_notes_missing(location)
        if missing:
            return missing
        ableton = get_ableton_connection()
        notes, data = _read_clip_notes(ableton, track_index, clip_index, location)
        if not notes:
            return "The clip has no notes"
        result = mt.apply_operations(notes, operations)
        if target_clip_index is not None:
            if location != "session":
                return "target_clip_index is for Session clips"
            end = max(n["start_time"] + n["duration"] for n in result)
            length = max(float(data.get("length") or 4.0), 4.0 * math.ceil(end / 4.0 - 1e-9))
            ableton.send_command("create_clip", {"track_index": track_index,
                                                 "clip_index": target_clip_index, "length": length})
            dest = target_clip_index
        else:
            ableton.send_command("clear_notes_from_clip", _note_params(track_index, clip_index, location))
            dest = clip_index
        for i in range(0, len(result), ADD_NOTES_CHUNK):
            params = _note_params(track_index, dest, location)
            params["notes"] = result[i:i + ADD_NOTES_CHUNK]
            ableton.send_command("add_notes_to_clip", params)
        after = mt.analyze_notes(result)
        return _json({
            "written_to": ("slot %d" % dest) if target_clip_index is not None else "same clip",
            "notes_before": len(notes), "notes_after": len(result),
            "operations": [o.get("op") or o.get("operation") for o in operations],
            "key_after": after.get("key", {}).get("best"),
            "chords_after": after.get("chords", [])[:16],
        })
    except Exception as e:
        logger.error(f"Error transforming clip: {str(e)}")
        return f"Error transforming clip: {str(e)}"


@mcp.tool()
def write_progression(
    ctx: Context,
    track_index: int,
    clip_index: int,
    root: str,
    scale: str = "major",
    numerals: List[str] = None,
    style: str = None,
    progression_index: int = 0,
    beats_per_chord: float = 4.0,
    pattern: str = None,
    low: str = "E3",
    high: str = "G4",
    bass: bool = True,
    repeat: int = 1,
    voices: int = 4,
) -> str:
    """
    Write a chord progression into an empty Session slot (clip created to
    fit) or an existing clip, voiced with smooth voice leading and played
    with an accompaniment pattern.

    Give `numerals` (roman numerals in the key: "ii7", "V7", "Imaj7",
    "bVII", "iv", "V/V", "N6", "viiø7"...) or a `style` (its typical
    progression number `progression_index`, its scale and pattern are used
    unless given). Patterns: block, pulse, pulse8, offbeat, arp8, arp16,
    alberti, bossa, waltz, ballad, stabs.

    Parameters:
    - track_index / clip_index: Target MIDI track and Session slot
    - root: Key tonic ("C", "F#", "Bb")
    - scale: Scale/mode of the key (default major)
    - numerals: Roman numerals (optional if style)
    - style: Style name (see music_styles)
    - progression_index: Which of the style's progressions
    - beats_per_chord: Harmonic rhythm (4 = one chord per bar)
    - pattern: Accompaniment pattern (default: the style's first, else block)
    - low / high: Range of the chord voicings
    - bass: Add a bass line (root, an octave or two below)
    - repeat: Times to repeat the progression
    - voices: Notes per chord voicing (3-5)
    """
    try:
        from . import music_styles as ms
        from . import music_theory as mt

        st = ms.get_style(style) if style else None
        if numerals is None:
            if not st:
                return "Give numerals or a style"
            numerals = st["progressions"][progression_index % len(st["progressions"])]
            if scale == "major" and st["scales"]:
                first = numerals[0]
                scale = st["scales"][0] if first[:1].islower() or first.startswith(("b", "#")) else scale
        pattern = pattern or (st["patterns"][0] if st else "block")
        chords = mt.progression(root, scale, list(numerals) * max(repeat, 1))
        notes = mt.render_progression(chords, beats_per_chord=beats_per_chord, pattern=pattern,
                                      low=low, high=high, bass=bass, voices=voices)
        ableton = get_ableton_connection()
        info = ableton.send_command("get_track_info", {"track_index": track_index})
        slots = info.get("clip_slots", [])
        if clip_index < 0 or clip_index >= len(slots):
            return f"Clip slot {clip_index} out of range ({len(slots)} slots)"
        length = beats_per_chord * len(chords)
        if not slots[clip_index].get("has_clip"):
            ableton.send_command("create_clip", {"track_index": track_index, "clip_index": clip_index,
                                                 "length": length})
        for i in range(0, len(notes), ADD_NOTES_CHUNK):
            params = _note_params(track_index, clip_index, "session")
            params["notes"] = notes[i:i + ADD_NOTES_CHUNK]
            ableton.send_command("add_notes_to_clip", params)
        return _json({
            "key": "%s %s" % (root, mt.scale_key(scale)),
            "style": st["style"] if st else None,
            "pattern": pattern,
            "chords": [{"numeral": c["numeral"], "symbol": c["symbol"]} for c in chords[:len(numerals)]],
            "notes_written": len(notes),
            "clip_length_beats": length,
            "swing_hint_pct": st["swing"] if st else None,
        })
    except Exception as e:
        logger.error(f"Error writing progression: {str(e)}")
        return f"Error writing progression: {str(e)}"


@mcp.tool()
def get_song_scale(ctx: Context) -> str:
    """
    Live 12's song scale: root, scale name, intervals and the Scale Mode
    switch (which highlights the scale in the piano roll and drives devices
    set to "Use Current Scale", e.g. the Scale, Arpeggiator and Chord devices).
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("get_song_scale")
        if missing:
            return missing
        return _json(get_ableton_connection().send_command("get_song_scale"))
    except Exception as e:
        return f"Error getting song scale: {str(e)}"


@mcp.tool()
def set_song_scale(ctx: Context, root: str = None, scale: str = None, scale_mode: bool = None) -> str:
    """
    Set Live 12's song scale so the piano roll shows it and scale-aware
    devices follow it. `scale` accepts this server's names (dorian, hijaz,
    harmonic minor...) and maps them to Live's name when Live has the scale.

    Parameters:
    - root: Tonic ("C", "Eb", "F#")
    - scale: Scale name
    - scale_mode: Turn Live's Scale Mode on/off
    """
    try:
        from . import music_theory as mt
        from .script_handshake import require_capability

        missing = require_capability("set_song_scale")
        if missing:
            return missing
        params: Dict[str, Any] = {}
        if root is not None:
            params["root_note"] = mt.parse_pitch_class(root)
        if scale is not None:
            try:
                live_name = mt.SCALES[mt.scale_key(scale)]["live_name"]
            except mt.TheoryError:
                live_name = scale  # maybe one of Live's own names
            if not live_name:
                return ("Live has no '%s' scale; set the closest one or keep it out of Live's "
                        "scale and use snap_to_scale on the clips" % scale)
            params["scale_name"] = live_name
        if scale_mode is not None:
            params["scale_mode"] = scale_mode
        return _json(get_ableton_connection().send_command("set_song_scale", params))
    except Exception as e:
        return f"Error setting song scale: {str(e)}"


# ───────────────────────────── Drums ────────────────────────────────

def _kit_roles(ableton, track_index: int):
    """(roles, rack info or None) from the track's Drum Rack pad names."""
    from . import drums
    from .script_handshake import require_capability

    if require_capability("get_drum_rack_map") is not None:
        return {}, None
    try:
        kit = ableton.send_command("get_drum_rack_map", {"track_index": track_index})
    except Exception:
        return {}, None
    return drums.infer_roles(kit.get("pads", [])), kit


@mcp.tool()
def drum_patterns(ctx: Context, style: str = None, euclid_hits: int = None, euclid_steps: int = 16,
                  euclid_rotate: int = 0) -> str:
    """
    Drum pattern library for electronic music. Without arguments, lists the
    styles (techno_four, techno_rolling, techno_hypnotic, minimal_techno,
    dub_techno, hard_techno, acid_techno, detroit_techno, house_classic,
    deep_house, tech_house, afro_house, uk_garage, breakbeat, electro,
    drum_and_bass, dubstep, trap, ebm). With `style`, its grids per role,
    tempo, swing, production notes and the available fills. With
    `euclid_hits`, returns a Euclidean rhythm grid, e.g. 3/8 = tresillo.

    Grid language (one string per role, 16 steps = one bar of 16ths):
    x hit · X accent · o ghost · . rest · 2 3 4 ratchet · ? 50 % chance · * 25 % chance ghost.

    Parameters:
    - style: Pattern style (optional)
    - euclid_hits / euclid_steps / euclid_rotate: Euclidean rhythm (optional)
    """
    try:
        from . import drums

        if euclid_hits is not None:
            return _json({"grid": drums.euclid(euclid_hits, euclid_steps, euclid_rotate)})
        return _json(drums.describe(style) if style else drums.list_patterns())
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def get_drum_map(ctx: Context, track_index: int) -> str:
    """
    The Drum Rack on a track: every filled pad (MIDI note, name, devices)
    and the role each one plays (kick, clap, closed_hat, open_hat, rim,
    ride, perc...), read from the pad names, as used by write_drum_pattern.

    Parameters:
    - track_index: Track holding the Drum Rack
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("get_drum_rack_map")
        if missing:
            return missing
        roles, kit = _kit_roles(get_ableton_connection(), track_index)
        if kit is None:
            return "No Drum Rack found on track %d" % track_index
        kit["roles"] = roles
        return _json(kit)
    except Exception as e:
        return f"Error reading the drum map: {str(e)}"


@mcp.tool()
def write_drum_pattern(
    ctx: Context,
    track_index: int,
    clip_index: int,
    style: str = None,
    layers: Dict[str, Any] = None,
    bars: int = 4,
    steps_per_bar: int = 16,
    swing_pct: float = None,
    fill: str = None,
    fill_every: int = 4,
    variation: float = 0.0,
    humanize: float = 0.0,
    replace: bool = False,
    seed: int = 0,
) -> str:
    """
    Program drums into a Session slot (clip created to fit) on a track with
    a Drum Rack. Roles are mapped to the kit's pads by their names (a
    similar free pad stands in for a missing role; missing ones are
    reported); without a Drum Rack, General MIDI notes are used.

    Start from a library `style` and/or give `layers`: {role: grid} or
    {role: {"euclid": [hits, steps, rotate]}}; layers override or extend the
    style. Roles: kick, clap, snare, rim, closed_hat, open_hat, pedal_hat,
    ride, crash, tom_low, tom_mid, tom_high, perc, shaker, tambourine, conga,
    bongo, clave, cowbell, fx. A grid shorter or longer than a bar cycles
    over the whole clip (a 12-step loop drifts against 16-step bars).
    Grid: x hit · X accent · o ghost · . rest · 2/3/4 ratchet · ? 50 % · * 25 % ghost
    (probabilities use Live 12's per-note chance, so the loop varies as it plays).

    Parameters:
    - track_index / clip_index: Drum track and Session slot
    - style: Library pattern (see drum_patterns)
    - layers: Extra or replacement grids per role
    - bars: Clip length in bars (4/4)
    - steps_per_bar: Grid resolution (16 = 16ths, 12 = 8th-note triplets, 32)
    - swing_pct: Swing on odd steps, 50 = straight (default: the style's)
    - fill: Every `fill_every` bars: roll, drop, open_hat, ratchet or crash
    - variation: 0-1, chance of extra ghost hats (written with low probability)
    - humanize: Timing spread in beats (e.g. 0.005), with small velocity changes
    - replace: Clear an existing clip in the slot first
    - seed: Random seed for variation/humanize
    """
    try:
        from . import drums
        from .script_handshake import require_capability

        grids: Dict[str, str] = {}
        swing = 50.0
        if style:
            grids.update(drums.pattern_layers(style))
            swing = drums.PATTERNS[style]["swing"]
        for role, spec in (layers or {}).items():
            if isinstance(spec, dict) and "euclid" in spec:
                e = list(spec["euclid"]) + [0] * (3 - len(spec["euclid"]))
                grids[role] = drums.euclid(int(e[0]), int(e[1]), int(e[2]))
            elif spec in (None, "", False):
                grids.pop(role, None)
            else:
                grids[role] = str(spec)
        if not grids:
            return "Give a style or layers"
        if swing_pct is not None:
            swing = swing_pct
        ableton = get_ableton_connection()
        roles, kit = _kit_roles(ableton, track_index)
        result = drums.render(grids, roles, bars=bars, steps_per_bar=steps_per_bar, swing_pct=swing,
                              fill=fill, fill_every=fill_every, humanize=humanize, variation=variation,
                              seed=seed, use_gm=kit is None)
        notes = result["notes"]
        if any("probability" in n for n in notes) and require_capability("note_probability") is not None:
            for n in notes:  # an older script would drop the field anyway
                n.pop("probability", None)
        info = ableton.send_command("get_track_info", {"track_index": track_index})
        slots = info.get("clip_slots", [])
        if clip_index < 0 or clip_index >= len(slots):
            return f"Clip slot {clip_index} out of range ({len(slots)} slots)"
        length = result["length_beats"]
        if slots[clip_index].get("has_clip"):
            if not replace:
                return "Slot %d already has a clip; pass replace=true or pick an empty slot" % clip_index
            ableton.send_command("clear_notes_from_clip", _note_params(track_index, clip_index, "session"))
            ableton.send_command("set_clip_loop", {"track_index": track_index, "clip_index": clip_index,
                                                   "loop_start": 0.0, "loop_end": length})
        else:
            ableton.send_command("create_clip", {"track_index": track_index, "clip_index": clip_index,
                                                 "length": length})
        for i in range(0, len(notes), ADD_NOTES_CHUNK):
            params = _note_params(track_index, clip_index, "session")
            params["notes"] = notes[i:i + ADD_NOTES_CHUNK]
            ableton.send_command("add_notes_to_clip", params)
        return _json({
            "kit": kit.get("rack_name") if kit else "no Drum Rack: General MIDI notes",
            "style": style, "bars": bars, "swing_pct": swing,
            "mapping": result["mapping"], "missing_roles": result["missing_roles"],
            "grids": grids, "notes_written": len(notes),
            "with_probability": sum(1 for n in notes if "probability" in n),
        })
    except Exception as e:
        logger.error(f"Error writing drum pattern: {str(e)}")
        return f"Error writing drum pattern: {str(e)}"


@mcp.tool()
def get_groove_pool(ctx: Context) -> str:
    """
    Live's Groove Pool: the grooves loaded in the set (name, base, timing,
    random, velocity and quantization amounts) and the global Groove amount.
    Grooves live in the browser under Packs (e.g.
    get_browser_items_at_path("packs/Core Library/Grooves")) and in the User
    Library; apply one with set_clip_groove. A groove only acts when the
    global amount is above 0 (set_groove_params global_amount).
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("get_groove_pool")
        if missing:
            return missing
        return _json(get_ableton_connection().send_command("get_groove_pool"))
    except Exception as e:
        return f"Error reading the Groove Pool: {str(e)}"


@mcp.tool()
def set_clip_groove(ctx: Context, track_index: int, clip_index: int, groove_index: int = None,
                    location: str = "session") -> str:
    """
    Apply a Groove Pool groove to a clip (Live's own swing/groove engine,
    non-destructive), or remove it with groove_index omitted.

    Parameters:
    - track_index / clip_index: The clip
    - groove_index: Index from get_groove_pool (omit to remove the groove)
    - location: "session" (default) or "arrangement"
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("set_clip_groove")
        if missing:
            return missing
        return _json(get_ableton_connection().send_command("set_clip_groove", {
            "track_index": track_index, "clip_index": clip_index, "groove_index": groove_index,
            "location": (location or "session").lower()}))
    except Exception as e:
        return f"Error setting the clip groove: {str(e)}"


@mcp.tool()
def set_groove_params(ctx: Context, groove_index: int = None, timing_amount: float = None,
                      random_amount: float = None, velocity_amount: float = None,
                      quantization_amount: float = None, global_amount: float = None) -> str:
    """
    Adjust a groove in the Groove Pool (amounts in %, as in Live) and/or the
    global Groove amount (0-1.3, i.e. 0-130 %).

    Parameters:
    - groove_index: Groove to change (from get_groove_pool)
    - timing_amount / random_amount / velocity_amount / quantization_amount: New amounts
    - global_amount: Global Groove amount
    """
    try:
        from .script_handshake import require_capability

        missing = require_capability("set_groove_params")
        if missing:
            return missing
        values = {k: v for k, v in (("timing_amount", timing_amount), ("random_amount", random_amount),
                                    ("velocity_amount", velocity_amount),
                                    ("quantization_amount", quantization_amount)) if v is not None}
        return _json(get_ableton_connection().send_command("set_groove_params", {
            "groove_index": groove_index, "values": values, "global_amount": global_amount}))
    except Exception as e:
        return f"Error setting groove parameters: {str(e)}"


# ───────────────────── Evolution and arrangement ─────────────────────

@mcp.tool()
def arrangement_templates(ctx: Context, template: str = None) -> str:
    """
    Arrangement templates for electronic music and the automation curve
    shapes. Without `template`: the list (techno_dj, techno_64, minimal,
    house) and the shapes. With it: its sections (name, bars, energy 0-1,
    roles that play, production tip).

    Parameters:
    - template: Template name (optional)
    """
    try:
        from . import arrangement as ar

        if template:
            return _json({"template": template, "label": ar.TEMPLATES[template]["label"]
                          if template in ar.TEMPLATES else None,
                          "sections": ar.template_sections(template)})
        return _json({"templates": {k: v["label"] for k, v in ar.TEMPLATES.items()},
                      "shapes": ar.SHAPES, "track_roles": [r for r, _ in ar.ROLE_WORDS]})
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def write_clip_evolution(
    ctx: Context,
    track_index: int,
    clip_index: int,
    lanes: List[Dict[str, Any]],
    bars: int = None,
    resolution: float = 1.0,
) -> str:
    """
    Make a Session clip evolve over many bars: optionally extend it to `bars`
    (a MIDI loop is tiled, e.g. 4 -> 64 bars), then write one automation
    envelope per lane with a musical curve. Copied to the Arrangement (e.g.
    by build_arrangement), the envelopes become the track's automation there.

    Each lane: {"mixer_parameter": "volume" | "panning" | "send:N"} or
    {"device_index": d, "parameter_index": p}, plus "start", "end" (in the
    parameter's units, see get_device_parameters: min/max/display), "shape"
    (linear, exp, log, s_curve, swell, sine, triangle, steps, random_walk,
    hold), optional "cycles" (sine/triangle), "steps" (steps), "power"
    (exp/log curvature, default 2.5), "from_bar"/"to_bar" to limit the curve
    to part of the clip (the value holds outside), "seed".

    Example, a 64-bar techno build: filter cutoff exp from 0.3 to 0.9, reverb
    send swell, hats volume in 8 steps.

    Parameters:
    - track_index / clip_index: Session clip
    - lanes: Curves to write (see above)
    - bars: Extend the clip to this many bars first (MIDI clips; 4/4)
    - resolution: Envelope step in beats (1 = a point per beat)
    """
    try:
        from . import arrangement as ar
        from .script_handshake import require_capability

        missing = require_capability("set_clip_automation")
        if missing:
            return missing
        ableton = get_ableton_connection()
        data = ableton.send_command("get_clip_notes", {"track_index": track_index, "clip_index": clip_index})
        length = float(data.get("length") or 0.0)
        report = {"clip_length_before": length}
        if bars:
            target = bars * 4.0
            if target > length + 1e-6:
                notes = data.get("notes", [])
                tiled = ar.tile_notes(notes, length, target)
                ableton.send_command("clear_notes_from_clip", _note_params(track_index, clip_index, "session"))
                ableton.send_command("set_clip_loop", {"track_index": track_index, "clip_index": clip_index,
                                                       "loop_start": 0.0, "loop_end": target,
                                                       "end_marker": target})
                for i in range(0, len(tiled), ADD_NOTES_CHUNK):
                    params = _note_params(track_index, clip_index, "session")
                    params["notes"] = tiled[i:i + ADD_NOTES_CHUNK]
                    ableton.send_command("add_notes_to_clip", params)
                length = target
                report["extended_to_beats"] = target
                report["notes_after_tiling"] = len(tiled)
        report["lanes"] = []
        for lane in lanes:
            a = float(lane.get("from_bar", 0)) * 4.0
            z = float(lane["to_bar"]) * 4.0 if lane.get("to_bar") is not None else length
            z = min(z, length)
            pts = ar.curve_points(z - a, float(lane["start"]), float(lane["end"]),
                                  shape=lane.get("shape", "linear"), resolution=resolution,
                                  cycles=float(lane.get("cycles", 1.0)), steps=int(lane.get("steps", 4)),
                                  power=float(lane.get("power", 2.5)), offset=a, seed=int(lane.get("seed", 0)))
            if a > 0:
                pts.insert(0, {"time": 0.0, "value": pts[0]["value"]})
            res = ableton.send_command("set_clip_automation", {
                "track_index": track_index, "clip_index": clip_index, "location": "session",
                "device_index": int(lane.get("device_index", -1)),
                "parameter_index": int(lane.get("parameter_index", 0)),
                "mixer_parameter": lane.get("mixer_parameter", ""), "points": pts,
                "interpolation": "step" if lane.get("shape") in ("steps", "hold") else "linear",
                "resolution": resolution, "clear_first": True})
            report["lanes"].append({"parameter": res.get("parameter"), "shape": lane.get("shape", "linear"),
                                    "from_beat": a, "to_beat": z, "points": len(pts),
                                    "start": lane["start"], "end": lane["end"]})
        report["clip_length_beats"] = length
        return _json(report)
    except Exception as e:
        logger.error(f"Error writing clip evolution: {str(e)}")
        return f"Error writing clip evolution: {str(e)}"


def _session_tracks(ableton) -> List[Dict[str, Any]]:
    count = int(ableton.send_command("get_session_info").get("track_count", 0))
    tracks = []
    for i in range(count):
        info = ableton.send_command("get_track_info", {"track_index": i})
        slots = {s["index"]: float(s["clip"]["length"]) for s in info.get("clip_slots", [])
                 if s.get("has_clip") and s.get("clip")}
        tracks.append({"index": i, "name": info.get("name", ""), "slots": slots})
    return tracks


@mcp.tool()
def build_arrangement(
    ctx: Context,
    template: str = None,
    sections: List[Dict[str, Any]] = None,
    track_roles: Dict[str, str] = None,
    start_bar: int = 0,
    default_slot: int = 0,
    section_slots: Dict[str, Dict[str, int]] = None,
    locators: bool = True,
    dry_run: bool = False,
) -> str:
    """
    Build the Arrangement from Session clips, section by section, like a
    producer laying out a track: each section plays the clips of the tracks
    whose role is active there, tiled to fill it, with a named locator at its
    start. Clip envelopes (see write_clip_evolution) come along as track
    automation, so a filter build or a reverb swell plays in the Arrangement.

    Use a `template` (techno_dj, techno_64, minimal, house; see
    arrangement_templates) or your own `sections`: [{"name", "bars",
    "roles": [...]} or {"name", "bars", "play": {"track_index": slot}}].
    Track roles come from track names (kick, drums, hats, perc, rumble, bass,
    chords, pad, lead, vocal, fx) unless `track_roles` {"track_index": role}
    overrides them. `section_slots` {"Section name": {"track_index": slot}}
    picks another clip for a section (e.g. the automated build variant).
    Run with dry_run=true first to see the plan.

    Parameters:
    - template / sections: Structure to build
    - track_roles: Role per track index, overriding names
    - start_bar: Arrangement bar to start at (0 = beginning)
    - default_slot: Session slot used by default for every track
    - section_slots: Per-section slot overrides
    - locators: Add a locator at each section (transport must be stopped)
    - dry_run: Only return the plan
    """
    try:
        from . import arrangement as ar

        if sections is None:
            if not template:
                return "Give a template or sections"
            sections = ar.template_sections(template)
        if section_slots:
            for sec in sections:
                over = section_slots.get(sec["name"])
                if over:
                    sec["slots"] = {int(k): int(v) for k, v in over.items()}
        ableton = get_ableton_connection()
        tracks = _session_tracks(ableton)
        roles = ar.infer_track_roles(tracks)
        for k, v in (track_roles or {}).items():
            roles[int(k)] = v
        info = ableton.send_command("get_session_info")
        bpb = float(info.get("signature_numerator", 4)) * 4.0 / float(info.get("signature_denominator", 4))
        plan = ar.plan_arrangement(sections, tracks, roles, beats_per_bar=bpb, start_bar=start_bar,
                                   default_slot=default_slot)
        summary = {"track_roles": {tracks[i]["name"]: r for i, r in roles.items() if i < len(tracks)},
                   "sections": plan["sections"], "total_bars": plan["total_bars"],
                   "placements": len(plan["placements"]), "warnings": plan["warnings"]}
        unassigned = [t["name"] for t in tracks if t["index"] not in roles and t["slots"]]
        if unassigned:
            summary["tracks_without_role"] = unassigned
        if dry_run:
            summary["dry_run"] = True
            return _json(summary)
        if ableton.send_command("get_session_info").get("is_playing"):
            ableton.send_command("stop_playback")
        for p in plan["placements"]:
            ableton.send_command("duplicate_session_clip_to_arrangement", {
                "track_index": p["track_index"], "clip_index": p["clip_index"],
                "destination_time": p["start"]})
        made = 0
        if locators:
            from .script_handshake import require_capability

            if require_capability("create_locator") is None:
                for loc in plan["locators"]:
                    try:
                        ableton.send_command("create_locator", {"name": loc["name"], "time": loc["beat"]})
                        made += 1
                    except Exception as e:
                        summary.setdefault("warnings", []).append("locator %s: %s" % (loc["name"], e))
        summary["locators_created"] = made
        return _json(summary)
    except Exception as e:
        logger.error(f"Error building arrangement: {str(e)}")
        return f"Error building arrangement: {str(e)}"


@mcp.tool()
def arrangement_overview(ctx: Context, block_bars: int = 8) -> str:
    """
    A map of the Arrangement: for every track, one character per block of
    `block_bars` bars ('#' = a clip plays, '.' = silent), so the structure,
    the entries and exits of each element and the phrasing are visible at a
    glance.

    Parameters:
    - block_bars: Bars per character (default 8)
    """
    try:
        from . import arrangement as ar

        ableton = get_ableton_connection()
        info = ableton.send_command("get_session_info")
        bpb = float(info.get("signature_numerator", 4)) * 4.0 / float(info.get("signature_denominator", 4))
        clips_by_track, end = {}, 0.0
        for i in range(int(info.get("track_count", 0))):
            data = ableton.send_command("get_arrangement_clips", {"track_index": i})
            clips = data.get("clips", [])
            clips_by_track["%d %s" % (i, data.get("track_name", ""))] = clips
            for c in clips:
                end = max(end, float(c["end_time"]))
        rows = ar.activity_map(clips_by_track, block_bars * bpb, end)
        blocks = len(next(iter(rows.values()), ""))
        return _json({"block_bars": block_bars, "length_bars": round(end / bpb, 2),
                      "block_start_bars": [1 + b * block_bars for b in range(blocks)],
                      "tracks": rows})
    except Exception as e:
        logger.error(f"Error reading the arrangement: {str(e)}")
        return f"Error reading the arrangement: {str(e)}"


# ───────────────────────────── Devices ──────────────────────────────

@mcp.tool()
def device_inventory(ctx: Context, installed_plugins: bool = False) -> str:
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
        from . import device_knowledge as dk

        ableton = get_ableton_connection()
        info = ableton.send_command("get_session_info")
        targets = [(i, "track") for i in range(int(info.get("track_count", 0)))]
        targets += [(i, "return") for i in range(int(info.get("return_track_count", 0)))]
        targets.append((0, "master"))
        tracks = []
        for index, tt in targets:
            params: Dict[str, Any] = {"track_index": index}
            if tt != "track":
                params["track_type"] = tt
            t = ableton.send_command("get_track_info", params)
            devices = []
            for d in t.get("devices", []):
                card = dk.describe_device(d)
                card["index"] = d.get("index")
                if d.get("class_name") in ("InstrumentGroupDevice", "AudioEffectGroupDevice",
                                           "MidiEffectGroupDevice", "DrumGroupDevice"):
                    try:
                        dp = dict(params, device_index=d["index"])
                        full = ableton.send_command("get_device_parameters", dp).get("device", {})
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
                    root = ableton.send_command("get_browser_items_at_path", {"path": "plugins/" + fmt})
                except Exception:
                    continue
                for item in root.get("items", []):
                    if item.get("is_folder"):
                        sub = ableton.send_command("get_browser_items_at_path",
                                                   {"path": "plugins/%s/%s" % (fmt, item["name"])})
                        vendor = item["name"]
                        for x in sub.get("items", []):
                            by_vendor.setdefault(vendor, [])
                            if x["name"] not in by_vendor[vendor]:
                                by_vendor[vendor].append(x["name"])
            result["installed_plugins"] = {v: sorted(n) for v, n in sorted(by_vendor.items())}
        return _json(result)
    except Exception as e:
        logger.error(f"Error building the device inventory: {str(e)}")
        return f"Error building the device inventory: {str(e)}"


@mcp.tool()
def device_knowledge(ctx: Context, name: str = None, kind: str = None) -> str:
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
    from . import device_knowledge as dk

    if name:
        entry = dk.lookup(name)
        return _json(entry) if entry else "No sheet for '%s' (maybe a third-party plug-in: check its parameters)" % name
    return _json({"devices": dk.catalog(kind), "midi_tools": dk.MIDI_TOOLS_NOTE})


def _device_cmd(command: str, params: Dict[str, Any], track_type: str = "track") -> str:
    from .script_handshake import require_capability

    missing = require_capability(command)
    if missing:
        return missing
    missing = _apply_track_type(params, track_type)
    if missing:
        return missing
    try:
        return _json(get_ableton_connection().send_command(command, params))
    except Exception as e:
        return f"Error ({command}): {str(e)}"


@mcp.tool()
def get_device_info(ctx: Context, track_index: int, device_index: int, track_type: str = "track") -> str:
    """
    One device's identity (Live's real device name even when a preset renamed
    it, kind, latency) and its specific API: sidechain routing and options
    (Compressor), plug-in presets, Simpler sample/slicing state, rack chains
    and variations.

    Parameters:
    - track_index / device_index: The device
    - track_type: "track", "return" or "master"
    """
    return _device_cmd("get_device_info", {"track_index": track_index, "device_index": device_index},
                       track_type)


@mcp.tool()
def set_device_sidechain(ctx: Context, track_index: int, device_index: int, source: str,
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
    return _device_cmd("set_device_sidechain", params, track_type)


@mcp.tool()
def plugin_presets(ctx: Context, track_index: int, device_index: int, preset_index: int = None,
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
        out = _device_cmd("get_device_info", {"track_index": track_index, "device_index": device_index},
                          track_type)
        try:
            data = json.loads(out)
            return _json(data.get("plugin") or {"error": "not a plug-in"})
        except ValueError:
            return out
    params = {"track_index": track_index, "device_index": device_index}
    if preset_index is not None:
        params["preset_index"] = preset_index
    if preset_name is not None:
        params["preset_name"] = preset_name
    return _device_cmd("select_plugin_preset", params, track_type)


@mcp.tool()
def simpler_sample(ctx: Context, track_index: int, device_index: int, file_path: str = None,
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
        res = _device_cmd("simpler_replace_sample", {"track_index": track_index, "device_index": device_index,
                                                     "file_path": os.path.expanduser(file_path)})
        if res.startswith("Error") or res.startswith("Ableton Remote Script missing"):
            return res
        out["loaded"] = json.loads(res).get("loaded")
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
        res = _device_cmd("simpler_configure", {"track_index": track_index, "device_index": device_index,
                                                "settings": settings})
        try:
            out.update(json.loads(res))
        except ValueError:
            return res
    return _json(out) if out else "Nothing to do: give file_path and/or settings"


@mcp.tool()
def rack_variation(ctx: Context, track_index: int, device_index: int, action: str = "list",
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
    return _device_cmd("rack_variation", {"track_index": track_index, "device_index": device_index,
                                          "action": action, "index": index}, track_type)


@mcp.tool()
def set_drum_choke(ctx: Context, track_index: int, notes: List[int], group: int = 1) -> str:
    """
    Put Drum Rack pads in a choke group so they cut each other — the classic:
    closed and open hi-hat together (e.g. notes [42, 46], group 1). Group 0
    removes the choke.

    Parameters:
    - track_index: Track with the Drum Rack
    - notes: Pad MIDI notes (see get_drum_map)
    - group: Choke group 1-16, or 0 for none
    """
    return _device_cmd("set_drum_choke", {"track_index": track_index, "notes": notes, "group": group})


# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()