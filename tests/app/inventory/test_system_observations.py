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

"""Test host and service system observation models and managers."""

from datetime import datetime, UTC

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPBadRequestException, HTTPConflictException
from app.core.utils.date_time import make_datetime_utc, utc_now
from app.inventory.crud import (
    HostSystemObservationManager,
    NodeManager,
    ServiceManager,
    ServiceSystemObservationManager,
)
from app.inventory.models import Node, Service
from tests.app.factories import (
    HostSystemObservationWriteFactory,
    ServiceSystemObservationWriteFactory,
    ServiceWriteFactory,
)

NONEXISTENT_PARENT_ID = 999_999

UPDATED_OBSERVED_AT = datetime(2026, 6, 2, 15, 30, 0, tzinfo=UTC)


def _assert_observed_at_equal(actual: datetime, expected: datetime) -> None:
    """Compare observed_at values (SQLite may return naive UTC datetimes)."""
    assert make_datetime_utc(actual) == make_datetime_utc(expected)


@pytest.mark.asyncio
async def test_dangling_parent_fk_rejected_by_database(
    session: AsyncSession,
) -> None:
    """Assert the DB foreign-key constraint rejects a dangling parent reference.

    ``create`` does not run the child manager's parent pre-check, so this writes a
    child row pointing at a nonexistent parent. With SQLite foreign-key enforcement
    enabled on the test engine (``PRAGMA foreign_keys=ON``), the database rejects the
    insert; ``save`` surfaces that ``DatabaseError`` as ``HTTPBadRequestException``.
    Without enforcement the insert would silently succeed and this would not raise.
    """
    with pytest.raises(HTTPBadRequestException):
        await ServiceManager.create(
            session,
            ServiceWriteFactory.build(),
            node_id=NONEXISTENT_PARENT_ID,
        )


@pytest.mark.asyncio
async def test_host_observation_create_roundtrip(
    session: AsyncSession,
    node: Node,
) -> None:
    """Assert host observation create round-trips field values via manager."""
    write = HostSystemObservationWriteFactory.build()
    created = await HostSystemObservationManager.create(
        session,
        write,
        node_id=node.id,
    )
    fetched = await HostSystemObservationManager.get(session, id=created.id)
    assert fetched is not None
    assert fetched.node_id == node.id
    assert fetched.os_version == write.os_version
    assert fetched.installed_packages == write.installed_packages
    assert fetched.config == write.config
    _assert_observed_at_equal(fetched.observed_at, write.observed_at)


@pytest.mark.asyncio
async def test_service_observation_create_roundtrip(
    session: AsyncSession,
    service: Service,
) -> None:
    """Assert service observation create round-trips field values via manager."""
    write = ServiceSystemObservationWriteFactory.build()
    created = await ServiceSystemObservationManager.create(
        session,
        write,
        service_id=service.id,
    )
    fetched = await ServiceSystemObservationManager.get(session, id=created.id)
    assert fetched is not None
    assert fetched.service_id == service.id
    assert fetched.db_engine_version == write.db_engine_version
    _assert_observed_at_equal(fetched.observed_at, write.observed_at)


@pytest.mark.asyncio
async def test_duplicate_host_observation_raises_conflict(
    session: AsyncSession,
    node: Node,
) -> None:
    """Raise HTTPConflictException when creating a second host observation for the same node."""
    await HostSystemObservationManager.create(
        session,
        HostSystemObservationWriteFactory.build(),
        node_id=node.id,
    )
    with pytest.raises(HTTPConflictException):
        await HostSystemObservationManager.create(
            session,
            HostSystemObservationWriteFactory.build(os_version="24.04"),
            node_id=node.id,
        )


@pytest.mark.asyncio
async def test_duplicate_service_observation_raises_conflict(
    session: AsyncSession,
    service: Service,
) -> None:
    """Raise HTTPConflictException when creating a second service observation for the same service."""
    await ServiceSystemObservationManager.create(
        session,
        ServiceSystemObservationWriteFactory.build(),
        service_id=service.id,
    )
    with pytest.raises(HTTPConflictException):
        await ServiceSystemObservationManager.create(
            session,
            ServiceSystemObservationWriteFactory.build(db_engine_version="8.4.0"),
            service_id=service.id,
        )


@pytest.mark.asyncio
async def test_host_observation_update_changes_fields(
    session: AsyncSession,
    node: Node,
) -> None:
    """Assert host observation update replaces snapshot fields."""
    existing = await HostSystemObservationManager.create(
        session,
        HostSystemObservationWriteFactory.build(),
        node_id=node.id,
    )
    updated = await HostSystemObservationManager.update(
        session,
        existing,
        HostSystemObservationWriteFactory.build(
            os_version="24.04",
            installed_packages=[{"name": "percona-server-server", "version": "8.4.0"}],
            config={"role": "replica"},
            observed_at=UPDATED_OBSERVED_AT,
        ),
        node_id=node.id,
    )
    assert updated.os_version == "24.04"
    assert updated.installed_packages == [
        {"name": "percona-server-server", "version": "8.4.0"}
    ]
    assert updated.config == {"role": "replica"}
    _assert_observed_at_equal(updated.observed_at, UPDATED_OBSERVED_AT)


@pytest.mark.asyncio
async def test_service_observation_update_changes_fields(
    session: AsyncSession,
    service: Service,
) -> None:
    """Assert service observation update replaces snapshot fields."""
    existing = await ServiceSystemObservationManager.create(
        session,
        ServiceSystemObservationWriteFactory.build(),
        service_id=service.id,
    )
    updated = await ServiceSystemObservationManager.update(
        session,
        existing,
        ServiceSystemObservationWriteFactory.build(
            db_engine_version="8.4.0-1",
            observed_at=UPDATED_OBSERVED_AT,
        ),
        service_id=service.id,
    )
    assert updated.db_engine_version == "8.4.0-1"
    _assert_observed_at_equal(updated.observed_at, UPDATED_OBSERVED_AT)


@pytest.mark.asyncio
async def test_host_observation_json_roundtrip(
    session: AsyncSession,
    node: Node,
) -> None:
    """Assert JSON columns round-trip list and dict payloads."""
    packages = [
        {"name": "openssl", "version": "3.0.2"},
        {"name": "curl", "version": "7.81"},
    ]
    config = {"packages": {"held": ["linux-image-generic"]}, "enabled": True}
    write = HostSystemObservationWriteFactory.build(
        installed_packages=packages,
        config=config,
        observed_at=utc_now(),
    )
    created = await HostSystemObservationManager.create(
        session,
        write,
        node_id=node.id,
    )
    fetched = await HostSystemObservationManager.get(session, id=created.id)
    assert fetched is not None
    assert fetched.installed_packages == packages
    assert fetched.config == config


@pytest.mark.asyncio
async def test_host_observation_cascade_on_node_delete(
    session: AsyncSession,
    node: Node,
) -> None:
    """Delete node and assert host system observation is removed."""
    observation = await HostSystemObservationManager.create(
        session,
        HostSystemObservationWriteFactory.build(),
        node_id=node.id,
    )
    await NodeManager.delete(session, node)
    assert await HostSystemObservationManager.first(session, id=observation.id) is None


@pytest.mark.asyncio
async def test_service_observation_cascade_on_service_delete(
    session: AsyncSession,
    node: Node,
    service: Service,
) -> None:
    """Delete service and assert service observation is removed while host observation remains."""
    host_observation = await HostSystemObservationManager.create(
        session,
        HostSystemObservationWriteFactory.build(),
        node_id=node.id,
    )
    service_observation = await ServiceSystemObservationManager.create(
        session,
        ServiceSystemObservationWriteFactory.build(),
        service_id=service.id,
    )
    await ServiceManager.delete(session, service)
    assert (
        await ServiceSystemObservationManager.first(
            session,
            id=service_observation.id,
        )
        is None
    )
    remaining_host = await HostSystemObservationManager.first(
        session,
        id=host_observation.id,
    )
    assert remaining_host is not None
    assert remaining_host.node_id == node.id
