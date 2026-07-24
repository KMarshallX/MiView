from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from mipview.io.nifti_io import NiftiLoadResult
from mipview.segmentation.overlay import segmentation_label_color
from mipview.vessel_graph.model import VesselGraphRenderGeometry


RENDER_LAYER_BASE = "base"
RENDER_LAYER_OVERLAY = "overlay"
RENDER_LAYERS = (RENDER_LAYER_BASE, RENDER_LAYER_OVERLAY)
RAW_RENDER_MODES = ("MIP", "MinIP", "Translucent", "Isosurface")
SEGMENTATION_RENDER_MODES = ("Surface", "Points")
VESSEL_GRAPH_RENDER_MODES = ("Skeleton",)
MASKED_IMAGE_RENDER_MODES = ("MIP", "MinIP")
MASKED_SEGMENTATION_RENDER_MODES = SEGMENTATION_RENDER_MODES
MAX_SEGMENTATION_LABELS = 256


@dataclass(frozen=True)
class Render3DSource:
    """One standalone file layer available to a 3D viewer."""

    id: str
    display_name: str
    volume: NiftiLoadResult | None
    kind: str
    vessel_graph: VesselGraphRenderGeometry | None = None
    overlay_eligible: bool = True

    def __post_init__(self) -> None:
        if self.kind not in {"image", "segmentation", "vessel_graph"}:
            raise ValueError(
                "3D render source kind must be image, segmentation, or vessel_graph."
            )
        if self.kind == "vessel_graph":
            if self.vessel_graph is None or self.volume is not None:
                raise ValueError(
                    "A vessel-graph 3D source requires graph geometry and no volume."
                )
        elif self.volume is None or self.vessel_graph is not None:
            raise ValueError("A NIfTI 3D source requires a volume and no graph geometry.")


@dataclass
class Render3DSettings:
    """Per-file display settings retained independently of GPU resources."""

    visible: bool = True
    opacity: float = 1.0
    colour: tuple[int, int, int] = (255, 255, 255)
    render_mode: str = "MIP"
    mask_source_id: str | None = None
    threshold: float = 0.0
    node_size: int = 4
    edge_thickness: int = 2
    label_colours: dict[int, tuple[int, int, int]] = field(default_factory=dict)
    dirty: bool = True

    def set_opacity(self, opacity: float) -> None:
        self.opacity = min(max(float(opacity), 0.0), 1.0)

    def set_colour(self, colour: tuple[int, int, int]) -> None:
        if len(colour) != 3 or any(not 0 <= int(value) <= 255 for value in colour):
            raise ValueError("3D layer colour must contain three values in 0..255.")
        self.colour = tuple(int(value) for value in colour)

    def set_node_size(self, node_size: int) -> None:
        self.node_size = min(max(int(node_size), 1), 10)

    def set_edge_thickness(self, edge_thickness: int) -> None:
        self.edge_thickness = min(max(int(edge_thickness), 1), 10)

    def set_label_colour(
        self,
        label: int,
        colour: tuple[int, int, int],
    ) -> None:
        label_value = int(label)
        if label_value <= 0:
            raise ValueError("3D segmentation colours require a positive label.")
        if len(colour) != 3 or any(not 0 <= int(value) <= 255 for value in colour):
            raise ValueError("3D label colour must contain three values in 0..255.")
        self.label_colours[label_value] = tuple(int(value) for value in colour)

    def colour_for_label(self, label: int) -> tuple[int, int, int]:
        label_value = int(label)
        configured = self.label_colours.get(label_value)
        if configured is not None:
            return configured
        default = segmentation_label_color(label_value)
        return tuple(int(value) for value in default)


@dataclass
class Render3DState:
    """File selection and settings for a single isolated 3D scene."""

    sources: dict[str, Render3DSource] = field(default_factory=dict)
    settings: dict[str, Render3DSettings] = field(default_factory=dict)
    overlay_settings: dict[str, Render3DSettings] = field(default_factory=dict)
    selected_source_id: str | None = None
    rendered_source_id: str | None = None
    overlay_selected_source_id: str | None = None
    overlay_rendered_source_id: str | None = None
    active: bool = False
    overlay_active: bool = False
    busy: bool = False
    overlay_busy: bool = False
    last_error: str | None = None
    overlay_last_error: str | None = None
    prepared_shape: tuple[int, int, int] | None = None
    downsample_stride: tuple[int, int, int] | None = None
    overlay_prepared_shape: tuple[int, int, int] | None = None
    overlay_downsample_stride: tuple[int, int, int] | None = None

    def set_sources(self, sources: list[Render3DSource]) -> None:
        new_sources = {source.id: source for source in sources}
        removed = set(self.sources).difference(new_sources)
        for source_id in removed:
            self.settings.pop(source_id, None)
            self.overlay_settings.pop(source_id, None)
        self.sources = new_sources

        for source in sources:
            self.settings.setdefault(source.id, default_settings_for_source(source))
            self.overlay_settings.setdefault(
                source.id,
                default_settings_for_source(source),
            )
        for settings_by_layer in (self.settings, self.overlay_settings):
            for source_id, settings in settings_by_layer.items():
                if settings.mask_source_id not in {
                    source.id for source in self.compatible_masks_for(source_id)
                }:
                    settings.mask_source_id = None

        if self.selected_source_id not in self.sources:
            self.selected_source_id = sources[0].id if sources else None
        if self.rendered_source_id not in self.sources:
            self.rendered_source_id = None
        eligible_overlay_ids = {source.id for source in self.overlay_sources()}
        if self.overlay_selected_source_id not in eligible_overlay_ids:
            self.overlay_selected_source_id = None
        if self.overlay_rendered_source_id not in eligible_overlay_ids:
            self.overlay_rendered_source_id = None

    def overlay_sources(self) -> tuple[Render3DSource, ...]:
        base = self.selected_source()
        return tuple(
            source
            for source in self.sources.values()
            if source.overlay_eligible
            and source.kind in {"segmentation", "vessel_graph"}
            and source.id != self.selected_source_id
            and (
                source.kind == "vessel_graph"
                or base is None
                or base.volume is None
                or (
                    source.volume is not None
                    and _volumes_are_spatially_compatible(
                        base.volume,
                        source.volume,
                    )
                )
            )
        )

    def selected_source(
        self,
        layer: str = RENDER_LAYER_BASE,
    ) -> Render3DSource | None:
        source_id = self._selected_source_id(layer)
        if source_id is None:
            return None
        return self.sources.get(source_id)

    def selected_settings(
        self,
        layer: str = RENDER_LAYER_BASE,
    ) -> Render3DSettings | None:
        source_id = self._selected_source_id(layer)
        if source_id is None:
            return None
        return self._settings_for_layer(layer).get(source_id)

    def select_source(
        self,
        source_id: str | None,
        layer: str = RENDER_LAYER_BASE,
    ) -> None:
        _validate_render_layer(layer)
        if source_id is not None and source_id not in self.sources:
            raise ValueError(f"3D render source does not exist: {source_id}")
        if layer == RENDER_LAYER_OVERLAY:
            eligible_ids = {source.id for source in self.overlay_sources()}
            if source_id is not None and source_id not in eligible_ids:
                raise ValueError(
                    f"3D overlay source is unavailable or is selected as the base: {source_id}"
                )
            self.overlay_selected_source_id = source_id
            return
        self.selected_source_id = source_id
        if source_id == self.overlay_selected_source_id:
            self.overlay_selected_source_id = None
            self.overlay_rendered_source_id = None

    def mark_selected_dirty(self, layer: str = RENDER_LAYER_BASE) -> None:
        settings = self.selected_settings(layer)
        if settings is not None:
            settings.dirty = True

    def compatible_masks_for(
        self,
        source_id: str | None,
    ) -> tuple[Render3DSource, ...]:
        source = self.sources.get(source_id) if source_id is not None else None
        if source is None:
            return ()
        return tuple(
            candidate
            for candidate in self.sources.values()
            if candidate.kind == "segmentation"
            and candidate.id != source.id
            and source.volume is not None
            and candidate.volume is not None
            and _volumes_are_spatially_compatible(
                source.volume,
                candidate.volume,
            )
        )

    def selected_mask_source(
        self,
        layer: str = RENDER_LAYER_BASE,
    ) -> Render3DSource | None:
        settings = self.selected_settings(layer)
        if settings is None or settings.mask_source_id is None:
            return None
        compatible_ids = {
            source.id
            for source in self.compatible_masks_for(self._selected_source_id(layer))
        }
        if settings.mask_source_id not in compatible_ids:
            return None
        return self.sources.get(settings.mask_source_id)

    def layer_status(self, layer: str) -> dict[str, object]:
        _validate_render_layer(layer)
        source = self.selected_source(layer)
        settings = self.selected_settings(layer)
        selected_source_id = self._selected_source_id(layer)
        rendered_source_id = (
            self.rendered_source_id
            if layer == RENDER_LAYER_BASE
            else self.overlay_rendered_source_id
        )
        active = self.active if layer == RENDER_LAYER_BASE else self.overlay_active
        busy = self.busy if layer == RENDER_LAYER_BASE else self.overlay_busy
        prepared_shape = (
            self.prepared_shape
            if layer == RENDER_LAYER_BASE
            else self.overlay_prepared_shape
        )
        downsample_stride = (
            self.downsample_stride
            if layer == RENDER_LAYER_BASE
            else self.overlay_downsample_stride
        )
        last_error = (
            self.last_error
            if layer == RENDER_LAYER_BASE
            else self.overlay_last_error
        )
        return {
            "layer": layer,
            "active": active,
            "busy": busy,
            "selected_source_id": selected_source_id,
            "selected_source_name": None if source is None else source.display_name,
            "selected_source_kind": None if source is None else source.kind,
            "rendered_source_id": rendered_source_id,
            "visible": None if settings is None else settings.visible,
            "opacity": None if settings is None else settings.opacity,
            "colour": None if settings is None else list(settings.colour),
            "label_colours": (
                None
                if settings is None
                else {
                    str(label): list(colour)
                    for label, colour in sorted(settings.label_colours.items())
                }
            ),
            "render_mode": None if settings is None else settings.render_mode,
            "mask_source_id": (
                None if settings is None else settings.mask_source_id
            ),
            "mask_source_name": (
                None
                if settings is None or self.selected_mask_source(layer) is None
                else self.selected_mask_source(layer).display_name
            ),
            "mask_applied": (
                False
                if source is None or settings is None
                else render_mode_supports_mask(source.kind, settings.render_mode)
                and self.selected_mask_source(layer) is not None
            ),
            "threshold": None if settings is None else settings.threshold,
            "node_size": None if settings is None else settings.node_size,
            "edge_thickness": (
                None if settings is None else settings.edge_thickness
            ),
            "update_required": None if settings is None else settings.dirty,
            "prepared_shape": (
                None if prepared_shape is None else list(prepared_shape)
            ),
            "downsample_stride": (
                None
                if downsample_stride is None
                else list(downsample_stride)
            ),
            "last_error": last_error,
        }

    def status(self) -> dict[str, object]:
        base = self.layer_status(RENDER_LAYER_BASE)
        overlay = self.layer_status(RENDER_LAYER_OVERLAY)
        return {
            **base,
            "base": base,
            "overlay": overlay,
        }

    def _selected_source_id(self, layer: str) -> str | None:
        _validate_render_layer(layer)
        return (
            self.selected_source_id
            if layer == RENDER_LAYER_BASE
            else self.overlay_selected_source_id
        )

    def _settings_for_layer(
        self,
        layer: str,
    ) -> dict[str, Render3DSettings]:
        _validate_render_layer(layer)
        return self.settings if layer == RENDER_LAYER_BASE else self.overlay_settings


def default_settings_for_source(source: Render3DSource) -> Render3DSettings:
    if source.kind == "vessel_graph":
        return Render3DSettings(
            colour=(57, 255, 20),
            render_mode="Skeleton",
            threshold=0.0,
        )
    assert source.volume is not None
    data = source.volume.data
    sample_stride = max(1, int(np.ceil(max(data.shape) / 128)))
    sample = np.asarray(data[::sample_stride, ::sample_stride, ::sample_stride])
    finite = sample[np.isfinite(sample)]
    threshold = 0.0
    if finite.size:
        threshold = float(np.median(finite))
    if source.kind == "segmentation":
        return Render3DSettings(
            colour=(230, 70, 70),
            render_mode="Surface",
            threshold=0.5,
        )
    return Render3DSettings(render_mode="MIP", threshold=threshold)


def render_mode_supports_mask(source_kind: str, render_mode: str) -> bool:
    if source_kind == "image":
        return render_mode in MASKED_IMAGE_RENDER_MODES
    if source_kind == "segmentation":
        return render_mode in MASKED_SEGMENTATION_RENDER_MODES
    return False


def segmentation_labels(volume: NiftiLoadResult) -> tuple[int, ...]:
    data = np.asarray(volume.data)
    if data.ndim != 3:
        raise ValueError(f"3D segmentation rendering expects 3D data, got {data.ndim}D.")
    if not np.all(np.isfinite(data)):
        raise ValueError("3D segmentation labels must all be finite.")
    if np.any(data < 0):
        raise ValueError("3D segmentation labels must be non-negative.")
    rounded = np.rint(data)
    if not np.array_equal(data, rounded):
        raise ValueError("3D segmentation labels must be integer-valued.")
    labels = tuple(int(value) for value in np.unique(rounded) if value > 0)
    if len(labels) > MAX_SEGMENTATION_LABELS:
        raise ValueError(
            "3D segmentation rendering supports at most "
            f"{MAX_SEGMENTATION_LABELS} foreground labels; found {len(labels)}."
        )
    return labels


def _validate_render_layer(layer: str) -> None:
    if layer not in RENDER_LAYERS:
        raise ValueError(
            f"3D render layer must be one of: {', '.join(RENDER_LAYERS)}."
        )


def _volumes_are_spatially_compatible(
    source: NiftiLoadResult,
    mask: NiftiLoadResult,
) -> bool:
    return (
        np.asarray(source.data).ndim == 3
        and np.asarray(mask.data).ndim == 3
        and source.shape == mask.shape
        and np.asarray(source.affine).shape == (4, 4)
        and np.asarray(mask.affine).shape == (4, 4)
        and bool(
            np.allclose(
                source.affine,
                mask.affine,
                atol=1.0e-4,
                rtol=0.0,
            )
        )
    )
