# PMM + SEP feature-build harness

Compose topology pairing the PMM feature build (SEP frontend + PostgreSQL
exposure, [Percona-Lab/pmm-submodules#4500] = percona/pmm branch `PMM-15216`,
PRs [percona/pmm#5653] + [percona/pmm#5700]) with the app-restricted SEP
side-car built from this branch (`percona/percona-sep:pmm-c412a7c`:
supervisord running the three APIs + Celery worker/beat + bundled Valkey,
shipping only the `inventory`, `mysql_backups`, `atw` and `snippets` apps).

[Percona-Lab/pmm-submodules#4500]: https://github.com/Percona-Lab/pmm-submodules/pull/4500
[percona/pmm#5653]: https://github.com/percona/pmm/pull/5653
[percona/pmm#5700]: https://github.com/percona/pmm/pull/5700

## Bring-up

```bash
docker compose up -d        # or: podman compose up -d
```

First boot takes a couple of minutes (PMM provisioning + SEP migrations; the
side-car healthcheck has a 150 s grace period). Then:

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

- `PMM_ENABLE_SEP=1` + `PMM_SEP_POSTGRES_PASSWORD` make pmm-server's
  entrypoint expose its embedded PostgreSQL on the compose network and
  provision the low-privilege `sep` role owning the `sep` database
  (percona/pmm#5700). Nothing is published on the host.
- All three SEP services **and** the Celery beat store share that single
  `sep` database — the exposure provisions exactly one db/role, and the three
  Alembic tracks use distinct version tables with non-colliding table names.
  The side-car's migration one-shots wait for `pmm-server:5432` and migrate
  on first boot.
- `pmm.conf` overlays the stock nginx config (bind mount) and adds the five
  SEP path prefixes the PMM UI expects (`/api`, `/sep_app`, `/stream-logs`,
  `/execution-events`, `/files`), proxying them to the side-car. Interim auth
  (Option D, mirroring the vite dev proxy on branch `PMM-15216`): nginx
  injects `Authorization: Bearer $SEP_INTERNAL_TOKEN` server-side when the
  client sent no bearer of its own, and SEP authenticates it as the
  non-admin service principal. Admin-only SEP endpoints therefore return 403
  through this path until the token-exchange provider (Option B) lands.
- The side-car has a fixed IP (`172.28.9.30`) because nginx resolves proxy
  targets at startup — a name-based upstream would keep pmm-server's nginx
  from booting before SEP is up, and would go stale across SEP restarts.

## Caveats

- Every credential here (`sep-fb-pg-pw`, `SECRET_KEY`, `SEP_INTERNAL_TOKEN`)
  is a throwaway feature-build test value, committed on purpose. The internal
  token lives in **both** `settings.yaml` and `pmm.conf` — rotate the two
  together.
- `auth_request` is off for the SEP locations (as in the dev proxy), so
  anything that can reach 127.0.0.1:8443 can call the SEP API as the service
  principal. Local testing only.
- Both ports 8443 and 9000-9002 bind to loopback only.
