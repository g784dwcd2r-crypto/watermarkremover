"""Video, GIF, poster and archive encoding."""

from __future__ import annotations

import json
import zipfile

import numpy as np
import pytest

from artrestore_timelapse import (
    AudioTrack,
    PROCESS_MARKER,
    RECONSTRUCTION_TYPE,
    RenderOptions,
    TimelapseRenderer,
    build_plan,
    build_project_json,
    disclosure_metadata,
    dump_project_json,
    encode_gif,
    encode_video,
    encoder_report,
    probe,
    write_frame_archive,
    write_poster,
)
from artrestore_timelapse.errors import EncodingFailedError
from artrestore_timelapse import ffmpeg_available

requires_ffmpeg = pytest.mark.skipif(
    not ffmpeg_available(), reason="FFmpeg is not installed on this machine"
)

FPS = 24
DURATION = 5.0


@pytest.fixture
def renderer(analysis):
    return TimelapseRenderer(
        analysis,
        build_plan("paint_reveal", total_seconds=DURATION),
        RenderOptions(fps=FPS, seed=7, preview=True, preview_max_side=160, end_card_seconds=0.5),
    )


def _video_stream(info: dict) -> dict:
    return next(stream for stream in info["streams"] if stream["codec_type"] == "video")


# -- disclosure -------------------------------------------------------------


def test_disclosure_metadata_names_the_reconstruction():
    payload = disclosure_metadata()
    assert payload["reconstruction_type"] == RECONSTRUCTION_TYPE
    assert payload["process"] == PROCESS_MARKER
    assert payload["is_original_recording"] == "false"
    assert "not a recording" in payload["comment"]


def test_extra_disclosure_cannot_be_used_to_claim_authenticity():
    """Callers may add fields, but the reconstruction markers are always present."""
    payload = disclosure_metadata({"custom": "value"})
    assert payload["custom"] == "value"
    assert payload["reconstruction_type"] == RECONSTRUCTION_TYPE


# -- video ------------------------------------------------------------------


@requires_ffmpeg
def test_encoder_report_lists_available_codecs():
    report = encoder_report()
    assert report["available"] is True
    assert "libx264" in report["encoders"]


@requires_ffmpeg
def test_mp4_dimensions_fps_and_duration(renderer, tmp_path):
    destination = tmp_path / "out.mp4"
    result = encode_video(
        renderer.iter_frames(),
        destination,
        width=renderer.plan.width,
        height=renderer.plan.height,
        fps=FPS,
    )
    assert result.byte_size > 0
    assert result.frame_count == renderer.plan.total_frames

    info = probe(destination)
    stream = _video_stream(info)
    assert stream["width"] == renderer.plan.width
    assert stream["height"] == renderer.plan.height
    assert stream["r_frame_rate"] == f"{FPS}/1"

    expected = renderer.plan.total_frames / FPS
    assert float(info["format"]["duration"]) == pytest.approx(expected, abs=0.2)


@requires_ffmpeg
def test_mp4_is_valid_h264(renderer, tmp_path):
    destination = tmp_path / "out.mp4"
    encode_video(
        renderer.iter_frames(),
        destination,
        width=renderer.plan.width,
        height=renderer.plan.height,
        fps=FPS,
    )
    stream = _video_stream(probe(destination))
    assert stream["codec_name"] == "h264"
    assert stream["pix_fmt"] == "yuv420p"
    assert stream["profile"] in ("High", "Main", "Baseline", "Constrained Baseline")


@requires_ffmpeg
def test_mp4_carries_the_disclosure_metadata(renderer, tmp_path):
    destination = tmp_path / "out.mp4"
    encode_video(
        renderer.iter_frames(),
        destination,
        width=renderer.plan.width,
        height=renderer.plan.height,
        fps=FPS,
    )
    tags = {key.lower(): value for key, value in probe(destination)["format"]["tags"].items()}
    assert tags["title"] == PROCESS_MARKER
    assert "not a recording of the original creation process" in tags["comment"]


@requires_ffmpeg
def test_webm_output(renderer, tmp_path):
    destination = tmp_path / "out.webm"
    result = encode_video(
        renderer.iter_frames(),
        destination,
        width=renderer.plan.width,
        height=renderer.plan.height,
        fps=FPS,
        container="webm",
    )
    assert result.format == "webm"
    stream = _video_stream(probe(destination))
    assert stream["codec_name"] in ("vp9", "vp8")
    assert stream["width"] == renderer.plan.width


@requires_ffmpeg
@pytest.mark.parametrize("fps", [24, 30, 60])
def test_supported_frame_rates(analysis, tmp_path, fps):
    renderer = TimelapseRenderer(
        analysis,
        build_plan("paint_reveal", total_seconds=5),
        RenderOptions(fps=fps, seed=2, preview=True, preview_max_side=120, end_card_seconds=0.3),
    )
    destination = tmp_path / f"out{fps}.mp4"
    encode_video(
        renderer.iter_frames(),
        destination,
        width=renderer.plan.width,
        height=renderer.plan.height,
        fps=fps,
    )
    assert _video_stream(probe(destination))["r_frame_rate"] == f"{fps}/1"


@requires_ffmpeg
def test_audio_is_muxed_and_stays_in_sync(renderer, tmp_path, audio_file):
    destination = tmp_path / "with-audio.mp4"
    encode_video(
        renderer.iter_frames(),
        destination,
        width=renderer.plan.width,
        height=renderer.plan.height,
        fps=FPS,
        audio=AudioTrack(path=audio_file, start_seconds=1.0, volume=0.5),
    )
    info = probe(destination)
    audio_streams = [stream for stream in info["streams"] if stream["codec_type"] == "audio"]
    assert audio_streams, "no audio stream was muxed"

    video = _video_stream(info)
    video_duration = float(video.get("duration") or info["format"]["duration"])
    audio_duration = float(audio_streams[0].get("duration") or info["format"]["duration"])
    # -shortest trims the music to the video rather than letting it run on.
    assert audio_duration == pytest.approx(video_duration, abs=0.3)


@requires_ffmpeg
def test_same_seed_produces_byte_identical_video(analysis, tmp_path):
    def render(path):
        renderer = TimelapseRenderer(
            analysis,
            build_plan("hand_drawn_strokes", total_seconds=5),
            RenderOptions(fps=24, seed=1234, preview=True, preview_max_side=120,
                          end_card_seconds=0.3),
        )
        encode_video(
            renderer.iter_frames(),
            path,
            width=renderer.plan.width,
            height=renderer.plan.height,
            fps=24,
        )
        return path.read_bytes()

    first = render(tmp_path / "a.mp4")
    second = render(tmp_path / "b.mp4")
    assert first == second, "the same seed must reproduce the same video"


@requires_ffmpeg
def test_frame_size_mismatch_is_rejected(tmp_path):
    frames = [np.zeros((10, 10, 3), np.uint8), np.zeros((12, 10, 3), np.uint8)]
    with pytest.raises(EncodingFailedError):
        encode_video(iter(frames), tmp_path / "bad.mp4", width=10, height=10, fps=24)


# -- other outputs ----------------------------------------------------------


def test_gif_preview_is_sampled_down(renderer, tmp_path):
    destination = tmp_path / "preview.gif"
    result = encode_gif(
        renderer.iter_frames(), destination, fps=8, max_width=160, source_fps=FPS
    )
    assert result.format == "gif"
    assert result.byte_size > 0
    assert result.width <= 160
    assert result.frame_count < renderer.plan.total_frames

    from PIL import Image

    with Image.open(destination) as image:
        assert image.is_animated
        assert image.n_frames == result.frame_count


def test_poster_frame_carries_the_disclosure(renderer, tmp_path):
    frames = list(renderer.iter_frames())
    destination = tmp_path / "poster.png"
    result = write_poster(frames[-1], destination)
    assert result.format == "png"

    from PIL import Image

    with Image.open(destination) as image:
        assert image.text["reconstruction_type"] == RECONSTRUCTION_TYPE
        assert image.size == (renderer.plan.width, renderer.plan.height)


def test_frame_archive_contains_pngs_and_the_disclosure(renderer, tmp_path):
    destination = tmp_path / "frames.zip"
    result = write_frame_archive(renderer.iter_frames(), destination, every=6)
    assert result.frame_count > 0

    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
        assert "DISCLOSURE.txt" in names
        payload = json.loads(archive.read("disclosure.json"))
        assert payload["reconstruction_type"] == RECONSTRUCTION_TYPE
        assert sum(1 for name in names if name.endswith(".png")) == result.frame_count


def test_project_json_records_the_seed_and_stage_list(analysis, renderer):
    stages = build_plan("paint_reveal", total_seconds=DURATION)
    document = build_project_json(
        project_name="Demo",
        mode="paint_reveal",
        stages=stages,
        options=renderer.options,
        plan=renderer.plan,
        analysis_summary=analysis.summary(),
    )
    assert document["seed"] == renderer.options.seed
    assert document["disclosure"]["is_original_recording"] is False
    assert len(document["stages"]) == len(stages)
    assert document["stages"][0]["starts_at"] == 0.0

    reloaded = json.loads(dump_project_json(document))
    assert reloaded["project"]["mode"] == "paint_reveal"


def test_project_json_flags_simulated_cursor(analysis, renderer):
    renderer.options.show_cursor = True
    document = build_project_json(
        project_name="Demo",
        mode="paint_reveal",
        stages=build_plan("paint_reveal", total_seconds=DURATION),
        options=renderer.options,
        plan=renderer.plan,
        analysis_summary=analysis.summary(),
    )
    assert document["disclosure"]["simulated_cursor"] is True
    assert "not a recording of real input" in document["disclosure"]["simulated_cursor_note"]
