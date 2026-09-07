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

"""Assert PackagesInstallStrategy plans the same steps and builds OS-correct actions."""

import pytest

from app.sep.apps.om_bootstrap.strategies.packages import (
    DATA_PATH,
    KEY_FILE_PATH,
    LOG_PATH,
    PackagesInstallStrategy,
    PID_FILE_PATH,
)
from app.sep.apps.om_bootstrap.strategy import (
    BootstrapSpec,
    InstallMethod,
    InstallStrategy,
    OperatingSystem,
)

STEP_NAMES = [
    "pre_check",
    "configure_repository",
    "install_package",
    "distribute_keyfile",
    "configure_mongod",
    "start_service",
    "verify",
]

RUN_STEP_NAMES = ["rs_initiate", "create_pmm_monitoring_user"]

FINALIZE_STEP_NAMES = ["enable_auth"]

ROLLBACK_STEP_NAMES = [
    "stop_service",
    "remove_config",
    "remove_keyfile",
    "purge_package",
    "remove_data",
]

#: Every per-host step's own required ``params``, so a single parametrized test
#: can build every step without hand-listing which ones need what.
_STEP_PARAMS: dict[str, dict[str, str]] = {
    "distribute_keyfile": {"key_file_content": "test-keyfile-content"},
}


def _spec(os_: OperatingSystem) -> BootstrapSpec:
    return BootstrapSpec(
        install_method=InstallMethod.PACKAGES,
        os=os_,
        mongodb_version="8.0",
        replica_set_name="rs-test",
    )


class TestPackagesInstallStrategyIsAnInstallStrategy:
    """Pin the structural-protocol contract, not just the concrete class."""

    def test_satisfies_the_protocol(self) -> None:
        """A future caller programming against InstallStrategy accepts this class."""
        assert isinstance(PackagesInstallStrategy(), InstallStrategy)


class TestPlanSteps:
    """Assert the step list is fixed and OS-independent for phase 1."""

    @pytest.mark.parametrize("os_", [OperatingSystem.UBUNTU, OperatingSystem.ROCKY])
    def test_returns_the_fixed_step_names_regardless_of_os(
        self, os_: OperatingSystem
    ) -> None:
        """Ubuntu and Rocky get the same step names -- only build_step branches on OS."""
        assert PackagesInstallStrategy().plan_steps(_spec(os_)) == STEP_NAMES


class TestBuildStep:
    """Assert build_step produces the right command per step and per OS."""

    @pytest.mark.parametrize("step_name", STEP_NAMES)
    def test_every_planned_step_builds_without_raising(self, step_name: str) -> None:
        """Every name plan_steps returns is one build_step actually knows."""
        PackagesInstallStrategy().build_step(
            step_name,
            "node00",
            _spec(OperatingSystem.UBUNTU),
            params=_STEP_PARAMS.get(step_name),
        )

    def test_unknown_step_name_raises(self) -> None:
        """A name outside plan_steps' own list is a programming error, not a silent no-op."""
        with pytest.raises(ValueError, match="not a PackagesInstallStrategy step"):
            PackagesInstallStrategy().build_step(
                "rs_initiate", "node00", _spec(OperatingSystem.UBUNTU)
            )

    def test_configure_repository_uses_apt_on_ubuntu(self) -> None:
        """Ubuntu gets percona-release's .deb, installed via dpkg."""
        action = PackagesInstallStrategy().build_step(
            "configure_repository", "node00", _spec(OperatingSystem.UBUNTU)
        )

        command = " ".join(action.command)
        assert "percona-release_latest.generic_all.deb" in command
        assert "dpkg -i" in command
        assert "psmdb-80" in command

    def test_configure_repository_uses_dnf_on_rocky(self) -> None:
        """Rocky gets percona-release's .rpm, installed via dnf."""
        action = PackagesInstallStrategy().build_step(
            "configure_repository", "node00", _spec(OperatingSystem.ROCKY)
        )

        command = " ".join(action.command)
        assert "percona-release-latest.noarch.rpm" in command
        assert "dnf install" in command
        assert "psmdb-80" in command

    def test_install_package_uses_apt_get_on_ubuntu(self) -> None:
        """Ubuntu's package install goes through apt-get, not dnf."""
        action = PackagesInstallStrategy().build_step(
            "install_package", "node00", _spec(OperatingSystem.UBUNTU)
        )

        assert "apt-get install -y percona-server-mongodb" in " ".join(action.command)

    def test_install_package_uses_dnf_on_rocky(self) -> None:
        """Rocky's package install goes through dnf, not apt-get."""
        action = PackagesInstallStrategy().build_step(
            "install_package", "node00", _spec(OperatingSystem.ROCKY)
        )

        assert "dnf install -y percona-server-mongodb" in " ".join(action.command)

    def test_configure_mongod_names_the_spec_replica_set(self) -> None:
        """The written mongod.conf carries this host's actual replica set name."""
        action = PackagesInstallStrategy().build_step(
            "configure_mongod", "node00", _spec(OperatingSystem.UBUNTU)
        )

        assert "replSetName: rs-test" in " ".join(action.command)

    def test_configure_mongod_creates_the_data_directory(self) -> None:
        """Mongod exits immediately on first start if nobody creates this first."""
        action = PackagesInstallStrategy().build_step(
            "configure_mongod", "node00", _spec(OperatingSystem.UBUNTU)
        )

        command = " ".join(action.command)
        assert f"install -d -m 750 -o mongod -g mongod {DATA_PATH}" in command

    def test_configure_mongod_forks(self) -> None:
        """mongod.service is Type=forking.

        Without fork: true it never satisfies systemd's readiness check and
        gets killed once TimeoutStartSec elapses.
        """
        action = PackagesInstallStrategy().build_step(
            "configure_mongod", "node00", _spec(OperatingSystem.UBUNTU)
        )

        command = " ".join(action.command)
        assert "fork: true" in command
        assert f"pidFilePath: {PID_FILE_PATH}" in command

    def test_configure_mongod_sets_a_logpath(self) -> None:
        """Mongod refuses to start at all with fork: true and no logpath.

        ``BadValue: --fork has to be used with --logpath or --syslog`` --
        confirmed against a real run.
        """
        action = PackagesInstallStrategy().build_step(
            "configure_mongod", "node00", _spec(OperatingSystem.UBUNTU)
        )

        command = " ".join(action.command)
        assert f"path: {LOG_PATH}" in command

    def test_configure_mongod_leaves_authorization_off(self) -> None:
        """Authorization has to stay off until the first user already exists.

        MongoDB's localhost exception is unreliable once a replica set already
        has more than one member -- confirmed against a real run where every
        createUser attempt failed identically once the first one did.
        enable_auth (a finalize step) turns authorization on afterward, once
        create_pmm_monitoring_user has actually succeeded.
        """
        action = PackagesInstallStrategy().build_step(
            "configure_mongod", "node00", _spec(OperatingSystem.UBUNTU)
        )

        command = " ".join(action.command)
        assert "authorization" not in command
        assert "keyFile" not in command

    def test_distribute_keyfile_requires_params(self) -> None:
        """Without a keyFile to plant, this is a programming error, not a blank file."""
        with pytest.raises(ValueError, match="key_file_content"):
            PackagesInstallStrategy().build_step(
                "distribute_keyfile", "node00", _spec(OperatingSystem.UBUNTU)
            )

    def test_distribute_keyfile_writes_the_given_content(self) -> None:
        """The dispatched command embeds exactly the content the caller supplied."""
        action = PackagesInstallStrategy().build_step(
            "distribute_keyfile",
            "node00",
            _spec(OperatingSystem.UBUNTU),
            params={"key_file_content": "super-secret-keyfile-bytes"},
        )

        command = " ".join(action.command)
        assert "super-secret-keyfile-bytes" in command
        assert "-m 400" in command


class TestPlanRunSteps:
    """Assert the run-level step list is fixed and OS-independent."""

    def test_returns_the_fixed_run_step_names(self) -> None:
        """rs_initiate and create_pmm_monitoring_user, in that order."""
        spec = _spec(OperatingSystem.UBUNTU)
        assert PackagesInstallStrategy().plan_run_steps(spec) == RUN_STEP_NAMES


class TestBuildRunStep:
    """Assert build_run_step targets the seed host and rejects unknown names."""

    def test_unknown_run_step_name_raises(self) -> None:
        """A per-host step name is not a run step -- caught the same way as the reverse."""
        with pytest.raises(ValueError, match="not a PackagesInstallStrategy run step"):
            PackagesInstallStrategy().build_run_step(
                "pre_check", ["node00"], _spec(OperatingSystem.UBUNTU)
            )

    def test_rs_initiate_names_every_host_as_a_member(self) -> None:
        """Every host in the run becomes an rs.initiate() member, not just the seed."""
        action = PackagesInstallStrategy().build_run_step(
            "rs_initiate", ["node00", "node01", "node02"], _spec(OperatingSystem.UBUNTU)
        )

        command = " ".join(action.command)
        assert "node00:27017" in command
        assert "node01:27017" in command
        assert "node02:27017" in command
        assert "rs-test" in command

    def test_create_pmm_monitoring_user_requires_params(self) -> None:
        """Without a generated username/password, this is a programming error."""
        with pytest.raises(ValueError, match="username"):
            PackagesInstallStrategy().build_run_step(
                "create_pmm_monitoring_user", ["node00"], _spec(OperatingSystem.UBUNTU)
            )

    def test_create_pmm_monitoring_user_embeds_the_given_credentials(self) -> None:
        """The dispatched command creates exactly the user the caller generated."""
        action = PackagesInstallStrategy().build_run_step(
            "create_pmm_monitoring_user",
            ["node00"],
            _spec(OperatingSystem.UBUNTU),
            params={"username": "pmm_monitor", "password": "generated-secret"},
        )

        command = " ".join(action.command)
        assert "pmm_monitor" in command
        assert "generated-secret" in command
        assert "clusterMonitor" in command


class TestPlanFinalizeSteps:
    """Assert the finalize step list is fixed and OS-independent."""

    def test_returns_the_fixed_finalize_step_names(self) -> None:
        """enable_auth, the only finalize step phase 1 needs."""
        spec = _spec(OperatingSystem.UBUNTU)
        assert (
            PackagesInstallStrategy().plan_finalize_steps(spec) == FINALIZE_STEP_NAMES
        )


class TestBuildFinalizeStep:
    """Assert build_finalize_step rejects unknown names and enables auth correctly."""

    def test_unknown_finalize_step_name_raises(self) -> None:
        """A per-host forward step name is not a finalize step."""
        with pytest.raises(
            ValueError, match="not a PackagesInstallStrategy finalize step"
        ):
            PackagesInstallStrategy().build_finalize_step(
                "configure_mongod", "node00", _spec(OperatingSystem.UBUNTU)
            )

    def test_enable_auth_turns_authorization_on(self) -> None:
        """The one thing configure_mongod deliberately left out."""
        action = PackagesInstallStrategy().build_finalize_step(
            "enable_auth", "node00", _spec(OperatingSystem.UBUNTU)
        )

        command = " ".join(action.command)
        assert "authorization: enabled" in command
        assert f"keyFile: {KEY_FILE_PATH}" in command

    def test_enable_auth_restarts_mongod(self) -> None:
        """security.authorization only takes effect on a fresh start."""
        action = PackagesInstallStrategy().build_finalize_step(
            "enable_auth", "node00", _spec(OperatingSystem.UBUNTU)
        )

        assert "systemctl restart mongod" in " ".join(action.command)

    def test_enable_auth_keeps_the_replica_set_name(self) -> None:
        """Rewriting the config must not lose settings configure_mongod wrote."""
        action = PackagesInstallStrategy().build_finalize_step(
            "enable_auth", "node00", _spec(OperatingSystem.UBUNTU)
        )

        command = " ".join(action.command)
        assert "replSetName: rs-test" in command
        assert "fork: true" in command
        assert f"path: {LOG_PATH}" in command


class TestPlanRollbackSteps:
    """Assert the rollback step list is fixed and OS-independent."""

    def test_returns_the_fixed_rollback_step_names(self) -> None:
        """The reverse of the forward steps that actually change host state."""
        spec = _spec(OperatingSystem.UBUNTU)
        assert (
            PackagesInstallStrategy().plan_rollback_steps(spec) == ROLLBACK_STEP_NAMES
        )


class TestBuildRollbackStep:
    """Assert build_rollback_step produces the right teardown command per OS."""

    @pytest.mark.parametrize("step_name", ROLLBACK_STEP_NAMES)
    def test_every_planned_rollback_step_builds_without_raising(
        self, step_name: str
    ) -> None:
        """Every name plan_rollback_steps returns is one build_rollback_step knows."""
        PackagesInstallStrategy().build_rollback_step(
            step_name, "node00", _spec(OperatingSystem.UBUNTU)
        )

    def test_unknown_rollback_step_name_raises(self) -> None:
        """A forward step name is not a rollback step -- no silent no-op."""
        with pytest.raises(
            ValueError, match="not a PackagesInstallStrategy rollback step"
        ):
            PackagesInstallStrategy().build_rollback_step(
                "install_package", "node00", _spec(OperatingSystem.UBUNTU)
            )

    def test_purge_package_uses_apt_get_on_ubuntu(self) -> None:
        """Ubuntu's rollback purge goes through apt-get, not dnf."""
        action = PackagesInstallStrategy().build_rollback_step(
            "purge_package", "node00", _spec(OperatingSystem.UBUNTU)
        )

        assert "apt-get remove -y --purge percona-server-mongodb" in " ".join(
            action.command
        )

    def test_purge_package_uses_dnf_on_rocky(self) -> None:
        """Rocky's rollback purge goes through dnf, not apt-get."""
        action = PackagesInstallStrategy().build_rollback_step(
            "purge_package", "node00", _spec(OperatingSystem.ROCKY)
        )

        assert "dnf remove -y percona-server-mongodb" in " ".join(action.command)
