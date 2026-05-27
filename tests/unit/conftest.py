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

"""Auto-marker for the unit layer.

Every test collected under ``tests/unit/`` gets ``@pytest.mark.unit`` applied
automatically. Selecting the unit lane is then ``pytest -m unit``, no manual
decoration required on each file.
"""

import pytest


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Apply ``unit`` marker to every item collected under this directory."""
    for item in items:
        if "tests/unit/" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
