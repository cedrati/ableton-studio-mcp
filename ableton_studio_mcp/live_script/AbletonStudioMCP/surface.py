"""The control surface Live instantiates, and how a request is executed.

Live's object model may only be touched from Live's main thread. Requests
arrive on socket threads, so each one is handed to the main thread with
``schedule_message`` and the socket thread waits for its result. A handler
may return a :class:`Deferred` when Live applies a change on a later tick;
the reply is sent once the deferred settles.
"""
from __future__ import absolute_import, print_function, unicode_literals

import queue
import traceback

from _Framework.ControlSurface import ControlSurface

from . import registry
from .automation import AutomationCommands
from .browser import BrowserCommands
from .clips import ClipCommands
from .constants import HOST, MAIN_THREAD_TIMEOUT, PORT, PROTOCOL_VERSION, SLOW_COMMAND_TIMEOUTS
from .deferred import Deferred, Waiting
from .devices import DeviceCommands
from .groove import GrooveCommands
from .notes import NoteCommands
from .recording import RecordingCommands
from .registry import command
from .session import SessionCommands
from .snapshot import SnapshotCommands
from .tracks import TrackCommands
from .transport import SocketServer
from .warp import WarpCommands

NAME = "AbletonStudioMCP"


class AbletonStudioMCP(Waiting, SessionCommands, TrackCommands, ClipCommands, NoteCommands,
                       WarpCommands, AutomationCommands, DeviceCommands, GrooveCommands,
                       BrowserCommands, RecordingCommands, SnapshotCommands, ControlSurface):

    def __init__(self, c_instance):
        ControlSurface.__init__(self, c_instance)
        from . import SCRIPT_VERSION
        self._song = self.song()
        self._server = SocketServer(HOST, PORT, self._process_command, self.log_message)
        try:
            self._server.start()
        except (OSError, IOError) as e:
            self.log_message("cannot listen on %s:%d: %s" % (HOST, PORT, e))
            self.show_message("%s: port %d unavailable (%s)" % (NAME, PORT, e))
            return
        self.log_message("%s %s listening on %s:%d" % (NAME, SCRIPT_VERSION, HOST, PORT))
        self.show_message("%s: ready on port %d" % (NAME, PORT))

    def disconnect(self):
        server = getattr(self, "_server", None)
        if server is not None:
            server.stop()
        ControlSurface.disconnect(self)

    @command("get_script_info")
    def _get_script_info(self):
        """Who we are, for the server's version check."""
        from . import SCRIPT_VERSION
        return {"name": NAME, "script_version": SCRIPT_VERSION,
                "protocol_version": PROTOCOL_VERSION, "port": PORT,
                "capabilities": registry.capabilities()}

    # ── requests ────────────────────────────────────────────────────────────

    def _process_command(self, request):
        """Execute one request and return the reply object."""
        name = request.get("type", "")
        entry = registry.COMMANDS.get(name)
        if entry is None:
            return {"status": "error", "message": "Unknown command: %s" % name}
        handler = getattr(self, entry[0])
        try:
            kwargs = registry.bind_arguments(handler, name, request.get("params"))
        except registry.CommandError as e:
            return {"status": "error", "message": str(e)}
        return self._run_on_main_thread(name, lambda: handler(**kwargs))

    def _run_on_main_thread(self, name, work):
        replies = queue.Queue()

        def task():
            try:
                result = work()
            except Exception as e:
                self.log_message("%s failed: %s\n%s" % (name, e, traceback.format_exc()))
                replies.put({"status": "error", "message": str(e)})
                return
            if isinstance(result, Deferred):
                result.start(lambda value: replies.put({"status": "success", "result": value}),
                             lambda message: replies.put({"status": "error", "message": message}))
            else:
                replies.put({"status": "success", "result": result})

        try:
            self.schedule_message(0, task)
        except AssertionError:   # already on the main thread
            task()
        try:
            return replies.get(timeout=SLOW_COMMAND_TIMEOUTS.get(name, MAIN_THREAD_TIMEOUT))
        except queue.Empty:
            return {"status": "error", "message": "Live did not finish '%s' in time" % name}
