#!/usr/bin/env python3
"""Report which Blender prerequisites are present. Detects only; installs nothing.

Prints one JSON object on stdout:
  blender    {path, version, tried}
  addon      {installed, enabled, path, searched}   (BlenderMCP addon.py)
  extensions {mpfb: {installed, enabled, path}}
  socket     {host, port, listening}
`enabled` is null unless --deep is given: --deep starts Blender once in the
background (slow) and reads which add-ons are enabled.

Exit codes:
  0  Blender and the BlenderMCP addon found (and enabled under --deep)
  1  --deep probe failed or printed no result
  2  Blender executable not found
  3  BlenderMCP addon missing (or, under --deep, installed but disabled)
A closed socket or a missing MPFB never changes the exit code.

Environment: BLENDER_PATH, BLENDER_HOST (default localhost), BLENDER_PORT (default 9876).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from launch_blender import port_open, search_blender  # noqa: E402

MARKER = "BLENDERMCP_PREREQ:"
PROBE = ("import bpy, json; print('" + MARKER
         + "' + json.dumps(list(bpy.context.preferences.addons.keys())))")
# extension name -> (directory under extensions/user_default, enabled-key in --deep)
EXTENSIONS = {"mpfb": "mpfb"}


def config_root():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        return Path(base) / "Blender Foundation" / "Blender"
    if sys.platform == "darwin":
        return Path(os.path.expanduser("~")) / "Library" / "Application Support" / "Blender"
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "blender"


def blender_version(exe):
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=30, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"Blender (\d+\.\d+(?:\.\d+)?)", out)
    return m.group(1) if m else None


def probe_enabled(exe):
    """Return the list of enabled add-on keys, or None if the probe failed."""
    try:
        out = subprocess.run([exe, "--background", "--python-expr", PROBE],
                             capture_output=True, text=True, timeout=120,
                             stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        if line.startswith(MARKER):
            try:
                keys = json.loads(line[len(MARKER):])
            except ValueError:
                return None
            return keys if isinstance(keys, list) else None
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--blender", help="path to the Blender executable")
    parser.add_argument("--deep", action="store_true",
                        help="launch Blender once to read which add-ons are enabled")
    args = parser.parse_args(argv)

    host = os.environ.get("BLENDER_HOST") or "localhost"
    port = int(os.environ.get("BLENDER_PORT") or 9876)
    exe, tried = search_blender(args.blender)
    version = blender_version(exe) if exe else None
    report = {
        "blender": {"path": exe, "version": version, "tried": tried},
        "addon": {"installed": False, "enabled": None, "path": None, "searched": None},
        "extensions": {name: {"installed": False, "enabled": None, "path": None}
                       for name in EXTENSIONS},
        "socket": {"host": host, "port": port, "listening": port_open(host, port)},
    }

    code = 0
    if not exe:
        code = 2
    else:
        ver_dir = None
        if version:
            ver_dir = config_root() / ".".join(version.split(".")[:2])
        if ver_dir is not None:
            addons_dir = ver_dir / "scripts" / "addons"
            addon = addons_dir / "addon.py"
            report["addon"]["searched"] = str(addons_dir)
            report["addon"]["installed"] = addon.is_file()
            if addon.is_file():
                report["addon"]["path"] = str(addon)
            for name, dirname in EXTENSIONS.items():
                ext = ver_dir / "extensions" / "user_default" / dirname
                if (ext / "blender_manifest.toml").is_file():
                    report["extensions"][name].update(installed=True, path=str(ext))
        if not report["addon"]["installed"]:
            code = 3
        if args.deep:
            keys = probe_enabled(exe)
            if keys is None:
                code = 1 if code == 0 else code
            else:
                report["addon"]["enabled"] = "addon" in keys
                for name, dirname in EXTENSIONS.items():
                    report["extensions"][name]["enabled"] = f"bl_ext.user_default.{dirname}" in keys
                if report["addon"]["installed"] and not report["addon"]["enabled"]:
                    code = 3

    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
