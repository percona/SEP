"""Define test cases for periodic task configuration."""

from app.tasks.periodic.config import PeriodicTaskAction, PeriodicTasksSettings


class TestPeriodicTaskAction:
    """Test the PeriodicTaskAction enum."""

    def test_nothing_value(self):
        """Assert NOTHING enum value exists."""
        assert PeriodicTaskAction.NOTHING == "nothing"

    def test_disable_value(self):
        """Assert DISABLE enum value exists."""
        assert PeriodicTaskAction.DISABLE == "disable"

    def test_delete_value(self):
        """Assert DELETE enum value exists."""
        assert PeriodicTaskAction.DELETE == "delete"

    def test_all_values(self):
        """Assert all expected enum values are present."""
        values = {member.value for member in PeriodicTaskAction}
        assert values == {"nothing", "disable", "delete"}


class TestPeriodicTasksSettings:
    """Test the PeriodicTasksSettings class."""

    def test_settings_prefixes(self):
        """Assert SETTINGS_PREFIXES is correctly set."""
        assert PeriodicTasksSettings.SETTINGS_PREFIXES == ["TASKS", "PERIODIC"]

    def test_instantiation(self):
        """Assert PeriodicTasksSettings can be instantiated."""
        instance = PeriodicTasksSettings()
        assert isinstance(instance, PeriodicTasksSettings)
