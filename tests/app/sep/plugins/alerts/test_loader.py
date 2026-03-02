"""Define tests for the app.sep.plugins.alerts.loader module."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.sep.plugins.alerts.loader import load_alert_templates
from app.sep.plugins.alerts.models import AlertTemplate, ServiceType

_ONE_TEMPLATE_PER_TYPE = 1
_TOTAL_TEMPLATES_IN_FIXTURE = len(ServiceType)


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.dump(data))


@pytest.fixture
def definitions_dir(tmp_path: Path) -> Path:
    """Return a temp directory with one YAML file per ServiceType."""
    _write_yaml(
        tmp_path / "generic_high_cpu.yaml",
        {
            "name": "High CPU",
            "service_type": "generic",
            "expression": "cpu_usage > 80",
            "default_threshold": 80.0,
            "severity": "warning",
            "description": "CPU is high.",
            "summary": "High CPU on {{ $labels.instance }}",
        },
    )
    _write_yaml(
        tmp_path / "mysql_slow_queries.yaml",
        {
            "name": "MySQL Slow Queries",
            "service_type": "mysql",
            "expression": "mysql_slow_queries > 10",
            "default_threshold": 10.0,
            "severity": "warning",
            "description": "Too many slow queries.",
            "summary": "Slow queries on {{ $labels.instance }}",
        },
    )
    _write_yaml(
        tmp_path / "mongodb_replica_lag.yaml",
        {
            "name": "MongoDB Replica Lag",
            "service_type": "mongodb",
            "expression": "mongodb_replica_lag > 30",
            "default_threshold": 30.0,
            "severity": "critical",
            "description": "Replica lag too high.",
            "summary": "Replica lag on {{ $labels.instance }}",
        },
    )
    _write_yaml(
        tmp_path / "postgresql_lock_waits.yaml",
        {
            "name": "PostgreSQL Lock Waits",
            "service_type": "postgresql",
            "expression": "pg_lock_waits > 5",
            "default_threshold": 5.0,
            "severity": "critical",
            "description": "Too many lock waits.",
            "summary": "Lock waits on {{ $labels.instance }}",
        },
    )
    return tmp_path


class TestLoadAlertTemplates:
    """Test the load_alert_templates loader function."""

    def test_reads_all_yamls_from_dir(self, definitions_dir: Path) -> None:
        """Assert all YAML files in the directory are loaded."""
        result = load_alert_templates(definitions_dir)
        total = sum(len(templates) for templates in result.values())
        assert total == _TOTAL_TEMPLATES_IN_FIXTURE

    def test_groups_by_service_type(self, definitions_dir: Path) -> None:
        """Assert each service type has exactly one template from the fixture."""
        result = load_alert_templates(definitions_dir)
        assert len(result[ServiceType.GENERIC]) == _ONE_TEMPLATE_PER_TYPE
        assert len(result[ServiceType.MYSQL]) == _ONE_TEMPLATE_PER_TYPE
        assert len(result[ServiceType.MONGODB]) == _ONE_TEMPLATE_PER_TYPE
        assert len(result[ServiceType.POSTGRESQL]) == _ONE_TEMPLATE_PER_TYPE

    def test_all_service_types_present_in_result(self, definitions_dir: Path) -> None:
        """Assert the result contains a key for every ServiceType."""
        result = load_alert_templates(definitions_dir)
        assert set(result.keys()) == set(ServiceType)

    def test_returned_items_are_alert_templates(self, definitions_dir: Path) -> None:
        """Assert every value in the result is an AlertTemplate instance."""
        result = load_alert_templates(definitions_dir)
        for templates in result.values():
            for template in templates:
                assert isinstance(template, AlertTemplate)

    def test_empty_dir_returns_empty_lists(self, tmp_path: Path) -> None:
        """Assert an empty directory returns a mapping with empty lists."""
        result = load_alert_templates(tmp_path)
        assert all(len(v) == 0 for v in result.values())
        assert set(result.keys()) == set(ServiceType)

    def test_invalid_yaml_raises_validation_error(self, tmp_path: Path) -> None:
        """Assert a ValidationError is raised when a YAML file has invalid data."""
        (tmp_path / "bad.yaml").write_text(
            yaml.dump({"name": "Bad", "service_type": "invalid_type"})
        )
        with pytest.raises(ValidationError):
            load_alert_templates(tmp_path)

    def test_lru_cache_returns_same_object(self, definitions_dir: Path) -> None:
        """Assert repeated calls with the same path return the cached object."""
        result1 = load_alert_templates(definitions_dir)
        result2 = load_alert_templates(definitions_dir)
        assert result1 is result2
