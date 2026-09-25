# agent-blender-wrapper

A Claude Code **skill** plugin. Pairs the external [BlenderMCP](https://github.com/ahujasid/blender-mcp) server with a skill so Claude can drive Blender — inspecting scenes, creating and modifying objects, applying materials, and sourcing assets — through structured MCP operations instead of blind Python scripting.

The MCP server is declared inline in both plugin manifests. When the plugin is installed, the host agent launches BlenderMCP automatically via `uvx` — no manual server setup. The server is pinned to an exact version (`blender-mcp==1.8.0`) so `uvx` resolves the same cached environment on every start.

## Prerequisites

### 1. `uv`

`uvx` (bundled with `uv`) launches the server on demand without a manual `pip install`.
Install: https://docs.astral.sh/uv/getting-started/installation/

### 2. Blender + the BlenderMCP addon

The MCP server is only a bridge — the actual work happens inside a running Blender session that has the BlenderMCP addon connected. **Without this, every tool call fails.**

1. Blender 3.0 or newer, running with a GUI.
2. Download `addon.py` from https://github.com/ahujasid/blender-mcp.
3. Blender → `Edit > Preferences > Add-ons > Install...` → select `addon.py`.
4. Enable **Interface: Blender MCP**.
5. In the 3D View, press `N` to open the sidebar → **BlenderMCP** tab → click **Connect to Claude**.

Step 5 is per Blender session. The addon listens on `localhost:9876`; if you change the port there, set `BLENDER_HOST` / `BLENDER_PORT` accordingly.

### 3. Optional integrations

Poly Haven (free assets), Sketchfab, Hyper3D Rodin, and Hunyuan3D are toggled in the same sidebar panel. Sketchfab and the AI generators need an API key; Poly Haven does not. The skill checks each integration's status before relying on it.

## Install

```
/plugin marketplace add seretos-agents/modular-software-factory
/plugin install agent-blender-wrapper@modular-software-factory
```

## Telemetry

Upstream BlenderMCP enables telemetry by default: anonymous session IDs, tool names, timings, errors, and platform/Blender versions are POSTed to a third-party endpoint. **This plugin disables it** by setting `BLENDER_MCP_DISABLE_TELEMETRY=true` in the `mcpServers` env of both manifests.

Because a manifest `env` value takes precedence over your shell environment, re-enabling telemetry means removing that `env` block from the manifest — setting the variable yourself won't override it.

## What the skills teach

See `skills/blender-wrapper/SKILL.md` for the full content: the inspect → change → verify loop, the complete tool inventory (scene/object introspection, viewport screenshots, `execute_blender_code`, Poly Haven, Sketchfab, Hyper3D Rodin, Hunyuan3D), recipes for common requests, and the pitfalls that matter — chiefly that `execute_blender_code` runs arbitrary Python inside the user's Blender.

See `skills/blender-game-export/SKILL.md` for getting a finished asset out of Blender and into a game engine: the copy-verbatim FBX export preset, why default settings leave node scale at 100 and node rotation at ~270°, the engine-space axis mapping (including the X mirror on import), the `bake_space_transform` caveat for rigged/animated assets, what FBX cannot carry (colliders, rigidbodies, tags), and a bundled stdlib-only script (`scripts/verify_fbx.py`) that reads a binary FBX back to check the export instead of trusting the settings.

## Troubleshooting

**Every tool errors with a connection failure.** Blender isn't running, the addon isn't enabled, or "Connect to Claude" wasn't clicked this session. Retrying won't help — fix the setup.

**The very first command after connecting fails, the next one works.** Known upstream behaviour; the socket isn't ready on the first call. A single retry is expected.

**A long operation times out after ~180 seconds.** The socket timeout. Split the work into smaller steps rather than resending the same call.

**"Server not loaded" right after install.** Cold `uvx` start: the environment is built before the first JSON-RPC byte, which can exceed the host's handshake timeout. Reconnect the MCP server (`/mcp` → reconnect) — it starts cleanly once cached. To warm the cache ahead of time:

```
uvx --from blender-mcp==1.8.0 blender-mcp --help
```

Do not otherwise run the server manually — the host owns that process, and two instances will fight over the socket.
