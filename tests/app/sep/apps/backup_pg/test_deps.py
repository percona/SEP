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

"""Define tests for the app.sep.apps.backup_pg.deps and spec modules."""

import pytest
import yaml

from app.core.utils.path import resolve_payload_reference
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_pg.deps import (
    get_backups_task_info,
    parse_backup_task_data,
)
from app.sep.apps.backup_pg.models import BackupPgForm, BackupType
from app.sep.apps.backup_pg.spec import build_backup_pg_spec
from app.sep.apps.framework.spec import ResolvedEntities
from app.sep.connectivity import CONNECTIVITY_META_PORT_KEY
from app.sep.inventory import CreatedService
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedServiceFactory,
)


def _resolved(service: CreatedService) -> ResolvedEntities:
    """Wrap ``service`` in the resolved-entities the spec builder reads."""
    return ResolvedEntities(
        service=service,
        entities={"service_id": service},
        executor_host="executor-host",
    )


def _form(service_id: int, **overrides: object) -> BackupPgForm:
    """Build a backup_pg create form for the spec-builder tests."""
    return BackupPgForm(
        task_name="test_task",
        hostname="executor-host",
        service_id=service_id,
        stanza=overrides.pop("stanza", "sep-test"),
        backup_dir=overrides.pop("backup_dir", "/var/lib/pgbackrest"),
        **overrides,
    )


def test_build_backup_pg_spec_produces_run_python_config():
    """Emit a run-python config carrying the pgBackRest server entry."""
    service = CreatedServiceFactory.build(
        node=CreatedNodeFactory.build(address="db.internal"),
        type=ServiceTypeEnum.POSTGRESQL,
        port=5432,
    )

    spec = build_backup_pg_spec(_form(service.id), _resolved(service))

    assert spec.requirements == "packaging\nPyYAML"
    assert spec.payload == "file://app/sep/apps/backup_pg/payload"
    assert resolve_payload_reference(spec.payload).is_file()

    cfg = yaml.safe_load(spec.config)
    server_config = cfg["SERVER_LIST"][0]
    assert server_config["ALIAS"] == "sep-test"
    assert server_config["HOST"] == "localhost"
    assert server_config["BACKUP_TYPE"] == BackupType.PGBACKREST.value
    # BackupConfigServer declares no ``port`` field, so the server entry carries
    # no PORT; the executor port travels on the envelope's connectivity meta key.
    assert "PORT" not in server_config


def test_build_backup_pg_spec_uses_stanza_as_alias():
    """Use the stanza value, not the service address, as the server ``ALIAS``."""
    service = CreatedServiceFactory.build(
        node=CreatedNodeFactory.build(address="10.30.50.162"),
        type=ServiceTypeEnum.POSTGRESQL,
        port=5432,
    )

    spec = build_backup_pg_spec(
        _form(service.id, stanza="my-custom-stanza"), _resolved(service)
    )

    cfg = yaml.safe_load(spec.config)
    assert cfg["SERVER_LIST"][0]["ALIAS"] == "my-custom-stanza"
    assert cfg["SERVER_LIST"][0]["ALIAS"] != service.node.address


def test_get_backups_task_info():
    """Test extracting the correct fields from a backup_pg task dictionary."""
    server_port = 5555
    fake_task_dict = {
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "HOST": "my-db-host",
                                "PORT": server_port,
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
                            }
                        ]
                    }
                ),
            }
        }
    }

    result = get_backups_task_info(fake_task_dict)

    assert result["hostname"] == "host.example.com"
    assert result["host"] == "my-db-host"
    assert result["port"] == server_port
    assert result["backup_type"] == BackupType.PGBACKREST.name


def test_get_backups_task_info_port_falls_back_to_meta():
    """Test PORT missing from YAML falls back to the meta connectivity port."""
    meta_port = 6543
    fake_task_dict = {
        "data": {
            "meta": {
                "target": "host.example.com",
                CONNECTIVITY_META_PORT_KEY: meta_port,
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "HOST": "my-db-host",
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
                            }
                        ]
                    }
                ),
            }
        }
    }

    result = get_backups_task_info(fake_task_dict)

    assert result["port"] == meta_port


def test_parse_backup_task_data():
    """Test parsing backup task data for the backup_pg detail view."""
    expected_port = 5432
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "HOST": "localhost",
                                "PORT": expected_port,
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
                            }
                        ],
                        "ALL_SERVERS": {
                            "LOGGING_DIR": "/var/log/pgbackrest",
                        },
                    }
                ),
            }
        },
    }

    result = parse_backup_task_data(fake_task_dict)

    assert result["name"] == "test_task"
    assert result["hostname"] == "host.example.com"
    assert result["backup_type"] == BackupType.PGBACKREST.value
    assert result["service_id"] is None
    assert result["host"] == "localhost"
    assert result["port"] == expected_port
    assert result["logging_dir"] == "/var/log/pgbackrest"


def test_parse_backup_task_data_port_falls_back_to_meta():
    """Test PORT missing from YAML falls back to the meta connectivity port."""
    meta_port = 6543
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                CONNECTIVITY_META_PORT_KEY: meta_port,
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "HOST": "localhost",
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
                            }
                        ],
                    }
                ),
            }
        },
    }

    result = parse_backup_task_data(fake_task_dict)

    assert result["port"] == meta_port


@pytest.mark.parametrize(
    ("upload_providers", "all_servers", "expected_result"),
    [
        (
            ["s3"],
            {
                "S3_BUCKET": "my-bucket",
                "S3_STORAGE_CLASS": "STANDARD_IA",
                "SKIP_S3_SAFETY_CHECK": True,
            },
            {
                "s3_bucket": "my-bucket",
                "s3_storage_class": "STANDARD_IA",
                "skip_s3_safety_check": True,
            },
        ),
        (
            ["s3"],
            {},
            {
                "s3_bucket": None,
                "s3_storage_class": None,
                "skip_s3_safety_check": False,
            },
        ),
        (
            ["gsutil"],
            {"GS_BUCKET": "my-gs-bucket"},
            {"gs_bucket": "my-gs-bucket"},
        ),
        (
            ["gsutil"],
            {},
            {"gs_bucket": None},
        ),
        (
            ["rsync"],
            {"RSYNC_PATH": "/mnt/backups"},
            {"rsync_path": "/mnt/backups"},
        ),
        (
            ["rsync"],
            {},
            {"rsync_path": None},
        ),
        (
            ["S3"],
            {"S3_BUCKET": "case-insensitive"},
            {"s3_bucket": "case-insensitive"},
        ),
    ],
)
def test_parse_backup_task_data_storage_targets(
    upload_providers: list[str],
    all_servers: dict,
    expected_result: dict,
):
    """Round-trip S3/GSUTIL/RSYNC fields from persisted YAML on the edit-form path."""
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "HOST": "localhost",
                                "PORT": 5432,
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
                                "UPLOAD": upload_providers,
                            }
                        ],
                        "ALL_SERVERS": all_servers,
                    }
                ),
            }
        },
    }

    result = parse_backup_task_data(fake_task_dict)

    for key, value in expected_result.items():
        assert result[key] == value


def test_parse_backup_task_data_without_all_servers():
    """Test parse_backup_task_data handles missing ALL_SERVERS section."""
    expected_port = 5432
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "HOST": "localhost",
                                "PORT": expected_port,
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
                            }
                        ]
                    }
                ),
            }
        },
    }

    result = parse_backup_task_data(fake_task_dict)

    assert result["name"] == "test_task"
    assert result["hostname"] == "host.example.com"
    assert result["backup_type"] == BackupType.PGBACKREST.value
    assert result["service_id"] is None
    assert result["host"] == "localhost"
    assert result["port"] == expected_port
    assert "logging_dir" not in result
