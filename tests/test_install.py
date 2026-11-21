"""`ableton-studio-mcp install`: finding the User Library and copying the script."""

import pytest

import ableton_studio_mcp.install as install


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake home with Live 12.4.7 preferences and a relocated User Library."""
    monkeypatch.setattr(install.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(install.sys, "platform", "darwin")
    prefs = tmp_path / "Library" / "Preferences" / "Ableton"
    for version in ("Live 12.3.1", "Live 12.4.7"):
        (prefs / version).mkdir(parents=True)
    library = tmp_path / "Studio" / "My Library"
    library.mkdir(parents=True)
    (prefs / "Live 12.4.7" / "Library.cfg").write_text(
        '<?xml version="1.0"?><Ableton><UserLibrary><LibraryProject>'
        f'<ProjectPath Value="{library.parent}"/><ProjectName Value="My Library"/>'
        '</LibraryProject></UserLibrary></Ableton>')
    return tmp_path


@pytest.fixture
def source(tmp_path):
    src = tmp_path / "src" / install.SURFACE_NAME
    src.mkdir(parents=True)
    (src / "__init__.py").write_text(f'SCRIPT_VERSION = "{install.SCRIPT_VERSION}"\n')
    (src / "commands.py").write_text("X = 1\n")
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "junk.pyc").write_bytes(b"x")
    return src


def test_preference_dirs_newest_first(home):
    assert [d.name for d in install.live_preference_dirs()] == ["Live 12.4.7", "Live 12.3.1"]


def test_configured_library_first_then_existing_defaults(home):
    (home / "Music" / "Ableton" / "User Library").mkdir(parents=True)
    dirs = install.remote_scripts_dirs()
    assert dirs == [home / "Studio" / "My Library" / "Remote Scripts",
                    home / "Music" / "Ableton" / "User Library" / "Remote Scripts"]


def test_no_library_no_target(home, capsys):
    (home / "Library" / "Preferences" / "Ableton" / "Live 12.4.7" / "Library.cfg").unlink()
    assert install.remote_scripts_dirs() == []
    assert install.main([]) == 1
    assert "No Ableton User Library" in capsys.readouterr().out


def test_unreadable_config_is_ignored(tmp_path):
    cfg = tmp_path / "Library.cfg"
    cfg.write_text("not xml <")
    assert install.user_library_from_config(cfg) is None


def test_install_update_and_up_to_date(tmp_path, source):
    scripts = tmp_path / "Remote Scripts"
    first = install.install_into(scripts, source=source)
    assert first.action == "installed"
    dest = scripts / install.SURFACE_NAME
    assert sorted(p.name for p in dest.iterdir()) == ["__init__.py", "commands.py"]
    assert install.install_into(scripts, source=source).action == "up to date"
    (source / "commands.py").write_text("X = 2\n")
    assert install.install_into(scripts, source=source).action == "updated"
    assert (dest / "commands.py").read_text() == "X = 2\n"
    assert [p.name for p in scripts.iterdir()] == [install.SURFACE_NAME]  # no staging left


def test_update_removes_files_dropped_from_the_package(tmp_path, source):
    scripts = tmp_path / "Remote Scripts"
    install.install_into(scripts, source=source)
    (source / "commands.py").unlink()
    install.install_into(scripts, source=source)
    assert not (scripts / install.SURFACE_NAME / "commands.py").exists()


def test_dry_run_changes_nothing(tmp_path, source):
    scripts = tmp_path / "Remote Scripts"
    assert install.install_into(scripts, dry_run=True, source=source).action == "would install"
    assert not scripts.exists()


def test_script_version_in(tmp_path):
    d = tmp_path / "S"
    assert install.script_version_in(d) is None
    d.mkdir()
    (d / "__init__.py").write_text("x = 1\nSCRIPT_VERSION = '1.2.3'\n")
    assert install.script_version_in(d) == "1.2.3"
    (d / "__init__.py").write_text("x = 1\n")
    assert install.script_version_in(d) == "unknown"


def test_legacy_surface_reported_then_removed_on_request(tmp_path, source, monkeypatch, capsys):
    monkeypatch.setattr(install, "SCRIPT_SOURCE", source)
    monkeypatch.setattr(install.install_into, "__defaults__", (False, source))
    scripts = tmp_path / "Remote Scripts"
    old = scripts / install.LEGACY_SURFACE_NAME
    old.mkdir(parents=True)
    (old / "__init__.py").write_text("SCRIPT_VERSION = '1.17.0'\n")
    assert install.main(["--target", str(scripts)]) == 0
    assert "still present" in capsys.readouterr().out and old.exists()
    assert install.main(["--target", str(scripts), "--remove-legacy"]) == 0
    assert not old.exists()


def test_packaged_script_is_where_the_installer_looks():
    assert (install.SCRIPT_SOURCE / "__init__.py").is_file()
    assert install.script_version_in(install.SCRIPT_SOURCE) == install.SCRIPT_VERSION


def test_registry_metadata_matches_the_package():
    """server.json (official MCP Registry) must describe this exact release."""
    import json
    from pathlib import Path
    from ableton_studio_mcp import __version__
    root = Path(__file__).resolve().parents[1]
    meta = json.loads((root / "server.json").read_text())
    assert meta["version"] == __version__
    assert meta["packages"][0]["version"] == __version__
    assert meta["packages"][0]["identifier"] == "ableton-studio-mcp"
    assert f"mcp-name: {meta['name']}" in (root / "README.md").read_text()
    assert len(meta["description"]) <= 100
