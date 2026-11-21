"""`ableton-studio-mcp doctor`: each check, on a fake User Library and Live."""

import json
import socket
import threading

import pytest

import MCP_Server.doctor as doctor
from MCP_Server.remote_script_install import EXPECTED_REMOTE_SCRIPT_VERSION as V


@pytest.fixture
def library(tmp_path, monkeypatch):
    roots = tmp_path / "User Library" / "Remote Scripts"
    roots.mkdir(parents=True)
    prefs = tmp_path / "Prefs" / "Live 12.4.7"
    prefs.mkdir(parents=True)
    monkeypatch.setattr(doctor, "discover_user_library_remote_script_dirs", lambda: [roots])
    monkeypatch.setattr(doctor, "_live_preference_dirs", lambda: [prefs])

    def install(version):
        d = roots / "AbletonMCP"
        d.mkdir(exist_ok=True)
        (d / "__init__.py").write_text(f'x = 1\nSCRIPT_VERSION = "{version}"\n')
    return type("Lib", (), {"roots": roots, "prefs": prefs, "install": staticmethod(install)})


def fake_live(reply):
    """Serve one get_script_info request on a free port; return the port."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        with conn:
            assert json.loads(conn.recv(65536))["type"] == "get_script_info"
            conn.sendall(json.dumps(reply).encode())
        srv.close()
    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_script_missing_then_outdated_then_ok(library):
    c = doctor.check_installed_script()
    assert c.status == "fail" and "install-script" in c.fix
    library.install("1.0.0")
    c = doctor.check_installed_script()
    assert c.status == "fail" and "1.0.0" in c.found
    library.install(V)
    assert doctor.check_installed_script().status == "ok"


def test_no_user_library(monkeypatch):
    monkeypatch.setattr(doctor, "discover_user_library_remote_script_dirs", lambda: [])
    c = doctor.check_installed_script()
    assert c.status == "fail" and "User Library" in c.found


def test_control_surface_read_from_utf16_preferences(library):
    cfg = library.prefs / "Preferences.cfg"
    cfg.write_bytes(b"\x00junk")
    assert doctor.check_control_surface().status == "warn"
    cfg.write_bytes(b"\x00junk" + "AbletonMCP".encode("utf-16-le"))
    assert doctor.check_control_surface().status == "ok"


def test_live_up_to_date():
    port = fake_live({"status": "success", "result": {"script_version": V}})
    c = doctor.check_live("127.0.0.1", port)
    assert c.status == "ok" and V in c.found


def test_live_runs_old_script_although_new_one_installed(library):
    library.install(V)
    port = fake_live({"status": "success", "result": {"script_version": "1.0.0"}})
    c = doctor.check_live("127.0.0.1", port)
    assert c.status == "fail" and "restart Live" in c.fix and "install-script" not in c.fix


def test_live_not_running_shows_log_errors(library):
    (library.prefs / "Log.txt").write_text(
        "info: RemoteScriptMessage: (AbletonMCP) warp_markers read failed: x\n"
        "error: RemoteScriptError: (AbletonMCP) Traceback: boom\n")
    c = doctor.check_live("127.0.0.1", free_port())
    assert c.status == "fail" and "boom" in c.fix and "warp_markers" not in c.fix


def test_report_and_exit_code(monkeypatch, capsys):
    ok = doctor.Check("A", "ok", "fine")
    bad = doctor.Check("B", "fail", "broken", "do this")
    monkeypatch.setattr(doctor, "run_checks", lambda: [ok, bad])
    assert doctor.main([]) == 1
    out = capsys.readouterr().out
    assert "✗ B: broken" in out and "→ do this" in out and "1 problem(s)" in out
    monkeypatch.setattr(doctor, "run_checks", lambda: [ok])
    assert doctor.main([]) == 0
    assert "All good." in capsys.readouterr().out


def test_server_main_dispatches_doctor(monkeypatch):
    import MCP_Server.server as server
    monkeypatch.setattr("sys.argv", ["ableton-studio-mcp", "doctor"])
    monkeypatch.setattr(doctor, "main", lambda argv: 0)
    with pytest.raises(SystemExit) as e:
        server.main()
    assert e.value.code == 0
