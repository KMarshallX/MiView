# MipView

**MipView** is a lightweight Linux-first desktop visualization and annotation tool for `.nii` / `.nii.gz` medical images.

It is designed as a focused research tool for:

- ITK-SNAP inspired image viewing,
- multi-label segmentation overlay inspection with deterministic per-label colors
  and synchronized main/patch overlay selectors (`---` disables the overlay),
- voxel-space annotation with editable label masks,
- interactive patch selection,
- patch saving,
- patch-wise volumetric computation (e.g., normalization, standardization, filtering, etc.),
- orthogonal **MIP / MinIP** inspection of selected, modified patches, optionally
  restricted to a loaded file-backed segmentation mask, with opt-in MIP of the
  active file or annotation segmentation overlay,
- projection-graph editing with persistent directed vectors, straight or curved edges, and multiple physical-spacing-aware angle measurements,
- patch-window triplanar screenshot export at 1–200% output resolution,
- controlled local IPC and `mipview-ctl` commands for viewer, patch, annotation, projection, and graph workflows.

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
└── src/mipview/
    ├── __init__.py
    ├── __main__.py
    ├── main.py
    ├── annotation/
    │   ├── annotation_mask.py
    │   ├── brush.py
    │   └── annotation_state.py
    ├── control/
    │   ├── cli.py
    │   ├── command_registry.py
    │   ├── controller.py
    │   └── ipc_server.py
    ├── graph/
    │   ├── curve.py
    │   ├── geometry.py
    │   ├── measurement.py
    │   ├── model.py
    │   ├── spatial.py
    │   ├── state.py
    │   └── vector.py
    ├── io/
    │   └── nifti_io.py
    ├── patch/
    │   ├── extractor.py
    │   ├── history.py
    │   ├── saver.py
    │   └── selector.py
    ├── segmentation/
    │   ├── models.py
    │   └── validation.py
    ├── state/
    ├── tools/
    ├── ui/
    └── viewer/
```

In practice, the main runtime flow is:

1. `python -m mipview` enters through `mipview/__main__.py`.
2. `main.py` creates the Qt application and main window.
3. `ui/main_window.py` coordinates loading, viewer updates, patch actions, segmentation and annotation state, and tool execution; patch-window Graph mode is coordinated by `ui/patch_window.py`.
4. `viewer/` modules render slices and projections and manage tri-planar, zoom, pan, annotation, and graph interactions.
5. `graph/` keeps graph identity, curve geometry, persistent vectors, measurement calculations, and interaction state outside the Qt panel code.
6. `control/` exposes structured local IPC commands through the command registry, controller, and `mipview-ctl` CLI.
7. `state/`, `io/`, `patch/`, `segmentation/`, `annotation/`, and `tools/` provide the remaining supporting logic.
