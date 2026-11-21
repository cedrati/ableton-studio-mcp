"""Settings and lookup tables shared by the control surface modules.

This code runs inside Ableton Live's embedded Python (3.7 in Live 11, 3.11
in Live 12): keep it free of newer syntax.
"""
from __future__ import absolute_import, print_function, unicode_literals

import os

# ── socket ───────────────────────────────────────────────────────────────────

PORT = 9877
# Anything that reaches this port can drive Live (load files, change the
# set), and it has no authentication, so it listens on the loopback interface
# only. ABLETON_MCP_HOST widens that on purpose, for a server on another
# machine behind a trusted network.
HOST = os.environ.get("ABLETON_MCP_HOST", "127.0.0.1")
# Requests are newline-delimited JSON. A peer that never ends its request
# must not make the buffer grow forever; this leaves room for large note lists.
MAX_REQUEST_BYTES = 16 * 1024 * 1024
# 2: newline-delimited JSON (1 was "read until the bytes parse").
PROTOCOL_VERSION = 2

# How long the socket thread waits for Live's main thread to run a command.
MAIN_THREAD_TIMEOUT = 10.0
SLOW_COMMAND_TIMEOUTS = {"create_audio_clip": 60.0}

# ── music ────────────────────────────────────────────────────────────────────

NOTE_NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Track.current_monitoring_state
MONITORING_STATES = {0: "in", 1: "auto", 2: "off"}
MONITORING_BY_NAME = dict((name, state) for state, name in MONITORING_STATES.items())

# Clip.warp_mode
WARP_MODE_NAMES = {0: "beats", 1: "tones", 2: "texture", 3: "re_pitch",
                   4: "complex", 5: "rex", 6: "complex_pro"}
WARP_MODES_BY_NAME = dict((name, mode) for mode, name in WARP_MODE_NAMES.items())
WARP_MODES_BY_NAME["repitch"] = 3

# ── limits and tolerances ────────────────────────────────────────────────────

# Envelope steps written or read in one command, at most.
MAX_AUTOMATION_STEPS = 4096
# Live keeps an invisible warp marker this many beats after the last one.
SHADOW_MARKER_GAP = 1.0 / 32
# original_bpm: a file this close to a whole number of beats is pinned to it.
CONFORM_SNAP_BEATS = 0.02
# Envelopes are read this far after each sample time (see automation.py).
ENVELOPE_PROBE_OFFSET = 1e-4
# Two song positions closer than this are the same position.
TIME_TOLERANCE = 1e-3

# ── waiting for Live ─────────────────────────────────────────────────────────
# Some writes (playhead moves, cue toggles, browser loads) only show up on a
# later tick (~100 ms each). Commands doing them poll for at most this many
# ticks, all well inside MAIN_THREAD_TIMEOUT.

PLAYHEAD_SETTLE_TICKS = 10
CUE_SETTLE_TICKS = 10
DEVICE_LOAD_SETTLE_TICKS = 50
SAME_KIND_RELOAD_SETTLE_TICKS = 20
RECORDING_POLL_TICKS = 1
