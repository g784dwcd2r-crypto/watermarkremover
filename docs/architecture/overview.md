# Architecture overview

## The shape of it

```
        browser
           │  HTTP + cookies (session, CSRF)
           ▼
   ┌───────────────┐        signed PUT / GET
   │  Next.js web  │─────────────────────────────┐
   └───────┬───────┘                             │
           │  JSON + Server-Sent Events          │
           ▼                                     ▼
   ┌───────────────┐   job rows      ┌───────────────────┐
   │  FastAPI api  │◄───────────────►│  object storage   │
   └───┬───────┬───┘                 │  (S3 / MinIO)     │
       │       │  task name          └─────────┬─────────┘
       │       ▼                               │
       │  ┌─────────┐   Celery over Redis      │
       │  │  queue  │──────────────┐           │
       │  └─────────┘              ▼           │
       │                    ┌─────────────┐    │
       ▼                    │   worker    │◄───┘
  ┌──────────┐              └──────┬──────┘
  │ Postgres │◄────────────────────┘
  └──────────┘        reads + writes the same job row
```

Two shared Python packages sit underneath the API and the worker:

- `artrestore_imaging` — validation, metadata, masks, protected-region
  detection, inpainting backends and the cleanup pipeline.
- `artrestore_timelapse` — artwork analysis, stage plans, reveal ordering,
  stroke simulation, frame generation and encoding.

Neither knows anything about HTTP, the database or storage. That is what makes
them testable at speed: 180 of the project's tests run against these packages
directly with no infrastructure at all.

## Decisions worth explaining

### Job rows first, queue messages second

The API writes a `ProcessingJob` row, commits, and only then dispatches by task
name. The worker updates that same row as it goes. This ordering buys three
things:

- **Progress is readable without the broker.** The SSE endpoint polls the row,
  so a client that reconnects mid-job immediately sees current state rather than
  waiting for the next event.
- **Cancellation is a database write.** The worker checks a `cancel_requested`
  flag between stages, so a cancelled job never leaves a half-written result.
- **Idempotency is a unique constraint**, not a race. Repeating a request with
  the same key returns the original job.

Dispatch is by _name_ (`artrestore.cleanup.run`), so the API never imports the
worker's heavy imaging dependencies. Celery ignores `task_always_eager` for
name-based dispatch, so eager mode calls the registered task directly — that is
what lets the whole pipeline run in-process for tests and for the zero-service
development setup.

### Synchronous SQLAlchemy everywhere

FastAPI runs `def` endpoints in a threadpool and Celery tasks are synchronous
anyway. One session style serves both, so the model layer is written once. The
SSE endpoint is the one async path, and it reads job state through
`run_in_threadpool`.

### Portable column types

`GUID` is a native `uuid` on PostgreSQL and `CHAR(36)` elsewhere; JSON columns
become `JSONB` on PostgreSQL. The whole test suite therefore runs on SQLite,
which is what makes the authorization-boundary tests cheap enough to run on
every commit.

### Bytes never touch the application server

Uploads and downloads use signed URLs straight to object storage. The API only
sees the bytes when it has to: validating a completed upload, and inside the
worker. Keys embed the owning user and project (`users/{user}/projects/{project}/…`)
so a deletion request maps to one prefix and a bucket policy can scope access
per tenant.

### The filesystem storage backend is not a stub

It signs URLs with HMAC scoped to key, method and expiry, and serves them
through a gateway route that checks the signature and nothing else — exactly
like S3 presigned URLs. Development therefore exercises the same expiry and
scope semantics as production, and the tests cover path traversal, forged
signatures and expiry.

## Request flows

### Cleanup

```
POST /v1/projects/{id}/assets/uploads      reserve an asset, mint a signed PUT
PUT  <signed url>                          browser → object storage
POST /v1/projects/{id}/assets/uploads/complete
                                           validate bytes, record the attestation
POST /v1/projects/{id}/masks               save an immutable mask version
POST /v1/projects/{id}/masks/{v}/preview   coverage, regions, safeguard findings
POST /v1/projects/{id}/cleanup             queue the job
GET  /v1/projects/{id}/jobs/{id}/events    stream progress until terminal
POST /v1/projects/{id}/exports             write the export
```

The worker loads the source, re-rasterises the mask from stored editor state,
runs the pipeline, and writes the processed image, a preview and a difference
map as new assets. The source object is never overwritten.

### Timelapse

```
POST /v1/projects/{id}/timelapse/analyze   decompose the artwork, seed a timeline
PUT  /v1/projects/{id}/timelapse/stages    save the user's edited timeline
POST /v1/projects/{id}/timelapse/preview   fast low-resolution render
POST /v1/projects/{id}/timelapse/render    final render and exports
```

Frames stream straight into FFmpeg over a pipe, so a five-minute 1080p render
never materialises in memory. Where several formats are requested, the render
runs again per format — the seed makes every pass identical, which is cheaper
than holding gigabytes of RGB.

## Data model

| Table              | Holds                                                                 |
| ------------------ | --------------------------------------------------------------------- |
| `users`            | Account, Argon2id hash, retention preference                          |
| `user_sessions`    | Hashed session tokens; no IP or user agent                            |
| `email_tokens`     | Single-use reset and passwordless links                               |
| `projects`         | Name, type, status, retention window, delete-after                    |
| `assets`           | Storage key, dimensions, and _descriptions_ of metadata — never bytes |
| `masks`            | Immutable versions of the declarative editor document                 |
| `processing_jobs`  | Status, progress, parameters, result, idempotency key                 |
| `timelapse_stages` | The editable timeline                                                 |
| `exports`          | Format, size, settings and the disclosure written into the file       |
| `consent_records`  | Append-only attestations with the policy version in force             |

Ownership is structural: every row that can hold image data hangs off a project,
and every project hangs off a user. There is no path to an asset that does not
pass through a project the caller owns, which is what the authorization tests
assert.

## Further reading

- [Image processing pipeline](image-pipeline.md)
- [Timelapse reconstruction](timelapse.md)
- [Safeguards](safeguards.md)
- [Deployment](deployment.md)
