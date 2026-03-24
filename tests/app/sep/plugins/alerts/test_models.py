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

"""Define tests for the app.sep.plugins.alerts.models module."""

import pytest
import yaml
from pydantic import ValidationError

from app.sep.plugins.alerts.backup import AlertBackup
from app.sep.plugins.alerts.models import (
    AlertSeverity,
    AlertTemplate,
    ServiceType,
    to_pmm_template_yaml,
)

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

    @pytest.mark.parametrize(
        ("member", "expected"),
        [
            (ServiceType.GENERIC, "Generic"),
            (ServiceType.MYSQL, "MySQL"),
            (ServiceType.MONGODB, "MongoDB"),
            (ServiceType.POSTGRESQL, "PostgreSQL"),
        ],
    )
    def test_label_returns_correct_product_name(
        self, member: ServiceType, expected: str
    ) -> None:
        """Assert `label` returns the correctly capitalized product name."""
        assert member.label == expected


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


class TestAlertBackup:
    """Test AlertBackup SQLModel fields and serialization."""

    def test_alert_backup_fields(self) -> None:
        """Assert AlertBackup stores data and metadata as JSON-compatible dicts."""
        backup = AlertBackup(
            data={"templates": [{"name": "t1"}], "rules": []},
            metadata_={"template_count": 1, "rule_count": 0},
        )
        assert backup.data["templates"] == [{"name": "t1"}]
        assert backup.metadata_["template_count"] == 1
        assert backup.metadata_["rule_count"] == 0

    def test_alert_backup_tablename(self) -> None:
        """Assert AlertBackup uses the ``alert_backup`` table name."""
        assert AlertBackup.__tablename__ == "alert_backup"


class TestToPmmTemplateYaml:
    """Test the to_pmm_template_yaml conversion function."""

    def test_output_structure_matches_pmm_format(self) -> None:
        """Assert the YAML output contains the expected PMM template structure."""
        template = AlertTemplate.model_validate(_valid_template_data())
        result = to_pmm_template_yaml(template)
        parsed = yaml.safe_load(result)

        assert "templates" in parsed
        assert len(parsed["templates"]) == 1

        pmm_tmpl = parsed["templates"][0]
        assert pmm_tmpl["name"] == "High CPU"
        assert pmm_tmpl["version"] == 1
        assert pmm_tmpl["summary"] == template.summary
        assert pmm_tmpl["expr"] == template.expression
        assert pmm_tmpl["for"] == "300s"
        assert pmm_tmpl["severity"] == "warning"
        assert pmm_tmpl["labels"] == {}
        assert pmm_tmpl["annotations"]["summary"] == template.summary
        assert pmm_tmpl["annotations"]["description"] == template.description

    def test_severity_uses_string_value(self) -> None:
        """Assert the severity field is serialized as a plain string value."""
        template = AlertTemplate.model_validate(
            _valid_template_data(severity="critical")
        )
        result = to_pmm_template_yaml(template)
        parsed = yaml.safe_load(result)
        assert parsed["templates"][0]["severity"] == "critical"
