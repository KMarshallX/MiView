# AGENTS.md

## Project

**MipView** is a lightweight Linux-first desktop visualization and annotation tool for `.nii` / `.nii.gz` medical images.

Its primary purpose is to support:

1. ITK-SNAP-inspired image visualization,
2. cursor-based voxel inspection,
3. interactive patch selection,
4. patch saving to local disk,
5. orthogonal patch MIP / MinIP inspection,
6. segmentation overlay visualization,
7. lightweight image-processing utilities for full volumes and selected patches,
8. voxel-space annotation layers,
9. agent-assisted patch annotation through a controlled MipView command interface.

MipView should remain focused and minimal. Do not expand scope into a full medical imaging platform unless explicitly requested.

* * *

## Product Priorities

Always prioritize the following in order:

1. **Correctness of image handling**
  
  * Preserve image shape, affine, header, voxel spacing, and metadata where appropriate.
  * Keep voxel coordinates, displayed intensities, patch bounds, segmentation overlays, and annotation masks spatially consistent.
  * Avoid silent axis flips, hidden reorientation, or guessed alignment.
2. **Correctness of annotation handling**
  
  * Annotation layers must be stored in voxel space.
  * Saved annotation masks must align with the source image.
  * Brush operations must modify the annotation mask, not only the display.
  * Screenshots are only visual references; they are not the source of truth for annotation coordinates.
3. **Usable GUI workflow**
  
  * Fast loading.
  * Stable cursor inspection.
  * Clear patch selection.
  * Clear annotation visibility.
  * Simple brush controls.
  * Predictable MIP / MinIP preview.
4. **Agent-control readiness**
  
  * Expose stable control commands for cursor movement, patch selection, screenshot capture, raw patch export, annotation editing, and mask saving.
  * Codex or other agents should interact through a controlled command/IPC layer, not by directly manipulating Qt widgets.
5. **Small milestone-based delivery**
  
  * Build the smallest complete working feature first.
  * Prefer one finished vertical slice over broad partial implementations.
6. **Code clarity and modularity**
  
  * Keep modules small.
  * Prefer explicit logic over clever abstractions.
  * Avoid unnecessary plugin frameworks, macro systems, or workflow engines.

* * *

## Platform and Environment

* Target platform: **Linux-first**
* Primary language: **Python**
* Python version: **3.11+**
* GUI framework: **PySide6**
* Medical image I/O: **NiBabel**
* Numerical operations: **NumPy**

Use these libraries by default unless a change is explicitly requested.

Do not introduce heavy dependencies unless clearly justified.

* * *

## Current Scope

MipView should support the following near-term capabilities:

### Core Viewer

Implemented or expected:

* loading `.nii` / `.nii.gz`,
* tri-planar image display,
* cursor inspection,
* voxel coordinate readout,
* intensity value readout,
* zoom / pan where already supported.

### Patch Selection and Saving

Expected behavior:

* fixed-size patch selection centered on the current cursor,
* configurable patch size,
* visible patch bounds,
* safe clipping near image boundaries,
* selected patch saving as `.nii.gz`,
* preservation of spatial metadata where appropriate.

### Orthogonal Patch MIP / MinIP

Expected behavior:

* axial, coronal, and sagittal projection of selected 3D patches,
* MIP and MinIP modes,
* projection display,
* projection image saving.

### Segmentation Overlay

Segmentation is primarily a visual overlay and aligned data companion.

Expected behavior:

* load one or more segmentation files,
* validate shape and affine compatibility,
* show segmentation overlays in the main viewer,
* support opacity controls,
* support active segmentation switching,
* extract segmentation patch using exactly the same bounds as image patch.

Do not silently resample or re-register segmentations unless explicitly requested and documented.

* * *

## Annotation Scope

MipView now includes a controlled annotation feature.

Annotation means:

* maintaining one or more editable voxel-space label masks,
* applying brush operations to the active annotation mask,
* previewing annotation overlays in the main viewer and patch viewer,
* saving annotation masks as `.nii.gz`,
* optionally saving JSON sidecars with annotation metadata.

Annotation does **not** mean:

* automatic segmentation model training,
* autonomous whole-volume medical annotation,
* complex multi-user labeling infrastructure,
* database-backed annotation management,
* DICOM-RT structure sets,
* advanced contour editing,
* full ITK-SNAP feature parity.

Keep annotation simple and voxel-space native.

* * *

## Annotation Rules

Annotation masks must:

* have the same voxel shape as the source image unless explicitly saved as a patch annotation,
* preserve the source image affine when saved as a full-volume mask,
* use integer labels,
* reserve label `0` for background,
* avoid modifying source image data,
* be saved explicitly by user or agent command.

Brush operations should support:

* paint,
* erase,
* set label,
* brush radius,
* optional stroke points,
* undo where practical.

Initial brush operations should be simple:

    brush.paint_voxel(x, y, z, label)
    brush.paint_disk(view, center_voxel, radius, label)
    brush.paint_stroke(points, radius, label)
    brush.erase_stroke(points, radius)
    annotation.save(path)

Do not implement complex freehand/contour tools unless explicitly requested.

* * *

## Agent-Assisted Annotation

MipView should support agent-assisted annotation, especially through Codex-facing workflows.

The preferred interaction model is:

    user provides small ground-truth patch
    → agent analyses raw patch + mask + MIP/MinIP views
    → MipView provides screenshot + viewer state + raw patch data
    → agent proposes voxel-space mask/stroke edits
    → MipView applies edits in voxel space
    → MipView returns updated MIP/MinIP and overlay preview
    → user confirms, agent iterates, or annotation is saved

Agents should output voxel-space operations, not mouse actions.

Prefer this:

    {
      "operation": "paint_stroke",
      "label": 1,
      "radius": 2,
      "points": [[32, 41, 5], [36, 43, 5], [40, 45, 6]]
    }

Avoid this:

    move mouse to screen coordinate (742, 381) and drag

Screenshots are useful for visual context, but raw image arrays, patch arrays, masks, and voxel-coordinate metadata are required for reliable annotation.

* * *

## Codex / Agent Control Interface

MipView should expose a minimal command-control layer for agent interaction.

Preferred architecture:

    Codex plugin / Unix terminal
        ↓
    mipview-ctl CLI
        ↓
    local IPC interface
        ↓
    MipView command registry
        ↓
    MipView controller
        ↓
    PySide6 GUI state and annotation mask

Agents must not directly manipulate Qt widgets.

Recommended command groups:

    viewer.status
    viewer.screenshot
    viewer.export_state
    
    cursor.get
    cursor.move
    
    patch.info
    patch.size
    patch.center
    patch.select
    patch.export_raw
    patch.save
    
    projection.mode
    projection.save
    
    annotation.create
    annotation.set_active
    annotation.paint_voxel
    annotation.paint_stroke
    annotation.erase_stroke
    annotation.preview
    annotation.save
    annotation.export_metadata
    
    tools.list
    tools.apply

All commands should return structured results:

    {
      "ok": true,
      "message": "Annotation stroke applied.",
      "data": {
        "label": 1,
        "num_voxels_modified": 128
      }
    }

Failures must be explicit and actionable.

* * *

## Screenshot and Viewer-State Rules

When providing screenshots for an agent, also provide structured state.

A useful agent package should include:

    - screenshot path,
    - active view,
    - slice index,
    - cursor voxel,
    - patch center,
    - patch size,
    - patch bounds,
    - image shape,
    - voxel spacing,
    - affine summary,
    - display orientation,
    - window/level or contrast state,
    - active annotation label,
    - active segmentation if any,
    - raw patch data path if exported,
    - current annotation mask patch if available.

Do not rely on screenshots alone for coordinate decisions.

If screen-pixel to voxel mapping is implemented, it must account for:

* active view,
* zoom,
* pan,
* orientation conventions,
* displayed slice geometry,
* image bounds,
* projection mode when relevant.

* * *

## Ground-Truth Example Rules

For few-shot agent-assisted annotation, a ground-truth example should include:

    - raw image patch,
    - annotation mask patch,
    - patch bounds,
    - voxel spacing,
    - MIP / MinIP preview,
    - optional screenshot,
    - label definitions,
    - notes on what should and should not be annotated.

The agent may use the example to infer local annotation rules, but MipView should remain the authority for applying voxel-space edits and saving masks.

Do not assume the agent’s proposed annotation is scientifically valid without user review.

* * *

## Image Handling Rules

When working with NIfTI data:

* preserve affine/header responsibly,
* distinguish voxel space from display space,
* keep cursor inspection correct,
* keep patch extraction and annotation mask updates aligned,
* validate shape compatibility,
* validate affine compatibility where relevant,
* fail clearly on mismatches,
* do not guess alignment silently.

If reorientation or axis normalization is introduced, it must be:

* explicit in code,
* documented,
* consistently applied across display, cursor inspection, patch extraction, segmentation overlay, annotation, and computational tools.

* * *

## Patch Selection Rules

Patch selection should use a fixed-size patch centered on the current voxel/cursor unless explicitly changed.

Requirements:

* user-configurable patch size,
* safe clipping at image boundaries,
* visible patch bounds,
* informative saved patch filenames,
* segmentation patch extraction must use the same bounds as image patch extraction,
* annotation patch extraction must use the same bounds as image patch extraction,
* patch-window tools must operate on the currently visualized patch.

* * *

## MIP / MinIP Rules

For MIP / MinIP:

* compute projections from the selected 3D patch,
* support axial, coronal, and sagittal directions,
* support both raw image and annotation-overlay previews,
* keep computation simple and readable,
* use NumPy reductions unless a different implementation is explicitly needed.

Do not implement advanced slab logic, adaptive thickness, or volume rendering unless explicitly requested.

* * *

## Computational Tool Rules

Computational tools are small, explicit utilities, not a generic pipeline framework.

Each tool must define:

* mathematical effect,
* accepted input scope: full image, current patch, annotation mask, or segmentation,
* output behavior: preview, derived result, or replacement,
* parameter defaults,
* edge-case handling.

Initial tools may include:

* normalization,
* standardization,
* local normalization,
* contrast inversion by minus method,
* contrast inversion by divide method,
* N4 bias field correction via ANTsPy only if dependency approval is explicit.

Do not overwrite source image data silently.

* * *

## File and Module Design

Keep modules small and single-purpose.

Suggested structure:

    src/mipview/
        io/
        viewer/
        patch/
        segmentation/
        annotation/
        tools/
        control/
        state/
        ui/
        utils/

Recommended responsibilities:

    annotation/
        annotation_mask.py
        brush.py
        annotation_io.py
        annotation_state.py
    
    control/
        controller.py
        command_registry.py
        ipc_server.py
        result.py
    
    ui/
        annotation_panel.py
        annotation_overlay.py

Avoid giant files with mixed responsibilities.

If a file starts doing unrelated jobs, split it.

* * *

## Editing Rules

When making changes:

* make the smallest effective change,
* do not refactor unrelated files,
* do not rename modules without clear reason,
* preserve existing viewer behavior,
* preserve patch saving,
* preserve segmentation overlay behavior,
* preserve runnable application state,
* keep annotation changes localized where possible.

If a wider refactor is required, explain why in comments or commit notes.

* * *

## Code Style

Prefer:

* readable Python,
* explicit variable names,
* small functions,
* type hints where practical,
* clear docstrings for nontrivial logic,
* actionable error messages.

Avoid:

* overly abstract class hierarchies,
* unnecessary design patterns,
* clever one-liners for important logic,
* silent exception swallowing,
* hidden state mutation.

* * *

## Testing Expectations

Add tests for logic-heavy functionality where practical, especially:

* NIfTI loading behavior,
* patch extraction bounds,
* patch size correctness,
* MIP / MinIP projection correctness,
* segmentation-image compatibility,
* annotation mask shape and affine preservation,
* brush painting correctness,
* brush erase correctness,
* annotation save/load round trip,
* coordinate mapping between viewer and voxel space,
* command result success/failure behavior.

Do not build a large test framework prematurely, but ensure critical numerical and spatial logic is testable.

* * *

## Performance Guidance

For early annotation features:

* prioritize correctness over speed,
* use NumPy efficiently,
* avoid unnecessary full-volume recomputation,
* update only affected overlays where practical,
* keep GUI interactions responsive,
* optimize only after measuring bottlenecks.

* * *

## Dependency Rules

Before adding a dependency:

1. confirm it is necessary,
2. confirm the same goal cannot be achieved with current stack,
3. prefer lightweight and maintained libraries,
4. document installation and fallback behavior.

Do not add large annotation frameworks, deep-learning inference frameworks, or database systems unless explicitly requested.

* * *

## Documentation Expectations

When implementing annotation or control features, update documentation for:

* annotation mask format,
* label conventions,
* brush behavior,
* save/load behavior,
* coordinate assumptions,
* screenshot/state export,
* agent-control command usage,
* limitations of agent-assisted annotation.

Document clearly that agent-assisted annotations require user review.

* * *

## Non-Goals Unless Explicitly Requested

Do not implement these by default:

* DICOM support,
* DICOM-RT export,
* registration tools,
* automatic segmentation model training,
* autonomous whole-volume annotation,
* cloud sync,
* authentication,
* database-backed annotation projects,
* multi-user annotation,
* complex plugin framework inside MipView,
* arbitrary Python scripting console,
* general-purpose workflow automation,
* full ITK-SNAP feature parity,
* advanced 3D rendering,
* GPU-specific optimization.

* * *

## Preferred Development Attitude

Act like a careful contributor to a focused research tool:

* practical,
* conservative,
* implementation-oriented,
* resistant to unnecessary scope growth,
* strict about spatial correctness,
* cautious about agent autonomy in medical-image annotation.

MipView should become a reliable viewer and voxel-space annotation tool before becoming a broader platform.

* * *

## Important

* Do not implement features that were not explicitly requested.
* Do not replace the existing stack without approval.
* Always preserve a runnable application state.
* Annotation must be voxel-space native.
* Screenshots are visual aids, not coordinate ground truth.
* Agent proposals must be reviewable.
* Saved annotation layers must preserve spatial correspondence with the source image.