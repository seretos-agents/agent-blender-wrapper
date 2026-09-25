---
name: blender-game-export
description: >
  Get a finished Blender asset into a game engine correctly, not just
  visually. Use at the end of a modelling job, when an FBX needs to be
  exported for Unity (or another engine) and look right once the FBX
  scale/rotation conventions and axis mapping are actually accounted for —
  not just "looks fine in the viewport". Use for requests like: "export this
  to Unity", "export as FBX", "prepare this asset for the engine", "make
  this game-ready", "what export settings should I use for Unity", "why does
  this look wrong in Unity but fine in Blender", "nach Unity exportieren",
  "als FBX exportieren", "für die Engine exportieren", "als Spiel-Asset
  exportieren", "welche Export-Einstellungen brauche ich für Unity".
---

# blender-game-export

## What this skill is for

Use this skill whenever a request is about **getting a finished asset out of
Blender and into a game engine** — not about building or editing the scene
itself. It picks up where `blender-wrapper` leaves off: that skill drives a
live Blender session (create, transform, material, screenshot); this one
covers the FBX export step and everything that goes wrong between "looks
correct in the Blender viewport" and "looks correct in the engine".

That gap is real and non-obvious: an FBX can render perfectly in Blender and
still carry wrong node scale, wrong node rotation, a mirrored axis, and
zero engine components, entirely invisibly, because the visual result in
both Blender and (often) the engine looks unchanged. This skill exists to
convert "the export settings should be correct" into a checked fact.

**Scope.** Everything here is general Blender → engine knowledge that
applies to any mesh, any project, any art style — unit conversion, axis
conventions, and what the FBX format can and cannot carry. It intentionally
contains **no** project-specific conventions: no grid sizes, no socket
naming schemes, no per-kit rules. If a piece of guidance wouldn't bite
someone exporting an arbitrary asset to Unity, it doesn't belong here — put
project conventions in the project's own docs instead.

**Other engines.** The numbers and the axis mapping in this skill are
Unity-specific, verified against Unity's FBX importer. Godot, Unreal, and
others use different up-axis and forward-axis conventions; re-derive the
mapping for that engine rather than assuming Unity's numbers carry over.

## The export preset

Run this via `execute_blender_code` (see `blender-wrapper`) once the objects
to export are selected. Copy it verbatim and only change what the inline
comments say is safe to change:

```python
bpy.ops.export_scene.fbx(
    filepath=path,
    use_selection=True,
    global_scale=1.0,
    apply_unit_scale=True,
    apply_scale_options="FBX_SCALE_ALL",   # -> node scale 1
    axis_forward="-Z", axis_up="Y",
    bake_space_transform=True,             # -> node rotation 0 (not for rigged assets)
    object_types={"MESH", "EMPTY"},
    mesh_smooth_type="FACE",               # -> flat shading survives
    use_triangles=True,
    add_leaf_bones=False,
    bake_anim=False,
)
```

Three things about this call that are easy to get wrong:

- **`filepath` is a path on the machine running Blender**, not the agent's
  own working directory. If Blender is remote or in a different environment
  than the agent, write to a path that machine can actually resolve.
- **`use_selection=True` means the current selection state decides what gets
  exported.** Set the selection deliberately (`bpy.context.view_layer.objects.active`
  / `obj.select_set(True)`) immediately before the export call — an export
  driven by whatever happened to be selected earlier silently ships too much
  or too little.
- **`object_types={"MESH", "EMPTY"}` excludes armatures on purpose.** For a
  rigged/animated asset, see "Rigged and animated assets" below before using
  this preset unmodified.

## What each setting fixes

| Setting | Symptom it prevents |
|---|---|
| `apply_scale_options="FBX_SCALE_ALL"` | **Node scale arrives as 100, not 1.** FBX's native unit is centimeters. With Blender's default (`'FBX_SCALE_NONE'`), the x100 unit conversion gets baked into every object's local scale. Unity's `fileScale = 0.01` cancels that visually on import, so nothing *looks* wrong — but everything parented under the mesh later (colliders, attach points, VFX, marker transforms) inherits the factor-100 scale, and a non-1 scale on an object with a Rigidbody is a well-known physics problem in Unity. `FBX_SCALE_ALL` instead puts the unit factor into the FBX `GlobalSettings.UnitScaleFactor`, leaving every node's own scale at 1. |
| `bake_space_transform=True` | **Node rotation arrives as 270.02 degrees, not 0.** Blender is Z-up; the engine is Y-up. Left unbaked, that Z-up → Y-up conversion is written as a rotation on the node itself — the mesh isn't axis-aligned in the engine, and float precision means it lands at 270.02 degrees, not a clean 270. That's a per-asset tilt, and it accumulates visibly across pieces that are meant to snap together. `bake_space_transform=True` ("Apply Transform" in the exporter UI) bakes the axis conversion into the mesh data instead, so the node's own rotation reads back as 0. **See the caveat below before using this on a rigged or animated asset.** |
| `mesh_smooth_type="FACE"` | Flat shading only survives export with this set; otherwise the importer falls back to smoothing groups derived from normals, and flat-shaded geometry can arrive smoothed. |

## Rigged and animated assets

`bake_space_transform=True` is right for **static props only**. Blender
itself flags this option as experimental, and it is known-broken with
armatures and animation — baking the space transform on a rigged asset can
corrupt bone transforms or animation curves in ways that are not obvious
until the rig moves.

For a rigged/animated asset:

- Leave `bake_space_transform` **off** (`False`).
- Add `"ARMATURE"` to `object_types` so the armature actually exports.
- Set `bake_anim=True` so animation curves are included.
- Document child rotation axes using the **unbaked** axis convention (see
  the table below, "without baking") rather than assuming the baked mapping
  applies — it doesn't, because the transform was never baked.

Do not "fix" the 270.02-degree rotation on a rigged asset by turning on
`bake_space_transform` — that trades a cosmetic node-rotation number for a
real risk to the rig.

## Axis mapping into engine space

### Position: the import mirrors X

Full mapping from a Blender-space point `(bx, by, bz)` to Unity world space:

```
Unity = (-bx, bz, -by)
```

The X component is **negated** — this is a mirror, not just an axis swap.
Symmetric parts hide this completely, because a mirrored symmetric shape
looks identical. It only surfaces on asymmetric geometry, and it is easy to
miss for exactly that reason: most placeholder/test assets *are* roughly
symmetric.

In practice this mapping has caused two concrete failures from a single
missed X flip in a hand-written measuring helper: a collider box placed in
empty space next to the asset it was meant to wrap, and three wrong rows in
a hand-written documentation table of marker positions.

**Rule:** never hand-derive an engine-space number from a Blender coordinate
inline, ad hoc, per-callsite. Write **one** measuring function that applies
the full `(-bx, bz, -by)` mapping, derive every reported number from that
one function, and sanity-check it against a single known-asymmetric
reference value (a point that isn't on any mirror plane) before trusting any
of its other output.

### Local axes of moving child parts

Documenting "this wheel/lever/needle rotates around its local X" only means
something once you say which export settings that statement is valid for —
the mapping is different depending on whether the space transform was
baked:

| Blender local axis | Without baking (`bake_space_transform=False`) | With baking (`bake_space_transform=True`) |
|---|---|---|
| Local +Z | Unity local axis is still "up" in the *unconverted* frame — a child's local +Z stays world-up in Blender terms, so e.g. an attach marker built with "+X points outward" can arrive with `forward` pointing at the sky if you assume the baked mapping. | Blender local Z → Unity local **Y** |
| Local +Y | Not directly comparable without baking; see caution above. | Blender local Y → Unity local **-Z** |
| Local +X | Not directly comparable without baking; see caution above. | Blender local X → Unity local **X** |

**Rule:** never state a rotation axis without stating which export settings
it is valid for. "The lever rotates around local X" is an incomplete
sentence — "…around local X, with `bake_space_transform=True`" is a
checkable claim.

### Reconciling the position and local-axis mappings
<!-- marker: axis-reconciliation-note -->


The position formula above (`Unity = (-bx, bz, -by)`) and the baked
local-axis row for X (`Blender local X → Unity local X`) disagree on the
sign of X **on purpose** — they are two different mappings, not two
derivations of the same fact, and the disagreement is not a dropped
negation. The position formula maps **points** and bakes in Unity's
FBX-importer X mirror; the local-axis table maps **directions** (rotation
axes, forward/up vectors) through the Z-up → Y-up basis conversion
(`axis_forward="-Z", axis_up="Y"`) alone, and a mirroring transform does not
change the sign of a direction the same way it changes the sign of a point's
coordinate. **Operational rule: use the position formula for points,
offsets, and collider centres; use the local-axis table for rotation axes
and forward/up directions — never convert one into the other.** Naively
pushing a position vector through the position formula to get a rotation
axis is exactly the kind of unverified derivation this skill warns against;
as with everything else here, confirm a rotation axis by watching the part
actually rotate the right way in the engine, not by deriving it from the
position formula.

## Verify the export, don't trust the settings

Blender writes binary FBX, and the format is documented well enough that a
small stdlib-only parser can read back `GlobalSettings` (`UnitScaleFactor`,
`UpAxis`) and every `Model` node's `Lcl Translation` / `Lcl Rotation` /
`Lcl Scaling`. This skill ships one: `scripts/verify_fbx.py`.

```
python scripts/verify_fbx.py path/to/export.fbx
```

What to check in the output:

- Every `Model`'s scale should read `(1.0, 1.0, 1.0)`. If it doesn't, and
  `GlobalSettings.UnitScaleFactor` reads `100`, `apply_scale_options` was
  not `'FBX_SCALE_ALL'`.
- Every `Model`'s rotation should read `(0.0, 0.0, 0.0)` (allow for tiny
  float noise, not a clean ~270). If it's ~270 on some axis,
  `bake_space_transform` was not enabled — correct for a rigged asset (see
  above), wrong for a static prop that was supposed to be baked.
- The script prints `[SCALE != 1]` / `[ROTATION != 0]` flags next to any
  node that fails those checks, so a bad export doesn't require manually
  reading raw numbers.

This turns "these settings should be correct" into a measured fact, without
having to open the engine at all.

**Known limitation:** the bundled parser only understands **binary FBX
7.x** — the format Blender's exporter writes. It detects the binary-FBX
magic header and refuses ASCII FBX or non-FBX input with a clear message
rather than producing wrong numbers from a format it can't actually parse.

## What FBX cannot carry

Colliders, rigidbodies, layers, and tags do not survive the FBX format —
they are engine concepts with no FBX equivalent, so the exporter has
nothing to write. Three ways to handle this, with trade-offs:

- **A small editor script that applies primitive colliders from marker
  transforms.** Recommended default: cheap to write, and the collider
  bounds are derived data rather than something re-authored by hand for
  every asset.
- **A naming convention** (e.g. `UCX_` prefixes) that the engine's importer
  recognizes and turns into collision geometry automatically, where the
  importer supports it. Convenient when it's available, but ties the asset
  to that specific importer feature.
- **`MeshCollider` as a fallback.** Works everywhere, costs more at runtime,
  and gives up the ability to control collision shape independently of
  render geometry. Treat this as the fallback, not the default — reach for
  it only when the other two aren't practical for a given asset.

## Pre-export checklist

- **Flat shading** only survives with `mesh_smooth_type='FACE'` (see the
  settings table above).
- **Material count = submesh count = draw calls.** For low-poly kits, one
  shared palette texture with flat colour fields, plus a constant UV per
  face, gives one material and one submesh for the whole kit. Two follow-on
  traps: place each face's UV at the *centre* of its colour cell with margin
  for bilinear filtering/mip bleeding, and never run Smart UV Project
  afterwards — it overwrites the palette UVs you just set.
- **Pivot = object origin.** Build geometry around the intended origin
  rather than moving the object afterwards to fake a pivot, and export each
  asset from the world origin — otherwise the prefab carries a permanent
  positional offset that has to be corrected on every use.
- **Polygon cross-sections have asymmetric bounds.** A hexagonal tube of
  radius `R` measures `2R` across one axis and `1.73R` (≈R·√3) across the
  other — it is not round in bounding-box terms. If a spec demands equal
  extent on both axes, the cross-section needs vertices on both axes (e.g.
  an octagon starting at 0 degrees, not a hexagon).
- **Call `bpy.context.view_layer.update()`** before reading `matrix_world`
  after changing an object's transform in the same script — otherwise a
  measuring script reads a stale, pre-update value.
- **Don't ship a "contact sheet" file** containing every asset in the kit
  alongside the individual per-asset files. Importing both into the same
  project duplicates every mesh and material.

## Pitfalls

- **The export path is on the Blender machine, not the agent's own working
  directory.** `filepath` must resolve on whatever machine is actually
  running Blender.
- **Selection state, not scene state, decides what `use_selection=True`
  exports.** Set selection immediately before the export call; don't rely
  on whatever was selected by an earlier step.
- **Re-run `verify_fbx.py` after any settings change**, not just once at the
  start — a single wrong argument (or reverting to Blender's default
  `apply_scale_options`) silently reintroduces the scale-100 or
  rotation-270 problem, and the viewport gives no warning either way.
- **These numbers were measured, not derived from documentation.** The
  270.02-degree figure, the `(-bx, bz, -by)` mapping, and the local-axis
  table all come from checking a real export against Unity's actual FBX
  importer — treat any similar claim about export behaviour as unverified
  until it's been checked the same way, with `verify_fbx.py` or the engine
  itself.
