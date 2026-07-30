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

"""Define tests for the ATW plugin settings section."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.sep.apps.atw.config import atw_settings, AtwSettings


class TestAtwSettingsDefaults:
    """Check the shipped defaults of the ATW settings section."""

    def test_defaults_stage_bundles_and_schedule_a_cleanup(self) -> None:
        """Ensure the out-of-the-box section stages bundles and sweeps them."""
        atw = AtwSettings()

        assert atw.bundle_dir.endswith("data/atw-bundles")
        assert atw.bundle_ttl == AtwSettings.model_fields["bundle_ttl"].default
        assert atw.cleanup_interval is not None
        assert atw.stale_send_after > timedelta(0)

    def test_module_level_instance_is_the_shared_section(self) -> None:
        """Ensure consumers get a ready-made section rather than building one."""
        assert isinstance(atw_settings, AtwSettings)


class TestAtwSettingsValidation:
    """Check the section's declarative positive-duration bounds."""

    @pytest.mark.parametrize("value", [0, -1])
    def test_rejects_a_non_positive_bundle_ttl(self, value: int) -> None:
        """Ensure a non-positive TTL is refused at config load, not at purge time."""
        with pytest.raises(ValidationError):
            AtwSettings(bundle_ttl=value)

    @pytest.mark.parametrize("value", [timedelta(0), timedelta(seconds=-1)])
    def test_rejects_a_non_positive_stale_send_after(self, value: timedelta) -> None:
        """Ensure a non-positive stale window cannot fail every in-flight send."""
        with pytest.raises(ValidationError):
            AtwSettings(stale_send_after=value)

    def test_cleanup_interval_may_be_disabled(self) -> None:
        """Ensure an operator can switch the sweep off entirely."""
        assert AtwSettings(cleanup_interval=None).cleanup_interval is None
