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
