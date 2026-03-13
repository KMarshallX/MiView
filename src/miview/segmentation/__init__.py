<<<<<<< ours
<<<<<<< ours
from miview.segmentation.models import LoadedSegmentation
from miview.segmentation.validation import (
=======
from miview.segmentation_models import LoadedSegmentation
from miview.segmentation_validation import (
>>>>>>> theirs
=======
from miview.segmentation_models import LoadedSegmentation
from miview.segmentation_validation import (
>>>>>>> theirs
    SegmentationValidationResult,
    validate_segmentation_compatibility,
)

__all__ = [
    "LoadedSegmentation",
    "SegmentationValidationResult",
    "validate_segmentation_compatibility",
]