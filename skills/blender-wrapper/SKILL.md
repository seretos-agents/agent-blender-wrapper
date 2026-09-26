---
name: blender-wrapper
description: >
  Drive a running Blender session through the BlenderMCP server's structured
  tools instead of guessing at scene state or writing blind Python. Use when
  inspecting a Blender scene or a specific object, creating/modifying/deleting
  3D objects, applying or creating materials, taking a viewport screenshot to
  verify a result, downloading assets from PolyHaven or Sketchfab, or
  generating 3D models with Hyper3D Rodin or Hunyuan3D.
  Also use for requests like: "what's in the Blender scene", "add a cube /
  sphere / light / camera", "move / scale / rotate object X", "make X red /
  metallic", "apply a wood texture", "show me the viewport", "render what it
  looks like now", "download an HDRI", "find a chair model", "generate a 3D
  model of X", "was ist in der Blender-Szene", "füge einen Würfel hinzu",
  "verschiebe / skaliere / drehe Objekt X", "mach X rot", "zeig mir das
  Viewport", "lade ein HDRI", "generiere ein 3D-Modell von X".
---

# blender-wrapper

## What this skill is for

Use this skill whenever a request touches a **live Blender session**: inspecting
what is in the scene, building or editing geometry, assigning materials,
lighting a shot, pulling in external assets, or verifying visually what the
scene currently looks like.

Getting a finished asset **out** of Blender and into a game engine (FBX
export settings, unit/axis conversion, verifying the export) is out of scope
here — use the `blender-game-export` skill for that.

The central rule is: **look before you act, and look again after you act.**
Blender scene state is persistent and mutable — the agent does not hold it, the
running Blender process does. Every assumption about object names, transforms,
or materials must come from `get_scene_info` / `get_object_info`, and every
non-trivial change should be confirmed with `get_viewport_screenshot`.

## Mental model

Three processes are involved, and all three must be up:

1. **Blender** itself, running with a GUI, with the **BlenderMCP addon**
   installed *and* "Connect to Claude" clicked in the 3D View sidebar (`N` →
   BlenderMCP tab). The addon opens a TCP server on `localhost:9876`.
2. **The BlenderMCP server**, launched automatically by this plugin via `uvx`.
   It is a thin bridge: it accepts MCP tool calls and forwards them over that
   TCP socket.
3. **The agent**, calling the MCP tools.

Consequences worth internalising:

- **There is no offline mode.** If Blender isn't running with the addon
  connected, every tool fails. That is a setup problem, not a tool-usage
  problem — tell the user to start Blender and click "Connect", don't retry.
- **The scene is shared, mutable state.** The user may have moved things
  between two of your tool calls. Re-read scene state rather than trusting a
  stale answer from earlier in the conversation.
- **Object names are the addressing scheme.** Nearly every tool takes an
  `object_name`. Names are what Blender's outliner shows and they are unique
  per scene; get them from `get_scene_info`, never invent them. Blender also
  silently suffixes duplicates (`Cube.001`), so a name you "expect" may not be
  the name that exists.
- **The optional integrations are off until enabled.** PolyHaven, Sketchfab,
  Hyper3D Rodin and Hunyuan3D are toggles in the addon's sidebar panel (some
  need an API key). Each has a `get_*_status` tool — check it before building a
  plan around that integration.
- **`user_prompt` is a telemetry field, and on `get_scene_info` it is
  *required*.** Most tools accept a `user_prompt` parameter documented as "the
  original user prompt that led to this tool call". It is never forwarded to
  Blender and has no effect on the result. This plugin ships with telemetry
  disabled (`BLENDER_MCP_DISABLE_TELEMETRY=true`), so the value goes nowhere —
  but `get_scene_info` still rejects the call without it. Pass a short
  paraphrase of the request; elsewhere it is optional and can be omitted.

## Tool inventory

### Core — scene, objects, code

| Tool | Best for |
|---|---|
| `get_scene_info` | The starting point for almost everything. Lists the scene's objects, names, types, and basic transforms. Call this first. |
| `get_object_info` | Detail on one object (`object_name`): full transform, mesh stats, materials. Use after `get_scene_info` narrows down the target. |
| `get_viewport_screenshot` | PNG of the current 3D viewport (`max_size`, default 1000). The only way to actually *see* the result. Use it to verify, not to guess. |
| `execute_blender_code` | Runs arbitrary Python (`code`) inside Blender with the full `bpy` API. This is the workhorse for creating, transforming, deleting objects, and building materials — but see Pitfalls. |

There are **no** dedicated `create_object` / `set_material` tools in this server
version: creating a cube, moving an object, assigning a material, adding a light
or camera all go through `execute_blender_code` with `bpy`. The typed tools
cover *reading* the scene and *sourcing* assets.

### PolyHaven — free HDRIs, textures, models

| Tool | Best for |
|---|---|
| `get_polyhaven_status` | Check whether the integration is enabled before planning around it. |
| `get_polyhaven_categories` | Category list for an `asset_type` (`hdris`, `textures`, `models`). |
| `search_polyhaven_assets` | Find assets by `asset_type` + optional comma-separated `categories`. |
| `download_polyhaven_asset` | Download and import by `asset_id` + `asset_type`, with `resolution` (default `1k`) and optional `file_format`. HDRIs become world lighting; models get imported; textures are staged for `set_texture`. |
| `set_texture` | Apply an already-downloaded PolyHaven texture (`texture_id`) to an object (`object_name`). Download first, then apply. |

### Sketchfab — searchable model library

| Tool | Best for |
|---|---|
| `get_sketchfab_status` | Enablement check (needs an API key in the addon). |
| `search_sketchfab_models` | Search by `query`, optional `categories`, `count` (default 20), `downloadable` (default true). Keep `downloadable=true` — non-downloadable hits cannot be imported. |
| `get_sketchfab_model_preview` | Thumbnail for a `uid` — use it to pick between candidates before committing to a download. |
| `download_sketchfab_model` | Import by `uid` with a `target_size` for scaling into the scene. |

### Hyper3D Rodin — AI model generation

| Tool | Best for |
|---|---|
| `get_hyper3d_status` | Enablement check (needs an API key / the addon's trial key). |
| `generate_hyper3d_model_via_text` | Generate from `text_prompt`, optionally constrained by `bbox_condition` (relative X/Y/Z proportions). |
| `generate_hyper3d_model_via_images` | Generate from `input_image_paths` (local) or `input_image_urls` (remote). |
| `poll_rodin_job_status` | Poll the job with the `subscription_key` / `request_id` the generate call returned. Generation is asynchronous. |
| `import_generated_asset` | Import the finished asset into the scene under `name`, using the same `task_uuid` / `request_id`. |

### Hunyuan3D — alternative AI generation

| Tool | Best for |
|---|---|
| `get_hunyuan3d_status` | Enablement check. |
| `generate_hunyuan3d_model` | Generate from `text_prompt` or `input_image_url`. |
| `poll_hunyuan_job_status` | Poll with the returned `job_id`. |
| `import_generated_asset_hunyuan` | Import the finished asset (`name`, `zip_file_url`). |

## Patterns and recipes

### Any scene change at all

1. `get_scene_info` — establish what exists and what the objects are actually called.
2. Make the change (`execute_blender_code`, or a download/import tool).
3. `get_viewport_screenshot` — confirm it looks right.

Step 3 is not optional for anything visual. Code that runs without an exception
routinely produces an object that is inside another object, scaled 100× wrong,
or outside the camera frustum. The screenshot is the only real feedback loop.

### Modify a specific object

1. `get_scene_info` to get the exact name.
2. `get_object_info` on that name for its current transform and materials — do
   not assume the object is at the origin with unit scale.
3. `execute_blender_code` operating on `bpy.data.objects["<exact name>"]`,
   applying a *delta* relative to what step 2 reported.
4. `get_viewport_screenshot` to verify.

### Source an asset instead of modelling it

Prefer a real asset over hand-built geometry whenever one exists — a scripted
"chair" is eight cubes; a Sketchfab chair is a chair.

1. Check the relevant `get_*_status` tool.
2. PolyHaven: `search_polyhaven_assets` → `download_polyhaven_asset`.
   Sketchfab: `search_sketchfab_models` → `get_sketchfab_model_preview` on the
   top candidates → `download_sketchfab_model` with a sensible `target_size`.
3. `get_scene_info` — the import's actual object name is rarely what you'd
   guess.
4. `get_viewport_screenshot` — imported assets frequently arrive at the wrong
   scale or orientation; fix with `execute_blender_code` and re-verify.

Fall back to scripting geometry only when every integration is disabled or
nothing suitable is found.

### Generate a model with AI

1. `get_hyper3d_status` (or `get_hunyuan3d_status`).
2. `generate_hyper3d_model_via_text` / `..._via_images` — keep the returned
   `subscription_key` / `request_id` (or `job_id`).
3. Poll with `poll_rodin_job_status` / `poll_hunyuan_job_status` until it
   reports completion. Do not import before the job is done.
4. `import_generated_asset` / `import_generated_asset_hunyuan`.
5. `get_scene_info` + `get_viewport_screenshot`, then fix scale/placement.

### Light a scene

An HDRI is usually the fastest good-looking result:
`download_polyhaven_asset` with `asset_type="hdris"` sets world lighting in one
call. Only script `bpy.ops.object.light_add` when a specific, directed light is
actually needed.

## Pitfalls

- **`execute_blender_code` runs arbitrary Python inside the user's Blender with
  full `bpy` access.** It can delete their work, overwrite files, and reach the
  filesystem. Keep each call small and single-purpose, never bundle unrelated
  operations, and never write code that deletes or overwrites something the user
  didn't ask you to touch (`bpy.ops.wm.read_homefile`, `bpy.ops.wm.save_*`,
  scene-wide `select_all` + `delete` are all destructive). If a request would
  discard existing work, confirm with the user first.
- **Big scripts fail opaquely.** A 60-line script that errors halfway leaves the
  scene half-modified with no clean rollback. Break complex work into several
  small `execute_blender_code` calls, screenshotting between them.
- **The first command after connecting often fails.** The addon's socket may not
  be ready on the very first call; a single retry normally succeeds. Persistent
  failures mean Blender is closed, the addon is disabled, or "Connect to Claude"
  was never clicked — a setup issue, not something to retry around.
- **Long operations hit a 180-second socket timeout** and surface as an error
  suggesting you simplify the request. Split the work rather than resending the
  same heavy call.
- **`get_viewport_screenshot` shows the *viewport camera*, not the scene
  camera,** and only what the user's current view is pointed at. If the result
  looks empty, the view may simply be aimed elsewhere or zoomed in — frame the
  object via `execute_blender_code` before concluding the object wasn't created.
- **Never guess object names.** Blender auto-suffixes duplicates (`Cube.001`)
  and imports name objects after their source file. Always re-read
  `get_scene_info` after any import or creation.
- **Don't start the server manually.** `uvx blender-mcp` in a terminal is not
  how this works — the host launches and owns the server process. Two instances
  fighting over the same socket is a common self-inflicted failure.
- **Downloaded PolyHaven textures aren't applied automatically.**
  `download_polyhaven_asset` stages the texture; `set_texture` puts it on an
  object. Missing the second step looks like "the download didn't work".
