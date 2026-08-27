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

"""Define unit tests pinning the framework test kit's boundary-mock invariants."""

import pytest

from app.core.exceptions import HTTPNotFoundException
from app.inventory.models import ServiceTypeEnum
from tests.app.factories import (
    MOCK_CREATED_NODE_ID,
    MOCK_CREATED_SCHEMA_ID,
    MOCK_CREATED_SERVICE_ID,
    MOCK_CREATED_TABLE_ID,
)
from tests.app.sep.apps.framework.kit import MockInventoryAPI


class TestMockInventoryAPISeeding:
    """Pin the seeded-entity invariants apps' reference resolution relies on."""

    @pytest.mark.asyncio
    async def test_seed_table_names_are_distinct_per_id(self) -> None:
        """Derive each seeded table's name from its id so distinct ids differ by name.

        The archives self-archive guard rejects a create whose source and
        destination tables resolve to the same name. A per-build random table name
        collides across distinct ids intermittently and spuriously rejects a valid
        distinct-table create, so the kit derives the name from the id instead.
        """
        api = MockInventoryAPI()
        second_id = MOCK_CREATED_TABLE_ID + 1
        api.seed_table(second_id)
        first = await api.get(f"/tables/{MOCK_CREATED_TABLE_ID}")
        second = await api.get(f"/tables/{second_id}")
        assert (first["name"], second["name"]) == (
            f"tbl-{MOCK_CREATED_TABLE_ID}",
            f"tbl-{second_id}",
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("collection", "entity_id"),
        [
            ("nodes", MOCK_CREATED_NODE_ID),
            ("services", MOCK_CREATED_SERVICE_ID),
            ("schemas", MOCK_CREATED_SCHEMA_ID),
            ("tables", MOCK_CREATED_TABLE_ID),
        ],
    )
    async def test_default_ids_resolve_without_an_explicit_seed(
        self, collection: str, entity_id: int
    ) -> None:
        """Materialise each default ``MOCK_*_ID`` entity on its first resolution.

        The constructor records the four defaults instead of building them, so
        every id an app's reference resolution reaches for must still come back.
        """
        api = MockInventoryAPI()

        entity = await api.get(f"/{collection}/{entity_id}")

        assert entity["id"] == entity_id

    @pytest.mark.asyncio
    async def test_explicit_reseed_wins_over_the_lazy_default(self) -> None:
        """Let a test-supplied seed survive the default that would have replaced it.

        ``backup_pg`` re-seeds the shared service id as PostgreSQL-typed because
        its single-type ``ServiceRef(POSTGRESQL)`` selector rejects the kit's
        MySQL default. Resolving the id must not overwrite that with the default.
        """
        api = MockInventoryAPI()
        api.seed_service(
            MOCK_CREATED_SERVICE_ID, service_type=ServiceTypeEnum.POSTGRESQL
        )

        service = await api.get(f"/services/{MOCK_CREATED_SERVICE_ID}")

        assert service["type"] == ServiceTypeEnum.POSTGRESQL

    @pytest.mark.asyncio
    async def test_unseeded_id_still_raises_not_found(self) -> None:
        """Keep the 404 contract for an id neither seeded nor pending."""
        api = MockInventoryAPI()

        with pytest.raises(HTTPNotFoundException):
            await api.get(f"/services/{MOCK_CREATED_SERVICE_ID + 1}")
