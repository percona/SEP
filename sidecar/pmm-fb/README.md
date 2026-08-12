# PMM + SEP feature-build harness

Compose topology pairing the PMM feature build (SEP frontend + PostgreSQL
exposure, [Percona-Lab/pmm-submodules#4500] = percona/pmm branch `PMM-15216`,
PRs [percona/pmm#5653] + [percona/pmm#5700]) with the app-restricted SEP
side-car: supervisord running the three APIs + Celery worker/beat + bundled
Valkey, shipping only the `inventory`, `mysql_backups` and `atw` apps. The
snippets management app is not shipped — the builtin snippet library is
ingested and auto-approved at boot (SEP-1627) so atw can execute it, with no
periodic or manual re-sync.

## Which image to pin

The restricted image is built on `main`, not on this branch. `main`'s
`image-sidecar-embedded` target derives the shipped app set from
`sidecar/settings.embedded.yaml`'s `SEP.APPS` and publishes it under an
`-embedded` suffix, so a feature build tagged `<customImageTag>` produces:

| Tag | Contents |
|---|---|
| `percona/percona-sep:<customImageTag>` | the standalone image |
| `percona/percona-sep:<customImageTag>-sidecar` | the full side-car, every app |
| `percona/percona-sep:<customImageTag>-embedded` | the app-restricted side-car — **pin this one** |

Which of those reach Docker Hub is a per-run decision: each push stage is
gated on the build job's `pushImageDocker` parameter. Only the plain tag has
ever landed there for a feature build, so check the registry rather than
assuming all three exist.

`compose.yaml`'s `sep-sidecar` service must therefore track the `-embedded`
tag. Pinning the plain tag gets the standalone image, which has no supervisord
and will not come up under this harness.

The pin reads `pmm-272c0f0-embedded` — the first `-embedded` build cut from
this branch after the branch-side repoint and strip were retired, published to
both the internal registry and Docker Hub. It carries the baked settings
profile, which is what the side-car reads for everything the `environment:`
block does not supply, and is required now that nothing is mounted over
`/home/sep/app/settings.yaml`.

Repin whenever you need a newer build: cut one from the SEP `Build` job with a
`customImageTag`, and pin that tag with `-embedded` appended. The plain tag
from the same run is the standalone image, not this one.

That image carries the side-car `HEALTHCHECK` — every side-car recipe builds
in docker format precisely because OCI discards the instruction — so
`docker compose ps` reports its health normally. The 150 s start period keeps
it out of `unhealthy` while PMM provisioning and SEP migrations finish.

[Percona-Lab/pmm-submodules#4500]: https://github.com/Percona-Lab/pmm-submodules/pull/4500
[percona/pmm#5653]: https://github.com/percona/pmm/pull/5653
[percona/pmm#5700]: https://github.com/percona/pmm/pull/5700

## Bring-up

```bash
./bootstrap.sh                                # generate .env, render pmm.conf
docker compose --profile mysql up -d --build  # or: podman compose ...
```

`--profile mysql` adds the `sep-mysql` task-execution target described below.
Omitting it is the supported fast path — you get the same two services this
harness has always had, and auth or UI work does not pay for a MySQL build:

```bash
docker compose up -d        # pmm-server + sep-sidecar only
```

Note that `docker compose build` obeys the profile too, and reports `No
services to build` rather than an error when you forget it.

First boot takes a couple of minutes (PMM provisioning + SEP migrations; the
side-car recipe budgets 150 s before its healthcheck would start failing).
`sep-mysql` initialises a datadir and imports the employees dataset on its
first boot; the import runs for several minutes. Its healthcheck reports
`healthy` as soon as MySQL answers — about a minute in, while the import is
still running — because health here means "the database is up" and nothing
more. Watch `docker compose logs -f sep-mysql` for `Imported the employees seed
dataset` before expecting a backup to have data to copy. Then:

- PMM UI: https://127.0.0.1:8443 (admin / admin)
- SEP API through PMM's nginx: https://127.0.0.1:8443/api/apps/
- SEP APIs directly: http://127.0.0.1:9000-9002 (sep / inventory / tasks)

Optionally mint a real Grafana service-account token (enables SEP-side
Grafana auth — login/ambient SSO — and the PMM syncer; the PMM UI's SEP pages
work without it):

```bash
./mint-grafana-token.sh
```

The token lands in `.env` and the script recreates the side-car to apply it —
a restart would reuse the old environment. Task-lifecycle PMM annotations also
start reaching PMM at that point: the baked profile enables them, and they are
inert while no token is set.

## How the pieces connect

- `bootstrap.sh` generates per-deployment secrets into the gitignored `.env`
  (PG password, SEP secret key, SEP internal token, plus an empty slot for the
  Grafana token) and renders the gitignored `pmm.conf` from its committed
  `pmm.conf.template` sibling. Nothing secret is committed; re-running
  re-renders and keeps an existing `.env`, minted Grafana token included.
- SEP's settings come from the profile baked into the image at
  `/home/sep/app/settings.yaml` — nothing is mounted over it. `compose.yaml`'s
  `environment:` block supplies only the per-deployment values (`SECRET_KEY`,
  `SEP_DB_PASSWORD`, `SEP_INTERNAL_TOKEN`, `SEP_GRAFANA_TOKEN`,
  `SEP_NOMAD_ENDPOINT`, `BASE_URL`), which outrank the file; the image supplies
  everything else. `../README.md` documents the full input contract, including
  that a *partial* override is environment-only and a *full* override means
  bind-mounting over the baked profile wholesale.
- `PMM_ENABLE_SEP=1` + the generated password make pmm-server's entrypoint
  expose its embedded PostgreSQL on the compose network and provision the
  low-privilege `sep` role owning the `sep` database (percona/pmm#5700).
  Nothing is published on the host. `PMM_ENABLE_NOMAD=1` +
  `PMM_PUBLIC_ADDRESS` start PMM's embedded Nomad, which SEP task execution
  dispatches through (Nomad silently stays down if the public address is
  unset).
- All three SEP services **and** the Celery beat store share that single
  `sep` database — the exposure provisions exactly one db/role, and the three
  Alembic tracks use distinct version tables with non-colliding table names.
  The side-car's migration one-shots wait for `pmm-server:5432` and migrate
  on first boot.
- The rendered `pmm.conf` overlays the stock nginx config (bind mount) and
  adds the five SEP path prefixes the PMM UI expects (`/api`, `/sep_app`,
  `/stream-logs`, `/execution-events`, `/files`), proxying them to the
  side-car. Interim auth (Option D, mirroring the vite dev proxy on branch
  `PMM-15216`): nginx injects `Authorization: Bearer $SEP_INTERNAL_TOKEN`
  server-side when the client sent no bearer of its own, and SEP
  authenticates it as the non-admin service principal. Admin-only SEP
  endpoints therefore return 403 through this path — swapping the injection
  to the long-lived Grafana SA token needs SEP-side bearer support first
  (SEP-1692; SEP's grafana provider currently validates bearers only as its
  own session JWTs).
- The side-car has a fixed IP (`172.28.9.30`) because nginx resolves proxy
  targets at startup — a name-based upstream would keep pmm-server's nginx
  from booting before SEP is up, and would go stale across SEP restarts.
  `sep-mysql` (`172.28.9.40`) is fixed for an unrelated reason: SEP never
  updates an existing inventory node's address, and the Mydumper path connects
  to exactly that address, so an address that moved across recreates would
  leave SEP pointing at a stale one.

## The MySQL target node (`sep-mysql`)

Behind the `mysql` compose profile. One container carrying Percona Server
8.4.10, a PMM Client, `percona-xtrabackup-84` (8.4.0), `mydumper` (1.0.3) and
the `datacharmer/test_db` employees dataset — the target a MySQL Backups run
executes *on*, not just against. The seed is baked into the image, so first
boot needs no download; it lands as ~125 MB of real data (300,024 employees,
2.8 M salary rows).

**Why one container.** SEP does no scheduling: it pins a Nomad job to the node
name the operator picked and `raw_exec` runs it as a plain process in that
node's namespace. The XtraBackup payload reads the datadir directly and SEP
pins its server config to `localhost`, so the datadir, a MySQL server on
loopback and the backup binaries all have to be reachable from that one
namespace. Sharing a datadir volume between a MySQL container and a separate
PMM Client container is the attractive wrong answer: everything upstream of
exec looks correctly wired, and the run then fails on *connect* rather than on
the datadir. Mydumper is the counterpart — it connects over the network to the
node's service address — so the single combined node covers both paths, since
it can reach itself by its own address.

The PMM Client is what makes the node selectable at both ends: `pmm-admin add
mysql` registers the service, which the syncer pulls into SEP as a backup
source, while the Nomad client `pmm-agent` supervises makes the same host an
executor. Joining Nomad is not enough on its own — SEP's host list filters on
`Status == ready and raw_exec in Drivers and Drivers.raw_exec.Healthy == true`,
so a node can be joined and still never appear. If it does not, check
`nomad node status -verbose` inside `pmm-server` before suspecting SEP.

**Prerequisites.** The service reaches SEP only through the PMM syncer, which
needs a real Grafana token: run `./mint-grafana-token.sh`, then trigger a sync
(`POST /apps/inventory/sync/`). Without it the node registers with PMM and
never appears in SEP.

**Credentials.** `./bootstrap.sh` generates three values into `.env`, like
every other secret here — nothing is committed:

| `.env` slot | MySQL account | Used by |
|---|---|---|
| `SEP_MYSQL_ROOT_PASSWORD` | `root@localhost` | local administration |
| `SEP_MYSQL_BACKUP_PASSWORD` | `sep_backup@%` | both backup payloads, via `/root/.my.cnf` |
| `SEP_MYSQL_PMM_PASSWORD` | `pmm@127.0.0.1` | the PMM exporters |

`sep_backup` is granted from `%` rather than `127.0.0.1` on purpose: XtraBackup
connects to loopback and Mydumper connects from the service address, and one
credential has to satisfy both. The entrypoint writes it into `/root/.my.cnf`
at mode `0600` on every boot.

Rotating any of them in `.env` after first boot does **not** take effect — the
passwords live in the datadir, so the container comes back up authenticating
with the originals. To re-bootstrap, drop **both** `sep-mysql-data` and
`sep-mysql-pmm-config`:

```bash
docker compose --profile mysql down
docker volume rm sep-pmm-fb_sep-mysql-data sep-pmm-fb_sep-mysql-pmm-config
```

Dropping only the datadir rotates the MySQL side while the PMM config volume
keeps the already-registered service, so the entrypoint skips `pmm-admin add`
and the exporters keep authenticating with the old `pmm` password — monitoring
then fails quietly. Removing the config volume re-registers the node, which
mints new PMM ids and therefore orphans any catalogued backup rows; that is the
trade the config volume exists to avoid, and it is the right one to take when
the datadir those backups came from is being discarded anyway.

**Running a backup.** In the MySQL Backups create form:

- **Execution Host** — `sep-mysql`
- **Database Host** — the `sep-mysql` MySQL service
- **MySQL defaults file** — `/root/.my.cnf`

Set the defaults file explicitly. Dispatched `raw_exec` tasks inherit the Nomad
client's identity, which here is root, so `/root/.my.cnf` is readable — but the
XtraBackup payload's *default* path is `f"{os.environ.get('HOME')}/.my.cnf"`,
which becomes the literal string `None/.my.cnf` if `HOME` does not reach the
task, and that surfaces as an *authentication* failure rather than a
missing-file one. Naming the path removes the dependency. A successful run logs
`Connecting to MySQL server host: localhost, user: sep_backup`.

Both fields matter independently. Leaving **Execution Host** on `pmm-server`
while pointing **Database Host** at the `sep-mysql` service is the mistake the
form invites, and it does not fall back: XtraBackup would run in `pmm-server`'s
namespace, where the pinned `localhost` has no MySQL and there is no datadir, so
it fails at connect rather than doing anything useful.

Compression and encryption need nothing extra — `zstd`, `lz4`, `gzip`, `gpg`
and XtraBackup's own `xbcrypt` all arrive as dependencies of the packages above.
Two caveats:

- **`quicklz` will fail.** The form offers it for XtraBackup, but Percona
  XtraBackup 8.4 supports only `lz4` and `zstd` (`xtrabackup --help`), and the
  `qpress` binary that produced `.qp` files is not packaged for this base.
  Nothing in the harness can make that combination work — pick `zstd` or `lz4`.
- **Only local destinations are reachable.** `rsync` is present; S3 and GCS
  uploads need `aws` and `gsutil`, which are not installed and would need
  credentials and a bucket anyway.

None of these paths is exercised by the runs this harness was added for; they
are documented so the next person knows which failures are the image and which
are the code.

**Repinning the feature build.** `${PMM_FB_TAG}` drives both `pmm-server`'s
image and the PMM Client copied into `sep-mysql`, and the two must stay on the
same build: the client ships its own `nomad` binary that has to speak RPC to
the server's, and a released client beside a feature-build server pairs two
Nomad builds nobody has tested. Move the one variable, and rebuild —
`docker compose --profile mysql up -d --build`. Without `--build` you keep the
old client against the new server, and the mismatch is silent: registration
succeeds and only `raw_exec` placement misbehaves.

## Caveats

- `auth_request` is off for the SEP locations (as in the dev proxy), so
  anything that can reach 127.0.0.1:8443 can call the SEP API as the service
  principal. Local testing only.
- Both ports 8443 and 9000-9002 bind to loopback only. `sep-mysql` publishes
  nothing; it is reachable only on the compose network.
- `sep-mysql` runs `privileged: true` with `cgroup: host` and a read-write
  `/sys/fs/cgroup` mount. A containerised Nomad client needs it — the
  fingerprinter reads cgroups and `raw_exec` places tasks into cgroups the
  client creates — but it is a harness-only concession, not something the
  side-car topology does.
- Rotating the internal token = edit `SEP_INTERNAL_TOKEN` in `.env`, re-run
  `./bootstrap.sh` so `pmm.conf` is re-rendered with the new bearer, then
  `docker compose up -d --force-recreate` for **both** containers: the side-car
  because a restart would reuse its old environment, and pmm-server because
  nginx only reads its config at start. The nginx map and the side-car's
  environment have to move together.
- The settings mount is gone, so editing a rendered YAML file is no longer a
  way to try something out. Partial overrides are environment-variable-only; a
  full override means bind-mounting over `/home/sep/app/settings.yaml`, which
  replaces the baked profile wholesale. Only `settings.yaml` is ignored here,
  so add an ignore rule for any other local filename you mount — such a file
  holds the deployment's secrets in cleartext.
- **Upgrading a harness bootstrapped before the mount was dropped:** delete the
  leftover `settings.yaml`. It is inert now but still holds the secret key, PG
  password and internal token in cleartext; it stays ignored only to keep it
  out of a commit until you do. If you had minted a Grafana token, it lives
  only in that file — copy it into `.env` as `SEP_GRAFANA_TOKEN=` before
  deleting, or just re-run `./mint-grafana-token.sh` afterwards; otherwise
  Grafana auth and the PMM syncer silently go inert.
