"""Define models for the Backups plugin."""

from enum import auto, IntEnum, StrEnum
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import EmptyStrToNone, EnumFieldMixin, RequiredStr

class BackupType(EnumFieldMixin, StrEnum):
    """Backup types."""

    PGBACKREST = "P"
