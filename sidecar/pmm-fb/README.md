# PMM + SEP feature-build harness

Compose topology pairing the PMM feature build (SEP frontend, PostgreSQL
exposure, secret provisioning and the native `/sep` proxy,
[Percona-Lab/pmm-submodules#4500] = percona/pmm branch `PMM-15216`, PRs
[percona/pmm#5653] + [percona/pmm#5700]) with the app-restricted SEP side-car:
supervisord running the three APIs + Celery worker/beat + bundled Valkey,
shipping only the `inventory`, `mysql_backups` and `atw` apps. The snippets
management app is not shipped — the builtin snippet library is ingested and
auto-approved at boot (SEP-1627) so atw can execute it, with no periodic or
manual re-sync.

## Which image to pin

The restricted image is built on `main`, not on this branch, and the build emits
a **single** artifact under a suffix-less tag — the `-sidecar` / `-embedded`
variants no longer exist. `main`'s `image` target builds it with
`SEP_RESTRICT_APPS=1`, deriving the shipped app set from `sidecar/settings.yaml`'s
`SEP.APPS`, and publishes it as `percona/percona-sep:<commit-sha>`.

`compose.yaml`'s `sep-sidecar` service therefore pins a main-line commit SHA.
Repin to a newer one by picking a tag published from `main` — the tag list on
Docker Hub is ordered by publish date.

Three properties of the pinned image are load-bearing, and all three are worth
checking on the **artifact** rather than on the commit that built it:

```bash
TAG=<the tag you are pinning>

# It must read secrets from a directory (SECRETS_DIR); expect a non-zero count.
docker run --rm --entrypoint sh docker.io/percona/percona-sep:$TAG \
  -c 'grep -c SECRETS_DIR /home/sep/app/settings-env.sh'

# It must carry the Grafana token mint; expect the helper and a 0700 state dir.
docker run --rm --entrypoint sh docker.io/percona/percona-sep:$TAG \
  -c 'ls /home/sep/app/grafana_service_account.py; ls -ld /home/sep/state'

# It must carry a HEALTHCHECK; expect a Test naming healthcheck.sh.
skopeo inspect --config --raw docker://docker.io/percona/percona-sep:$TAG \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["config"]["Healthcheck"])'
```

`skopeo inspect --config` **without** `--raw` normalizes to OCI, whose
image-config spec has no `Healthcheck` field, so it reports `null` for every SEP
tag including ones that carry the instruction. Only the raw config blob answers
the question. Every side-car recipe builds in docker format for the same reason:
OCI discards the instruction. The 150 s start period keeps the side-car out of
`unhealthy` while PMM provisioning and SEP migrations finish.

The mint is the property a backwards repin loses most quietly. An image without
it satisfies the other two checks, comes up healthy, and mounts the `sep-state`
volume over a directory nothing ever writes to — the only symptom is that
Grafana-backed sign-in and the PMM syncer are inert, with nothing logged.

The pmm-server pin is subject to its own constraint — see
[Caveats](#caveats).

[Percona-Lab/pmm-submodules#4500]: https://github.com/Percona-Lab/pmm-submodules/pull/4500
[percona/pmm#5653]: https://github.com/percona/pmm/pull/5653
[percona/pmm#5700]: https://github.com/percona/pmm/pull/5700

## Bring-up

```bash
git clone -b pmm git@github.com:percona/SEP.git  # already cloned: git checkout pmm && git pull
cd SEP/sidecar/pmm-fb

docker compose up -d                          # pmm-server + sep-sidecar
```

That is the whole prerequisite list. PMM publishes the four secrets SEP reads
from disk and the side-car mints its own Grafana token, so nothing has to be
chosen or seeded in advance. The one thing it assumes is an x86-64 host — see
[Caveats](#caveats) if yours is arm64.

`./bootstrap.sh` is needed **only** for the `mysql` profile, whose three
test-fixture passwords are the only thing the generated `.env` still holds:

```bash
./bootstrap.sh                                # generate .env
docker compose --profile mysql up -d --build  # or: podman compose ...
```

`--profile mysql` adds the `sep-mysql` task-execution target — a MySQL server,
a PMM Client and the employees seed in one container, documented in
[mysql-target.md](mysql-target.md). Omitting it is the supported fast path —
you get the same two services this harness has always had, and auth or UI work
does not pay for a MySQL build:

```bash
docker compose up -d        # pmm-server + sep-sidecar only
```

Note that `docker compose build` obeys the profile too, and reports `No
services to build` rather than an error when you forget it.

First boot takes a couple of minutes. The side-car does not start until
pmm-server reports healthy, which now means "SEP's secrets are published" as
well as "PMM is up" — so expect `sep-sidecar` to sit in `Created` for a while
before it runs. `sep-mysql` initialises a datadir and imports the employees
dataset on its first boot; the import runs for several minutes. Its healthcheck
reports `healthy` as soon as MySQL answers — about a minute in, while the import
is still running — because health here means "the database is up" and nothing
more. Watch `docker compose logs -f sep-mysql` for `Imported the employees seed
dataset` before expecting a backup to have data to copy. Then:

- PMM UI: https://127.0.0.1:8443 (admin / admin) — SEP's pages are part of it
- SEP's API through PMM's nginx: https://127.0.0.1:8443/sep/api/… . The side-car
  serves no UI of its own, so `/sep/` itself answers `{"detail":"Not Found"}`;
  that is the embedded topology working, not a routing fault.
- SEP APIs directly: http://127.0.0.1:9000-9002 (sep / inventory / tasks)

There is no manual token-minting step. The side-car obtains its own Grafana
service-account token at container start when no token reaches it through
`SECRETS_DIR`, so Grafana-backed sign-in, the PMM syncer and task-lifecycle PMM
annotations all work on a first boot. It persists that token in the `sep-state`
volume, so a recreate reuses it rather than minting a second one. A PMM build
that publishes the two Grafana token names into the secrets directory still
outranks the mint, which then does nothing — the side-car resolves each
canonical name from its own file first.

To probe the API by hand, exchange your PMM browser session for a short-lived
SEP bearer rather than looking for a static token — an unauthenticated request
is answered `401`, because nothing injects a bearer server-side any more:

```bash
curl -sk -c /tmp/pmm-cookies -X POST https://127.0.0.1:8443/graph/login \
  -H 'Content-Type: application/json' -d '{"user":"admin","password":"admin"}'
TOKEN=$(curl -sk -b /tmp/pmm-cookies -X POST \
  https://127.0.0.1:8443/sep/api/oauth/session/exchange | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["access_token"])')
curl -sk -H "Authorization: Bearer $TOKEN" https://127.0.0.1:8443/sep/api/apps/
```

## How the pieces connect

- `bootstrap.sh` generates the gitignored `.env`, which now holds only the three
  `sep-mysql` passwords — test-fixture credentials for the `mysql` profile, not
  anything the pair needs, so a bring-up without that profile can skip it
  entirely. `sep-mysql`'s entrypoint refuses to start without them; `compose.yaml`
  deliberately does not, because Compose interpolates every service at parse time
  regardless of the active profile, and a guard there would make the script a
  prerequisite of every bring-up. PMM generates the secrets it publishes itself,
  including the PostgreSQL role's password. Nothing secret is committed;
  re-running keeps an existing `.env` and appends any slot it predates.
- **PMM owns the four secrets SEP reads from disk.** With `PMM_ENABLE_SEP=1` it
  writes four files into the `pmm-sep` volume, which pmm-server mounts at
  `/srv/sep` and the side-car mounts read-only at `/run/secrets/sep`.
  `SECRETS_DIR` points SEP at that directory and it reads each file as the
  canonical setting the filename names:

  | File | Written by | When |
  |---|---|---|
  | `SECRET_KEY` | the entrypoint | seconds after container start |
  | `SEP__DATABASE__PASSWORD`, `INVENTORY__DATABASE__PASSWORD`, `TASKS__DATABASE__PASSWORD` | the entrypoint | seconds after container start |

  None of the four reaches the side-car as environment, so none appears in
  `docker inspect` or in the process environment. `SEP_NOMAD_ENDPOINT` is the
  one credential that does: PMM's stock `admin:admin`, a published default
  rather than a provisioned secret.
- **The Grafana service-account token is the side-car's own.** It is the one SEP
  credential this pin does not get from PMM: the side-car mints it against
  Grafana at start and persists it in the `sep-state` volume. A PMM build that
  publishes the two canonical token names into `SECRETS_DIR` still outranks the
  mint, which is what makes the two owners compatible rather than competing.
- **`sep-sidecar` waits on `condition: service_healthy`** because SEP builds its
  settings once, at process start, and never re-reads them: a side-car released
  before the files exist comes up with those settings permanently unset. Health
  means the current provisioning run has published them.
- **Group 0, not a matching uid.** The side-car runs as uid/gid 1001 and PMM
  writes the files mode 0640 owned by group `root` under a setgid `02770`
  directory. `group_add: ["0"]` is what makes them readable, and it keeps
  working if PMM's runtime uid changes.
- `PMM_ENABLE_SEP=1` alone also makes pmm-server's entrypoint
  expose its embedded PostgreSQL on the compose network and provision the
  low-privilege `sep` role owning the `sep` database (percona/pmm#5700).
  Nothing is published on the host. `PMM_ENABLE_NOMAD=1` + `PMM_PUBLIC_ADDRESS`
  start PMM's embedded Nomad, which SEP task execution dispatches through
  (Nomad silently stays down if the public address is unset).
- All three SEP services **and** the Celery beat store share that single
  `sep` database — the exposure provisions exactly one db/role, and the three
  Alembic tracks use distinct version tables with non-colliding table names.
  The side-car's migration one-shots wait for `pmm-server:5432` and migrate
  on first boot.
- **PMM proxies SEP natively.** pmm-server ships its own `location /sep/`
  block; `PMM_SEP_ADDRESS: sep-sidecar:9000` points it at the side-car, and the
  baked settings profile sets `SEP.ROOT_PATH: /sep` to match. The value is a
  bare `host:port` — a scheme or a trailing path is rejected, and the failure
  surfaces as a routing fault rather than a config error. Nothing is bind-mounted
  over PMM's nginx config.
- **Neither container needs a fixed address.** PMM's SEP location proxies to a
  *variable* under a location-scoped `resolver ... valid=10s`, which defers
  resolution to request time, so the config loads with the side-car absent and
  picks up a new address within the TTL when it is recreated. `sep-mysql`
  (`172.28.9.40`) is still fixed, for an unrelated reason: SEP never updates an
  existing inventory node's address, and the Mydumper path connects to exactly
  that address, so an address that moved across recreates would leave SEP
  pointing at a stale one.
- `BASE_URL` is `http://sep-sidecar:9000/sep` — a compose service name, which
  `../README.md` explicitly tells you not to use because it defines `BASE_URL`
  as the side-car's address *as reachable from Nomad task executors*. That
  prescription is for a real deployment, where PMM Client nodes run their own
  Nomad clients and resolve no compose name. This harness has no PMM Client
  nodes: its only executor is the Nomad client inside `pmm-server`, which shares
  that container's network namespace and resolves `sep-sidecar` through Docker's
  embedded DNS. The consequence is that **the harness does not exercise the
  production artifact-download path**. The `/sep` suffix is required either way
  — download URLs are joined onto `BASE_URL`'s path rather than replacing it.

## Caveats

- **The topology is `linux/amd64` throughout, and every service pins it.** No
  arm64 variant is published for the pmm-server or pmm-client feature builds,
  for the released `percona/pmm-server`, or for the side-car image — whose
  manifest carries no platform index at all. On an Apple Silicon or other arm64
  host the pins are what let the harness come up, under emulation, rather than
  failing the pull. `sep-mysql` is the one that needs its pin most: that service
  is *built*, and `oraclelinux:9` is the one base here that does ship arm64, so
  without the pin an arm64 host builds natively and succeeds — having copied the
  pmm-client stage's amd64 binaries into an image that cannot execute them. Keep
  all three pins across a repin. And treat an emulated run as evidence for
  functional behaviour only: nothing timing-shaped survives QEMU, so backup and
  restore durations, the start periods set here, and any Nomad scheduling race
  are not measurable on such a host.
- **pmm-server's start period is set by this compose file, not by the image.**
  The image ships 25 s with 3 retries at 4 s, so it is marked `unhealthy` around
  37 s while a cold start needs appreciably longer to first pass `readyz` — and
  because `sep-sidecar` depends on `service_healthy`, compose aborts the
  dependent instead of waiting. A build-side gate (PMM-15331) once widened this,
  but the PR was closed unmerged, so `compose.yaml` sets a 300 s start period of
  its own. That is the only healthcheck field it sets — Docker merges the rest
  field by field, so the probe and the other timings keep tracking whatever the
  pinned image ships. Keep that override whenever you repin: dropping it
  reintroduces the aborted bring-up, and switching `sep-sidecar` to
  `service_started` instead trades it for a side-car that exits on a missing
  `SECRET_KEY` when it wins the race.
- **`PMM_ENABLE_SEP` unset takes SEP down**, it does not degrade it. All four
  files are removed on pmm-server's next start, and the side-car exits 1 with a
  single actionable `SECRET_KEY is required` rather than coming up
  half-configured. A side-car already running is unaffected until it restarts,
  because its settings are in memory.
- Both ports 8443 and 9000-9002 bind to loopback only. `sep-mysql` publishes
  nothing; it is reachable only on the compose network.
- Under **rootless podman**, `group_add: ["0"]` maps through the user namespace
  differently and may need `--group-add keep-groups`. If the side-car exits
  reporting it cannot read `/run/secrets/sep`, that is the first thing to check.
- PMM generates the PostgreSQL password on first start and persists it at
  `/srv/.sep_postgres_password`; set `PMM_SEP_POSTGRES_PASSWORD` on pmm-server to
  supply your own instead. Rotating it takes two restarts, in order: pmm-server
  first, so it moves the database password and rewrites the files, then the
  side-car, which reads those files only at process start.
- `sep-mysql` runs `privileged: true` with `cgroup: host` and a read-write
  `/sys/fs/cgroup` mount. A containerised Nomad client needs it — the
  fingerprinter reads cgroups and `raw_exec` places tasks into cgroups the
  client creates — but it is a harness-only concession, not something the
  side-car topology does.
- The settings mount is gone, so editing a rendered YAML file is no longer a
  way to try something out. Partial overrides are environment-variable-only; a
  full override means bind-mounting over `/home/sep/app/settings.yaml`, which
  replaces the baked profile wholesale. Add an ignore rule for any local
  filename you mount that is not already in `.gitignore` — such a file holds the
  deployment's secrets in cleartext.
- **Upgrading a harness bootstrapped before PMM took over the secrets:** the
  supported path is `docker compose down -v`, then `./bootstrap.sh` and a fresh
  `up -d`. Dropping the volumes is what gets the secrets volume initialised with
  PMM's `02770` permissions — Docker only initialises a *new* named volume from
  the image, never an existing one. Then delete the leftover `pmm.conf` and
  `settings.yaml`: both are inert now, both hold secrets in cleartext, and both
  stay gitignored only to keep them out of a commit until you do. The retired
  `SEP_SECRET_KEY`, `SEP_INTERNAL_TOKEN` and `SEP_GRAFANA_TOKEN` slots in an
  existing `.env` are inert too — nothing reads them — but delete them for the
  same reason.
