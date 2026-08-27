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

"""Shared fixtures for the migration tests that need a real PostgreSQL server."""

import os

import pytest
from sqlalchemy.engine import make_url, URL

from tests.app.conftest import POSTGRES_DSN_ENV


@pytest.fixture
def postgres_sync_url() -> URL:
    """Return a sync (``psycopg2``) URL to the real-PostgreSQL test database.

    Skip when ``$SEP_TEST_POSTGRES_DSN`` is unset (local runs without
    PostgreSQL); the dedicated ``test_postgres`` CI job supplies it.
    """
    dsn = os.environ.get(POSTGRES_DSN_ENV)
    if not dsn:
        pytest.skip(f"{POSTGRES_DSN_ENV} not set; skipping real-PostgreSQL tests")
    return make_url(dsn).set(drivername="postgresql+psycopg2")
