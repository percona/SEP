"""Define tests for the app.sep.plugins.alerts.models module."""

import pytest
from pydantic import ValidationError

from app.sep.plugins.alerts.models import AlertSeverity, AlertTemplate, ServiceType

_THRESHOLD = 80.0


def _valid_template_data(**overrides: object) -> dict:
    data = {
        "name": "High CPU",
        "service_type": "generic",
        "expression": "100 - (avg by(instance)(rate(node_cpu_seconds_total{mode='idle'}[5m])) * 100) > 80",
        "default_threshold": _THRESHOLD,
        "severity": "warning",
        "description": "CPU usage is above threshold.",
        "summary": "High CPU usage on {{ $labels.instance }}",
    }
    data.update(overrides)
    return data


class TestServiceType:
    """Test the ServiceType enum."""

    def test_valid_values(self) -> None:
        """Assert all four service type values are defined correctly."""
        assert ServiceType.GENERIC == "generic"
        assert ServiceType.MYSQL == "mysql"
        assert ServiceType.MONGODB == "mongodb"
        assert ServiceType.POSTGRESQL == "postgresql"


class TestAlertSeverity:
    """Test the AlertSeverity enum."""

    def test_valid_values(self) -> None:
        """Assert all three severity values are defined correctly."""
        assert AlertSeverity.INFO == "info"
        assert AlertSeverity.WARNING == "warning"
        assert AlertSeverity.CRITICAL == "critical"


class TestAlertTemplate:
    """Test AlertTemplate Pydantic model validation."""

    def test_valid_model(self) -> None:
        """Assert a fully specified template parses without error."""
        template = AlertTemplate.model_validate(_valid_template_data())
        assert template.name == "High CPU"
        assert template.service_type == ServiceType.GENERIC
        assert template.severity == AlertSeverity.WARNING
        assert template.default_threshold == _THRESHOLD

    def test_missing_name_raises(self) -> None:
        """Assert ValidationError is raised when name is absent."""
        data = _valid_template_data()
        del data["name"]
        with pytest.raises(ValidationError):
            AlertTemplate.model_validate(data)

    def test_missing_expression_raises(self) -> None:
        """Assert ValidationError is raised when expression is absent."""
        data = _valid_template_data()
        del data["expression"]
        with pytest.raises(ValidationError):
            AlertTemplate.model_validate(data)

    def test_missing_service_type_raises(self) -> None:
        """Assert ValidationError is raised when service_type is absent."""
        data = _valid_template_data()
        del data["service_type"]
        with pytest.raises(ValidationError):
            AlertTemplate.model_validate(data)

    def test_missing_severity_raises(self) -> None:
        """Assert ValidationError is raised when severity is absent."""
        data = _valid_template_data()
        del data["severity"]
        with pytest.raises(ValidationError):
            AlertTemplate.model_validate(data)

    def test_invalid_severity_raises(self) -> None:
        """Assert ValidationError is raised for an unrecognised severity value."""
        with pytest.raises(ValidationError):
            AlertTemplate.model_validate(_valid_template_data(severity="high"))

    def test_invalid_service_type_raises(self) -> None:
        """Assert ValidationError is raised for an unrecognised service_type value."""
        with pytest.raises(ValidationError):
            AlertTemplate.model_validate(_valid_template_data(service_type="redis"))

    def test_empty_expression_raises(self) -> None:
        """Assert ValidationError is raised when expression is an empty string."""
        with pytest.raises(ValidationError):
            AlertTemplate.model_validate(_valid_template_data(expression=""))

    def test_whitespace_only_expression_raises(self) -> None:
        """Assert ValidationError is raised when expression contains only whitespace."""
        with pytest.raises(ValidationError):
            AlertTemplate.model_validate(_valid_template_data(expression="   "))

    def test_non_numeric_threshold_raises(self) -> None:
        """Assert ValidationError is raised when default_threshold is not numeric."""
        with pytest.raises(ValidationError):
            AlertTemplate.model_validate(
                _valid_template_data(default_threshold="not-a-number")
            )

    def test_integer_threshold_is_coerced_to_float(self) -> None:
        """Assert an integer threshold is coerced to float by Pydantic."""
        template = AlertTemplate.model_validate(
            _valid_template_data(default_threshold=int(_THRESHOLD))
        )
        assert isinstance(template.default_threshold, float)
        assert template.default_threshold == _THRESHOLD
