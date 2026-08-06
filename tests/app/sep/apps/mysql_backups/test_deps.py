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

"""Define tests for the app.sep.apps.mysql_backups.deps module."""

from typing import Any

import pytest
import yaml

from app.core.utils.path import resolve_payload_reference
from app.sep.apps.mysql_backups.deps import (
    _extract_backup_type_from_task,
    build_backup_task_payload,
    build_mysql_backups_api_task_response,
    get_backups_task_info,
    parse_backup_task_data,
)
from app.sep.apps.mysql_backups.forms import BackupCreate, UploadProvider
from app.sep.apps.mysql_backups.models import BackupType, extract_backup_type_marker
from app.sep.apps.mysql_backups.recorder import RUN_RESULT_RECORDER
from app.sep.inventory import CreatedNode, CreatedService
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskWrite,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "backup_type",
        "expected_payload_filename",
        "expected_requirements",
        "expected_host",
    ),
    [
        (
            BackupType.MYDUMPER,
            "mydumper_payload",
            "packaging\nPyYAML\nPyMySQL[rsa,ed25519]\nboto3\nfilelock",
            "fake-address",
        ),
        (
            BackupType.XTRABACKUP,
            # The form selects S3 + Rsync, so the dispatch carries the variant with
            # those two providers and omits the Google Cloud Storage one.
            "xtrabackup_rsync_s3_payload",
            "packaging\nPyYAML\nPyMySQL[rsa,ed25519]\nboto3\nfilelock",
            "localhost",
        ),
        (
            BackupType.BINLOG,
            "binlog_payload",
            "packaging\nPyYAML\nPyMySQL[rsa,ed25519]\nboto3",
            "10.0.0.5",
        ),
    ],
)
async def test_build_backup_task_payload(
    backup_type: BackupType,
    expected_payload_filename,
    expected_requirements,
    expected_host,
    faker,
    mocker,
    mock_remote_api,
    created_service: CreatedService,
):
    """Test build_backup_task_payload.

    Test that build_backup_task_payload generates the correct TaskWrite
    depending on the backup_type, encryption, and other fields.
    """
    mocker.patch(
        "app.sep.apps.framework.spec.get_created_entity",
        return_value=created_service,
    )
    created_service.node = CreatedNode(
        id=1,
        address="fake-address",
        node_name="fake-node",
    )

    form_data = {
        "service_id": created_service.id,
        "task_name": "test_task",
        "backup_type": backup_type,
        "hostname": "test_host",
        "upload": [UploadProvider.S3, UploadProvider.RSYNC],
        "s3_bucket": "my-test-bucket",
        "rsync_path": "/rsync",
        "encrypt": True,
        "encryption_recipient": faker.email(),
    }
    if backup_type == BackupType.BINLOG:
        form_data["binlog_alternative_host"] = "10.0.0.5"
    backup_create = BackupCreate(**form_data)

    task_payload = await build_backup_task_payload(backup_create, mock_remote_api)

    assert isinstance(task_payload, TaskWrite)
    assert task_payload.name == form_data["task_name"]
    assert task_payload.backend == TaskBackendEnum.PROXY
    assert task_payload.owner == "BACKUPS"
    # A form-built task must carry the recorder so its completed runs are
    # catalogued, exactly as the model-first JSON create path does.
    assert task_payload.run_result_recorder == RUN_RESULT_RECORDER

    data = task_payload.data
    assert data["task"] == "run-python"
    assert (
        data["payload"]
        == f"file://app/sep/apps/mysql_backups/{expected_payload_filename}"
    )
    assert resolve_payload_reference(data["payload"]).is_file()

    meta = data["meta"]
    assert meta["target"] == form_data["hostname"]
    assert meta["requirements"] == expected_requirements
    assert meta["_service_name"] == created_service.name

    cfg = yaml.safe_load(meta["config"])
    server_list = cfg["SERVER_LIST"]
    assert len(server_list) == 1
    server_config = server_list[0]

    assert server_config["HOST"] == expected_host
    assert server_config["BACKUP_TYPE"] == backup_type.value

    if backup_type == BackupType.BINLOG:
        assert cfg["ALL_SERVERS"]["BINLOG_ALTERNATIVE_HOST"] == "10.0.0.5"
    else:
        assert "BINLOG_ALTERNATIVE_HOST" not in cfg["ALL_SERVERS"]

    assert "s3" in server_config["UPLOAD"]
    assert "rsync" in server_config["UPLOAD"]

    assert data["payload"].startswith("file://")
    assert expected_payload_filename in data["payload"]


@pytest.mark.asyncio
async def test_build_backup_task_payload_raises_for_invalid_backup_type(
    faker, mocker, created_service, mock_remote_api
):
    """Test that passing an invalid BackupType raises ValueError."""
    mocker.patch(
        "app.sep.apps.framework.spec.get_created_entity",
        return_value=created_service,
    )

    backup_create = BackupCreate.model_construct(
        service_id=created_service.id,
        task_name="test_task",
        hostname="test_host",
        backup_type="invalid",
        upload=[UploadProvider.S3],
        s3_bucket="bkt",
    )

    with pytest.raises(ValueError, match="Invalid Backup Type"):
        await build_backup_task_payload(backup_create, mock_remote_api)


def test_get_backups_task_info():
    """Test extracting the correct fields from a task dictionary."""
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
                                "UPLOAD": ["S3", "RSYNC"],
                                "BACKUP_TYPE": "X",
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
    assert result["upload"] == "S3, RSYNC"
    assert result["backup_type"] == BackupType.XTRABACKUP.name


@pytest.mark.parametrize(
    ("all_servers", "expected_alt_host"),
    [
        (
            {
                "BINLOG_ALTERNATIVE_HOST": "10.0.0.5",
                "BINLOG_PREFIX": "binlog",
            },
            "10.0.0.5",
        ),
        (
            {"BINLOG_PREFIX": "binlog"},
            None,
        ),
    ],
)
def test_parse_backup_task_data(
    all_servers: dict[str, Any], expected_alt_host: str | None
):
    """Round-trip the binlog alt host from persisted YAML on the edit form path."""
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "ALIAS": "db1-mysql",
                                "HOST": "10.0.0.5",
                                "PORT": 3306,
                                "BACKUP_TYPE": BackupType.BINLOG.value,
                                "UPLOAD": ["gsutil"],
                            }
                        ],
                        "ALL_SERVERS": all_servers,
                    }
                ),
            }
        },
    }

    result = parse_backup_task_data(fake_task_dict)

    assert result["name"] == "test_task"
    assert result["hostname"] == "host.example.com"
    assert result["backup_type"] == BackupType.BINLOG.value
    assert result["service_id"] is None
    assert result["host"] == "10.0.0.5"
    assert result["binlog_alternative_host"] == expected_alt_host


class TestParseBackupTaskDataXtrabackupQuiet:
    """Tests for XTRABACKUP_QUIET round-trip through ``parse_backup_task_data``."""

    def _make_task_dict(self, all_servers: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": "test_task",
            "data": {
                "meta": {
                    "target": "host.example.com",
                    "config": yaml.dump(
                        {
                            "SERVER_LIST": [
                                {
                                    "ALIAS": "db1-mysql",
                                    "HOST": "10.0.0.5",
                                    "PORT": 3306,
                                    "BACKUP_TYPE": BackupType.XTRABACKUP.value,
                                }
                            ],
                            "ALL_SERVERS": all_servers,
                        }
                    ),
                }
            },
        }

    @pytest.mark.parametrize(
        ("all_servers", "expected"),
        [
            ({"XTRABACKUP_QUIET": True}, True),
            ({"XTRABACKUP_QUIET": False}, False),
            # Absent key: legacy tasks pre-date the field; form must render unchecked.
            ({}, None),
            # YAML null value behaves identically to absent key.
            ({"XTRABACKUP_QUIET": None}, None),
        ],
    )
    def test_xtrabackup_quiet_round_trips(
        self, all_servers: dict[str, Any], expected: bool | None
    ):
        """XTRABACKUP_QUIET round-trips from persisted YAML to the edit-form dict."""
        result = parse_backup_task_data(self._make_task_dict(all_servers))
        assert result["xtrabackup_quiet"] == expected

    def test_missing_all_servers_section_returns_none(self):
        """Return ``None`` for ``xtrabackup_quiet`` when ``ALL_SERVERS`` is absent.

        Guards the legacy-task path where the config YAML pre-dates the
        ``ALL_SERVERS`` section entirely.
        """
        task_dict = {
            "name": "legacy_task",
            "data": {
                "meta": {
                    "target": "host.example.com",
                    "config": yaml.dump(
                        {
                            "SERVER_LIST": [
                                {
                                    "ALIAS": "db1",
                                    "HOST": "10.0.0.5",
                                    "PORT": 3306,
                                    "BACKUP_TYPE": BackupType.XTRABACKUP.value,
                                }
                            ]
                        }
                    ),
                }
            },
        }
        result = parse_backup_task_data(task_dict)
        assert result["xtrabackup_quiet"] is None

    def test_other_fields_are_unaffected(self):
        """Adding xtrabackup_quiet must not clobber adjacent fields in the result."""
        result = parse_backup_task_data(
            self._make_task_dict({"XTRABACKUP_QUIET": True, "BINLOG_PREFIX": "bp"})
        )
        assert result["xtrabackup_quiet"] is True
        assert result["binlog_prefix"] == "bp"


class TestParseBackupTaskDataUploadQuiet:
    """Tests for UPLOAD_QUIET round-trip through ``parse_backup_task_data``."""

    def _make_task_dict(self, all_servers: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": "test_task",
            "data": {
                "meta": {
                    "target": "host.example.com",
                    "config": yaml.dump(
                        {
                            "SERVER_LIST": [
                                {
                                    "ALIAS": "db1",
                                    "HOST": "10.0.0.1",
                                    "PORT": 3306,
                                    "BACKUP_TYPE": BackupType.XTRABACKUP.value,
                                    "UPLOAD": ["s3"],
                                }
                            ],
                            "ALL_SERVERS": all_servers,
                        }
                    ),
                }
            },
        }

    @pytest.mark.parametrize(
        ("all_servers", "expected"),
        [
            ({"UPLOAD_QUIET": True}, True),
            ({"UPLOAD_QUIET": False}, False),
            # Absent key: legacy tasks pre-date the field; form must render unchecked.
            ({}, None),
            # YAML null value behaves identically to absent key.
            ({"UPLOAD_QUIET": None}, None),
        ],
    )
    def test_upload_quiet_round_trips(
        self, all_servers: dict[str, Any], expected: bool | None
    ):
        """UPLOAD_QUIET round-trips from persisted YAML to the edit-form dict."""
        result = parse_backup_task_data(self._make_task_dict(all_servers))
        assert result["upload_quiet"] == expected

    def test_missing_all_servers_section_returns_none(self):
        """Return ``None`` for ``upload_quiet`` when ``ALL_SERVERS`` is absent.

        Guards the legacy-task path where the config YAML pre-dates the
        ``ALL_SERVERS`` section entirely.
        """
        task_dict = {
            "name": "legacy_task",
            "data": {
                "meta": {
                    "target": "host.example.com",
                    "config": yaml.dump(
                        {
                            "SERVER_LIST": [
                                {
                                    "ALIAS": "db1",
                                    "HOST": "10.0.0.1",
                                    "PORT": 3306,
                                    "BACKUP_TYPE": BackupType.XTRABACKUP.value,
                                    "UPLOAD": ["s3"],
                                }
                            ]
                        }
                    ),
                }
            },
        }
        result = parse_backup_task_data(task_dict)
        assert result["upload_quiet"] is None

    def test_other_fields_are_unaffected(self):
        """Adding upload_quiet must not clobber adjacent fields in the result."""
        result = parse_backup_task_data(
            self._make_task_dict({"UPLOAD_QUIET": True, "BINLOG_PREFIX": "bp"})
        )
        assert result["upload_quiet"] is True
        assert result["binlog_prefix"] == "bp"


@pytest.mark.parametrize(
    ("all_servers", "expected"),
    [
        ({"UPLOAD_QUIET": True}, True),
        ({"UPLOAD_QUIET": False}, False),
        ({}, None),
    ],
)
def test_parse_backup_task_data_upload_quiet(
    all_servers: dict, expected: bool | None
) -> None:
    """Round-trip upload_quiet from persisted YAML on the edit form path."""
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "ALIAS": "db1",
                                "HOST": "10.0.0.1",
                                "PORT": 3306,
                                "BACKUP_TYPE": BackupType.XTRABACKUP.value,
                                "UPLOAD": ["s3"],
                            }
                        ],
                        "ALL_SERVERS": all_servers,
                    }
                ),
            }
        },
    }

    result = parse_backup_task_data(fake_task_dict)

    assert result["upload_quiet"] == expected


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
    all_servers: dict[str, Any],
    expected_result: dict[str, Any],
):
    """Round-trip S3/GSUTIL/RSYNC storage-target keys from persisted YAML on the edit form path."""
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "ALIAS": "db1-mysql",
                                "HOST": "10.0.0.5",
                                "PORT": 3306,
                                "BACKUP_TYPE": BackupType.XTRABACKUP.value,
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
    """parse_backup_task_data handles a YAML config with no ALL_SERVERS block."""
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "ALIAS": "db1-mysql",
                                "HOST": "10.0.0.5",
                                "PORT": 3306,
                                "BACKUP_TYPE": BackupType.BINLOG.value,
                                "UPLOAD": ["gsutil"],
                            }
                        ],
                    }
                ),
            }
        },
    }

    result = parse_backup_task_data(fake_task_dict)

    assert result["name"] == "test_task"
    assert result["hostname"] == "host.example.com"
    assert result["host"] == "10.0.0.5"
    assert result["binlog_alternative_host"] is None


@pytest.mark.parametrize(
    ("all_servers", "expected_verbose"),
    [
        ({"MYDUMPER_VERBOSE": 1}, 1),
        ({"MYDUMPER_EXTRA_ARGS": "--foo"}, None),
        ({"MYDUMPER_VERBOSE": 0}, 0),
    ],
)
def test_parse_backup_task_data_mydumper_verbose(
    all_servers: dict[str, Any], expected_verbose: int | None
):
    """Round-trip the mydumper verbose level from persisted YAML on the edit form path.

    The ``0`` (silent) case guards against a falsy-value bug: a non-empty
    ``"0"`` must survive rather than collapse to "unset"/default. The
    no-key case asserts legacy tasks pre-populate the form empty (``None``)
    rather than omitting the field entirely.
    """
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "ALIAS": "db1-mysql",
                                "HOST": "10.0.0.5",
                                "PORT": 3306,
                                "BACKUP_TYPE": BackupType.MYDUMPER.value,
                                "UPLOAD": ["gsutil"],
                            }
                        ],
                        "ALL_SERVERS": all_servers,
                    }
                ),
            }
        },
    }

    result = parse_backup_task_data(fake_task_dict)

    assert result["mydumper_verbose"] == expected_verbose


def _task_with_raw_config(raw_config: str) -> Task:
    """Build a minimal Task whose YAML config is the given raw string."""
    return Task(
        name="t",
        owner="BACKUPS",
        data={"meta": {"config": raw_config}},
    )


@pytest.mark.parametrize(
    "raw_config",
    [
        "- just\n- a\n- list\n",
        "scalar",
        "SERVER_LIST: not-a-list\n",
        "SERVER_LIST:\n  - just-a-string\n",
        "SERVER_LIST: []\n",
        ": invalid : yaml :",
    ],
)
def test_extract_backup_type_handles_non_dict_yaml(raw_config: str):
    """Malformed/non-dict YAML must return ``None`` instead of raising."""
    assert _extract_backup_type_from_task(_task_with_raw_config(raw_config)) is None


class TestExtractBackupTypeMarkerShapeGuards:
    """Guard ``extract_backup_type_marker`` against non-string/missing shapes.

    ``meta.config`` is expected to be a YAML string, but the value is untrusted
    task data. Before the structural-match rewrite, a non-string ``config``
    (e.g. a dict) reached ``yaml.safe_load`` directly and raised
    ``AttributeError`` uncaught by the ``except yaml.YAMLError`` guard. These
    lock in the ``None``-not-raise contract for every shape short of a string.
    """

    def test_none_task_data_returns_none(self):
        """Return ``None`` for a task with no ``data`` at all."""
        assert extract_backup_type_marker(None) is None

    def test_missing_meta_key_returns_none(self):
        """Return ``None`` when ``data`` carries no ``meta`` key."""
        assert extract_backup_type_marker({}) is None

    def test_non_dict_meta_returns_none(self):
        """Return ``None`` when ``meta`` itself is not a mapping."""
        assert extract_backup_type_marker({"meta": "not-a-dict"}) is None

    def test_dict_valued_config_returns_none_without_raising(self):
        """Return ``None``, not raise, when ``config`` is a dict instead of YAML text.

        This is the exact shape that used to reach ``yaml.safe_load`` and raise
        ``AttributeError: 'dict' object has no attribute 'read'``.
        """
        task_data = {"meta": {"config": {"SERVER_LIST": [{"BACKUP_TYPE": "M"}]}}}
        assert extract_backup_type_marker(task_data) is None

    def test_non_string_backup_type_marker_returns_none(self):
        """Return ``None`` when ``BACKUP_TYPE`` itself is not a string."""
        task_data = {
            "meta": {"config": yaml.dump({"SERVER_LIST": [{"BACKUP_TYPE": 1}]})}
        }
        assert extract_backup_type_marker(task_data) is None


def _make_backup_task(
    created_by: str | None = None, last_updated_by: str | None = None
) -> Task:
    """Build a minimal backups Task carrying the given user ids."""
    return Task(
        name="backup-task",
        owner="BACKUPS",
        data={"meta": {"target": "host1", "config": ""}},
        created_by=created_by,
        last_updated_by=last_updated_by,
    )


class TestBuildMysqlBackupsApiTaskResponse:
    """Tests for build_mysql_backups_api_task_response username mapping."""

    def test_created_by_resolved_to_username_when_mapping_provided(self):
        """created_by is resolved when the mapping contains the id."""
        task = _make_backup_task(created_by="uid-abc")

        result = build_mysql_backups_api_task_response(
            task, context={"uid-abc": "Alice"}
        )

        assert result.created_by == "Alice"

    def test_created_by_falls_back_to_raw_id_when_not_in_mapping(self):
        """created_by is preserved when the id is not in the mapping."""
        task = _make_backup_task(created_by="uid-unknown")

        result = build_mysql_backups_api_task_response(
            task, context={"uid-other": "Bob"}
        )

        assert result.created_by == "uid-unknown"

    def test_last_updated_by_resolved_via_mapping(self):
        """last_updated_by is also resolved via the mapping."""
        task = _make_backup_task(last_updated_by="uid-xyz")

        result = build_mysql_backups_api_task_response(
            task, context={"uid-xyz": "Carol"}
        )

        assert result.last_updated_by == "Carol"

    def test_context_none_preserves_raw_ids(self):
        """Raw ids are unchanged when no context is bound."""
        task = _make_backup_task(created_by="uid-123", last_updated_by="uid-456")

        result = build_mysql_backups_api_task_response(task)

        assert result.created_by == "uid-123"
        assert result.last_updated_by == "uid-456"
