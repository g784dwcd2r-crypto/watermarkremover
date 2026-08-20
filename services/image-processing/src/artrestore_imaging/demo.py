"""Original demonstration assets, generated procedurally.

Every marketing image, seed project and test fixture in this repository is drawn
by this module. Nothing is downloaded, scraped or copied from a third party, so
the demo content carries no third-party rights - which is the only honest way to
ship demonstration material for a product about respecting ownership.
"""

from __future__ import annotations

import io
import math

import cv2
import numpy as np
from PIL import Image

DEMO_SEED = 20260115


def _rng(seed: int | None = None) -> np.random.Generator:
    return np.random.default_rng(DEMO_SEED if seed is None else seed)


def to_png(rgb: np.ndarray, alpha: np.ndarray | None = None) -> bytes:
    image = Image.fromarray(rgb.astype(np.uint8), mode="RGB")
    if alpha is not None:
        image.putalpha(Image.fromarray(alpha.astype(np.uint8), mode="L"))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def to_jpeg(rgb: np.ndarray, quality: int = 92) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(rgb.astype(np.uint8), mode="RGB").save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Backgrounds
# ---------------------------------------------------------------------------


def flat_gradient(width: int = 800, height: int = 600, seed: int | None = None) -> np.ndarray:
    """A smooth studio-sweep gradient: the easy case for Fast Fill."""
    ys = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    xs = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    radial = np.sqrt((xs - 0.5) ** 2 + (ys - 0.35) ** 2)
    base = 1.0 - np.clip(radial * 1.1, 0.0, 1.0)
    image = np.stack(
        [
            (28 + base * 190),
            (36 + base * 176),
            (46 + base * 158),
        ],
        axis=-1,
    )
    noise = _rng(seed).normal(0.0, 1.1, size=image.shape).astype(np.float32)
    return np.clip(image + noise, 0, 255).astype(np.uint8)


def woven_texture(width: int = 800, height: int = 600, seed: int | None = None) -> np.ndarray:
    """A repeating woven-canvas texture: the hard case for diffusion inpainting."""
    rng = _rng(seed)
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    warp = np.sin(xs * math.pi / 6.0) * 10.0
    weft = np.sin(ys * math.pi / 6.0 + 1.2) * 10.0
    weave = 168.0 + warp + weft
    slub = cv2.GaussianBlur(rng.normal(0.0, 9.0, size=(height, width)).astype(np.float32), (0, 0), 2.0)
    fibres = rng.normal(0.0, 3.5, size=(height, width)).astype(np.float32)
    luminance = np.clip(weave + slub + fibres, 0, 255)
    tint = np.stack([luminance * 1.02, luminance * 0.98, luminance * 0.88], axis=-1)
    return np.clip(tint, 0, 255).astype(np.uint8)


def painted_illustration(width: int = 900, height: int = 640, seed: int | None = None) -> np.ndarray:
    """A procedurally painted landscape with visible brushwork and paper grain."""
    rng = _rng(seed)
    canvas = np.zeros((height, width, 3), np.float32)

    # Sky wash
    for y in range(height):
        t = y / float(height)
        canvas[y, :] = np.array([236 - t * 70, 214 - t * 40, 186 + t * 20], np.float32)

    # Distant hills, painted back to front.
    palettes = [
        (150, 168, 148),
        (110, 138, 122),
        (74, 104, 96),
        (48, 74, 72),
    ]
    for index, colour in enumerate(palettes):
        base_y = int(height * (0.45 + index * 0.11))
        points = [(0, height)]
        for x in range(0, width + 40, 40):
            wobble = math.sin(x / (90.0 + index * 30)) * (26 - index * 4)
            points.append((x, int(base_y + wobble + rng.normal(0, 3))))
        points.append((width, height))
        cv2.fillPoly(canvas, [np.array(points, np.int32)], colour)

    # Brush strokes: short directional dabs following the hill contours.
    for _ in range(2600):
        x = int(rng.integers(0, width))
        y = int(rng.integers(int(height * 0.4), height))
        length = int(rng.integers(6, 26))
        angle = rng.normal(0.15, 0.35)
        dx, dy = int(math.cos(angle) * length), int(math.sin(angle) * length)
        shade = rng.normal(0, 13, size=3)
        colour = np.clip(canvas[y, x] + shade, 0, 255)
        cv2.line(canvas, (x, y), (x + dx, y + dy), colour.tolist(), int(rng.integers(1, 4)), cv2.LINE_AA)

    # A warm sun disc and its glow.
    cv2.circle(canvas, (int(width * 0.72), int(height * 0.22)), 46, (255, 226, 172), -1, cv2.LINE_AA)
    canvas = cv2.GaussianBlur(canvas, (0, 0), 0.7)

    # Paper grain.
    grain = cv2.GaussianBlur(rng.normal(0, 5.5, size=(height, width)).astype(np.float32), (0, 0), 0.6)
    canvas += grain[:, :, None]
    return np.clip(canvas, 0, 255).astype(np.uint8)


def line_artwork(width: int = 800, height: int = 800, seed: int | None = None) -> np.ndarray:
    """Thin-line ink artwork on paper: the stress case for edge preservation."""
    rng = _rng(seed)
    canvas = np.full((height, width, 3), 247, np.float32)
    grain = cv2.GaussianBlur(rng.normal(0, 4.0, size=(height, width)).astype(np.float32), (0, 0), 0.8)
    canvas += grain[:, :, None]

    centre = (width // 2, height // 2)
    for ring in range(9):
        radius = 40 + ring * 34
        points = []
        for degree in range(0, 361, 4):
            angle = math.radians(degree)
            wobble = math.sin(angle * (3 + ring)) * (6 + ring)
            points.append(
                (
                    int(centre[0] + math.cos(angle) * (radius + wobble)),
                    int(centre[1] + math.sin(angle) * (radius + wobble) * 0.82),
                )
            )
        cv2.polylines(canvas, [np.array(points, np.int32)], True, (38, 40, 48), 1, cv2.LINE_AA)

    for _ in range(220):
        x1 = int(rng.integers(0, width))
        y1 = int(rng.integers(0, height))
        angle = rng.uniform(0, math.pi)
        length = int(rng.integers(18, 70))
        x2 = int(x1 + math.cos(angle) * length)
        y2 = int(y1 + math.sin(angle) * length)
        cv2.line(canvas, (x1, y1), (x2, y2), (58, 62, 74), 1, cv2.LINE_AA)

    return np.clip(canvas, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Overlays (the things a user is authorized to remove)
# ---------------------------------------------------------------------------


def add_date_stamp(
    rgb: np.ndarray, text: str = "2019-04-11", *, origin: tuple[int, int] | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Burn in a camera-style date stamp. Returns ``(image, ground_truth_mask)``."""
    image = rgb.copy()
    mask = np.zeros(rgb.shape[:2], np.uint8)
    height, width = rgb.shape[:2]
    point = origin or (int(width * 0.06), int(height * 0.92))
    scale = max(0.6, width / 900.0)
    cv2.putText(image, text, point, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 196, 60), 2, cv2.LINE_AA)
    cv2.putText(mask, text, point, cv2.FONT_HERSHEY_SIMPLEX, scale, 255, 4, cv2.LINE_AA)
    return image, mask


def add_small_overlay_badge(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """An obsolete corner badge of the kind a designer removes from their own asset."""
    image = rgb.copy()
    mask = np.zeros(rgb.shape[:2], np.uint8)
    height, width = rgb.shape[:2]
    x, y = int(width * 0.70), int(height * 0.08)
    w, h = int(width * 0.22), int(height * 0.09)
    cv2.rectangle(image, (x, y), (x + w, y + h), (30, 30, 34), -1)
    cv2.putText(
        image, "DRAFT", (x + 12, y + int(h * 0.7)), cv2.FONT_HERSHEY_SIMPLEX,
        max(0.5, width / 1400.0), (250, 250, 250), 2, cv2.LINE_AA,
    )
    cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)
    return image, mask


# ---------------------------------------------------------------------------
# Protected content (the things this product refuses to remove)
# ---------------------------------------------------------------------------


def add_signature(rgb: np.ndarray, seed: int | None = None) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Draw a handwritten-style signature. Returns ``(image, bounding_box)``.

    Used to verify that the safeguard refuses to reconstruct over it.
    """
    rng = _rng(seed)
    image = rgb.copy()
    height, width = rgb.shape[:2]
    x0 = int(width * 0.66)
    y0 = int(height * 0.88)
    span = int(width * 0.26)

    points: list[tuple[int, int]] = []
    phase = rng.uniform(0, math.pi)
    for step in range(span):
        t = step / float(span)
        y = y0 + int(math.sin(t * 9.5 + phase) * 13 - t * 6 + math.sin(t * 27) * 3)
        points.append((x0 + step, y))

    # Artists pick an ink that reads against the surface they are signing.
    patch = cv2.cvtColor(image[max(0, y0 - 25) : y0 + 25, x0 : x0 + span], cv2.COLOR_RGB2GRAY)
    ink = (18, 16, 24) if float(patch.mean()) > 110 else (238, 232, 220)
    for index in range(1, len(points)):
        # Pressure-varying stroke width is the key signature cue.
        thickness = 1 + int(abs(math.sin(index / 11.0)) * 2)
        cv2.line(image, points[index - 1], points[index], ink, thickness, cv2.LINE_AA)

    # A trailing flourish.
    cv2.ellipse(image, (x0 + span - 12, y0 - 4), (16, 9), 18, 200, 470, ink, 1, cv2.LINE_AA)

    box = (x0 - 6, y0 - 22, span + 24, 44)
    return image, box


def add_copyright_line(
    rgb: np.ndarray, text: str = "(c) 2026 Demo Artist - All rights reserved"
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Draw a credit line in the bottom margin. Returns ``(image, bounding_box)``."""
    image = rgb.copy()
    height, width = rgb.shape[:2]
    scale = max(0.4, width / 1800.0)
    (text_w, text_h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    x = int((width - text_w) / 2)
    y = int(height * 0.965)
    cv2.putText(image, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (24, 24, 28), 1, cv2.LINE_AA)
    return image, (x - 4, y - text_h - 4, text_w + 8, text_h + 10)


def add_stock_watermark(
    rgb: np.ndarray, text: str = "SAMPLE PREVIEW", *, opacity: float = 0.42
) -> np.ndarray:
    """Tile a diagonal semi-transparent licensing watermark across the frame."""
    height, width = rgb.shape[:2]
    layer = np.zeros_like(rgb)
    scale = max(0.6, width / 900.0)
    step_x = int(280 * scale)
    step_y = int(120 * scale)
    for row in range(-2, height // step_y + 3):
        for column in range(-2, width // step_x + 3):
            cv2.putText(
                layer,
                text,
                (column * step_x, row * step_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                scale * 0.9,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
    rotation = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), 30.0, 1.0)
    layer = cv2.warpAffine(layer, rotation, (width, height))
    return np.clip(rgb.astype(np.float32) + layer.astype(np.float32) * opacity, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Alpha / edge cases
# ---------------------------------------------------------------------------


def alpha_sticker(size: int = 400, seed: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """An RGBA illustration with real transparency."""
    rng = _rng(seed)
    rgb = np.zeros((size, size, 3), np.uint8)
    alpha = np.zeros((size, size), np.uint8)
    centre = (size // 2, size // 2)
    cv2.circle(rgb, centre, size // 3, (232, 116, 92), -1, cv2.LINE_AA)
    cv2.circle(alpha, centre, size // 3, 255, -1, cv2.LINE_AA)
    for _ in range(160):
        x = int(rng.integers(0, size))
        y = int(rng.integers(0, size))
        cv2.circle(rgb, (x, y), int(rng.integers(2, 7)), (250, 224, 196), -1, cv2.LINE_AA)
    rgb = cv2.bitwise_and(rgb, rgb, mask=alpha)
    return rgb, alpha


def large_photo(width: int = 4000, height: int = 3000) -> np.ndarray:
    """A large image used to exercise the size and memory limits."""
    base = flat_gradient(width // 4, height // 4)
    return cv2.resize(base, (width, height), interpolation=cv2.INTER_CUBIC)


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


def build_demo_bundle() -> dict[str, bytes]:
    """Every demonstration asset, keyed by file name."""
    bundle: dict[str, bytes] = {}

    gradient = flat_gradient()
    stamped, _ = add_date_stamp(gradient)
    bundle["demo-portrait-backdrop-clean.png"] = to_png(gradient)
    bundle["demo-portrait-backdrop-datestamp.png"] = to_png(stamped)

    texture = woven_texture()
    textured_overlay, _ = add_small_overlay_badge(texture)
    bundle["demo-canvas-texture-clean.png"] = to_png(texture)
    bundle["demo-canvas-texture-badge.png"] = to_png(textured_overlay)

    painting = painted_illustration()
    bundle["demo-painted-landscape.png"] = to_png(painting)
    signed, _ = add_signature(painting)
    bundle["demo-painted-landscape-signed.png"] = to_png(signed)
    credited, _ = add_copyright_line(painting)
    bundle["demo-painted-landscape-credit.png"] = to_png(credited)
    bundle["demo-painted-landscape-stock-watermarked.png"] = to_png(add_stock_watermark(painting))

    lines = line_artwork()
    bundle["demo-line-artwork.png"] = to_png(lines)

    sticker_rgb, sticker_alpha = alpha_sticker()
    bundle["demo-alpha-sticker.png"] = to_png(sticker_rgb, sticker_alpha)

    return bundle
