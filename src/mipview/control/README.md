# MipView Control Command Layer

## Overview

The MipView control command layer is a local command interface for controlling an already-running MipView GUI. It is intended for terminal-side tools and future agent workflows that need structured access to viewer state, screenshots, cursor movement, patch operations, projection export, and voxel-space annotation.

External clients should use the command layer through `mipview-ctl` or the local IPC protocol. They should not import or mutate Qt widgets directly. Commands operate on MipView state and existing GUI logic, and every command returns structured JSON through `CommandResult`.

Most state-changing commands require a NIfTI image to already be loaded in the running GUI. Screenshots are visual references only; voxel coordinates, patch bounds, raw patch data, and annotation masks are the coordinate ground truth.

## Content List

- [Mechanism](#mechanism)
- [Direct Command Usage](#direct-command-usage)
- [Command Reference](#command-reference)
- [`viewer.status`](#viewerstatus)
- [`viewer.screenshot`](#viewerscreenshot)
- [`viewer.export_state`](#viewerexport_state)
- [`cursor.move`](#cursormove)
- [`patch.size`](#patchsize)
- [`patch.center`](#patchcenter)
- [`patch.select`](#patchselect)
- [`patch.translate`](#patchtranslate)
- [`patch.export_raw`](#patchexport_raw)
- [`patch.save`](#patchsave)
- [`patch.screenshot`](#patchscreenshot)
- [`projection.mode`](#projectionmode)
- [`projection.save`](#projectionsave)
- [`graph.*`](#graph-commands)
- [`annotation.create`](#annotationcreate)
- [`annotation.paint_stroke`](#annotationpaint_stroke)
- [`annotation.erase_stroke`](#annotationerase_stroke)
- [`annotation.save`](#annotationsave)
- [Vertical Slice Example](#vertical-slice-example)

## Mechanism

The command path is:

```text
mipview-ctl or JSON client
    -> Unix domain socket
    -> MipViewIpcServer
    -> Qt main-thread dispatcher
    -> CommandRegistry
    -> MipViewController
    -> GUI/state/annotation logic
```

The default socket path is:

```text
/tmp/mipview-${USER}/session.sock
```

Use `--socket` to connect to a non-default socket:

```bash
mipview-ctl --socket /path/to/session.sock status
```

IPC requests are newline-delimited JSON objects:

```json
{"id": "cmd-001", "command": "cursor.move", "args": {"x": 120, "y": 80, "z": 45}}
```

Responses include the request ID and a structured command result:

```json
{"id": "cmd-001", "ok": true, "message": "Cursor moved.", "data": {"cursor": [120, 80, 45]}}
```

Failed commands also return JSON with `"ok": false`. The `mipview-ctl` CLI prints the response JSON and exits with a non-zero status when `"ok"` is false.

## Direct Command Usage

Use `mipview-ctl send` to call any registered command directly:

```bash
mipview-ctl send cursor.move --args-json '{"x": 120, "y": 80, "z": 45}'
```

The `--args-json` value must be a JSON object matching the command argument names.

## Command Reference

### `viewer.status`

Function: Report whether an image is loaded plus current cursor, annotation, patch-selection, and segmentation summary.

CLI usage:

```bash
mipview-ctl status
```

Direct command:

```json
{"command": "viewer.status", "args": {}}
```

Parameters: none.

Example:

```bash
mipview-ctl status
```

### `viewer.screenshot`

Function: Save a full-window screenshot and return the screenshot path plus viewer state.

CLI usage:

```bash
mipview-ctl viewer screenshot PATH
```

Direct command:

```json
{"command": "viewer.screenshot", "args": {"path": "./current.png"}}
```

Parameters:

| Name | Type | Description |
| --- | --- | --- |
| `path` | `str` | Output image path. The parent directory must exist and be writable. |

Example:

```bash
mipview-ctl viewer screenshot ./current.png
```

### `viewer.export_state`

Function: Export machine-readable viewer state including image shape, spacing, cursor, patch, projection, segmentation, annotation, and affine when available.

CLI usage:

```bash
mipview-ctl viewer state PATH
```

Direct command:

```json
{"command": "viewer.export_state", "args": {}}
```

Parameters: none for IPC. The CLI writes the returned `data` object to `PATH`.

Example:

```bash
mipview-ctl viewer state ./state.json
```

### `cursor.move`

Function: Move the cursor to an in-bounds voxel coordinate.

CLI usage:

```bash
mipview-ctl cursor move X Y Z
```

Direct command:

```json
{"command": "cursor.move", "args": {"x": 120, "y": 80, "z": 45}}
```

Parameters:

| Name | Type | Description |
| --- | --- | --- |
| `x` | `int` | X voxel coordinate. |
| `y` | `int` | Y voxel coordinate. |
| `z` | `int` | Z voxel coordinate. |

Example:

```bash
mipview-ctl cursor move 120 80 45
```

### `patch.size`

Function: Set the fixed patch size in voxel units.

CLI usage:

```bash
mipview-ctl patch size SX SY SZ
```

Direct command:

```json
{"command": "patch.size", "args": {"sx": 64, "sy": 64, "sz": 10}}
```

Parameters:

| Name | Type | Description |
| --- | --- | --- |
| `sx` | `int` | Patch size along X; must be positive. |
| `sy` | `int` | Patch size along Y; must be positive. |
| `sz` | `int` | Patch size along Z; must be positive. |

Example:

```bash
mipview-ctl patch size 64 64 10
```

### `patch.center`

Function: Set the patch center to an in-bounds voxel coordinate.

CLI usage:

```bash
mipview-ctl patch center X Y Z
```

Direct command:

```json
{"command": "patch.center", "args": {"x": 120, "y": 80, "z": 45}}
```

Parameters:

| Name | Type | Description |
| --- | --- | --- |
| `x` | `int` | X voxel coordinate. |
| `y` | `int` | Y voxel coordinate. |
| `z` | `int` | Z voxel coordinate. |

Example:

```bash
mipview-ctl patch center 120 80 45
```

### `patch.select`

Function: Extract and store the current patch using the current patch bounds.

CLI usage:

```bash
mipview-ctl patch select
```

Direct command:

```json
{"command": "patch.select", "args": {}}
```

Parameters: none.

Example:

```bash
mipview-ctl patch select
```

### `patch.export_raw`

Function: Export selected patch arrays and metadata to a compressed `.npz`
archive. When an active annotation mask or file-backed active segmentation is
available, their patch arrays are exported with the same selected patch bounds as
the image patch.

CLI usage:

```bash
mipview-ctl patch export-raw PATH
```

Direct command:

```json
{"command": "patch.export_raw", "args": {"path": "./patch_raw.npz"}}
```

Parameters:

| Name | Type | Description |
| --- | --- | --- |
| `path` | `str` | Output `.npz` path. The parent directory must exist and be writable. |

The `.npz` archive always includes:

| Key | Description |
| --- | --- |
| `image_patch` | Raw selected image patch array. |
| `bounds` | Half-open source voxel bounds as `[[x0, x1], [y0, y1], [z0, z1]]`. |
| `patch_size` | Current requested patch size as `[sx, sy, sz]`. |
| `patch_center` | Current patch center voxel as `[x, y, z]`, when available. |
| `affine` | Patch affine. |
| `voxel_spacing` | Patch voxel spacing. |
| `source_image_path` | Loaded source image path, or an empty string. |
| `viewer_state_json` | JSON string containing the exported viewer state. |

The archive conditionally includes:

| Key | Included when |
| --- | --- |
| `annotation_patch` | An active annotation mask exists. The patch is extracted in voxel space using the same bounds as `image_patch`. |
| `segmentation_patch` | The active segmentation is a loaded file segmentation. Annotation-backed segmentations are not duplicated here. |

The command response includes `annotation_included` and `segmentation_included`
booleans so clients can tell which optional arrays were written.

This command exports selected patch arrays only. It does not provide standalone
full-volume annotation or segmentation `.npz` export commands.

Example:

```bash
mipview-ctl patch export-raw ./patch_raw.npz
```

### `patch.save`

Function: Save the selected image patch as NIfTI.

CLI usage:

```bash
mipview-ctl patch save PATH
```

Direct command:

```json
{"command": "patch.save", "args": {"path": "./patch.nii.gz"}}
```

Parameters:

| Name | Type | Description |
| --- | --- | --- |
| `path` | `str` | Output NIfTI path. |

Example:

```bash
mipview-ctl patch save ./patch.nii.gz
```

### `patch.screenshot`

Save only an open patch window's triplanar viewer, including its current zoom,
pan, projections, overlays, vectors, and angle legends. Controls are excluded.

```bash
mipview-ctl patch screenshot SESSION_ID ./triplanar.png --resolution-percent 150
```

The matching direct command is `patch.screenshot` with `session_id`, `path`, and
`resolution_percent`. Resolution must be from 1 through 200 and defaults to 100.
PNG and JPEG are supported; JPEG uses fixed encoding quality 95.

### `patch.translate`

Move one open patch window within its source image while preserving its shape.
Directions use canonical RPI anatomical axes. Translation refreshes the image,
segmentation, annotation, projection masks, and active MIP/MinIP views without
moving the main-window patch selector or other patch windows.

```bash
mipview-ctl patch translate SESSION_ID R
mipview-ctl patch translate SESSION_ID S --voxels 5
mipview-ctl patch translate SESSION_ID P --discard-local-work
```

The direct command is `patch.translate` with `session_id`, `direction`, optional
positive `voxels` (default `1`), and optional `discard_local_work` (default
`false`). Directions are `L`, `R`, `A`, `P`, `S`, and `I`. If processing history
or graph annotations exist, the command fails unless `discard_local_work` is
true. Results include requested and actual displacement, bounds, center, shape,
boundary status, and reset status.

### `projection.mode`

Function: Set the projection mode to MIP or MinIP.

CLI usage:

```bash
mipview-ctl projection mode MODE
```

Direct command:

```json
{"command": "projection.mode", "args": {"mode": "minip"}}
```

Parameters:

| Name | Type | Description |
| --- | --- | --- |
| `mode` | `str` | Projection mode. Accepted values are `mip` and `minip`, case-insensitively. |

Example:

```bash
mipview-ctl projection mode minip
```

### `projection.save`

Function: Save the selected patch projection image for one anatomical view.
With `--annotation-preview`, overlay the active annotation mask projection onto the
exported grayscale image projection.

CLI usage:

```bash
mipview-ctl projection save VIEW PATH
mipview-ctl projection save VIEW PATH --annotation-preview
```

Direct command:

```json
{"command": "projection.save", "args": {"view": "axial", "path": "./patch_axial_minip.png"}}
{"command": "projection.save", "args": {"view": "axial", "path": "./patch_axial_minip.png", "annotation_preview": true}}
```

Parameters:

| Name | Type | Description |
| --- | --- | --- |
| `view` | `str` | Projection view: `axial`, `coronal`, or `sagittal`. |
| `path` | `str` | Output image path. The parent directory must exist and be writable. |
| `annotation_preview` | `bool` | Optional. When true, project the active annotation patch with MIP and overlay it on the image projection. |

The image projection uses the current projection mode (`MIP` or `MinIP`). The
annotation preview always uses MIP, even when the image projection mode is
`MinIP`. This command-layer preview is independent of the GUI patch-window view
export overlay path.

If annotation preview is requested but there is no active annotation mask, or
the selected patch contains no nonzero annotation labels, the command still saves
the grayscale projection. The JSON response includes a warning in
`data.warnings`, and `mipview-ctl` prints the warning to stderr.

Example:

```bash
mipview-ctl projection save axial ./patch_axial_minip.png
mipview-ctl projection save axial ./patch_axial_minip.png --annotation-preview
```

### Graph commands

Graph commands target an open patch window by the session ID reported in
`viewer.export_state` under `graph_sessions`. The graph is shared across all
three projections and stored in patch-local source voxel space. `add-node` uses
oriented 2D projection indices and resolves depth from the current finite
MIP/MinIP extremum; `add-voxel-node` accepts explicit patch-local `(x, y, z)`
coordinates. Node/edge editing commands require Graph mode; clearing the complete
graph remains available whenever the session contains graph elements.

```bash
mipview-ctl graph status SESSION_ID
mipview-ctl graph open ./vessels.mipgraph.json
mipview-ctl graph save SESSION_ID ./vessels.mipgraph.json
mipview-ctl graph save SESSION_ID ./vessels.mipgraph.json --overwrite
mipview-ctl graph load SESSION_ID ./vessels.mipgraph.json
mipview-ctl graph load SESSION_ID ./vessels.mipgraph.json --replace
mipview-ctl graph activate SESSION_ID
mipview-ctl graph display SESSION_ID --opacity 0.75 --node-size 3
mipview-ctl graph add-node SESSION_ID axial 12 18
mipview-ctl graph add-voxel-node SESSION_ID 12 18 7
mipview-ctl graph add-edge SESSION_ID axial 1 2
mipview-ctl graph curve-edge SESSION_ID axial 1 2 18.5 24.0
mipview-ctl graph straighten-edge SESSION_ID axial 1 2
mipview-ctl graph add-node-vector SESSION_ID axial 1 2
mipview-ctl graph add-tangent-vector SESSION_ID axial 1 2
mipview-ctl graph add-normal-vector SESSION_ID axial 1 2
mipview-ctl graph extension-line SESSION_ID axial 1 2 show
mipview-ctl graph normal-line SESSION_ID axial 1 2 show
mipview-ctl graph flip-vector SESSION_ID 1
mipview-ctl graph split-edge SESSION_ID axial 1 2 18 24
mipview-ctl graph calculate-angle SESSION_ID 1 2
mipview-ctl graph set-angle-label-position SESSION_ID 1 0.35 0.70
mipview-ctl graph delete-angle SESSION_ID 1
mipview-ctl graph clear-angles SESSION_ID
mipview-ctl graph delete-vector SESSION_ID 1
mipview-ctl graph clear SESSION_ID
mipview-ctl graph delete-edge SESSION_ID axial 1 2
mipview-ctl graph delete-node SESSION_ID axial 1
mipview-ctl graph exit SESSION_ID
```

The matching direct commands are `graph.status`, `graph.open`, `graph.save`, `graph.load`,
`graph.activate`,
`graph.set_display`, `graph.add_node`, `graph.delete_node`, `graph.add_edge`,
`graph.add_voxel_node`, `graph.delete_edge`, `graph.curve_edge`,
`graph.straighten_edge`, `graph.set_extension_line`, `graph.set_normal_line`,
`graph.add_node_vector`, `graph.add_tangent_vector`, `graph.add_normal_vector`,
`graph.flip_vector`, `graph.delete_vector`,
`graph.split_edge`, `graph.calculate_angle`,
`graph.set_angle_label_position`, `graph.delete_angle`,
`graph.clear_angles`, and `graph.clear`.

Curve controls use floating-point oriented projection coordinates and must be
finite and inside the projection plane. They update a shared 3D control point by
preserving the coordinate hidden by the selected view. Angles reference two
one-to-one vector pairs in one projection and scale their components by physical
in-plane voxel spacing. Label positions use normalized projection coordinates.
Graph status includes authoritative patch voxels,
projections, 3D curve controls, vector colour/direction records, pending vector
creation, angle selection, and all retained measurements. `.mipgraph.json` files
persist completed graph content, construction lines, and Graph-specific display
settings, plus MIP/MinIP mode and enabled projection orientations. Loading is
transactional and requires matching patch shape, bounds, and
affine; a changed source path is returned in `data.warnings`. Command saves do not
overwrite and command loads do not replace a non-empty graph unless the matching
flags are supplied. `graph.open PATH` requires the source image to be loaded,
extracts a fresh patch from the saved source bounds, and opens a restored patch
window. Version 1 graph files remain supported and open with all projection
orientations disabled because that schema did not store projection state.

`graph.split_edge` takes the clicked oriented projection index, inserts a node at
the nearest point on the target edge, and replaces it with two connected edges.
Quadratic edges retain their shape through Bezier subdivision.

### `annotation.create`

Function: Create or enable an active voxel-space annotation mask and set the active label.

CLI usage:

```bash
mipview-ctl annotation create --label LABEL
```

Direct command:

```json
{"command": "annotation.create", "args": {"label": 1}}
```

Parameters:

| Name | Type | Description |
| --- | --- | --- |
| `label` | `int` | Active annotation label. The CLI default is `1`; values below `1` are clamped to `1`. |

Example:

```bash
mipview-ctl annotation create --label 1
```

### `annotation.paint_stroke`

Function: Paint a voxel-space stroke on the active annotation mask.

CLI usage:

```bash
mipview-ctl annotation paint-stroke --label LABEL --radius RADIUS --view VIEW --points POINTS_JSON
```

Direct command:

```json
{"command": "annotation.paint_stroke", "args": {"label": 1, "radius": 2, "view": "axial", "points": [[116, 80, 45], [120, 80, 45], [124, 80, 45]]}}
```

Parameters:

| Name | Type | Description |
| --- | --- | --- |
| `points` | `list[list[int]]` | Voxel-space stroke points, each as `[x, y, z]`. |
| `radius` | `int` | Brush radius in voxels; must be non-negative. |
| `label` | `int` | Positive annotation label to paint. |
| `view` | `str` | Stroke disk plane: `axial`, `coronal`, or `sagittal`. |

Example:

```bash
printf '[[116,80,45],[120,80,45],[124,80,45]]\n' > stroke_points.json
mipview-ctl annotation paint-stroke --label 1 --radius 2 --view axial --points ./stroke_points.json
```

### `annotation.erase_stroke`

Function: Erase a voxel-space stroke from the active annotation mask.

CLI usage:

```bash
mipview-ctl annotation erase-stroke --radius RADIUS --view VIEW --points POINTS_JSON
```

Direct command:

```json
{"command": "annotation.erase_stroke", "args": {"radius": 2, "view": "axial", "points": [[116, 80, 45], [120, 80, 45], [124, 80, 45]]}}
```

Parameters:

| Name | Type | Description |
| --- | --- | --- |
| `points` | `list[list[int]]` | Voxel-space stroke points, each as `[x, y, z]`. |
| `radius` | `int` | Brush radius in voxels; must be non-negative. |
| `view` | `str` | Stroke disk plane: `axial`, `coronal`, or `sagittal`. |

Example:

```bash
printf '[[116,80,45],[120,80,45],[124,80,45]]\n' > stroke_points.json
mipview-ctl annotation erase-stroke --radius 2 --view axial --points ./stroke_points.json
```

### `annotation.save`

Function: Save the active annotation mask as NIfTI.

CLI usage:

```bash
mipview-ctl annotation save PATH
```

Direct command:

```json
{"command": "annotation.save", "args": {"path": "./annotation_mask.nii.gz"}}
```

Parameters:

| Name | Type | Description |
| --- | --- | --- |
| `path` | `str` | Output NIfTI path. |

Example:

```bash
mipview-ctl annotation save ./annotation_mask.nii.gz
```

## Vertical Slice Example

This example assumes MipView is already running and a NIfTI image with voxel `[120, 80, 45]` is loaded in the GUI.

```bash
printf '[[116,80,45],[120,80,45],[124,80,45]]\n' > stroke_points.json

mipview-ctl status
mipview-ctl viewer screenshot ./before.png
mipview-ctl viewer state ./state_before.json
mipview-ctl cursor move 120 80 45
mipview-ctl patch size 64 64 10
mipview-ctl patch center 120 80 45
mipview-ctl patch select
mipview-ctl patch export-raw ./patch_raw.npz
mipview-ctl projection mode minip
mipview-ctl projection save axial ./patch_axial_minip.png
mipview-ctl projection save axial ./patch_axial_minip.png --annotation-preview  # add a flag to export png with current annotation overlayed
mipview-ctl annotation create --label 1
mipview-ctl annotation paint-stroke --label 1 --radius 2 --view axial --points ./stroke_points.json
mipview-ctl viewer screenshot ./after.png
mipview-ctl annotation save ./annotation_mask.nii.gz
```
