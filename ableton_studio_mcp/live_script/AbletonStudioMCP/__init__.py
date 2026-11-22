"""AbletonStudioMCP: the Ableton Live control surface of Ableton Studio MCP.

Live loads this folder from ``<User Library>/Remote Scripts`` and calls
:func:`create_instance` when the control surface is selected. The surface
listens on 127.0.0.1:9877 for the Ableton Studio MCP server.
"""
from __future__ import absolute_import, print_function, unicode_literals

# Must equal the server's version: the server refuses any other.
SCRIPT_VERSION = "2.5.0"

from . import registry  # noqa: E402
from .constants import HOST, PORT, PROTOCOL_VERSION  # noqa: E402,F401  (re-exported)
from .surface import AbletonStudioMCP  # noqa: E402

# Every command plus the behaviour flags, generated from the handlers.
SCRIPT_CAPABILITIES = registry.capabilities()


def create_instance(c_instance):
    return AbletonStudioMCP(c_instance)
