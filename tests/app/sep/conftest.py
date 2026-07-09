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

"""Re-export the shared SEP test fixtures for the ``tests/app/sep`` subtree.

These fixtures are defined in the always-loaded ancestor ``tests/app/conftest.py`` so they
resolve regardless of single-process pytest collection order (SEP-1417). They are re-exported
here so app-subtree conftests can keep importing them from ``tests.app.sep.conftest``.
"""

from tests.app.conftest import (  # noqa: F401
    api_admin_client_no_bearer,
    async_test_client,
    celery_beat_session_fixture,
    dummy_request,
    mock_get_username_mapping,
    mock_inventory_api_dep,
    mock_task_api_dep,
    session_fixture,
    test_client,
    unauthenticated_client,
)
