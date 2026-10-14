"""Driving tests for the Blender launcher (ticket #13).

Covers skills/blender-wrapper/scripts/launch_blender.py (exit codes 0/1/2/3)
and skills/blender-wrapper/scripts/blender_mcp_autostart.py (with a fake bpy).

A stand-in "Blender" (a Python script behind a tiny sh/cmd wrapper) replaces
the real application so the tests run on ubuntu and windows without Blender.
STANDIN_MODE selects: listen | never | addon-missing.

Run with: python -m unittest discover -s tests -v
"""

import importlib.util
import io
import os
import socket
import subprocess
import sys
import tempfile
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "blender-wrapper" / "scripts"
LAUNCHER = SCRIPTS_DIR / "launch_blender.py"
AUTOSTART = SCRIPTS_DIR / "blender_mcp_autostart.py"

STANDIN_SOURCE = """\
import os, socket, sys, time

print("standin argv:", sys.argv[1:], flush=True)
marker = os.environ.get("SPAWN_MARKER")
if marker:
    open(marker, "w").write("spawned")
mode = os.environ.get("STANDIN_MODE", "listen")
deadline = time.time() + 30
if mode == "listen":
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", int(os.environ["BLENDER_PORT"])))
    srv.listen(5)
    srv.settimeout(0.5)
    while time.time() < deadline:
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        conn.settimeout(1)
        try:
            if conn.recv(100).strip() == b"stop":
                break
        except OSError:
            pass
        finally:
            conn.close()
elif mode == "addon-missing":
    print("BLENDERMCP_AUTOSTART_ERROR: addon module 'addon' not found", flush=True)
    time.sleep(30)
else:
    time.sleep(30)
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LauncherTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        standin = self.tmp / "standin.py"
        standin.write_text(STANDIN_SOURCE)
        if os.name == "nt":
            self.blender = self.tmp / "blender.cmd"
            self.blender.write_text(f'@"{sys.executable}" "{standin}" %*\r\n')
        else:
            self.blender = self.tmp / "blender"
            self.blender.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{standin}" "$@"\n')
            self.blender.chmod(0o755)
        self.port = free_port()
        self.log = self.tmp / "launch.log"
        self.addCleanup(self._stop_standin)

    def _stop_standin(self):
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=1) as s:
                s.sendall(b"stop")
        except OSError:
            pass

    def run_launcher(self, *args, mode="listen", env_extra=None, timeout=60):
        env = dict(os.environ)
        env["BLENDER_PORT"] = str(self.port)
        env["STANDIN_MODE"] = mode
        env.pop("BLENDER_HOST", None)
        env.pop("BLENDER_PATH", None)
        env.update(env_extra or {})
        start = time.time()
        proc = subprocess.run(
            [sys.executable, str(LAUNCHER), *args],
            env=env, capture_output=True, text=True, timeout=timeout,
        )
        return proc, time.time() - start, proc.stdout + proc.stderr


class LaunchBlenderTests(LauncherTestCase):
    def test_launch_succeeds_prints_pid_and_port(self):
        proc, _, out = self.run_launcher(
            "--blender", str(self.blender), "--timeout", "20", "--log", str(self.log))
        self.assertEqual(proc.returncode, 0, out)
        self.assertRegex(out, rf"pid=\d+ port={self.port}")

    def test_log_records_autostart_args(self):
        proc, _, out = self.run_launcher(
            "--blender", str(self.blender), "--timeout", "20", "--log", str(self.log))
        self.assertEqual(proc.returncode, 0, out)
        log = self.log.read_text()
        self.assertIn("--python", log)
        self.assertIn("blender_mcp_autostart.py", log)

    def test_blender_path_env_used(self):
        proc, _, out = self.run_launcher(
            "--timeout", "20", "--log", str(self.log),
            env_extra={"BLENDER_PATH": str(self.blender)})
        self.assertEqual(proc.returncode, 0, out)
        self.assertRegex(out, rf"pid=\d+ port={self.port}")

    def test_timeout_exits_nonzero(self):
        proc, elapsed, out = self.run_launcher(
            "--blender", str(self.blender), "--timeout", "2", "--log", str(self.log),
            mode="never")
        self.assertEqual(proc.returncode, 1, out)
        self.assertIn(str(self.port), out)
        self.assertIn("did not open within 2", out)
        self.assertLess(elapsed, 15)

    def test_existing_listener_no_spawn(self):
        marker = self.tmp / "spawned"
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", self.port))
            srv.listen(5)
            proc, _, out = self.run_launcher(
                "--blender", str(self.blender), "--timeout", "5", "--log", str(self.log),
                env_extra={"SPAWN_MARKER": str(marker)})
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("already listening", out)
        self.assertIn(str(self.port), out)
        time.sleep(1)
        self.assertFalse(marker.exists())

    def test_wrong_path_names_path(self):
        bad = self.tmp / "nope" / "blender"
        proc, _, out = self.run_launcher(
            "--blender", str(bad), "--timeout", "5", "--log", str(self.log))
        self.assertEqual(proc.returncode, 2, out)
        self.assertIn(str(bad), out)

    def test_addon_missing_exit_3(self):
        proc, elapsed, out = self.run_launcher(
            "--blender", str(self.blender), "--timeout", "20", "--log", str(self.log),
            mode="addon-missing")
        self.assertEqual(proc.returncode, 3, out)
        self.assertIn("addon", out)
        self.assertLess(elapsed, 15)


class FakeBlender:
    """Fake bpy / addon_utils / addon modules for exercising the autostart."""

    def __init__(self, loaded=False, enable_result="module"):
        self.timers = []
        self.enable_calls = []
        self.servers = []
        self.prefs = types.SimpleNamespace(is_dirty=False)
        fake = self

        class View:
            def __init__(self):
                self._splash = True

            @property
            def show_splash(self):
                return self._splash

            @show_splash.setter
            def show_splash(self, value):
                self._splash = value
                fake.prefs.is_dirty = True

        self.view = View()
        self.prefs.view = self.view
        self.scene = types.SimpleNamespace()

        class Types:
            pass

        bpy = types.ModuleType("bpy")
        bpy.app = types.SimpleNamespace(timers=types.SimpleNamespace(
            register=lambda fn, first_interval=0: self.timers.append((fn, first_interval))))
        bpy.context = types.SimpleNamespace(preferences=self.prefs, scene=self.scene)
        bpy.types = Types
        self.bpy = bpy

        addon_utils = types.ModuleType("addon_utils")
        addon_utils.check = lambda name: (loaded, loaded)

        def enable(name, *args, **kwargs):
            self.enable_calls.append((name, args, kwargs))
            if enable_result == "error":
                raise ImportError("no addon")
            return None if enable_result is None else types.ModuleType(name)

        addon_utils.enable = enable
        self.addon_utils = addon_utils

        class Server:
            def __init__(self, host="localhost", port=9876):
                self.port = port
                self.started = False
                fake.servers.append(self)

            def start(self):
                self.started = True

        addon = types.ModuleType("addon")
        addon.BlenderMCPServer = Server
        self.addon = addon

    def modules(self):
        return {"bpy": self.bpy, "addon_utils": self.addon_utils, "addon": self.addon}


def load_autostart():
    spec = importlib.util.spec_from_file_location("blender_mcp_autostart_under_test", AUTOSTART)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AutostartTests(unittest.TestCase):
    def run_autostart(self, fake, port="9911"):
        out = io.StringIO()
        with mock.patch.dict(sys.modules, fake.modules()), \
                mock.patch.dict(os.environ, {"BLENDER_PORT": port}), \
                redirect_stdout(out):
            module = load_autostart()
            module.main()
            self.assertEqual(len(fake.timers), 1)
            during = fake.view.show_splash
            result = fake.timers[0][0]()
        return module, during, result, out.getvalue()

    def test_autostart_with_fake_bpy(self):
        fake = FakeBlender()
        _, during, result, _ = self.run_autostart(fake, port="9911")
        self.assertFalse(during)
        self.assertTrue(fake.view.show_splash)
        self.assertFalse(fake.prefs.is_dirty)
        self.assertEqual(len(fake.enable_calls), 1)
        self.assertIs(fake.enable_calls[0][2].get("default_set"), False)
        self.assertEqual(len(fake.servers), 1)
        self.assertEqual(fake.servers[0].port, 9911)
        self.assertTrue(fake.servers[0].started)
        self.assertEqual(fake.scene.blendermcp_port, 9911)
        self.assertTrue(fake.scene.blendermcp_server_running)
        self.assertIsNone(result)

    def test_addon_import_failure_prints_marker(self):
        fake = FakeBlender(enable_result="error")
        _, _, result, out = self.run_autostart(fake)
        self.assertIn("BLENDERMCP_AUTOSTART_ERROR:", out)
        self.assertEqual(fake.servers, [])
        self.assertIsNone(result)

    def test_addon_falsy_module_prints_marker(self):
        fake = FakeBlender(enable_result=None)
        _, _, _, out = self.run_autostart(fake)
        self.assertIn("BLENDERMCP_AUTOSTART_ERROR:", out)
        self.assertEqual(fake.servers, [])

    def test_already_loaded_skips_enable(self):
        fake = FakeBlender(loaded=True)
        self.run_autostart(fake)
        self.assertEqual(fake.enable_calls, [])
        self.assertEqual(len(fake.servers), 1)
        self.assertTrue(fake.servers[0].started)


if __name__ == "__main__":
    unittest.main()
