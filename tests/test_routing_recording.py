"""Return/main-track devices, routing, arrangement recording, listening and
MIDI import (Remote Script 1.12.0).

Live-side tests drive the real Remote Script against fakes; server-side tests
drive the real tool functions against a scripted connection.
"""

import json
import math
import struct
import wave
from collections import deque

import pytest

from ableton_studio_mcp import app, live, tools
from ableton_studio_mcp.tools import listening
from test_clip_notes import call
from test_remote_script_bridge import _load_script_module, make_instance


@pytest.fixture(scope="module")
def script_module():
    return _load_script_module()


# ------------------------------------------------------------ Live fakes

class Value(object):
    def __init__(self, value):
        self.value = value


class Mixer(object):
    def __init__(self):
        self.volume, self.panning = Value(0.85), Value(0.0)


class Param(object):
    def __init__(self, name, value=0.5):
        self.name, self.value, self.min, self.max = name, value, 0.0, 1.0
        self.is_quantized = False


class Device(object):
    def __init__(self, name):
        self.name = self.class_name = name
        self.parameters = [Param("Device On", 1.0), Param("Dry/Wet", 0.3)]


class Routing(object):
    def __init__(self, name):
        self.display_name = name


class Track(object):
    INPUTS = ["Ext. In", "Resampling", "1-Piano", "2-Piano Doublure", "Aucune entrée"]
    OUTPUTS = ["Master", "A-Reverb", "Sends Only"]

    def __init__(self, name, armable=True):
        self.name = name
        self.devices = []
        self.clip_slots = []
        self.arrangement_clips = []
        self.mixer_device = Mixer()
        self.has_audio_input, self.has_midi_input = True, False
        self.mute = self.solo = False
        self.can_be_armed = armable
        self.arm = False
        self.current_monitoring_state = 1
        self.available_input_routing_types = [Routing(n) for n in self.INPUTS]
        self.available_output_routing_types = [Routing(n) for n in self.OUTPUTS]
        self._in_type = self.available_input_routing_types[0]
        self.output_routing_type = self.available_output_routing_types[0]
        self.output_routing_channel = Routing("1/2")
        self.available_output_routing_channels = [Routing("1/2")]
        self.writes = []

    # Channels depend on the type, as in Live.
    @property
    def input_routing_type(self):
        return self._in_type

    @input_routing_type.setter
    def input_routing_type(self, value):
        self.writes.append(("input_type", value.display_name))
        self._in_type = value
        self.input_routing_channel = self.available_input_routing_channels[0]

    @property
    def available_input_routing_channels(self):
        if "Piano" in self._in_type.display_name:
            return [Routing("Post FX"), Routing("Pre FX")]
        return [Routing("1/2"), Routing("1"), Routing("2")]


class MainTrack(Track):
    """Live refuses mute/solo/arm reads on the main track."""

    def __init__(self):
        Track.__init__(self, "Main", armable=False)

    @property
    def mute(self):
        raise RuntimeError("Main track has no mute")

    @mute.setter
    def mute(self, v):
        pass


class Song(object):
    def __init__(self):
        self.tracks = [Track("1-Audio"), Track("2-Audio")]
        self.return_tracks = [Track("A-Reverb", armable=False)]
        self.return_tracks[0].devices = [Device("Reverb")]
        self.master_track = MainTrack()
        self.master_track.devices = [Device("Limiter")]
        self.is_playing = False
        self.record_mode = False
        self.current_song_time = 0.0

    def start_playing(self):
        self.is_playing = True

    def stop_playing(self):
        self.is_playing = False


def live_instance(script_module, song):
    inst = make_instance(script_module)
    inst._song = song
    queue = deque()
    inst.schedule_message = lambda delay, cb: cb() if delay == 0 else queue.append(cb)

    def run(limit=500):
        n = 0
        while queue and n < limit:
            queue.popleft()()
            n += 1
    return inst, run


def resolve(deferred, run):
    out = {}
    deferred.start(lambda v: out.setdefault("ok", v), lambda m: out.setdefault("err", m))
    run()
    return out


# -------------------------------------------------- return / main tracks

def test_track_info_for_return_and_main(script_module):
    inst, _ = live_instance(script_module, Song())
    ret = inst._get_track_info(0, "return")
    assert ret["name"] == "A-Reverb" and ret["devices"][0]["name"] == "Reverb"
    assert ret["clip_slots"] == [] and ret["track_type"] == "return"
    main = inst._get_track_info(0, "master")
    assert main["name"] == "Main" and main["mute"] is False  # read refused -> default


def test_device_parameters_on_return_and_main(script_module):
    song = Song()
    inst, _ = live_instance(script_module, song)
    params = inst._get_device_parameters(0, 0, "return")
    assert params["device"]["name"] == "Reverb"
    inst._set_device_parameter(0, 0, 1, 0.8, "master")
    assert song.master_track.devices[0].parameters[1].value == 0.8
    with pytest.raises(IndexError):
        inst._get_device_parameters(3, 0, "return")


def test_track_type_is_validated(script_module):
    inst, _ = live_instance(script_module, Song())
    with pytest.raises(ValueError):
        inst._get_track_info(0, "group")


# ---------------------------------------------------------------- routing

def test_routing_lists_options_and_monitoring(script_module):
    inst, _ = live_instance(script_module, Song())
    r = inst._get_track_routing(0)
    assert r["input"]["type"] == "Ext. In"
    assert "Resampling" in r["input"]["available_types"]
    assert r["output"]["available_types"] == Track.OUTPUTS
    assert r["monitoring"] == "auto"
    ret = inst._get_track_routing(0, "return")
    assert "input" not in ret and ret["output"]["type"] == "Master"


def test_routing_exact_substring_and_errors(script_module):
    song = Song()
    inst, _ = live_instance(script_module, song)
    inst._set_track_routing(0, input_type="resampling", monitoring="off")
    assert song.tracks[0].input_routing_type.display_name == "Resampling"
    assert song.tracks[0].current_monitoring_state == 2
    inst._set_track_routing(0, input_type="Doublure")  # unique substring
    assert song.tracks[0].input_routing_type.display_name == "2-Piano Doublure"
    with pytest.raises(ValueError, match="ambiguous"):
        inst._set_track_routing(0, input_type="Piano")
    with pytest.raises(ValueError, match="Available"):
        inst._set_track_routing(0, output_type="Bus 7")
    with pytest.raises(ValueError):
        inst._set_track_routing(0, monitoring="loud")


def test_routing_type_is_written_before_channel(script_module):
    """Channels depend on the type: "Post FX" only exists for a track input."""
    song = Song()
    inst, _ = live_instance(script_module, song)
    r = inst._set_track_routing(1, input_type="1-Piano", input_channel="Post FX")
    assert song.tracks[1].input_routing_channel.display_name == "Post FX"
    assert r["changed"] == ["input_type", "input_channel"]


def test_return_track_has_no_input(script_module):
    inst, _ = live_instance(script_module, Song())
    with pytest.raises(ValueError):
        inst._set_track_routing(0, "return", input_type="Resampling")
    inst._set_track_routing(0, "return", output_type="Sends Only")


# -------------------------------------------------------------- recording

def test_record_needs_an_armed_track(script_module):
    inst, _ = live_instance(script_module, Song())
    with pytest.raises(ValueError, match="armed"):
        inst._record_arrangement(0, 8)
    with pytest.raises(ValueError):
        inst._record_arrangement(8, 8)


def test_record_runs_and_stops_at_end(script_module):
    song = Song()
    song.tracks[1].arm = True
    inst, run = live_instance(script_module, song)
    out = resolve(inst._record_arrangement(4.0, 12.0), lambda: None)
    run(limit=1)  # nothing pending yet; resolution happened synchronously
    assert out["ok"]["status"] == "recording"
    assert song.record_mode and song.is_playing
    assert out["ok"]["armed"] == [{"index": 1, "name": "2-Audio"}]
    song.current_song_time = 8.0
    run(limit=3)
    assert not inst._recording["finished"]
    song.current_song_time = 12.05
    run(limit=3)
    status = inst._get_recording_status()
    assert status["recording"]["finished"] and status["recording"]["reason"] == "end_reached"
    assert not song.record_mode and not song.is_playing


def test_record_stopped_by_hand_or_command(script_module):
    song = Song()
    song.tracks[0].arm = True
    inst, run = live_instance(script_module, song)
    resolve(inst._record_arrangement(0.0, 64.0), lambda: None)
    song.stop_playing()  # the user pressed stop
    run(limit=3)
    assert inst._recording["reason"] == "stopped" and not song.record_mode
    resolve(inst._record_arrangement(0.0, 64.0), lambda: None)
    with pytest.raises(RuntimeError):
        inst._record_arrangement(0.0, 64.0)  # one at a time
    assert inst._stop_arrangement_recording()["reason"] == "stopped_by_command"
    assert not song.is_playing


class AudioClip(object):
    is_audio_clip, is_midi_clip = True, False
    name, length, start_time, end_time = "take", 16.0, 0.0, 16.0
    file_path, sample_rate, sample_length, warping = "/tmp/take.wav", 48000.0, 384000, True


def test_audio_clip_file(script_module):
    song = Song()
    song.tracks[0].arrangement_clips = [AudioClip()]
    inst, _ = live_instance(script_module, song)
    info = inst._get_audio_clip_file(0, 0, "arrangement")
    assert info["file_path"] == "/tmp/take.wav" and info["sample_rate"] == 48000.0


def test_new_commands_are_advertised(script_module):
    caps = set(script_module.SCRIPT_CAPABILITIES)
    assert {"return_master_devices", "get_track_routing", "set_track_routing",
            "record_arrangement", "stop_arrangement_recording",
            "get_recording_status", "get_audio_clip_file"} <= caps


def test_expected_version_matches_script(script_module):
    from ableton_studio_mcp.install import SCRIPT_VERSION as EXPECTED_REMOTE_SCRIPT_VERSION
    assert EXPECTED_REMOTE_SCRIPT_VERSION == script_module.SCRIPT_VERSION


# ----------------------------------------------------------- server side

class ScriptedConnection(object):
    """Answers each command from a table (value or callable(params))."""

    def __init__(self, answers):
        self.answers = answers
        self.sent = []

    def call(self, command_type, params=None):
        self.sent.append((command_type, params or {}))
        answer = self.answers.get(command_type, {})
        return answer(params or {}) if callable(answer) else answer


@pytest.fixture
def connect(monkeypatch):
    def _make(answers):
        conn = ScriptedConnection(answers)
        monkeypatch.setattr(live, "client", lambda: conn)
        return conn
    return _make


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
        monkeypatch.setattr(live, "require", lambda name: None)


def test_load_sends_track_type_only_for_return_and_main(connect):
    conn = connect({"load_browser_item": {"loaded": True, "new_devices": ["Reverb"]}})
    call(tools.load_instrument_or_effect, 0, "query:x")
    call(tools.load_instrument_or_effect, 1, "query:x", track_type="return")
    call(tools.load_instrument_or_effect, 0, "query:x", track_type="master")
    assert [p.get("track_type") for _, p in conn.sent] == [None, "return", "master"]
    assert "track_type must be" in call(tools.load_instrument_or_effect, 0, "q",
                                        track_type="bus")


def test_old_script_is_refused_for_return_tracks(connect, monkeypatch):
    def require(name):
        if name == "return_master_devices":
            raise live.MissingCapability("missing " + name)
    monkeypatch.setattr(live, "require", require)
    conn = connect({})
    out = call(tools.set_device_parameter, 0, 0, 1, 0.5, track_type="return")
    assert out == "missing return_master_devices" and conn.sent == []


def test_routing_tool_sends_only_given_fields(connect):
    conn = connect({"set_track_routing": {"changed": ["input_type"]}})
    call(tools.set_track_routing, 2, input_type="Resampling", monitoring="off")
    assert conn.sent == [("set_track_routing", {"track_index": 2, "input_type": "Resampling",
                                                "monitoring": "off"})]


def test_resampling_name_is_found_in_french():
    routing = {"input": {"available_types": ["Entrée ext.", "Rééchantillonnage", "1-Orgue"]}}
    assert listening._resampling_input_name(routing) == "Rééchantillonnage"
    assert listening._resampling_input_name({"input": {"available_types": ["Ext. In"]}}) is None


def test_record_arrangement_waits_for_the_watcher(connect, monkeypatch):
    monkeypatch.setattr(listening, "RECORDING_POLL_S", 0.0)
    polls = iter([{"recording": {"finished": False}}] * 2
                 + [{"recording": {"finished": True, "reason": "end_reached"}}])
    conn = connect({"get_session_info": {"tempo": 120.0},
                    "record_arrangement": {"status": "recording"},
                    "get_recording_status": lambda p: next(polls)})
    out = json.loads(call(tools.record_arrangement, 0.0, 8.0))
    assert out["recording"]["reason"] == "end_reached"
    assert [c for c, _ in conn.sent].count("get_recording_status") == 3


def _wav(path, seconds=0.5, amp=0.5):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        frames = bytearray()
        for i in range(int(44100 * seconds)):
            v = int(amp * 32767 * math.sin(2 * math.pi * 220 * i / 44100))
            frames += struct.pack("<hh", v, v)
        w.writeframes(bytes(frames))


def test_listen_records_analyzes_and_cleans_up(connect, monkeypatch, tmp_path):
    monkeypatch.setattr(listening, "RECORDING_POLL_S", 0.0)
    take = tmp_path / "Claude – écoute 0001 [2026-11-21 120000].wav"
    _wav(take)
    asd = tmp_path / (take.name + ".asd")
    asd.write_bytes(b"live analysis")
    conn = connect({
        "get_session_info": {"tempo": 120.0},
        "get_recording_status": lambda p: {"armed_tracks": [{"index": 0}],
                                           "recording": {"finished": True}},
        "create_audio_track": {"index": 4, "name": "5-Audio"},
        "get_track_routing": {"input": {"available_types": ["Ext. In", "Rééchantillonnage"]}},
        "get_arrangement_clips": {"clips": [{"name": "take"}]},
        "get_audio_clip_file": {"file_path": str(take)},
    })
    out = json.loads(call(tools.listen_to_arrangement, 0.0, 4.0, report="basic"))
    assert out["analysis"]["peak_dbfs"] == pytest.approx(-6.02, abs=0.1)
    assert out["recorded"]["track"] == "deleted" and out["recorded"]["file"] == "deleted"
    assert not take.exists() and not asd.exists()  # no audio piles up in the project
    sent = [(c, p) for c, p in conn.sent]
    assert ("set_track_routing", {"track_index": 4, "input_type": "Rééchantillonnage",
                                  "monitoring": "off"}) in sent
    assert ("delete_track", {"track_index": 4}) in sent
    # The track armed before was disarmed for the take, then re-armed.
    arms = [p for c, p in sent if c == "set_track_arm" and p["track_index"] == 0]
    assert arms == [{"track_index": 0, "arm": False}, {"track_index": 0, "arm": True}]


def _midi(path, notes, division=96):
    def vlq(n):
        out = [n & 0x7F]
        n >>= 7
        while n:
            out.insert(0, (n & 0x7F) | 0x80)
            n >>= 7
        return bytes(out)
    events, t = [], 0
    timeline = sorted([(s, 0x90, p) for p, s, d in notes] + [(s + d, 0x80, p) for p, s, d in notes])
    for tick, kind, pitch in timeline:
        events.append(vlq(tick - t) + bytes([kind, pitch, 100 if kind == 0x90 else 0]))
        t = tick
    body = b"".join(events) + b"\x00\xff\x2f\x00"
    path.write_bytes(b"MThd" + struct.pack(">IHHH", 6, 0, 1, division)
                     + b"MTrk" + struct.pack(">I", len(body)) + body)


def test_import_midi_creates_a_clip_and_chunks(connect, monkeypatch, tmp_path):
    monkeypatch.setattr(app, "NOTES_PER_REQUEST", 2)
    mid = tmp_path / "m.mid"
    _midi(mid, [(60, 0, 96), (64, 96, 96), (67, 480, 48)])  # last note ends at beat 5.5
    conn = connect({"get_track_info": {"clip_slots": [{"has_clip": False}] * 8}})
    out = call(tools.import_midi_file, str(mid), track_index=1, clip_index=0,
               transpose=-12)
    assert out.startswith("Imported 3 notes")
    assert ("create_clip", {"track_index": 1, "clip_index": 0, "length": 8.0}) in conn.sent
    adds = [p["notes"] for c, p in conn.sent if c == "add_notes_to_clip"]
    assert [len(a) for a in adds] == [2, 1]
    assert [n["pitch"] for a in adds for n in a] == [48, 52, 55]


def test_import_midi_replace_and_describe(connect, tmp_path):
    mid = tmp_path / "m.mid"
    _midi(mid, [(60, 0, 96)])
    conn = connect({"get_track_info": {"clip_slots": [{"has_clip": True}]}})
    call(tools.import_midi_file, str(mid), track_index=0, replace=True)
    assert [c for c, _ in conn.sent] == ["get_track_info", "clear_notes_from_clip",
                                         "add_notes_to_clip"]
    desc = json.loads(call(tools.import_midi_file, str(mid)))
    assert desc["tracks"][0]["notes"] == 1


# ------------------------------------------------- mix report (1.13.0)

def test_track_meters_cover_tracks_returns_and_main(script_module):
    song = Song()
    for t in song.tracks + song.return_tracks + [song.master_track]:
        t.output_meter_left, t.output_meter_right = 0.5, 0.7
    inst, _ = live_instance(script_module, song)
    out = inst._get_track_meters()
    kinds = [(m["type"], m["index"]) for m in out["meters"]]
    assert kinds == [("track", 0), ("track", 1), ("return", 0), ("master", 0)]
    assert all(m["level"] == 0.7 for m in out["meters"])


def test_listen_mix_report_returns_image_and_meters(connect, monkeypatch, tmp_path):
    from mcp.server.fastmcp import Image
    monkeypatch.setattr(listening, "RECORDING_POLL_S", 0.0)
    take = tmp_path / "take.wav"
    _wav(take, seconds=4.0)
    polls = iter([{"armed_tracks": []}, {"recording": {"finished": False}},
                  {"recording": {"finished": False}}, {"recording": {"finished": True}}])
    connect({
        "get_session_info": {"tempo": 120.0},
        "get_recording_status": lambda p: next(polls),
        "create_audio_track": {"index": 2, "name": "3-Audio"},
        "get_track_routing": {"input": {"available_types": ["Resampling"]}},
        "get_arrangement_clips": {"clips": [{"name": "take"}]},
        "get_audio_clip_file": {"file_path": str(take)},
        "get_track_meters": {"meters": [
            {"type": "track", "index": 0, "name": "Orgue", "level": 0.8},
            {"type": "track", "index": 1, "name": "Basse", "level": 0.4},
            {"type": "track", "index": 2, "name": "Claude – écoute", "level": 0.9},
            {"type": "master", "index": 0, "name": "Main", "level": 0.85}]},
    })
    monkeypatch.setattr(listening, "_spectrogram_path", lambda p: str(tmp_path / "spec.png"))
    out = call(tools.listen_to_arrangement, 0.0, 8.0, target="classical")
    assert isinstance(out, list) and isinstance(out[1], Image)
    data = json.loads(out[0])
    assert data["analysis"]["loudness"]["integrated_lufs"] is not None
    assert data["analysis"]["assessment"]["target"].startswith("Classique")
    names = [m["name"] for m in data["track_meters_during_take"]["tracks"]]
    assert names == ["Main", "Orgue", "Basse"]  # main first, listening track skipped
    assert (tmp_path / "spec.png").exists()


def test_analyze_mix_tool_validates_target(tmp_path):
    take = tmp_path / "t.wav"
    _wav(take, seconds=1.0)
    assert "target must be" in call(tools.analyze_mix, str(take), target="radio")
    text_only = call(tools.analyze_mix, str(take), spectrogram=False)
    assert json.loads(text_only)["assessment"]["findings"]


# ------------------------------------------- song scale, parameter display (1.14.0)

class ScaleSong(Song):
    LIVE_SCALES = ["Major", "Minor", "Dorian", "Phrygian Dominant"]

    def __init__(self):
        Song.__init__(self)
        self.root_note, self._scale, self.scale_mode = 0, "Major", False

    @property
    def scale_name(self):
        return self._scale

    @scale_name.setter
    def scale_name(self, v):
        if v in self.LIVE_SCALES:  # Live ignores unknown names
            self._scale = v

    @property
    def scale_intervals(self):
        return {"Major": [0, 2, 4, 5, 7, 9, 11], "Phrygian Dominant": [0, 1, 4, 5, 7, 8, 10]}.get(self._scale, [])


def test_song_scale_get_and_set(script_module):
    song = ScaleSong()
    inst, _ = live_instance(script_module, song)
    out = inst._set_song_scale(root_note="Eb", scale_name="Phrygian Dominant", scale_mode=True)
    assert (out["root_note"], out["root_name"], out["scale_name"], out["scale_mode"]) == (3, "D#", "Phrygian Dominant", True)
    with pytest.raises(ValueError, match="did not accept"):
        inst._set_song_scale(scale_name="Hijaz")
    with pytest.raises(ValueError):
        inst._set_song_scale(root_note="H")


class DisplayParam(Param):
    value_items = ["Low Cut 48", "Low Cut 12", "Low Shelf", "Bell", "Notch", "High Shelf", "High Cut 12", "High Cut 48"]

    def __init__(self, name, value):
        Param.__init__(self, name, value)
        self.max = 7.0   # quantized: one step per item

    def str_for_value(self, v):
        return self.value_items[int(v)]


def test_parameter_display_and_items(script_module):
    song = Song()
    dev = Device("EQ Eight")
    dev.parameters = [DisplayParam("1 Filter Type A", 3)]
    song.tracks[0].devices = [dev]
    inst, _ = live_instance(script_module, song)
    p = inst._get_device_parameters(0, 0)["device"]["parameters"][0]
    assert p["display"] == "Bell" and p["value_items"][5] == "High Shelf"
    r = inst._set_device_parameter(0, 0, 0, 5)
    assert (r["old_display"], r["display"]) == ("Bell", "High Shelf")
    with pytest.raises(ValueError, match="takes 0.0 to 7.0, not 9.0"):
        inst._set_device_parameter(0, 0, 0, 9)
    with pytest.raises(IndexError, match="no parameter 3"):
        inst._set_device_parameter(0, 0, 3, 1)



def test_listen_can_keep_the_take(connect, monkeypatch, tmp_path):
    monkeypatch.setattr(listening, "RECORDING_POLL_S", 0.0)
    take = tmp_path / "Claude – écoute 0001 [2026-11-21 120500].wav"
    _wav(take)
    connect({
        "get_session_info": {"tempo": 120.0},
        "get_recording_status": lambda p: {"armed_tracks": [], "recording": {"finished": True}},
        "create_audio_track": {"index": 2, "name": "3-Audio"},
        "get_track_routing": {"input": {"available_types": ["Resampling"]}},
        "get_arrangement_clips": {"clips": [{"name": "take"}]},
        "get_audio_clip_file": {"file_path": str(take)},
    })
    out = json.loads(call(tools.listen_to_arrangement, 0.0, 4.0, report="basic", keep_audio=True))
    assert out["recorded"]["track"] == "deleted (file kept)" and take.exists()


def test_discard_take_never_touches_other_files(tmp_path):
    mine = tmp_path / "Vocals 0003 [2026-11-21 120000].wav"
    mine.write_bytes(b"RIFF")
    assert listening._discard_take(str(mine)) is False and mine.exists()
    ours = tmp_path / "Claude – écoute 0002.wav"
    ours.write_bytes(b"RIFF")
    assert listening._discard_take(str(ours)) is True and not ours.exists()


def test_old_spectrograms_are_pruned(monkeypatch, tmp_path):
    import os
    import tempfile
    import time as _t
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    folder = tmp_path / "ableton-mcp"
    folder.mkdir()
    for i in range(listening.SPECTROGRAMS_KEPT + 5):
        f = folder / ("take%02d_spectrogram.png" % i)
        f.write_bytes(b"png")
        os.utime(f, (_t.time() - 1000 + i, _t.time() - 1000 + i))
    listening._spectrogram_path("/x/new.wav")
    left = sorted(p.name for p in folder.iterdir())
    assert len(left) == listening.SPECTROGRAMS_KEPT and left[0] == "take05_spectrogram.png"


# ------------------------------------------------------------- delete_locator

def test_delete_locator_tool_prefers_time_over_name(connect):
    conn = connect({"delete_locator": {"time": 16.0, "name": "Drop"}})
    out = call(tools.delete_locator, name="Drop", time=16.0)
    assert conn.sent == [("delete_locator", {"time": 16.0})]
    assert out == "Locator 'Drop' at beat 16.0 deleted"


def test_delete_locator_tool_by_name(connect):
    conn = connect({"delete_locator": {"time": 32.0, "name": "Break"}})
    call(tools.delete_locator, name="Break")
    assert conn.sent == [("delete_locator", {"name": "Break"})]


def test_delete_locator_tool_needs_a_target(connect):
    conn = connect({})
    assert "name or its time" in call(tools.delete_locator)
    assert conn.sent == []


def test_recording_uses_punch_in_after_a_preroll(script_module):
    """Live 12.4: playback started by a script doesn't reliably begin at
    current_song_time, and moving the playhead while recording splits the
    take. Recording sets the passage as the punch range, starts playback,
    jumps one beat before it, and only then arms Arrangement Record; loop and
    punch settings are put back at the end."""
    song = Song()
    song.tracks[1].arm = True
    song.loop, song.loop_start, song.loop_length = True, 8.0, 16.0
    song.punch_in = song.punch_out = False
    song.continue_playing = lambda: setattr(song, "is_playing", True)
    inst, run = live_instance(script_module, song)
    out = resolve(inst._record_arrangement(64.0, 72.0), lambda: None)
    assert (song.loop, song.loop_start, song.loop_length, song.punch_in, song.punch_out) == (False, 64.0, 8.0, True, True)
    assert song.current_song_time == 63.0 and not song.record_mode   # jumped to the pre-roll, not armed yet
    run(limit=1)                                                      # the next tick: in the pre-roll
    assert song.record_mode and out["ok"]["status"] == "recording"
    song.current_song_time = 72.1
    run(limit=3)
    assert inst._recording["reason"] == "end_reached" and not song.record_mode
    assert (song.loop, song.loop_start, song.loop_length, song.punch_in, song.punch_out) == (True, 8.0, 16.0, False, False)


def test_recording_is_not_armed_until_the_preroll_is_reached(script_module):
    song = Song()
    song.tracks[1].arm = True

    song.continue_playing = lambda: setattr(song, "is_playing", True)
    inst, run = live_instance(script_module, song)
    inst.schedule_message = lambda delay, cb: None      # ticks never come
    song.current_song_time = 40.0                       # playback began inside the passage
    resolve(inst._record_arrangement(32.0, 48.0), lambda: None)
    assert not song.record_mode                         # never records from the wrong place


# ------------------------------------------------ Back to Arrangement (#83)

class TimedSong(Song):
    """A song get_session_info can describe."""

    def __init__(self):
        Song.__init__(self)
        self.tempo, self.signature_numerator, self.signature_denominator = 120.0, 4, 4


class OverridingSong(TimedSong):
    def __init__(self):
        TimedSong.__init__(self)
        self.back_to_arranger = True
        self.tracks[0].playing_slot_index = 2     # a Session clip plays
        self.tracks[1].playing_slot_index = -2    # stopped, but still overriding


def test_back_to_arrangement_presses_the_button(script_module):
    song = OverridingSong()
    inst, _ = live_instance(script_module, song)
    assert inst._get_session_info()["back_to_arranger"] is True
    inst, run = live_instance(script_module, song)
    out = resolve(inst._back_to_arrangement(), run)["ok"]
    assert out == {"was_overriding": True, "tracks_playing_session_clips": ["1-Audio"],
                   "back_to_arranger": False, "settled": True}
    assert song.back_to_arranger is False
    # Already following the Arrangement: nothing to press.
    assert inst._back_to_arrangement()["was_overriding"] is False


class LateSong(OverridingSong):
    """Live turns the button off a few ticks after the script asks."""

    def __init__(self):
        OverridingSong.__init__(self)
        self._lit, self._ticks_left = True, None

    @property
    def back_to_arranger(self):
        if self._ticks_left is not None:
            self._ticks_left -= 1
            if self._ticks_left < 0:
                self._lit = False
        return self._lit

    @back_to_arranger.setter
    def back_to_arranger(self, value):
        if value:
            self._lit = True
        else:
            self._ticks_left = 3


def test_back_to_arrangement_replies_once_live_applied_it(script_module):
    inst, run = live_instance(script_module, LateSong())
    out = resolve(inst._back_to_arrangement(), run)["ok"]
    assert (out["back_to_arranger"], out["settled"]) == (False, True)


def test_back_to_arrangement_needs_the_api(script_module):
    inst, _ = live_instance(script_module, TimedSong())
    assert inst._get_session_info()["back_to_arranger"] is False
    with pytest.raises(RuntimeError, match="no Back to Arrangement"):
        inst._back_to_arrangement()
    assert "back_to_arrangement" in set(script_module.SCRIPT_CAPABILITIES)


def test_back_to_arrangement_tool_reports_what_it_stopped(connect):
    connect({"back_to_arrangement": {"was_overriding": True,
                                     "tracks_playing_session_clips": ["Lead", "Drums"]}})
    assert call(tools.back_to_arrangement).endswith("(stopped the Session clips of: Lead, Drums)")
    connect({"back_to_arrangement": {"was_overriding": False}})
    assert call(tools.back_to_arrangement) == "Every track already follows the Arrangement"


def _listen_answers(take, clips_by_track, overriding=True):
    polls = iter([{"armed_tracks": [], "recording": {"finished": False}}] * 2
                 + [{"armed_tracks": [], "recording": {"finished": True}}] * 10)
    return {
        "get_session_info": {"tempo": 120.0, "back_to_arranger": overriding},
        "back_to_arrangement": {"was_overriding": overriding,
                                "tracks_playing_session_clips": ["Lead"] if overriding else []},
        "get_recording_status": lambda p: next(polls),
        "create_audio_track": {"index": 3, "name": "4-Audio"},
        "get_track_routing": {"input": {"available_types": ["Resampling"]}},
        "get_arrangement_clips": lambda p: {"clips": clips_by_track.get(p["track_index"], [])},
        "get_audio_clip_file": {"file_path": str(take)},
        "get_track_meters": {"meters": [
            {"type": "track", "index": 0, "name": "Lead", "level": 0.7},
            {"type": "track", "index": 1, "name": "Clavecin", "level": 0.0},
            {"type": "track", "index": 2, "name": "Bass", "level": 0.6},
            {"type": "master", "index": 0, "name": "Main", "level": 0.9}]},
    }


def test_listen_goes_back_to_arrangement_and_flags_mismatches(connect, monkeypatch, tmp_path):
    pytest.importorskip("numpy")
    monkeypatch.setattr(listening, "RECORDING_POLL_S", 0.0)
    monkeypatch.setattr(listening, "_spectrogram_path", lambda p: None)
    take = tmp_path / "Claude – écoute 0001 [2026-11-22 120000].wav"
    _wav(take, seconds=1.0)
    clips = {1: [{"start_time": 0.0, "end_time": 16.0}],      # clavecin: clips, silent
             2: [{"start_time": 0.0, "end_time": 16.0}],      # bass: clips, playing
             3: [{"start_time": 0.0, "end_time": 8.0}]}       # the take itself
    conn = connect(_listen_answers(take, clips))
    data = json.loads(call(tools.listen_to_arrangement, 0.0, 8.0, target="club"))
    sent = [c for c, _ in conn.sent]
    assert sent.index("back_to_arrangement") < sent.index("record_arrangement")
    assert data["back_to_arrangement"] == {"pressed": True, "stopped_session_clips_on": ["Lead"]}
    warnings = data["warnings"]
    assert any(w.startswith("Lead sounded although it has no Arrangement clip") for w in warnings)
    assert any(w.startswith("Clavecin stayed silent although it has Arrangement clips") for w in warnings)
    assert not any(w.startswith("Bass") for w in warnings)


def test_listen_can_keep_session_clips_but_says_so(connect, monkeypatch, tmp_path):
    monkeypatch.setattr(listening, "RECORDING_POLL_S", 0.0)
    take = tmp_path / "Claude – écoute 0002 [2026-11-22 120100].wav"
    _wav(take)
    conn = connect(_listen_answers(take, {3: [{"start_time": 0.0, "end_time": 4.0}]}))
    data = json.loads(call(tools.listen_to_arrangement, 0.0, 4.0, report="basic",
                           back_to_arrangement=False))
    assert "back_to_arrangement" not in [c for c, _ in conn.sent]
    assert data["warnings"][0].startswith("Some tracks play Session clips")
