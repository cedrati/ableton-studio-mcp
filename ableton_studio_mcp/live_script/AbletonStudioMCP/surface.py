"""The control surface Live instantiates, and how a request is executed.

Everything happens on Live's main thread, the only one allowed to touch the
Live object model: Live calls :meth:`update_display` about ten times a
second, and each call lets the socket server accept, read, run requests and
write replies (see transport.py). No threads, no locks, no waiting.

A handler may return a :class:`Deferred` when Live applies a change on a
later tick; its reply goes out when the deferred settles.
"""
from __future__ import absolute_import, print_function, unicode_literals

import time
import traceback

from _Framework.ControlSurface import ControlSurface

from . import registry
from .automation import AutomationCommands
from .browser import BrowserCommands
from .clips import ClipCommands
from .constants import HOST, PORT, PROTOCOL_VERSION
from .deferred import Deferred, Waiting
from .devices import DeviceCommands
from .groove import GrooveCommands
from .notes import NoteCommands
from .recording import RecordingCommands
from .registry import command
from .session import SessionCommands
from .snapshot import SnapshotCommands
from .tracks import TrackCommands
from .undo import UndoCommands
from .transport import SocketServer
from .warp import WarpCommands

NAME = "AbletonStudioMCP"
# Commands slower than this are written to Live's log (Log.txt), to spot regressions.
SLOW_COMMAND_LOG_SECONDS = 1.0


class AbletonStudioMCP(Waiting, UndoCommands, SessionCommands, TrackCommands, ClipCommands, NoteCommands,
                       WarpCommands, AutomationCommands, DeviceCommands, GrooveCommands,
                       BrowserCommands, RecordingCommands, SnapshotCommands, ControlSurface):

    def __init__(self, c_instance):
        ControlSurface.__init__(self, c_instance)
        from . import SCRIPT_VERSION
        self._song = self.song()
        self._server = SocketServer(HOST, PORT, self._execute, self.log_message, is_read=self._is_read)
        try:
            self._server.start()
        except (OSError, IOError) as e:
            self._server = None
            self.log_message("cannot listen on %s:%d: %s" % (HOST, PORT, e))
            self.show_message("%s: port %d unavailable (%s)" % (NAME, PORT, e))
            return
        self.log_message("%s %s listening on %s:%d" % (NAME, SCRIPT_VERSION, HOST, PORT))
        self.show_message("%s: ready on port %d" % (NAME, PORT))

    def update_display(self):
        """Called by Live on its main thread about ten times a second."""
        ControlSurface.update_display(self)
        server = getattr(self, "_server", None)
        if server is not None:
            try:
                server.poll()
                self._close_stale_undo_group()
            except Exception as e:   # never let a network problem break Live's display loop
                self.log_message("socket poll failed: %s\n%s" % (e, traceback.format_exc()))

    def disconnect(self):
        server = getattr(self, "_server", None)
        if server is not None:
            server.stop()
            self._server = None
        ControlSurface.disconnect(self)

    @command("get_script_info")
    def _get_script_info(self):
        """Who we are, for the server's version check."""
        from . import SCRIPT_VERSION
        return {"name": NAME, "script_version": SCRIPT_VERSION,
                "protocol_version": PROTOCOL_VERSION, "port": PORT,
                "capabilities": registry.capabilities()}

    # ── requests ────────────────────────────────────────────────────────────

    @staticmethod
    def _is_read(request):
        """Reads leave the set untouched and can be chained in one pass."""
        return registry.is_read(request.get("type", ""))

    def _execute(self, request, respond):
        """Run one request and pass its reply to ``respond`` (now, or later
        for a Deferred)."""
        name = request.get("type", "")
        entry = registry.COMMANDS.get(name)
        if entry is None:
            return respond({"status": "error", "message": "Unknown command: %s" % name})
        handler = getattr(self, entry[0])
        try:
            kwargs = registry.bind_arguments(handler, name, request.get("params"))
        except registry.CommandError as e:
            return respond({"status": "error", "message": str(e)})
        # Live merges every change a script makes into one undo step until
        # something closes it, so Undo would wipe out a whole session's work.
        # Each change therefore gets a step of its own (or joins the open
        # group, see session.py).
        own_step = self._opens_undo_step(name)
        if own_step:
            self._open_entry(name)
        closed = []

        def close_step():
            if own_step and not closed:
                closed.append(True)
                self._close_entry()

        def finish(reply):
            close_step()
            respond(reply)

        started = time.time()
        try:
            result = handler(**kwargs)
        except Exception as e:
            self.log_message("%s failed: %s\n%s" % (name, e, traceback.format_exc()))
            return finish({"status": "error", "message": str(e)})
        elapsed = time.time() - started
        if elapsed > SLOW_COMMAND_LOG_SECONDS:
            self.log_message("%s took %.0f ms" % (name, elapsed * 1000))
        if isinstance(result, Deferred):
            result.start(lambda value: finish({"status": "success", "result": value}),
                         lambda message: finish({"status": "error", "message": message}))
        else:
            finish({"status": "success", "result": result})

    UNDO_CONTROL = frozenset(("undo", "redo", "begin_undo_group", "end_undo_group"))

    def _opens_undo_step(self, name):
        """Whether ``name`` runs in an undo step of its own."""
        return (not registry.is_read(name) and name not in self.UNDO_CONTROL
                and not getattr(self, "_undo_group", None)
                and hasattr(getattr(self, "_song", None), "begin_undo_step"))

    def _process_command(self, request):
        """Run a request and return its reply, when it settles right away
        (as it does in tests, where deferreds resolve synchronously)."""
        replies = []
        self._execute(request, replies.append)
        if replies:
            return replies[0]
        return {"status": "error", "message": "'%s' has not finished yet" % request.get("type")}
