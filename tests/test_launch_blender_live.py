"""Live end-to-end check of the Blender launcher (ticket #13). Skipped by default.

Run: BLENDER_LIVE_TEST=1 python -m unittest tests.test_launch_blender_live -v
Needs a real Blender with the BlenderMCP addon installed.

It launches real Blender via the launcher, then sends the same wire command
the plugin's MCP `get_scene_info` tool sends ({"type": "get_scene_info"}) over
the addon socket once, with no retry. This is the addon-socket equivalent of the
plugin tool call (the MCP server is a thin bridge to this socket), not the MCP
tool itself. It then requests a viewport screenshot for manual inspection.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LAUNCHER = (Path(__file__).resolve().parent.parent
            / "skills" / "blender-wrapper" / "scripts" / "launch_blender.py")


def _command(port, payload, timeout=30):
    host = os.environ.get("BLENDER_HOST") or "localhost"
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(json.dumps(payload).encode())
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                raise ConnectionError("socket closed before a full response")
            buf += chunk
            try:
                return json.loads(buf.decode())
            except ValueError:
                continue


@unittest.skipUnless(os.environ.get("BLENDER_LIVE_TEST") == "1",
                     "set BLENDER_LIVE_TEST=1 to launch real Blender")
class LiveLaunchTest(unittest.TestCase):
    def test_launch_then_scene_info_first_try(self):
        port = int(os.environ.get("BLENDER_PORT") or 9876)
        proc = subprocess.run([sys.executable, str(LAUNCHER)],
                              capture_output=True, text=True, timeout=120)
        print(proc.stdout, proc.stderr)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        info = _command(port, {"type": "get_scene_info", "params": {}})
        self.assertEqual(info.get("status"), "success", info)
        names = [o.get("name") for o in info.get("result", {}).get("objects", [])]
        print("objects:", names)
        shot = str(Path(tempfile.gettempdir()) / "blender-live-viewport.png")
        _command(port, {"type": "get_viewport_screenshot",
                        "params": {"filepath": shot, "max_size": 800, "format": "png"}})
        print("screenshot:", shot)


if __name__ == "__main__":
    unittest.main()
