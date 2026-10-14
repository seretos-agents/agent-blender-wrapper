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
   installed. The addon's TCP server listens on `localhost:9876`
   (`BLENDER_HOST` / `BLENDER_PORT` override it) once it is started — either by
   this skill's launcher script (see "When a tool can't reach Blender") or by
   the user clicking "Connect to Claude" in the 3D View sidebar (`N` →
   BlenderMCP tab).
2. **The BlenderMCP server**, launched automatically by this plugin via `uvx`.
   It is a thin bridge: it accepts MCP tool calls and forwards them over that
   TCP socket.
3. **The agent**, calling the MCP tools.

Consequences worth internalising:

- **There is no offline mode.** If nothing is listening on the addon's port,
  every tool fails. That is a setup problem, not a tool-usage problem — don't
  retry the tool blindly; bring the session up with the launcher as described
  in "When a tool can't reach Blender".
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

### When a tool can't reach Blender

Every other recipe depends on this one. When a BlenderMCP tool call fails with
a connection error — "Could not connect to Blender", connection refused, nothing
listening on `BLENDER_HOST`:`BLENDER_PORT` (default `localhost:9876`) — start
Blender yourself. Do not ask the user first.

1. Run the launcher from a shell. Its path is relative to this skill's own base
   directory:

   ```sh
   python <this skill's directory>/scripts/launch_blender.py
   ```

   If `python` is not on `PATH`, run
   `uv run --no-project python <this skill's directory>/scripts/launch_blender.py`
   instead. The launcher waits up to 60 seconds for the port (`--timeout`
   changes that), so give the shell call a timeout longer than that. It honours
   `BLENDER_PORT`, `BLENDER_HOST` and `BLENDER_PATH`, writes Blender's output
   to a log file (`--log` changes where), and starts nothing if the port is
   already listening.
2. Act on its exit code:

   | Exit | Meaning | Next action |
   |---|---|---|
   | `0` | BlenderMCP is listening (started now, or already was) | Retry the failed tool call. |
   | `2` | Blender executable not found | Keep the paths the launcher says it tried. Run the check (step 3), then tell the user (step 4). |
   | `3` | Blender started, but the BlenderMCP addon is missing or failed to start | Keep the `BLENDERMCP_AUTOSTART_ERROR:` line the launcher printed. Run the check (step 3), then tell the user (step 4). |
   | `1` | Blender failed to start, exited early, or the port did not open in time | Keep the log path the launcher printed. Run the check (step 3), then tell the user (step 4). Do not relaunch. |

3. Before you tell the user anything, run the prerequisite check yourself — do
   not hand the command to the user instead:

   ```sh
   python <this skill's directory>/scripts/check_prerequisites.py
   ```

   Use the same `uv run --no-project python …` fallback as in step 1, and add
   `--blender <path>` if you already know where Blender is. Do not pass
   `--deep`: it starts another Blender in the background for up to 120 seconds
   to read the add-ons enabled in the user's preferences, and the launcher
   enables the addon for its session only, so that state decides nothing here.
   The check prints one JSON object; read its fields and ignore its exit code.
4. Tell the user what the report shows, together with what you kept from the
   launcher:

   - `blender.path` is `null`: Blender was not found. List `blender.tried`, ask
     where Blender is installed, then rerun the launcher once with
     `--blender <path>`.
   - `addon.installed` is `false`: ask the user to install `addon.py` for
     Blender `blender.version` (Preferences → Add-ons) and name
     `addon.searched` as the directory that was looked in (if `blender.version`
     is `null`, nothing was searched — say so). Detection only looks for the
     file name; if the user says the addon is installed, trust the launcher's
     `BLENDERMCP_AUTOSTART_ERROR:` line over the report.
   - `addon.installed` is `true` and the launcher exited `3`: the addon file is
     there but did not load or start. Relay the `BLENDERMCP_AUTOSTART_ERROR:`
     line and the launcher's log path.
   - `addon.enabled` is `null`: it was not checked. Never report it as
     disabled.
   - `socket.listening` is `true` while tools still fail: something that is not
     BlenderMCP is answering on `socket.host`:`socket.port`, or the addon and
     the server use different ports. Name that `host:port`.
   - `extensions.mpfb.*` is never the cause of a connection failure. Mention
     MPFB only if the user's own task needs it.

Run the launcher at most once per failure. If the tool call still fails after
exit `0` (including "already listening"), allow the single retry described
under Pitfalls; if that fails too, do not relaunch — run the check (step 3) and
report as in step 4.

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
  be ready on the very first call; a single retry normally succeeds. A failure
  that persists is a setup issue, not something to retry around — handle it
  with "When a tool can't reach Blender" (the launcher, then the check before
  you involve the user).
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
- **Don't start the BlenderMCP server manually.** `uvx blender-mcp` in a terminal is not
  how this works — the host launches and owns the server process. Two instances
  fighting over the same socket is a common self-inflicted failure.
- **Downloaded PolyHaven textures aren't applied automatically.**
  `download_polyhaven_asset` stages the texture; `set_texture` puts it on an
  object. Missing the second step looks like "the download didn't work".
