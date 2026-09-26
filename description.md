# agent-blender-wrapper

Turns Blender into something Claude can actually operate. This plugin bundles
the headless BlenderMCP server together with a skill that teaches the agent how
to drive a live Blender session — reading the real scene, changing it, and
visually verifying the result — instead of writing Python into the dark.

## Key features

- **Zero-setup MCP server** — BlenderMCP is declared inline in the plugin
  manifest and launched via `uvx` on install. No manual server, no
  `pip install`, no config step.
- **Scene-aware, not guess-driven** — the skill's core loop is inspect →
  change → screenshot. The agent reads actual object names and transforms
  before touching anything, and verifies the viewport afterwards.
- **Asset sourcing built in** — search and import from **Poly Haven** (HDRIs,
  textures, models) and **Sketchfab**, with previews before download, so a
  chair is a real chair instead of eight cubes.
- **AI model generation** — generate 3D assets from text or images via
  **Hyper3D Rodin** or **Hunyuan3D**, including the async poll-and-import
  workflow.
- **Full `bpy` scripting when it's the right tool** — arbitrary Python
  execution inside Blender, with the skill's guardrails on how to keep it
  small, non-destructive, and verifiable.
- **Game-engine-ready FBX export** — unit scale, axis conversion, and a
  bundled verifier so an export is checked, not just assumed correct.
- **Telemetry off by default** — upstream BlenderMCP reports usage to a
  third-party endpoint unless disabled; this plugin disables it in the
  manifest.
- **Works in Claude Code and Codex** — ships both a `.claude-plugin` and a
  `.codex-plugin` manifest from one repository.

## Requirements

- **Blender 3.0+** running with a GUI.
- The **BlenderMCP addon** (`addon.py` from
  https://github.com/ahujasid/blender-mcp) installed in Blender and started per
  session via "Connect to Claude" in the 3D View sidebar.
- `uv` on the host machine; `uvx` launches the server on demand. See
  https://docs.astral.sh/uv/getting-started/installation/
- Optional: API keys in the addon panel for Sketchfab, Hyper3D Rodin, and
  Hunyuan3D. Poly Haven needs none.

## A good fit if you want to

- Block out or dress a 3D scene conversationally.
- Have an agent inspect and fix an existing Blender file rather than start over.
- Pull real assets and HDRI lighting into a scene without leaving the chat.
