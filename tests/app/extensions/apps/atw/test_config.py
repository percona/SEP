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
from pytest_mock import MockerFixture

from app.core.celery.models import IntervalSchedule, Period
from app.extensions.apps.atw.app import atw_periodic_tasks
from app.extensions.apps.atw.config import atw_settings, AtwSettings


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

    @pytest.mark.parametrize("value", [0, -1])
    def test_rejects_a_non_positive_reconcile_batch_size(self, value: int) -> None:
        """Ensure a batch size that would examine nothing is refused at config load."""
        with pytest.raises(ValidationError):
            AtwSettings(reconcile_batch_size=value)


class TestReconcileSettings:
    """Check the reconciliation sweep's own settings and their default."""

    def test_reconcile_ships_enabled(self) -> None:
        """Ensure the sweep runs out of the box.

        The default is load-bearing twice over: a defaultless ``IntervalSchedule |
        None`` would be a *required* field in Pydantic v2 and break settings
        construction on every existing deployment, and a ``None`` default would
        unregister the only mechanism that reconciles historical executions and the
        recorder's three unobserved terminal paths.
        """
        atw = AtwSettings()

        assert atw.reconcile_interval is not None
        assert atw.reconcile_batch_size > 0

    def test_reconcile_interval_may_be_disabled(self) -> None:
        """Ensure ``None`` is available as an explicit operator opt-out."""
        assert AtwSettings(reconcile_interval=None).reconcile_interval is None


class TestAtwSettingsEnvironmentOptOut:
    """Check the ``null`` opt-out that both sweep intervals document.

    ``settings.yaml`` offers ``null`` as the way to unregister either sweep, and an
    environment variable is the deployment path that offer is read against. Both
    fields are optional models, which pydantic-settings treats as complex: the raw
    value is JSON-decoded and a resulting ``None`` is dropped from the environment
    source entirely, so without an explicit none-string the opt-out reads as "unset"
    and the compiled-in default wins with nothing logged.
    """

    @pytest.mark.parametrize(
        ("env_var", "field_name"),
        [
            ("EXTENSIONS__ATW__CLEANUP_INTERVAL", "cleanup_interval"),
            ("EXTENSIONS__ATW__RECONCILE_INTERVAL", "reconcile_interval"),
        ],
    )
    def test_a_null_env_var_unregisters_a_sweep(
        self, monkeypatch: pytest.MonkeyPatch, env_var: str, field_name: str
    ) -> None:
        """Ensure ``null`` disables the sweep rather than restoring the default."""
        monkeypatch.setenv(env_var, "null")

        assert getattr(AtwSettings(), field_name) is None

    def test_an_interval_env_var_still_overrides_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ensure reading ``null`` as an opt-out leaves an ordinary override intact."""
        monkeypatch.setenv(
            "EXTENSIONS__ATW__RECONCILE_INTERVAL", '{"every": 30, "period": "seconds"}'
        )

        assert AtwSettings().reconcile_interval == IntervalSchedule(
            every=30, period=Period.SECONDS
        )


class TestAtwPeriodicTaskContributions:
    """Check that each sweep's schedule is guarded on its own interval."""

    def test_both_sweeps_are_scheduled_by_default(self) -> None:
        """Ensure the shipped defaults register the purge and the reconcile."""
        names = {task.name for task in atw_periodic_tasks()}

        assert names == {
            "extensions__purge_atw_bundles",
            "extensions__reconcile_atw_executions",
        }

    def test_disabling_reconcile_leaves_the_purge_scheduled(
        self, mocker: MockerFixture
    ) -> None:
        """Ensure the two guards are independent, not one shared switch."""
        mocker.patch.object(atw_settings, "reconcile_interval", None)

        names = {task.name for task in atw_periodic_tasks()}

        assert names == {"extensions__purge_atw_bundles"}

    def test_disabling_the_purge_leaves_reconcile_scheduled(
        self, mocker: MockerFixture
    ) -> None:
        """Ensure switching off housekeeping does not silently stop reconciliation."""
        mocker.patch.object(atw_settings, "cleanup_interval", None)

        names = {task.name for task in atw_periodic_tasks()}

        assert names == {"extensions__reconcile_atw_executions"}

    def test_disabling_both_contributes_nothing(self, mocker: MockerFixture) -> None:
        """Ensure an all-off configuration registers no beat entry at all."""
        mocker.patch.object(atw_settings, "cleanup_interval", None)
        mocker.patch.object(atw_settings, "reconcile_interval", None)

        assert atw_periodic_tasks() == []
