# MipView

**MipView** is a lightweight Linux-first desktop viewer for `.nii` / `.nii.gz` medical images.

It is designed as a focused research tool for:
- ITK-SNAP inspired image viewing,
- segmentation overlay inspection,
- interactive patch selection,
- patch saving,
- patch-wise volumetric computation (e.g., normalization, standardization, filtering, etc.),
- orthogonal **MIP / MinIP** inspection of selected, modified patches.

MipView is intentionally minimal. The goal is to build a small, reliable viewer before adding more advanced features.

---

## Current Status

MipView is under active development, but the prototype is already here! Please have a try and share your feedback through [GitHub issues](https://github.com/KMarshallX/MipView/issues).


### Launching MipView

Installed or packaged usage:
```bash
mipview
```

This is the primary end-user launch command and the expected launch path for container and Neurodesk-style environments.

Local development from a repository checkout:
```bash
bash setup.sh
bash run.sh
```

`setup.sh` is a development bootstrap helper. It creates or reuses a local `.venv` and installs the project from `pyproject.toml`. It is not the canonical container installation path.

Repository compatibility wrapper:
```bash
bash run.sh
```

`run.sh` is a simple repository/dev wrapper. It tries the launch commands in this order:
- repo-local `.venv/bin/mipview`
- `mipview` on `PATH`
- `PYTHONPATH=src python -m mipview` for source checkouts

Or make it executable once:
```bash
chmod +x run.sh
./run.sh
```

Source-checkout fallback:
```bash
PYTHONPATH=src python -m mipview
```

Expected local development flow:
1. `bash setup.sh`
2. `bash run.sh`

Expected installed/container/Neurodesk flow:
1. Install the package into the environment
2. Launch with `mipview`

Container / pip-based dependency install:
```bash
pip install -r requirements.txt
```
This `requirements.txt` mirrors the runtime dependencies used by the app and is intended for Docker-style installs. In installed/container environments, the intended launch command remains `mipview`.

CI note:
- GitHub Actions validates three install paths (`setup.sh`, `pip install -e .`, and `pip install -r requirements.txt`) and runs a headless startup smoke test for each.

## Branch And Release Workflow

- `development`: active feature development and testing branch.
- `master`: stable source branch for releases.
- Pull requests should be merged from `development` into `master` for stable releases.

## Code Structure

The current codebase is organized around a small top-level `mipview` package:

```text
.
├── run.sh
├── setup.sh
├── requirements.txt
├── pyproject.toml
├── scripts/
│   └── bootstrap_helpers.sh
└── src/
```

```text
src/
└── mipview/
    ├── __init__.py
    ├── __main__.py
    ├── main.py
    ├── nifti_io.py
    ├── patch_extractor.py
    ├── patch_history.py
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
    │   ├── patch_utility.py
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
    │   ├── patch_history_panel.py
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
- `patch_*.py`, `patch_history.py`: patch bounds, extraction, patch-save behavior, and patch history tracking.
- `segmentation_*.py`: segmentation metadata and image/segmentation compatibility validation.
- `state/`: small state containers for app-level state, cursor position, contrast window, and zoom.
- `viewer/`: core image-display logic, orientation handling, slice geometry, intensity mapping, and tri-planar coordination.
- `ui/`: Qt windows, panels, menus, dialogs, styling helpers, and UI-specific action wiring.
- `tools/`: lightweight image-processing tool definitions, registry, and derived-volume helpers.

In practice, the main runtime flow is:

1. `python -m mipview` enters through `mipview/__main__.py`.
2. `main.py` creates the Qt application and main window.
3. `ui/main_window.py` coordinates loading, viewer updates, patch actions, segmentation overlay state, and tool execution.
4. `viewer/` modules render slices and manage tri-planar interactions.
5. `state/`, `patch_*.py`, `segmentation_*.py`, and `tools/` provide the supporting logic behind those UI actions.
