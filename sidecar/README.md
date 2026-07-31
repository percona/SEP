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
| `entrypoint.sh` | PID 1. Mints the broker credential for the container run, then hands off to `supervisord`. |
| `supervisord.conf` | Runs `valkey`, three `migrate-*` one-shots, the `sep`/`inventory`/`tasks` APIs, and the Celery worker and beat. |
| `healthcheck.sh` | Aggregate probe wired as the image `HEALTHCHECK`. |
| `settings-env.sh` | Sourced by `entrypoint.sh`; expands the per-deployment inputs into the canonical `__`-nested settings variables. |
| `settings.embedded.yaml` | The PMM-embedded settings profile, baked at `/home/sep/app/settings.yaml`. |

The image is built in **docker** manifest format rather than OCI, because OCI
silently discards the `HEALTHCHECK` instruction.

## Runtime configuration

`sidecar/settings.embedded.yaml` is baked into the image at
`/home/sep/app/settings.yaml`, so the container comes up on a working
PMM-embedded profile with no mount. It carries no secrets: the values that vary
per deployment arrive as environment variables, which outrank the file.

**Only one YAML file is ever loaded.** `PreEnvSettings.SETTINGS_FILE` names a
single file and `YamlPrefixConfigSettingsSource` reads only that one — there is
no baked-file-plus-overlay merge. So a **partial** override is
environment-variable-only, and a **full** override is a bind mount at
`/home/sep/app/settings.yaml`, which replaces the baked profile wholesale.

### Deployment inputs

Expanded by `settings-env.sh` into the canonical settings variables:

| Input | Required | Default | Canonical destinations |
|---|---|---|---|
| `SECRET_KEY` | **yes** | — (fail fast) | already canonical (global `Settings`, no prefix) |
| `SEP_DB_PASSWORD` | yes in practice | none | `SEP__DATABASE__PASSWORD`, `INVENTORY__DATABASE__PASSWORD`, `TASKS__DATABASE__PASSWORD`, and the assembled `CELERY__BEAT_DBURI` |
| `SEP_DB_HOST` | no | `pmm-server` | `SEP__DATABASE__HOST`, `INVENTORY__DATABASE__HOST`, `TASKS__DATABASE__HOST`, `CELERY__BEAT_DBURI`, and the three supervisord wait loops |
| `SEP_DB_PORT` | no | `5432` | same as `SEP_DB_HOST` |
| `SEP_GRAFANA_TOKEN` | no | none | `AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN`, `PMM__API_KEY` |
| `SEP_PMM_ENDPOINT` | no | `https://pmm-server:8443` | `PMM__ENDPOINT`, `AUTH__PROVIDER__GRAFANA__ENDPOINT` (with `/graph` appended) |
| `SEP_NOMAD_ENDPOINT` | no | the profile's credential-free URL | `TASKS__NOMAD__ENDPOINT` |

`SEP_GRAFANA_TOKEN` is optional and the container boots without it, but
Grafana-backed sign-in and the PMM syncer stay inert until it is supplied — the
profile ships an empty `service_account_token`, which is a valid `SecretStr`.
The same shape means a *misspelled* token yields a silently inert provider
rather than a startup error.

Already canonical, so they are passed straight through with no expansion:

| Input | Required | Notes |
|---|---|---|
| `SEP_INTERNAL_TOKEN` | no | Derived from `SECRET_KEY` by HMAC when unset. Set it explicitly when PMM's nginx overlay pins a specific value. |
| `BASE_URL` | no* | The side-car's address as reachable from Nomad task executors. *Required when tasks download scripts or artifacts. |

Any canonical variable can also be set directly — an explicit
`TASKS__DATABASE__HOST` outranks the one derived from `SEP_DB_HOST`.

### Not deployment inputs

| Setting | Why it is fixed |
|---|---|
| Database user and name | PMM's `PMM_ENABLE_SEP` provisions exactly the `sep` role and `sep` database. |
| Celery broker and result-backend URLs | Minted per container start — see below. |
| Uvicorn hosts and ports | `healthcheck.sh` probes loopback `:9000`/`:9001`/`:9002`, so they are image contract. |
| TLS certificate and key files | TLS is off inside the container; the probe speaks plain HTTP on loopback and PMM's nginx terminates TLS. |

### The broker credential is generated, not configured

`entrypoint.sh` mints a random password per container start, writes it into a
mode-`0600` Valkey config at `/tmp/valkey.conf`, and exports
`CELERY__BROKER_URL` / `CELERY__RESULT_BACKEND` carrying it. Environment
outranks the baked `settings.yaml`, so the password-less
`redis://127.0.0.1:6379` the profile carries keeps working unchanged; the
exported value wins. It also supersedes a `CELERY__BROKER_URL` passed to
`docker run`, since only the generated credential opens the bundled broker —
this is the one input the deployment-input table above deliberately excludes.
Nothing external supplies the credential and nothing needs to know it.

The password never reaches the command line, of either `valkey-server` or the
`healthcheck.sh` probe (which reads it back from the config file and passes it
through `REDISCLI_AUTH`), because argv is readable by every process in the
container's PID namespace. A container restart mints a fresh one, which is safe:
the broker runs with `save ""` and `appendonly no`, so no broker state crosses
restarts.

## Volumes

Everything shipped into `$APP_HOME` is `root:sep` and read-only to the `sep`
user; the directory itself is `0750 sep:sep`, so `sep` can create new entries
directly under it but cannot write inside any shipped subdirectory. Runtime
artifacts survive a container replacement only if their path is mounted as a
writable volume — at minimum `SEP.artifact_dir`, which defaults to
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
PMM's own Valkey, and Celery then fails to reach its own broker. Give the
side-car its own network namespace — the generated broker URL is not
deployer-overridable, so re-pointing Celery elsewhere is not an option.

Authentication is what keeps that shared-namespace case from also being an
exposure: the loopback bind is no boundary there, so the broker requires the
generated `requirepass` credential described above rather than relying on the
bind alone. The collision remains — a neighbouring process cannot use the
broker, but it can still occupy the port first.
