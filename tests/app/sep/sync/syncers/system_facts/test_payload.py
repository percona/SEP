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

"""Test the app.sep.sync.syncers.system_facts.payload module."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from app.sep.sync.syncers.system_facts import payload as payload_module
from app.sep.sync.syncers.system_facts.payload import (
    collect_host_facts,
    collect_installed_packages,
    collect_os_version,
    collect_service_version,
    main,
)

MODULE = "app.sep.sync.syncers.system_facts.payload"
OS_RELEASE = (
    'NAME="Ubuntu"\n'
    'VERSION_ID="22.04"\n'
    'VERSION="22.04.3 LTS (Jammy Jellyfish)"\n'
    'PRETTY_NAME="Ubuntu 22.04.3 LTS"\n'
    "ID=ubuntu\n"
)


def _write_config(tmp_path: Path, config: dict) -> Path:
    """Write a payload config file and return its path."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return path


class TestHostFacts:
    """Test best-effort host fact collection."""

    def test_collect_os_version(self, tmp_path, monkeypatch):
        """os_version is parsed from /etc/os-release PRETTY_NAME."""
        os_release = tmp_path / "os-release"
        os_release.write_text(OS_RELEASE)
        monkeypatch.setattr(payload_module, "OS_RELEASE_PATH", os_release)
        assert collect_os_version() == "Ubuntu 22.04.3 LTS"

    def test_collect_os_version_missing_returns_none(self, tmp_path, monkeypatch):
        """A missing os-release file yields None, not an error."""
        monkeypatch.setattr(
            payload_module, "OS_RELEASE_PATH", tmp_path / "does-not-exist"
        )
        assert collect_os_version() is None

    def test_collect_installed_packages_rpm(self, mocker):
        """Packages are parsed from the rpm query output."""
        mocker.patch(
            f"{MODULE}.shutil.which",
            side_effect=lambda b: "/usr/bin/rpm" if b == "rpm" else None,
        )
        mocker.patch(
            f"{MODULE}.subprocess.run",
            return_value=MagicMock(
                returncode=0, stdout="glibc\t2.35-1\nopenssl\t3.0.2\n"
            ),
        )
        packages = collect_installed_packages()
        assert {"name": "glibc", "version": "2.35-1"} in packages
        assert {"name": "openssl", "version": "3.0.2"} in packages

    def test_collect_installed_packages_no_manager_returns_none(self, mocker):
        """With neither rpm nor dpkg available, packages collection is skipped."""
        mocker.patch(f"{MODULE}.shutil.which", return_value=None)
        assert collect_installed_packages() is None

    def test_collect_host_facts_assembles_collected_at(self, mocker):
        """Host facts carry collected_at plus whatever was gathered."""
        mocker.patch(f"{MODULE}.collect_os_version", return_value="Ubuntu 22.04")
        mocker.patch(
            f"{MODULE}.collect_installed_packages",
            return_value=[{"name": "glibc", "version": "2.35"}],
        )
        mocker.patch(f"{MODULE}.collect_host_config", return_value={"kernel": "5.15.0"})
        facts = collect_host_facts()
        assert facts["os_version"] == "Ubuntu 22.04"
        assert facts["installed_packages"] == [{"name": "glibc", "version": "2.35"}]
        assert facts["config"] == {"kernel": "5.15.0"}
        assert "collected_at" in facts


class TestServiceVersion:
    """Test per-engine version dispatch and error handling."""

    def test_dispatch_mysql(self, mocker):
        """A MySQL service routes to the MySQL collector."""
        mocker.patch(f"{MODULE}._collect_mysql_version", return_value="8.0.35")
        assert collect_service_version("10.0.0.5:3306", "mysql") == "8.0.35"

    def test_dispatch_postgresql(self, mocker):
        """A PostgreSQL service routes to the PostgreSQL collector."""
        mocker.patch(f"{MODULE}._collect_postgresql_version", return_value="15.4")
        assert collect_service_version("10.0.0.5:5432", "postgresql") == "15.4"

    def test_dispatch_mongodb(self, mocker):
        """A MongoDB service routes to the MongoDB collector."""
        mocker.patch(f"{MODULE}._collect_mongodb_version", return_value="7.0.2")
        assert collect_service_version("10.0.0.5:27017", "mongodb") == "7.0.2"

    def test_unknown_type_returns_none(self):
        """An unsupported service type is not probed."""
        assert collect_service_version("10.0.0.5:6033", "proxysql") is None

    def test_collector_error_is_swallowed(self, mocker):
        """A failing collector (bad creds, unreachable) yields None, not a crash."""
        mocker.patch(
            f"{MODULE}._collect_mysql_version", side_effect=RuntimeError("no creds")
        )
        assert collect_service_version("10.0.0.5:3306", "mysql") is None


class TestMain:
    """Test the payload entrypoint orchestration and JSON output."""

    def test_main_collect_host_and_services(
        self, tmp_path, monkeypatch, mocker, capsys
    ):
        """collect_host=True emits host facts plus per-service versions."""
        config = _write_config(
            tmp_path,
            {
                "collect_host": True,
                "services": [{"address": "10.0.0.5:3306", "type": "mysql"}],
            },
        )
        monkeypatch.setattr("sys.argv", ["payload", "-c", str(config)])
        mocker.patch(
            f"{MODULE}.collect_host_facts",
            return_value={"os_version": "Ubuntu 22.04", "collected_at": "t"},
        )
        mocker.patch(f"{MODULE}.collect_service_version", return_value="8.0.35")

        main()

        out = json.loads(capsys.readouterr().out)
        assert out["host"]["os_version"] == "Ubuntu 22.04"
        assert out["services"]["10.0.0.5:3306"]["db_engine_version"] == "8.0.35"
        assert "collected_at" in out["services"]["10.0.0.5:3306"]

    def test_main_collect_host_false(self, tmp_path, monkeypatch, mocker, capsys):
        """collect_host=False yields a null host but still probes services."""
        config = _write_config(
            tmp_path,
            {
                "collect_host": False,
                "services": [{"address": "10.0.0.5:5432", "type": "postgresql"}],
            },
        )
        monkeypatch.setattr("sys.argv", ["payload", "-c", str(config)])
        host = mocker.patch(f"{MODULE}.collect_host_facts")
        mocker.patch(f"{MODULE}.collect_service_version", return_value="15.4")

        main()

        out = json.loads(capsys.readouterr().out)
        assert out["host"] is None
        host.assert_not_called()
        assert out["services"]["10.0.0.5:5432"]["db_engine_version"] == "15.4"

    def test_main_service_failure_omitted(self, tmp_path, monkeypatch, mocker, capsys):
        """A service with no obtainable version is omitted; main still exits cleanly."""
        config = _write_config(
            tmp_path,
            {
                "collect_host": False,
                "services": [
                    {"address": "10.0.0.5:3306", "type": "mysql"},
                    {"address": "10.0.0.9:5432", "type": "postgresql"},
                ],
            },
        )
        monkeypatch.setattr("sys.argv", ["payload", "-c", str(config)])
        mocker.patch(
            f"{MODULE}.collect_service_version",
            side_effect=lambda address, _type: "8.0.35"
            if address == "10.0.0.5:3306"
            else None,
        )

        main()

        out = json.loads(capsys.readouterr().out)
        assert "10.0.0.5:3306" in out["services"]
        assert "10.0.0.9:5432" not in out["services"]

    def test_main_empty_host_facts_yields_null_host(
        self, tmp_path, monkeypatch, mocker, capsys
    ):
        """Host facts with no usable field collapse to a null host (no half-snapshot)."""
        config = _write_config(tmp_path, {"collect_host": True, "services": []})
        monkeypatch.setattr("sys.argv", ["payload", "-c", str(config)])
        mocker.patch(f"{MODULE}.collect_host_facts", return_value={"collected_at": "t"})

        main()

        out = json.loads(capsys.readouterr().out)
        assert out["host"] is None
