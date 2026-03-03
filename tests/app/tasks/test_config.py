"""Define tests for the app.tasks.config module."""

from datetime import timedelta

from app.core.db.config import DatabaseOptions
from app.tasks.config import tasks_settings, TasksSettings

EXPECTED_UVICORN_PORT = 8002


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
