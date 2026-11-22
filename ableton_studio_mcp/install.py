"""Copy the AbletonStudioMCP control surface into Ableton Live's User Library.

Live (10.1.13 and later) loads third-party control surfaces from
``<User Library>/Remote Scripts/<Name>/``. The User Library can be moved by
the user; its location is recorded in each Live version's ``Library.cfg``.

Usage:  ableton-studio-mcp install [--target DIR] [--list-targets]
                                   [--dry-run] [--remove-legacy]
"""

from __future__ import annotations

import argparse
import filecmp
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path


SURFACE_NAME = "AbletonStudioMCP"
# Folder name used by versions before 2.0 (and by the original ableton-mcp).
# Both listen on the same port, so only one may be selected in Live.
LEGACY_SURFACE_NAME = "AbletonMCP"

SCRIPT_SOURCE = Path(__file__).resolve().parent / "live_script" / SURFACE_NAME
_NOT_COPIED = shutil.ignore_patterns("__pycache__", "*.pyc")


# ── Where Live keeps things ──────────────────────────────────────────────────

def _preference_roots() -> list[Path]:
    home = Path.home()
    if sys.platform == "darwin":
        return [home / "Library" / "Preferences" / "Ableton"]
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
        return [Path(appdata) / "Ableton"]
    return [home / ".config" / "ableton", home / ".local" / "share" / "Ableton"]


def _version_tuple(folder: Path) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", folder.name))


def live_preference_dirs() -> list[Path]:
    """``…/Ableton/Live 12.x.y`` preference folders, newest Live first."""
    found = [d for root in _preference_roots() if root.is_dir()
             for d in root.glob("Live *") if d.is_dir()]
    return sorted(found, key=_version_tuple, reverse=True)


def user_library_from_config(cfg: Path) -> Path | None:
    """The User Library folder recorded in a ``Library.cfg``, if it exists.

    Live writes it as ``<UserLibrary><LibraryProject><ProjectPath Value=…/>
    <ProjectName Value=…/>``: the library is ProjectPath/ProjectName.
    """
    try:
        tree = ElementTree.parse(cfg)
    except (OSError, ElementTree.ParseError):
        return None
    for block in tree.getroot().iter("UserLibrary"):
        values = {el.tag: el.get("Value") for el in block.iter() if el.get("Value")}
        parent, name = values.get("ProjectPath"), values.get("ProjectName")
        if parent and name:
            library = Path(parent).expanduser() / name
            if library.is_dir():
                return library
    return None


def remote_scripts_dirs() -> list[Path]:
    """Candidate ``<User Library>/Remote Scripts`` folders, without duplicates.

    Libraries configured in Live come first; the default locations are added
    only when they exist, so nothing is created for a Live that isn't there.
    """
    libraries = [lib for d in live_preference_dirs()
                 if (lib := user_library_from_config(d / "Library.cfg"))]
    for default in (Path.home() / "Music" / "Ableton" / "User Library",
                    Path.home() / "Documents" / "Ableton" / "User Library"):
        if default.is_dir():
            libraries.append(default)
    unique: dict[str, Path] = {}
    for lib in libraries:
        unique.setdefault(str(lib.resolve()), lib / "Remote Scripts")
    return list(unique.values())


def script_version_in(folder: Path) -> str | None:
    """SCRIPT_VERSION declared by an installed control surface folder."""
    init = folder / "__init__.py"
    if not init.is_file():
        return None
    match = re.search(r'^SCRIPT_VERSION\s*=\s*["\']([^"\']+)', init.read_text(errors="replace"), re.M)
    return match.group(1) if match else "unknown"


# The version of the control surface shipped in this package.
SCRIPT_VERSION = script_version_in(SCRIPT_SOURCE)


# ── Installing ───────────────────────────────────────────────────────────────

@dataclass
class Outcome:
    destination: Path
    action: str          # "installed" | "updated" | "up to date" | "would install" | "failed"
    note: str = ""


def _same_tree(a: Path, b: Path) -> bool:
    cmp = filecmp.dircmp(a, b, ignore=["__pycache__"])
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return False
    return all(_same_tree(a / sub, b / sub) for sub in cmp.common_dirs)


def install_into(remote_scripts: Path, *, dry_run: bool = False,
                 source: Path = SCRIPT_SOURCE) -> Outcome:
    """Install (or refresh) the control surface under one Remote Scripts folder.

    The new copy is staged next to the destination and swapped in at the end,
    so Live never sees a half-copied script.
    """
    dest = remote_scripts / SURFACE_NAME
    existed = dest.is_dir()
    if existed and _same_tree(source, dest):
        return Outcome(dest, "up to date", f"version {SCRIPT_VERSION}")
    if dry_run:
        return Outcome(dest, "would update" if existed else "would install", f"version {SCRIPT_VERSION}")
    try:
        remote_scripts.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{SURFACE_NAME}-", dir=remote_scripts))
        new_copy = staging / SURFACE_NAME
        shutil.copytree(source, new_copy, ignore=_NOT_COPIED)
        if existed:
            shutil.rmtree(dest)
        new_copy.rename(dest)
        shutil.rmtree(staging, ignore_errors=True)
    except OSError as e:
        return Outcome(dest, "failed", str(e))
    return Outcome(dest, "updated" if existed else "installed", f"version {SCRIPT_VERSION}")


def legacy_installs(dirs: list[Path] | None = None) -> list[Path]:
    """Pre-2.0 ``AbletonMCP`` control surfaces still present in Remote Scripts."""
    dirs = remote_scripts_dirs() if dirs is None else dirs
    return [d / LEGACY_SURFACE_NAME for d in dirs if (d / LEGACY_SURFACE_NAME / "__init__.py").is_file()]


# ── Command line ─────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ableton-studio-mcp install",
        description=f"Install the {SURFACE_NAME} control surface into Ableton Live's User Library.")
    parser.add_argument("--target", metavar="DIR",
                        help="a Remote Scripts folder to install into, instead of the ones Live uses")
    parser.add_argument("--list-targets", action="store_true",
                        help="only show where the script would be installed")
    parser.add_argument("--dry-run", action="store_true", help="say what would change, change nothing")
    parser.add_argument("--remove-legacy", action="store_true",
                        help=f"delete the old '{LEGACY_SURFACE_NAME}' control surface folder(s)")
    args = parser.parse_args(argv)

    targets = [Path(args.target).expanduser()] if args.target else remote_scripts_dirs()
    if args.list_targets:
        for t in targets:
            print(t)
        return 0
    if not targets:
        print("No Ableton User Library found. Open Live once so it creates one, "
              "or pass --target '<User Library>/Remote Scripts'.")
        return 1

    outcomes = [install_into(t, dry_run=args.dry_run) for t in targets]
    for o in outcomes:
        print(f"{o.action}: {o.destination}" + (f" ({o.note})" if o.note else ""))

    old = legacy_installs(targets)
    for folder in old:
        if args.remove_legacy and not args.dry_run:
            shutil.rmtree(folder)
            print(f"removed old control surface: {folder}")
        else:
            print(f"old control surface still present: {folder}. It uses the same port: "
                  f"run with --remove-legacy to delete it")

    if all(o.action == "failed" for o in outcomes):
        return 1
    if any(o.action in ("installed", "updated") for o in outcomes):
        print(f"\nRestart Live, then choose {SURFACE_NAME} under "
              "Settings → Link, Tempo & MIDI → Control Surface.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
