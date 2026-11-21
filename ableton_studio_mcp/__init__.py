"""Ableton Studio MCP: AI music production in Ableton Live through the Model Context Protocol."""

__version__ = "2.2.0"

# The server works with any control surface of the same series (major.minor).
# A release that changes the control surface starts a new series; patch
# releases of the server alone don't make anyone reinstall it in Live.
SCRIPT_SERIES = ".".join(__version__.split(".")[:2])


def same_series(version):
    """Whether a control surface version belongs to this server's series."""
    return isinstance(version, str) and version.split(".")[:2] == SCRIPT_SERIES.split(".")
