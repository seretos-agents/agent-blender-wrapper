"""Start the BlenderMCP addon's TCP server inside a running Blender.

Passed to Blender by launch_blender.py as ``blender --python <this file>``.
Blender runs it as ``__main__`` before the startup splash, so ``main()`` only
suppresses the splash and registers a timer; the real work happens on the
first timer tick, once the UI and a scene exist.

Failures print a ``BLENDERMCP_AUTOSTART_ERROR:`` line, which the launcher
watches for in Blender's log (exit code 3).
"""

import importlib
import os

import addon_utils
import bpy

MARKER = "BLENDERMCP_AUTOSTART_ERROR:"
ADDON_MODULE = "addon"

_saved = {}


def _fail(message):
    print(f"{MARKER} {message}", flush=True)


def _prefs():
    return bpy.context.preferences


def _suppress_splash():
    prefs = _prefs()
    _saved["show_splash"] = prefs.view.show_splash
    _saved["is_dirty"] = prefs.is_dirty
    prefs.view.show_splash = False


def _restore_splash():
    if not _saved:
        return
    prefs = _prefs()
    prefs.view.show_splash = _saved["show_splash"]
    prefs.is_dirty = _saved["is_dirty"]
    _saved.clear()


def _load_addon():
    """Enable the addon for this session only (default_set=False persists nothing)."""
    try:
        if not addon_utils.check(ADDON_MODULE)[1]:
            if not addon_utils.enable(ADDON_MODULE, default_set=False):
                raise ImportError(ADDON_MODULE)
        return importlib.import_module(ADDON_MODULE)
    except Exception as exc:  # ImportError, or anything the addon raises on load
        _fail(f"addon module '{ADDON_MODULE}' not found or failed to load ({exc!r})")
        return None


def _start():
    scene = bpy.context.scene
    if scene is None:
        return 0.5
    _restore_splash()
    module = _load_addon()
    if module is None:
        return None
    port = int(os.environ.get("BLENDER_PORT") or 9876)
    try:
        server = getattr(bpy.types, "blendermcp_server", None)
        if server is None:
            server = module.BlenderMCPServer(port=port)
            bpy.types.blendermcp_server = server
        server.start()
        scene.blendermcp_port = port
        scene.blendermcp_server_running = True
    except Exception as exc:
        _fail(f"addon '{ADDON_MODULE}' failed to start its server ({exc!r})")
    return None


def main():
    _suppress_splash()
    bpy.app.timers.register(_start, first_interval=0.5)


if __name__ == "__main__":
    main()
