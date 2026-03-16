# DEBUGLOG.md

## Purpose
This file is a drag-and-drop debugging handoff for MiView.

It is intended to help the next debugging session continue from the current state without repeating prior work or assuming the issue is solved.

## Scope
Feature under investigation:
- Dragging a local `.nii` or `.nii.gz` file onto the main window tri-planar viewer should trigger MiView's existing dropped-file flow.
- After drop, the user should see the minimal choice dialog:
  - `Base Image`
  - `Segmentation`
- Drag-and-drop must apply only to the main window viewer area.
- Dragging onto the selected-patch window should do nothing.

## Current Bug Status
The user reports that drag-and-drop still does not work in the real GUI.

Observed user-facing behavior:
- Dragging a valid `.nii` / `.nii.gz` file over the main window still shows the red forbidden cursor.
- That means Qt is still rejecting the drag before the intended load-choice flow is reached.
- The actual live GUI behavior has not been confirmed as fixed in this conversation.

Important:
- Do not assume the current code fixes the bug.
- Do not assume the passing tests prove live GUI drag-and-drop is working.

## Relevant Work Already Done

### 1. Added minimal drop-choice UI
File:
- `src/miview/ui/drop_load_choice_dialog.py`

What was added:
- `DropLoadChoice`
- `DropLoadChoiceDialog`

Intent:
- Provide the two-button minimal post-drop choice dialog for:
  - base image
  - segmentation

### 2. Added drop file helpers
File:
- `src/miview/ui/drop_loading.py`

What was added:
- `is_supported_nifti_path(path)`
- `first_supported_local_nifti_path(urls)`

Current behavior:
- Only accepts a single local file URL.
- Accepts only `.nii` or `.nii.gz`.
- Rejects multi-file drops.
- Rejects remote URLs.

### 3. Refactored main-window loading flow
File:
- `src/miview/ui/main_window.py`

What was added/refactored:
- `self.slice_viewer.nifti_file_dropped.connect(self._on_viewer_nifti_file_dropped)`
- `self.slice_viewer.set_drop_loading_enabled(True)`
- `_prompt_drop_load_choice()`
- `_load_base_image_from_path(image_path)`
- `_load_segmentation_from_path(seg_path)`
- `_on_viewer_nifti_file_dropped(dropped_path)`

Intent:
- Reuse the same base-image and segmentation loading/validation paths for dropped files.

This part is likely not the main issue:
- The user reports a forbidden cursor during hover.
- That implies the problem is still in drag-enter / drag-move / widget acceptance, not in the downstream loading logic.

### 4. Added drag/drop handling inside the tri-planar viewer
File:
- `src/miview/viewer/triplanar_viewer_widget.py`

What was added:
- Signal: `nifti_file_dropped`
- Flag: `_drop_loading_enabled`
- `set_drop_loading_enabled(enabled)`
- `dragEnterEvent`
- `dragMoveEvent`
- `dropEvent`
- `eventFilter`
- `_accept_drop_event(event)`
- `_dropped_nifti_path(event)`

Also added:
- `_drop_event_sources` including:
  - `TriPlanarViewerWidget`
  - each `SliceViewerWidget`
  - each slice `image_label`

Intent:
- Catch drag/drop at the visible viewer surfaces, not only the outer container.

### 5. Added drag/drop handling at main-window/container level
File:
- `src/miview/ui/main_window.py`

What was added:
- `self.setAcceptDrops(True)`
- `content_widget.setAcceptDrops(True)`
- `splitter.setAcceptDrops(True)`
- event filters on the content widget and splitter
- `dragEnterEvent`
- `dragMoveEvent`
- `dropEvent`
- `_accept_drop_for_viewer(...)`
- `_handle_drop_for_viewer(...)`
- `_dropped_nifti_path_for_viewer(...)`
- `_event_point_hits_slice_viewer(...)`

Intent:
- Handle drag acceptance at the QMainWindow and intermediate container level in case Qt rejects the drag before it reaches the viewer subtree.

### 6. Explicitly disabled drops in the patch window
File:
- `src/miview/ui/patch_window.py`

What was added:
- `self.setAcceptDrops(False)`

Intent:
- Make the selected-patch window explicitly non-droppable.

## Validation Already Performed

### Tests run
Current shell:
- `pytest` was not available.

Conda:
- `main_env` exists.

Successful test run:
- `QT_QPA_PLATFORM=offscreen conda run -n main_env pytest tests/test_drop_loading.py tests/test_segmentation_validation.py`
- Result at the end of the conversation:
  - `13 passed in 4.01s`

Important limitation:
- These are code-level and widget-property tests.
- They do not prove that the live OS drag cursor changes from forbidden to accepted.
- No live interactive GUI drag was verified in this environment.

## Why The Bug May Still Be Happening
Likely remaining root causes:

### 1. The real drag target may still not be the widgets currently instrumented
Possible issue:
- The actual widget receiving drag hover in the running GUI may not be:
  - `MainWindow`
  - `content_widget`
  - `QSplitter`
  - `TriPlanarViewerWidget`
  - `SliceViewerWidget`
  - `image_label`

There may be another widget in the hierarchy that still rejects the drag first.

### 2. The coordinate hit-test in `MainWindow` may be wrong for drag events
Code to inspect:
- `_event_point_hits_slice_viewer(...)`

Risk:
- `event.position()` is interpreted in the source widget's local coordinates.
- If the source widget or Qt drag event path differs from assumptions, the mapping may fail and incorrectly reject valid drags.

### 3. Event-filter ownership may still be incomplete or misleading
Potential issue:
- `TriPlanarViewerWidget` installs itself as an event filter on child widgets.
- `MainWindow` installs itself as an event filter on parent containers.
- The real drag path may still bypass these filters or may be accepted/rejected before these handlers matter.

### 4. A child widget may still be implicitly refusing the drag
Potential issue:
- Some widgets may need explicit `setAcceptDrops(True)` even if their parent has it.
- Some widgets may consume or alter drag events before the custom logic runs.

### 5. OS-level drag source or URL format may differ from assumptions
Potential issue:
- The dropped data may not arrive as exactly one local file URL in the running desktop environment.
- `first_supported_local_nifti_path(...)` currently rejects:
  - multiple URLs
  - non-local URLs
  - anything not ending with `.nii` or `.nii.gz`

Need to confirm:
- What `mimeData().formats()` and `mimeData().urls()` actually look like during a real drag on the target system.

### 6. `acceptProposedAction()` may still not be happening at the decisive widget
Even though the code now calls `acceptProposedAction()` in multiple places, the decisive accepting widget in the live GUI may still be elsewhere.

## Files, Classes, And Functions To Inspect Next

### Main drag/drop files
- `src/miview/ui/main_window.py`
- `src/miview/viewer/triplanar_viewer_widget.py`
- `src/miview/viewer/slice_viewer_widget.py`
- `src/miview/ui/drop_loading.py`
- `src/miview/ui/patch_window.py`

### Key classes
- `MainWindow`
- `TriPlanarViewerWidget`
- `SliceViewerWidget`
- `PatchViewerWindow`

### Key functions and methods
- `MainWindow.dragEnterEvent`
- `MainWindow.dragMoveEvent`
- `MainWindow.dropEvent`
- `MainWindow.eventFilter`
- `MainWindow._accept_drop_for_viewer`
- `MainWindow._handle_drop_for_viewer`
- `MainWindow._dropped_nifti_path_for_viewer`
- `MainWindow._event_point_hits_slice_viewer`
- `MainWindow._on_viewer_nifti_file_dropped`
- `TriPlanarViewerWidget.set_drop_loading_enabled`
- `TriPlanarViewerWidget.dragEnterEvent`
- `TriPlanarViewerWidget.dragMoveEvent`
- `TriPlanarViewerWidget.dropEvent`
- `TriPlanarViewerWidget.eventFilter`
- `TriPlanarViewerWidget._accept_drop_event`
- `TriPlanarViewerWidget._dropped_nifti_path`
- `drop_loading.first_supported_local_nifti_path`
- `SliceViewerWidget.eventFilter`

## Current Code State Worth Noting

### Main window
The main window now has:
- `setAcceptDrops(True)`
- drag/drop handlers
- event filters on:
  - central content widget
  - main splitter

### Tri-planar viewer
The viewer now has:
- drop enabled via `set_drop_loading_enabled(True)` from `MainWindow`
- event filter installed on:
  - viewer widget
  - each slice widget
  - each slice image label

### Patch window
The patch window now explicitly disables drops:
- `setAcceptDrops(False)`

## Assumptions Made So Far
- The drag payload is delivered as local file URLs through `mimeData().urls()`.
- Accepting a single local `.nii` / `.nii.gz` URL is the intended UX.
- Multi-file drop should fail safely.
- The user wants no drag-and-drop behavior in the selected-patch window.
- The real failure is still in event acceptance/routing, not in the load-choice dialog or NIfTI load logic.

## Constraints
- Keep scope limited to the main window tri-planar viewer.
- Do not add unrelated GUI features.
- Do not silently resample or coerce segmentation files.
- Preserve existing base image and segmentation loading behavior.
- Keep changes localized.
- No extra dependencies unless truly necessary.

## Unresolved Questions
- Which exact widget receives `dragEnterEvent` first during a live drag over the viewer area?
- Does the running desktop environment provide exactly one local file URL?
- Is the drag event position mapping in `MainWindow._event_point_hits_slice_viewer(...)` correct in practice?
- Is there a widget between the top-level window and the visible slice labels that still blocks the drag?
- Is `SliceViewerWidget.image_label` actually the final hover target during live drag, or does Qt drag over another internal surface?
- Are the current event filters firing at all during a real drag session?

## Recommended Debugging Plan For Next Conversation

### 1. Instrument the real drag path
Add temporary logging or status-bar tracing for:
- `dragEnterEvent`
- `dragMoveEvent`
- `dropEvent`
- `eventFilter`

Log:
- widget/class name
- whether event was accepted or ignored
- `mimeData().formats()`
- `mimeData().urls()`
- local coordinates and mapped global coordinates

Goal:
- Confirm which widget actually sees the drag first.

### 2. Confirm the live MIME payload
During a real drag, inspect:
- `event.mimeData().formats()`
- `event.mimeData().urls()`

Goal:
- Confirm whether `first_supported_local_nifti_path(...)` is too strict for the real desktop drag source.

### 3. Simplify acceptance temporarily
As a debugging step only:
- temporarily accept any local file URL at the main window level
- ignore viewer hit-testing at first

Goal:
- Determine whether the failure is caused by:
  - event routing
  - hit-testing
  - URL filtering

If that works, reintroduce constraints step by step.

### 4. Verify whether child filtering is even needed
Try reducing the design to one decisive acceptance layer:
- either top-level `MainWindow`
- or `TriPlanarViewerWidget`

Goal:
- Avoid a complex, overlapping drag/drop path that is harder to reason about.

### 5. Manually verify live GUI behavior
Specifically confirm:
- hover over viewer changes cursor away from forbidden
- drop triggers the load-choice dialog
- drag over patch window still does nothing

This has not yet been proven in the live app.

## Recommended Caution
- Do not assume passing unit tests mean the GUI drag route works.
- Do not continue layering more handlers without first proving which widget is actually rejecting the drag.
- The next step should be evidence-driven debugging of the live event path.

