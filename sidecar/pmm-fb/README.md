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

The pin currently reads `pmm-e11e9fd`, which predates this split: it is a
restricted image only because `make image` used to build the side-car on this
branch, and no `-embedded` tag has been published yet. It replaces
`pmm-a2db4ac` because it is the first build carrying the baked settings
profile, without which the side-car has no settings source once the mount is
gone. It has **not** been pushed to Docker Hub yet, so `docker compose up -d`
cannot pull it on another machine until it is. The first feature build cut
after this branch merges publishes `<customImageTag>-embedded`, and the pin
moves there.

That image carries the side-car `HEALTHCHECK` — every side-car recipe builds
in docker format precisely because OCI discards the instruction — so
`docker compose ps` reports its health normally. The 150 s start period keeps
it out of `unhealthy` while PMM provisioning and SEP migrations finish.

[Percona-Lab/pmm-submodules#4500]: https://github.com/Percona-Lab/pmm-submodules/pull/4500
[percona/pmm#5653]: https://github.com/percona/pmm/pull/5653
[percona/pmm#5700]: https://github.com/percona/pmm/pull/5700

## Bring-up

```bash
./bootstrap.sh              # generate .env, render pmm.conf
docker compose up -d        # or: podman compose up -d
```

First boot takes a couple of minutes (PMM provisioning + SEP migrations; the
side-car recipe budgets 150 s before its healthcheck would start failing).
Then:

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

## Caveats

- `auth_request` is off for the SEP locations (as in the dev proxy), so
  anything that can reach 127.0.0.1:8443 can call the SEP API as the service
  principal. Local testing only.
- Both ports 8443 and 9000-9002 bind to loopback only.
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
