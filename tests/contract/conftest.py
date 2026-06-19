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

"""Auto-marker for the contract layer.

Every test collected under ``tests/contract/`` gets ``@pytest.mark.contract``
applied automatically. The lane skips cleanly when ``schemathesis`` is not
installed locally; CI installs it on every PR (milestone M6).
"""

import pytest


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Apply ``contract`` marker to every item collected under this directory."""
    for item in items:
        if "tests/contract/" in str(item.fspath):
            item.add_marker(pytest.mark.contract)
