from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
import nibabel as nib
import numpy as np

from miview.nifti_io import NiftiLoadResult
from miview.ui.drop_loading import (
    first_supported_local_nifti_path,
    is_supported_nifti_path,
)
from miview.ui.main_window import MainWindow
from miview.ui.patch_window import PatchViewerWindow
from miview.viewer.triplanar_viewer_widget import TriPlanarViewerWidget


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
    data = np.zeros((3, 3, 3), dtype=np.float32)
    affine = np.eye(4)
    header = nib.Nifti1Image(data, affine).header.copy()
    header.set_zooms((1.0, 1.0, 1.0))
    patch_volume = NiftiLoadResult(
        data=data,
        affine=affine,
        header=header,
        shape=(3, 3, 3),
        dtype=data.dtype,
    )

    window = PatchViewerWindow(patch_volume)

    assert not window.acceptDrops()
    assert not window.slice_viewer.acceptDrops()

    window.deleteLater()
    _ = app
