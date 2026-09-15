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

"""Hold the Tasks track's autogenerate quiet about a store where beat has run."""

from alembic import command

from app.core.celery.migrations import BEAT_TABLE_NAMES
from tests.app.beat_autogenerate import (
    autogenerate_diffs,
    create_beat_tables,
    tables_mentioned,
)


def test_autogenerate_ignores_the_beat_tables(tasks_alembic_config):
    """Keep the schedule tables out of the Tasks track's proposed operations."""
    cfg, sync_url = tasks_alembic_config
    command.upgrade(cfg, "heads")
    create_beat_tables(sync_url)

    diffs = autogenerate_diffs(cfg)

    assert tables_mentioned(diffs, BEAT_TABLE_NAMES) == []
