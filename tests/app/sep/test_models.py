"""Define tests for the app.sep.models module."""

import pytest
from pydantic import ValidationError

from app.sep.plugins.archives.models import ArchivesCreate, SwapDropEnum


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
            match="both dest_table_id/dest_table_name and dest_file must be None/empty",
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
        with pytest.raises(ValidationError, match="swp_table_suffix must be provided"):
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
        assert (
            "so source_db_id/source_table_id and source_db_name/source_table_name must be None/empty"
            in error_message
        )

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
            "either both source_db_id and source_table_id, or both source_db_name and source_table_name must be provided"
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
        assert "When swap_drop is SWAP_DROP" in error_message
        assert "where" in error_message
        assert "must be None" in error_message

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
        assert "When swap_drop is not SWAP_DROP" in error_message
        assert "where" in error_message
        assert "must be set" in error_message
