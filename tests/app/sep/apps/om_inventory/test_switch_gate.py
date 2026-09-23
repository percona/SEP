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

"""Test ``run_om_probe``'s own ``ENABLED`` backstop.

``app.py``'s periodic-task thunk keeps a disabled deployment off Celery beat, and
``trigger_probe`` refuses a manual trigger while ``ENABLED`` is off -- but beat calls
this task directly, so neither of those checks runs on the scheduled path. This is
the backstop for the moment ``ENABLED`` flips off after a sweep was already due.
"""

import pytest

from app.sep.apps.om_inventory.celery import run_om_probe
from app.sep.apps.om_inventory.config import om_inventory_settings

MODULE = "app.sep.apps.om_inventory.celery"


class TestRunOmProbeEnabledGate:
    """Cover the ``ENABLED`` check ``run_om_probe`` makes before dispatching."""

    def test_skips_the_sweep_while_enabled_is_off(
        self, mocker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No-op, without touching the event loop, while the switch is off."""
        monkeypatch.setattr(om_inventory_settings, "ENABLED", False)
        mock_celery = mocker.patch(f"{MODULE}.celery")
        run_probe_mock = mocker.patch(f"{MODULE}.run_probe")

        result = run_om_probe("11111111-1111-1111-1111-111111111111", None)

        assert result is None
        run_probe_mock.assert_not_called()
        mock_celery.loop.run_until_complete.assert_not_called()

    def test_runs_the_sweep_while_enabled_is_on(
        self, mocker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dispatch to ``run_probe`` via the event loop while the switch is on."""
        monkeypatch.setattr(om_inventory_settings, "ENABLED", True)
        mock_celery = mocker.patch(f"{MODULE}.celery")
        mock_celery.loop.run_until_complete.return_value = (
            "11111111-1111-1111-1111-111111111111"
        )
        run_probe_mock = mocker.patch(f"{MODULE}.run_probe")

        result = run_om_probe(None, ["id-db00"])

        run_probe_mock.assert_called_once_with(None, ["id-db00"])
        mock_celery.loop.run_until_complete.assert_called_once()
        assert result == "11111111-1111-1111-1111-111111111111"
