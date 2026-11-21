# Ensures `import ableton_studio_mcp.server` resolves no matter how pytest is invoked.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import contextlib

import pytest


@pytest.fixture(autouse=True)
def _no_undo_groups(monkeypatch, request):
    """Tools that wrap their work in an undo group would add begin/end
    commands to every recorded exchange; tests about the exchange itself
    don't want them. Tests marked `undo_groups` keep the real behaviour."""
    if request.node.get_closest_marker("undo_groups"):
        return
    from ableton_studio_mcp import live
    monkeypatch.setattr(live, "undo_group", lambda name: contextlib.nullcontext())
