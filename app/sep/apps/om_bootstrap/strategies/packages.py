# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Install Percona Server for MongoDB from Percona's official OS packages.

First (and, for now, only) implementation of
:class:`~app.sep.apps.om_bootstrap.strategy.InstallStrategy` -- Ubuntu and Rocky
Linux only, matching PMM-15347's phase-1 OS scope. ``DockerInstallStrategy`` and
``PodmanInstallStrategy`` are future siblings of this module, implementing the same
protocol.

Every per-host step here is package-manager-specific (``apt`` vs. ``dnf``), which
is exactly what the strategy boundary is for: :meth:`PackagesInstallStrategy.plan_steps`
returns the same step *names* regardless of OS, so the stepper never branches on
OS -- only :meth:`PackagesInstallStrategy.build_step` does, once, per step.

The mongod port is never a field anywhere in this module: every step (and
:meth:`build_run_step`'s member list) assumes the package's own unconfigured
default, 27017 -- ``mongod.conf`` here never sets ``net.port``. Making the port
configurable is future scope, alongside TLS and per-member voting
(PMM-15347/plan.md §3 Phase 4).
"""

import json
import shlex

from app.sep.apps.om_bootstrap.strategy import (
    BootstrapSpec,
    OperatingSystem,
    StepAction,
)

#: Where every step here reads or writes the shared keyFile -- planted by the
#: ``distribute_keyfile`` step, ahead of ``configure_mongod``.
KEY_FILE_PATH = "/etc/mongod.key"

#: Where the packaged mongod stores its data -- the default the package itself
#: configures, kept explicit here since ``pre_check`` and ``configure_mongod`` both
#: need to agree on it.
DATA_PATH = "/var/lib/mongo"

#: Where the packaged mongod's own config file lives on both supported OSes.
CONFIG_PATH = "/etc/mongod.conf"

#: Matches the packaged ``mongod.service``'s own ``PIDFile=`` on both supported
#: OSes. The unit is ``Type=forking``, so this has to agree with the systemd unit
#: exactly -- see :meth:`PackagesInstallStrategy._configure_mongod`.
PID_FILE_PATH = "/var/run/mongod.pid"

#: Where mongod's own logs go once it forks. Not the same thing as the unit's
#: ``STDOUT``/``STDERR`` redirects in ``/etc/default/mongod`` -- those capture
#: only the pre-fork parent, which prints nothing once mongod backgrounds
#: itself. ``/var/log/mongodb`` already exists, owned by ``mongod``, from the
#: package's own post-install.
LOG_PATH = "/var/log/mongodb/mongod.log"

#: Minimum free space at :data:`DATA_PATH` ``pre_check`` requires, in bytes.
#: 5 GiB -- generous for phase-1's single-member/three-member replica sets, not a
#: sized-for-production figure.
MIN_DATA_DISK_BYTES = 5 * 1024 * 1024 * 1024

#: The mongod port every step assumes -- see the module docstring.
MONGOD_PORT = 27017

#: Roles PMM's ``mongodb_exporter`` needs, granted to the user
#: ``create_pmm_monitoring_user`` creates -- ``clusterMonitor`` for replication/
#: server-status metrics, ``read`` on ``local`` for oplog metrics. The same
#: minimum PMM's own client-side setup docs grant a manually-created monitoring
#: user.
PMM_MONITORING_USER_ROLES = [
    {"role": "clusterMonitor", "db": "admin"},
    {"role": "read", "db": "local"},
]


def _psmdb_channel(mongodb_version: str) -> str:
    """Turn ``"8.0"`` into the ``percona-release`` channel name ``"psmdb-80"``.

    :param mongodb_version: A dotted version, e.g. ``"8.0"``.
    :return: The channel name ``percona-release setup`` expects.
    """
    return f"psmdb-{mongodb_version.replace('.', '')}"


def _mongosh_eval(js: str) -> StepAction:
    """Build a ``StepAction`` running one ``mongosh --quiet --eval`` command.

    Centralized so every run-level step (which embeds generated JS, some of it
    carrying a secret) quotes the same way, once. ``shlex.quote`` on the whole
    ``--eval`` argument, not string interpolation into a shell command, avoids the
    quoting bugs that show up trying to nest a JS string literal inside a shell
    double-quoted one.

    :param js: The JavaScript to evaluate.
    :return: The step action.
    """
    return StepAction(
        command=["sh", "-c", f"mongosh --quiet --eval {shlex.quote(js)}"],
        timeout_s=60,
    )


class PackagesInstallStrategy:
    """Install Percona Server for MongoDB from Percona's Ubuntu/Rocky packages."""

    def plan_steps(self, spec: BootstrapSpec) -> list[str]:
        """Return this strategy's fixed per-host step names.

        Fixed rather than spec-dependent for phase 1: packages, Ubuntu or Rocky,
        no TLS. A spec asking for TLS would need this to grow a certificate step --
        not built here, since TLS is out of phase-1 scope
        (PMM-15347/plan.md §3 Phase 3).

        :param spec: The host's bootstrap spec.
        :return: Step names, in execution order.
        """
        del spec  # Unused for now -- see the docstring.
        return [
            "pre_check",
            "configure_repository",
            "install_package",
            "distribute_keyfile",
            "configure_mongod",
            "start_service",
            "verify",
        ]

    def build_step(
        self,
        step_name: str,
        host: str,
        spec: BootstrapSpec,
        params: dict[str, str] | None = None,
    ) -> StepAction:
        """Build the action for one of :meth:`plan_steps`' names.

        :param step_name: One of :meth:`plan_steps`' names.
        :param host: The node name being bootstrapped. Unused by every step below
            today -- each builds a command to run *on* ``host``, not one
            referencing it -- kept in the signature because
            :class:`~app.sep.apps.om_bootstrap.strategy.InstallStrategy` requires
            it and a future step (e.g. one resolving this host's advertised
            address for ``configure_mongod``) will need it.
        :param spec: The host's bootstrap spec.
        :param params: ``{"key_file_content": ...}`` for ``distribute_keyfile``;
            ignored by every other step.
        :return: What the execution layer needs to run this step.
        :raises ValueError: If ``step_name`` is not one of :meth:`plan_steps`'
            names, ``spec.os`` is not a supported :class:`OperatingSystem`, or
            ``distribute_keyfile`` is built without ``params["key_file_content"]``.
        """
        del host  # Unused by every step below today -- see the docstring.
        builders = {
            "distribute_keyfile": lambda s: self._distribute_keyfile(s, params),
            "pre_check": self._pre_check,
            "configure_repository": self._configure_repository,
            "install_package": self._install_package,
            "configure_mongod": self._configure_mongod,
            "start_service": self._start_service,
            "verify": self._verify,
        }
        try:
            builder = builders[step_name]
        except KeyError:
            raise ValueError(
                f"{step_name!r} is not a PackagesInstallStrategy step; "
                f"expected one of {list(builders)}"
            ) from None
        return builder(spec)

    def _distribute_keyfile(
        self, spec: BootstrapSpec, params: dict[str, str] | None
    ) -> StepAction:
        """Write the replica set's shared keyFile, owned by ``mongod`` and mode 400.

        Runs after ``install_package`` (so the ``mongod`` system user this chowns
        to already exists) and before ``configure_mongod``, which enables
        ``security.keyFile`` pointing at :data:`KEY_FILE_PATH`. The content comes
        from ``params`` rather than being generated here: PMM-15347/questions.md
        Q7 decided keyFiles are generated once per run and persisted, encrypted,
        in PMM's Postgres -- this strategy only ever plants the one copy the
        stepper hands it, transiently, at dispatch time (see
        :class:`~app.sep.apps.om_bootstrap.strategy.InstallStrategy`'s docstring).

        :param spec: The host's bootstrap spec. Unused -- the keyFile's content is
            entirely determined by ``params``, not by anything in ``spec``.
        :param params: Must contain ``"key_file_content"``.
        :raises ValueError: If ``params`` is missing ``"key_file_content"``.
        """
        del spec
        if not params or "key_file_content" not in params:
            raise ValueError("distribute_keyfile requires params['key_file_content']")
        content = params["key_file_content"]
        return StepAction(
            command=[
                "sh",
                "-c",
                f"install -m 400 -o mongod -g mongod /dev/stdin {KEY_FILE_PATH} "
                f"<<'MONGOD_KEYFILE'\n{content}\nMONGOD_KEYFILE\n",
            ],
            timeout_s=30,
        )

    def _pre_check(self, spec: BootstrapSpec) -> StepAction:
        """Verify OS, package manager, and disk space before touching anything.

        PMM-15347/questions.md Q8: disk space, path, OS version -- Adamo's three
        checks, all read-only, all fast enough to run inline rather than as a
        background job.
        """
        pkg_manager = self._require_package_manager(spec.os)
        return StepAction(
            command=[
                "sh",
                "-c",
                f"command -v {pkg_manager} >/dev/null && "
                f'[ "$(df --output=avail -B1 {DATA_PATH} 2>/dev/null || '
                f'df --output=avail -B1 / | tail -1)" -ge {MIN_DATA_DISK_BYTES} ]',
            ],
            timeout_s=30,
        )

    def _configure_repository(self, spec: BootstrapSpec) -> StepAction:
        """Install ``percona-release`` and enable the requested PSMDB channel."""
        channel = _psmdb_channel(spec.mongodb_version)
        if spec.os is OperatingSystem.UBUNTU:
            command = (
                "curl -fsSL -o /tmp/percona-release.deb "
                "https://repo.percona.com/apt/percona-release_latest.generic_all.deb && "
                "dpkg -i /tmp/percona-release.deb && "
                f"percona-release setup -y {channel}"
            )
        elif spec.os is OperatingSystem.ROCKY:
            command = (
                "dnf install -y "
                "https://repo.percona.com/yum/percona-release-latest.noarch.rpm && "
                f"percona-release setup -y {channel}"
            )
        else:
            raise ValueError(f"unsupported OperatingSystem: {spec.os!r}")
        return StepAction(command=["sh", "-c", command], timeout_s=120)

    def _install_package(self, spec: BootstrapSpec) -> StepAction:
        """Install the ``percona-server-mongodb`` package itself."""
        pkg_manager = self._require_package_manager(spec.os)
        install = "apt-get install -y" if pkg_manager == "apt-get" else "dnf install -y"
        return StepAction(
            command=["sh", "-c", f"{install} percona-server-mongodb"],
            timeout_s=300,
        )

    def _configure_mongod(self, spec: BootstrapSpec) -> StepAction:
        """Write ``mongod.conf`` enabling replication and keyFile auth.

        Assumes a keyFile already exists at :data:`KEY_FILE_PATH` -- planted by
        ``distribute_keyfile``, immediately before this step.

        Also creates :data:`DATA_PATH`, owned by ``mongod``, rather than
        assuming the package's own post-install already did -- confirmed
        against a real failure that it does not: mongod exits immediately on
        first start with ``NonExistentPath: Data directory /var/lib/mongo not
        found``, and ``start_service`` (``systemctl enable --now``) reports
        success regardless, since ``Type=forking`` only waits for the initial
        fork, not for mongod's own startup logic to run. ``verify``, a step
        later, is what actually surfaces the failure -- by then the run has
        already reported ``start_service`` as done.

        Sets ``processManagement.fork``/``pidFilePath`` for the same reason:
        the packaged ``mongod.service`` is ``Type=forking``, so systemd waits for
        mongod itself to daemonize and write :data:`PID_FILE_PATH`. Without
        ``fork: true`` mongod runs in the foreground indefinitely -- confirmed
        against a real run where mongod started and stayed healthy, but systemd's
        default 90s ``TimeoutStartSec`` elapsed waiting for a fork that was never
        coming and killed it, so ``verify`` found nothing listening on 27017 a
        step later, again after ``start_service`` had already reported success.

        ``systemLog.path`` is required alongside ``fork: true`` -- mongod refuses
        to start at all otherwise (``BadValue: --fork has to be used with
        --logpath or --syslog``), confirmed against a real run once the
        fork-without-a-logpath combination above was fixed. The unit's own
        ``STDOUT``/``STDERR`` redirects in ``/etc/default/mongod`` do not stand
        in for this: those capture only the pre-fork parent, which prints
        nothing once mongod backgrounds itself.
        """
        config = (
            f"net:\n  bindIp: 0.0.0.0\n"
            f"storage:\n  dbPath: {DATA_PATH}\n"
            f"security:\n  authorization: enabled\n  keyFile: {KEY_FILE_PATH}\n"
            f"replication:\n  replSetName: {spec.replica_set_name}\n"
            f"processManagement:\n  fork: true\n  pidFilePath: {PID_FILE_PATH}\n"
            f"systemLog:\n  destination: file\n  path: {LOG_PATH}\n  logAppend: true\n"
        )
        command = (
            f"install -d -m 750 -o mongod -g mongod {DATA_PATH} && "
            f"cat > {CONFIG_PATH} <<'MONGOD_CONF'\n{config}MONGOD_CONF\n"
        )
        return StepAction(
            command=["sh", "-c", command],
            timeout_s=30,
        )

    def _start_service(self, spec: BootstrapSpec) -> StepAction:
        """Enable and start the ``mongod`` systemd unit."""
        del spec
        return StepAction(
            command=["systemctl", "enable", "--now", "mongod"], timeout_s=60
        )

    def _verify(self, spec: BootstrapSpec) -> StepAction:
        """Confirm ``mongod`` answers before declaring this host done."""
        del spec
        return StepAction(
            command=[
                "sh",
                "-c",
                "mongosh --quiet --eval \"db.adminCommand('ping').ok\"",
            ],
            timeout_s=60,
        )

    def _require_package_manager(self, os_: OperatingSystem) -> str:
        """Map a supported OS to its package manager, or reject an unsupported one."""
        if os_ is OperatingSystem.UBUNTU:
            return "apt-get"
        if os_ is OperatingSystem.ROCKY:
            return "dnf"
        raise ValueError(f"unsupported OperatingSystem: {os_!r}")

    def plan_run_steps(self, spec: BootstrapSpec) -> list[str]:
        """Return this strategy's fixed run-level step names.

        Both need every member's mongod already running (every host's
        :meth:`plan_steps` succeeded) -- the stepper's job to wait for, not this
        method's.

        :param spec: The run's bootstrap spec.
        :return: Step names, in execution order.
        """
        del spec  # Unused for now -- fixed regardless of spec, like plan_steps.
        return ["rs_initiate", "create_pmm_monitoring_user"]

    def build_run_step(
        self,
        step_name: str,
        hosts: list[str],
        spec: BootstrapSpec,
        params: dict[str, str] | None = None,
    ) -> StepAction:
        """Build the action for one of :meth:`plan_run_steps`' names.

        :param step_name: One of :meth:`plan_run_steps`' names.
        :param hosts: Every host in this run -- see
            :meth:`~app.sep.apps.om_bootstrap.strategy.InstallStrategy.build_run_step`'s
            own docstring for why index 0 is where this action actually runs.
        :param spec: The run's bootstrap spec.
        :param params: ``{"username": ..., "password": ...}`` for
            ``create_pmm_monitoring_user``; ignored by ``rs_initiate``.
        :return: What the execution layer needs to run this step.
        :raises ValueError: If ``step_name`` is not one of :meth:`plan_run_steps`'
            names, or ``create_pmm_monitoring_user`` is built without both
            ``params`` entries.
        """
        if step_name == "rs_initiate":
            return self._rs_initiate(hosts, spec)
        if step_name == "create_pmm_monitoring_user":
            return self._create_pmm_monitoring_user(params)
        raise ValueError(
            f"{step_name!r} is not a PackagesInstallStrategy run step; "
            f"expected one of {self.plan_run_steps(spec)}"
        )

    def _rs_initiate(self, hosts: list[str], spec: BootstrapSpec) -> StepAction:
        """Initiate the replica set from its seed member (``hosts[0]``).

        Equal-priority members, no voting/hidden/delayed configuration -- that
        per-member tuning is phase-4 scope (PMM-15347/plan.md §3), out of reach
        until the Configure step actually collects it.
        """
        members = [
            {"_id": index, "host": f"{host}:{MONGOD_PORT}"}
            for index, host in enumerate(hosts)
        ]
        config = {"_id": spec.replica_set_name, "members": members}
        return _mongosh_eval(f"rs.initiate({json.dumps(config)})")

    def _create_pmm_monitoring_user(self, params: dict[str, str] | None) -> StepAction:
        """Create the MongoDB user PMM's ``mongodb_exporter`` authenticates as.

        Created once, on the seed member -- MongoDB replicates ``admin.system.users``
        to every other member automatically, so this never needs to run per host.
        ``params`` rather than a generated value here for the same reason
        ``distribute_keyfile`` takes one: PMM-15347/questions.md Q7 makes PMM's
        encrypted Postgres this secret's durable home, not this strategy.

        :raises ValueError: If ``params`` is missing ``"username"`` or
            ``"password"``.
        """
        if not params or "username" not in params or "password" not in params:
            raise ValueError(
                "create_pmm_monitoring_user requires params['username'] and "
                "params['password']"
            )
        command = (
            f"db.getSiblingDB('admin').createUser({{"
            f"user: {json.dumps(params['username'])}, "
            f"pwd: {json.dumps(params['password'])}, "
            f"roles: {json.dumps(PMM_MONITORING_USER_ROLES)}"
            f"}})"
        )
        return _mongosh_eval(command)

    def plan_rollback_steps(self, spec: BootstrapSpec) -> list[str]:
        """Return this strategy's fixed per-host rollback step names.

        The reverse of :meth:`plan_steps`, undoing what a host's forward steps
        did rather than mirroring their names one-for-one: there is nothing to
        undo for ``pre_check``/``verify`` (read-only), and ``configure_repository``
        is left alone deliberately -- removing ``percona-release`` would affect
        anything else on the host that depends on it, well outside this run's
        blast radius.

        :param spec: The host's bootstrap spec.
        :return: Step names, in the order rollback applies them.
        """
        del spec
        return [
            "stop_service",
            "remove_config",
            "remove_keyfile",
            "purge_package",
            "remove_data",
        ]

    def build_rollback_step(
        self, step_name: str, host: str, spec: BootstrapSpec
    ) -> StepAction:
        """Build the action for one of :meth:`plan_rollback_steps`' names.

        :param step_name: One of :meth:`plan_rollback_steps`' names.
        :param host: The node name being rolled back. Unused -- same reasoning as
            :meth:`build_step`'s own ``host`` parameter.
        :param spec: The host's bootstrap spec.
        :return: What the execution layer needs to run this step.
        :raises ValueError: If ``step_name`` is not one of
            :meth:`plan_rollback_steps`' names, or ``spec.os`` is not a supported
            :class:`OperatingSystem`.
        """
        del host  # See the docstring.
        builders = {
            "stop_service": self._rollback_stop_service,
            "remove_config": self._rollback_remove_config,
            "remove_keyfile": self._rollback_remove_keyfile,
            "purge_package": self._rollback_purge_package,
            "remove_data": self._rollback_remove_data,
        }
        try:
            builder = builders[step_name]
        except KeyError:
            raise ValueError(
                f"{step_name!r} is not a PackagesInstallStrategy rollback step; "
                f"expected one of {list(builders)}"
            ) from None
        return builder(spec)

    def _rollback_stop_service(self, spec: BootstrapSpec) -> StepAction:
        """Stop and disable ``mongod`` -- tolerant of it never having started."""
        del spec
        return StepAction(
            command=["sh", "-c", "systemctl disable --now mongod || true"],
            timeout_s=60,
        )

    def _rollback_remove_config(self, spec: BootstrapSpec) -> StepAction:
        """Remove the config file ``configure_mongod`` wrote."""
        del spec
        return StepAction(command=["rm", "-f", CONFIG_PATH], timeout_s=30)

    def _rollback_remove_keyfile(self, spec: BootstrapSpec) -> StepAction:
        """Remove the keyFile ``distribute_keyfile`` wrote."""
        del spec
        return StepAction(command=["rm", "-f", KEY_FILE_PATH], timeout_s=30)

    def _rollback_purge_package(self, spec: BootstrapSpec) -> StepAction:
        """Purge the ``percona-server-mongodb`` package ``install_package`` installed.

        Tolerant of the package never having installed (a host that failed
        ``pre_check`` or ``configure_repository`` still runs the full rollback
        list -- see :func:`~app.sep.apps.om_bootstrap.strategy.InstallStrategy`).
        """
        pkg_manager = self._require_package_manager(spec.os)
        remove = (
            "apt-get remove -y --purge percona-server-mongodb"
            if pkg_manager == "apt-get"
            else "dnf remove -y percona-server-mongodb"
        )
        return StepAction(command=["sh", "-c", f"{remove} || true"], timeout_s=120)

    def _rollback_remove_data(self, spec: BootstrapSpec) -> StepAction:
        """Remove the data directory ``mongod`` was configured to use."""
        del spec
        return StepAction(command=["rm", "-rf", DATA_PATH], timeout_s=60)
