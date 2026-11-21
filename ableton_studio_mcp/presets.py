"""Live's device presets on disk: finding them and reading what they do.

Presets are gzipped XML: ``.adv`` holds one device, ``.adg`` a rack (macros,
chains, the devices inside each chain). They live in Live's Core Library
(inside the application), in installed packs and in the User Library.

Reading a preset compares it with the device's default preset (Live ships one
per device in ``Core Library/Defaults``), so the result shows what gives the
sound its character rather than every parameter of the device. Values are
the ones stored in the file, in the device's own units (Hz, seconds, dB,
percent or 0–1 depending on the parameter).

Nothing here needs Live to be running.
"""

from __future__ import annotations

import gzip
import os
import re
import sys
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .install import remote_scripts_dirs

PRESET_SUFFIXES = (".adv", ".adg")


# ── where presets are ────────────────────────────────────────────────────────

def _core_libraries() -> list[Path]:
    if sys.platform == "darwin":
        apps = sorted(Path("/Applications").glob("Ableton Live*.app"), reverse=True)
        return [a / "Contents" / "App-Resources" / "Core Library" for a in apps
                if (a / "Contents" / "App-Resources" / "Core Library").is_dir()]
    if sys.platform == "win32":
        base = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Ableton"
        return sorted((p for p in base.glob("Live */Resources/Core Library") if p.is_dir()), reverse=True)
    return []


def _pack_folders() -> list[Path]:
    home = Path.home()
    return [p for p in (home / "Music" / "Ableton" / "Factory Packs",
                        home / "Documents" / "Ableton" / "Factory Packs") if p.is_dir()]


def libraries() -> list[tuple[str, Path]]:
    """(label, folder) for every preset library found, newest Live first."""
    found: list[tuple[str, Path]] = []
    cores = _core_libraries()
    if cores:
        found.append(("Core Library", cores[0]))
    for scripts in remote_scripts_dirs():
        found.append(("User Library", scripts.parent))
    for packs in _pack_folders():
        found += [(f"Pack: {p.name}", p) for p in sorted(packs.iterdir()) if p.is_dir()]
    seen, unique = set(), []
    for label, path in found:
        if str(path) not in seen:
            seen.add(str(path))
            unique.append((label, path))
    return unique


@dataclass(frozen=True)
class PresetFile:
    path: Path
    library: str
    name: str
    kind: str        # instrument | audio_effect | midi_effect | rack | drum_rack | other
    device: str      # device folder ("Drift", "Reverb") or rack type
    category: str    # first folder below the device ("Bass", "Pads"), may be ""

    def as_dict(self) -> dict:
        return {"name": self.name, "device": self.device, "category": self.category,
                "kind": self.kind, "library": self.library, "path": str(self.path)}


_KIND_FOLDERS = {"instruments": "instrument", "audio effects": "audio_effect",
                 "midi effects": "midi_effect", "instrument racks": "rack", "audio effect racks": "rack",
                 "midi effect racks": "rack", "drum racks": "drum_rack", "drums": "drum_rack"}


def _describe_path(path: Path, root: Path, library: str) -> PresetFile:
    parts = [p for p in path.relative_to(root).parts[:-1]]
    lowered = [p.lower() for p in parts]
    kind, device, category = "other", "", ""
    if "devices" in lowered:
        i = lowered.index("devices")
        rest = parts[i + 1:]
        kind = _KIND_FOLDERS.get(rest[0].lower(), "other") if rest else "other"
        device = rest[1] if len(rest) > 1 else ""
        category = rest[2] if len(rest) > 2 else ""
    elif "racks" in lowered or any(p in _KIND_FOLDERS for p in lowered):
        j = next(i for i, p in enumerate(lowered) if p in _KIND_FOLDERS or p == "racks")
        rest = parts[j:]
        label = rest[1] if lowered[j] == "racks" and len(rest) > 1 else rest[0]
        kind = _KIND_FOLDERS.get(label.lower(), "rack")
        device = label
        category = rest[-1] if len(rest) > 2 else ""
    if path.suffix.lower() == ".adg" and kind not in ("rack", "drum_rack"):
        kind = "drum_rack" if "drum" in str(path).lower() else "rack"
    return PresetFile(path, library, path.stem, kind, device, category)


@lru_cache(maxsize=1)
def index() -> tuple[PresetFile, ...]:
    """Every preset file in every library (cached; a few thousand files)."""
    files = []
    for library, root in libraries():
        for dirpath, _dirs, names in os.walk(root):
            for name in names:
                if name.lower().endswith(PRESET_SUFFIXES):
                    files.append(_describe_path(Path(dirpath) / name, root, library))
    return tuple(files)


def find_presets(query: str = "", device: str = "", kind: str = "", library: str = "",
                 limit: int = 50) -> list[dict]:
    """Presets whose name, device, category or library contain every word of
    ``query`` (case-insensitive), optionally for one device, kind or library."""
    words = [w for w in re.split(r"\s+", query.lower()) if w]
    out = []
    for p in index():
        if device and device.lower() != p.device.lower():
            continue
        if kind and kind.lower() != p.kind:
            continue
        if library and library.lower() not in p.library.lower():
            continue
        haystack = f"{p.name} {p.device} {p.category} {p.library}".lower()
        if all(w in haystack for w in words):
            out.append(p.as_dict())
            if len(out) >= limit:
                break
    return out


# ── reading ──────────────────────────────────────────────────────────────────

def _load(path: Path) -> ElementTree.Element:
    with gzip.open(path) as f:
        return ElementTree.fromstring(f.read())


def _value(raw: str) -> Any:
    if raw in ("true", "false"):
        return raw == "true"
    try:
        number = float(raw)
    except ValueError:
        return raw
    return int(number) if number.is_integer() and abs(number) < 1e9 else round(number, 6)


def _label(path: str) -> str:
    """'Operator.0/Envelope/AttackTime' -> 'Operator 1 › Envelope › Attack Time'."""
    parts = []
    for part in path.split("/"):
        part = re.sub(r"\.(\d+)$", lambda m: f" {int(m.group(1)) + 1}", part)
        part = part.replace("_", " ")
        part = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", part)
        part = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", part)
        parts.append(part.strip())
    return " › ".join(parts)


def device_parameters(device: ElementTree.Element) -> dict[str, Any]:
    """Automatable parameters of one device element: {xml path: value}.
    A parameter is an element with a <Manual> value and an automation target."""
    params: dict[str, Any] = {}

    def walk(element: ElementTree.Element, trail: list[str]) -> None:
        manual = element.find("Manual")
        if manual is not None and manual.get("Value") is not None and element.find("AutomationTarget") is not None:
            params["/".join(trail)] = _value(manual.get("Value"))
        for child in element:
            if child.tag in ("Branches", "ReturnBranches", "DeviceChain") or child.tag.startswith("MacroControls"):
                continue      # nested chains belong to their devices; macros are listed apart
            walk(child, trail + [child.tag])

    for child in device:
        if child.tag in ("Branches", "ReturnBranches", "DeviceChain") or child.tag.startswith("MacroControls"):
            continue
        walk(child, [child.tag])
    return params


def _samples(device: ElementTree.Element) -> list[str]:
    names = []
    for ref in device.iter("SampleRef"):
        path = ref.find("FileRef/Path") or ref.find("FileRef/RelativePath")
        if path is not None and path.get("Value"):
            names.append(Path(path.get("Value")).name)
    return sorted(set(names))


@lru_cache(maxsize=1)
def _defaults() -> dict[str, tuple[str, dict[str, Any]]]:
    """Device XML tag -> (friendly name, default parameters), from Live's
    Core Library/Defaults (e.g. 'InstrumentVector' -> 'Wavetable')."""
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for core in _core_libraries()[:1]:
        for path in sorted((core / "Defaults").rglob("*.adv")):
            try:
                device = _load(path)[0]
            except (OSError, ElementTree.ParseError, IndexError):
                continue
            out.setdefault(device.tag, (path.stem, device_parameters(device)))
    return out


RACK_NAMES = {"InstrumentGroupDevice": "Instrument Rack", "AudioEffectGroupDevice": "Audio Effect Rack",
              "MidiEffectGroupDevice": "MIDI Effect Rack", "DrumGroupDevice": "Drum Rack"}


def device_name(tag: str) -> str:
    return RACK_NAMES.get(tag) or _defaults().get(tag, (tag, {}))[0]


def describe_device(device: ElementTree.Element, detail: str = "changes") -> dict:
    """What one device element does: its name, and its parameters (only those
    that differ from the device's default preset unless detail='full')."""
    params = device_parameters(device)
    name, defaults = _defaults().get(device.tag, (device_name(device.tag), {}))
    if device.tag in RACK_NAMES:          # a rack's sound is in its chains and macros
        params = {k: v for k, v in params.items() if v not in (0, False) and k != "On"}
    if detail == "full" or not defaults:
        shown = params
        basis = "all parameters" if not defaults else "all parameters (full)"
    else:
        shown = {k: v for k, v in params.items() if defaults.get(k) != v and k != "On"}
        basis = f"differences from the default {name}"
    info: dict[str, Any] = {
        "device": name, "xml_tag": device.tag, "on": params.get("On", True),
        "parameters_shown": basis,
        "parameters": {_label(k): v for k, v in shown.items()},
        "parameter_count": len(params),
    }
    user_name = device.find("UserName")
    if user_name is not None and user_name.get("Value"):
        info["name_in_rack"] = user_name.get("Value")
    samples = _samples(device)
    if samples:
        info["samples"] = samples
    if device.tag.endswith("GroupDevice") or device.tag == "DrumGroupDevice":
        info["macros"] = _macros(device)
    return info


def _macros(rack: ElementTree.Element) -> list[dict]:
    macros = []
    for i in range(16):
        control = rack.find(f"MacroControls.{i}")
        if control is None:
            break
        name = rack.find(f"MacroDisplayNames.{i}")
        manual = control.find("Manual")
        label = name.get("Value") if name is not None else ""
        value = _value(manual.get("Value")) if manual is not None else None
        if label or value:
            macros.append({"index": i + 1, "name": label or f"Macro {i + 1}", "value": value})
    return macros


def _chains(preset: ElementTree.Element, detail: str) -> list[dict]:
    chains = []
    for tag in ("BranchPresets", "ReturnBranchPresets"):
        group = preset.find(tag)
        if group is None:
            continue
        for branch in group:
            name = branch.find("Name")
            devices = []
            for device_preset in branch.iter("DevicePresets"):
                for item in device_preset:
                    devices.append(_describe_preset_element(item, detail))
                break
            entry = {"name": name.get("Value") if name is not None else "", "devices": devices}
            if tag == "ReturnBranchPresets":
                entry["return_chain"] = True
            zone = branch.find("ReceivingNote") if branch.find("ReceivingNote") is not None else None
            if zone is not None and zone.get("Value"):
                entry["note"] = int(zone.get("Value"))
            chains.append(entry)
    return chains


def _describe_preset_element(element: ElementTree.Element, detail: str) -> dict:
    """A <...Preset> element inside a rack: a device, or a nested rack."""
    holder = element.find("Device")
    device = list(holder)[0] if holder is not None and len(holder) else element
    info = describe_device(device, detail)
    if element.find("BranchPresets") is not None:
        info["chains"] = _chains(element, detail)
    return info


def read_preset(path: str | Path, detail: str = "changes") -> dict:
    """Describe a .adv or .adg preset file."""
    path = Path(path).expanduser()
    if path.suffix.lower() not in PRESET_SUFFIXES:
        raise ValueError(f"Not a device or rack preset (.adv / .adg): {path.name}")
    root = _load(path)
    if not len(root):
        raise ValueError(f"Empty preset: {path.name}")
    top = root[0]
    if top.tag == "GroupDevicePreset":
        info = _describe_preset_element(top, detail)
    else:
        info = describe_device(top, detail)
    info.update({"preset": path.stem, "file": str(path), "type": "rack" if path.suffix.lower() == ".adg" else "device"})
    return info


def resolve(name_or_path: str) -> Path:
    """A preset path from a path, or from a preset name found in the libraries."""
    candidate = Path(name_or_path).expanduser()
    if candidate.suffix.lower() in PRESET_SUFFIXES and candidate.is_file():
        return candidate
    wanted = Path(name_or_path).stem.lower()
    exact = [p for p in index() if p.name.lower() == wanted]
    if exact:
        return exact[0].path
    matches = find_presets(name_or_path, limit=6)
    if len(matches) == 1:
        return Path(matches[0]["path"])
    if not matches:
        raise ValueError(f"No preset matches '{name_or_path}'")
    raise ValueError(f"Several presets match '{name_or_path}': "
                     + "; ".join(f"{m['name']} ({m['device'] or m['kind']}, {m['library']})" for m in matches))
