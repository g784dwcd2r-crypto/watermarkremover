"""Encoding: MP4, WebM, GIF, poster frames and PNG sequences.

Frames are streamed to FFmpeg over a pipe, so a five-minute render never has to
exist in memory or as thousands of files on disk.

Every video carries the reconstruction disclosure in its container metadata.
That is not optional and there is no flag to turn it off - the visible end card
can be disabled, the metadata cannot.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from .errors import EncoderUnavailableError, EncodingFailedError
from .presets import DISCLOSURE_LONG, END_CARD_TEXT, PROCESS_MARKER, RECONSTRUCTION_TYPE


def disclosure_metadata(extra: dict | None = None) -> dict:
    """The disclosure block written into exports and stored on the Export row."""
    payload = {
        "reconstruction_type": RECONSTRUCTION_TYPE,
        "process": PROCESS_MARKER,
        "comment": DISCLOSURE_LONG,
        "description": DISCLOSURE_LONG,
        "is_original_recording": "false",
        "end_card_text": END_CARD_TEXT,
    }
    payload.update(extra or {})
    return payload


def ffmpeg_available(binary: str = "ffmpeg") -> bool:
    return shutil.which(binary) is not None


def encoder_report(binary: str = "ffmpeg") -> dict:
    """What the deployment can actually produce, for the readiness probe."""
    path = shutil.which(binary)
    if path is None:
        return {"available": False, "encoders": [], "path": None}
    try:
        result = subprocess.run(
            [binary, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20
        )
    except (subprocess.SubprocessError, OSError):
        return {"available": False, "encoders": [], "path": path}
    text = result.stdout
    return {
        "available": True,
        "path": path,
        "encoders": [name for name in ("libx264", "libvpx-vp9", "libvpx") if name in text],
    }


@dataclass(slots=True)
class EncodeResult:
    path: Path
    format: str
    byte_size: int
    width: int
    height: int
    fps: int
    frame_count: int
    duration_seconds: float
    disclosure: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "format": self.format,
            "byte_size": self.byte_size,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "frame_count": self.frame_count,
            "duration_seconds": round(self.duration_seconds, 3),
            "disclosure": self.disclosure,
        }


@dataclass(slots=True)
class AudioTrack:
    """User-supplied music they hold the rights to."""

    path: str
    start_seconds: float = 0.0
    volume: float = 0.8

    def filter_arguments(self, duration: float) -> list[str]:
        return [
            "-ss",
            f"{max(0.0, self.start_seconds):.3f}",
            "-i",
            self.path,
            "-t",
            f"{duration:.3f}",
            "-filter:a",
            f"volume={max(0.0, min(1.0, self.volume)):.3f},afade=t=out:st="
            f"{max(0.0, duration - 1.0):.3f}:d=1",
        ]


def _metadata_arguments(disclosure: dict) -> list[str]:
    """Map the disclosure onto container metadata keys players actually show."""
    mapping = {
        "comment": disclosure["comment"],
        "description": disclosure["description"],
        # 'Reconstructed process' is the required short marker.
        "title": PROCESS_MARKER,
        "synopsis": disclosure["comment"],
        "reconstruction_type": disclosure["reconstruction_type"],
        "process": disclosure["process"],
        "is_original_recording": disclosure["is_original_recording"],
        "software": "ArtRestore Studio",
    }
    arguments: list[str] = []
    for key, value in mapping.items():
        arguments.extend(["-metadata", f"{key}={value}"])
    return arguments


def encode_video(
    frames: Iterable[np.ndarray],
    destination: str | Path,
    *,
    width: int,
    height: int,
    fps: int,
    container: str = "mp4",
    audio: AudioTrack | None = None,
    crf: int = 20,
    binary: str = "ffmpeg",
    extra_disclosure: dict | None = None,
) -> EncodeResult:
    """Encode a frame stream to MP4 (H.264) or WebM (VP9)."""
    if not ffmpeg_available(binary):
        raise EncoderUnavailableError(
            "FFmpeg is not installed, so video export is unavailable on this deployment.",
            details={"binary": binary},
        )

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    disclosure = disclosure_metadata(extra_disclosure)

    if container == "webm":
        codec_arguments = [
            "-c:v",
            "libvpx-vp9",
            "-b:v",
            "0",
            "-crf",
            str(crf + 12),
            "-row-mt",
            "1",
            "-pix_fmt",
            "yuv420p",
        ]
        audio_codec = ["-c:a", "libopus", "-b:a", "128k"]
    else:
        container = "mp4"
        codec_arguments = [
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-preset",
            "medium",
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
        ]
        audio_codec = ["-c:a", "aac", "-b:a", "160k"]

    command = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
    ]
    frame_count_holder: list[int] = [0]

    if audio is not None and os.path.exists(audio.path):
        # Duration is not known until the stream is consumed, so the audio is
        # trimmed with -shortest against the video stream instead.
        command.extend(["-ss", f"{max(0.0, audio.start_seconds):.3f}", "-i", audio.path])
        command.extend(
            [
                "-filter:a",
                f"volume={max(0.0, min(1.0, audio.volume)):.3f}",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-shortest",
            ]
        )
        command.extend(audio_codec)
    else:
        command.append("-an")

    command.extend(codec_arguments)
    command.extend(_metadata_arguments(disclosure))
    command.append(str(destination))

    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        assert process.stdin is not None
        for frame in frames:
            if frame.shape[0] != height or frame.shape[1] != width:
                raise EncodingFailedError(
                    "A frame did not match the declared output size.",
                    details={
                        "expected": [width, height],
                        "received": [int(frame.shape[1]), int(frame.shape[0])],
                    },
                )
            process.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())
            frame_count_holder[0] += 1
        process.stdin.close()
    except BrokenPipeError as exc:
        stderr = process.stderr.read().decode("utf-8", "ignore") if process.stderr else ""
        raise EncodingFailedError(
            "The encoder closed unexpectedly.", details={"stderr": stderr[-2000:]}
        ) from exc
    finally:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()

    stderr_output = process.stderr.read().decode("utf-8", "ignore") if process.stderr else ""
    return_code = process.wait()
    if return_code != 0 or not destination.exists():
        raise EncodingFailedError(
            "FFmpeg could not encode the video.",
            details={"returncode": return_code, "stderr": stderr_output[-2000:]},
        )

    frame_count = frame_count_holder[0]
    return EncodeResult(
        path=destination,
        format=container,
        byte_size=destination.stat().st_size,
        width=width,
        height=height,
        fps=fps,
        frame_count=frame_count,
        duration_seconds=frame_count / float(fps),
        disclosure=disclosure,
    )


def encode_gif(
    frames: Iterable[np.ndarray],
    destination: str | Path,
    *,
    fps: int = 12,
    max_width: int = 480,
    source_fps: int = 30,
    loop: int = 0,
) -> EncodeResult:
    """A GIF preview, sampled down from the full frame stream."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    step = max(1, int(round(source_fps / float(max(1, fps)))))
    images: list[Image.Image] = []
    size: tuple[int, int] | None = None

    for index, frame in enumerate(frames):
        if index % step:
            continue
        image = Image.fromarray(np.ascontiguousarray(frame, dtype=np.uint8), mode="RGB")
        if image.width > max_width:
            scale = max_width / float(image.width)
            image = image.resize((max_width, max(1, int(image.height * scale))), Image.LANCZOS)
        size = image.size
        images.append(image.convert("P", palette=Image.ADAPTIVE, colors=128))

    if not images or size is None:
        raise EncodingFailedError("No frames were produced for the GIF preview.")

    images[0].save(
        destination,
        save_all=True,
        append_images=images[1:],
        duration=int(1000 / max(1, fps)),
        loop=loop,
        optimize=True,
        # The disclosure travels in the GIF comment block.
        comment=DISCLOSURE_LONG.encode("utf-8"),
    )
    # Pillow's optimiser drops frames that are identical to their predecessor,
    # so the count is read back from the file rather than assumed.
    with Image.open(destination) as saved:
        written = int(getattr(saved, "n_frames", len(images)))

    return EncodeResult(
        path=destination,
        format="gif",
        byte_size=destination.stat().st_size,
        width=size[0],
        height=size[1],
        fps=fps,
        frame_count=written,
        duration_seconds=written / float(fps),
        disclosure=disclosure_metadata(),
    )


def write_poster(frame: np.ndarray, destination: str | Path) -> EncodeResult:
    """The poster frame used as a video thumbnail."""
    from PIL import PngImagePlugin

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    disclosure = disclosure_metadata()

    info = PngImagePlugin.PngInfo()
    for key, value in disclosure.items():
        info.add_text(str(key), str(value))
    image = Image.fromarray(np.ascontiguousarray(frame, dtype=np.uint8), mode="RGB")
    image.save(destination, format="PNG", pnginfo=info, optimize=True)

    return EncodeResult(
        path=destination,
        format="png",
        byte_size=destination.stat().st_size,
        width=image.width,
        height=image.height,
        fps=0,
        frame_count=1,
        duration_seconds=0.0,
        disclosure=disclosure,
    )


def write_frame_archive(
    frames: Iterable[np.ndarray], destination: str | Path, *, every: int = 1
) -> EncodeResult:
    """A zip of individual PNG frames, for users who want to re-edit."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    disclosure = disclosure_metadata()

    written = 0
    size = (0, 0)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("DISCLOSURE.txt", DISCLOSURE_LONG + "\n")
        archive.writestr("disclosure.json", json.dumps(disclosure, indent=2))
        for index, frame in enumerate(frames):
            if index % max(1, every):
                continue
            image = Image.fromarray(np.ascontiguousarray(frame, dtype=np.uint8), mode="RGB")
            size = image.size
            buffer = _png_bytes(image)
            archive.writestr(f"frames/frame_{index:06d}.png", buffer)
            written += 1

    return EncodeResult(
        path=destination,
        format="zip",
        byte_size=destination.stat().st_size,
        width=size[0],
        height=size[1],
        fps=0,
        frame_count=written,
        duration_seconds=0.0,
        disclosure=disclosure,
    )


def _png_bytes(image: Image.Image) -> bytes:
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=4)
    return buffer.getvalue()


def tee(frames: Iterable[np.ndarray], sinks: list[list[np.ndarray]]) -> Iterator[np.ndarray]:
    """Yield frames while also collecting them into caches.

    Used when several outputs are requested from one render pass so the frames
    are generated once rather than once per format.
    """
    for frame in frames:
        for sink in sinks:
            sink.append(frame)
        yield frame


def probe(path: str | Path, binary: str = "ffprobe") -> dict:
    """Read back a produced file. Used by the tests and the readiness probe."""
    if shutil.which(binary) is None:
        raise EncoderUnavailableError("ffprobe is not installed.")
    result = subprocess.run(
        [
            binary,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-print_format",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise EncodingFailedError(
            "ffprobe could not read the file.", details={"stderr": result.stderr[-1000:]}
        )
    return json.loads(result.stdout)
