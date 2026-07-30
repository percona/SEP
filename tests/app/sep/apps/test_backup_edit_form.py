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

"""Cover the shared backup edit-form backfill helper in ``shared.backups.edit_form``."""

import pytest

from app.sep.apps.shared.backups.edit_form import parse_server_list_config


class TestParseServerListConfig:
    """Cover the shared SERVER_LIST edit-form backfill helper."""

    @staticmethod
    def _task(*, name: str = "edit-task", target: str = "host.example.com") -> dict:
        """Build the minimal task dict the helper reads identity fields from."""
        return {"name": name, "data": {"meta": {"target": target}}}

    def test_builds_common_base_and_merges_extra_fields(self) -> None:
        """Build the shared base dict and layer the caller's app-specific keys."""
        server_config = {"HOST": "10.0.0.5", "BACKUP_TYPE": "pgbackrest"}

        result = parse_server_list_config(
            self._task(),
            server_config,
            {},
            {"port": 5432, "alias": "db1"},
        )

        assert result == {
            "name": "edit-task",
            "hostname": "host.example.com",
            "backup_type": "pgbackrest",
            "service_id": None,
            "host": "10.0.0.5",
            "port": 5432,
            "alias": "db1",
        }

    def test_extracts_upload_provider_targets(self) -> None:
        """Build the S3/GSUTIL/RSYNC targets from ALL_SERVERS for the providers."""
        server_config = {
            "HOST": "10.0.0.5",
            "BACKUP_TYPE": "xtrabackup",
            "UPLOAD": ["s3", "gsutil", "rsync"],
        }
        all_servers_config = {
            "S3_BUCKET": "my-bucket",
            "S3_STORAGE_CLASS": "STANDARD_IA",
            "SKIP_S3_SAFETY_CHECK": True,
            "GS_BUCKET": "my-gs-bucket",
            "RSYNC_PATH": "/mnt/backups",
        }

        result = parse_server_list_config(
            self._task(), server_config, all_servers_config, {}
        )

        assert result["s3_bucket"] == "my-bucket"
        assert result["s3_storage_class"] == "STANDARD_IA"
        assert result["skip_s3_safety_check"] is True
        assert result["gs_bucket"] == "my-gs-bucket"
        assert result["rsync_path"] == "/mnt/backups"

    def test_upload_targets_default_when_all_servers_empty(self) -> None:
        """Cover the None/False defaults for providers with an empty ALL_SERVERS."""
        server_config = {
            "HOST": "10.0.0.5",
            "BACKUP_TYPE": "xtrabackup",
            "UPLOAD": ["s3"],
        }

        result = parse_server_list_config(self._task(), server_config, {}, {})

        assert result["s3_bucket"] is None
        assert result["s3_storage_class"] is None
        assert result["skip_s3_safety_check"] is False

    def test_lowercases_remaining_all_servers_keys(self) -> None:
        """Cover the catch-all lowering of leftover ALL_SERVERS keys not yet present."""
        retention_days = 7
        server_config = {"HOST": "10.0.0.5", "BACKUP_TYPE": "pgbackrest"}
        all_servers_config = {"LOGGING_DIR": "/var/log", "RETENTION": retention_days}

        result = parse_server_list_config(
            self._task(), server_config, all_servers_config, {}
        )

        assert result["logging_dir"] == "/var/log"
        assert result["retention"] == retention_days

    def test_explicit_keys_win_over_lowered_all_servers_fallback(self) -> None:
        """Assert explicit keys win over an ALL_SERVERS key lowering onto them."""
        explicit_port = 5432
        server_config = {"HOST": "10.0.0.5", "BACKUP_TYPE": "pgbackrest"}
        all_servers_config = {"HOST": "should-not-win", "PORT": 9999}

        result = parse_server_list_config(
            self._task(),
            server_config,
            all_servers_config,
            {"port": explicit_port},
        )

        assert result["host"] == "10.0.0.5"
        assert result["port"] == explicit_port

    def test_ignores_non_string_upload_providers(self) -> None:
        """Skip non-string UPLOAD entries so the provider set only holds names."""
        server_config = {
            "HOST": "10.0.0.5",
            "BACKUP_TYPE": "xtrabackup",
            "UPLOAD": [None, 1, "s3"],
        }
        all_servers_config = {"S3_BUCKET": "my-bucket"}

        result = parse_server_list_config(
            self._task(), server_config, all_servers_config, {}
        )

        # The str "s3" still resolves; the None/int entries are dropped without error.
        assert result["s3_bucket"] == "my-bucket"
        assert "gs_bucket" not in result
        assert "rsync_path" not in result

    def test_gsutil_and_rsync_targets_default_when_all_servers_empty(self) -> None:
        """Default GSUTIL/RSYNC targets to None when ALL_SERVERS lacks the keys."""
        server_config = {
            "HOST": "10.0.0.5",
            "BACKUP_TYPE": "xtrabackup",
            "UPLOAD": ["gsutil", "rsync"],
        }

        result = parse_server_list_config(self._task(), server_config, {}, {})

        assert result["gs_bucket"] is None
        assert result["rsync_path"] is None

    @pytest.mark.parametrize(
        ("task", "server_config", "missing"),
        [
            (
                {"data": {"meta": {"target": "h"}}},
                {"HOST": "x", "BACKUP_TYPE": "t"},
                "name",
            ),
            (
                {"name": "n", "data": {"meta": {}}},
                {"HOST": "x", "BACKUP_TYPE": "t"},
                "target",
            ),
            (
                {"name": "n", "data": {"meta": {"target": "h"}}},
                {"HOST": "x"},
                "BACKUP_TYPE",
            ),
            (
                {"name": "n", "data": {"meta": {"target": "h"}}},
                {"BACKUP_TYPE": "t"},
                "HOST",
            ),
        ],
    )
    def test_missing_required_key_raises_keyerror(
        self, task: dict, server_config: dict, missing: str
    ) -> None:
        """Raise KeyError when a required task/server field is absent."""
        with pytest.raises(KeyError):
            parse_server_list_config(task, server_config, {}, {})
