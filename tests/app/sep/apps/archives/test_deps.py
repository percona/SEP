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

"""Test the hand-written parts of the archives ``deps`` module.

The model-first create / update / list / detail surfaces are covered by
``test_api`` and ``test_payload_snapshot``; this file covers the legacy
flat-form → one-of mapping and the Jinja index's task-info extraction.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
import yaml

from app.core.exceptions import HTTPUnprocessableEntityException
from app.core.requests.remote_api import RemoteAPI
from app.core.utils.path import resolve_payload_reference
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.archives.constants import SwapDropEnum
from app.sep.apps.archives.deps import (
    ArchivesLegacyForm,
    build_archives_task_payload,
    get_archives_task_info,
)
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
)

_SRC_DB_ID = 10
_SRC_TBL_ID = 20
_DEST_TBL_ID = 30


def _legacy(**overrides: Any) -> ArchivesLegacyForm:
    """Build a flat legacy form with a table source + table destination."""
    body: dict[str, Any] = {
        "alias": "arch",
        "hostname": "exec-host",
        "service_id": 1,
        "source_db_id": _SRC_DB_ID,
        "source_table_id": _SRC_TBL_ID,
        "dest_table_id": _DEST_TBL_ID,
        "swap_drop": SwapDropEnum.PURGE_ONLY.value,
        "where": "id < 100",
    }
    body.update(overrides)
    return ArchivesLegacyForm.model_validate(body)


def _fake_inventory() -> AsyncMock:
    """Return an inventory mock resolving the seeded source/dest ids by path."""
    routes = {
        "/services/1": CreatedServiceFactory.build(
            id=1,
            node=CreatedNodeFactory.build(address="src-host", name="src-node"),
            type=ServiceTypeEnum.MYSQL,
            name="src-svc",
            port=3306,
        ).model_dump(mode="json"),
        f"/schemas/{_SRC_DB_ID}": CreatedSchemaFactory.build(
            id=_SRC_DB_ID, name="src_db"
        ).model_dump(mode="json"),
        f"/tables/{_SRC_TBL_ID}": CreatedTableFactory.build(
            id=_SRC_TBL_ID, name="src_tbl"
        ).model_dump(mode="json"),
        f"/tables/{_DEST_TBL_ID}": CreatedTableFactory.build(
            id=_DEST_TBL_ID, name="dst_tbl"
        ).model_dump(mode="json"),
    }
    api = AsyncMock(spec=RemoteAPI)

    async def _get(path: str, params: dict | None = None) -> dict:
        return routes[path]

    api.get.side_effect = _get
    return api


def _purge_item(task: Any) -> dict[str, Any]:
    """Return the single PURGE_LIST item from a built task's config."""
    return yaml.safe_load(task.data["meta"]["config"])["PURGE_LIST"][0]


class TestLegacyFormPayload:
    """Cover the flat Jinja form folded into the one-of model via the public dep."""

    @pytest.mark.asyncio
    async def test_table_path_collapses_ids(self) -> None:
        """Assert the flat id/name pairs collapse into the resolved config names."""
        task = await build_archives_task_payload(_legacy(), _fake_inventory())
        item = _purge_item(task)
        assert item["SOURCE_DB"] == "src_db"
        assert item["SOURCE_TABLE"] == "src_tbl"
        assert item["DEST_TABLE"] == "dst_tbl"
        assert task.name == "arch"
        assert task.data["payload"] == "file://app/sep/apps/archives/payload"
        assert resolve_payload_reference(task.data["payload"]).is_file()

    @pytest.mark.asyncio
    async def test_manual_names(self) -> None:
        """Assert the free-typed names are used when no inventory id is supplied."""
        task = await build_archives_task_payload(
            _legacy(
                source_db_id="",
                source_db_name="mydb",
                source_table_id="",
                source_table_name="mytbl",
            ),
            _fake_inventory(),
        )
        item = _purge_item(task)
        assert item["SOURCE_DB"] == "mydb"
        assert item["SOURCE_TABLE"] == "mytbl"

    @pytest.mark.asyncio
    async def test_query_path(self) -> None:
        """Assert a source query folds into the query branch."""
        task = await build_archives_task_payload(
            _legacy(source_db_id="", source_table_id="", source_query="SELECT 1"),
            _fake_inventory(),
        )
        item = _purge_item(task)
        assert item["SOURCE_QUERY"] == "SELECT 1"
        assert "SOURCE_DB" not in item

    @pytest.mark.asyncio
    async def test_invalid_swap_drop_raises_422(self) -> None:
        """Assert a folded-model validation failure surfaces as a 422."""
        with pytest.raises(HTTPUnprocessableEntityException):
            await build_archives_task_payload(
                _legacy(swap_drop=SwapDropEnum.SWAP_DROP.value), AsyncMock()
            )


class TestGetArchivesTaskInfo:
    """Cover the Jinja index's task-info extraction from a task's config."""

    @staticmethod
    def _task(
        purge_item: dict[str, Any], hostname: str = "mock_target"
    ) -> dict[str, Any]:
        """Build a minimal task dict carrying a one-item PURGE_LIST config."""
        return {
            "data": {
                "meta": {
                    "config": yaml.dump({"PURGE_LIST": [purge_item]}),
                    "target": hostname,
                }
            },
            "created_by": None,
            "last_updated_by": None,
        }

    def test_source_and_dest_table(self) -> None:
        """Extract the source and destination tables and the hostname."""
        result = get_archives_task_info(
            self._task(
                {"SOURCE_DB": "mydb", "SOURCE_TABLE": "src", "DEST_TABLE": "arch"}
            )
        )
        assert result["hostname"] == "mock_target"
        assert result["source_table"] == "mydb.src"
        assert result["dest_table"] == "mydb.arch"

    def test_source_query(self) -> None:
        """Extract a source query and omit the source table."""
        result = get_archives_task_info(self._task({"SOURCE_QUERY": "SELECT 1"}))
        assert result["source_query"] == "SELECT 1"
        assert "source_table" not in result

    def test_dest_file(self) -> None:
        """Extract a destination file path."""
        result = get_archives_task_info(
            self._task(
                {"SOURCE_DB": "d", "SOURCE_TABLE": "t", "DEST_FILE": "/tmp/a.csv"}
            )
        )
        assert result["dest_file"] == "/tmp/a.csv"

    def test_no_source_table(self) -> None:
        """Omit the source table when neither source db nor table is set."""
        result = get_archives_task_info(self._task({"ALIAS": "x", "SWAP_DROP": 0}))
        assert "source_table" not in result
