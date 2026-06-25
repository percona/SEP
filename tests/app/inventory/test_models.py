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

from app.core.utils.date_time import utc_now
from app.inventory.models import (
    HostSystemObservationWrite,
    NodeWrite,
    ServiceSystemObservationWrite,
    ServiceTypeEnum,
    SourceEnum,
)


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
