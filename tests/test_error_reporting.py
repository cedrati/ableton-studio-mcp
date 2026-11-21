"""Naming regression: get_session_info must report the main track's real
name ("Main" in Live 12), like the mixer tools do. Connection-level error
handling is covered by test_live_client.py."""

import types

import pytest

from test_remote_script_bridge import _load_script_module, make_instance


@pytest.fixture(scope="module")
def script_module():
    return _load_script_module()


def _song_with_master(name):
    param = lambda v: types.SimpleNamespace(value=v)
    master = types.SimpleNamespace(
        mixer_device=types.SimpleNamespace(volume=param(0.85), panning=param(0.0)))
    if name is not None:
        master.name = name
    return types.SimpleNamespace(
        tempo=120.0, signature_numerator=4, signature_denominator=4,
        tracks=[], return_tracks=[], master_track=master,
        is_playing=False, current_song_time=0.0, song_length=0.0,
        loop=False, loop_start=0.0, loop_length=4.0)


@pytest.mark.parametrize("live_name, expected", [
    ("Main", "Main"),      # Live 12
    ("Master", "Master"),  # Live 11
    (None, "Master"),      # attribute missing: fall back
])
def test_session_info_reports_live_master_name(script_module, live_name, expected):
    inst = make_instance(script_module)
    inst._song = _song_with_master(live_name)
    assert inst._get_session_info()["master_track"]["name"] == expected
