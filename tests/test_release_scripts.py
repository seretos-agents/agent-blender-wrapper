"""Driving tests for the release-scripts scoped-release-notes work (epic #11).

Covers:
  - .github/scripts/prev-release-tag.sh (previous-release-tag resolution)
  - .github/scripts/marketplace-payload.sh (jq-built dispatch payload)

Run with: python -m unittest discover -s tests -v
Requires `jq` on PATH. Invokes the scripts via bash (Git Bash on Windows,
`bash` on PATH elsewhere) with MSYS_NO_PATHCONV=1 so MSYS doesn't mangle
plain string arguments that merely look like paths.
"""

import json
import os
import platform
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / ".github" / "scripts"
PREV_TAG_SCRIPT = SCRIPTS_DIR / "prev-release-tag.sh"
PAYLOAD_SCRIPT = SCRIPTS_DIR / "marketplace-payload.sh"


def _find_bash() -> str:
    if platform.system() == "Windows":
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        if git_bash.exists():
            return str(git_bash)
    found = shutil.which("bash")
    if not found:
        raise RuntimeError("no bash executable found on PATH")
    return found


BASH = _find_bash()


def _base_env():
    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    return env


def run_prev_tag(tags, plugin, version):
    """Run prev-release-tag.sh <plugin> <version> with `tags` fed on stdin."""
    stdin = "".join(t + "\n" for t in tags)
    return subprocess.run(
        [BASH, str(PREV_TAG_SCRIPT), plugin, version],
        input=stdin,
        capture_output=True,
        encoding="utf-8",
        env=_base_env(),
    )


def run_payload(env_vars):
    """Run marketplace-payload.sh with `env_vars` as its only inputs (no argv)."""
    env = _base_env()
    env.pop("CHANGELOG", None)
    env.update(env_vars)
    return subprocess.run(
        [BASH, str(PAYLOAD_SCRIPT)],
        capture_output=True,
        encoding="utf-8",
        env=env,
    )


class PrevReleaseTagTests(unittest.TestCase):
    """.github/scripts/prev-release-tag.sh"""

    def test_prev_tag_numeric_and_prerelease_order(self):
        cases = [
            (
                [
                    "agent-blender-wrapper--v0.0.1",
                    "agent-blender-wrapper--v0.0.2",
                    "agent-blender-wrapper--v0.0.9",
                    "agent-blender-wrapper--v0.0.10",
                ],
                "0.0.11",
                "agent-blender-wrapper--v0.0.10",
            ),
            (
                [
                    "agent-blender-wrapper--v0.9.0",
                    "agent-blender-wrapper--v1.0.0-rc.2",
                    "agent-blender-wrapper--v1.0.0-rc.10",
                ],
                "1.0.0",
                "agent-blender-wrapper--v1.0.0-rc.10",
            ),
            (
                [
                    "agent-blender-wrapper--v0.9.0",
                    "agent-blender-wrapper--v1.0.0-rc.2",
                    "agent-blender-wrapper--v1.0.0-rc.10",
                ],
                "1.0.0-rc.3",
                "agent-blender-wrapper--v1.0.0-rc.2",
            ),
        ]
        for tags, version, expected in cases:
            with self.subTest(version=version):
                result = run_prev_tag(tags, "agent-blender-wrapper", version)
                self.assertEqual(
                    result.returncode, 0,
                    msg=f"stdout={result.stdout!r} stderr={result.stderr!r}",
                )
                self.assertEqual(result.stdout.strip(), expected)

    def test_prev_tag_exclusions(self):
        # Every noise tag below must be excluded, leaving only the one real
        # predecessor: the tag being created itself, a src/* marker for the
        # same version, a foreign plugin's tag, and an invalid (leading-zero)
        # version.
        tags = [
            "agent-blender-wrapper--v0.0.8",
            "agent-blender-wrapper--v0.0.9",
            "src/agent-blender-wrapper--v0.0.9",
            "other-plugin--v0.0.9",
            "agent-blender-wrapper--v01.0.0",
        ]
        result = run_prev_tag(tags, "agent-blender-wrapper", "0.0.9")
        self.assertEqual(
            result.returncode, 0,
            msg=f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        self.assertEqual(result.stdout.strip(), "agent-blender-wrapper--v0.0.8")

    def test_prev_tag_first_release(self):
        for tags in ([], ["other-plugin--v1.0.0"]):
            with self.subTest(tags=tags):
                result = run_prev_tag(tags, "agent-blender-wrapper", "0.0.1")
                self.assertEqual(
                    result.returncode, 0,
                    msg=f"stdout={result.stdout!r} stderr={result.stderr!r}",
                )
                self.assertEqual(result.stdout.strip(), "")

    def test_invalid_version_rejected(self):
        for version in ("1.0", "v1.0.0", "01.0.0", "1.0.0-"):
            with self.subTest(version=version):
                result = run_prev_tag([], "agent-blender-wrapper", version)
                self.assertEqual(
                    result.returncode, 2,
                    msg=f"stdout={result.stdout!r} stderr={result.stderr!r}",
                )


class MarketplacePayloadTests(unittest.TestCase):
    """.github/scripts/marketplace-payload.sh"""

    def test_payload_hostile_changelog_roundtrip(self):
        changelog = (
            'Contains "quotes", a \\backslash\\, `backticks`, $(id), ${NAME},\r\n'
            "an EOF\r\n"
            "line that looks like a heredoc terminator,\r\n"
            "a leading /usr/local/bin path,\r\n"
            "unicode: caf\u00e9 \u65e5\u672c\u8a9e,\r\n"
            "and a mention: @user #12"
        )
        env_vars = {
            "NAME": "agent-blender-wrapper",
            "DESC": "Wraps BlenderMCP",
            "REPO": "seretos-agents/agent-blender-wrapper",
            "VERSION": "0.0.3",
            "TAG": "agent-blender-wrapper--v0.0.3",
            "CHANGELOG": changelog,
        }

        result = run_payload(env_vars)
        self.assertEqual(
            result.returncode, 0,
            msg=f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        payload = json.loads(result.stdout)

        self.assertEqual(payload["event_type"], "plugin-release")
        cp = payload["client_payload"]
        self.assertEqual(cp["name"], env_vars["NAME"])
        self.assertEqual(cp["description"], env_vars["DESC"])
        self.assertEqual(cp["repo"], env_vars["REPO"])
        self.assertEqual(cp["category"], "skill")
        self.assertEqual(cp["version"], env_vars["VERSION"])
        self.assertEqual(cp["ref"], env_vars["TAG"])
        self.assertEqual(
            cp["icon"],
            f"https://raw.githubusercontent.com/{env_vars['REPO']}/{env_vars['TAG']}/assets/icon.png",
        )
        self.assertEqual(
            cp["description_url"],
            f"https://raw.githubusercontent.com/{env_vars['REPO']}/{env_vars['TAG']}/description.md",
        )
        self.assertEqual(cp["tags"], ["3d", "creative"])
        self.assertEqual(cp["changelog"], changelog)

    def test_payload_omits_empty_changelog(self):
        base_env_vars = {
            "NAME": "agent-blender-wrapper",
            "DESC": "Wraps BlenderMCP",
            "REPO": "seretos-agents/agent-blender-wrapper",
            "VERSION": "0.0.3",
            "TAG": "agent-blender-wrapper--v0.0.3",
        }

        with self.subTest(case="empty string"):
            result = run_payload(dict(base_env_vars, CHANGELOG=""))
            self.assertEqual(
                result.returncode, 0,
                msg=f"stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            payload = json.loads(result.stdout)
            self.assertNotIn("changelog", payload["client_payload"])

        with self.subTest(case="unset"):
            result = run_payload(dict(base_env_vars))
            self.assertEqual(
                result.returncode, 0,
                msg=f"stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            payload = json.loads(result.stdout)
            self.assertNotIn("changelog", payload["client_payload"])


if __name__ == "__main__":
    unittest.main()
