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

"""Test the one-of ``ArchivesCreate`` model's validation surface."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.sep.plugins.archives.constants import SwapDropEnum
from app.sep.plugins.archives.models import (
    ArchivesCreate,
    DestByTable,
    HostManual,
    SourceByQuery,
    SourceByTable,
)

_MANUAL_PORT = 3307
_SCHEMA_ID = 5
_TABLE_ID = 6


def _valid(**overrides: Any) -> dict[str, Any]:
    """Return a valid table->table create body, with overrides merged in."""
    body: dict[str, Any] = {
        "task_name": "arch",
        "hostname": "exec-host",
        "service_id": 1,
        "swap_drop": SwapDropEnum.PURGE_ONLY.value,
        "source": {"mode": "table", "source_db": "src_db", "source_table": "src_tbl"},
        "destination": {"mode": "table", "dest_table": "dst_tbl"},
        "where": "id < 100",
    }
    body.update(overrides)
    return body


class TestArchivesCreateBranches:
    """Cover the source / destination / host discriminated-union branches."""

    def test_valid_table_to_table(self) -> None:
        """Accept a table source with a table destination."""
        form = ArchivesCreate.model_validate(_valid())
        assert isinstance(form.source, SourceByTable)
        assert isinstance(form.destination, DestByTable)
        assert form.host is None

    def test_source_query_branch(self) -> None:
        """Accept a query source branch."""
        form = ArchivesCreate.model_validate(
            _valid(source={"mode": "query", "source_query": "SELECT 1"})
        )
        assert isinstance(form.source, SourceByQuery)
        assert form.source.source_query == "SELECT 1"

    def test_host_manual_branch(self) -> None:
        """Accept a manual destination-host branch with a port."""
        form = ArchivesCreate.model_validate(
            _valid(
                host={
                    "mode": "manual",
                    "dest_host": "remote",
                    "dest_port": _MANUAL_PORT,
                }
            )
        )
        assert isinstance(form.host, HostManual)
        assert form.host.dest_port == _MANUAL_PORT

    def test_free_solo_accepts_int_and_str(self) -> None:
        """Accept both an inventory id (int) and a free-typed name (str)."""
        by_id = ArchivesCreate.model_validate(
            _valid(
                source={
                    "mode": "table",
                    "source_db": _SCHEMA_ID,
                    "source_table": _TABLE_ID,
                }
            )
        )
        assert by_id.source.source_db == _SCHEMA_ID
        by_name = ArchivesCreate.model_validate(_valid())
        assert by_name.source.source_db == "src_db"


class TestArchivesCreateRules:
    """Cover the conditional rules ported onto the one-of model."""

    def test_swap_drop_non_purge_rejected(self) -> None:
        """Reject any archive type other than Purge Only."""
        with pytest.raises(ValidationError, match="Purge Only"):
            ArchivesCreate.model_validate(
                _valid(swap_drop=SwapDropEnum.SWAP_DROP.value)
            )

    def test_destination_required_without_delete_data(self) -> None:
        """Reject an archiving run with no destination."""
        body = _valid()
        del body["destination"]
        with pytest.raises(ValidationError, match="destination"):
            ArchivesCreate.model_validate(body)

    def test_delete_data_forbids_destination(self) -> None:
        """Reject a destination when deleting without archiving."""
        with pytest.raises(ValidationError, match="destination cannot be set"):
            ArchivesCreate.model_validate(_valid(delete_data=True))

    def test_delete_data_allows_no_destination(self) -> None:
        """Accept a delete-only run with no destination."""
        body = _valid(delete_data=True)
        del body["destination"]
        form = ArchivesCreate.model_validate(body)
        assert form.destination is None
        assert form.delete_data is True

    def test_where_required_for_purge(self) -> None:
        """Require a WHERE clause for a Purge Only run."""
        body = _valid()
        del body["where"]
        with pytest.raises(ValidationError):
            ArchivesCreate.model_validate(body)


class TestArchivesCreateDsnDelimiters:
    """Cover the DSN-delimiter validators on the manual host and destination db."""

    @pytest.mark.parametrize("bad", ["a,b", "a=b"])
    def test_dest_host_rejects_delimiters(self, bad: str) -> None:
        """Reject DSN delimiters in a manual destination host."""
        with pytest.raises(ValidationError, match="DSN delimiters"):
            ArchivesCreate.model_validate(
                _valid(host={"mode": "manual", "dest_host": bad})
            )

    @pytest.mark.parametrize("bad", ["a,b", "a=b"])
    def test_dest_db_rejects_delimiters(self, bad: str) -> None:
        """Reject DSN delimiters in a free-typed destination schema name."""
        with pytest.raises(ValidationError, match="DSN delimiters"):
            ArchivesCreate.model_validate(
                _valid(destination={"mode": "table", "dest_table": "t", "dest_db": bad})
            )

    @pytest.mark.parametrize("port", [0, 70000])
    def test_dest_port_range(self, port: int) -> None:
        """Reject an out-of-range manual destination port."""
        with pytest.raises(ValidationError):
            ArchivesCreate.model_validate(
                _valid(
                    host={"mode": "manual", "dest_host": "remote", "dest_port": port}
                )
            )
