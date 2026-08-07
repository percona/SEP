# SEP consolidated side-car image

A frontend-less variant of the SEP image, built for embedding SEP inside a PMM
deployment. One `supervisord` runs the five SEP programs plus a bundled Valkey
broker under a single PID 1, so the whole product ships as one container with
one log stream.

Build it with `make image-sidecar` (tag `sep:${RELEASE_VER}-sidecar`). Jenkins
builds and publishes the same tag with a `-sidecar` suffix on both the internal
and Docker Hub registries.

An **app-restricted** variant of the same image is built by
`make image-sidecar-embedded` (tag `sep:${RELEASE_VER}-embedded`). It is the
side-car recipe with the app strip switched on, so it ships only the app
packages the embedded settings profile activates — see [App set](#app-set).
Jenkins builds and publishes it alongside the other two.

## What it contains

| Input | Role |
|---|---|
| `Containerfile.sidecar` | Final stage; mirrors the standalone `Dockerfile` minus the frontend-builder stage, and reuses the shared `sep:builder` wheel image. |
| `entrypoint.sh` | PID 1. Mints the broker credential for the container run, then hands off to `supervisord`. |
| `supervisord.conf` | Runs `valkey`, three `migrate-*` one-shots, the `sep`/`inventory`/`tasks` APIs, and the Celery worker and beat. |
| `healthcheck.sh` | Aggregate probe wired as the image `HEALTHCHECK`. |
| `settings-env.sh` | Sourced by `entrypoint.sh`; expands the per-deployment inputs into the canonical `__`-nested settings variables, leaving unexported any name a file under `SECRETS_DIR` already supplies. |
| `settings.embedded.yaml` | The PMM-embedded settings profile, baked at `/home/sep/app/settings.yaml`. |
| `restrict_apps.py` | Build-step strip for the app-restricted variant; removes every app package the baked profile does not activate. Removed during the build, so it is not present in the final image. |
| `verify_image_apps.py` | Post-build assertion that an image's app set matches its own baked profile. Piped into the image, never copied into it. |
| `verify_image_apps.sh` | Runs `verify_image_apps.py` inside an already-built image; used by both CI and the Jenkins build. |

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

**Mounted secret files reach this image's settings.** SEP reads settings from
files in the directory `SECRETS_DIR` names, and `settings-env.sh` consults the
same directory before it derives anything: a canonical name a file supplies is
left *unexported*, so each settings class resolves it from the file. The
deployment inputs in the table below — the `SEP_*` names — are shell inputs that
script expands, not settings fields, so none of them is mountable under its own
name. What a file supplies is a *canonical destination*:

| Canonical name | Mountable? |
|---|---|
| `SECRET_KEY` | **Yes.** The gate accepts a file and the script never exports the key, so each process reads it from the file. |
| `{SEP,INVENTORY,TASKS}__DATABASE__HOST` / `__PORT` / `__PASSWORD`, `CELERY__BEAT_DBURI`, `AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN`, `PMM__API_KEY`, `PMM__ENDPOINT`, `AUTH__PROVIDER__GRAFANA__ENDPOINT`, `TASKS__NOMAD__ENDPOINT` | **Yes.** A file suppresses the derived export. An explicitly-set variable of the same name still wins over both. |
| `SEP_INTERNAL_TOKEN`, `BASE_URL` | **Yes.** Already canonical and never touched by the script. |
| `CELERY__BROKER_URL`, `CELERY__RESULT_BACKEND` | **No.** `entrypoint.sh` mints the bundled Valkey credential per container run and exports both unconditionally, so a file has nothing to supply. |
| The `SEP_*` deployment inputs | **No.** Shell inputs, not settings fields. |

The resolution order is: an explicitly-set canonical environment variable, then a
file of that name, then the value derived from the raw `SEP_*` input.

**To keep the database password out of the environment, mount
`SEP__DATABASE__PASSWORD` *and* `CELERY__BEAT_DBURI`.** Mounting only the first
still puts the password into the derived beat-store URI, since celery-beat has no
file channel of its own; mounting the second suppresses that derivation.

Constraints on the directory: entries must be regular files directly inside it (a
name in a subdirectory matches no setting). File names are matched
case-insensitively, by both the script and the settings classes — but two files
whose names differ **only** in case are an unsupported mount, and which of them
wins is unspecified. A symlink whose target resolves outside the directory is
ignored by both; the Kubernetes `..data` projected layout resolves normally.
`SECRETS_DIR` has no baked default, so a side-car that mounts nothing is
unaffected.

### App set

The app-restricted image ships exactly the apps `settings.embedded.yaml`'s
`SEP.APPS` activates, plus `framework` and `shared`, which shipped modules reach
and which the activation list never names. Nothing else declares the set: changing
which apps the image ships is an edit to `SEP.APPS` and nothing else, and the
build fails if an activated app has no package to keep.

The strip is driven by the `SEP_RESTRICT_APPS` build argument, which
`image-sidecar-embedded` passes as `1`. Only the exact value `1` strips
anything; the argument defaults to `0`, and any other value leaves the image
unrestricted — which is why the general side-car build, which never passes it,
keeps every app package.

The set is asserted on the **published artifact**, not on a rebuild of it:
`verify_image_apps.sh` pipes `verify_image_apps.py` into an already-built
image's own interpreter, and both CI and the Jenkins build call it before
anything is pushed. The check re-derives the expected set from the profile the
image itself bakes rather than importing `restrict_apps.py` — which the build
deletes from the image anyway, and which could only ever agree with the tree it
produced. The general side-car image is checked in the opposite direction, so a
`SEP_RESTRICT_APPS` value leaking into that build is caught rather than
published. A run prints the set it verified, because a checker that silently
never ran would otherwise be indistinguishable from a passing one.

The strip removes an app's directory and leaves its `version_locations` entry in
`alembic.ini` alone. That combination is load-bearing, not incidental. Each app
owning migrations is an independent Alembic branch recorded in the shared
`alembic_version_sep` table, so a database a full image migrated carries head
rows for apps this image does not ship. `skip_unresolvable_heads` in
`app/sep/migrations/_orphan_heads.py` drops those rows from the heads it hands
Alembic — but only when a configured `version_locations` entry is absent from
disk, which is what a stripped app looks like. With every configured location
present, an unresolvable revision means version skew instead and the upgrade
hard-fails by design. So pruning a stripped app's entry — regenerating the list
in an already-stripped tree, or rewriting the file during the build — turns a
working upgrade into a failed one. `tests/sidecar/test_app_strip.py` asserts the
entries survive for every app the strip removes that owns migrations; an app
owning none needs no entry, and must not carry one.

On this image an `SEP.APPS` override can therefore only **narrow** the baked
set, never widen it. Registry construction imports each activated module, so
activating a package the image does not ship raises `ModuleNotFoundError` and
the container fails to start. The two surfaces that reach `SEP.APPS` are a bind
mount at `/home/sep/app/settings.yaml` (which, per above, replaces the profile
wholesale — so its `SEP.APPS` must be a subset of the baked one) and the
`SEP__APPS` environment variable; the runtime settings-override API cannot,
because `SEP.APPS` is absent from `SETTINGS_OVERRIDE_ALLOWED_KEYS`.

The two unrestricted images (`sep:${RELEASE_VER}` and
`sep:${RELEASE_VER}-sidecar`) ship every app package, so neither constraint
applies to them.

### Deployment inputs

Expanded by `settings-env.sh` into the canonical settings variables. The `SEP_*`
names are shell inputs rather than settings fields, so none of them is mountable
under its own name — the canonical destinations they expand to are.
`SECRET_KEY` is the exception, being already canonical: it is both an input here
and mountable. See the note under
[Runtime configuration](#runtime-configuration):

| Input | Required | Default | Canonical destinations |
|---|---|---|---|
| `SECRET_KEY` | **yes** | — (fail fast) | already canonical (global `Settings`, no prefix) |
| `SEP_DB_PASSWORD` | yes in practice | none | `SEP__DATABASE__PASSWORD`, `INVENTORY__DATABASE__PASSWORD`, `TASKS__DATABASE__PASSWORD`, and the assembled `CELERY__BEAT_DBURI` |
| `SEP_DB_HOST` | no | `pmm-server` | `SEP__DATABASE__HOST`, `INVENTORY__DATABASE__HOST`, `TASKS__DATABASE__HOST`, `CELERY__BEAT_DBURI`, and the three supervisord wait loops |
| `SEP_DB_PORT` | no | `5432` | same as `SEP_DB_HOST` |
| `SEP_GRAFANA_TOKEN` | no | none | `AUTH__PROVIDER__GRAFANA__SERVICE_ACCOUNT_TOKEN`, `PMM__API_KEY` |
| `SEP_PMM_ENDPOINT` | no | `https://pmm-server:8443` | `PMM__ENDPOINT`, `AUTH__PROVIDER__GRAFANA__ENDPOINT` (with `/graph` appended) |
| `SEP_NOMAD_ENDPOINT` | no | the profile's credential-free URL | `TASKS__NOMAD__ENDPOINT` |

`SECRET_KEY` is the only input with no default — the container exits unless one
is supplied, as an environment variable or as a mounted file. It signs the
framework's cookies and CSRF tokens and, when
`SEP_INTERNAL_TOKEN` is unset, derives that token by HMAC, so it has to be both
identical across the supervisord children and stable across restarts. The class
default (`secrets.token_urlsafe(32)`) satisfies neither: it is evaluated per
process, so each child would resolve a different key. Minting one per container
run the way the bundled Valkey credential is minted would fix that and still
break the second half — every session would be signed out and the inter-service
token would rotate on each restart. Generate it once per deployment, persist it
alongside the other deployment secrets, and either pass it in or mount it as a
file named `SECRET_KEY` under `SECRETS_DIR` — the mount keeps it out of every
process's environment.

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
`TASKS__DATABASE__HOST` outranks the one derived from `SEP_DB_HOST`. It overrides
only itself, though: setting `SEP__DATABASE__PASSWORD` by hand leaves the other
two services and `CELERY__BEAT_DBURI` on whatever `SEP_DB_PASSWORD` supplied, so
prefer the deployment input when you want the value to fan out.

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

## What the settings API will and will not change

The image bakes `SETTINGS_OVERRIDE_ALLOWED_KEYS` — the exhaustive list of
settings an administrator may change from the settings UI or API. Everything
this container provisions is refused with `422`: the loopback endpoints and
ports from the table above, the PMM connection and its API key, the whole Nomad
subtree, the snippets source, sessions, security headers, and auth. What stays
tunable is product behaviour: log level, PMM annotations, sync cadence, the
footer and message-level display options, alerting policy and retention,
anonymizer entities, the diagnostics-delivery inputs, and the task
connectivity-check and log-retention settings.

Diagnostics delivery is the one tunable that is off until you configure it. The
image bakes the receiver plan — its resolution steps, its upload spec, and the
*names* of the credentials it needs — but ships those credentials empty, so no
bundle leaves the container until an operator supplies them through
`SEPSettings.DIAGNOSTICS_DELIVERY_INPUTS`. That is a single whole-object PATCH
carrying every declared secret name at once: a per-leaf write such as
`DIAGNOSTICS_DELIVERY_INPUTS__secrets` is refused with `422`, and so is a
payload naming a secret the baked plan does not declare or omitting one it
does. The same key optionally carries an `endpoint` that replaces the baked
receiver; omit it to keep the shipped one. Stored secrets read back as
`**********`, and resubmitting that mask preserves the stored value.

Rows written before the restriction applied — by a standalone deployment whose
database was carried over, or by direct table access — are **inert**: the
snapshot builder skips them, so the baked value is what the services read. They
remain deletable through `DELETE /settings/<class>/<key>`, which is how an
operator clears one; deleting a locked key that has no row answers `409`
instead, since there is nothing to remove.

`SETTINGS_OVERRIDE_ALLOWED_KEYS` is a general capability, not a side-car
special case: any deployment can set it (bare env var, or a `default:` key in
`settings.yaml`) to harden its own override surface. Leaving it unset — the
default everywhere else — keeps every overridable setting overridable. It can
never be changed through the API, only through the deployment's own
configuration. This image carries it as a `default:` key in
`settings.embedded.yaml`, so the bind mount that replaces that file is what
changes the list. A replacement that omits the key does not preserve the
shipped list — it lifts the restriction entirely, since an absent key reads the
same as a deployment that never set one. An environment variable of the same
name still outranks the profile, as it does for every other setting here.

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
