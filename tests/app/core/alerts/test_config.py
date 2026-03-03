# Copyright 2026 Percona LLC
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

"""Define tests for the app.core.alerts.config module."""

import pytest

from app.core.alerts.config import AlertProviderEnum, AlertSettings
from app.core.alerts.providers.pagerduty import PagerDutyEventsAlertProvider


def make_provider_entry(name: str, **kwargs):
    """Define helper to build a provider config dict."""
    entry = {"PROVIDER": name}
    entry.update(kwargs)
    return entry


def test_set_alerts_providers_success(tmp_path):
    """Test that valid provider configs produce provider instances."""
    raw = [
        make_provider_entry("pagerduty", routing_key="abc123"),
    ]
    settings = AlertSettings(PROVIDERS=raw, SOURCE_PREFIX="X-", SOURCE_SUFFIX="-Y")
    provs = settings.PROVIDERS
    assert isinstance(provs, set)
    assert len(provs) == 1
    p = next(iter(provs))
    assert isinstance(p, PagerDutyEventsAlertProvider)
    assert p.routing_key.get_secret_value() == "abc123"
    assert settings.SOURCE_PREFIX == "X-"
    assert settings.SOURCE_SUFFIX == "-Y"


def test_set_alerts_providers_missing_provider_key():
    """Ensure missing PROVIDER key raises ValueError."""
    with pytest.raises(ValueError, match="Ensure 'PROVIDER' is set"):
        AlertSettings(PROVIDERS=[{"routing_key": "no-name"}])


def test_set_alerts_providers_invalid_provider_name():
    """Ensure invalid provider names raise ValueError listing options."""
    with pytest.raises(ValueError, match="Invalid alert provider: nope") as exc:
        AlertSettings(PROVIDERS=[make_provider_entry("nope", routing_key="x")])
    for name in AlertProviderEnum.__members__:
        assert name in str(exc.value)


def test_set_alerts_providers_invalid_provider_configuration():
    """Ensure invalid provider configuration raises ValueError."""
    with pytest.raises(ValueError, match="Invalid configuration"):
        AlertSettings(PROVIDERS=[make_provider_entry("pagerduty")])
