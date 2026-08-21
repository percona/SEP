# The MySQL target node (`sep-mysql`)

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

**Prerequisites.** The service reaches SEP only through the PMM syncer, so
trigger a sync (`POST https://127.0.0.1:8443/sep/api/apps/inventory/sync/`) once
the node has registered. PMM publishes the Grafana token the syncer needs, so
there is no minting step. Until a sync runs, the node registers with PMM and
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
passwords live in the datadir. Re-bootstrapping means dropping **both**
`sep-mysql-data` and `sep-mysql-pmm-config`:

```bash
docker compose --profile mysql down
docker volume rm sep-pmm-fb_sep-mysql-data sep-pmm-fb_sep-mysql-pmm-config
```

Drop the datadir alone and the exporters keep authenticating with the old `pmm`
password, so monitoring fails quietly. Removing the config volume as well
re-registers the node, which mints new PMM ids and orphans any catalogued
backup rows — the right trade when the datadir those backups came from is being
discarded anyway. The service's third volume, `sep-mysql-nomad`, carries the
Nomad client's own state and holds no credential, so it is left alone.

**Running a backup.** In the MySQL Backups create form:

- **Execution Host** — `sep-mysql`
- **Database Host** — the `sep-mysql` MySQL service
- **MySQL defaults file** — `/root/.my.cnf`
- **XtraBackup defaults file** — `/root/.my.cnf` (XtraBackup runs only)

Set both defaults-file fields explicitly: the general one configures the
payload's own connection to MySQL, while only the XtraBackup one becomes
`--defaults-file` on the `xtrabackup` command line. Left empty they fall back to
`f"{os.environ.get('HOME')}/.my.cnf"`, which becomes the literal `None/.my.cnf`
when `HOME` does not reach the dispatched task — and that surfaces as an
*authentication* failure rather than a missing-file one. A successful run logs
`Connecting to MySQL server host: localhost, user: sep_backup`.

`--defaults-file` is exclusive — it suppresses `/etc/my.cnf` rather than adding
to it — so the entrypoint writes `[mysqld]` and `[xtrabackup]` groups into
`/root/.my.cnf` beside `[client]`, carrying the datadir and socket the binary
would otherwise have taken from the distro config.

Both host fields matter independently. Leaving **Execution Host** on
`pmm-server` while pointing **Database Host** at the `sep-mysql` service is the
mistake the form invites, and it does not fall back: XtraBackup runs in
`pmm-server`'s namespace, where the pinned `localhost` has no MySQL and there is
no datadir, so it fails at connect.

Compression and encryption need nothing extra — `zstd`, `lz4`, `gzip`, `gpg` and
XtraBackup's own `xbcrypt` all arrive with the packages the image installs. Two
caveats:

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
Nomad builds nobody has tested. Move the variable — `compose.yaml` spells its
pinned default out on both lines — and rebuild with `docker compose --profile
mysql up -d --build`. Without `--build` you keep the old client against the new
server, and the mismatch is silent: registration succeeds and only `raw_exec`
placement misbehaves.
