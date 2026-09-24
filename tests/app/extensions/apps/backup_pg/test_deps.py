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

"""Define tests for the app.extensions.apps.backup_pg.deps and spec modules."""

from unittest.mock import AsyncMock

import pytest
import yaml

from app.core.exceptions import HTTPUnprocessableEntityException
from app.core.utils.path import resolve_payload_reference
from app.extensions.apps.backup_pg.deps import (
    build_backup_pg_api_detail_response,
    build_backup_pg_api_task_response,
    check_create_has_no_conflicted_running_tasks,
    parse_backup_task_data,
)
from app.extensions.apps.backup_pg.models import BackupPgForm, BackupType
from app.extensions.apps.backup_pg.spec import build_backup_pg_spec
from app.extensions.apps.framework.spec import ResolvedEntities
from app.extensions.connectivity import CONNECTIVITY_META_PORT_KEY
from app.extensions.inventory import CreatedService
from app.inventory.models import ServiceTypeEnum
from app.tasks.models import Task
from tests.app.extensions.path_unsafe_task_names import PATH_UNSAFE_TASKS
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedServiceFactory,
    MOCK_ACTOR_USERNAMES,
    MOCK_CREATOR_ID,
    MOCK_UPDATER_ID,
    TaskFactory,
)


def _resolved(service: CreatedService) -> ResolvedEntities:
    """Wrap ``service`` in the resolved-entities the spec builder reads."""
    return ResolvedEntities(
        service=service,
        entities={"service_id": service},
        executor_host="executor-host",
    )


def _backup_pg_task() -> Task:
    """Build a backup_pg task whose config names one pgBackRest server."""
    config = yaml.dump(
        {
            "SERVER_LIST": [
                {
                    "HOST": "db.internal",
                    "PORT": 5433,
                    "BACKUP_TYPE": BackupType.PGBACKREST.value,
                }
            ]
        }
    )
    return TaskFactory.build(
        name="pg-backup",
        owner="BACKUP_PG",
        data={"meta": {"target": "pg-host", "config": config}},
        created_by=MOCK_CREATOR_ID,
        last_updated_by=MOCK_UPDATER_ID,
    )


def _form(service_id: int, **overrides: object) -> BackupPgForm:
    """Build a backup_pg create form for the spec-builder tests."""
    return BackupPgForm(
        task_name="test_task",
        hostname="executor-host",
        service_id=service_id,
        stanza=overrides.pop("stanza", "extensions-test"),
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
    assert spec.payload == "file://app/extensions/apps/backup_pg/payload"
    assert resolve_payload_reference(spec.payload).is_file()

    cfg = yaml.safe_load(spec.config)
    server_config = cfg["SERVER_LIST"][0]
    assert server_config["ALIAS"] == "extensions-test"
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


class TestBuildBackupPgApiTaskResponse:
    """Cover the backup_pg list-row builder's actor resolution."""

    def test_resolves_actors_through_the_context(self):
        """Render both actors as usernames and keep the app's own extras."""
        response = build_backup_pg_api_task_response(
            _backup_pg_task(), context=MOCK_ACTOR_USERNAMES
        )

        assert (response.created_by, response.last_updated_by) == ("alice", "bob")
        assert (response.hostname, response.backup_type) == (
            "pg-host",
            BackupType.PGBACKREST.value,
        )

    def test_keeps_raw_ids_without_a_context(self):
        """Serve the stored identifiers when no username map is bound."""
        response = build_backup_pg_api_task_response(_backup_pg_task())

        assert (response.created_by, response.last_updated_by) == (
            MOCK_CREATOR_ID,
            MOCK_UPDATER_ID,
        )


def test_detail_builder_forwards_the_context_to_the_task_builder():
    """Resolve actors on the detail response the derived detail and create serve."""
    response = build_backup_pg_api_detail_response(
        _backup_pg_task(), context=MOCK_ACTOR_USERNAMES
    )

    assert (response.created_by, response.last_updated_by) == ("alice", "bob")
    assert response.host == "db.internal"


class TestCheckCreateHasNoConflictedRunningTasks:
    """Test the create guard's handling of the body-supplied task name."""

    @staticmethod
    def _request(payload: object) -> AsyncMock:
        """Build a request stub whose JSON body is ``payload``."""
        request = AsyncMock()
        request.json = AsyncMock(return_value=payload)
        return request

    @pytest.mark.asyncio
    @pytest.mark.parametrize("task_name", PATH_UNSAFE_TASKS)
    async def test_refuses_a_name_that_is_not_one_path_segment(
        self, task_name: str
    ) -> None:
        """Refuse a body-supplied name before the history lookups are composed.

        A body value is the one shape that can carry a literal ``/``, which a
        path parameter's ``[^/]+`` convertor cannot deliver.
        """
        tasks_api = AsyncMock()

        with pytest.raises(HTTPUnprocessableEntityException):
            await check_create_has_no_conflicted_running_tasks(
                self._request({"task_name": task_name}), tasks_api
            )

        tasks_api.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_safe_name_reaches_both_history_lookups(self) -> None:
        """Query RUNNING then PENDING history for a plain name."""
        tasks_api = AsyncMock()
        tasks_api.get = AsyncMock(return_value={"items": []})

        await check_create_has_no_conflicted_running_tasks(
            self._request({"task_name": "backup-task"}), tasks_api
        )

        assert [call.args[0] for call in tasks_api.get.await_args_list] == [
            "/backup-task/history/",
            "/backup-task/history/",
        ]
