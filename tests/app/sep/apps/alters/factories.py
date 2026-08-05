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

"""Define the model factories for the Schema Change app's tests."""

from polyfactory.factories.pydantic_factory import ModelFactory

from app.sep.apps.alters.models import AltersCreate


class AltersCreateFactory(ModelFactory[AltersCreate]):
    """Define factory for AltersCreate instances."""

    db_schema: int | str = 1
    db_table: int | str = 2
    recursion_method: str = "processlist"
    dsn_table: str = ""
    continue_on_pre_check_failure: bool = False
