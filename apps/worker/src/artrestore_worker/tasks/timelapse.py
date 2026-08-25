"""Timelapse analysis, preview and render tasks.

Renders stream frames straight into the encoder, so a five-minute 1080p video
never materialises in memory. Where several formats are requested the render
runs again per format rather than caching frames - the seed makes every pass
identical, which is cheaper than holding gigabytes of RGB.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from artrestore_api.config import get_settings
from artrestore_api.db import session_scope
from artrestore_api.logging_setup import log_context
from artrestore_api.models import Asset, Export, ProcessingJob, Project, TimelapseStage
from artrestore_api.queue import (
    TASK_TIMELAPSE_ANALYZE,
    TASK_TIMELAPSE_PREVIEW,
    TASK_TIMELAPSE_RENDER,
    get_celery_app,
)
from artrestore_api.services import jobs as job_service
from artrestore_api.storage import build_object_key, get_storage
from artrestore_imaging import load_safe_raster
from artrestore_imaging.errors import ImagingError
from artrestore_timelapse import (
    AudioTrack,
    RenderOptions,
    Stage,
    TimelapseRenderer,
    analyse_artwork,
    build_plan,
    build_project_json,
    describe_plan,
    disclosure_metadata,
    dump_project_json,
    encode_gif,
    encode_video,
    normalise_plan,
    write_frame_archive,
    write_poster,
)
from artrestore_timelapse.errors import RenderCancelledError, TimelapseError
from sqlalchemy import select

from ..progress import ProgressReporter

logger = logging.getLogger(__name__)

celery_app = get_celery_app()

MIME_BY_FORMAT = {
    "mp4": "video/mp4",
    "webm": "video/webm",
    "gif": "image/gif",
    "poster": "image/png",
    "frames": "application/zip",
    "project_json": "application/json",
    "svg": "image/svg+xml",
}


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@celery_app.task(name=TASK_TIMELAPSE_ANALYZE, bind=True, acks_late=True)
def analyze_artwork_task(self, job_id: str) -> dict:
    """Analyse the artwork and seed an editable stage timeline."""
    settings = get_settings()
    storage = get_storage()
    reporter = ProgressReporter(job_id)

    context = _begin(job_id)
    if context is None:
        return {"status": "unknown_job"}
    project_id, _user_id, parameters = context

    try:
        reporter.report(0.1, "Loading artwork", force=True)
        source_key, _ = _source_key(project_id, parameters.get("asset_id"))
        raster = load_safe_raster(
            storage.get_bytes(source_key), max_pixels=settings.max_image_pixels
        )

        reporter.report(0.35, "Analysing structure, colour and value", force=True)
        analysis = analyse_artwork(raster.rgb, seed=int(parameters.get("seed", 0)))
        summary = analysis.summary()

        mode = str(parameters.get("mode", "sketch_to_colour"))
        intermediate_count = _intermediate_count(project_id)
        reporter.report(0.75, "Building the stage timeline", force=True)
        stages = build_plan(
            mode,
            total_seconds=float(parameters.get("duration_seconds", 12.0)),
            intermediate_count=intermediate_count,
        )
        _replace_stages(project_id, stages)

        with session_scope() as session:
            project = session.get(Project, project_id)
            if project is not None:
                project.settings = {
                    **(project.settings or {}),
                    "timelapse": {
                        "mode": mode,
                        "seed": int(parameters.get("seed", 0)),
                        "analysis": summary,
                        "intermediate_count": intermediate_count,
                    },
                }

        payload = {
            "status": "succeeded",
            "mode": mode,
            "analysis": summary,
            "intermediate_count": intermediate_count,
            "stages": describe_plan(stages),
        }
        _finish(job_id, payload)
        return payload

    except (TimelapseError, ImagingError) as exc:
        return _fail(job_id, exc.code, exc.message, getattr(exc, "details", {}))
    except Exception:
        logger.exception("timelapse analysis failed", extra=log_context(job_id=job_id))
        return _fail(job_id, "internal_error", "The artwork could not be analysed.")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@celery_app.task(name=TASK_TIMELAPSE_PREVIEW, bind=True, acks_late=True)
def render_preview_task(self, job_id: str) -> dict:
    """A fast, low-resolution look at the current timeline."""
    return _render(job_id, preview=True)


@celery_app.task(name=TASK_TIMELAPSE_RENDER, bind=True, acks_late=True)
def render_timelapse_task(self, job_id: str) -> dict:
    """The full-resolution render and its exports."""
    return _render(job_id, preview=False)


def _render(job_id: str, *, preview: bool) -> dict:
    settings = get_settings()
    storage = get_storage()
    reporter = ProgressReporter(job_id)

    context = _begin(job_id)
    if context is None:
        return {"status": "unknown_job"}
    project_id, user_id, parameters = context

    try:
        reporter.report(0.03, "Loading artwork", force=True)
        source_key, source_asset_id = _source_key(project_id, parameters.get("asset_id"))
        raster = load_safe_raster(
            storage.get_bytes(source_key), max_pixels=settings.max_image_pixels
        )

        seed = int(parameters.get("seed", 0))
        reporter.report(0.08, "Analysing artwork", force=True)
        analysis = analyse_artwork(raster.rgb, seed=seed)

        intermediates = _load_intermediates(project_id, storage, settings)
        line_art = _load_line_art(project_id, storage, settings)
        stages = _load_stages(project_id, parameters)

        options = RenderOptions(
            fps=int(parameters.get("fps", 30)),
            preset=str(parameters.get("preset", "square")),
            background_colour=str(parameters.get("background_colour", "#F7F4EF")),
            transition_curve=str(parameters.get("transition_curve", "ease_in_out")),
            stroke_speed=float(parameters.get("stroke_speed", 1.0)),
            stroke_density=float(parameters.get("stroke_density", 1.0)),
            brush_size_min=int(parameters.get("brush_size_min", 6)),
            brush_size_max=int(parameters.get("brush_size_max", 48)),
            seed=seed,
            zoom_pan=bool(parameters.get("zoom_pan", False)),
            show_cursor=bool(parameters.get("show_cursor", False)),
            end_card_disclosure=bool(parameters.get("end_card_disclosure", True)),
            preview=preview,
            preview_max_side=settings.preview_max_dimension,
            brand_watermark=_load_brand_mark(
                project_id, parameters.get("brand_watermark_asset_id"), storage, settings
            ),
        )

        renderer = TimelapseRenderer(
            analysis, stages, options, intermediates=intermediates, line_art=line_art
        )
        formats = _requested_formats(parameters, preview)

        with tempfile.TemporaryDirectory(prefix="artrestore-render-") as workspace:
            audio = _prepare_audio(project_id, parameters, storage, workspace, preview)
            outputs = _produce_outputs(
                renderer=renderer,
                formats=formats,
                workspace=Path(workspace),
                audio=audio,
                reporter=reporter,
                settings=settings,
                gif_fps=int(parameters.get("gif_fps", 12)),
                gif_max_width=int(parameters.get("gif_max_width", 480)),
            )
            project_document = build_project_json(
                project_name=_project_name(project_id),
                mode=str(parameters.get("mode", "sketch_to_colour")),
                stages=stages,
                options=options,
                plan=renderer.plan,
                analysis_summary=analysis.summary(),
                source={
                    "asset_id": source_asset_id,
                    "width": raster.width,
                    "height": raster.height,
                },
                intermediates=[
                    {"index": index, "used_as_keyframe": True}
                    for index in range(len(intermediates))
                ],
            )
            if "project_json" in formats:
                path = Path(workspace) / "project.json"
                path.write_bytes(dump_project_json(project_document))
                outputs.append(
                    {
                        "format": "project_json",
                        "path": path,
                        "byte_size": path.stat().st_size,
                        "disclosure": project_document["disclosure"],
                        "settings": {"version": project_document["version"]},
                    }
                )

            reporter.report(0.9, "Storing exports", force=True)
            stored = _store_outputs(
                outputs, project_id=project_id, user_id=user_id, storage=storage, preview=preview
            )

        payload = {
            "status": "succeeded",
            "preview": preview,
            "width": renderer.plan.width,
            "height": renderer.plan.height,
            "fps": renderer.plan.fps,
            "duration_seconds": renderer.plan.duration_seconds,
            "total_frames": renderer.plan.total_frames,
            "exports": stored,
            "stages": describe_plan(stages),
            "disclosure": project_document["disclosure"],
        }
        _finish(job_id, payload)
        return payload

    except RenderCancelledError:
        with session_scope() as session:
            job = session.get(ProcessingJob, job_id)
            if job is not None:
                job_service.mark_cancelled(session, job)
        return {"status": "cancelled"}
    except (TimelapseError, ImagingError) as exc:
        return _fail(job_id, exc.code, exc.message, getattr(exc, "details", {}))
    except Exception:
        logger.exception("timelapse render failed", extra=log_context(job_id=job_id))
        return _fail(job_id, "internal_error", "The timelapse could not be rendered.")


def _produce_outputs(
    *,
    renderer: TimelapseRenderer,
    formats: list[str],
    workspace: Path,
    audio: AudioTrack | None,
    reporter: ProgressReporter,
    settings,
    gif_fps: int = 12,
    gif_max_width: int = 480,
) -> list[dict]:
    """Render each requested output.

    The first video pass also collects the GIF sample and the poster frame, so
    the common case (MP4 + GIF + poster) costs exactly one pass.
    """
    outputs: list[dict] = []
    plan = renderer.plan
    gif_wanted = "gif" in formats
    poster_wanted = "poster" in formats
    gif_frames: list = []
    poster_frame = None

    gif_step = max(1, int(round(plan.fps / float(max(1, gif_fps)))))

    def instrumented():
        nonlocal poster_frame
        for index, frame in enumerate(
            renderer.iter_frames(
                progress=lambda fraction, message: reporter.report(0.1 + fraction * 0.7, message),
                should_cancel=reporter.should_cancel,
            )
        ):
            if gif_wanted and index % gif_step == 0:
                gif_frames.append(frame.copy())
            if poster_wanted:
                poster_frame = frame
            yield frame

    video_formats = [name for name in ("mp4", "webm") if name in formats]
    if video_formats:
        primary = video_formats[0]
        destination = workspace / f"timelapse.{primary}"
        result = encode_video(
            instrumented(),
            destination,
            width=plan.width,
            height=plan.height,
            fps=plan.fps,
            container=primary,
            audio=audio,
            binary=settings.ffmpeg_binary,
        )
        outputs.append(_output_entry(primary, destination, result))

        for extra in video_formats[1:]:
            reporter.report(0.8, f"Encoding {extra.upper()}", force=True)
            extra_destination = workspace / f"timelapse.{extra}"
            extra_result = encode_video(
                renderer.iter_frames(should_cancel=reporter.should_cancel),
                extra_destination,
                width=plan.width,
                height=plan.height,
                fps=plan.fps,
                container=extra,
                audio=audio,
                binary=settings.ffmpeg_binary,
            )
            outputs.append(_output_entry(extra, extra_destination, extra_result))
    elif gif_wanted or poster_wanted:
        # No video requested: still need one pass to collect the stills.
        for _ in instrumented():
            pass

    if gif_wanted and gif_frames:
        reporter.report(0.84, "Building GIF preview", force=True)
        destination = workspace / "timelapse.gif"
        result = encode_gif(iter(gif_frames), destination, fps=12, max_width=480, source_fps=12)
        outputs.append(_output_entry("gif", destination, result))

    if poster_wanted and poster_frame is not None:
        destination = workspace / "poster.png"
        result = write_poster(poster_frame, destination)
        outputs.append(_output_entry("poster", destination, result))

    if "svg" in formats:
        reporter.report(0.85, "Writing stroke SVG", force=True)
        destination = workspace / "strokes.svg"
        _write_stroke_svg(renderer, destination)
        outputs.append(
            {
                "format": "svg",
                "path": destination,
                "byte_size": destination.stat().st_size,
                "disclosure": disclosure_metadata(),
                "settings": {"kind": "simulated_stroke_paths"},
            }
        )

    if "frames" in formats:
        reporter.report(0.86, "Writing frame archive", force=True)
        destination = workspace / "frames.zip"
        result = write_frame_archive(
            renderer.iter_frames(should_cancel=reporter.should_cancel), destination, every=1
        )
        outputs.append(_output_entry("frames", destination, result))

    return outputs


KNOWN_FORMATS = ("mp4", "webm", "gif", "poster", "frames", "project_json", "svg")


def _requested_formats(parameters: dict, preview: bool) -> list[str]:
    """Which outputs to produce, in a stable order.

    A preview is for judging timing, so it is always a single low-resolution
    MP4 no matter what the request asked for.
    """
    if preview:
        return ["mp4"]
    requested = [name for name in (parameters.get("formats") or ["mp4"]) if name in KNOWN_FORMATS]
    if not requested:
        requested = ["mp4"]
    return [name for name in KNOWN_FORMATS if name in requested]


def _write_stroke_svg(renderer: TimelapseRenderer, destination: Path) -> None:
    """Export the simulated stroke passes as SVG paths.

    One layer group per pass, each path carrying its width and opacity, and a
    leading comment stating that the strokes are generated - they are vector
    material for the user's own motion tooling, not recorded input.
    """
    from artrestore_timelapse import DISCLOSURE_LONG, generate_strokes

    analysis = renderer.analysis
    options = renderer.options
    width, height = analysis.size
    groups: list[str] = []
    for index, pass_name in enumerate(("structure", "mass", "detail")):
        field = generate_strokes(
            analysis,
            pass_name=pass_name,
            density=options.stroke_density,
            brush_min=float(options.brush_size_min),
            brush_max=float(options.brush_size_max),
            seed=options.seed + index,
        )
        paths = "\n".join(
            f'    <path d="{stroke.to_svg_path()}" stroke-width="{stroke.width:.2f}" '
            f'stroke-opacity="{stroke.opacity:.2f}" />'
            for stroke in field.strokes
            if stroke.points
        )
        groups.append(f'  <g id="pass-{pass_name}" data-order="{index}">\n{paths}\n  </g>')

    document = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<!-- {DISCLOSURE_LONG} Stroke paths are simulated, not recorded input. -->\n"
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" stroke="#2c2c2c" fill="none" stroke-linecap="round">\n'
        + "\n".join(groups)
        + "\n</svg>\n"
    )
    destination.write_text(document, encoding="utf-8")


def _output_entry(name: str, path: Path, result) -> dict:
    return {
        "format": name,
        "path": path,
        "byte_size": result.byte_size,
        "disclosure": result.disclosure,
        "settings": result.to_dict(),
    }


# ---------------------------------------------------------------------------
# Storage and database helpers
# ---------------------------------------------------------------------------


def _store_outputs(
    outputs: list[dict], *, project_id: str, user_id: str, storage, preview: bool
) -> list[dict]:
    stored: list[dict] = []
    with session_scope() as session:
        for entry in outputs:
            name = entry["format"]
            extension = {
                "poster": "png",
                "frames": "zip",
                "project_json": "json",
                "svg": "svg",
            }.get(name, name)
            prefix = "preview" if preview else "timelapse"
            key = build_object_key(user_id, project_id, "export", f"{prefix}-{name}.{extension}")
            storage.put_bytes(
                key,
                Path(entry["path"]).read_bytes(),
                MIME_BY_FORMAT.get(name, "application/octet-stream"),
            )
            export = Export(
                project_id=project_id,
                format=(
                    "png"
                    if name == "poster"
                    else (
                        "zip" if name == "frames" else ("json" if name == "project_json" else name)
                    )
                ),
                storage_key=key,
                byte_size=int(entry["byte_size"]),
                settings={**entry["settings"], "preview": preview, "output": name},
                disclosure_metadata=entry["disclosure"],
            )
            session.add(export)
            session.flush()
            stored.append(
                {
                    "export_id": export.id,
                    "format": export.format,
                    "output": name,
                    "byte_size": export.byte_size,
                }
            )
    return stored


def _begin(job_id: str) -> tuple[str, str, dict] | None:
    with session_scope() as session:
        job = session.get(ProcessingJob, job_id)
        if job is None:
            logger.warning("timelapse task for unknown job", extra=log_context(job_id=job_id))
            return None
        if job.status == "cancelled" or job.cancel_requested:
            job_service.mark_cancelled(session, job)
            return None
        project = session.get(Project, job.project_id)
        if project is None:
            job_service.mark_failed(
                session, job, code="not_found", message="The project no longer exists."
            )
            return None
        job_service.mark_running(session, job)
        return project.id, project.user_id, dict(job.parameters or {})


def _finish(job_id: str, payload: dict) -> None:
    with session_scope() as session:
        job = session.get(ProcessingJob, job_id)
        if job is None:
            return
        if job.cancel_requested:
            job_service.mark_cancelled(session, job)
            return
        job_service.mark_succeeded(session, job, payload)


def _fail(job_id: str, code: str, message: str, details: dict | None = None) -> dict:
    with session_scope() as session:
        job = session.get(ProcessingJob, job_id)
        if job is not None:
            job_service.mark_failed(
                session, job, code=code, message=message, result={"details": details or {}}
            )
    return {"status": "failed", "code": code}


def _source_key(project_id: str, asset_id: str | None) -> tuple[str, str]:
    with session_scope() as session:
        if asset_id:
            asset = session.get(Asset, asset_id)
            if asset is None or asset.project_id != project_id:
                raise ImagingError("The requested artwork does not belong to this project.")
        else:
            asset = session.execute(
                select(Asset)
                .where(
                    Asset.project_id == project_id,
                    Asset.type == "source",
                    Asset.upload_complete.is_(True),
                )
                .order_by(Asset.created_at.asc())
                .limit(1)
            ).scalar_one_or_none()
        if asset is None:
            raise ImagingError("Upload the finished artwork before rendering a timelapse.")
        return asset.storage_key, asset.id


def _intermediate_count(project_id: str) -> int:
    with session_scope() as session:
        return len(
            session.execute(
                select(Asset.id).where(
                    Asset.project_id == project_id,
                    Asset.type == "intermediate",
                    Asset.upload_complete.is_(True),
                )
            ).all()
        )


def _load_intermediates(project_id: str, storage, settings) -> list:
    """The artist's own progress images, in the order they uploaded them."""
    with session_scope() as session:
        rows = list(
            session.execute(
                select(Asset)
                .where(
                    Asset.project_id == project_id,
                    Asset.type == "intermediate",
                    Asset.upload_complete.is_(True),
                )
                .order_by(Asset.order_index, Asset.created_at)
            ).scalars()
        )
        keys = [row.storage_key for row in rows]
    return [
        load_safe_raster(storage.get_bytes(key), max_pixels=settings.max_image_pixels).rgb
        for key in keys
    ]


def _load_line_art(project_id: str, storage, settings):
    import cv2

    with session_scope() as session:
        row = session.execute(
            select(Asset)
            .where(
                Asset.project_id == project_id,
                Asset.type == "line_art",
                Asset.upload_complete.is_(True),
            )
            .order_by(Asset.created_at)
            .limit(1)
        ).scalar_one_or_none()
        key = row.storage_key if row else None
    if key is None:
        return None
    raster = load_safe_raster(storage.get_bytes(key), max_pixels=settings.max_image_pixels)
    if raster.alpha is not None:
        return raster.alpha
    gray = cv2.cvtColor(raster.rgb, cv2.COLOR_RGB2GRAY)
    return cv2.bitwise_not(gray)


def _load_brand_mark(project_id: str, asset_id: str | None, storage, settings):
    import numpy as np

    if not asset_id:
        return None
    with session_scope() as session:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.project_id != project_id or not asset.upload_complete:
            return None
        key = asset.storage_key
    raster = load_safe_raster(storage.get_bytes(key), max_pixels=settings.max_image_pixels)
    if raster.alpha is not None:
        return np.dstack([raster.rgb, raster.alpha])
    return raster.rgb


def _prepare_audio(project_id: str, parameters: dict, storage, workspace: str, preview: bool):
    """Download the user's music to a temp file for the muxer."""
    asset_id = parameters.get("audio_asset_id")
    if not asset_id or preview:
        return None
    with session_scope() as session:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.project_id != project_id or asset.type != "audio":
            return None
        key, mime = asset.storage_key, asset.mime_type
    extension = {"audio/mpeg": "mp3", "audio/wav": "wav", "audio/ogg": "ogg"}.get(mime, "bin")
    path = Path(workspace) / f"audio.{extension}"
    path.write_bytes(storage.get_bytes(key))
    return AudioTrack(
        path=str(path),
        start_seconds=float(parameters.get("audio_start_seconds", 0.0)),
        volume=float(parameters.get("audio_volume", 0.8)),
    )


def _load_stages(project_id: str, parameters: dict) -> list[Stage]:
    """Use the saved timeline, falling back to the mode template."""
    with session_scope() as session:
        rows = list(
            session.execute(
                select(TimelapseStage)
                .where(TimelapseStage.project_id == project_id)
                .order_by(TimelapseStage.order_index)
            ).scalars()
        )
        stages = [
            Stage(
                stage_type=row.stage_type,
                order_index=row.order_index,
                duration=row.duration,
                label=row.label,
                enabled=row.enabled,
                settings=dict(row.settings or {}),
            )
            for row in rows
        ]
    if not stages:
        stages = build_plan(
            str(parameters.get("mode", "sketch_to_colour")),
            total_seconds=float(parameters.get("duration_seconds", 12.0)),
            intermediate_count=_intermediate_count(project_id),
            hold_final_seconds=float(parameters.get("hold_final_seconds", 1.5)),
        )
    return normalise_plan(stages, total_seconds=float(parameters.get("duration_seconds", 12.0)))


def _replace_stages(project_id: str, stages: list[Stage]) -> None:
    from sqlalchemy import delete

    with session_scope() as session:
        session.execute(delete(TimelapseStage).where(TimelapseStage.project_id == project_id))
        for stage in stages:
            session.add(
                TimelapseStage(
                    project_id=project_id,
                    stage_type=stage.stage_type,
                    label=stage.label,
                    order_index=stage.order_index,
                    duration=stage.duration,
                    enabled=stage.enabled,
                    settings=stage.settings,
                )
            )


def _project_name(project_id: str) -> str:
    with session_scope() as session:
        project = session.get(Project, project_id)
        return project.name if project else "Untitled"
