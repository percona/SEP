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

"""Define tests for the app.core.alerts.models module."""

from datetime import datetime
from unittest.mock import Mock

import pytest

from app.core.alerts.models import (
    Alert,
    AlertService,
    AlertSeverity,
    BaseAlertProvider,
)


class DummyProvider(BaseAlertProvider):
    """Define dummy alert provider."""

    sent: list[Alert] = []
    resolved: list[str] = []

    async def send_alert(self, alert: Alert) -> None:
        """Add alert to sent list."""
        self.sent.append(alert)

    async def resolve_alert(self, dedup_key: str) -> None:
        """Add dedup_key to resolved list."""
        self.resolved.append(dedup_key)


@pytest.fixture
def logger_mock(mocker) -> Mock:
    """Mock the logger for the app.core.alerts.models module."""
    return mocker.patch("app.core.alerts.models.logger")


@pytest.fixture
def dummy_alert():
    """Provide a basic Alert instance for testing."""
    return Alert(
        summary="Test summary",
        source="unit-test",
        severity=AlertSeverity.WARNING,
    )


@pytest.fixture
def dummy_provider():
    """Provide a dummy alert provider implementation."""
    return DummyProvider()


@pytest.fixture
def alert_service_with_provider(dummy_provider):
    """Create an AlertService configured with a dummy provider and affixes."""
    return AlertService(
        providers={dummy_provider}, source_prefix="PRE-", source_suffix="-SUF"
    )


class TestAlert:
    """Define tests for the Alert model."""

    def test_alert_model_defaults_and_serialization(self, dummy_alert):
        """Test default timestamp and round-trip serialization of Alert."""
        assert isinstance(dummy_alert.timestamp, datetime)
        dumped = dummy_alert.model_dump()
        rebuilt = Alert(**dumped)
        assert rebuilt.summary == dummy_alert.summary
        assert rebuilt.severity == dummy_alert.severity

    def test_alert_extra_fields_are_allowed(self):
        """Ensure Alert accepts and preserves extra fields."""
        a = Alert(summary="s", source="o", severity=AlertSeverity.INFO, foo="bar")
        data = a.model_dump()
        assert data["foo"] == "bar"


class TestAlertService:
    """Define tests for the AlertService."""

    @pytest.mark.asyncio
    async def test_trigger_no_providers_logs_warning(self, logger_mock, dummy_alert):
        """Verify warning is logged when no providers are registered."""
        svc = AlertService(providers=set())
        await svc.trigger(dummy_alert)
        logger_mock.warning.assert_called_with("No alert providers registered.")

    @pytest.mark.asyncio
    async def test_trigger_sends_to_all_providers(
        self, alert_service_with_provider, dummy_provider, dummy_alert, logger_mock
    ):
        """Check that AlertService sends alerts with prefix/suffix to each provider."""
        await alert_service_with_provider.trigger(dummy_alert)
        assert dummy_provider.sent, "Provider did not receive any alerts"
        sent = dummy_provider.sent[0]
        assert sent.source == "PRE-unit-test-SUF"
        logger_mock.info.assert_called_with(
            "Alert sent via %s: %s", dummy_provider.__class__.__name__, sent
        )

    @pytest.mark.asyncio
    async def test_trigger_handles_provider_exception(
        self, alert_service_with_provider, dummy_alert, logger_mock
    ):
        """Ensure exceptions in providers are caught and logged."""

        class BrokenProvider(BaseAlertProvider):
            async def send_alert(self, alert: Alert) -> None:
                raise RuntimeError("boom")

        svc = AlertService(
            providers={BrokenProvider()}, source_prefix="", source_suffix=""
        )
        await svc.trigger(dummy_alert)
        logger_mock.exception.assert_called_with(
            "Failed to send alert via %s: %s", "BrokenProvider", dummy_alert
        )


class TestAlertServiceResolve:
    """Define tests for AlertService.resolve."""

    @pytest.mark.asyncio
    async def test_resolve_no_providers_logs_warning(self, logger_mock):
        """Verify warning is logged when no providers are registered."""
        svc = AlertService(providers=set())
        await svc.resolve("task:test:node-1")
        logger_mock.warning.assert_called_with("No alert providers registered.")

    @pytest.mark.asyncio
    async def test_resolve_calls_all_providers(self, dummy_provider, logger_mock):
        """Verify resolve_alert is called on all registered providers."""
        svc = AlertService(providers={dummy_provider})
        await svc.resolve("task:test:node-1")
        assert dummy_provider.resolved == ["task:test:node-1"]
        logger_mock.info.assert_called_with(
            "Alert resolved via %s: dedup_key=%s",
            "DummyProvider",
            "task:test:node-1",
        )

    @pytest.mark.asyncio
    async def test_resolve_handles_provider_exception(self, logger_mock):
        """Ensure exceptions in providers are caught and logged during resolve."""

        class BrokenProvider(BaseAlertProvider):
            async def send_alert(self, alert: Alert) -> None:
                pass

            async def resolve_alert(self, dedup_key: str) -> None:
                raise RuntimeError("boom")

        svc = AlertService(providers={BrokenProvider()})
        await svc.resolve("task:test:node-1")
        logger_mock.exception.assert_called_with(
            "Failed to resolve alert via %s: dedup_key=%s",
            "BrokenProvider",
            "task:test:node-1",
        )


class TestBaseAlertProviderResolve:
    """Define tests for BaseAlertProvider.resolve_alert default no-op."""

    @pytest.mark.asyncio
    async def test_resolve_alert_is_noop_by_default(self):
        """Verify the base ``resolve_alert`` does nothing.

        Call ``BaseAlertProvider.resolve_alert`` directly (unbound) so the
        ``DummyProvider`` override is bypassed.
        """
        provider = DummyProvider()
        provider.resolved = []
        await BaseAlertProvider.resolve_alert(provider, "some-key")
        assert provider.resolved == []
