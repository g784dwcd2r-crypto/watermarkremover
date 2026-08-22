# Timelapse reconstruction

`artrestore_timelapse` turns a finished artwork into a plausible process video.
It does not recover the real process, and every part of the design assumes it
will be published somewhere that the distinction matters.

## Analysis

`analyse_artwork` decomposes the artwork once and hands the renderers everything
they need:

| Layer               | How it is derived                                         | Used for                    |
| ------------------- | --------------------------------------------------------- | --------------------------- |
| Palette + flat map  | k-means in Lab, ordered by share of the image             | Base colours, colour groups |
| Line structure      | Canny, closed and thinned                                 | Sketch and line-art stages  |
| Edge orientation    | Sobel rotated 90°, smoothed                               | Stroke direction            |
| Detail map          | High-frequency energy                                     | Detail passes               |
| Scale map           | Fine energy over total energy across blur scales          | Forms before specifics      |
| Shadows, highlights | Percentile thresholds on smoothed luminance               | Tonal stages                |
| Saliency            | Spectral residual                                         | Focal detail, camera move   |
| Background/subject  | Colour clusters dominating the frame edges, plus saliency | Layer Build                 |
| Pyramid             | Coarse-to-fine Gaussian levels                            | Paint Reveal                |

Analysis runs at a bounded resolution and is deterministic for a given seed —
including the k-means, which is seeded through `cv2.setRNGSeed` and given a
fixed sample.

## Stages

A plan is a list of stages, each with a type, a duration and its own settings.
The five modes are templates that produce a starting plan; the editor then
reorders, retimes and disables stages, and the renderer works from whatever the
plan says rather than from the mode name.

- **Sketch to Colour** — blank canvas, construction sketch, refined lines, base
  colours, shadows, highlights, texture and finishing details.
- **Paint Reveal** — broad forms, secondary forms, detail pass, colour
  correction, driven by the pyramid.
- **Layer Build** — background, silhouette, colour groups, focal details, polish.
- **Hand-Drawn Stroke Simulation** — three stroke passes at decreasing brush
  scale, then a texture pass.
- **Real Intermediate Frames** — the artist's own uploaded stages, in their
  order, with generated transitions between them. When an upload is missing the
  renderer holds the previous stage rather than substituting a generated
  stand-in.

## Reveal ordering

Each stage has a _target_ — what the canvas looks like when it ends — and a way
of getting there. A reveal map assigns every pixel a value in 0..1: the moment
it switches from the previous image to the target.

Maps are built from the artwork's own structure, never from screen position:

| Kind       | Ordering                                                        |
| ---------- | --------------------------------------------------------------- |
| `organic`  | Scale map, low-frequency noise, and a minority directional term |
| `region`   | Colour group by colour group, largest first, each with a sweep  |
| `tonal`    | Luminance rank, so shadows are blocked in before lights         |
| `detail`   | Detail energy, with salient areas held back                     |
| `radial`   | Distance from the saliency centroid                             |
| `dissolve` | Low-frequency noise alone                                       |

Every map is rank-normalised, so a stage reveals at a steady visual pace whatever
the distribution of the underlying field. A test asserts that no reveal kind
correlates strongly with the x axis — that is what keeps this from degenerating
into a left-to-right wipe.

## Strokes

Stroke seeds are placed where there is something to draw (edge energy, detail,
subject mask, weighted per pass). Each stroke walks along the local edge
orientation, turning toward it rather than snapping to it, with a small
hand-wobble. Width, speed and opacity vary per stroke, and drawing order comes
from scale and saliency with jitter, so it never looks mechanical. Strokes reveal
the target's real colours rather than painting a synthetic ink, and can be
exported as SVG paths.

## Rendering and encoding

Frames stream into FFmpeg over a pipe. Outputs: MP4 (H.264 High, yuv420p, faststart),
WebM (VP9), GIF preview sampled from the same pass, poster frame, PNG frame
archive, and a project JSON.

Output dimensions are forced even, because H.264 under yuv420p requires it.
Optional audio is muxed with `-shortest`, so the music is trimmed to the video
rather than running past it.

## Disclosure

This is the part that is structural rather than cosmetic:

- Every video, GIF, poster and frame archive carries `reconstruction_type`,
  `Reconstructed process` and the full statement in its file metadata. It is
  written on every render and there is no flag that removes it.
- The visible end card is on by default and can be switched off; the metadata
  stays either way.
- The exported project JSON records the seed, the exact stage list with timings,
  and — when the optional cursor is enabled — an explicit note that the cursor
  motion is simulated and is not a recording of real input.
- Rendering records a `timelapse_disclosure` consent entry.

## Verified behaviour

`services/timelapse-renderer/tests` asserts output dimensions, frame rate,
duration within tolerance, valid H.264, audio synchronisation, the presence of
the disclosure metadata, and byte-identical output for the same seed.
