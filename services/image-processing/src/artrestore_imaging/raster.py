"""The processing-safe raster representation.

``SafeRaster`` is the only image object the pipelines operate on. Building one
re-decodes pixels, bakes EXIF orientation, separates alpha, and captures the
metadata blocks that must survive to export. The original upload bytes are never
mutated: exports are always written to a new object key.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from .errors import CorruptImageError
from .metadata import apply_orientation, describe_metadata, extract_preserved_metadata

_MIME_TO_PIL_FORMAT = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
    "image/tiff": "TIFF",
}


@dataclass(slots=True)
class SafeRaster:
    """Decoded pixels plus everything needed to write a faithful export."""

    rgb: np.ndarray  # uint8, HxWx3
    alpha: np.ndarray | None  # uint8, HxW, or None
    mime_type: str
    source_mode: str
    preserved_metadata: dict = field(default_factory=dict)
    metadata_summary: dict = field(default_factory=dict)

    @property
    def height(self) -> int:
        return int(self.rgb.shape[0])

    @property
    def width(self) -> int:
        return int(self.rgb.shape[1])

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height

    @property
    def has_alpha(self) -> bool:
        return self.alpha is not None

    def copy(self) -> SafeRaster:
        return SafeRaster(
            rgb=self.rgb.copy(),
            alpha=None if self.alpha is None else self.alpha.copy(),
            mime_type=self.mime_type,
            source_mode=self.source_mode,
            preserved_metadata=dict(self.preserved_metadata),
            metadata_summary=dict(self.metadata_summary),
        )

    def with_rgb(self, rgb: np.ndarray) -> SafeRaster:
        """Return a copy carrying new pixel data at identical dimensions."""
        if rgb.shape[:2] != self.rgb.shape[:2]:
            raise CorruptImageError("Processed pixels changed the image dimensions.")
        replacement = self.copy()
        replacement.rgb = np.ascontiguousarray(rgb.astype(np.uint8))
        return replacement

    def to_pil(self) -> Image.Image:
        image = Image.fromarray(self.rgb, mode="RGB")
        if self.alpha is not None:
            image.putalpha(Image.fromarray(self.alpha, mode="L"))
        return image


def load_safe_raster(data: bytes, *, max_pixels: int | None = 50_000_000) -> SafeRaster:
    """Decode upload bytes into a :class:`SafeRaster`.

    Only pixel data and the permitted metadata blocks cross this boundary, so
    embedded payloads in unknown chunks cannot reach downstream processing.
    """
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            mime = Image.MIME.get(opened.format or "", "application/octet-stream")
            source_mode = opened.mode
            oriented = apply_orientation(opened)

            alpha: np.ndarray | None = None
            if oriented.mode in ("RGBA", "LA", "PA") or (
                oriented.mode == "P" and "transparency" in oriented.info
            ):
                rgba = oriented.convert("RGBA")
                array = np.array(rgba, dtype=np.uint8)
                rgb = np.ascontiguousarray(array[:, :, :3])
                alpha = np.ascontiguousarray(array[:, :, 3])
            else:
                rgb = np.array(oriented.convert("RGB"), dtype=np.uint8)
    except Exception as exc:
        raise CorruptImageError(f"The image could not be decoded: {exc}") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit

    return SafeRaster(
        rgb=rgb,
        alpha=alpha,
        mime_type=mime,
        source_mode=source_mode,
        preserved_metadata=extract_preserved_metadata(data),
        metadata_summary=describe_metadata(data),
    )


def encode_raster(
    raster: SafeRaster,
    *,
    mime_type: str | None = None,
    quality: int = 95,
    extra_metadata: dict | None = None,
) -> bytes:
    """Encode a raster back to bytes without changing resolution or colour profile.

    ``extra_metadata`` may add disclosure fields (for example the reconstructed
    process marker) but can never remove preserved provenance blocks.
    """
    target_mime = mime_type or raster.mime_type
    pil_format = _MIME_TO_PIL_FORMAT.get(target_mime)
    if pil_format is None:
        pil_format = "PNG"
        target_mime = "image/png"

    image = raster.to_pil()
    save_kwargs: dict = {}
    preserved = dict(raster.preserved_metadata)

    if preserved.get("icc_profile"):
        save_kwargs["icc_profile"] = preserved["icc_profile"]
    if preserved.get("dpi"):
        save_kwargs["dpi"] = preserved["dpi"]

    if pil_format in ("JPEG", "WEBP", "TIFF") and preserved.get("exif"):
        save_kwargs["exif"] = preserved["exif"]
    if pil_format == "PNG" and preserved.get("exif"):
        save_kwargs["exif"] = preserved["exif"]

    if pil_format == "JPEG":
        if image.mode == "RGBA":
            # JPEG has no alpha channel; composite on white rather than
            # silently discarding the transparency information.
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        save_kwargs.update({"quality": quality, "subsampling": 0, "optimize": True})
    elif pil_format == "WEBP":
        save_kwargs.update({"quality": quality, "method": 4})
    elif pil_format == "PNG":
        save_kwargs.update({"compress_level": 6})
        pnginfo = _png_metadata(preserved, extra_metadata)
        if pnginfo is not None:
            save_kwargs["pnginfo"] = pnginfo
    elif pil_format == "TIFF":
        save_kwargs.update({"compression": "tiff_lzw"})

    buffer = io.BytesIO()
    image.save(buffer, format=pil_format, **save_kwargs)
    return buffer.getvalue()


def _png_metadata(preserved: dict, extra_metadata: dict | None):
    from PIL import PngImagePlugin

    xmp = preserved.get("xmp")
    if not xmp and not extra_metadata:
        return None
    info = PngImagePlugin.PngInfo()
    if xmp:
        text = xmp.decode("utf-8", "ignore") if isinstance(xmp, bytes) else str(xmp)
        info.add_itxt("XML:com.adobe.xmp", text)
    for key, value in (extra_metadata or {}).items():
        info.add_text(str(key), str(value))
    return info


def downscale(raster: SafeRaster, max_dimension: int) -> SafeRaster:
    """Return a preview-sized copy. Never used for final exports."""
    height, width = raster.rgb.shape[:2]
    longest = max(height, width)
    if longest <= max_dimension:
        return raster.copy()
    scale = max_dimension / float(longest)
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    image = raster.to_pil().resize(new_size, Image.LANCZOS)
    array = np.array(image.convert("RGBA" if raster.has_alpha else "RGB"), dtype=np.uint8)
    if raster.has_alpha:
        return SafeRaster(
            rgb=np.ascontiguousarray(array[:, :, :3]),
            alpha=np.ascontiguousarray(array[:, :, 3]),
            mime_type=raster.mime_type,
            source_mode=raster.source_mode,
            preserved_metadata=dict(raster.preserved_metadata),
            metadata_summary=dict(raster.metadata_summary),
        )
    return SafeRaster(
        rgb=np.ascontiguousarray(array),
        alpha=None,
        mime_type=raster.mime_type,
        source_mode=raster.source_mode,
        preserved_metadata=dict(raster.preserved_metadata),
        metadata_summary=dict(raster.metadata_summary),
    )
