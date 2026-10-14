#!/usr/bin/env python3
"""Launch Blender with the BlenderMCP addon's socket already listening.

Exit codes:
  0  BlenderMCP is listening (started now, or already was)
  1  Blender failed to start, exited early, or the port did not open in time
  2  Blender executable not found
  3  Blender started but the BlenderMCP addon is missing or failed to start

Environment: BLENDER_PORT (default 9876), BLENDER_HOST (default localhost),
BLENDER_PATH (Blender executable, overridden by --blender).
"""

import argparse
import glob
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MARKER = "BLENDERMCP_AUTOSTART_ERROR:"
AUTOSTART = Path(__file__).resolve().parent / "blender_mcp_autostart.py"


def port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def candidate_paths():
    if sys.platform == "win32":
        base = os.environ.get("ProgramFiles", r"C:\Program Files")
        found = glob.glob(os.path.join(base, "Blender Foundation", "Blender *", "blender.exe"))

        def version_key(p):
            name = os.path.basename(os.path.dirname(p)).replace("Blender", "").strip()
            return tuple(int(x) if x.isdigit() else 0 for x in name.split("."))

        return sorted(found, key=version_key, reverse=True) or [
            os.path.join(base, "Blender Foundation", "Blender *", "blender.exe")]
    if sys.platform == "darwin":
        return ["/Applications/Blender.app/Contents/MacOS/Blender"]
    return ["/usr/bin/blender", "/snap/bin/blender"] + sorted(
        glob.glob("/opt/blender*/blender"), reverse=True)


def resolve_blender(explicit):
    """Return (path, None) or (None, error_message)."""
    if explicit:
        if os.path.isfile(explicit):
            return explicit, None
        return None, f"Blender not found at {explicit}"
    env = os.environ.get("BLENDER_PATH")
    if env:
        if os.path.isfile(env):
            return env, None
        return None, f"Blender not found at {env} (from BLENDER_PATH)"
    which = shutil.which("blender")
    if which:
        return which, None
    tried = ["PATH (blender)"]
    for cand in candidate_paths():
        if os.path.isfile(cand):
            return cand, None
        tried.append(cand)
    return None, ("Blender not found. Tried: " + "; ".join(tried)
                  + ". Pass --blender PATH or set BLENDER_PATH.")


def log_has_marker(log):
    try:
        with open(log, "r", errors="replace") as f:
            for line in f:
                if MARKER in line:
                    return line.strip()
    except OSError:
        pass
    return None


def stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--blender", help="path to the Blender executable")
    parser.add_argument("--timeout", type=float, default=60,
                        help="seconds to wait for the port to open (default 60)")
    parser.add_argument("--log", default=os.path.join(tempfile.gettempdir(), "blender-mcp-launch.log"),
                        help="file receiving Blender's stdout/stderr")
    args = parser.parse_args(argv)

    host = os.environ.get("BLENDER_HOST") or "localhost"
    port = int(os.environ.get("BLENDER_PORT") or 9876)

    if port_open(host, port):
        print(f"BlenderMCP already listening on {host}:{port}; not starting a second Blender")
        return 0

    exe, error = resolve_blender(args.blender)
    if error:
        print(error)
        return 2

    env = dict(os.environ, BLENDER_PORT=str(port))
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    with open(args.log, "wb") as log_file:
        try:
            proc = subprocess.Popen([exe, "--python", str(AUTOSTART)], env=env,
                                    stdin=subprocess.DEVNULL, stdout=log_file,
                                    stderr=subprocess.STDOUT, **kwargs)
        except OSError as exc:
            print(f"Could not start Blender at {exe}: {exc}")
            return 1

    deadline = time.time() + args.timeout
    while True:
        if port_open(host, port):
            print(f"Blender started: pid={proc.pid} port={port} log={args.log}")
            return 0
        line = log_has_marker(args.log)
        if line:
            stop(proc)
            print(line)
            print(f"BlenderMCP addon unavailable; see {args.log}")
            return 3
        code = proc.poll()
        if code is not None:
            print(f"Blender exited early with code {code}; see {args.log}")
            return 1
        if time.time() >= deadline:
            stop(proc)
            print(f"port {port} did not open within {args.timeout:g}s; see {args.log}")
            return 1
        time.sleep(0.5)


if __name__ == "__main__":
    sys.exit(main())
