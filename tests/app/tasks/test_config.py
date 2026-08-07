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

"""Define tests for the app.tasks.config module."""

from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy_celery_beat.models import Period

from app.core.celery.models import IntervalSchedule
from app.core.db.config import DatabaseOptions
from app.core.settings_override.registry import (
    field_reload_classification,
    is_explicit_not_overridable,
    ReloadClassification,
)
from app.tasks.config import PreExecutionCheckMode, tasks_settings, TasksSettings

EXPECTED_UVICORN_PORT = 8002
EXPECTED_LOG_RETENTION_DAYS = 90
EXPECTED_LOG_PURGE_BATCH_SIZE = 10_000
MAX_LOG_RETENTION_DAYS = 365


class TestTasksSettings:
    """Test the TasksSettings class."""

    def test_settings_prefixes(self):
        """Assert SETTINGS_PREFIXES contains 'TASKS'."""
        assert TasksSettings.SETTINGS_PREFIXES == ["TASKS"]

    def test_default_uvicorn_port(self):
        """Assert default UVICORN_PORT is 8002."""
        assert tasks_settings.UVICORN_PORT == EXPECTED_UVICORN_PORT

    def test_default_database_name(self):
        """Assert default DATABASE.NAME is 'tasks.db'."""
        assert tasks_settings.DATABASE.NAME == "tasks.db"

    def test_default_database_is_database_options(self):
        """Assert DATABASE is a DatabaseOptions instance."""
        assert isinstance(tasks_settings.DATABASE, DatabaseOptions)

    def test_default_sync_lock_ttl(self):
        """Assert default SYNC_LOCK_TTL is 5 minutes."""
        assert timedelta(minutes=5) == tasks_settings.SYNC_LOCK_TTL

    def test_singleton_is_tasks_settings_instance(self):
        """Assert the module-level singleton is a TasksSettings instance."""
        assert isinstance(tasks_settings, TasksSettings)

    def test_default_pre_execution_connectivity_check(self):
        """Assert default PRE_EXECUTION_CONNECTIVITY_CHECK is ``warn``."""
        assert (
            tasks_settings.PRE_EXECUTION_CONNECTIVITY_CHECK
            == PreExecutionCheckMode.WARN
        )

    def test_default_log_retention_days(self):
        """Assert default LOG_RETENTION_DAYS is 90."""
        assert tasks_settings.LOG_RETENTION_DAYS == EXPECTED_LOG_RETENTION_DAYS

    def test_default_log_purge_batch_size(self):
        """Assert default LOG_PURGE_BATCH_SIZE is 10,000."""
        assert tasks_settings.LOG_PURGE_BATCH_SIZE == EXPECTED_LOG_PURGE_BATCH_SIZE

    def test_default_log_purge_interval_is_daily(self):
        """Assert default LOG_PURGE_INTERVAL runs once per day."""
        interval = tasks_settings.LOG_PURGE_INTERVAL
        assert isinstance(interval, IntervalSchedule)
        assert interval.every == 1
        assert interval.period == Period.DAYS

    def test_log_retention_days_rejects_non_positive(self):
        """Assert LOG_RETENTION_DAYS rejects zero and negative values."""
        for value in (0, -1):
            with pytest.raises(ValidationError):
                TasksSettings(LOG_RETENTION_DAYS=value)

    def test_log_retention_days_rejects_above_max(self):
        """Assert LOG_RETENTION_DAYS rejects values above the 365-day ceiling."""
        with pytest.raises(ValidationError):
            TasksSettings(LOG_RETENTION_DAYS=MAX_LOG_RETENTION_DAYS + 1)

    def test_log_retention_days_accepts_bounds(self):
        """Assert LOG_RETENTION_DAYS accepts the inclusive 1..365 bounds."""
        assert TasksSettings(LOG_RETENTION_DAYS=1).LOG_RETENTION_DAYS == 1
        assert (
            TasksSettings(LOG_RETENTION_DAYS=MAX_LOG_RETENTION_DAYS).LOG_RETENTION_DAYS
            == MAX_LOG_RETENTION_DAYS
        )

    def test_default_hook_module_allowlist(self) -> None:
        """Assert the default allow-list admits the namespace holding the task apps."""
        assert tasks_settings.HOOK_MODULE_ALLOWLIST == ("app.sep.apps",)

    def test_hook_module_allowlist_is_not_runtime_overridable(self) -> None:
        """Assert the allow-list cannot be widened through the settings API.

        Widening the namespace at runtime would itself be a privilege-escalation
        path, since the resolved callable is imported and invoked.
        """
        field_info = TasksSettings.model_fields["HOOK_MODULE_ALLOWLIST"]

        assert (
            field_reload_classification(field_info)
            is ReloadClassification.NOT_OVERRIDABLE
        )
        assert is_explicit_not_overridable(field_info)
