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

"""Tests for the snapshot-building cache layer."""

import logging
from string import Template

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.alerts.config import AlertSettings
from app.core.alerts.models import BaseAlertProvider
from app.core.settings_override.cache import build_snapshot
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum, SettingOverride
from app.sep.config import SEPSettings
from app.tasks.config import PreExecutionCheckMode, TasksSettings


async def _insert(session: AsyncSession, **kwargs: object) -> None:
    """Insert a setting override row via the manager."""
    await SettingsOverrideManager.create(session, SettingOverride(**kwargs))


@pytest.mark.asyncio
async def test_empty_table_yields_empty_snapshot(session: AsyncSession) -> None:
    """An empty override table produces an empty snapshot."""
    snapshot = await build_snapshot(session, SEPSettings)
    assert dict(snapshot) == {}


@pytest.mark.asyncio
async def test_active_hot_row_appears_in_snapshot(session: AsyncSession) -> None:
    """Active rows whose key is HOT are surfaced through the snapshot."""
    await _insert(
        session,
        setting_class=SettingClassEnum.SEP_SETTINGS,
        key="CONNECTIVITY_CHECK_DEFAULT",
        value=False,
        is_active=True,
    )
    snapshot = await build_snapshot(session, SEPSettings)
    assert snapshot["CONNECTIVITY_CHECK_DEFAULT"] is False


@pytest.mark.asyncio
async def test_inactive_rows_skipped(session: AsyncSession) -> None:
    """Rows with ``is_active=False`` do not enter the snapshot."""
    await _insert(
        session,
        setting_class=SettingClassEnum.SEP_SETTINGS,
        key="CONNECTIVITY_CHECK_DEFAULT",
        value=False,
        is_active=False,
    )
    snapshot = await build_snapshot(session, SEPSettings)
    assert "CONNECTIVITY_CHECK_DEFAULT" not in snapshot


@pytest.mark.asyncio
async def test_non_hot_field_skipped_with_warning(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """A row for a NOT_OVERRIDABLE field is skipped and a warning is logged."""
    caplog.set_level(logging.WARNING, logger="app.core.settings_override.cache")
    await _insert(
        session,
        setting_class=SettingClassEnum.SEP_SETTINGS,
        key="PROXY_HEADERS",
        value=True,
        is_active=True,
    )
    snapshot = await build_snapshot(session, SEPSettings)
    assert "PROXY_HEADERS" not in snapshot
    assert any("non-HOT" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_unknown_field_skipped_with_warning(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """A row for a field that does not exist on the model is skipped."""
    caplog.set_level(logging.WARNING, logger="app.core.settings_override.cache")
    await _insert(
        session,
        setting_class=SettingClassEnum.SEP_SETTINGS,
        key="DOES_NOT_EXIST",
        value=True,
        is_active=True,
    )
    snapshot = await build_snapshot(session, SEPSettings)
    assert "DOES_NOT_EXIST" not in snapshot
    assert any("unknown field" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_coerces_int_for_positive_int_field(session: AsyncSession) -> None:
    """A JSON int round-trips to ``PositiveInt`` for ``ARTIFACT_DOWNLOAD_TTL``."""
    override_ttl = 120
    await _insert(
        session,
        setting_class=SettingClassEnum.SEP_SETTINGS,
        key="ARTIFACT_DOWNLOAD_TTL",
        value=override_ttl,
    )
    snapshot = await build_snapshot(session, SEPSettings)
    assert snapshot["ARTIFACT_DOWNLOAD_TTL"] == override_ttl


@pytest.mark.asyncio
async def test_coerces_strenum_for_pre_execution_check(
    session: AsyncSession,
) -> None:
    """A JSON string is coerced into the StrEnum ``PreExecutionCheckMode``."""
    await _insert(
        session,
        setting_class=SettingClassEnum.TASKS_SETTINGS,
        key="PRE_EXECUTION_CONNECTIVITY_CHECK",
        value="block",
    )
    snapshot = await build_snapshot(session, TasksSettings)
    assert snapshot["PRE_EXECUTION_CONNECTIVITY_CHECK"] is PreExecutionCheckMode.BLOCK


@pytest.mark.asyncio
async def test_coercion_failure_skipped_and_logged(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """A row whose value fails Pydantic coercion is dropped with a warning."""
    caplog.set_level(logging.WARNING, logger="app.core.settings_override.cache")
    await _insert(
        session,
        setting_class=SettingClassEnum.SEP_SETTINGS,
        key="ARTIFACT_DOWNLOAD_TTL",
        value="not-a-number",
    )
    snapshot = await build_snapshot(session, SEPSettings)
    assert "ARTIFACT_DOWNLOAD_TTL" not in snapshot
    assert any("coercion" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_dict_for_scalar_field_skipped(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """A JSON object override for a scalar field is dropped (nested overrides out of scope)."""
    caplog.set_level(logging.WARNING, logger="app.core.settings_override.cache")
    await _insert(
        session,
        setting_class=SettingClassEnum.SEP_SETTINGS,
        key="CONNECTIVITY_CHECK_DEFAULT",
        value={"nested": True},
    )
    snapshot = await build_snapshot(session, SEPSettings)
    assert "CONNECTIVITY_CHECK_DEFAULT" not in snapshot
    assert any("coercion" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_positive_int_constraint_rejects_zero(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """``PositiveInt`` constraint metadata is preserved across coercion.

    ``ARTIFACT_DOWNLOAD_TTL`` is annotated ``PositiveInt`` (= ``Annotated[int,
    Gt(0)]``). The bare-annotation coercion would accept ``0`` because
    ``TypeAdapter(int)`` drops the constraint, leaving issued tokens to
    expire immediately. The cache preserves the constraint and rejects.
    """
    caplog.set_level(logging.WARNING, logger="app.core.settings_override.cache")
    await _insert(
        session,
        setting_class=SettingClassEnum.SEP_SETTINGS,
        key="ARTIFACT_DOWNLOAD_TTL",
        value=0,
    )
    snapshot = await build_snapshot(session, SEPSettings)
    assert "ARTIFACT_DOWNLOAD_TTL" not in snapshot
    assert any("coercion" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_positive_int_constraint_rejects_negative(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """Negative integers are rejected for ``PositiveInt`` fields."""
    caplog.set_level(logging.WARNING, logger="app.core.settings_override.cache")
    await _insert(
        session,
        setting_class=SettingClassEnum.TASKS_SETTINGS,
        key="STALENESS_THRESHOLD_SECONDS",
        value=-1,
    )
    snapshot = await build_snapshot(session, TasksSettings)
    assert "STALENESS_THRESHOLD_SECONDS" not in snapshot
    assert any("coercion" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_other_entries_remain_after_failure(session: AsyncSession) -> None:
    """A single coercion failure does not drop other valid entries."""
    await _insert(
        session,
        setting_class=SettingClassEnum.SEP_SETTINGS,
        key="ARTIFACT_DOWNLOAD_TTL",
        value="not-a-number",
    )
    await _insert(
        session,
        setting_class=SettingClassEnum.SEP_SETTINGS,
        key="CONNECTIVITY_CHECK_DEFAULT",
        value=False,
    )
    snapshot = await build_snapshot(session, SEPSettings)
    assert snapshot == {"CONNECTIVITY_CHECK_DEFAULT": False}


@pytest.mark.asyncio
async def test_providers_materialized_via_owning_model(session: AsyncSession) -> None:
    """``PROVIDERS`` snapshots a ``set`` of providers built by the before-validator."""
    await _insert(
        session,
        setting_class=SettingClassEnum.ALERT_SETTINGS,
        key="PROVIDERS",
        value=[{"PROVIDER": "pagerduty", "routing_key": "abc123"}],
    )
    snapshot = await build_snapshot(session, AlertSettings)
    providers = snapshot["PROVIDERS"]
    assert isinstance(providers, set)
    assert all(isinstance(provider, BaseAlertProvider) for provider in providers)


@pytest.mark.asyncio
async def test_invalid_providers_value_logged_and_skipped(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """A before-validator ``ValueError`` is caught, logged, and the row skipped."""
    caplog.set_level(logging.WARNING, logger="app.core.settings_override.cache")
    await _insert(
        session,
        setting_class=SettingClassEnum.ALERT_SETTINGS,
        key="PROVIDERS",
        value=[{"routing_key": "no-provider-key"}],
    )
    snapshot = await build_snapshot(session, AlertSettings)
    assert "PROVIDERS" not in snapshot
    assert any("coercion" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_footer_template_materialized_to_template(session: AsyncSession) -> None:
    """``FOOTER_TEMPLATE`` snapshots a ``Template`` without crashing the build."""
    await _insert(
        session,
        setting_class=SettingClassEnum.SEP_SETTINGS,
        key="FOOTER_TEMPLATE",
        value="$summary v$version",
    )
    snapshot = await build_snapshot(session, SEPSettings)
    assert isinstance(snapshot["FOOTER_TEMPLATE"], Template)
    assert snapshot["FOOTER_TEMPLATE"].template == "$summary v$version"


@pytest.mark.asyncio
async def test_invalid_footer_template_value_logged_and_skipped(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-string ``FOOTER_TEMPLATE`` override is caught, logged, and skipped."""
    caplog.set_level(logging.WARNING, logger="app.core.settings_override.cache")
    await _insert(
        session,
        setting_class=SettingClassEnum.SEP_SETTINGS,
        key="FOOTER_TEMPLATE",
        value=123,
    )
    snapshot = await build_snapshot(session, SEPSettings)
    assert "FOOTER_TEMPLATE" not in snapshot
    assert any("coercion" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_nomad_materialized_to_diff_stable_fingerprint(
    session: AsyncSession,
) -> None:
    """``NOMAD`` snapshots a plain dict equal across two consecutive builds."""
    await _insert(
        session,
        setting_class=SettingClassEnum.TASKS_SETTINGS,
        key="NOMAD",
        value={"endpoint": "https://nomad.example.org"},
    )
    first = await build_snapshot(session, TasksSettings)
    second = await build_snapshot(session, TasksSettings)
    assert isinstance(first["NOMAD"], dict)
    assert first["NOMAD"] == second["NOMAD"]
