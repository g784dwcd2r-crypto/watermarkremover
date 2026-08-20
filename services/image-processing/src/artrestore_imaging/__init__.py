"""ArtRestore Studio imaging services.

Authorized visible-watermark cleanup: validation, provenance-aware metadata
handling, mask normalisation, protected-region safeguards and inpainting.
"""

from .errors import (  # noqa: F401
    CorruptImageError,
    ImageTooLargeError,
    ImagingError,
    InpaintBackendUnavailableError,
    JobCancelledError,
    MaskError,
    ProtectedRegionError,
    ProtectedRegionReviewError,
    UnsupportedFormatError,
)
from .detection import (  # noqa: F401
    DetectionConfig,
    ProtectionAssessment,
    Region,
    assess_mask,
    detect_overlay_candidates,
    detect_protected_regions,
    subtract_protected,
)
from .masks import (  # noqa: F401
    MaskAdjustments,
    decode_mask_png,
    encode_mask_png,
    mask_components,
    mask_coverage,
    normalize_mask,
    rasterize_editor_state,
)
from .metadata import ProvenanceReport, describe_metadata, detect_provenance  # noqa: F401
from .pipeline import (  # noqa: F401
    CLEANUP_MODES,
    MODE_LABELS,
    CleanupOptions,
    CleanupResult,
    analyse_background,
    build_previews,
    difference_map,
    run_cleanup,
)
from .raster import SafeRaster, downscale, encode_raster, load_safe_raster  # noqa: F401
from .segmentation import segment_box, segment_point, segment_text_overlay  # noqa: F401
from .validation import (  # noqa: F401
    SUPPORTED_MIME_TYPES,
    ValidatedImage,
    estimated_output_bytes,
    sniff_mime,
    validate_image_bytes,
)

__version__ = "0.1.0"
