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

Every step here is package-manager-specific (``apt`` vs. ``dnf``), which is exactly
what the strategy boundary is for: :meth:`PackagesInstallStrategy.plan_steps`
returns the same step *names* regardless of OS, so the state machine (not yet
built) never branches on OS -- only :meth:`PackagesInstallStrategy.build_step`
does, once, per step.

Two things this module deliberately does not do, left for later design passes:

- **Write or distribute the keyFile.** PMM-15347/questions.md Q7 decided *where*
  keyFiles live (Postgres, encrypted) but not the mechanism that gets one from
  there onto a host's filesystem before ``configure_mongod`` runs. This module's
  ``configure_mongod`` step assumes a keyFile already exists at
  :data:`KEY_FILE_PATH` on the host -- provisioning it there is a prerequisite
  step this strategy does not yet plan.
- **Replica-set-level orchestration.** ``rs.initiate`` runs once per replica set,
  not once per host, and only after every member's mongod is up -- that is the
  state machine coordinating multiple hosts' strategy runs, not something a single
  host's strategy plans for itself.
"""

from app.sep.apps.om_bootstrap.strategy import (
    BootstrapSpec,
    OperatingSystem,
    StepAction,
)

#: Where PackagesInstallStrategy expects a keyFile to already exist on the host.
#: See the module docstring's "does not do" list -- provisioning it there is not
#: yet one of this strategy's own steps.
KEY_FILE_PATH = "/etc/mongod.key"

#: Where the packaged mongod stores its data -- the default the package itself
#: configures, kept explicit here since ``pre_check`` and ``configure_mongod`` both
#: need to agree on it.
DATA_PATH = "/var/lib/mongo"

#: Where the packaged mongod's own config file lives on both supported OSes.
CONFIG_PATH = "/etc/mongod.conf"

#: Minimum free space at :data:`DATA_PATH` ``pre_check`` requires, in bytes.
#: 5 GiB -- generous for phase-1's single-member/three-member replica sets, not a
#: sized-for-production figure.
MIN_DATA_DISK_BYTES = 5 * 1024 * 1024 * 1024


def _psmdb_channel(mongodb_version: str) -> str:
    """Turn ``"8.0"`` into the ``percona-release`` channel name ``"psmdb-80"``.

    :param mongodb_version: A dotted version, e.g. ``"8.0"``.
    :return: The channel name ``percona-release setup`` expects.
    """
    return f"psmdb-{mongodb_version.replace('.', '')}"


class PackagesInstallStrategy:
    """Install Percona Server for MongoDB from Percona's Ubuntu/Rocky packages."""

    def plan_steps(self, spec: BootstrapSpec) -> list[str]:
        """Return this strategy's fixed step names.

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
            "configure_mongod",
            "start_service",
            "verify",
        ]

    def build_step(self, step_name: str, host: str, spec: BootstrapSpec) -> StepAction:
        """Build the action for one of :meth:`plan_steps`' names.

        :param step_name: One of :meth:`plan_steps`' names.
        :param host: The node name being bootstrapped. Unused by every step below
            today -- each builds a command to run *on* ``host``, not one
            referencing it -- kept in the signature because
            :class:`~app.sep.apps.om_bootstrap.strategy.InstallStrategy` requires
            it and a future step (e.g. one resolving this host's advertised
            address for ``configure_mongod``) will need it.
        :param spec: The host's bootstrap spec.
        :return: What the execution layer needs to run this step.
        :raises ValueError: If ``step_name`` is not one of :meth:`plan_steps`'
            names, or ``spec.os`` is not a supported :class:`OperatingSystem`.
        """
        del host  # Unused by every step below today -- see the docstring.
        builders = {
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

        Assumes a keyFile already exists at :data:`KEY_FILE_PATH` -- see the
        module docstring's "does not do" list.
        """
        config = (
            f"net:\n  bindIp: 0.0.0.0\n"
            f"storage:\n  dbPath: {DATA_PATH}\n"
            f"security:\n  authorization: enabled\n  keyFile: {KEY_FILE_PATH}\n"
            f"replication:\n  replSetName: {spec.replica_set_name}\n"
        )
        return StepAction(
            command=["sh", "-c", f"cat > {CONFIG_PATH} <<'MONGOD_CONF'\n{config}MONGOD_CONF\n"],
            timeout_s=30,
        )

    def _start_service(self, spec: BootstrapSpec) -> StepAction:
        """Enable and start the ``mongod`` systemd unit."""
        del spec
        return StepAction(command=["systemctl", "enable", "--now", "mongod"], timeout_s=60)

    def _verify(self, spec: BootstrapSpec) -> StepAction:
        """Confirm ``mongod`` answers before declaring this host done."""
        del spec
        return StepAction(
            command=["sh", "-c", "mongosh --quiet --eval \"db.adminCommand('ping').ok\""],
            timeout_s=60,
        )

    def _require_package_manager(self, os_: OperatingSystem) -> str:
        """Map a supported OS to its package manager, or reject an unsupported one."""
        if os_ is OperatingSystem.UBUNTU:
            return "apt-get"
        if os_ is OperatingSystem.ROCKY:
            return "dnf"
        raise ValueError(f"unsupported OperatingSystem: {os_!r}")
