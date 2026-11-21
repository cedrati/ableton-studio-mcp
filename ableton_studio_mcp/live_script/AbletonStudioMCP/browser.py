"""Live's browser: listing its folders, and loading an item onto a track."""
from __future__ import absolute_import, print_function, unicode_literals

from .constants import DEVICE_LOAD_SETTLE_TICKS, SAME_KIND_RELOAD_SETTLE_TICKS
from .deferred import Deferred
from .registry import command

# The browser's top-level sections, in Live's sidebar order, with the label
# shown to the assistant.
SECTIONS = (
    ("instruments", "Instruments"),
    ("sounds", "Sounds"),
    ("drums", "Drums"),
    ("audio_effects", "Audio Effects"),
    ("midi_effects", "MIDI Effects"),
    ("max_for_live", "Max for Live"),
    ("plugins", "Plug-ins"),
    ("clips", "Clips"),
    ("samples", "Samples"),
    ("packs", "Packs"),
    ("user_library", "User Library"),
    ("current_project", "Current Project"),
)
SECTION_LABELS = dict(SECTIONS)

# A URI usually tells which section holds the item; searching that section
# first saves walking the whole browser.
URI_HINTS = (
    ("plugins", ("vst:", "vst3:", "au:", "query:plugins", "plugin#")),
    ("max_for_live", ("query:max", "max for live", "maxforlive", "m4l")),
    ("user_library", ("query:user", "user library", "userlibrary")),
    ("packs", ("query:packs", "/packs/")),
    ("samples", ("query:samples", "sample:", "/samples/")),
    ("drums", ("query:drums", "/drums/")),
    ("instruments", ("query:instruments", "query:synths", "/instruments/")),
    ("sounds", ("query:sounds", "/sounds/")),
    ("audio_effects", ("query:audio", "audioeffects", "/audio_effects/")),
    ("midi_effects", ("query:midi", "midieffects", "/midi_effects/")),
)

TREE_DEPTH = 1          # levels shown below a section (get_browser_items_at_path goes further)
TREE_FANOUT = 64        # children shown per folder
SEARCH_DEPTH = 10       # how deep a search goes
SEARCH_BUDGET = 40000   # items looked at, at most, in one name search


def _children(item):
    try:
        return list(getattr(item, "children", None) or [])
    except RuntimeError:   # some Live folders refuse to list while loading
        return []


def _describe(item):
    return {
        "name": getattr(item, "name", "?"),
        "uri": getattr(item, "uri", None),
        "is_folder": bool(_children(item)),
        "is_device": bool(getattr(item, "is_device", False)),
        "is_loadable": bool(getattr(item, "is_loadable", False)),
    }


class BrowserCommands(object):

    # ── reaching the browser ────────────────────────────────────────────────

    def _browser(self):
        app = self.application()
        browser = getattr(app, "browser", None) if app is not None else None
        if browser is None:
            raise RuntimeError("Live's browser is not available yet (is the set still loading?)")
        return browser

    @staticmethod
    def _sections(browser):
        """(key, item) for every top-level section this Live has."""
        found = []
        for key, _label in SECTIONS:
            try:
                item = getattr(browser, key, None)
            except (AttributeError, RuntimeError):
                item = None
            if item is not None:
                found.append((key, item))
        return found

    # ── listing ─────────────────────────────────────────────────────────────

    @command("get_browser_tree")
    def get_browser_tree(self, category_type="all"):
        """The browser's folders, one level below each section, at most
        TREE_FANOUT children per folder; deeper or cut folders say has_more."""
        browser = self._browser()
        sections = self._sections(browser)
        wanted = (category_type or "all").lower()
        folders = [0]

        def node(item, depth):
            entry = _describe(item)
            kids = _children(item)
            if kids:
                folders[0] += 1
            if kids and depth >= TREE_DEPTH:
                entry["has_more"] = True
                return entry
            entry["children"] = [node(kid, depth + 1) for kid in kids[:TREE_FANOUT]]
            if len(kids) > TREE_FANOUT:
                entry["has_more"] = True
            return entry

        categories = []
        for key, item in sections:
            if wanted in ("all", key):
                entry = node(item, 0)
                entry["name"] = SECTION_LABELS.get(key, key)
                entry["path"] = key
                categories.append(entry)
        return {"type": category_type, "categories": categories, "total_folders": folders[0],
                "available_categories": [key for key, _ in sections]}

    @command("get_browser_items_at_path")
    def get_browser_items_at_path(self, path):
        """The content of one browser folder, "section/folder/subfolder"
        (names compared without case)."""
        browser = self._browser()
        sections = self._sections(browser)
        parts = [p for p in (path or "").split("/") if p]
        if not parts:
            return {"path": path, "error": "Empty path", "items": [],
                    "available_categories": [key for key, _ in sections]}
        root = parts[0].lower()
        current = next((item for key, item in sections
                        if root in (key, SECTION_LABELS.get(key, "").lower())), None)
        if current is None:
            return {"path": path, "error": "Unknown browser section '%s'" % parts[0], "items": [],
                    "available_categories": [key for key, _ in sections]}
        for depth, part in enumerate(parts[1:], start=1):
            match = next((kid for kid in _children(current)
                          if getattr(kid, "name", "").lower() == part.lower()), None)
            if match is None:
                return {"path": path, "items": [],
                        "error": "'%s' not found in '%s'" % (part, "/".join(parts[:depth]))}
            current = match
        folder = _describe(current)
        folder.update({"path": path, "items": [_describe(kid) for kid in _children(current)]})
        return folder

    @command("find_browser_items")
    def _find_browser_items(self, name, sections=None, limit=5):
        """Loadable items named ``name`` (with or without extension, any
        case), searched breadth-first in the given sections (all by default)."""
        wanted = str(name).lower()
        browser = self._browser()
        chosen = [(k, i) for k, i in self._sections(browser) if not sections or k in sections]
        found, visited = [], 0
        queue = [(item, SECTION_LABELS.get(key, key), 0) for key, item in chosen]
        while queue and len(found) < limit and visited < SEARCH_BUDGET:
            item, path, depth = queue.pop(0)
            visited += 1
            label = getattr(item, "name", "")
            stem = label.rsplit(".", 1)[0] if "." in label else label
            if getattr(item, "is_loadable", False) and wanted in (label.lower(), stem.lower()):
                found.append({"name": label, "uri": getattr(item, "uri", None), "path": path})
            if depth < SEARCH_DEPTH:
                queue.extend((kid, path + "/" + getattr(kid, "name", "?"), depth + 1) for kid in _children(item))
        return {"items": found, "visited": visited, "complete": not queue}

    # ── finding by URI ──────────────────────────────────────────────────────

    def _find_browser_item_by_uri(self, browser, uri):
        """The browser item with this URI, or None. Results are cached:
        walking the whole browser takes seconds."""
        cache = self.__dict__.setdefault("_uri_cache", {})
        if uri not in cache:
            found = self._search_uri(browser, uri)
            if found is None:
                return None
            cache[uri] = found
        return cache[uri]

    def _search_uri(self, browser, uri):
        lowered = (uri or "").lower()
        sections = self._sections(browser)
        hinted = [key for key, markers in URI_HINTS if any(m in lowered for m in markers)]
        sections.sort(key=lambda pair: 0 if pair[0] in hinted[:1] else 1)
        for _key, section in sections:
            stack = [(section, 0)]
            while stack:   # depth-first, without recursion
                item, depth = stack.pop()
                if getattr(item, "uri", None) == uri:
                    return item
                if depth < SEARCH_DEPTH:
                    stack.extend((kid, depth + 1) for kid in reversed(_children(item)))
        return None

    # ── loading ─────────────────────────────────────────────────────────────

    @command("load_browser_item")
    def _load_browser_item(self, track_index, item_uri, track_type="track"):
        """Load a browser item (by URI) onto a track, a return track or the
        main track. Live loads onto the selected track, so the target is
        selected first.

        The chain only changes on a later tick, so the reply waits for it.
        Loading a device identical to one already there (Drift onto Drift)
        never changes the chain: Live resets that device in place about a
        second later, which only shows in its parameter values.
        """
        track, _ = self._resolve_track(track_index, track_type)
        browser = self._browser()
        item = self._find_browser_item_by_uri(browser, item_uri)
        if item is None:
            raise ValueError("Nothing in Live's browser has the URI '%s'" % item_uri)

        self._song.view.selected_track = track
        before = self._device_signature(track)
        name = item.name
        same_kind = any(existing == name for (_, existing) in before)
        params_before = self._param_fingerprint(track) if same_kind else None
        self._note_browser_load()     # the load splits the open undo step (see undo.py)
        browser.load_item(item)

        def chain_changed():
            return self._device_signature(track) != before

        def reset_in_place():
            return same_kind and self._param_fingerprint(track) != params_before

        def start(resolve, reject):
            def report(settled):
                after = self._device_signature(track)
                in_place = same_kind and not chain_changed()
                if in_place:
                    added = [name] if settled else []
                else:
                    added = [n for (key, n) in after if (key, n) not in before]
                resolve({
                    "loaded": True, "item_name": name, "uri": item_uri, "track_name": track.name,
                    "devices_before": [n for (_, n) in before],
                    "devices_after": [n for (_, n) in after],
                    "new_devices": added, "in_place": in_place, "settled": settled,
                })

            self._poll_until(lambda: chain_changed() or reset_in_place(),
                             on_ready=lambda: report(True), on_timeout=lambda: report(False),
                             reject=reject,
                             # Parameters already at their defaults never move:
                             # don't wait the full budget for that case.
                             max_ticks=SAME_KIND_RELOAD_SETTLE_TICKS if same_kind
                             else DEVICE_LOAD_SETTLE_TICKS)

        return Deferred(start)

    @staticmethod
    def _device_signature(track):
        """(identity, name) of each device on the track, in chain order."""
        return [((getattr(d, "_live_ptr", None), d.class_name), d.name) for d in track.devices]

    @staticmethod
    def _param_fingerprint(track):
        """Every parameter value of every device on the track."""
        return [tuple(p.value for p in d.parameters) for d in track.devices]
