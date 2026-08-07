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

"""Define tests for the ATW ``closed_at`` column Alembic migration."""

from alembic import command
from sqlalchemy import create_engine, inspect

_CLOSED_AT_REVISION = "447ee0172734"
_PRE_CLOSED_AT_REVISION = "c93998e0fa14"


def _incident_columns(sync_url: str) -> set[str]:
    """Return column names on ``atw_incident``, or empty if the table is absent."""
    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        if "atw_incident" not in inspector.get_table_names():
            return set()
        return {column["name"] for column in inspector.get_columns("atw_incident")}
    finally:
        engine.dispose()


def test_upgrade_adds_closed_at_column(sep_alembic_config):
    """Assert upgrade stamps ``closed_at`` onto ``atw_incident``."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, _CLOSED_AT_REVISION)
    assert "closed_at" in _incident_columns(sync_url)


def test_downgrade_drops_closed_at_column(sep_alembic_config):
    """Assert downgrade removes ``closed_at`` from ``atw_incident``."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, _CLOSED_AT_REVISION)
    command.downgrade(cfg, _PRE_CLOSED_AT_REVISION)
    assert "closed_at" not in _incident_columns(sync_url)
