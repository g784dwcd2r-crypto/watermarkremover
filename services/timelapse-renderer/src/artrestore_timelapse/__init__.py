"""ArtRestore Studio timelapse reconstruction.

Turns a finished artwork into a plausible process video. Every output is
labelled a reconstruction: the disclosure is written into file metadata by the
encoder, the visible end card is on by default, and the exported project JSON
records the exact synthetic stage list that produced the result.
"""

from .analysis import ArtworkAnalysis, analyse_artwork  # noqa: F401
from .encode import (  # noqa: F401
    AudioTrack,
    EncodeResult,
    disclosure_metadata,
    encode_gif,
    encode_video,
    encoder_report,
    ffmpeg_available,
    probe,
    write_frame_archive,
    write_poster,
)
from .errors import (  # noqa: F401
    EncoderUnavailableError,
    EncodingFailedError,
    InvalidPlanError,
    RenderCancelledError,
    TimelapseError,
)
from .frames import RenderOptions, RenderPlan, TimelapseRenderer  # noqa: F401
from .presets import (  # noqa: F401
    CANVAS_PRESETS,
    DISCLOSURE_LONG,
    EASING_CURVES,
    END_CARD_TEXT,
    MAX_DURATION_SECONDS,
    MIN_DURATION_SECONDS,
    PROCESS_MARKER,
    RECONSTRUCTION_TYPE,
    SPEED_CHOICES,
    SPEED_RANGE,
    SUPPORTED_FPS,
    resolve_canvas,
)
from .project import build_project_json  # noqa: F401
from .project import dumps as dump_project_json  # noqa: F401
from .reveal import REVEAL_KINDS, apply_reveal, build_reveal_map  # noqa: F401
from .stages import (  # noqa: F401
    MODE_LABELS,
    MODES,
    STAGE_LABELS,
    Stage,
    build_plan,
    describe_plan,
    normalise_plan,
    plan_duration,
)
from .strokes import (  # noqa: F401
    Stroke,
    StrokeField,
    generate_fill_strokes,
    generate_strokes,
    render_strokes,
)

__version__ = "0.1.0"
