"""The TCP side of the control surface, without threads.

Live's embedded Python only lets other threads run while Live itself calls
into Python, about ten times a second. A socket thread handing work to the
main thread therefore paid for several of those calls per request. Instead,
:meth:`SocketServer.poll` is called from the control surface's
``update_display`` (Live's main thread): it accepts connections, reads what
has arrived, runs the complete requests and writes the replies, all with
non-blocking sockets. A request waits at most one display update.

Framing: one JSON object per line, both ways. A request without a trailing
newline is also accepted once its bytes form a complete JSON object (servers
from before protocol 2 send none).
"""
from __future__ import absolute_import, print_function, unicode_literals

import collections
import errno
import json
import select
import socket
import time

from .constants import MAX_REQUEST_BYTES

RECV_CHUNK = 65536
# A client usually sends its next request right after a reply. Waiting this
# long for it, within one poll, saves a whole display update (~100 ms) per
# request in a sequence; POLL_BUDGET caps the time a poll keeps Live busy.
#
# Only reads are chained like that. After a change to the set, Live needs a
# display update of its own before the next command: changing the routing of a
# track created in the same pass crashed Live 12.4. So a request that is not a
# read ends the pass, and whatever follows waits for the next update.
LINGER_SECONDS = 0.004
POLL_BUDGET_SECONDS = 0.05
# Write at most this much per client per poll, so one huge reply can't stall Live.
SEND_BUDGET = 4 * 1024 * 1024
_WOULD_BLOCK = (errno.EAGAIN, errno.EWOULDBLOCK, getattr(errno, "WSAEWOULDBLOCK", errno.EAGAIN))


class RequestReader(object):
    """Cuts a byte stream into JSON requests."""

    def __init__(self, limit=MAX_REQUEST_BYTES):
        self.limit = limit
        self.pending = b""

    def feed(self, data):
        """Add received bytes; return the complete requests (dicts) found."""
        self.pending += data
        requests = []
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            if line.strip():
                requests.append(self._decode(line))
        if self.pending.strip().endswith(b"}"):
            try:   # protocol 1 peers send no newline
                requests.append(self._decode(self.pending))
                self.pending = b""
            except ValueError:
                pass   # not complete yet
        if len(self.pending) > self.limit:
            self.pending = b""
            raise ValueError("request larger than %d bytes" % self.limit)
        return requests

    @staticmethod
    def _decode(raw):
        request = json.loads(raw.decode("utf-8"))
        if not isinstance(request, dict):
            raise ValueError("a request must be a JSON object")
        return request


def encode(reply):
    return (json.dumps(reply) + "\n").encode("utf-8")


class Client(object):
    def __init__(self, sock, address):
        self.sock, self.address = sock, address
        self.reader = RequestReader()
        self.backlog = collections.deque()   # requests received, not run yet
        self.outgoing = b""
        self.closing = False     # hang up once the outgoing bytes are written

    def send(self, reply):
        self.outgoing += encode(reply)


class SocketServer(object):
    """Accepts clients and exchanges requests/replies when polled.

    ``handle(request, respond)`` runs each request; it calls ``respond(reply)``
    once, now or on a later poll (for changes Live applies on a later tick).
    """

    def __init__(self, host, port, handle, log, is_read=lambda request: False):
        self.host, self.port = host, port
        self.handle = handle
        self.is_read = is_read
        self.log = log
        self.listener = None
        self.clients = []

    def start(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen(5)
        listener.setblocking(False)
        self.listener = listener

    def stop(self):
        for client in self.clients:
            self._close(client)
        self.clients = []
        if self.listener is not None:
            try:
                self.listener.close()
            except (OSError, socket.error):
                pass
            self.listener = None

    def poll(self):
        """Accept, read and run requests, write replies; keep going while
        requests keep arriving, up to POLL_BUDGET_SECONDS."""
        if self.listener is None:
            return
        deadline = time.time() + POLL_BUDGET_SECONDS
        while True:
            if not self._round():
                return     # the set changed: let Live catch up first
            waiting = [c.sock for c in self.clients if not c.closing]
            if not waiting or time.time() >= deadline:
                return
            try:
                ready = select.select(waiting, [], [], LINGER_SECONDS)[0]
            except (OSError, ValueError, select.error):
                return
            if not ready:
                return

    def _round(self):
        """Accept, read, run what may run, write. False once a request that
        changes the set has run (the pass must end)."""
        self._accept()
        may_continue = True
        for client in list(self.clients):
            if not client.closing:
                self._read(client)
            if may_continue:
                may_continue = self._run(client)
            self._write(client)
        self.clients = [c for c in self.clients if c.sock is not None]
        return may_continue

    def _run(self, client):
        while client.backlog:
            request = client.backlog.popleft()
            self.handle(request, client.send)
            if not self.is_read(request):
                return False
        return True

    # ── steps ───────────────────────────────────────────────────────────────

    def _accept(self):
        while True:
            try:
                sock, address = self.listener.accept()
            except (OSError, socket.error):
                return   # nobody waiting (or the listener closed)
            sock.setblocking(False)
            self.clients.append(Client(sock, address))
            self.log("client connected from %s:%s" % tuple(address[:2]))

    def _read(self, client):
        while True:
            try:
                data = client.sock.recv(RECV_CHUNK)
            except (OSError, socket.error) as e:
                if getattr(e, "errno", None) in _WOULD_BLOCK:
                    return
                self.log("client connection error: %s" % e)
                return self._close(client)
            if not data:
                return self._close(client)
            try:
                requests = client.reader.feed(data)
            except ValueError as e:
                # The stream can't be trusted any more: say why, then hang up.
                client.send({"status": "error", "message": "bad request: %s" % e})
                client.closing = True
                return
            client.backlog.extend(requests)

    def _write(self, client):
        budget = SEND_BUDGET
        while client.sock is not None and client.outgoing and budget > 0:
            try:
                sent = client.sock.send(client.outgoing[:min(budget, RECV_CHUNK * 4)])
            except (OSError, socket.error) as e:
                if getattr(e, "errno", None) in _WOULD_BLOCK:
                    return
                self.log("client connection error: %s" % e)
                return self._close(client)
            client.outgoing = client.outgoing[sent:]
            budget -= sent
        if client.closing and not client.outgoing:
            self._close(client)

    def _close(self, client):
        if client.sock is not None:
            try:
                client.sock.close()
            except (OSError, socket.error):
                pass
            client.sock = None
            self.log("client disconnected")
