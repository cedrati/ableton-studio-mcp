"""Device knowledge, inventory, and the device-specific Live commands
(sidechain routing, plug-in presets, Simpler, rack variations, drum chokes)."""

import json

import pytest

from ableton_studio_mcp import live, tools
from ableton_studio_mcp import device_knowledge as dk
from test_clip_notes import call
from test_remote_script_bridge import _load_script_module, make_instance


def test_native_sheets_and_plugin_families():
    comp = dk.lookup("compressor")
    assert comp["sidechain"] and "Threshold" in comp["key_parameters"]
    assert dk.lookup("Operator")["kind"] == "instrument"
    assert "TB-303" in dk.lookup("Acid V")["what"]
    assert "1176" in dk.plugin_description("Comp FET-76")
    assert "Cthulhu" in dk.plugin_description("Cthulhu")
    assert dk.lookup("Totally Unknown Plugin") is None
    assert all(e["kind"] in ("instrument", "audio_effect", "midi_effect", "max_for_live") for e in dk.NATIVE.values())


def test_legacy_and_pack_devices():
    legacy = ["Auto Filter Legacy", "Auto Pan", "Chorus", "Erosion Legacy", "Flanger", "Frequency Shifter",
              "Phaser", "Redux Legacy"]
    for name in legacy:
        entry = dk.lookup(name)
        assert entry["kind"] == "audio_effect" and entry["source"] == "Ableton Live 12 manual"
    assert "Shifter" in dk.lookup("frequency shifter")["tip"]
    conv = dk.lookup("Convolution Reverb")
    assert conv["kind"] == "max_for_live" and conv["source"] == "Ableton Pack (Max for Live)"
    card = dk.describe_device({"name": "Gated Delay", "class_name": "MxDeviceAudioEffect",
                               "class_display_name": "Max Audio Effect"})
    assert "gate" in card["what"]


def test_describe_device_cards():
    op = dk.describe_device({"name": "Acid Bass", "class_name": "Operator", "class_display_name": "Operator"})
    assert op["device"] == "Operator" and "FM" in op["category"] and op["preset_or_name"] == "Acid Bass"
    vst = dk.describe_device({"name": "Acid V", "class_name": "PluginDevice", "class_display_name": "Acid V"})
    assert vst["kind"] == "plug-in VST/VST3" and "303" in vst["what"]
    rack = dk.describe_device({"name": "909 Core Kit", "class_name": "DrumGroupDevice",
                               "class_display_name": "Drum Rack"})
    assert rack["kind"] == "Drum Rack" and "pads" in rack["what"]
    m4l = dk.describe_device({"name": "LFO", "class_name": "MxDeviceAudioEffect", "class_display_name": "LFO"})
    assert m4l["kind"].startswith("Max for Live") and "LFO" in m4l["what"]


# ------------------------------------------------------------ Live side

@pytest.fixture(scope="module")
def script_module():
    return _load_script_module()


class P:
    def __init__(self, name, value=0.0, lo=0.0, hi=1.0):
        self.name, self.value, self.min, self.max = name, value, lo, hi


class R:
    def __init__(self, n):
        self.display_name = n


class Compressor:
    name = class_name = class_display_name = "Compressor"
    type, is_active, latency_in_ms, can_have_chains = 2, True, 0.0, False

    def __init__(self):
        self.parameters = [P("Device On", 1), P("Threshold"), P("S/C On", 0)]
        self.available_input_routing_types = [R("No Input"), R("1-Kick"), R("2-Bass")]
        self.available_input_routing_channels = [R("Pre FX"), R("Post FX")]
        self.input_routing_type, self.input_routing_channel = self.available_input_routing_types[0], None


class Plugin:
    name = class_display_name = "Acid V"
    class_name, type, can_have_chains = "PluginDevice", 1, False
    parameters = []
    presets = ["Init", "Acid Squelch", "Rubber Bass"]
    selected_preset_index = 0


class Sample:
    file_path, length, sample_rate, warping, slicing_style, slices = "/tmp/break.wav", 96000, 48000, True, 0, [0, 100]
    slicing_region_count = 8


class Simpler:
    name = class_name = "OriginalSimpler"
    class_display_name, type, can_have_chains = "Simpler", 1, False
    parameters = []
    playback_mode, voices = 0, 1

    def __init__(self):
        self.sample, self.calls = Sample(), []

    def replace_sample(self, path):
        self.calls.append(("replace", path))

    def warp_as(self, beats):
        self.calls.append(("warp_as", beats))


class Rack:
    name, class_name, class_display_name, type = "Bass Rack", "InstrumentGroupDevice", "Instrument Rack", 1
    can_have_chains, can_have_drum_pads = True, False
    chains, visible_macro_count, variation_count, selected_variation_index = [], 8, 2, -1

    def __init__(self):
        self.parameters = [P("Device On", 1)] + [P("Macro %d" % i, 0.5) for i in range(1, 9)]
        self.calls = []

    def recall_selected_variation(self):
        self.calls.append("recall")

    def store_variation(self):
        self.variation_count += 1

    def randomize_macros(self):
        for p in self.parameters[1:]:
            p.value = 0.9


def _live(script_module, devices):
    track = type("T", (), {})()
    track.name, track.devices = "Bass", devices
    song = type("S", (), {})()
    song.tracks, song.return_tracks = [track], []
    inst = make_instance(script_module)
    inst._song = song
    return inst


def test_sidechain_routing_and_switch(script_module):
    comp = Compressor()
    inst = _live(script_module, [comp])
    info = inst._get_device_info(0, 0)
    assert info["sidechain"]["available_types"] == ["No Input", "1-Kick", "2-Bass"]
    out = inst._set_device_sidechain(0, 0, source_type="Kick", source_channel="Post FX")
    assert out["source_type"] == "1-Kick" and out["source_channel"] == "Post FX"
    assert comp.parameters[2].value == 1.0  # S/C On switched on
    with pytest.raises(ValueError):
        inst._set_device_sidechain(0, 0, source_type="Hats")


def test_plugin_presets(script_module):
    plug = Plugin()
    inst = _live(script_module, [plug])
    assert inst._get_device_info(0, 0)["plugin"]["preset_count"] == 3
    assert inst._select_plugin_preset(0, 0, preset_name="squelch")["preset"] == "Acid Squelch"
    assert plug.selected_preset_index == 1
    with pytest.raises(IndexError):
        inst._select_plugin_preset(0, 0, preset_index=9)


def test_simpler_load_and_slice(script_module, tmp_path):
    simp = Simpler()
    inst = _live(script_module, [simp])
    f = tmp_path / "break.wav"
    f.write_bytes(b"RIFF")
    inst._simpler_replace_sample(0, 0, str(f))
    out = inst._simpler_configure(0, 0, {"playback_mode": "slicing", "slicing_style": "region",
                                         "slicing_region_count": 16, "warp_as": 8})
    assert simp.playback_mode == 2 and simp.sample.slicing_style == 2 and simp.sample.slicing_region_count == 16
    assert ("warp_as", 8) in simp.calls and out["simpler"]["playback_mode"] == "slicing"
    with pytest.raises(ValueError):
        inst._simpler_replace_sample(0, 0, "relative.wav")


def test_rack_variations(script_module):
    rack = Rack()
    inst = _live(script_module, [rack])
    assert inst._rack_variation(0, 0, action="store")["variation_count"] == 3
    assert inst._rack_variation(0, 0, action="randomize")["macros"][0]["value"] == 0.9
    inst._rack_variation(0, 0, action="recall", index=1)
    assert rack.selected_variation_index == 1 and rack.calls == ["recall"]


def test_drum_choke(script_module):
    class Chain:
        choke_group = 0

    class Pad:
        def __init__(self, note, name):
            self.note, self.name, self.chains = note, name, [Chain()]

    class Drums:
        can_have_drum_pads, can_have_chains, name = True, True, "909"

        def __init__(self):
            self.drum_pads = [Pad(42, "Closed Hat"), Pad(46, "Open Hat"), Pad(36, "Kick")]
    rack = Drums()
    inst = _live(script_module, [rack])
    out = inst._set_drum_choke(0, [42, 46], 1)
    assert [p["note"] for p in out["pads"]] == [42, 46]
    assert rack.drum_pads[0].chains[0].choke_group == 1 and rack.drum_pads[2].chains[0].choke_group == 0


# ------------------------------------------------------------ server side

class _Conn:
    def __init__(self, answers):
        self.answers, self.sent = answers, []

    def call(self, cmd, params=None):
        self.sent.append((cmd, params or {}))
        a = self.answers.get(cmd, {})
        return a(params or {}) if callable(a) else a


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setattr(live, "require", lambda name: None)

    def make(answers):
        c = _Conn(answers)
        monkeypatch.setattr(live, "client", lambda: c)
        return c
    return make


def test_device_inventory(conn):
    tracks = {("track", 0): {"name": "Bass", "devices": [
        {"index": 0, "name": "Acid V", "class_name": "PluginDevice", "class_display_name": "Acid V"},
        {"index": 1, "name": "Compressor", "class_name": "Compressor", "class_display_name": "Compressor"},
        {"index": 2, "name": "Kit", "class_name": "DrumGroupDevice", "class_display_name": "Drum Rack"}]},
        ("master", 0): {"name": "Main", "devices": [
            {"index": 0, "name": "Limiter", "class_name": "Limiter", "class_display_name": "Limiter"}]}}
    conn({"get_session_info": {"track_count": 1, "return_track_count": 0},
          "get_device_parameters": {"device": {"chains": [{"chain_name": "Kick", "devices": [{"name": "Simpler"}]}]}},
          "get_track_info": lambda p: tracks[(p.get("track_type", "track"), p["track_index"])],
          "get_browser_items_at_path": lambda p: {"items": [{"name": "Arturia", "is_folder": True}]}
          if p["path"].count("/") == 1 else {"items": [{"name": "Acid V"}, {"name": "Comp FET-76"}]}})
    out = json.loads(call(tools.device_inventory, installed_plugins=True))
    bass = out["tracks"][0]["devices"]
    assert "303" in bass[0]["what"] and bass[1]["sidechain"] is True
    assert bass[2]["chains"] == [{"name": "Kick", "devices": ["Simpler"]}]
    assert out["tracks"][1]["type"] == "master" and out["tracks"][1]["devices"][0]["device"] == "Limiter"
    assert out["installed_plugins"]["Arturia"] == ["Acid V", "Comp FET-76"]


def test_device_knowledge_tool():
    assert json.loads(call(tools.device_knowledge, name="Glue Compressor"))["sidechain"] is True
    cat = json.loads(call(tools.device_knowledge, kind="midi_effect"))
    assert any(d["name"] == "Arpeggiator" for d in cat["devices"]) and "API" in cat["midi_tools"]


# ------------------------------------------------ device chain (#84)

class Dev:
    def __init__(self, name):
        self.name, self.parameters = name, []


class ChainTrack:
    def __init__(self, names):
        self.name, self.devices = "Bass", [Dev(n) for n in names]

    def delete_device(self, index):
        del self.devices[index]


class MovingSong:
    """Live 12.4's move_device: the position counts the device still in place."""

    def __init__(self, track):
        self.tracks, self.return_tracks = [track], []

    def move_device(self, device, target, position):
        chain = target.devices
        chain.insert(position, device)
        for i, d in enumerate(chain):
            if d is device and i != position:
                del chain[i]
                break


def _chain_live(script_module, names, can_move=True):
    track = ChainTrack(names)
    inst = make_instance(script_module)
    inst._song = MovingSong(track) if can_move else type("S", (), {"tracks": [track], "return_tracks": []})()
    return inst, track


def test_delete_device(script_module):
    inst, track = _chain_live(script_module, ["Operator", "Glue", "Limiter", "Rack"])
    out = inst._delete_device(0, 1)
    assert out["deleted"] == "Glue" and out["devices"] == ["Operator", "Limiter", "Rack"]
    with pytest.raises(IndexError):
        inst._delete_device(0, 7)


@pytest.mark.parametrize("src, dst, order", [
    (1, 3, ["Op", "EQ", "Comp", "Sat", "Lim"]),   # right: Live needs one more
    (4, 1, ["Op", "Lim", "Sat", "EQ", "Comp"]),   # left
    (0, 4, ["Sat", "EQ", "Comp", "Lim", "Op"]),   # to the very end
    (2, 2, ["Op", "Sat", "EQ", "Comp", "Lim"]),   # in place
])
def test_move_device_lands_where_asked(script_module, src, dst, order):
    inst, track = _chain_live(script_module, ["Op", "Sat", "EQ", "Comp", "Lim"])
    out = inst._move_device(0, src, dst)
    assert out["devices"] == order and [d.name for d in track.devices] == order


def test_move_device_checks(script_module):
    inst, _ = _chain_live(script_module, ["Op", "Lim"])
    with pytest.raises(IndexError, match="new_index goes from 0 to 1"):
        inst._move_device(0, 0, 2)
    old, _ = _chain_live(script_module, ["Op", "Lim"], can_move=False)
    with pytest.raises(RuntimeError, match="Live 11"):
        old._move_device(0, 0, 1)
    assert {"delete_device", "move_device"} <= set(script_module.SCRIPT_CAPABILITIES)


def test_chain_tools_show_the_new_order(conn):
    conn({"delete_device": {"deleted": "Glue", "on": "main track", "devices": ["Rack", "Limiter"]},
          "move_device": {"moved": "Limiter", "on": "main track", "devices": ["Rack", "Limiter"]}})
    assert call(tools.delete_device, 0, 1, track_type="master") == \
        "Deleted Glue from main track. Chain now: 0 Rack → 1 Limiter"
    assert call(tools.move_device, 0, 0, 1, track_type="master").endswith("0 Rack → 1 Limiter")


# ------------------------------------------- parameter filters (#85)

def _params():
    names = ["Device On", "Algorithm", "Ae Attack", "Ae Release", "Filter Freq", "Filter Res", "Fe Attack"]
    return {"track_index": 0, "device": {"name": "Operator", "parameters": [
        {"index": i, "name": n, "value": 0.5, "min": 0, "max": 1, "display": "v%d" % i}
        for i, n in enumerate(names)]}}


def test_parameters_by_names_query_and_brief(conn):
    conn({"get_device_parameters": _params()})
    by_name = json.loads(call(tools.get_device_parameters, 0, 0, names=["filter freq", "Ae "]))["device"]
    assert [p["name"] for p in by_name["parameters"]] == ["Ae Attack", "Ae Release", "Filter Freq"]
    assert by_name["parameters_shown"] == "3 of 7"
    q = json.loads(call(tools.get_device_parameters, 0, 0, query="attack", brief=True))["device"]
    assert q["parameters"] == [{"index": 2, "name": "Ae Attack", "display": "v2"},
                               {"index": 6, "name": "Fe Attack", "display": "v6"}]
    whole = json.loads(call(tools.get_device_parameters, 0, 0))["device"]
    assert len(whole["parameters"]) == 7 and "parameters_shown" not in whole
    assert "did you mean Filter Freq" in call(tools.get_device_parameters, 0, 0, names=["Filtre Freq"])
