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
        api.seed_table(2)
        first = await api.get("/tables/1")
        second = await api.get("/tables/2")
        assert (first["name"], second["name"]) == ("tbl-1", "tbl-2")
