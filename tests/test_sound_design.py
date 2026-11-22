"""Sound design: musical values -> internal values, presets on disk, tools."""

import gzip
import json
import math

import pytest

from test_remote_script_bridge import _load_script_module, make_instance


@pytest.fixture(scope="module")
def script_module():
    return _load_script_module()


class Freq(object):
    """Like Drift's LP Freq: 0–1 internally, 20 Hz … 20 kHz exponential.
    Like Live, asking a continuous parameter for value_items raises."""
    name, min, max, is_quantized = "LP Freq", 0.0, 1.0, False

    @property
    def value_items(self):
        raise RuntimeError("Only quantized parameters have value items")

    def __init__(self):
        self.value = 1.0

    def str_for_value(self, v):
        hz = 20 * (1000 ** v)
        return "%.1f kHz" % (hz / 1000) if hz >= 1000 else "%d Hz" % round(hz)


class Gain(object):
    """0–1 internally, -inf dB at 0, up to +6 dB."""
    name, min, max, is_quantized, value_items = "Volume", 0.0, 1.0, False, ()
    value = 0.85

    def str_for_value(self, v):
        return "-inf dB" if v <= 0 else "%.1f dB" % (6 + 40 * math.log10(v))


class Shape(object):
    name, min, max, is_quantized = "Filter Type", 0.0, 3.0, True
    value_items = ("Lowpass", "Highpass", "Bandpass", "Notch")
    value = 0.0

    def str_for_value(self, v):
        return self.value_items[int(v)]


class Rate(object):
    """A continuous parameter whose display is text ("1/16")."""
    name, min, max, is_quantized, value_items = "Rate", 0.0, 1.0, False, ()
    value = 0.0
    labels = ("1/32", "1/16", "1/8", "1/4", "1/2", "1")

    def str_for_value(self, v):
        return self.labels[min(int(v * len(self.labels)), len(self.labels) - 1)]


@pytest.fixture
def values(script_module):
    return script_module.values


@pytest.mark.parametrize("text, expected", [
    ("800 Hz", (800.0, "hz")), ("2.2 kHz", (2200.0, "hz")), ("5 ms", (0.005, "s")),
    ("-6 dB", (-6.0, "db")), ("-inf dB", (float("-inf"), "db")), ("30 %", (30.0, "%")),
    ("+7 st", (7.0, "st")), ("0,5", (0.5, "")), ("Bell", None), ("1/16", None),
])
def test_parse_quantity(values, text, expected):
    assert values.parse_quantity(text) == expected


def test_frequency_found_by_its_display(values):
    p = Freq()
    v = values.resolve_value(p, "800 Hz")
    assert abs(20 * (1000 ** v) - 800) < 5
    v = values.resolve_value(p, "2.5 kHz")
    assert p.str_for_value(v) == "2.5 kHz"


def test_decibels_including_silence(values):
    p = Gain()
    assert p.str_for_value(values.resolve_value(p, "-12 dB")) == "-12.0 dB"
    assert values.resolve_value(p, "-inf dB") == 0.0


def test_named_settings_and_text_displays(values):
    assert values.resolve_value(Shape(), "bandpass") == 2.0
    assert Rate().str_for_value(values.resolve_value(Rate(), "1/8")) == "1/8"
    with pytest.raises(ValueError, match="no setting 'Comb'.*Lowpass"):
        values.resolve_value(Shape(), "Comb")


def test_out_of_range_and_wrong_unit_are_refused(values):
    with pytest.raises(ValueError, match="can't be 50 kHz"):
        values.resolve_value(Freq(), "50 kHz")
    with pytest.raises(ValueError, match="not shown in db"):
        values.resolve_value(Freq(), "-6 dB")
    with pytest.raises(ValueError, match="takes 0.0 to 1.0"):
        values.resolve_value(Freq(), 3)


def test_set_device_parameters_checks_everything_first(script_module):
    import types
    inst = make_instance(script_module)
    freq, shape = Freq(), Shape()
    device = types.SimpleNamespace(name="Drift", parameters=[freq, shape])
    inst._device_on = lambda t, d, k: device
    out = inst._set_device_parameters(0, 0, {"lp freq": "1.0 kHz", "type": "Highpass"})
    assert [c["now"] for c in out["changes"]] == ["1.0 kHz", "Highpass"]
    before = (freq.value, shape.value)
    with pytest.raises(ValueError, match="No parameter 'Cutoff'"):
        inst._set_device_parameters(0, 0, {"Type": "Notch", "Cutoff": "1 kHz"})
    assert (freq.value, shape.value) == before          # nothing half-applied


# ── presets on disk ──────────────────────────────────────────────────────────

ADV = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton><Drift>
  <On><Manual Value="true"/><AutomationTarget Id="1"/></On>
  <Filter_Frequency><Manual Value="{freq}"/><AutomationTarget Id="2"/></Filter_Frequency>
  <Envelope1_Attack><Manual Value="0.001"/><AutomationTarget Id="3"/></Envelope1_Attack>
  <UserName Value="{name}"/>
</Drift></Ableton>"""


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as f:
        f.write(text.encode())


@pytest.fixture
def library(tmp_path, monkeypatch):
    from ableton_studio_mcp import presets
    core = tmp_path / "Core Library"
    _write(core / "Defaults" / "Instruments" / "Drift.adv", ADV.format(freq=19999.99, name=""))
    _write(core / "Devices" / "Instruments" / "Drift" / "Bass" / "Dark Sub.adv", ADV.format(freq=180, name="Dark Sub"))
    _write(core / "Devices" / "Instruments" / "Drift" / "Pads" / "Wide Pad.adv", ADV.format(freq=2400, name=""))
    monkeypatch.setattr(presets, "_core_libraries", lambda: [core])
    monkeypatch.setattr(presets, "libraries", lambda: [("Core Library", core)])
    presets.index.cache_clear()
    presets._defaults.cache_clear()
    yield presets
    presets.index.cache_clear()
    presets._defaults.cache_clear()


def test_index_and_search(library):
    names = [p["name"] for p in library.find_presets("bass", device="Drift")]
    assert names == ["Dark Sub"]
    sub = library.find_presets("dark")[0]
    assert (sub["kind"], sub["device"], sub["category"]) == ("instrument", "Drift", "Bass")


def test_read_shows_what_differs_from_the_default(library):
    info = library.read_preset(library.resolve("Dark Sub"))
    assert info["device"] == "Drift"
    assert info["parameters"] == {"Filter Frequency": 180}         # attack equals the default
    full = library.read_preset(library.resolve("Dark Sub"), detail="full")
    assert full["parameters"]["Envelope 1 Attack"] == 0.001


def test_resolve_reports_ambiguity(library):
    with pytest.raises(ValueError, match="No preset matches"):
        library.resolve("trumpet")


def test_find_presets_tool(library):
    from ableton_studio_mcp import tools
    out = json.loads(tools.find_presets("pad"))
    assert out["presets"][0]["name"] == "Wide Pad"


class Plain(object):
    """Like Drift's LP Res: a plain number from 0 to about 1."""
    name, min, max, is_quantized, value_items = "LP Res", 0.0, 1.0, False, ()
    value = 0.0

    def str_for_value(self, v):
        return "%.2f " % (v * 1.01)


def test_percent_on_a_plain_zero_to_one_parameter(values):
    p = Plain()
    assert p.str_for_value(values.resolve_value(p, "35 %")) == "0.35 "
    assert p.str_for_value(values.resolve_value(p, "0.5")) == "0.50 "


# ── the assistant's own sounds ───────────────────────────────────────────────

@pytest.fixture
def sound_lib(tmp_path, monkeypatch):
    from ableton_studio_mcp import sounds
    monkeypatch.setattr(sounds, "libraries", lambda: [("User Library", tmp_path / "User Library")])
    return sounds


def test_save_list_load_sound(sound_lib):
    params = [{"index": 1, "name": "LP Freq", "value": 0.42, "display": "800 Hz"}]
    path = sound_lib.save("Rolling Sub", "Drift", "Drift", params, "deep and round")
    assert path.parent.name == "Drift" and path.name == "Rolling Sub.json"
    with pytest.raises(ValueError, match="already exists"):
        sound_lib.save("Rolling Sub", "Drift", "Drift", params)
    assert [s["name"] for s in sound_lib.list_sounds("deep")] == ["Rolling Sub"]
    data = sound_lib.load("rolling sub")
    assert data["parameters"][0]["display"] == "800 Hz" and data["device_class"] == "Drift"
    with pytest.raises(ValueError, match="No saved sound"):
        sound_lib.load("Nothing")
    with pytest.raises(ValueError, match="needs a name"):
        sound_lib.save("///", "Drift", "Drift", params)


def test_apply_device_state_matches_by_index_then_name(script_module):
    import types
    inst = make_instance(script_module)
    freq, shape = Freq(), Shape()
    device = types.SimpleNamespace(name="Drift", parameters=[shape, freq])   # order changed
    inst._device_on = lambda t, d, k: device
    out = inst._apply_device_state(0, 0, [
        {"index": 0, "name": "LP Freq", "value": 0.25},      # index points elsewhere: found by name
        {"index": 0, "name": "Filter Type", "value": 9.0},   # clamped to the range
        {"index": 5, "name": "Gone", "value": 1.0},
    ])
    assert freq.value == 0.25 and shape.value == 3.0
    assert out["applied"] == 2 and out["skipped"] == ["Gone"]


# ── recipes and auditioning ──────────────────────────────────────────────────

class Recorder(object):
    def __init__(self, replies):
        self.sent, self.replies = [], replies

    def call(self, name, params=None):
        self.sent.append((name, params or {}))
        reply = self.replies.get(name, {})
        if isinstance(reply, Exception):
            raise reply
        return reply(params or {}) if callable(reply) else reply


@pytest.fixture
def fake_live(monkeypatch):
    from ableton_studio_mcp import live

    def make(replies):
        r = Recorder(replies)
        monkeypatch.setattr(live, "client", lambda: r)
        monkeypatch.setattr(live, "require", lambda name: None)
        return r
    return make


def test_every_recipe_is_complete():
    from ableton_studio_mcp import recipes
    for name, r in recipes.RECIPES.items():
        assert {"device", "uri", "role", "values", "play", "listen"} <= set(r), name
        assert r["role"] in recipes.PHRASES, name
    with pytest.raises(ValueError, match="No recipe 'banjo'"):
        recipes.recipe("banjo")
    assert recipes.recipe("Acid Bass") is recipes.RECIPES["acid_bass"]


def test_design_sound_applies_recipe_then_tweaks(fake_live):
    from ableton_studio_mcp import tools
    r = fake_live({"load_browser_item": {"loaded": True},
                   "get_track_info": {"devices": [{"index": 0, "name": "Drift", "class_display_name": "Drift"}]},
                   "set_device_parameters": lambda p: {"changes": [{"name": k, "now": v} for k, v in p["values"].items()]}})
    out = json.loads(tools.design_sound(2, "acid_bass", {"LP Freq": "500 Hz"}))
    sent = dict(r.sent)
    assert sent["load_browser_item"]["item_uri"] == "query:Synths#Drift"
    assert sent["set_device_parameters"]["values"]["LP Freq"] == "500 Hz"      # tweak wins
    assert sent["set_device_parameters"]["values"]["LP Res"] == "0.75"
    assert out["device_index"] == 0 and out["set"]["Glide Time"] == "60 ms"


def test_audition_cleans_up_even_when_listening_fails(fake_live, monkeypatch):
    from ableton_studio_mcp import tools
    from ableton_studio_mcp.tools import listening

    def broken(*a, **k):
        raise RuntimeError("Live stopped")
    monkeypatch.setattr(listening.listen_to_arrangement, "__wrapped__", broken)
    r = fake_live({"get_track_info": {"name": "Bass", "clip_slots": [{"index": 0, "has_clip": True},
                                                                      {"index": 1, "has_clip": False}]},
                   "get_session_info": {"song_length": 286.0},
                   "get_arrangement_clips": {"clips": [{"start_time": 32.0}, {"start_time": 292.0}]}})
    assert "failed" in tools.audition_sound(1, role="bass")
    names = [n for n, _ in r.sent]
    assert ("create_clip", {"track_index": 1, "clip_index": 1, "length": 4.0}) in r.sent
    dup = dict(r.sent)["duplicate_session_clip_to_arrangement"]
    assert dup["destination_time"] == 292.0       # the song ends inside bar 72: start of bar 74
    assert ("delete_arrangement_clip", {"track_index": 1, "clip_index": 1}) in r.sent
    assert names[-1] == "delete_clip"


# ------------------------------------------------ ratios (#86)

class Ratio(object):
    """Like Compressor's Ratio: 0–1 internally, shown '2.00 : 1' … 'inf : 1'."""
    name, min, max, is_quantized, value_items = "Ratio", 0.0, 1.0, False, ()
    value = 0.3

    def str_for_value(self, v):
        if v >= 0.999:
            return "inf : 1"
        r = 1 + 99 * v ** 3
        return "%.1f : 1" % r if r >= 10 else "%.2f : 1" % r


@pytest.mark.parametrize("text, expected", [
    ("8.00 : 1", (8.0, "ratio")), ("8:1", (8.0, "ratio")), ("inf : 1", (float("inf"), "ratio")),
    ("∞:1", (float("inf"), "ratio")), ("2,5 : 1", (2.5, "ratio")),
])
def test_parse_ratio(values, text, expected):
    assert values.parse_quantity(text) == expected


@pytest.mark.parametrize("wanted, shown", [
    ("8", "8.00 : 1"), (8, "8.00 : 1"), ("8:1", "8.00 : 1"), ("8.00 : 1", "8.00 : 1"),
    ("10.00 : 1", "10.0 : 1"), ("inf : 1", "inf : 1"), ("1.5:1", "1.50 : 1"),
])
def test_ratio_from_what_producers_say(values, wanted, shown):
    p = Ratio()
    assert p.str_for_value(values.resolve_value(p, wanted)) == shown


def test_plain_numbers_in_range_stay_internal(values):
    assert values.resolve_value(Ratio(), 0.5) == 0.5       # backward compatible
    with pytest.raises(ValueError, match="takes 0.0 to 1.0"):
        values.resolve_value(Freq(), 8)                     # not a ratio: still refused
