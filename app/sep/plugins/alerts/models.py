"""Define Pydantic models for alert templates."""

from enum import StrEnum

from pydantic import BaseModel, field_validator


class ServiceType(StrEnum):
    """Enumerate the supported service types for alert templates.

    :cvar GENERIC: Generic service type.
    :vartype GENERIC: str
    :cvar MYSQL: MySQL service type.
    :vartype MYSQL: str
    :cvar MONGODB: MongoDB service type.
    :vartype MONGODB: str
    :cvar POSTGRESQL: PostgreSQL service type.
    :vartype POSTGRESQL: str
    """

    GENERIC = "generic"
    MYSQL = "mysql"
    MONGODB = "mongodb"
    POSTGRESQL = "postgresql"


class AlertSeverity(StrEnum):
    """Enumerate the supported severity levels for alert templates.

    :cvar INFO: Informational severity.
    :vartype INFO: str
    :cvar WARNING: Warning severity.
    :vartype WARNING: str
    :cvar CRITICAL: Critical severity.
    :vartype CRITICAL: str
    """

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertTemplate(BaseModel):
    """Represent a static, file-backed alert template definition.

    :param name: The display name of the alert.
    :type name: str
    :param service_type: The service category this alert applies to.
    :type service_type: ServiceType
    :param expression: The PromQL expression used to evaluate the alert condition.
        Must be non-empty after stripping whitespace.
    :type expression: str
    :param default_threshold: The default numeric threshold value for the alert.
    :type default_threshold: float
    :param severity: The severity level of the alert.
    :type severity: AlertSeverity
    :param description: A human-readable description of what the alert detects.
    :type description: str
    :param summary: A short summary template for alert notifications.
    :type summary: str
    """

    name: str
    service_type: ServiceType
    expression: str
    default_threshold: float
    severity: AlertSeverity
    description: str
    summary: str

    @field_validator("expression", mode="after")
    @classmethod
    def validate_expression_non_empty(cls, v: str) -> str:
        """Validate that the PromQL expression is non-empty after stripping whitespace.

        :param v: The expression string to validate.
        :type v: str
        :return: The stripped expression string.
        :rtype: str
        :raises ValueError: If the expression is blank after stripping whitespace.
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("expression must not be blank")
        return stripped
