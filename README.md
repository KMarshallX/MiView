# MiView

**MiView** is a lightweight Linux-first desktop viewer for `.nii` / `.nii.gz` medical images.

It is designed as a focused research tool for:
- image visualization,
- voxel/cursor inspection,
- interactive patch selection,
- patch saving,
- and later, orthogonal **MIP / MinIP** inspection of selected patches.

MiView is intentionally minimal. The goal is to build a small, reliable viewer before adding more advanced features.

---

## Current Status

MiView is under active development.

The current viewer provides a minimal tri-planar layout with axial, coronal, and sagittal 2D slice views plus a cursor inspection panel.

### Deploy Locally
```
PYTHONPATH=src python -m miview
```

## Code Structure

The current codebase is organized around a small top-level `miview` package, with most logic grouped by responsibility:

```text
src/
└── miview/
    ├── __init__.py
    ├── __main__.py
    ├── main.py
    ├── nifti_io.py
    ├── patch_extractor.py
    ├── patch_saver.py
    ├── patch_selector.py
    ├── segmentation_models.py
    ├── segmentation_validation.py
    ├── io/
    │   └── __init__.py
    ├── patch/
    │   └── __init__.py
    ├── segmentation/
    │   └── __init__.py
    ├── state/
    │   ├── __init__.py
    │   ├── app_state.py
    │   ├── contrast_state.py
    │   ├── cursor_state.py
    │   └── zoom_state.py
    ├── tools/
    │   ├── __init__.py
    │   ├── processing.py
    │   ├── registry.py
    │   └── volume.py
    ├── ui/
    │   ├── __init__.py
    │   ├── contrast_control_bar.py
    │   ├── contrast_helpers.py
    │   ├── cursor_panel.py
    │   ├── drop_load_choice_dialog.py
    │   ├── drop_loading.py
    │   ├── main_window.py
    │   ├── patch_window.py
    │   ├── segmentation_config_window.py
    │   ├── tool_actions.py
    │   ├── tools_menu.py
    │   ├── viewer_area.py
    │   └── window_styling.py
    └── viewer/
        ├── __init__.py
        ├── intensity.py
        ├── oriented_volume.py
        ├── slice_geometry.py
        ├── slice_viewer_widget.py
        └── triplanar_viewer_widget.py
```

High-level responsibilities:

- `main.py`, `__main__.py`: application startup and package entry point.
- `nifti_io.py`: NIfTI loading and saving helpers shared across the app.
- `patch_*.py`: patch bounds, extraction, and patch-save behavior.
- `segmentation_*.py`: segmentation metadata and image/segmentation compatibility validation.
- `state/`: small state containers for app-level state, cursor position, contrast window, and zoom.
- `viewer/`: core image-display logic, orientation handling, slice geometry, intensity mapping, and tri-planar coordination.
- `ui/`: Qt windows, panels, menus, dialogs, styling helpers, and UI-specific action wiring.
- `tools/`: lightweight image-processing tool definitions, registry, and derived-volume helpers.

In practice, the main runtime flow is:

1. `python -m miview` enters through `__main__.py`.
2. `main.py` creates the Qt application and main window.
3. `ui/main_window.py` coordinates loading, viewer updates, patch actions, segmentation overlay state, and tool execution.
4. `viewer/` modules render slices and manage tri-planar interactions.
5. `state/`, `patch_*.py`, `segmentation_*.py`, and `tools/` provide the supporting logic behind those UI actions.
