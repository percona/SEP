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

"""Asserts for SEP database seed data (system periodic tasks)."""

from app.core.celery.utils import SystemPeriodicTaskData
from app.sep.db.seed import SYSTEM_PERIODIC_TASKS


def test_nomad_cert_expiry_periodic_task_seeded() -> None:
    """Assert sep__check_nomad_cert_expiry is seeded with the Celery task path."""
    assert any(
        entry.name == "sep__check_nomad_cert_expiry"
        and entry.task_name == "app.sep.celery.check_nomad_cert_expiry"
        for _schedule, tasks in SYSTEM_PERIODIC_TASKS
        for entry in tasks
    )
    data = _find_nomad_cert_task()
    assert data is not None
    assert data.task_name == "app.sep.celery.check_nomad_cert_expiry"


def _find_nomad_cert_task() -> SystemPeriodicTaskData | None:
    for _schedule, tasks in SYSTEM_PERIODIC_TASKS:
        for entry in tasks:
            if entry.name == "sep__check_nomad_cert_expiry":
                return entry
    return None
