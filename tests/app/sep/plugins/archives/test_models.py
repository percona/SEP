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

"""Tests for the app.sep.plugins.archives.models module."""

import pytest
from pydantic import ValidationError

from app.sep.plugins.archives.constants import SwapDropEnum
from app.sep.plugins.archives.models import ArchivesCreate

MAX_VALID_PORT = 65535
MIN_VALID_PORT = 1
SAMPLE_DEST_SERVICE_ID = 2
SAMPLE_DEST_PORT = 3307
OTHER_DEST_SERVICE_ID = 7
INVENTORY_DEST_SCHEMA_ID = 99


class TestArchivesCreateDestinationValidation:
    """Test destination field validation in ArchivesCreate."""

    def test_dest_host_rejects_comma(self):
        """dest_host cannot contain commas (DSN delimiter)."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="test",
                hostname="host",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 1",
                dest_table_id=2,
                dest_host="host,bad",
            )
        assert "DSN delimiter" in str(exc_info.value)

    def test_dest_host_rejects_equals(self):
        """dest_host cannot contain equals signs (DSN delimiter)."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="test",
                hostname="host",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 1",
                dest_table_id=2,
                dest_host="host=bad",
            )
        assert "DSN delimiter" in str(exc_info.value)

    def test_dest_db_name_rejects_comma(self):
        """dest_db_name cannot contain commas."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="test",
                hostname="host",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 1",
                dest_table_id=2,
                dest_host="archive.host",
                dest_db_name="db,bad",
            )
        assert "DSN delimiter" in str(exc_info.value)

    def test_dest_service_id_and_dest_host_mutually_exclusive(self):
        """Cannot set both dest_service_id (inventory) and dest_host (manual)."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="test",
                hostname="host",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 1",
                dest_table_id=2,
                dest_service_id=2,
                dest_host="archive.host",
            )
        assert "Cannot use both" in str(exc_info.value)

    def test_dest_service_id_and_dest_port_forbidden(self):
        """Cannot type a manual dest_port when a dest_service_id is selected."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="test",
                hostname="host",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 1",
                dest_table_id=2,
                dest_service_id=2,
                dest_port=3307,
            )
        assert "dest_port" in str(exc_info.value)

    def test_dest_service_id_with_empty_dest_port_succeeds(self):
        """Empty dest_port alongside dest_service_id is valid; port is derived from the service."""
        dest_service_id = 2
        form = ArchivesCreate(
            alias="test",
            hostname="host",
            service_id=1,
            source_db_id=1,
            source_table_id=1,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=2,
            dest_service_id=dest_service_id,
            dest_port="",
        )
        assert form.dest_service_id == dest_service_id
        assert form.dest_port is None

    def test_dest_db_id_and_dest_db_name_mutually_exclusive(self):
        """Cannot set both dest_db_id (inventory) and dest_db_name (manual)."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="test",
                hostname="host",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 1",
                dest_table_id=2,
                dest_service_id=2,
                dest_db_id=10,
                dest_db_name="archive_db",
            )
        assert "Cannot use both" in str(exc_info.value)

    def test_dest_db_id_requires_dest_service_id(self):
        """dest_db_id requires dest_service_id (cannot pick inventory schema with manual host)."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="test",
                hostname="host",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 1",
                dest_table_id=2,
                dest_host="archive.host",
                dest_db_id=10,
            )
        assert "requires dest_service_id" in str(exc_info.value)

    def test_dest_host_forbidden_with_swap_archive_drop(self):
        """Cannot set destination host when swap_drop is SWAP_ARCHIVE_DROP (2)."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="test",
                hostname="host",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.SWAP_ARCHIVE_DROP,
                swp_table_suffix="2026-04-29",
                dest_table_id=2,
                dest_service_id=2,
            )
        assert "SWAP_ARCHIVE_DROP" in str(exc_info.value)

    def test_valid_dest_service_and_db_id(self):
        """Valid: dest_service_id + dest_db_id (inventory path)."""
        dest_service_id = 3
        dest_db_id = 10
        form = ArchivesCreate(
            alias="test",
            hostname="host",
            service_id=1,
            source_db_id=1,
            source_table_id=1,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=2,
            dest_service_id=dest_service_id,
            dest_db_id=dest_db_id,
        )
        assert form.dest_service_id == dest_service_id
        assert form.dest_db_id == dest_db_id

    def test_valid_dest_host_manual_path(self):
        """Valid: dest_host + dest_port + dest_db_name (manual path)."""
        dest_port = 3307
        dest_host = "archive.host"
        dest_db_name = "archive_db"
        form = ArchivesCreate(
            alias="test",
            hostname="host",
            service_id=1,
            source_db_id=1,
            source_table_id=1,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=2,
            dest_host=dest_host,
            dest_port=dest_port,
            dest_db_name=dest_db_name,
        )
        assert form.dest_host == dest_host
        assert form.dest_port == dest_port
        assert form.dest_db_name == dest_db_name

    def test_valid_no_destination_defaults_to_source(self):
        """Valid: no destination fields set (falls back to source at runtime)."""
        form = ArchivesCreate(
            alias="test",
            hostname="host",
            service_id=1,
            source_db_id=1,
            source_table_id=1,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=2,
        )
        assert form.dest_service_id is None
        assert form.dest_host is None
        assert form.dest_db_id is None
        assert form.dest_db_name == ""

    def test_dest_host_port_range_validation(self):
        """dest_port must be within valid range (1-65535)."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="test",
                hostname="host",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 1",
                dest_table_id=2,
                dest_host="archive.host",
                dest_port=70000,
            )
        assert "less than or equal to 65535" in str(exc_info.value)

    def test_dest_port_boundary_zero(self):
        """dest_port cannot be 0 (minimum is 1)."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="test",
                hostname="host",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 1",
                dest_table_id=2,
                dest_host="archive.host",
                dest_port=0,
            )
        assert "greater than or equal to 1" in str(exc_info.value)

    def test_dest_port_boundary_negative(self):
        """dest_port cannot be negative."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="test",
                hostname="host",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 1",
                dest_table_id=2,
                dest_host="archive.host",
                dest_port=-1,
            )
        assert "greater than or equal to 1" in str(exc_info.value)

    def test_dest_port_boundary_min_valid(self):
        """dest_port minimum valid value is 1."""
        form = ArchivesCreate(
            alias="test",
            hostname="host",
            service_id=1,
            source_db_id=1,
            source_table_id=1,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=2,
            dest_host="archive.host",
            dest_port=1,
        )
        assert form.dest_port == 1

    def test_dest_port_boundary_max_valid(self):
        """dest_port maximum valid value is 65535."""
        form = ArchivesCreate(
            alias="test",
            hostname="host",
            service_id=1,
            source_db_id=1,
            source_table_id=1,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=2,
            dest_host="archive.host",
            dest_port=MAX_VALID_PORT,
        )
        assert form.dest_port == MAX_VALID_PORT

    def test_dest_db_name_rejects_equals(self):
        """dest_db_name cannot contain equals signs (DSN delimiter)."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="test",
                hostname="host",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 1",
                dest_table_id=2,
                dest_host="archive.host",
                dest_db_name="db=name",
            )
        assert "DSN delimiter" in str(exc_info.value)

    def test_dest_service_with_dest_db_name_allowed(self):
        """dest_service_id can be combined with dest_db_name (not dest_db_id)."""
        form = ArchivesCreate(
            alias="test",
            hostname="host",
            service_id=1,
            source_db_id=1,
            source_table_id=1,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=2,
            dest_service_id=SAMPLE_DEST_SERVICE_ID,
            dest_db_name="custom_db",
        )
        assert form.dest_service_id == SAMPLE_DEST_SERVICE_ID
        assert form.dest_db_name == "custom_db"

    def test_dest_host_with_dest_db_name_allowed(self):
        """dest_host can be combined with dest_db_name."""
        form = ArchivesCreate(
            alias="test",
            hostname="host",
            service_id=1,
            source_db_id=1,
            source_table_id=1,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=2,
            dest_host="archive.host",
            dest_port=SAMPLE_DEST_PORT,
            dest_db_name="archive_db",
        )
        assert form.dest_host == "archive.host"
        assert form.dest_port == SAMPLE_DEST_PORT
        assert form.dest_db_name == "archive_db"

    def test_dest_host_forbidden_with_swap_drop(self):
        """Cannot set dest_host when swap_drop is SWAP_ARCHIVE_DROP (2)."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="test",
                hostname="host",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.SWAP_ARCHIVE_DROP,
                swp_table_suffix="2026-04-29",
                dest_table_id=2,
                dest_host="archive.host",
            )
        assert "SWAP_ARCHIVE_DROP" in str(exc_info.value)

    def test_dest_host_whitespace_only_treated_as_none(self):
        """dest_host with only whitespace should not trigger validation errors."""
        # The model stores the raw whitespace-only value, but the validator and
        # resolver both strip before acting on it, so it is treated as absent.
        form = ArchivesCreate(
            alias="test",
            hostname="host",
            service_id=1,
            source_db_id=1,
            source_table_id=1,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=2,
            dest_host="   ",
        )
        assert form.dest_host == "   "

    def test_dest_host_none_and_dest_db_name_empty_is_valid(self):
        """dest_host=None and dest_db_name='' (defaults) should not raise ValidationError."""
        form = ArchivesCreate(
            alias="test",
            hostname="host",
            service_id=1,
            source_db_id=1,
            source_table_id=1,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=2,
        )
        assert form.dest_host is None
        assert form.dest_db_name == ""


class TestArchivesCreateEmptyStringCoercion:
    """Empty-string coercion to ``None`` on form-bound optional int fields."""

    @pytest.mark.parametrize(
        "field",
        [
            "source_db_id",
            "source_table_id",
            "dest_table_id",
            "limit",
            "sleep",
            "dest_service_id",
            "dest_port",
            "dest_db_id",
        ],
    )
    def test_empty_string_optional_int_coerced_to_none(self, field: str) -> None:
        """Empty strings on form-bound optional ints become ``None``, not 422.

        Uses a Purge Only + ``source_query`` + ``delete_data`` base so every
        parametrized field can legitimately be ``None`` without tripping the
        source/destination exclusivity validators (``delete_data`` forbids the
        destination fields, ``source_query`` covers the source side).
        """
        base = {
            "alias": "t",
            "hostname": "h",
            "service_id": 1,
            "source_query": "SELECT 1",
            "where": "id > 1",
            "delete_data": 1,
            "swap_drop": SwapDropEnum.PURGE_ONLY,
            field: "",
        }
        form = ArchivesCreate(**base)
        assert getattr(form, field) is None

    def test_dest_port_non_empty_string_parsed_as_int(self) -> None:
        """A non-empty ``dest_port`` string still parses to ``int`` (range-checked)."""
        form = ArchivesCreate(
            alias="t",
            hostname="h",
            service_id=1,
            source_db_id=1,
            source_table_id=1,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=2,
            dest_host="archive.host",
            dest_port="3307",
        )
        assert form.dest_port == SAMPLE_DEST_PORT
        assert isinstance(form.dest_port, int)

    def test_dest_port_out_of_range_still_rejected(self) -> None:
        """Non-empty ``dest_port`` above 65535 still fails the range constraint."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="t",
                hostname="h",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 1",
                dest_table_id=2,
                dest_host="archive.host",
                dest_port="99999",
            )
        assert "less than or equal to 65535" in str(exc_info.value)

    def test_dest_port_non_numeric_still_rejected(self) -> None:
        """Non-empty, non-numeric ``dest_port`` still fails int parsing."""
        with pytest.raises(ValidationError) as exc_info:
            ArchivesCreate(
                alias="t",
                hostname="h",
                service_id=1,
                source_db_id=1,
                source_table_id=1,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 1",
                dest_table_id=2,
                dest_host="archive.host",
                dest_port="abc",
            )
        assert "valid integer" in str(exc_info.value)


class TestArchivesCreateSameTableIdentity:
    """Verify the destination-identity rule (Validator 1b).

    A destination table is the *same* table only when host, schema, and table
    name all match. All cases use the manual-source path (``source_db_name`` /
    ``source_table_name``), which is the only path Validator 1b runs on.
    """

    @staticmethod
    def _base_kwargs(**overrides: object) -> dict[str, object]:
        """Return manual-source kwargs that pass every validator but 1b.

        The destination table name equals the source table name, so the
        accept/reject outcome is driven solely by the destination host/schema
        identity supplied via ``overrides``.
        """
        return {
            "alias": "t",
            "hostname": "h",
            "service_id": 1,
            "source_db_name": "sbtest",
            "source_table_name": "sbtest5",
            "swap_drop": SwapDropEnum.PURGE_ONLY,
            "where": "id > 1",
            "dest_table_name": "sbtest5",
            **overrides,
        }

    def test_same_host_same_schema_same_table_rejected(self):
        """No explicit dest host/schema → defaults to source → genuine self-archive."""
        with pytest.raises(ValidationError, match="cannot be the same"):
            ArchivesCreate(**self._base_kwargs())

    def test_explicit_same_host_and_schema_same_table_rejected(self):
        """Explicit dest host and schema that equal the source → self-archive."""
        with pytest.raises(ValidationError, match="cannot be the same"):
            ArchivesCreate(
                **self._base_kwargs(dest_service_id=1, dest_db_name="sbtest")
            )

    def test_different_dest_service_same_table_accepted(self):
        """Different inventory destination host, same table name → accepted (the bug)."""
        form = ArchivesCreate(
            **self._base_kwargs(dest_service_id=OTHER_DEST_SERVICE_ID)
        )
        assert form.dest_service_id == OTHER_DEST_SERVICE_ID

    def test_manual_different_dest_host_same_table_accepted(self):
        """Different manual destination host, same table name → accepted."""
        form = ArchivesCreate(**self._base_kwargs(dest_host="other-host"))
        assert form.dest_host == "other-host"

    def test_same_host_different_schema_name_accepted(self):
        """Same host, different manual schema name, same table → accepted."""
        form = ArchivesCreate(**self._base_kwargs(dest_db_name="sbtest_archived"))
        assert form.dest_db_name == "sbtest_archived"

    def test_same_host_inventory_dest_schema_accepted(self):
        """Same host, inventory destination schema (unresolvable to a name) → accepted.

        The validator cannot resolve an inventory ``dest_db_id`` to a schema
        name, so it treats the destination schema as distinct — an accepted
        limitation.
        """
        form = ArchivesCreate(
            **self._base_kwargs(dest_service_id=1, dest_db_id=INVENTORY_DEST_SCHEMA_ID)
        )
        assert form.dest_db_id == INVENTORY_DEST_SCHEMA_ID

    def test_same_inventory_table_ids_still_rejected(self):
        """Validator 1a (inventory table ids) is unchanged: same ids → rejected."""
        with pytest.raises(ValidationError, match="cannot be the same"):
            ArchivesCreate(
                alias="t",
                hostname="h",
                service_id=1,
                source_db_id=1,
                source_table_id=5,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 1",
                dest_table_id=5,
            )


def test_archives_create_has_conditional_rules_plan():
    """ArchivesCreate must have a non-None __conditional_rules_plan__ after decoration."""
    assert ArchivesCreate.__conditional_rules_plan__ is not None
