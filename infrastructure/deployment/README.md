# Deployment templates

| File                      | What it is                                                    |
| ------------------------- | ------------------------------------------------------------- |
| `docker-compose.prod.yml` | Production-shaped stack: no MinIO, no exposed ports, one beat |
| `Caddyfile`               | Reverse proxy with automatic TLS                              |
| `nginx.conf`              | The same, for nginx                                           |
| `s3-cors.json`            | Bucket CORS allowing signed `PUT`/`GET` from the web origin   |

Both proxy configs disable buffering on the job-progress route. Without that,
Server-Sent Events are held until the job finishes and the progress bar appears
to hang.

Read [../../docs/architecture/deployment.md](../../docs/architecture/deployment.md)
before using any of these.
