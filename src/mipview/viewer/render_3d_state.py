from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from mipview.io.nifti_io import NiftiLoadResult


RAW_RENDER_MODES = ("MIP", "MinIP", "Translucent", "Isosurface")
SEGMENTATION_RENDER_MODES = ("Surface", "Points")


@dataclass(frozen=True)
class Render3DSource:
    """A loaded NIfTI volume available to one 3D viewer."""

    id: str
    display_name: str
    volume: NiftiLoadResult
    kind: str

    def __post_init__(self) -> None:
        if self.kind not in {"image", "segmentation"}:
            raise ValueError("3D render source kind must be image or segmentation.")


@dataclass
class Render3DSettings:
    """Per-file display settings retained independently of GPU resources."""

    visible: bool = True
    opacity: float = 1.0
    colour: tuple[int, int, int] = (255, 255, 255)
    render_mode: str = "MIP"
    threshold: float = 0.0
    dirty: bool = True

    def set_opacity(self, opacity: float) -> None:
        self.opacity = min(max(float(opacity), 0.0), 1.0)

    def set_colour(self, colour: tuple[int, int, int]) -> None:
        if len(colour) != 3 or any(not 0 <= int(value) <= 255 for value in colour):
            raise ValueError("3D layer colour must contain three values in 0..255.")
        self.colour = tuple(int(value) for value in colour)


@dataclass
class Render3DState:
    """File selection and settings for a single isolated 3D scene."""

    sources: dict[str, Render3DSource] = field(default_factory=dict)
    settings: dict[str, Render3DSettings] = field(default_factory=dict)
    selected_source_id: str | None = None
    rendered_source_id: str | None = None
    active: bool = False
    busy: bool = False
    last_error: str | None = None
    prepared_shape: tuple[int, int, int] | None = None
    downsample_stride: tuple[int, int, int] | None = None

    def set_sources(self, sources: list[Render3DSource]) -> None:
        new_sources = {source.id: source for source in sources}
        removed = set(self.sources).difference(new_sources)
        for source_id in removed:
            self.settings.pop(source_id, None)
        self.sources = new_sources

        for source in sources:
            self.settings.setdefault(source.id, default_settings_for_source(source))

        if self.selected_source_id not in self.sources:
            self.selected_source_id = sources[0].id if sources else None
        if self.rendered_source_id not in self.sources:
            self.rendered_source_id = None

    def selected_source(self) -> Render3DSource | None:
        if self.selected_source_id is None:
            return None
        return self.sources.get(self.selected_source_id)

    def selected_settings(self) -> Render3DSettings | None:
        if self.selected_source_id is None:
            return None
        return self.settings.get(self.selected_source_id)

    def select_source(self, source_id: str | None) -> None:
        if source_id is not None and source_id not in self.sources:
            raise ValueError(f"3D render source does not exist: {source_id}")
        self.selected_source_id = source_id

    def mark_selected_dirty(self) -> None:
        settings = self.selected_settings()
        if settings is not None:
            settings.dirty = True

    def status(self) -> dict[str, object]:
        source = self.selected_source()
        settings = self.selected_settings()
        return {
            "active": self.active,
            "busy": self.busy,
            "selected_source_id": self.selected_source_id,
            "selected_source_name": None if source is None else source.display_name,
            "rendered_source_id": self.rendered_source_id,
            "visible": None if settings is None else settings.visible,
            "opacity": None if settings is None else settings.opacity,
            "colour": None if settings is None else list(settings.colour),
            "render_mode": None if settings is None else settings.render_mode,
            "threshold": None if settings is None else settings.threshold,
            "update_required": None if settings is None else settings.dirty,
            "prepared_shape": (
                None if self.prepared_shape is None else list(self.prepared_shape)
            ),
            "downsample_stride": (
                None
                if self.downsample_stride is None
                else list(self.downsample_stride)
            ),
            "last_error": self.last_error,
        }


def default_settings_for_source(source: Render3DSource) -> Render3DSettings:
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
