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

The pin currently reads `pmm-a2db4ac`, which predates this split: it is a
restricted image only because `make image` used to build the side-car on this
branch, and no `-embedded` tag has been published yet. It stays valid, so the
harness keeps working — but the first feature build cut after this branch
merges publishes `<customImageTag>-embedded`, and the pin moves there.

That image carries the side-car `HEALTHCHECK` — every side-car recipe builds
in docker format precisely because OCI discards the instruction — so
`docker compose ps` reports its health normally. The 150 s start period keeps
it out of `unhealthy` while PMM provisioning and SEP migrations finish.

[Percona-Lab/pmm-submodules#4500]: https://github.com/Percona-Lab/pmm-submodules/pull/4500
[percona/pmm#5653]: https://github.com/percona/pmm/pull/5653
[percona/pmm#5700]: https://github.com/percona/pmm/pull/5700

## Bring-up

```bash
./bootstrap.sh              # generate .env, render settings.yaml + pmm.conf
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

## How the pieces connect

- `bootstrap.sh` generates per-deployment secrets into the gitignored `.env`
  (PG password, SEP secret key, SEP internal token) and renders the
  gitignored `settings.yaml` / `pmm.conf` from their committed `*.template`
  siblings. Nothing secret is committed; re-running re-renders and keeps an
  already-minted Grafana token.
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
- Rotating the internal token = edit `.env`, re-run `./bootstrap.sh`, then
  recreate both containers (the nginx map and SEP settings must move
  together).
