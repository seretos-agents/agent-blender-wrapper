"""Driving tests for the prerequisite check (ticket #14).

Runs skills/blender-wrapper/scripts/check_prerequisites.py as a real
subprocess against a stand-in "Blender" (a Python script behind a tiny sh/cmd
wrapper, as in test_launch_blender.py) and temp per-version config dirs.
The stand-in answers `--version` with `Blender 5.0.1`; for `--python-expr` it
prints `BLENDERMCP_PREREQ:` followed by $STANDIN_ADDONS (nothing when unset).

Run with: python -m unittest discover -s tests -v
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK = REPO_ROOT / "skills" / "blender-wrapper" / "scripts" / "check_prerequisites.py"

STANDIN_SOURCE = """\
import os, sys

args = sys.argv[1:]
if "--version" in args:
    print("Blender 5.0.1")
    print("\\tbuild date: 2025-10-01")
elif "--python-expr" in args:
    addons = os.environ.get("STANDIN_ADDONS")
    print("Blender noise line")
    if addons is not None:
        print("BLENDERMCP_PREREQ:" + addons)
    print("more noise")
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class CheckTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        standin = self.tmp / "standin.py"
        standin.write_text(STANDIN_SOURCE)
        bindir = self.tmp / "bin"
        bindir.mkdir()
        if os.name == "nt":
            self.blender = bindir / "blender.cmd"
            self.blender.write_text(f'@"{sys.executable}" "{standin}" %*\r\n')
        else:
            self.blender = bindir / "blender"
            self.blender.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{standin}" "$@"\n')
            self.blender.chmod(0o755)
        self.home = self.tmp / "home"
        self.appdata = self.tmp / "appdata"
        self.xdg = self.tmp / "xdg"
        for d in (self.home, self.appdata, self.xdg):
            d.mkdir()
        self.port = free_port()

    def config_root(self) -> Path:
        if sys.platform == "win32":
            return self.appdata / "Blender Foundation" / "Blender"
        if sys.platform == "darwin":
            return self.home / "Library" / "Application Support" / "Blender"
        return self.xdg / "blender"

    def install(self, addon=True, mpfb=True, version="5.0"):
        root = self.config_root() / version
        addons = root / "scripts" / "addons"
        addons.mkdir(parents=True, exist_ok=True)
        if addon:
            (addons / "addon.py").write_text("# stand-in BlenderMCP addon\n")
        if mpfb:
            mdir = root / "extensions" / "user_default" / "mpfb"
            mdir.mkdir(parents=True, exist_ok=True)
            (mdir / "blender_manifest.toml").write_text('id = "mpfb"\n')

    def run_check(self, *args, env_extra=None, timeout=120):
        env = dict(os.environ)
        for k in ("BLENDER_HOST", "BLENDER_PATH", "STANDIN_ADDONS"):
            env.pop(k, None)
        env.update(APPDATA=str(self.appdata), XDG_CONFIG_HOME=str(self.xdg),
                   HOME=str(self.home), USERPROFILE=str(self.home),
                   BLENDER_PORT=str(self.port))
        env.update(env_extra or {})
        proc = subprocess.run([sys.executable, str(CHECK), *args], env=env,
                              capture_output=True, text=True, timeout=timeout)
        out = proc.stdout + proc.stderr
        try:
            report = json.loads(proc.stdout)
        except ValueError:
            self.fail(f"stdout is not one JSON object (exit {proc.returncode}): {out!r}")
        return proc, report, out


class FullReportTests(CheckTestCase):
    def test_full_install_reports_all_and_exits_0(self):
        self.install()
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", self.port))
            srv.listen(5)
            proc, rep, out = self.run_check("--blender", str(self.blender))
        self.assertEqual(proc.returncode, 0, out)
        self.assertEqual(rep["blender"]["path"], str(self.blender))
        self.assertEqual(rep["blender"]["version"], "5.0.1")
        self.assertTrue(rep["addon"]["installed"])
        self.assertIsNone(rep["addon"]["enabled"])
        self.assertEqual(Path(rep["addon"]["path"]),
                         self.config_root() / "5.0" / "scripts" / "addons" / "addon.py")
        self.assertTrue(rep["extensions"]["mpfb"]["installed"])
        self.assertIsNone(rep["extensions"]["mpfb"]["enabled"])
        self.assertEqual(rep["socket"]["port"], self.port)
        self.assertIs(rep["socket"]["listening"], True)

    def test_socket_closed_reports_false_still_exit_0(self):
        self.install()
        proc, rep, out = self.run_check("--blender", str(self.blender))
        self.assertEqual(proc.returncode, 0, out)
        self.assertIs(rep["socket"]["listening"], False)
        self.assertEqual(rep["socket"]["port"], self.port)

    def test_mpfb_absent_reports_false_still_exit_0(self):
        self.install(mpfb=False)
        proc, rep, out = self.run_check("--blender", str(self.blender))
        self.assertEqual(proc.returncode, 0, out)
        self.assertIs(rep["extensions"]["mpfb"]["installed"], False)
        self.assertTrue(rep["addon"]["installed"])

    def test_blender_path_env_used(self):
        self.install()
        proc, rep, out = self.run_check(env_extra={"BLENDER_PATH": str(self.blender)})
        self.assertEqual(proc.returncode, 0, out)
        self.assertEqual(rep["blender"]["path"], str(self.blender))


class AddonMissingTests(CheckTestCase):
    def test_addon_missing_reports_searched_dir_exit_3(self):
        self.install(addon=False)
        proc, rep, out = self.run_check("--blender", str(self.blender))
        self.assertEqual(proc.returncode, 3, out)
        self.assertIs(rep["addon"]["installed"], False)
        self.assertEqual(Path(rep["addon"]["searched"]),
                         self.config_root() / "5.0" / "scripts" / "addons")
        self.assertEqual(rep["blender"]["version"], "5.0.1")

    def test_addon_only_in_other_version_dir_is_missing(self):
        self.install(version="4.2")
        proc, rep, out = self.run_check("--blender", str(self.blender))
        self.assertEqual(proc.returncode, 3, out)
        self.assertIs(rep["addon"]["installed"], False)


class NoBlenderTests(CheckTestCase):
    def isolated_env(self):
        empty = self.tmp / "empty"
        empty.mkdir(exist_ok=True)
        pf = self.tmp / "programfiles"
        pf.mkdir(exist_ok=True)
        return {"PATH": str(empty), "ProgramFiles": str(pf)}

    def test_no_blender_reports_tried_exit_2(self):
        if sys.platform != "win32":
            defaults = ["/Applications/Blender.app/Contents/MacOS/Blender",
                        "/usr/bin/blender", "/snap/bin/blender"]
            if any(os.path.isfile(p) for p in defaults):
                self.skipTest("a real Blender sits at a default location")
        proc, rep, out = self.run_check(env_extra=self.isolated_env())
        self.assertEqual(proc.returncode, 2, out)
        self.assertIsNone(rep["blender"]["path"])
        self.assertIsNone(rep["blender"]["version"])
        self.assertIn("PATH (blender)", rep["blender"]["tried"])
        self.assertGreater(len(rep["blender"]["tried"]), 1)

    def test_blender_path_env_missing_listed_in_tried(self):
        missing = self.tmp / "nowhere" / "blender"
        env = self.isolated_env()
        env["BLENDER_PATH"] = str(missing)
        proc, rep, out = self.run_check(env_extra=env)
        self.assertEqual(proc.returncode, 2, out)
        self.assertIsNone(rep["blender"]["path"])
        self.assertTrue(any(str(missing) in t for t in rep["blender"]["tried"]),
                        rep["blender"]["tried"])


class DeepTests(CheckTestCase):
    def test_deep_enabled(self):
        self.install()
        proc, rep, out = self.run_check(
            "--blender", str(self.blender), "--deep",
            env_extra={"STANDIN_ADDONS": json.dumps(["addon", "bl_ext.user_default.mpfb"])})
        self.assertEqual(proc.returncode, 0, out)
        self.assertIs(rep["addon"]["enabled"], True)
        self.assertIs(rep["extensions"]["mpfb"]["enabled"], True)

    def test_deep_disabled_exit_3(self):
        self.install()
        proc, rep, out = self.run_check(
            "--blender", str(self.blender), "--deep",
            env_extra={"STANDIN_ADDONS": json.dumps(["bl_ext.user_default.mpfb"])})
        self.assertEqual(proc.returncode, 3, out)
        self.assertIs(rep["addon"]["installed"], True)
        self.assertIs(rep["addon"]["enabled"], False)
        self.assertIs(rep["extensions"]["mpfb"]["enabled"], True)

    def test_deep_mpfb_disabled_does_not_change_exit(self):
        self.install()
        proc, rep, out = self.run_check(
            "--blender", str(self.blender), "--deep",
            env_extra={"STANDIN_ADDONS": json.dumps(["addon"])})
        self.assertEqual(proc.returncode, 0, out)
        self.assertIs(rep["extensions"]["mpfb"]["enabled"], False)

    def test_deep_probe_failure_exit_1(self):
        self.install()
        proc, rep, out = self.run_check("--blender", str(self.blender), "--deep")
        self.assertEqual(proc.returncode, 1, out)
        self.assertIsNone(rep["addon"]["enabled"])
        self.assertTrue(rep["addon"]["installed"])


if __name__ == "__main__":
    unittest.main()
