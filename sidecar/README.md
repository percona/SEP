# SEP consolidated side-car image

A frontend-less variant of the SEP image, built for embedding SEP inside a PMM
deployment. One `supervisord` runs the five SEP programs plus a bundled Valkey
broker under a single PID 1, so the whole product ships as one container with
one log stream.

Build it with `make image-sidecar` (tag `sep:${RELEASE_VER}-sidecar`). Jenkins
builds and publishes the same tag with a `-sidecar` suffix on both the internal
and Docker Hub registries.

## What it contains

| Input | Role |
|---|---|
| `Containerfile.sidecar` | Final stage; mirrors the standalone `Dockerfile` minus the frontend-builder stage, and reuses the shared `sep:builder` wheel image. |
| `supervisord.conf` | Runs `valkey`, three `migrate-*` one-shots, the `sep`/`inventory`/`tasks` APIs, and the Celery worker and beat. |
| `healthcheck.sh` | Aggregate probe wired as the image `HEALTHCHECK`. |

The image is built in **docker** manifest format rather than OCI, because OCI
silently discards the `HEALTHCHECK` instruction.

## Required runtime configuration

`settings.yaml` is **not** baked into the image — it must be mounted at
`/home/sep/app/settings.yaml`. The committed `production_docker` block does
**not** satisfy this contract (it points at `sep-db`, `redis:6379` and
`casdoor`, with TLS on), so mounting the repo's `settings.yaml` unchanged
yields a container that never reaches a healthy state.

A conforming profile must provide:

| Setting | Required value | Why |
|---|---|---|
| `<SVC>.DATABASE.HOST` / `.PORT` | `pmm-server` / `5432` | The migration one-shots wait on `nc -z pmm-server 5432`. |
| `<SVC>.DATABASE.NAME` | `sep` / `inventory` / `tasks` | One database per service, owned by a shared least-privilege role. |
| `SEP.UVICORN_PORT` | `9000` | `healthcheck.sh` probes loopback `:9000/health`. |
| `INVENTORY.UVICORN_PORT` | `9001` | Probed by `healthcheck.sh`. |
| `TASKS.UVICORN_PORT` | `9002` | Probed by `healthcheck.sh`. |
| `<SVC>.UVICORN_HOST` | `0.0.0.0` | Ports are published out of the container. |
| `<SVC>.SSL_CERTFILE` / `.SSL_KEYFILE` | `null` | The probe speaks plain HTTP on loopback. |
| `SEP.INVENTORY_ENDPOINT` / `.TASKS_ENDPOINT` | `http://127.0.0.1:9001` / `:9002` | Inter-service calls stay inside the container. |
| `AUTH.PROVIDER` | `grafana` | PMM's Grafana is the identity provider; there is no Casdoor. |
| Celery broker | `redis://127.0.0.1:6379` | Served by the bundled Valkey. |

`env/spikes/SEP-1578/settings-spike.yaml` is a working reference profile.

## Volumes

`$APP_HOME` is `0750 root:sep` with read-only files, so the `sep` user cannot
create directories under it. Any path SEP writes to at runtime must be mounted
as a writable volume — at minimum `SEP.artifact_dir`, which defaults to
`data/health-reports`:

```
-v report-artifacts:/home/sep/app/data/health-reports
```

## Health

`healthcheck.sh` exits 0 only when every non-one-shot program is `RUNNING`, all
three `migrate-*` one-shots have written their `/tmp/migrate-<svc>.ok` sentinel,
the three `/health` endpoints return 200, and the bundled Valkey answers `PING`.
The sentinels matter because a failed `alembic upgrade` ends in `EXITED` — the
same state a successful one reaches — so program state alone cannot distinguish
them.

`HEALTHCHECK` is configured `--interval=15s --timeout=15s --start-period=150s
--retries=5`, so a program going down surfaces as an unhealthy container after
roughly 75-80s.

## Deployment caveat

The bundled Valkey binds `127.0.0.1:6379` inside the container's own network
namespace. If the side-car is ever deployed sharing a namespace with PMM (a
Kubernetes pod, or `--network container:pmm-server`), that port collides with
PMM's own Valkey and Celery may attach to the wrong broker. Give the side-car
its own namespace, or re-point the broker.
