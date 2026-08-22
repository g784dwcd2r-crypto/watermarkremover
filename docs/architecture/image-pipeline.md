# Image processing pipeline

`artrestore_imaging` owns everything the cleanup tool does to pixels. It has no
knowledge of HTTP, the database or storage.

## Order of operations

```
upload bytes
   │
   ├─ validate_image_bytes ......... sniff the format, parse the container,
   │                                 enforce byte and pixel budgets
   ├─ describe_metadata ............ detect EXIF / ICC / XMP / IPTC / C2PA
   ├─ load_safe_raster ............. re-decode pixels, bake EXIF orientation,
   │                                 split alpha, drop unknown chunks
   │
   ├─ rasterize_editor_state ....... rebuild the mask from stored state
   ├─ normalize_mask ............... expand / contract, then feather
   │
   ├─ detect_protected_regions ..... signatures, credit lines, watermarks
   ├─ assess_mask .................. block, pause for attestation, or continue
   │
   ├─ analyse_background ........... texture energy, edge density, colour variance
   ├─ run the selected mode ........ inpaint
   ├─ continue_edges ............... re-assert structure crossing the boundary
   ├─ match_local_colour ........... remove drift against the surrounding ring
   ├─ restore_grain ................ match the local noise floor, seeded
   ├─ feather_composite ............ blend using the soft mask
   │
   └─ encode_raster ................ same resolution, same colour profile,
                                     metadata carried through
```

## Validation

The declared `Content-Type` is never trusted. The format is sniffed from magic
bytes, parsed by Pillow, and cross-checked: if the signature and the container
disagree, the upload is rejected as hostile. Truncated files fail rather than
being half-decoded. `Image.MAX_IMAGE_PIXELS` is set for the duration of the
parse, so a decompression bomb is refused before any buffer is allocated.

`SafeRaster` is the only object the pipelines operate on. Building one re-decodes
pixels and copies across only the permitted metadata blocks, so a payload hidden
in an unknown ancillary chunk cannot reach downstream processing.

## Masks

The editor sends a declarative document — regions plus adjustments — and the
server rasterises it itself. Two reasons:

1. A job is reproducible from stored state alone.
2. A hand-crafted PNG cannot smuggle in a mask the editor never showed the user.

`normalize_mask` returns two arrays: a binary mask that selects the pixels to
reconstruct, and a feathered soft mask used when compositing, so the repair
blends into untouched pixels instead of leaving a seam. Pixels outside the soft
mask are returned bit-for-bit unchanged, and a test asserts exactly that.

A mask covering more than 85% of the image is refused: cleanup is for removing
specific marks, not for regenerating a picture.

## The four modes

| Mode                   | Strategy                                                                                | Best for                             |
| ---------------------- | --------------------------------------------------------------------------------------- | ------------------------------------ |
| **Fast Fill**          | OpenCV Telea fast-marching                                                              | Small marks, smooth backgrounds      |
| **Texture Restore**    | Neural backend when deployed, otherwise exemplar synthesis                              | Patterned and textured areas         |
| **Edge-Aware Restore** | Structure/texture decomposition; structure filled by a blend of Telea and Navier-Stokes | Lines, borders, object contours      |
| **Art Mode**           | Same decomposition, texture at full amplitude, patch radius reduced                     | Brushwork, paper grain, illustration |

The decomposition is what makes the last two work. A bilateral filter splits the
image into a structure layer (flat regions and hard edges) and a texture
residual (grain, weave, brush marks). Structure is filled by diffusion methods,
which are strongest there; texture is synthesised from real neighbouring pixels,
which is what keeps a repaired canvas weave from turning into a soft patch. The
two are then recombined.

`analyse_background` measures the ring around the mask and suggests a mode. The
editor surfaces the suggestion; it never switches on the user's behalf.

## Inpainting backends

Backends register themselves by name and report their own availability.

| Name                        | Notes                                                                 |
| --------------------------- | --------------------------------------------------------------------- |
| `opencv_telea`, `opencv_ns` | Always available                                                      |
| `opencv_blend`              | Structure-weighted blend of the two, avoiding each one's weak case    |
| `patchmatch`                | Exemplar synthesis, isophote-driven, always available                 |
| `lama`                      | Local LaMa checkpoint (TorchScript or ONNX) via `ARS_LAMA_MODEL_PATH` |
| `diffusion`                 | Local diffusion pipeline via `ARS_DIFFUSION_MODEL_PATH`               |

No weights are bundled and nothing is downloaded at build or run time. The
model-backed adapters report themselves unavailable until an operator configures
a checkpoint, and the pipeline falls back to the exemplar filler.

The exemplar filler is a real Criminisi-style implementation: the hole is eroded
patch by patch, always starting where the surrounding structure is strongest
(confidence × isophote term), and each patch is matched against known
neighbourhoods with `matchTemplate` under a mask, rejecting candidates that
overlap the hole. Above a pixel budget it runs on a downscaled copy so worst-case
runtime stays bounded.

## Post-fill correction

A fill can be locally plausible and still read as a patch:

- **Colour drift** — the fill's mean and spread are matched to the surrounding
  ring, with the correction clamped so it removes drift without inventing a
  different colour.
- **Missing grain** — the noise amplitude in the ring is measured and matching
  grain is added, correlated at roughly one pixel so it does not look like
  per-pixel white noise. Seeded, so a project re-renders identically.
- **Interrupted structure** — edges entering the hole from the known side are
  detected and their continuation is re-sharpened, so borders and contours do not
  fade out mid-repair.
- **Alpha** — transparency is inpainted rather than overwritten, so cleaning an
  overlay that sat on transparent pixels does not turn them opaque.

## Export

`encode_raster` writes back at the same resolution with the ICC profile, EXIF,
XMP and DPI carried across. JPEG output composites RGBA onto white rather than
silently discarding transparency. There is no code path that removes metadata.

## Tested cases

`services/image-processing/tests` covers flat backgrounds, repeating texture,
painted illustration, thin-line artwork, small authorized overlays, protected
signature detection, alpha transparency, large images, and invalid or malicious
uploads — including a JPEG signature glued to PNG data, an SVG with a script
tag, a truncated file and a decompression bomb.
