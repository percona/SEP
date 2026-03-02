"""Define dependencies for the alerts plugin."""

from typing import Annotated

from fastapi import Depends

from app.sep.plugins.alerts.loader import get_alert_templates
from app.sep.plugins.alerts.models import AlertTemplate, ServiceType

AlertTemplatesDep = Annotated[
    dict[ServiceType, tuple[AlertTemplate, ...]], Depends(get_alert_templates)
]
