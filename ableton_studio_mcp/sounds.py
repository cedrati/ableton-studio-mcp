"""Sounds the assistant designs, saved as plain JSON in the User Library.

Live's API cannot write device presets (.adv), so a designed sound is stored
as the device it uses plus every parameter value, in
``<User Library>/Ableton Studio MCP/Sounds/<Device>/<Name>.json``. Loading it
puts that device on a track and restores the values. To turn a sound into a
real Live preset, use the device's "Save Preset" button in Live.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .presets import libraries

FORMAT = "ableton-studio-mcp.sound/1"
FOLDER = Path("Ableton Studio MCP") / "Sounds"


def sounds_dir() -> Path:
    user = next((path for label, path in libraries() if label == "User Library"), None)
    if user is None:
        raise RuntimeError("No Ableton User Library found to keep sounds in")
    return user / FOLDER


def _safe(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .-")
    if not cleaned:
        raise ValueError("A sound needs a name")
    return cleaned[:120]


def save(name: str, device: str, device_class: str, parameters: list[dict],
         description: str = "", overwrite: bool = False) -> Path:
    path = sounds_dir() / _safe(device) / f"{_safe(name)}.json"
    if path.exists() and not overwrite:
        raise ValueError(f"A sound called '{name}' already exists for {device} (overwrite=true replaces it)")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "format": FORMAT, "name": name, "description": description,
        "device": device, "device_class": device_class,
        "saved": time.strftime("%Y-%m-%d %H:%M"),
        "parameters": [{"index": p["index"], "name": p["name"], "value": p["value"],
                        "display": p.get("display")} for p in parameters],
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)          # never leave a half-written sound behind
    return path


def _read(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != FORMAT:
        raise ValueError(f"{path.name} is not an Ableton Studio MCP sound")
    return data


def list_sounds(query: str = "", device: str = "") -> list[dict]:
    root = sounds_dir()
    if not root.is_dir():
        return []
    words = query.lower().split()
    out = []
    for path in sorted(root.rglob("*.json")):
        try:
            data = _read(path)
        except (OSError, ValueError):
            continue
        if device and data["device"].lower() != device.lower():
            continue
        text = f"{data['name']} {data['device']} {data.get('description', '')}".lower()
        if all(w in text for w in words):
            out.append({"name": data["name"], "device": data["device"],
                        "description": data.get("description", ""), "saved": data.get("saved"),
                        "path": str(path)})
    return out


def load(name: str) -> dict:
    """A saved sound by name (case-insensitive) or path."""
    candidate = Path(name).expanduser()
    if candidate.suffix == ".json" and candidate.is_file():
        return _read(candidate)
    matches = [s for s in list_sounds() if s["name"].lower() == name.lower()]
    if not matches:
        matches = list_sounds(name)
    if not matches:
        raise ValueError(f"No saved sound called '{name}'")
    if len(matches) > 1:
        raise ValueError(f"Several sounds match '{name}': "
                         + "; ".join(f"{m['name']} ({m['device']})" for m in matches[:6]))
    return _read(Path(matches[0]["path"]))
