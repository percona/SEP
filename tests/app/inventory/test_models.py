"""Test inventory model validators and enums."""

import pytest
from pydantic import ValidationError

from app.inventory.models import NodeWrite, ServiceTypeEnum, SourceEnum


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
        }
