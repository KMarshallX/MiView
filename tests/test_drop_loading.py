from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImageWriter
from PySide6.QtWidgets import QApplication
import nibabel as nib
import numpy as np
import pytest

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


def test_patch_window_uses_separate_scroll_regions_for_viewer_and_config() -> None:
    app = QApplication.instance() or QApplication([])
    patch_volume = _build_test_volume((5, 5, 5))

    window = PatchViewerWindow(patch_volume)

    assert window._main_splitter.widget(0) is window._viewer_scroll_area
    assert window._main_splitter.widget(1) is window._right_control_scroll_area
    assert (
        window._viewer_scroll_area.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    assert (
        window._viewer_scroll_area.verticalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    assert (
        window._right_control_scroll_area.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    assert (
        window._right_control_scroll_area.verticalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    assert window.slice_viewer.minimumWidth() > 0
    assert window._right_control_container.minimumWidth() >= window.cursor_panel.minimumWidth()

    window.deleteLater()
    _ = app


def test_patch_window_has_views_export_button_above_save_patch_button() -> None:
    app = QApplication.instance() or QApplication([])
    patch_volume = _build_test_volume((5, 5, 5))
    window = PatchViewerWindow(patch_volume)

    save_layout = window.patch_save_panel.layout()
    assert save_layout is not None
    assert save_layout.itemAt(0).widget() is window.save_views_button
    assert save_layout.itemAt(1).widget() is window.save_patch_button

    window.deleteLater()
    _ = app


def test_patch_window_builds_composite_image_from_current_views() -> None:
    app = QApplication.instance() or QApplication([])
    patch_volume = _build_test_volume((5, 5, 5))
    window = PatchViewerWindow(patch_volume)
    window.projection_mode_combo.setCurrentText("MinIP")
    window.axial_toggle_button.setChecked(True)
    window.coronal_toggle_button.setChecked(True)
    window.sagittal_toggle_button.setChecked(True)

    composite = window._build_views_composite_image()

    assert composite is not None
    assert composite.width() > 0
    assert composite.height() > 0

    window.deleteLater()
    _ = app


def test_patch_window_export_computes_true_three_direction_projection_planes() -> None:
    app = QApplication.instance() or QApplication([])
    patch_volume = _build_test_volume((4, 5, 6))
    window = PatchViewerWindow(patch_volume)

    window.projection_mode_combo.setCurrentText("MIP")
    computed_mip = window._compute_projection_planes_for_export()
    assert computed_mip is not None
    np.testing.assert_allclose(
        computed_mip["axial"],
        np.max(patch_volume.data, axis=2).T[::-1, ::-1],
    )
    np.testing.assert_allclose(
        computed_mip["coronal"],
        np.max(patch_volume.data, axis=1).T[::-1, ::-1],
    )
    np.testing.assert_allclose(
        computed_mip["sagittal"],
        np.max(patch_volume.data, axis=0).T[::-1, ::-1],
    )

    window.projection_mode_combo.setCurrentText("MinIP")
    computed_minip = window._compute_projection_planes_for_export()
    assert computed_minip is not None
    np.testing.assert_allclose(
        computed_minip["axial"],
        np.min(patch_volume.data, axis=2).T[::-1, ::-1],
    )

    window.deleteLater()
    _ = app


def test_patch_window_export_size_scales_each_projection_panel() -> None:
    app = QApplication.instance() or QApplication([])
    patch_volume = _build_test_volume((4, 5, 6))
    window = PatchViewerWindow(patch_volume)
    window.projection_mode_combo.setCurrentText("MIP")

    planes = window._compute_projection_planes_for_export()
    assert planes is not None
    axial_shape = planes["axial"].shape
    composite = window._build_views_composite_image()
    assert composite is not None

    expected_scaled_panel_width = axial_shape[1] * window.VIEW_EXPORT_SCALE_FACTOR
    expected_scaled_panel_height = axial_shape[0] * window.VIEW_EXPORT_SCALE_FACTOR
    assert expected_scaled_panel_width >= axial_shape[1] * 3
    assert expected_scaled_panel_height >= axial_shape[0] * 3
    assert composite.width() >= expected_scaled_panel_width * 3
    assert composite.height() >= expected_scaled_panel_height

    window.deleteLater()
    _ = app


def test_patch_window_composite_export_saves_png_and_jpg(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    patch_volume = _build_test_volume((5, 5, 5))
    window = PatchViewerWindow(patch_volume)
    window.axial_toggle_button.setChecked(True)
    window.coronal_toggle_button.setChecked(True)
    window.sagittal_toggle_button.setChecked(True)
    composite = window._build_views_composite_image()
    assert composite is not None

    png_target, png_format = window._resolve_views_export_target(
        str(tmp_path / "views"),
        "PNG Image (*.png)",
    )
    assert composite.save(str(png_target), png_format)
    assert png_target.suffix.lower() == ".png"
    assert png_target.exists()

    supported_formats = {
        bytes(value).decode("ascii").lower()
        for value in QImageWriter.supportedImageFormats()
    }
    if "jpg" not in supported_formats and "jpeg" not in supported_formats:
        pytest.skip("JPEG export is not supported by this Qt build.")

    jpg_target, jpg_format = window._resolve_views_export_target(
        str(tmp_path / "views"),
        "JPEG Image (*.jpg *.jpeg)",
    )
    assert composite.save(str(jpg_target), jpg_format)
    assert jpg_target.suffix.lower() == ".jpg"
    assert jpg_target.exists()

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
