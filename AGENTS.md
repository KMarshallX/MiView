# AGENTS.md

## Project
**MiView** is a lightweight Linux-first desktop visualization tool for `.nii` / `.nii.gz` medical images.

Its primary purpose is to support:
1. image visualization in an ITK-SNAP-inspired GUI layout,
2. cursor-based voxel inspection,
3. interactive patch selection,
4. patch saving to local disk,
5. orthogonal patch MIP / MinIP inspection,
6. segmentation overlay visualization,
7. lightweight image-processing utilities for full volumes and selected patches.

This project should remain focused and minimal. Do not expand scope unless explicitly requested.

---

## Product Priorities
Always prioritize the following in order:

1. **Correctness of image handling**
   - Loading `.nii` / `.nii.gz` safely and consistently
   - Preserving shape, affine, header, and metadata where appropriate
   - Keeping voxel coordinates and displayed intensity values correct
   - Keeping image, segmentation, and extracted patch relationships spatially correct

2. **Usable GUI workflow**
   - Fast loading
   - Clear image display
   - Stable cursor inspection
   - Simple patch selection workflow
   - Predictable segmentation overlay controls
   - Simple computational tool workflow

3. **Small milestone-based delivery**
   - Build the smallest complete working feature first
   - Avoid partially implementing multiple large features at once
   - Prefer one finished vertical slice of functionality over broad partial coverage

4. **Code clarity and modularity**
   - Keep files and modules small
   - Prefer explicit logic over clever abstractions
   - Avoid unnecessary architectural complexity

---

## Platform and Environment
- Target platform: **Linux-first**
- Primary language: **Python**
- Python version: **3.11+** unless otherwise specified
- GUI framework: **PySide6**
- Medical image I/O: **NiBabel**
- Numerical operations: **NumPy**

Use these libraries by default unless a change is explicitly requested.

Do not introduce heavy additional dependencies unless clearly justified.

---

## Core Technical Decisions
- Use **PySide6** for the GUI
- Use **NiBabel** to load and save `.nii` / `.nii.gz`
- Use **NumPy** for patch extraction, overlay alignment logic, and MIP / MinIP computation
- Keep the viewer focused on **2D slice visualization** with tri-planar coordination already established
- Do **not** introduce VTK, OpenGL-heavy rendering, or advanced 3D infrastructure unless explicitly requested
- Prefer simple, testable implementations over highly optimized ones for early milestones
- Treat segmentation as a **visual overlay and aligned data companion**, not as an editable object in this phase
- Treat computational tools as **deterministic image transforms** with clear scope and explicit input/output behavior

---

## Current Project Scope
MiView should be developed in milestones.

### Milestone 1 — Core Viewer
Implemented:
- loading `.nii` / `.nii.gz`
- image display window(s)
- ITK-SNAP-inspired minimal GUI layout
- cursor inspection panel
- voxel coordinate readout
- intensity value readout

### Milestone 2 — Patch Selection and Saving
Implemented:
- fixed-size patch selection centered on the current cursor
- patch bounds preview
- patch extraction from the loaded volume
- save selected patch locally as `.nii.gz`

### Milestone 3 — Orthogonal Patch MIP / MinIP
Implemented:
- axial projection of selected patch
- coronal projection of selected patch
- sagittal projection of selected patch
- MIP and MinIP modes
- simple projection display panel

### Milestone 4 — Segmentation Overlay Support
Implement:
- loading one or more segmentation files in `.nii` / `.nii.gz` format
- keeping segmentation volumes associated with the currently loaded image
- segmentation overlay rendering in the main viewer panels
- a standalone segmentation control panel
- opacity control for the active segmentation overlay
- a dropdown menu to switch between available segmentation files
- correct overlay visibility updates when the active segmentation changes
- segmentation support inside the patch selection window
- patchified segmentation extraction aligned with the selected image patch

Constraints for this milestone:
- do **not** implement segmentation drawing, painting, erasing, relabeling, or annotation tools
- do **not** implement multi-label editing workflows
- do **not** silently resample or re-register mismatched segmentations unless explicitly requested and documented
- prioritize spatial consistency and safe validation over convenience

### Milestone 5 — Lightweight Computational Tools
Implement:
- a `Tools` subcategory or submenu for simple image-processing utilities
- support for running selected utilities on the loaded image volume
- support for running selected utilities on the currently selected patch where applicable
- explicit UI controls for choosing the target data scope:
  - full image
  - current patch
- clear preview or replacement behavior for transformed outputs
- A Gitgraph inspired visual history of applied tools and transformations
   - each entry should show the tool name, parameters, and target scope
   - clicking an entry should show a preview of the resulting image or patch after applying that tool
   - clicking an entry should allow reverting to the state before that tool was applied

Initial tool set should include:
- normalization
- standardization
- local normalization
- contrast inversion by minus method
- contrast inversion by divide method
- N4 bias field correction via **ANTsPy** if dependency approval is given

Constraints for this milestone:
- keep the tool list small and explicit
- do **not** build a general-purpose image-processing pipeline editor
- do **not** add batch processing, macros, or workflow automation unless explicitly requested
- do **not** add advanced filtering libraries unless clearly needed for a requested tool

Do not work on future milestones until the current milestone is working unless explicitly instructed.

---

## Non-Goals for Early Versions
Do **not** add these unless explicitly requested:
- DICOM support
- segmentation editing tools
- registration tools
- annotation frameworks
- plugin systems
- networking features
- cloud sync
- authentication
- database storage
- GPU-specific optimization
- complex 3D rendering
- full ITK-SNAP feature parity
- batch processing pipelines
- scripting consoles
- radiomics frameworks
- model training or inference pipelines under the viewer unless explicitly requested

MiView is **not** intended to become a full medical imaging platform in the early stages.

---

## UI Guidance
The GUI should be inspired by ITK-SNAP only at a high level.

Prioritize:
- a clear visualization area
- a clear cursor inspection area
- a simple and stable layout
- minimal controls needed for the active milestone
- explicit segmentation state visibility
- explicit processing-tool target selection

Avoid overbuilding the UI.

For current and near-term versions:
- prefer simple layouts over polished styling
- prioritize working controls and correct interactions
- keep labels explicit and readable
- use separate panels for logically separate concerns
- avoid burying important controls in deep menus when a panel or compact toolbar is clearer

For segmentation UI specifically:
- keep overlay controls separate from image loading controls when practical
- show the active segmentation name clearly
- make opacity adjustment immediate and visually obvious
- ensure switching segmentation does not desynchronize the viewers

For computational tools specifically:
- make each tool discoverable under the `Tools` area
- expose only the parameters needed for the current tool
- make it obvious whether the tool applies to the full image or the current patch
- avoid ambiguous destructive actions

---

## Image Handling Rules
When working with NIfTI data:

- Preserve metadata responsibly
- Do not discard affine/header information without reason
- Be explicit about voxel-space vs display-space assumptions
- Ensure cursor inspection reports correct voxel indices and values
- Handle edge cases near image boundaries safely
- Avoid hidden axis flips or silent reorientation unless explicitly implemented and documented

If reorientation or axis normalization is introduced, it must be:
- explicit in code,
- documented,
- and consistently applied across display, cursor inspection, patch extraction, segmentation overlay, and computational tools.

If multiple volumes are loaded together:
- validate shape compatibility explicitly
- validate affine compatibility explicitly when relevant
- fail clearly when image and segmentation are incompatible for direct overlay
- do not guess alignment silently

---

## Segmentation Rules
Segmentation support in this phase is **overlay-only**.

Required behavior:
- allow loading one or more segmentation files for the active image
- maintain a list of available segmentation volumes
- allow switching the active segmentation from a dropdown selector
- support opacity adjustment from a standalone segmentation panel
- render segmentation overlays consistently across all synchronized viewer panels
- ensure patch-view segmentation corresponds to the same voxel bounds as the image patch

Alignment rules:
- segmentation patch extraction must use the exact same voxel bounds as image patch extraction
- segmentation overlays must respect the same orientation logic used by the base image display
- any mismatch in shape, affine, or orientation assumptions must be surfaced clearly to the user or developer

Out of scope for this phase:
- editing segmentation voxels
- brush tools
- erase tools
- contour tools
- relabel tools
- auto-segmentation features
- quantitative label statistics unless explicitly requested

---

## Patch Selection Rules
Patch selection should use a **fixed-size patch centered on the current voxel/cursor** unless a task explicitly changes that behavior.

Requirements:
- patch size should be user-configurable
- patch extraction must clip safely at image boundaries
- patch bounds should be visible in the UI or clearly shown in text
- saved patch filenames should be informative
- when segmentation is active, the segmentation patch must be extracted from the same bounds as the image patch
- patch window tools must operate on the same patch currently visualized

Do not implement freehand or arbitrarily shaped ROI tools unless explicitly requested.

---

## MIP / MinIP Rules
For the current implementation of MIP / MinIP:
- compute projections from the **entire selected 3D patch**
- support the three orthogonal directions:
  - axial
  - coronal
  - sagittal
- keep the computation simple and readable
- use NumPy reductions unless a different implementation is explicitly needed

Do not implement advanced slab logic, adaptive thickness, or volume rendering unless explicitly requested.

---

## Computational Tool Rules
Computational tools in this phase are **small, explicit utilities**, not a generic framework.

Required behavior:
- each tool must have a clearly defined mathematical or algorithmic effect
- each tool must specify whether it applies to the full image, the current patch, or both
- tools should be callable from the main viewer workflow
- tools intended for patch use must also function in the patch selection window
- transformed outputs must have clearly defined handling:
  - preview-only,
  - replace active display data,
  - or create a derived temporary result,
  depending on the requested implementation

Preferred initial tool definitions:
- **Normalization**: rescale intensities to a defined range
- **Standardization**: transform intensities using mean and standard deviation
- **Local normalization**: local-window-based normalization with explicit parameters
- **Contrast inversion (minus)**: subtract intensities from a defined reference value
- **Contrast inversion (divide)**: invert intensities by a defined division-based rule with safe zero handling
- **N4 bias field correction**: use ANTsPy only if dependency approval is explicit and environment setup is documented

Safety rules:
- do not overwrite source image data silently
- do not apply transforms with hidden parameter defaults if those defaults materially affect results
- document numerical assumptions and edge-case handling
- handle divide-by-zero and near-zero cases explicitly

---

## File and Module Design
Keep modules small and single-purpose.

Suggested structure:

- `io/` for loading and saving NIfTI files
- `viewer/` for slice display and cursor interaction
- `patch/` for patch extraction, saving, and projections
- `segmentation/` for overlay state, validation, and patch-aligned segmentation logic
- `tools/` for computational image transforms
- `ui/` for window layout and widgets
- `models/` or `state/` for app state and data containers
- `utils/` for focused helper logic only

Avoid giant files with mixed responsibilities.

As a rule of thumb:
- if a file starts doing multiple unrelated jobs, split it
- if a helper is only used once and hurts readability, keep it local
- prefer explicit method names
- keep transformation logic separate from widget wiring

---

## Editing Rules
When making changes:

- Make the **smallest effective change**
- Do not refactor unrelated files
- Do not rename modules or move files without a clear reason
- Do not change public behavior unless required for the task
- Do not introduce speculative abstractions
- Preserve existing milestone behavior
- Preserve a working viewer even when a new milestone is partially underway

If a task requires a wider refactor, explain why in comments or commit notes.

---

## Code Style
Prefer:
- readable Python
- explicit variable names
- small functions
- minimal hidden state
- clear docstrings for nontrivial logic
- type hints where practical

Avoid:
- overly abstract class hierarchies
- unnecessary design patterns
- clever one-liners for important logic
- silent exception swallowing

Error messages should be actionable and concise.

---

## Testing Expectations
Add tests for logic-heavy functionality where practical, especially:
- NIfTI loading behavior
- patch extraction bounds
- patch size correctness
- MIP / MinIP projection correctness
- file save/load round trips when relevant
- segmentation-image compatibility checks
- segmentation patch alignment correctness
- computational tool numerical correctness
- computational tool behavior on edge cases

Do not spend excessive time building a large test framework early on, but ensure critical numerical and patch logic is testable.

---

## Performance Guidance
For these milestones:
- prioritize correctness and maintainability over optimization
- avoid premature optimization
- use NumPy efficiently for array operations
- keep interactions responsive for normal MRI-sized volumes
- avoid repeated recomputation when cached slice or patch state is sufficient

If performance becomes a problem, optimize only after measuring bottlenecks.

---

## Dependency Rules
Before adding a new dependency:
1. confirm it is necessary,
2. confirm the same goal cannot be achieved with the current stack,
3. prefer lightweight and well-maintained libraries.

Additional rule for this stage:
- **ANTsPy** may be introduced only for requested N4 bias field correction, and only if installation, platform constraints, and fallback behavior are documented clearly.

Do not add large frameworks for features outside the active milestone.

---

## Documentation Expectations
When implementing a feature:
- keep README usage instructions accurate
- document non-obvious design decisions
- note assumptions around orientation, affine handling, patch coordinates, and segmentation alignment
- keep setup steps minimal and reproducible
- document the exact behavior of each computational tool and whether it affects full-image or patch data

---

## How to Approach Tasks
When given a task:
1. identify the active milestone,
2. implement only what is needed for that milestone,
3. keep changes localized,
4. verify existing behavior is not broken,
5. leave the codebase in a runnable state.

If a request is ambiguous, prefer the interpretation that:
- preserves scope,
- keeps MiView minimal,
- supports the current milestone,
- and does not silently expand into editing or workflow automation features.

---

## Preferred Development Attitude
Act like a careful contributor to a focused research tool:
- practical,
- conservative,
- implementation-oriented,
- and resistant to unnecessary scope growth.

MiView should become a reliable small tool before it becomes a feature-rich one.

## Important
- Do not implement features that were not explicitly requested.
- Do not replace the existing stack without approval.
- Always preserve a runnable application state after changes.
- For segmentation in this phase, treat it as visualization and aligned data handling only.
- For computational tools in this phase, prefer a few correct tools over a broad unfinished toolbox.