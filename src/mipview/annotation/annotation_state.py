from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from mipview.annotation.annotation_mask import AnnotationMask
from mipview.annotation.undo import AnnotationUndoStack


@dataclass
class AnnotationState:
    active_mask: AnnotationMask | None = None
    active_label: int = 1
    opacity: float = 0.5
    visible: bool = True
    brush_radius: int = 1
    brush_mode: str = "paint"
    undo_stack: AnnotationUndoStack = field(default_factory=AnnotationUndoStack)

    def __post_init__(self) -> None:
        if self.active_label < 0:
            raise ValueError("Active annotation label must be non-negative.")
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError("Annotation opacity must be between 0.0 and 1.0.")
        if self.brush_radius < 0:
            raise ValueError("Annotation brush radius must be non-negative.")
        if self.brush_mode not in {"paint", "erase"}:
            raise ValueError("Annotation brush mode must be 'paint' or 'erase'.")
