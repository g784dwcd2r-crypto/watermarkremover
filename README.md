# ArtRestore Studio

Two tools for work you are entitled to do:

1. **Authorized visible watermark cleanup** — remove a date stamp, an obsolete
   overlay or a burned-in caption from an image you own or have permission to
   edit.
2. **Artwork timelapse reconstruction** — build a process video from your
   finished artwork, labelled as a reconstruction in the file itself.

It is deliberately not a tool for erasing someone's signature, stripping a
licensing watermark, defeating provenance systems, or passing a reconstruction
off as a recording. Those refusals are enforced in the processing pipeline, not
just described in a policy page.

---

## Quick start

The fastest path needs no Postgres, Redis or object storage:

```bash
git clone <this repository> && cd artrestore-studio
cp .env.example .env

make setup          # .venv + node_modules
make dev-api        # API on http://localhost:8000  (SQLite, local files, in-process jobs)
make seed           # optional: demo@example.com / demo-account-passphrase
make dev-web        # web on http://localhost:3000  (in a second terminal)
```

Then open <http://localhost:3000>. API reference: <http://localhost:8000/docs>.

### The full stack

```bash
cp .env.example .env
make up             # Postgres, Redis, MinIO, API, worker, beat and web
```

| Service       | URL                                          |
| ------------- | -------------------------------------------- |
| Web           | <http://localhost:3000>                      |
| API + docs    | <http://localhost:8000> · `/docs` · `/redoc` |
| MinIO console | <http://localhost:9001> (`minioadmin`)       |

### Everyday commands

```bash
make test           # 301 Python tests + 48 web tests
make test-e2e       # 36 Playwright tests (start the API first)
make lint           # ruff, black, prettier, eslint, tsc
make format         # autofix all of the above
make migrate        # alembic upgrade head
make assets         # regenerate the demonstration images
```

---

## What is here

```
apps/
  web/                     Next.js App Router frontend
  api/                     FastAPI service, Alembic migrations
  worker/                  Celery worker: cleanup, analysis, rendering, retention
packages/
  ui/                      Design-system primitives (Radix + Tailwind tokens)
  types/                   Shared API contract types
  config/                  Shared tsconfig, Tailwind theme, ESLint base
services/
  image-processing/        artrestore_imaging: validation, safeguards, inpainting
  timelapse-renderer/      artrestore_timelapse: analysis, frames, encoding
infrastructure/
  docker/                  Dockerfiles for api, worker and web
  deployment/              Production configuration templates
docs/
  architecture/            How it fits together, and why
  api/                     Endpoint reference
  policies/                Authorized use, privacy, terms
assets/demo/               Procedurally generated demonstration images
scripts/                   dev-api, seed, demo-asset generation
```

Full walkthrough: [docs/architecture/overview.md](docs/architecture/overview.md).

---

## The two rules the code enforces

**Nothing is processed without an ownership attestation.** Completing an upload
and queueing a job both require a `ConsentRecord` for the project carrying the
exact statement _"I own this image or have permission to edit it."_, stamped
with the policy version in force. The API refuses both without it.

**Attribution and provenance are out of scope, in two tiers.**

| Tier       | What triggers it                                                                        | What happens                                                                      |
| ---------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| **Block**  | Artist signatures, tiled stock watermarks, OCR-confirmed rights text, credential badges | The run stops. There is no override, on any plan or setting.                      |
| **Review** | Credit-line geometry, a marginal repeating pattern                                      | The run pauses. The user must explicitly attest, and the attestation is recorded. |

The two-tier split exists because some shapes are genuinely ambiguous: a date
stamp in a bottom corner has the same geometry as a copyright line, and a
patterned artwork shares some signal with a tiled watermark. Guessing either way
would be wrong, so the product asks instead of assuming.

Metadata — EXIF, ICC, XMP, IPTC and C2PA — is preserved on every export. There is
no strip-metadata mode.

**Timelapses are never presented as recordings.** Every exported file carries
`Reconstructed process` and the full disclosure statement in its metadata; that
is written on every render and cannot be disabled. The visible end card is on by
default. The exported project JSON lists the exact stages and the random seed,
so results are reproducible and inspectable.

---

## Implemented features

### Cleanup

- Content-based upload validation (JPG, PNG, WebP, TIFF), rejecting polyglots,
  truncated files, decompression bombs and disguised payloads.
- EXIF orientation baked into pixels while rights metadata is kept.
- Mask editor: brush, eraser, rectangle, lasso, polygon; size, hardness and
  opacity; expand, contract, feather and blur; undo/redo; mask visibility;
  zoom/pan with fit-to-screen and 100%; light and dark workspaces; keyboard
  shortcuts; touch and stylus input; autosave into immutable mask versions.
- Assisted selection: overlay detection, GrabCut box refinement, flood-fill from
  a click, and glyph-stroke isolation that masks letterforms rather than their
  bounding box.
- Four processing modes: **Fast Fill** (OpenCV Telea), **Texture Restore**
  (neural backend when deployed, else exemplar synthesis), **Edge-Aware Restore**
  and **Art Mode** (structure/texture decomposition, so contours stay crisp and
  brushwork is synthesised rather than blurred).
- Post-fill correction: feathered compositing, local colour matching, edge
  continuation and seeded grain restoration.
- Before/after slider, split view, difference map, and export that preserves
  resolution, colour profile and metadata.

### Timelapse

- Artwork analysis into background, colour masses, line structure, value bands,
  shadows, highlights, saliency and a coarse-to-fine pyramid.
- Five modes: Sketch to Colour, Paint Reveal, Layer Build, Hand-Drawn Stroke
  Simulation, and Real Intermediate Frames (which uses your own uploaded
  progress images as genuine keyframes, in your order).
- Editable stage timeline: reorder, retime, enable and disable, all from the
  keyboard.
- Reveal ordering derived from the artwork's own structure, with a test that
  fails if any reveal degenerates into a horizontal wipe.
- Controls for duration (5s–5min), 24/30/60 fps, canvas presets, transition
  curves, stroke speed and density, brush range, seed, background colour, final
  hold, zoom/pan, optional cursor, your own brand mark, and your own music with
  trim and volume.
- Outputs: MP4 (H.264), WebM (VP9), GIF preview, poster frame, PNG frame
  archive, and a project JSON with the seed and the exact stage list.

### Platform

- Argon2id passwords, hashed session tokens, HTTP-only cookies, double-submit
  CSRF, per-route rate limiting, password reset and passwordless sign-in.
- Server-side authorization on every project and asset; a foreign project is
  indistinguishable from a missing one.
- Signed upload and download URLs with short expiry; image bytes never pass
  through the application server.
- Jobs with SSE progress, cooperative cancellation, retry and idempotency keys.
- Retention of 1, 7 or 30 days, applied to existing work when changed;
  immediate manual deletion; JSON data export; account deletion that erases
  every object.
- Structured logs that scrub signed URLs and email addresses and truncate
  storage keys.
- WCAG 2.2 AA target, verified with axe-core in both component and browser tests.

---

## Known limitations

These are real and worth reading before relying on any of it.

**Model backends.** No inpainting weights are bundled and none are downloaded.
Out of the box, Texture Restore and Art Mode use the exemplar-based synthesiser,
which is good on repeating texture and weaker on structured content than a
trained model. `ARS_LAMA_MODEL_PATH` and `ARS_DIFFUSION_MODEL_PATH` accept a
locally deployed checkpoint; those adapters are written and wired but are
exercised only by the availability checks in CI, since there is no checkpoint to
test against.

**Detection is heuristic.** Signature detection keys on the continuity of a
handwritten trace, so a signature with very low contrast against a busy surface
can be missed, and a long continuous decorative line in a corner can be flagged.
Stock-watermark detection needs roughly two tiles in frame to see the lattice;
below that it grades the evidence as "review" rather than blocking. OCR-based
keyword matching only runs when `pytesseract` and the tesseract binary are
installed — they are not required, and the geometric heuristics carry the
decision without them.

**Invisible watermarks.** No attempt is made to detect them, and by design no
attempt is made to remove or weaken them. An inpainted region will not carry
whatever invisible mark was there; that is a consequence of reconstructing
pixels, not a feature, and it is why cleanup is limited to marks the user is
authorized to remove.

**Layered file formats.** PSD/ORA layer reading is not implemented. The
timelapse editor reads a separate line-art asset and separate progress images
instead, which covers the same need with formats every tool can export.

**Segmentation.** Assisted selection uses GrabCut and flood fill, which are
solid for overlays on distinguishable backgrounds and weaker on low-contrast
subjects. `ARS_SEGMENTATION_MODEL_PATH` is read by the availability check but no
model-backed path is implemented yet.

**Email.** No SMTP provider is bundled. The shipped sender logs a redacted
record, and outside production it returns the token through the API so the reset
and passwordless flows are fully testable. Implement `EmailSender` to send real
mail.

**Rate limiting** falls back to an in-process counter when Redis is unreachable,
which makes limits per-replica rather than global. The readiness probe reports
this rather than hiding it.

**Scale.** Very large images are analysed at a reduced resolution and the result
is composited back at full size, so extremely fine detail in a large canvas is
reconstructed from a downscaled view. Rendering is CPU-bound and single-pass per
output format.

**The policy pages are templates.** They describe what the software does
accurately, but an operator must add their legal entity, contact routes and
jurisdiction-specific terms before publishing them.

**Layer files.** The timelapse tool reads a separate line-art asset and separate
progress images rather than parsing PSD or ORA layer stacks. That covers the same
need with formats every tool can export, but it does mean an artist with a
layered file has to export the layers they want to use.

---

## Documentation

- [Architecture overview](docs/architecture/overview.md)
- [Image processing pipeline](docs/architecture/image-pipeline.md)
- [Timelapse reconstruction](docs/architecture/timelapse.md)
- [Safeguards](docs/architecture/safeguards.md)
- [Deployment guide](docs/architecture/deployment.md)
- [API reference](docs/api/README.md)
- [Authorized-use policy](docs/policies/authorized-use-policy.md)
- [Privacy policy template](docs/policies/privacy-policy.md)
- [Terms template](docs/policies/terms.md)

## Licence

The application code is provided as-is for the deployment it ships with. All
demonstration imagery is generated by `artrestore_imaging.demo` and carries no
third-party rights.
