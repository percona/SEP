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

"""Guard the seed ↔ include ↔ registration invariant for SEP Celery tasks.

The relocation of the app-owned Celery tasks (SEP-1506) split one hazard three
ways: a task's registered name is its module path, the beat seed hard-codes that
path as ``task_name``, and two ``include`` lists drive which modules a worker
imports. If any of those drifts apart, a beat row points at a task no worker
registers — and every task-logic test stays green. These tests pin the three
together so a future move cannot silently break dispatch.
"""

import importlib

from app.celery import celery
from app.core.config import settings


def _seed_task_names() -> set[str]:
    """Return every ``task_name`` the SEP beat seed schedules."""
    from app.sep.db.seed import get_system_periodic_tasks

    return {
        task.task_name
        for schedule in get_system_periodic_tasks()
        for task in schedule.tasks
    }


class TestCeleryInclude:
    """Cover the two ``include`` lists that must move in lockstep."""

    def test_worker_include_matches_configured_include(self, mocker) -> None:
        """Assert ``start_celery_worker`` registers the configured module set.

        The worker's ``include`` list (``app/main.py``) and the Celery app's
        configured ``include`` (``settings.CELERY.include``) are separate
        literals; a change to one but not the other lets beat schedule against a
        module the worker never imports.
        """
        import app.main

        worker_cls = mocker.patch.object(app.main.celery_app, "Worker")

        app.main.start_celery_worker()

        _, kwargs = worker_cls.call_args
        assert kwargs["include"] == settings.CELERY.include
        worker_cls.return_value.start.assert_called_once()


class TestSeedTaskRegistration:
    """Cover the seed ``task_name`` ↔ actual-registration invariant."""

    def test_seed_task_names_are_registered(self) -> None:
        """Assert every seeded ``task_name`` resolves to a registered Celery task.

        Importing the configured ``include`` modules is what a worker does at
        startup; ``@owned_by`` app tasks (and, transitively, the ``app_drain``
        reconcile task they import) register as a side effect. Any seeded
        ``task_name`` absent afterwards is a beat row pointing at nothing.
        """
        for module in settings.CELERY.include:
            importlib.import_module(module)

        missing = _seed_task_names() - set(celery.tasks)
        assert not missing, f"seeded task_name(s) not registered: {sorted(missing)}"

    def test_relocated_tasks_register_under_new_names(self) -> None:
        """Assert the two SEP-1506 tasks register under their app-owned paths."""
        importlib.import_module("app.sep.apps.snippets.celery")
        importlib.import_module("app.sep.apps.alerts.celery")

        assert "app.sep.apps.snippets.celery.sync_snippets" in celery.tasks
        assert "app.sep.apps.alerts.celery.backup_alert_config" in celery.tasks

    def test_no_task_registered_under_retired_shared_module(self) -> None:
        """Assert nothing still registers under the deleted ``app.sep.celery``."""
        stale = [name for name in celery.tasks if name.startswith("app.sep.celery.")]
        assert not stale, f"tasks still under retired module: {stale}"
