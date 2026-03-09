# AGENTS.md

## Project
**MiView** is a lightweight Linux-first desktop visualization tool for `.nii` / `.nii.gz` medical images.

Its primary purpose is to support:
1. image visualization in an ITK-SNAP-inspired GUI layout,
2. cursor-based voxel inspection,
3. interactive patch selection,
4. patch saving to local disk,
5. later, orthogonal MIP / MinIP inspection of the selected patch.

This project should remain focused and minimal. Do not expand scope unless explicitly requested.

---

## Product Priorities
Always prioritize the following in order:

1. **Correctness of image handling**
   - Loading `.nii` / `.nii.gz` safely and consistently
   - Preserving shape, affine, header, and metadata where appropriate
   - Keeping voxel coordinates and displayed intensity values correct

2. **Usable GUI workflow**
   - Fast loading
   - Clear image display
   - Stable cursor inspection
   - Simple patch selection workflow

3. **Small milestone-based delivery**
   - Build the smallest complete working feature first
   - Avoid partially implementing multiple large features at once

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
- Use **NumPy** for patch extraction and MIP / MinIP computation
- Keep the first implementation focused on **2D slice visualization**
- Do **not** introduce VTK, OpenGL-heavy rendering, or advanced 3D infrastructure unless explicitly requested
- Prefer simple, testable implementations over highly optimized ones for early milestones

---

## Current Project Scope
MiView should be developed in milestones.

### Milestone 1 — Core Viewer
Implement:
- loading `.nii` / `.nii.gz`
- image display window(s)
- ITK-SNAP-inspired minimal GUI layout
- cursor inspection panel
- voxel coordinate readout
- intensity value readout

### Milestone 2 — Patch Selection and Saving
Implement:
- fixed-size patch selection centered on the current cursor
- patch bounds preview
- patch extraction from the loaded volume
- save selected patch locally as `.nii.gz`

### Milestone 3 — Orthogonal Patch MIP / MinIP
Implement:
- axial projection of selected patch
- coronal projection of selected patch
- sagittal projection of selected patch
- MIP and MinIP modes
- simple projection display panel

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

MiView is **not** intended to become a full medical imaging platform in the early stages.

---

## UI Guidance
The GUI should be inspired by ITK-SNAP only at a high level.

Prioritize:
- a clear visualization area
- a clear cursor inspection area
- a simple and stable layout
- minimal controls needed for the active milestone

Avoid overbuilding the UI.

For early versions:
- prefer simple layouts over polished styling
- prioritize working controls and correct interactions
- keep labels explicit and readable

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
- and consistently applied across display, cursor inspection, and patch extraction.

---

## Patch Selection Rules
Patch selection should initially use a **fixed-size patch centered on the current voxel/cursor**.

For early implementation:
- patch size should be user-configurable
- patch extraction must clip safely at image boundaries
- patch bounds should be visible in the UI or clearly shown in text
- saved patch filenames should be informative

Do not implement freehand or arbitrarily shaped ROI tools unless explicitly requested.

---

## MIP / MinIP Rules
For the first implementation of MIP / MinIP:
- compute projections from the **entire selected 3D patch**
- support the three orthogonal directions:
  - axial
  - coronal
  - sagittal
- keep the computation simple and readable
- use NumPy reductions unless a different implementation is explicitly needed

Do not implement advanced slab logic, adaptive thickness, or volume rendering in the first version.

---

## File and Module Design
Keep modules small and single-purpose.

Suggested structure:

- `io/` for loading and saving NIfTI files
- `viewer/` for slice display and cursor interaction
- `patch/` for patch extraction, saving, and projections
- `ui/` for window layout and widgets
- `models/` or `state/` for app state and data containers
- `utils/` for focused helper logic only

Avoid giant files with mixed responsibilities.

As a rule of thumb:
- if a file starts doing multiple unrelated jobs, split it
- if a helper is only used once and hurts readability, keep it local
- prefer explicit method names

---

## Editing Rules
When making changes:

- Make the **smallest effective change**
- Do not refactor unrelated files
- Do not rename modules or move files without a clear reason
- Do not change public behavior unless required for the task
- Do not introduce speculative abstractions
- Preserve existing milestone behavior

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

Do not spend excessive time building a large test framework early on, but ensure critical numerical and patch logic is testable.

---

## Performance Guidance
For early milestones:
- prioritize correctness and maintainability over optimization
- avoid premature optimization
- use NumPy efficiently for array operations
- keep interactions responsive for normal MRI-sized volumes

If performance becomes a problem, optimize only after measuring bottlenecks.

---

## Dependency Rules
Before adding a new dependency:
1. confirm it is necessary,
2. confirm the same goal cannot be achieved with the current stack,
3. prefer lightweight and well-maintained libraries.

Do not add large frameworks for features outside the active milestone.

---

## Documentation Expectations
When implementing a feature:
- keep README usage instructions accurate
- document non-obvious design decisions
- note assumptions around orientation, affine handling, and patch coordinates
- keep setup steps minimal and reproducible

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
- and supports the current milestone.

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