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
- [`patch.export_raw`](#patchexport_raw)
- [`patch.save`](#patchsave)
- [`projection.mode`](#projectionmode)
- [`projection.save`](#projectionsave)
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

Function: Export selected patch arrays and metadata, including annotation or segmentation patch arrays when available.

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

CLI usage:

```bash
mipview-ctl projection save VIEW PATH
```

Direct command:

```json
{"command": "projection.save", "args": {"view": "axial", "path": "./patch_axial_minip.png"}}
```

Parameters:

| Name | Type | Description |
| --- | --- | --- |
| `view` | `str` | Projection view: `axial`, `coronal`, or `sagittal`. |
| `path` | `str` | Output image path. The parent directory must exist and be writable. |

Example:

```bash
mipview-ctl projection save axial ./patch_axial_minip.png
```

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
mipview-ctl annotation create --label 1
mipview-ctl annotation paint-stroke --label 1 --radius 2 --view axial --points ./stroke_points.json
mipview-ctl viewer screenshot ./after.png
mipview-ctl annotation save ./annotation_mask.nii.gz
```
