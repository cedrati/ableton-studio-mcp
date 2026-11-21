"""The 2.0 control surface: browser search, input validation, snapshot."""

import types

import pytest

from test_remote_script_bridge import _load_script_module, make_instance


@pytest.fixture(scope="module")
def script_module():
    return _load_script_module()


class Item(object):
    def __init__(self, name, children=(), uri=None, loadable=False):
        self.name, self.children, self.uri = name, list(children), uri
        self.is_loadable, self.is_device = loadable, False


def browser_app(**sections):
    browser = types.SimpleNamespace(**sections)
    return types.SimpleNamespace(browser=browser)


# ── browser ──────────────────────────────────────────────────────────────────

def test_uri_search_walks_deep_and_caches(script_module):
    target = Item("Drift", uri="query:Synths#Drift", loadable=True)
    deep = Item("A", [Item("B", [Item("C", [target])])])
    walked = []

    class Spy(Item):
        @property
        def children(self):
            walked.append(self.name)
            return self._children

        @children.setter
        def children(self, value):
            self._children = value

    instruments = Spy("Instruments", [deep])
    inst = make_instance(script_module, browser_app(instruments=instruments, sounds=Item("Sounds")))
    assert inst._find_browser_item_by_uri(inst._browser(), "query:Synths#Drift") is target
    first = len(walked)
    assert inst._find_browser_item_by_uri(inst._browser(), "query:Synths#Drift") is target
    assert len(walked) == first                      # second lookup comes from the cache
    assert inst._find_browser_item_by_uri(inst._browser(), "query:nothing") is None


def test_uri_hint_searches_the_likely_section_first(script_module):
    plug = Item("Serum", uri="vst3:Serum")
    order = []

    class Section(Item):
        @property
        def children(self):
            order.append(self.name)
            return self._kids

        @children.setter
        def children(self, value):
            self._kids = value

    app = browser_app(instruments=Section("Instruments", [Item("x")]), plugins=Section("Plug-ins", [plug]))
    inst = make_instance(script_module, app)
    assert inst._find_browser_item_by_uri(inst._browser(), "vst3:Serum") is plug
    assert order[0] == "Plug-ins"


def test_items_at_path_and_its_errors(script_module):
    kits = Item("Kits", [Item("909 Core Kit", uri="kit:909", loadable=True)])
    inst = make_instance(script_module, browser_app(drums=Item("Drums", [kits])))
    folder = inst.get_browser_items_at_path("drums/kits")
    assert [i["name"] for i in folder["items"]] == ["909 Core Kit"] and folder["items"][0]["is_loadable"]
    assert "Unknown browser section 'synths'" in inst.get_browser_items_at_path("synths/x")["error"]
    assert inst.get_browser_items_at_path("drums/Nope")["error"] == "'Nope' not found in 'drums'"
    assert inst.get_browser_items_at_path("")["error"] == "Empty path"


def test_browser_missing_gives_a_clear_error(script_module):
    inst = make_instance(script_module, types.SimpleNamespace(browser=None))
    with pytest.raises(RuntimeError, match="browser is not available"):
        inst.get_browser_tree()


# ── validation ───────────────────────────────────────────────────────────────

class Clip(object):
    def __init__(self):
        self.name, self.length, self.is_midi_clip = "c", 4.0, True
        self.written = None

    def set_notes(self, notes):
        self.written = notes


@pytest.mark.parametrize("note, message", [
    ({"pitch": 128}, "pitch 128 is outside 0-127"),
    ({"pitch": 60, "duration": 0}, "duration > 0"),
    ({"pitch": 60, "start_time": -1}, "start_time >= 0"),
    ({"pitch": "high"}, "not a valid note"),
])
def test_bad_notes_are_refused_with_their_position(script_module, note, message):
    inst = make_instance(script_module)
    clip = Clip()
    inst._midi_clip = lambda t, c, loc: (clip, "session clip 0/0")
    with pytest.raises(ValueError, match=message):
        inst._add_notes_to_clip(0, 0, [{"pitch": 60}, note])
    assert clip.written is None                     # nothing half-written


def test_velocity_is_clamped_and_defaults_filled(script_module):
    inst = make_instance(script_module)
    clip = Clip()
    inst._midi_clip = lambda t, c, loc: (clip, "session clip 0/0")
    inst._clip_location_info = lambda c, loc: {}
    inst._add_notes_to_clip(0, 0, [{"pitch": 36, "velocity": 300}])
    assert clip.written == ((36, 0.0, 0.25, 127.0, False),)


def test_tempo_and_clip_length_and_track_index_are_checked(script_module):
    inst = make_instance(script_module)
    inst._song = types.SimpleNamespace(tempo=120.0, tracks=[])
    with pytest.raises(ValueError, match="20 to 999"):
        inst._set_tempo(5)
    with pytest.raises(ValueError, match="positive length"):
        inst._create_clip(0, 0, 0)
    with pytest.raises(IndexError, match="0..0, or -1"):
        inst._create_midi_track(3)
    with pytest.raises(ValueError, match="starts at beat 0"):
        inst._set_current_song_time(-4)


# ── snapshot ─────────────────────────────────────────────────────────────────

class Param(object):
    def __init__(self, name, value):
        self.name, self.value, self.min, self.max = name, value, 0.0, 1.0


class MidiClip(object):
    name, length, is_midi_clip, is_audio_clip = "beat", 4.0, True, False
    start_time, end_time = 0.0, 4.0

    @property
    def warp_markers(self):
        raise RuntimeError("Warp markers are only available for Audio Clips")

    def get_notes(self, start, pitch, span, pitch_span):
        return [(36, 0.0, 0.25, 100, False)]


def test_snapshot_of_a_midi_clip_does_not_touch_warp_markers(script_module):
    mixer = types.SimpleNamespace(volume=Param("v", 0.85), panning=Param("p", 0.0), sends=[])
    slot = types.SimpleNamespace(has_clip=True, clip=MidiClip())
    track = types.SimpleNamespace(name="Drums", has_audio_input=False, has_midi_input=True, mute=False,
                                  solo=False, can_be_armed=True, arm=False, mixer_device=mixer,
                                  clip_slots=[slot], devices=[], arrangement_clips=[MidiClip()])
    main = types.SimpleNamespace(name="Main", mixer_device=mixer, devices=[])
    song = types.SimpleNamespace(tempo=124.0, signature_numerator=4, signature_denominator=4,
                                 tracks=[track], return_tracks=[], master_track=main, scenes=[],
                                 cue_points=[], is_playing=False, current_song_time=0.0,
                                 song_length=16.0, loop=False, loop_start=0.0, loop_length=4.0)
    logged = []
    inst = make_instance(script_module)
    inst.log_message = logged.append
    inst._song = song
    snap = inst._get_session_snapshot()
    clip = snap["tracks"][0]["clip_slots"][0]["clip"]
    assert clip["note_count"] == 1 and "warp_markers" not in clip
    assert snap["tracks"][0]["arrangement_clips"][0]["start_time"] == 0.0
    assert snap["schema"].startswith("ableton_studio_mcp.snapshot/")
    assert logged == []                              # no log spam for MIDI clips
