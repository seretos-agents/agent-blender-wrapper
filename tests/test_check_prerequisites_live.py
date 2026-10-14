"""Live check of the prerequisite script against real Blender (ticket #14). Skipped by default.

Run: BLENDER_LIVE_TEST=1 python -m unittest tests.test_check_prerequisites_live -v
Needs a real Blender with the BlenderMCP addon and MPFB installed. This is not
evidence for the PR suite; it exists for whoever has that machine.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

CHECK = (Path(__file__).resolve().parent.parent
         / "skills" / "blender-wrapper" / "scripts" / "check_prerequisites.py")


@unittest.skipUnless(os.environ.get("BLENDER_LIVE_TEST") == "1",
                     "set BLENDER_LIVE_TEST=1 to run against real Blender")
class LiveCheckTest(unittest.TestCase):
    def test_deep_check_on_real_machine(self):
        proc = subprocess.run([sys.executable, str(CHECK), "--deep"],
                              capture_output=True, text=True, timeout=180)
        print(proc.stdout, proc.stderr)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        rep = json.loads(proc.stdout)
        self.assertTrue(rep["blender"]["path"], rep)
        self.assertRegex(rep["blender"]["version"] or "", r"^\d+\.\d+")
        self.assertIs(rep["addon"]["installed"], True)
        self.assertIs(rep["addon"]["enabled"], True)
        self.assertIs(rep["extensions"]["mpfb"]["installed"], True)
        self.assertIsInstance(rep["socket"]["listening"], bool)


if __name__ == "__main__":
    unittest.main()
