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

import pytest
import yaml

from app.core.exceptions import HTTPUnprocessableEntityException
from app.sep.plugins.archives.constants import SwapDropEnum
from app.sep.plugins.archives.deps import (
    _map_legacy_to_create,
    ArchivesLegacyForm,
    get_archives_task_info,
)
from app.sep.plugins.archives.models import (
    DestByTable,
    SourceByQuery,
    SourceByTable,
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


class TestMapLegacyToCreate:
    """Cover folding the flat Jinja form into the one-of ``ArchivesCreate``."""

    def test_table_path_collapses_ids(self) -> None:
        """Map the flat id/name pairs into the collapsed free-solo fields."""
        create = _map_legacy_to_create(_legacy())
        assert isinstance(create.source, SourceByTable)
        assert create.source.source_db == _SRC_DB_ID
        assert create.source.source_table == _SRC_TBL_ID
        assert isinstance(create.destination, DestByTable)
        assert create.destination.dest_table == _DEST_TBL_ID
        assert create.task_name == "arch"

    def test_table_path_prefers_manual_names(self) -> None:
        """Use the manual name when no id is supplied."""
        create = _map_legacy_to_create(
            _legacy(
                source_db_id="",
                source_db_name="mydb",
                source_table_id="",
                source_table_name="mytbl",
            )
        )
        assert create.source.source_db == "mydb"
        assert create.source.source_table == "mytbl"

    def test_query_path(self) -> None:
        """Map a source query into the query branch."""
        create = _map_legacy_to_create(
            _legacy(source_db_id="", source_table_id="", source_query="SELECT 1")
        )
        assert isinstance(create.source, SourceByQuery)
        assert create.source.source_query == "SELECT 1"

    def test_invalid_swap_drop_raises_422(self) -> None:
        """Surface a folded-model validation failure as a 422."""
        with pytest.raises(HTTPUnprocessableEntityException):
            _map_legacy_to_create(_legacy(swap_drop=SwapDropEnum.SWAP_DROP.value))


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
