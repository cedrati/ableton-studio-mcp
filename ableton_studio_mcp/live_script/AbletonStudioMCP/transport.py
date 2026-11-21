"""The TCP side of the control surface.

One background thread accepts connections; each client gets its own thread
that reads newline-delimited JSON requests and writes one JSON line back per
request. What a request means is not this module's business: it hands every
decoded request to ``handle(request) -> reply``.

For servers from before protocol 2, a request without a trailing newline is
also accepted once its bytes form a complete JSON object.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import socket
import threading

from .constants import MAX_REQUEST_BYTES

ACCEPT_POLL_SECONDS = 1.0


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


class SocketServer(object):
    def __init__(self, host, port, handle, log):
        self.host, self.port = host, port
        self.handle = handle
        self.log = log
        self.listener = None
        self.running = False
        self.threads = []

    def start(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen(5)
        listener.settimeout(ACCEPT_POLL_SECONDS)
        self.listener = listener
        self.running = True
        self._spawn(self._accept_loop)

    def stop(self):
        self.running = False
        if self.listener is not None:
            try:
                self.listener.close()
            except OSError:
                pass
            self.listener = None

    def _spawn(self, target, *args):
        thread = threading.Thread(target=target, args=args)
        thread.daemon = True
        thread.start()
        self.threads = [t for t in self.threads if t.is_alive()] + [thread]

    def _accept_loop(self):
        while self.running:
            try:
                client, address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    self.log("accept failed; listener closed")
                break
            self.log("client connected from %s:%s" % address[:2])
            self._spawn(self._serve, client)

    def _serve(self, client):
        reader = RequestReader()
        try:
            while self.running:
                data = client.recv(65536)
                if not data:
                    break
                try:
                    requests = reader.feed(data)
                except ValueError as e:
                    # The stream can no longer be trusted: say why, then hang up.
                    client.sendall(encode({"status": "error", "message": "bad request: %s" % e}))
                    break
                for request in requests:
                    client.sendall(encode(self.handle(request)))
        except (OSError, socket.error) as e:
            self.log("client connection error: %s" % e)
        finally:
            try:
                client.close()
            except OSError:
                pass
            self.log("client disconnected")
