from __future__ import annotations

from dataclasses import dataclass

from mipview.annotation.annotation_mask import AnnotationMask


@dataclass
class AnnotationState:
    active_mask: AnnotationMask | None = None
    active_label: int = 1
    opacity: float = 0.5
    visible: bool = True

    def __post_init__(self) -> None:
        if self.active_label < 0:
            raise ValueError("Active annotation label must be non-negative.")
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError("Annotation opacity must be between 0.0 and 1.0.")
