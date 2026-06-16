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

"""Define tests for the app.sep.models module."""

import pytest
from pydantic import ValidationError

from app.sep.models import AppLifecycleEnum, AppState, AppStateBase, AppStateWrite
from app.sep.plugins.archives.constants import SwapDropEnum
from app.sep.plugins.archives.models import ArchivesCreate


class TestAppStateModel:
    """Test suite for the AppState model and its companions."""

    def test_base_lifecycle_state_defaults_to_enabled(self):
        """The shared base column-default for ``lifecycle_state`` is ``ENABLED``."""
        assert (
            AppStateBase(app_key="snippets").lifecycle_state is AppLifecycleEnum.ENABLED
        )

    def test_base_requires_app_key(self):
        """``app_key`` has no default — omitting it fails validation."""
        with pytest.raises(ValidationError):
            AppStateBase()

    def test_base_rejects_empty_app_key(self):
        """``app_key`` is a ``NonEmptyStr`` — an empty string is rejected."""
        with pytest.raises(ValidationError):
            AppStateBase(app_key="")

    def test_table_model_lifecycle_state_defaults_to_enabled(self):
        """The table model inherits the ``lifecycle_state=ENABLED`` column default."""
        assert AppState(app_key="snippets").lifecycle_state is AppLifecycleEnum.ENABLED

    @pytest.mark.parametrize("state", list(AppLifecycleEnum))
    def test_enabled_computed_field_parity(self, state: AppLifecycleEnum) -> None:
        """``enabled`` is ``True`` only for the ``ENABLED`` lifecycle state."""
        row = AppState(app_key="snippets", lifecycle_state=state)
        assert row.enabled is (state == AppLifecycleEnum.ENABLED)

    def test_enabled_appears_in_model_dump(self):
        """The derived ``enabled`` flag is serialized alongside ``lifecycle_state``."""
        dumped = AppState(
            app_key="snippets", lifecycle_state=AppLifecycleEnum.DISABLING
        ).model_dump()
        assert dumped["lifecycle_state"] is AppLifecycleEnum.DISABLING
        assert dumped["enabled"] is False

    def test_write_model_requires_lifecycle_state(self):
        """The write payload requires ``lifecycle_state`` — it has no default."""
        with pytest.raises(ValidationError):
            AppStateWrite()

    def test_write_model_rejects_unknown_lifecycle_state(self):
        """The write payload rejects a value outside ``AppLifecycleEnum``."""
        with pytest.raises(ValidationError):
            AppStateWrite(lifecycle_state="BOGUS")


class TestArchivesCreateModel:
    """Test suite for ArchivesCreate model validation."""

    def test_archive_table_to_another(self):
        """Test archiving from one table to another with a WHERE condition."""
        dest_table_id = 30
        instance = ArchivesCreate(
            alias="archive_table_to_another",
            hostname="source_db",
            service_id=1,
            source_db_id=10,
            source_table_id=20,
            dest_table_id=dest_table_id,
            where="date < CURDATE() - INTERVAL 6 MONTH",
            swap_drop=SwapDropEnum.PURGE_ONLY,
        )
        assert instance.alias == "archive_table_to_another"
        assert instance.dest_table_id == dest_table_id

    def test_archive_table_to_file(self):
        """Test archiving from a table to a file with a WHERE condition."""
        instance = ArchivesCreate(
            alias="archive_table_to_file",
            hostname="source_db",
            service_id=1,
            source_db_id=10,
            source_table_id=20,
            dest_file="/var/log/archive/%Y-%m-%d-%D.%t",
            where="date < CURDATE() - INTERVAL 6 MONTH",
            swap_drop=SwapDropEnum.PURGE_ONLY,
        )
        assert instance.alias == "archive_table_to_file"
        assert instance.dest_file == "/var/log/archive/%Y-%m-%d-%D.%t"

    def test_purge_rows(self):
        """Test purging rows with DELETE_DATA set."""
        instance = ArchivesCreate(
            alias="purge_rows",
            hostname="source_db",
            service_id=1,
            source_db_id=10,
            source_table_id=20,
            use_index="created_date",
            where="date < CURDATE() - INTERVAL 6 MONTH",
            delete_data=1,
            swap_drop=SwapDropEnum.PURGE_ONLY,
        )
        assert instance.alias == "purge_rows"
        assert instance.delete_data == 1

    def test_drop_swap(self):
        """Test swap and drop with swap_drop set to 1."""
        instance = ArchivesCreate(
            alias="drop_swap",
            hostname="source_db",
            service_id=1,
            source_db_id=10,
            source_table_id=20,
            swap_drop=SwapDropEnum.SWAP_DROP,
        )
        assert instance.alias == "drop_swap"
        assert instance.swap_drop == 1

    def test_dynamic_tables_sources(self):
        """Test archiving with a dynamic source query and destination file."""
        instance = ArchivesCreate(
            alias="dynamic_tables_sources",
            hostname="source_db",
            service_id=1,
            source_query="SELECT ...",
            where="date < CURDATE() - INTERVAL 6 MONTH",
            dest_file="/var/log/archive/%Y-%m-%d-%D.%t",
            swap_drop=SwapDropEnum.PURGE_ONLY,
        )
        assert instance.alias == "dynamic_tables_sources"
        assert instance.source_query == "SELECT ..."

    def test_validate_tables_are_different(self):
        """Test that source_table_id and dest_table_id cannot be the same."""
        with pytest.raises(
            ValidationError, match="Source and Destination tables cannot be the same."
        ):
            ArchivesCreate(
                alias="task-alias",
                hostname="example.com",
                service_id=123,
                source_db_id=1,
                source_table_id=2,
                dest_table_id=2,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 100",
            )

    def test_validate_dest_file_or_dest_table_id(self):
        """Test that dest_table_id and dest_file are mutually exclusive with swap_drop."""
        with pytest.raises(
            ValidationError,
            match="must not be set",
        ):
            ArchivesCreate(
                alias="task-alias",
                hostname="example.com",
                service_id=123,
                source_db_id=1,
                source_table_id=2,
                dest_file="/path/to/file",
                swap_drop=SwapDropEnum.SWAP_DROP,
            )

    def test_validate_dest_file_or_dest_table_id_required(self):
        """Test that either dest_table_id or dest_file must be set.

        When delete_data and swap_drop are not set.
        """
        with pytest.raises(
            ValidationError,
            match="At least one of dest_file or dest_table_id/dest_table_name must be set",
        ):
            ArchivesCreate(
                alias="task-alias",
                hostname="example.com",
                service_id=123,
                source_db_id=1,
                source_table_id=2,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 100",
            )

    def test_validate_swp_table_suffix_required_with_swap_archive_drop(self):
        """Test that swp_table_suffix is required.

        When swap_drop is set to SWAP_ARCHIVE_DROP.
        """
        with pytest.raises(ValidationError, match="'swp_table_suffix' is required"):
            ArchivesCreate(
                alias="task-alias",
                hostname="example.com",
                service_id=123,
                source_db_id=1,
                source_table_id=2,
                dest_table_id=3,
                swap_drop=SwapDropEnum.SWAP_ARCHIVE_DROP,
                where="id > 100",
            )

    def test_validate_source_query_exclusivity(self):
        """Test source_query exclusivity with source_db_id and source_table_id."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="task-alias",
                hostname="example.com",
                service_id=123,
                source_query="SELECT * FROM data",
                source_db_id=1,
                source_table_id=2,
                dest_table_id=3,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 100",
            )
        error_message = str(exc_info.value)
        assert "must not be set" in error_message

        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="task-alias",
                hostname="example.com",
                service_id=123,
                dest_table_id=3,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 100",
            )
        error_message = str(exc_info.value)
        assert (
            "either both source_db_id and source_table_id or both source_db_name and source_table_name must be provided"
            in error_message
        )

    def test_validate_where_based_on_swap_drop(self):
        """Test that 'where' is set or unset based on the value of swap_drop."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="task-alias",
                hostname="example.com",
                service_id=123,
                source_db_id=1,
                source_table_id=2,
                swap_drop=SwapDropEnum.SWAP_DROP,
                where="id > 100",
            )
        error_message = str(exc_info.value)
        assert "'where' must not be set" in error_message

        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="task-alias",
                hostname="example.com",
                service_id=123,
                source_db_id=1,
                source_table_id=2,
                dest_table_id=3,
                swap_drop=SwapDropEnum.PURGE_ONLY,
            )
        error_message = str(exc_info.value)
        assert "'where' is required" in error_message
