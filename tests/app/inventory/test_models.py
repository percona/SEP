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

"""Test inventory model validators and enums."""

import pytest
from pydantic import ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPConflictException
from app.core.utils.date_time import utc_now
from app.inventory.constants import ACTIVE_RETIREMENT_KEY
from app.inventory.crud import RetiredInclusiveServiceManager, ServiceManager
from app.inventory.models import (
    HostSystemObservationWrite,
    NodeWrite,
    Service,
    ServiceSystemObservationWrite,
    ServiceTypeEnum,
    SourceEnum,
)
from tests.app.factories import ServiceWriteFactory


class TestNodeBaseValidator:
    """Test the NodeBase.validate_external_id_source model validator."""

    def test_external_id_without_source_raises(self) -> None:
        """Raise ValidationError when external_id is set without source."""
        with pytest.raises(ValidationError, match="external_id"):
            NodeWrite(
                address="10.0.0.1",
                name="node1",
                external_id="abc",
                source=None,
            )

    def test_external_id_with_source_succeeds(self) -> None:
        """Accept external_id when source is also provided."""
        node = NodeWrite(
            address="10.0.0.1",
            name="node1",
            external_id="abc",
            source=SourceEnum.PMM,
        )
        assert node.external_id == "abc"
        assert node.source == SourceEnum.PMM

    def test_no_external_id_no_source_succeeds(self) -> None:
        """Accept when neither external_id nor source is set."""
        node = NodeWrite(
            address="10.0.0.1",
            name="node1",
        )
        assert node.external_id is None
        assert node.source is None


class TestHostSystemObservationBaseValidator:
    """Test HostSystemObservationBase.validate_at_least_one_observation_field."""

    def test_all_observation_fields_none_raises(self) -> None:
        """Raise ValidationError when os_version, packages, and config are all None."""
        with pytest.raises(ValidationError, match="os_version"):
            HostSystemObservationWrite(
                observed_at=utc_now(),
            )

    def test_os_version_only_succeeds(self) -> None:
        """Accept when only os_version is set."""
        observation = HostSystemObservationWrite(
            os_version="22.04",
            observed_at=utc_now(),
        )
        assert observation.os_version == "22.04"
        assert observation.installed_packages is None
        assert observation.config is None

    def test_installed_packages_only_succeeds(self) -> None:
        """Accept when only installed_packages is set."""
        observation = HostSystemObservationWrite(
            installed_packages=[{"name": "curl", "version": "7.81"}],
            observed_at=utc_now(),
        )
        assert observation.installed_packages == [{"name": "curl", "version": "7.81"}]

    def test_config_only_succeeds(self) -> None:
        """Accept when only config is set."""
        observation = HostSystemObservationWrite(
            config={"kernel": "5.15"},
            observed_at=utc_now(),
        )
        assert observation.config == {"kernel": "5.15"}


class TestServiceSystemObservationBaseValidator:
    """Test required fields on ServiceSystemObservationWrite."""

    def test_db_engine_version_required(self) -> None:
        """Raise ValidationError when db_engine_version is omitted."""
        with pytest.raises(ValidationError, match="db_engine_version"):
            ServiceSystemObservationWrite(observed_at=utc_now())


class TestSourceEnum:
    """Test SourceEnum values."""

    def test_values(self) -> None:
        """Assert SourceEnum has exactly the expected values."""
        assert {member.value for member in SourceEnum} == {"pmm"}


class TestServiceTypeEnum:
    """Test ServiceTypeEnum values."""

    def test_values(self) -> None:
        """Assert ServiceTypeEnum has exactly the expected values."""
        assert {member.value for member in ServiceTypeEnum} == {
            "mysql",
            "postgresql",
            "mongodb",
            "proxysql",
            "haproxy",
            "external",
            "valkey",
        }


class TestRetirementKeyUniqueness:
    """Test how ``retirement_key`` scopes the composite unique indexes.

    Uniqueness is enforced twice: by the database index, and by the Python
    duplicate check ``BaseSQLModelManager.save`` rebuilds from the model's unique
    indexes. The Python half is guarded by ``all(equal_filters.values())``, so it
    only keeps running while the discriminator stays truthy — which is why these
    tests distinguish ``HTTPConflictException`` (Python check) from the
    ``HTTPBadRequestException`` a bare index violation would produce.
    """

    @pytest.mark.asyncio
    async def test_active_service_carries_the_active_sentinel(
        self, service: Service
    ) -> None:
        """Keep the discriminator truthy on an active row."""
        assert service.retirement_key == ACTIVE_RETIREMENT_KEY
        assert ACTIVE_RETIREMENT_KEY

    @pytest.mark.asyncio
    async def test_second_active_service_on_one_key_conflicts(
        self, session: AsyncSession, service: Service
    ) -> None:
        """Reject a second active service on one node and port."""
        with pytest.raises(HTTPConflictException):
            await ServiceManager.create(
                session,
                ServiceWriteFactory.build(port=service.port),
                node_id=service.node_id,
            )

    @pytest.mark.asyncio
    async def test_replacement_over_a_tombstone_is_admitted(
        self, session: AsyncSession, service: Service
    ) -> None:
        """Admit a replacement on the node and port a tombstone still holds."""
        await ServiceManager.retire(session, service)

        replacement = await ServiceManager.create(
            session,
            ServiceWriteFactory.build(port=service.port),
            node_id=service.node_id,
        )
        assert replacement.id != service.id
        assert replacement.retirement_key == ACTIVE_RETIREMENT_KEY

    @pytest.mark.asyncio
    async def test_successive_tombstones_share_one_key(
        self, session: AsyncSession, service: Service
    ) -> None:
        """Let any number of tombstones sit on the same node and port."""
        await ServiceManager.retire(session, service)
        replacement = await ServiceManager.create(
            session,
            ServiceWriteFactory.build(port=service.port),
            node_id=service.node_id,
        )
        await ServiceManager.retire(session, replacement)

        retired = await RetiredInclusiveServiceManager.list(
            session, node_id=service.node_id
        )
        assert {row.id for row in retired} == {service.id, replacement.id}
        assert {row.retirement_key for row in retired} == {service.id, replacement.id}
