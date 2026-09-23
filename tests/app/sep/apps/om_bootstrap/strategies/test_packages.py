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

import base64
import shlex
import shutil
import subprocess
from pathlib import Path
from uuid import UUID

import pytest

from app.sep.apps.om_bootstrap.dispatch import build_step_script
from app.sep.apps.om_bootstrap.strategies import packages
from app.sep.apps.om_bootstrap.strategies.packages import (
    _mongosh_eval,
    DATA_PATH,
    LOG_PATH,
    OWNERSHIP_MARKER_PATH,
    PackagesInstallStrategy,
    PID_FILE_PATH,
)
from app.sep.apps.om_bootstrap.strategy import (
    BootstrapSpec,
    InstallMethod,
    InstallStrategy,
    OperatingSystem,
)

SUPPORTED_OSES = [OperatingSystem.UBUNTU, OperatingSystem.ROCKY]

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_RUN_ID = UUID("22222222-2222-4222-8222-222222222222")


def _spec(os_: OperatingSystem, run_id: UUID | None = RUN_ID) -> BootstrapSpec:
    return BootstrapSpec(
        install_method=InstallMethod.PACKAGES,
        os=os_,
        mongodb_version="8.0",
        replica_set_name="rs-test",
        run_id=run_id,
    )


#: Derived from the strategy itself, so the parametrized build tests below cover
#: exactly what the strategy plans; the plan tests pin the lists' contents.
STEP_NAMES = PackagesInstallStrategy().plan_steps(_spec(OperatingSystem.UBUNTU))
RUN_STEP_NAMES = PackagesInstallStrategy().plan_run_steps(_spec(OperatingSystem.UBUNTU))
ROLLBACK_STEP_NAMES = PackagesInstallStrategy().plan_rollback_steps(
    _spec(OperatingSystem.UBUNTU)
)

#: Every per-host step's own required ``params``, so a single parametrized test
#: can build every step without hand-listing which ones need what.
_STEP_PARAMS: dict[str, dict[str, str]] = {
    "distribute_keyfile": {"key_file_content": "test-keyfile-content"},
}

_SH = shutil.which("sh") or "/bin/sh"


def _body(command: list[str]) -> str:
    """Return the shell body of an ``["sh", "-c", body]`` action."""
    assert command[:2] == ["sh", "-c"]
    return command[2]


class TestPackagesInstallStrategyIsAnInstallStrategy:
    """Pin the structural-protocol contract, not just the concrete class."""

    def test_satisfies_the_protocol(self) -> None:
        """A future caller programming against InstallStrategy accepts this class."""
        assert isinstance(PackagesInstallStrategy(), InstallStrategy)


class TestPlanSteps:
    """Assert the step list is fixed and OS-independent for phase 1."""

    @pytest.mark.parametrize("os_", SUPPORTED_OSES)
    def test_returns_the_fixed_step_names_regardless_of_os(
        self, os_: OperatingSystem
    ) -> None:
        """Ubuntu and Rocky get the same step names -- only build_step branches on OS."""
        assert PackagesInstallStrategy().plan_steps(_spec(os_)) == [
            "pre_check",
            "configure_repository",
            "install_package",
            "distribute_keyfile",
            "configure_mongod",
            "start_service",
            "verify",
        ]


class TestBuildStep:
    """Assert build_step produces the right command per step and per OS."""

    @pytest.mark.parametrize("os_", SUPPORTED_OSES)
    @pytest.mark.parametrize("step_name", STEP_NAMES)
    def test_every_planned_step_builds_a_runnable_action(
        self, step_name: str, os_: OperatingSystem
    ) -> None:
        """Build a non-empty command with a real timeout for every name plan_steps returns."""
        action = PackagesInstallStrategy().build_step(
            step_name, "node00", _spec(os_), params=_STEP_PARAMS.get(step_name)
        )

        assert action.command
        assert all(action.command)
        assert action.timeout_s > 0

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

    def test_configure_repository_quotes_the_channel(self) -> None:
        """Pass the channel to the shell quoted, whatever the version string held."""
        spec = _spec(OperatingSystem.UBUNTU).model_copy(
            update={"mongodb_version": "8.0;touch /tmp/x"}
        )

        action = PackagesInstallStrategy().build_step(
            "configure_repository", "node00", spec
        )

        assert "percona-release setup -y 'psmdb-80;touch /tmp/x'" in _body(
            action.command
        )

    def test_configure_repository_accepts_a_full_patch_version(self) -> None:
        """Only major.minor selects the channel, not the full patch version.

        Exactly like the request field's own "only the major version selects
        the install source" comment (TriggerHostBootstrapRequest.mongodb_version)
        promises - a full patch version like "7.0.14" must not leak into the
        channel name. Confirmed against a live host: this used to produce the
        nonexistent channel "psmdb-7014" and configure_repository failed with
        "Specified repository does not exist".
        """
        spec = BootstrapSpec(
            install_method=InstallMethod.PACKAGES,
            os=OperatingSystem.ROCKY,
            mongodb_version="7.0.14",
            replica_set_name="rs-test",
        )
        action = PackagesInstallStrategy().build_step(
            "configure_repository", "node00", spec
        )

        command = " ".join(action.command)
        assert "psmdb-70" in command
        assert "psmdb-7014" not in command

    def test_install_package_uses_apt_get_on_ubuntu(self) -> None:
        """Ubuntu's package install goes through apt-get, not dnf."""
        action = PackagesInstallStrategy().build_step(
            "install_package", "node00", _spec(OperatingSystem.UBUNTU)
        )

        assert "apt-get install -y percona-server-mongodb" in " ".join(action.command)

    @pytest.mark.parametrize("os_", SUPPORTED_OSES)
    def test_install_package_claims_the_host_before_installing(
        self, os_: OperatingSystem
    ) -> None:
        """Claim the host for this run first, so a half-finished install rolls back."""
        action = PackagesInstallStrategy().build_step(
            "install_package", "node00", _spec(os_)
        )

        lines = _body(action.command).splitlines()
        assert lines[0] == f"printf '%s\\n' {RUN_ID} > {OWNERSHIP_MARKER_PATH}"
        assert "percona-server-mongodb" in lines[1]

    def test_install_package_requires_a_run_id(self) -> None:
        """Refuse to write an ownership marker no run's rollback could match."""
        with pytest.raises(ValueError, match="install_package requires spec.run_id"):
            PackagesInstallStrategy().build_step(
                "install_package", "node00", _spec(OperatingSystem.UBUNTU, None)
            )

    def test_install_package_writes_the_run_id_to_the_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Leave exactly this run's id in the marker once the shell has run."""
        marker = tmp_path / "mongod.om-bootstrap"
        monkeypatch.setattr(packages, "OWNERSHIP_MARKER_PATH", str(marker))
        action = PackagesInstallStrategy().build_step(
            "install_package", "node00", _spec(OperatingSystem.UBUNTU)
        )
        bin_dir = _recording_bin(tmp_path, ["apt-get"])

        subprocess.run(
            [_SH, "-c", _body(action.command)],
            env={"PATH": str(bin_dir)},
            check=True,
        )

        assert marker.read_text() == f"{RUN_ID}\n"

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

    def test_distribute_keyfile_requires_params(self) -> None:
        """Without a keyFile to plant, this is a programming error, not a blank file."""
        with pytest.raises(ValueError, match="key_file_content"):
            PackagesInstallStrategy().build_step(
                "distribute_keyfile", "node00", _spec(OperatingSystem.UBUNTU)
            )

    def test_distribute_keyfile_writes_the_given_content(self) -> None:
        """Carry exactly the content the caller supplied, base64-encoded."""
        content = "super-secret-keyfile-bytes"
        action = PackagesInstallStrategy().build_step(
            "distribute_keyfile",
            "node00",
            _spec(OperatingSystem.UBUNTU),
            params={"key_file_content": content},
        )

        body = _body(action.command)
        encoded = shlex.split(body)[2]
        assert base64.b64decode(encoded).decode() == content
        assert content not in body
        assert "install -m 400 -o mongod -g mongod /dev/stdin" in body

    def test_distribute_keyfile_content_cannot_break_out_of_the_command(
        self,
    ) -> None:
        """Decode content holding a heredoc delimiter or a command verbatim."""
        content = "abc\nMONGOD_KEYFILE\n$(touch /tmp/pwned)'\"\n"
        action = PackagesInstallStrategy().build_step(
            "distribute_keyfile",
            "node00",
            _spec(OperatingSystem.UBUNTU),
            params={"key_file_content": content},
        )
        decoder = _body(action.command).split(" | install ")[0]

        result = subprocess.run([_SH, "-c", decoder], capture_output=True, check=True)

        assert result.stdout.decode() == content

    def test_verify_goes_through_mongosh_eval_too(self) -> None:
        """``verify`` must not bypass the Atlas CLI probe suppression every mongosh call needs."""
        action = PackagesInstallStrategy().build_step(
            "verify", "node00", _spec(OperatingSystem.UBUNTU)
        )

        assert action == _mongosh_eval("db.adminCommand('ping').ok")


class TestPlanRunSteps:
    """Assert the run-level step list is fixed and OS-independent."""

    def test_returns_the_fixed_run_step_names(self) -> None:
        """rs_initiate and create_pmm_monitoring_user, in that order."""
        spec = _spec(OperatingSystem.UBUNTU)
        assert PackagesInstallStrategy().plan_run_steps(spec) == [
            "rs_initiate",
            "create_pmm_monitoring_user",
        ]


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

    def test_create_pmm_monitoring_user_keeps_the_password_out_of_argv(self) -> None:
        """Read the JS from a private temp file, never through --eval."""
        action = PackagesInstallStrategy().build_run_step(
            "create_pmm_monitoring_user",
            ["node00"],
            _spec(OperatingSystem.UBUNTU),
            params={"username": "pmm_monitor", "password": "generated-secret"},
        )
        script = build_step_script(action)

        assert "--eval" not in script
        assert 'mongosh --quiet --file "$js"' in script
        assert "umask 077" in script
        assert "sh -c" not in script
        heredoc = script.split("<<'OM_BOOTSTRAP_JS'\n")[1].split("\nOM_BOOTSTRAP_JS\n")[
            0
        ]
        assert "generated-secret" in heredoc

    def test_create_pmm_monitoring_user_disables_the_atlas_cli_check(self) -> None:
        """Mongosh's Atlas CLI local-deployment probe closes the localhost exception.

        Confirmed against a real run where every attempt to create the first
        user failed "not authorized" even though create_pmm_monitoring_user's
        own command was correct -- the probe, not our command, burned it.
        """
        action = PackagesInstallStrategy().build_run_step(
            "create_pmm_monitoring_user",
            ["node00"],
            _spec(OperatingSystem.UBUNTU),
            params={"username": "pmm_monitor", "password": "generated-secret"},
        )

        command = " ".join(action.command)
        assert "MONGOSH_DISABLE_ATLAS_LOCAL_DEV_CLUSTER_CHECK=1" in command


class TestPlanRollbackSteps:
    """Assert the rollback step list is fixed and OS-independent."""

    def test_returns_the_fixed_rollback_step_names(self) -> None:
        """The reverse of the forward steps that actually change host state."""
        spec = _spec(OperatingSystem.UBUNTU)
        assert PackagesInstallStrategy().plan_rollback_steps(spec) == [
            "stop_service",
            "remove_config",
            "remove_keyfile",
            "purge_package",
            "remove_data",
        ]


class TestBuildRollbackStep:
    """Assert build_rollback_step produces the right teardown command per OS."""

    @pytest.mark.parametrize("os_", SUPPORTED_OSES)
    @pytest.mark.parametrize("step_name", ROLLBACK_STEP_NAMES)
    def test_every_rollback_step_is_scoped_to_its_run(
        self, step_name: str, os_: OperatingSystem
    ) -> None:
        """Skip every rollback step unless the marker holds this run's id."""
        action = PackagesInstallStrategy().build_rollback_step(
            step_name, "node00", _spec(os_)
        )

        assert _body(action.command).startswith(
            f'[ "$(cat {OWNERSHIP_MARKER_PATH} 2>/dev/null)" = {RUN_ID} ] || exit 0\n'
        )

    @pytest.mark.parametrize("step_name", ROLLBACK_STEP_NAMES)
    def test_every_rollback_step_requires_a_run_id(self, step_name: str) -> None:
        """Refuse to build a rollback step that no marker could scope."""
        with pytest.raises(ValueError, match=f"{step_name} requires spec.run_id"):
            PackagesInstallStrategy().build_rollback_step(
                step_name, "node00", _spec(OperatingSystem.UBUNTU, None)
            )

    def test_remove_data_removes_the_marker_last(self) -> None:
        """Remove the marker after everything else, so a retried rollback still runs."""
        action = PackagesInstallStrategy().build_rollback_step(
            "remove_data", "node00", _spec(OperatingSystem.UBUNTU)
        )

        lines = _body(action.command).strip().splitlines()
        assert lines[-2] == f"rm -rf {DATA_PATH}"
        assert lines[-1] == f"rm -f {OWNERSHIP_MARKER_PATH}"

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


def _recording_bin(tmp_path: Path, fakes: list[str]) -> Path:
    """Build a ``PATH`` directory with ``cat``/``rm`` and fakes that log their argv.

    Each fake appends its name and arguments to ``calls.log`` in ``tmp_path``.

    :param tmp_path: The test's scratch directory.
    :param fakes: The commands to fake.
    :return: The directory.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("cat", "rm"):
        real = shutil.which(tool)
        assert real is not None
        (bin_dir / tool).symlink_to(real)
    log = tmp_path / "calls.log"
    for fake in fakes:
        path = bin_dir / fake
        path.write_text(f'#!/bin/sh\necho "{fake} $*" >> {shlex.quote(str(log))}\n')
        path.chmod(0o755)
    return bin_dir


def _fake_bin(tmp_path: Path, *, with_mongod: bool) -> Path:
    """Build a ``PATH`` directory with the real tools pre_check needs and fake ones.

    :param tmp_path: The test's scratch directory.
    :param with_mongod: Whether a ``mongod`` is on this ``PATH``.
    :return: The directory.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("df", "tail", "ls"):
        real = shutil.which(tool)
        assert real is not None
        (bin_dir / tool).symlink_to(real)
    fakes = ["apt-get", "mongod"] if with_mongod else ["apt-get"]
    for fake in fakes:
        path = bin_dir / fake
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    return bin_dir


class TestPreCheckCommand:
    """Run pre_check's generated shell for real against scratch paths."""

    @pytest.fixture
    def paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[Path, Path]:
        """Point the config and data paths at scratch paths, with a 1-byte minimum."""
        config = tmp_path / "mongod.conf"
        data = tmp_path / "data"
        monkeypatch.setattr(packages, "CONFIG_PATH", str(config))
        monkeypatch.setattr(packages, "DATA_PATH", str(data))
        monkeypatch.setattr(packages, "MIN_DATA_DISK_BYTES", 1)
        return config, data

    def _run(
        self, tmp_path: Path, *, with_mongod: bool = False
    ) -> subprocess.CompletedProcess[str]:
        action = PackagesInstallStrategy().build_step(
            "pre_check", "node00", _spec(OperatingSystem.UBUNTU)
        )
        bin_dir = _fake_bin(tmp_path, with_mongod=with_mongod)
        return subprocess.run(
            [_SH, "-c", _body(action.command)],
            capture_output=True,
            text=True,
            env={"PATH": str(bin_dir)},
            check=False,
        )

    def test_passes_on_a_clean_host(
        self, tmp_path: Path, paths: tuple[Path, Path]
    ) -> None:
        """Pass on a host with no MongoDB anywhere and enough disk."""
        result = self._run(tmp_path)

        assert result.returncode == 0, result.stderr

    def test_passes_with_an_empty_data_directory(
        self, tmp_path: Path, paths: tuple[Path, Path]
    ) -> None:
        """Pass with an empty data directory, measuring its free space."""
        paths[1].mkdir()

        result = self._run(tmp_path)

        assert result.returncode == 0, result.stderr

    def test_fails_when_mongod_is_on_path(
        self, tmp_path: Path, paths: tuple[Path, Path]
    ) -> None:
        """Fail when a mongod is installed: the host runs a MongoDB of its own."""
        result = self._run(tmp_path, with_mongod=True)

        assert result.returncode != 0
        assert "mongod is already installed" in result.stderr

    def test_fails_when_the_config_file_exists(
        self, tmp_path: Path, paths: tuple[Path, Path]
    ) -> None:
        """Fail when a mongod.conf from someone else's install is present."""
        paths[0].write_text("net: {}\n")

        result = self._run(tmp_path)

        assert result.returncode != 0
        assert "already exists" in result.stderr

    def test_fails_when_the_data_directory_is_not_empty(
        self, tmp_path: Path, paths: tuple[Path, Path]
    ) -> None:
        """Fail on existing data files, exactly what rollback must never delete."""
        paths[1].mkdir()
        (paths[1] / "WiredTiger").write_text("")

        result = self._run(tmp_path)

        assert result.returncode != 0
        assert "is not empty" in result.stderr

    def test_fails_without_enough_disk_space(
        self,
        tmp_path: Path,
        paths: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Fail with less free space than the minimum, naming why."""
        monkeypatch.setattr(packages, "MIN_DATA_DISK_BYTES", 2**62)

        result = self._run(tmp_path)

        assert result.returncode != 0
        assert "bytes free" in result.stderr

    def test_fails_when_free_space_cannot_be_measured(
        self, tmp_path: Path, paths: tuple[Path, Path]
    ) -> None:
        """Fail closed when ``df`` prints nothing, instead of passing the check."""
        action = PackagesInstallStrategy().build_step(
            "pre_check", "node00", _spec(OperatingSystem.UBUNTU)
        )
        bin_dir = _fake_bin(tmp_path, with_mongod=False)
        (bin_dir / "df").unlink()
        (bin_dir / "df").write_text("#!/bin/sh\nexit 1\n")
        (bin_dir / "df").chmod(0o755)

        result = subprocess.run(
            [_SH, "-c", _body(action.command)],
            capture_output=True,
            text=True,
            env={"PATH": str(bin_dir)},
            check=False,
        )

        assert result.returncode != 0
        assert "could not measure free space" in result.stderr


class TestRollbackCommands:
    """Run rollback steps' generated shell for real against scratch paths."""

    @pytest.fixture
    def paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[Path, Path, Path]:
        """Point every path at scratch copies holding a config file and data."""
        config = tmp_path / "mongod.conf"
        data = tmp_path / "data"
        marker = tmp_path / "mongod.om-bootstrap"
        monkeypatch.setattr(packages, "CONFIG_PATH", str(config))
        monkeypatch.setattr(packages, "DATA_PATH", str(data))
        monkeypatch.setattr(packages, "OWNERSHIP_MARKER_PATH", str(marker))
        config.write_text("net: {}\n")
        data.mkdir()
        (data / "WiredTiger").write_text("")
        return config, data, marker

    def _run(self, tmp_path: Path, step_name: str) -> None:
        action = PackagesInstallStrategy().build_rollback_step(
            step_name, "node00", _spec(OperatingSystem.UBUNTU)
        )
        bin_dir = tmp_path / "bin"
        if not bin_dir.exists():
            _recording_bin(tmp_path, ["systemctl", "apt-get"])
        subprocess.run(
            [_SH, "-c", _body(action.command)],
            env={"PATH": str(bin_dir)},
            check=True,
        )

    def _run_all(self, tmp_path: Path) -> list[str]:
        """Run every rollback step in order and return the faked commands' calls."""
        for step_name in ROLLBACK_STEP_NAMES:
            self._run(tmp_path, step_name)
        log = tmp_path / "calls.log"
        return log.read_text().splitlines() if log.exists() else []

    def test_leaves_a_host_without_the_marker_untouched(
        self, tmp_path: Path, paths: tuple[Path, Path, Path]
    ) -> None:
        """Leave a MongoDB this strategy never installed intact."""
        config, data, _marker = paths

        calls = self._run_all(tmp_path)

        assert calls == []
        assert config.exists()
        assert (data / "WiredTiger").exists()

    def test_leaves_another_runs_install_untouched(
        self, tmp_path: Path, paths: tuple[Path, Path, Path]
    ) -> None:
        """Make every step a no-op when the marker holds a different run's id.

        The host an earlier run bootstrapped keeps its marker; a later run
        that fails ``pre_check`` there and rolls back must not destroy it.
        """
        config, data, marker = paths
        marker.write_text(f"{OTHER_RUN_ID}\n")

        calls = self._run_all(tmp_path)

        assert calls == []
        assert config.exists()
        assert (data / "WiredTiger").exists()
        assert marker.read_text() == f"{OTHER_RUN_ID}\n"

    def test_removes_what_it_installed_when_the_marker_holds_its_run(
        self, tmp_path: Path, paths: tuple[Path, Path, Path]
    ) -> None:
        """Stop, purge, and remove everything, then the marker, for this run."""
        config, data, marker = paths
        marker.write_text(f"{RUN_ID}\n")

        calls = self._run_all(tmp_path)

        assert calls == [
            "systemctl disable --now mongod",
            "apt-get remove -y --purge percona-server-mongodb",
        ]
        assert not config.exists()
        assert not data.exists()
        assert not marker.exists()
