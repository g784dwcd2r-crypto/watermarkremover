# Production deployment

## Before anything else

`GET /readyz` reports configuration problems rather than accepting them
quietly. In production it will tell you if any of these are wrong:

| Setting                | Requirement                                               |
| ---------------------- | --------------------------------------------------------- |
| `ARS_SECRET_KEY`       | 32+ characters, generated, not the shipped default        |
| `ARS_COOKIE_SECURE`    | `true` (HTTPS only)                                       |
| `ARS_DEBUG`            | `false`                                                   |
| `ARS_STORAGE_BACKEND`  | `s3` — the filesystem backend is a development affordance |
| `ARS_S3_ACCESS_KEY_ID` | Not the MinIO default                                     |

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## Topology

```
            TLS terminating proxy / CDN
                   │
        ┌──────────┴───────────┐
        ▼                      ▼
   web (Next.js)          api (FastAPI, N replicas)
                               │
              ┌────────────────┼───────────────┐
              ▼                ▼               ▼
         PostgreSQL         Redis          S3 bucket
                               │
                       ┌───────┴────────┐
                       ▼                ▼
                 worker (N)        beat (exactly 1)
```

**Exactly one beat replica.** It drives the retention sweep; two would delete
twice and race each other.

**Workers are CPU-bound.** Both inpainting and video rendering saturate a core.
Set `CELERY_CONCURRENCY` to roughly the core count and scale replicas rather than
oversubscribing — oversubscription makes every job slower without finishing more
of them.

## Building

```bash
docker build -f infrastructure/docker/Dockerfile.api    --target api -t artrestore-api:$TAG .
docker build -f infrastructure/docker/Dockerfile.worker --build-arg BASE_IMAGE=artrestore-api:$TAG -t artrestore-worker:$TAG .
docker build -f infrastructure/docker/Dockerfile.web \
  --build-arg NEXT_PUBLIC_API_URL=https://api.example.com -t artrestore-web:$TAG .
```

`NEXT_PUBLIC_*` values are inlined at build time, so the API URL is a build
argument. A web image built for one environment cannot be promoted to another.

## Migrations

Run `alembic upgrade head` as a release step _before_ rolling new API replicas.
Both directions are exercised in CI against real PostgreSQL, so a rollback is a
tested path rather than a hope.

## Storage

The bucket must be **private**. Nothing is served publicly; every read goes
through a short-lived signed URL.

- Enable default server-side encryption. The API also sets `AES256` per object.
- Enable versioning if you want protection against accidental deletion, and be
  aware that it changes what "immediate deletion" means for your privacy policy.
- CORS on the bucket must allow `PUT` and `GET` from your web origin, with
  `Content-Type` and `x-amz-server-side-encryption` in the allowed headers.
- A lifecycle rule is a useful backstop under the retention sweep, not a
  replacement for it.

## Cookies and origins

Sessions are `HttpOnly`, `Secure` and `SameSite=Lax`. Serve the web app and the
API on the **same registrable domain** — `app.example.com` and
`api.example.com` — so that cookies are first-party. Different hosts (or
`localhost` vs `127.0.0.1`) make every call cross-site and drop the session.

Set `ARS_CORS_ORIGINS` to the exact web origin. Set `ARS_COOKIE_DOMAIN` to the
shared parent domain.

## Rate limiting

With `ARS_REDIS_URL` reachable, limits are global. Without it, the limiter falls
back to an in-process counter and limits become per-replica. `/readyz` reports
which backend is active; treat the memory backend as a warning in production.

## Observability

- `GET /healthz` — liveness. Cheap, no dependencies.
- `GET /readyz` — readiness. Checks database, storage and limiter, and reports
  configuration warnings.
- Logs are structured JSON on stdout, with signed URLs and email addresses
  scrubbed and storage keys truncated to a prefix. Ship them as-is.
- Error tracking: set `ARS_ERROR_TRACKING_DSN` and install `sentry-sdk`. The
  integration sets `send_default_pii=False`, so customer content is never sent to
  a third party.

## Models

No weights ship in the images. To enable neural inpainting, mount a checkpoint
into the worker and set `ARS_LAMA_MODEL_PATH` (TorchScript or ONNX) or
`ARS_DIFFUSION_MODEL_PATH`. Install the corresponding runtime (`torch`,
`onnxruntime` or `diffusers`) in a derived image. Backends report their own
availability, so a missing checkpoint degrades to the exemplar filler rather than
failing jobs.

Do not commit weights. A pre-commit hook refuses them, because a stray
multi-gigabyte file in git history is effectively permanent.

## Backups and restore

- PostgreSQL: point-in-time recovery. It holds every project, job and consent
  record.
- Object storage: the images themselves. Note that consent records and their
  images have the same retention window by design; restoring one without the
  other leaves attestations pointing at content you no longer hold.
- Redis: no backup needed. It carries in-flight queue state only; a lost queue
  means re-queuing jobs, not lost data.

## Scaling notes

- API replicas are stateless. Scale on request latency.
- Workers scale on queue depth. A 1080p five-minute render is minutes of CPU.
- Previews exist precisely so users are not waiting on full renders to judge
  timing; keep `ARS_PREVIEW_MAX_DIMENSION` modest.
- `ARS_MAX_UPLOAD_BYTES` and `ARS_MAX_IMAGE_PIXELS` bound worst-case memory in
  the worker. Raise them together with worker memory, not on their own.

## Pre-launch checklist

- [ ] `/readyz` returns `ok` with an empty `warnings` array
- [ ] TLS terminates in front of both services; HSTS is set
- [ ] Bucket is private, encrypted, and CORS is scoped to the web origin
- [ ] Beat runs exactly once
- [ ] Retention sweep observed deleting an expired project
- [ ] Account deletion observed clearing the storage prefix
- [ ] Policy pages completed with the operator's legal details
- [ ] Backups tested by restoring, not just by running
