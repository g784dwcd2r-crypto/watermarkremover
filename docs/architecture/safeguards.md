# Safeguards

Two rules are enforced by code rather than by policy text. This document
describes exactly how, including where the detection is weak.

## 1. Nothing is processed without an ownership attestation

`POST /v1/projects/{id}/assets/uploads/complete` requires `ownership_confirmed:
true`, and refuses the completion otherwise. Every job endpoint calls
`require_ownership_confirmation`, which looks for a `ConsentRecord` of type
`ownership_confirmation` scoped to that project.

The record is append-only and stores the statement and the policy version in
force. Duplicating a project copies the attestation forward with a reference to
where it came from, rather than silently assuming it.

## 2. Attribution and provenance are out of scope

### Two severity tiers

| Severity   | Meaning                             | Override                                |
| ---------- | ----------------------------------- | --------------------------------------- |
| **block**  | High-confidence attribution content | None. Not by plan, setting or support.  |
| **review** | Genuinely ambiguous geometry        | An explicit, recorded user attestation. |

The split exists because some shapes cannot be told apart without reading the
content. A date stamp in a bottom corner has the same geometry as a copyright
line. A diagonally patterned artwork shares signal with a tiled watermark.
Refusing both would break legitimate work; allowing both would risk erasing
attribution. So the product asks, and records the answer.

`acknowledged_protected_kinds` only ever clears `review` findings. A test
asserts that acknowledging every kind still fails to clear a signature.

### What each detector keys on

**Signatures — `block`.** Not thresholded ink: a signature is _one long
continuous trace that wanders across its whole bounding box_. The detector
measures the longest edge contour relative to the box diagonal, how much of the
box width it spans, and how many separate contours there are. Handwriting scores
a long trace spanning most of the box in few contours; printed text breaks into
many short glyph outlines; surface texture has no dominant trace. An
axis-alignment guard rejects rectilinear traces, because the outline of a solid
badge would otherwise read as one long continuous mark.

This is what makes it work on painted and photographic surfaces, where ink
darkness tells you nothing.

**Stock watermarks — graded.** A tiled overlay is a _lattice_. The analysis runs
on a high-pass image, so gradients and vignettes contribute nothing, and looks
for strong secondary peaks in the normalised autocorrelation away from the
centre and the axis cross, corroborated by consistently oriented diagonal edge
energy. Either signal alone is ordinary content — a woven canvas is periodic
without being oriented; hatched line art is oriented without being periodic — so
neither alone triggers.

Evidence is graded because how many tiles fit in frame bounds how strong the
signal can be: a clear lattice blocks outright, a marginal one asks.

**Copyright and credit lines — `review` on geometry, `block` on text.** Short
lines of small, evenly-weighted glyphs in a margin or corner are flagged for
review. When an OCR engine is installed, a rights keyword (`©`, "all rights
reserved", an agency name) upgrades the finding to a block. OCR is optional; the
geometric heuristics stand alone without it.

**Agency marks — `block`.** OCR keyword match against known stock providers.

**Provenance — preserved, and blocking when visible.** C2PA/JUMBF manifests, XMP
rights, IPTC blocks and EXIF authorship fields are detected and reported. Metadata
provenance alone does not block a cleanup — preserving it is handled by the
export path — but a mask targeting a _visible_ credential badge does.

### Where the mask meets the finding

`assess_mask` intersects the normalised mask with each detected region and
reports the share of each. A finding matters when it covers a meaningful part of
either the mask or the region. A full-frame watermark blocks any mask at all,
because there is nowhere in the image that is not under it.

## Metadata is never stripped

There is no strip-metadata mode, no flag, and no code path that removes EXIF,
ICC, XMP, IPTC or C2PA blocks. `SafeRaster` carries them from source to export,
and the export route deliberately re-reads the _original_ asset's metadata rather
than the intermediate's, so nothing is lost in a multi-step edit.

## Timelapse disclosure

Covered in [timelapse.md](timelapse.md). In short: the metadata disclosure is
written on every render and cannot be disabled, the visible end card defaults to
on, simulated cursor motion is labelled as simulated in the project file, and
uploaded progress images are used as genuine keyframes rather than being replaced
by generated approximations.

## Known weaknesses

Stated plainly, because a safeguard whose limits are undocumented is a safeguard
you cannot reason about:

- A signature with very low contrast against a busy surface can be missed.
- A long continuous decorative line in a corner can be flagged as one.
- Watermark detection needs roughly two tiles in frame to see the lattice.
  Below that it grades the evidence as `review` rather than blocking.
- Without OCR, a credit line and a date stamp are distinguished only by asking
  the user.
- Invisible watermarks are neither detected nor targeted. Reconstructing pixels
  does not preserve whatever invisible mark was in them; that is a consequence of
  inpainting, and it is why cleanup is scoped to marks the user is authorized to
  remove.

The tests in `services/image-processing/tests/test_detection.py` pin both the
detections and the false-positive guards, so a change that makes the detector
more permissive fails CI.
