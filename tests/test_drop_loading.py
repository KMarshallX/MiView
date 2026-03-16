from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
import nibabel as nib
import numpy as np

from miview.nifti_io import NiftiLoadResult
from miview.tools import derive_volume
from miview.ui.drop_loading import (
    first_supported_local_nifti_path,
    is_supported_nifti_path,
)
from miview.ui.main_window import MainWindow
from miview.ui.patch_window import PatchViewerWindow
from miview.viewer.triplanar_viewer_widget import TriPlanarViewerWidget


def _build_test_volume(shape: tuple[int, int, int] = (3, 3, 3)) -> NiftiLoadResult:
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    affine = np.eye(4)
    header = nib.Nifti1Image(data, affine).header.copy()
    header.set_zooms((1.0, 1.0, 1.0))
    return NiftiLoadResult(
        data=data,
        affine=affine,
        header=header,
        shape=shape,
        dtype=data.dtype,
    )


def test_is_supported_nifti_path_accepts_nii_and_nii_gz() -> None:
    assert is_supported_nifti_path("brain.nii")
    assert is_supported_nifti_path("brain.nii.gz")
    assert is_supported_nifti_path(Path("/tmp/BRAIN.NII.GZ"))


def test_is_supported_nifti_path_rejects_other_extensions() -> None:
    assert not is_supported_nifti_path("brain.nrrd")
    assert not is_supported_nifti_path("brain.gz")


def test_first_supported_local_nifti_path_returns_first_supported_local_file() -> None:
    urls = [QUrl.fromLocalFile("/tmp/scan.nii.gz")]

    result = first_supported_local_nifti_path(urls)

    assert result == Path("/tmp/scan.nii.gz")


def test_first_supported_local_nifti_path_returns_none_when_no_supported_file_exists() -> None:
    urls = [
        QUrl("https://example.com/remote.nii.gz"),
        QUrl.fromLocalFile("/tmp/readme.txt"),
    ]

    result = first_supported_local_nifti_path(urls)

    assert result is None


def test_first_supported_local_nifti_path_rejects_multi_file_drops() -> None:
    urls = [
        QUrl.fromLocalFile("/tmp/scan.nii.gz"),
        QUrl.fromLocalFile("/tmp/later.nii"),
    ]

    result = first_supported_local_nifti_path(urls)

    assert result is None


def test_triplanar_viewer_drop_loading_toggles_inner_view_targets() -> None:
    app = QApplication.instance() or QApplication([])
    viewer = TriPlanarViewerWidget()

    viewer.set_drop_loading_enabled(True)

    assert viewer.acceptDrops()
    assert viewer.axial_view.acceptDrops()
    assert viewer.axial_view.image_label.acceptDrops()
    assert viewer.coronal_view.acceptDrops()
    assert viewer.coronal_view.image_label.acceptDrops()
    assert viewer.sagittal_view.acceptDrops()
    assert viewer.sagittal_view.image_label.acceptDrops()

    viewer.set_drop_loading_enabled(False)

    assert not viewer.acceptDrops()
    assert not viewer.axial_view.acceptDrops()
    assert not viewer.axial_view.image_label.acceptDrops()
    assert not viewer.coronal_view.acceptDrops()
    assert not viewer.coronal_view.image_label.acceptDrops()
    assert not viewer.sagittal_view.acceptDrops()
    assert not viewer.sagittal_view.image_label.acceptDrops()

    viewer.deleteLater()
    _ = app


def test_main_window_enables_drop_acceptance_only_for_main_viewer_path() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.acceptDrops()
    assert window._content_widget is not None
    assert window._content_widget.acceptDrops()
    assert window._main_splitter is not None
    assert window._main_splitter.acceptDrops()
    assert window.slice_viewer.acceptDrops()

    window.deleteLater()
    _ = app


def test_patch_window_does_not_enable_drag_and_drop() -> None:
    app = QApplication.instance() or QApplication([])
    patch_volume = _build_test_volume()

    window = PatchViewerWindow(patch_volume)

    assert not window.acceptDrops()
    assert not window.slice_viewer.acceptDrops()

    window.deleteLater()
    _ = app


def test_patch_window_tool_replacement_preserves_initial_display_without_cursor_motion() -> None:
    app = QApplication.instance() or QApplication([])
    patch_volume = _build_test_volume((5, 5, 5))
    window = PatchViewerWindow(patch_volume)

    replacement = derive_volume(patch_volume, patch_volume.data + 10.0)
    window._replace_patch_viewer_volume(replacement)

    assert window.slice_viewer.current_cursor_position() == (2, 2, 2)
    assert window.slice_viewer.axial_view._source_cursor_position == (2, 2, 2)
    assert window.slice_viewer.axial_view._current_pixmap is not None
    assert window.slice_viewer.axial_view.slice_label.text() == "Slice: 3 / 5"

    window.deleteLater()
    _ = app


def test_patch_window_tool_replacement_preserves_display_after_cursor_motion() -> None:
    app = QApplication.instance() or QApplication([])
    patch_volume = _build_test_volume((5, 5, 5))
    window = PatchViewerWindow(patch_volume)

    window.slice_viewer.cursor_state.set_cursor_position((1, 3, 4))
    replacement = derive_volume(patch_volume, patch_volume.data * 2.0)
    window._replace_patch_viewer_volume(replacement)

    assert window.slice_viewer.current_cursor_position() == (1, 3, 4)
    assert window.slice_viewer.axial_view._source_cursor_position == (1, 3, 4)
    assert window.slice_viewer.axial_view._current_pixmap is not None
    assert window.slice_viewer.axial_view.slice_label.text() == "Slice: 5 / 5"

    window.deleteLater()
    _ = app
