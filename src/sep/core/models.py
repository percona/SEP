"""Core models"""

from pydantic import (
    BaseModel,
    Field,
)


class Widget(BaseModel):
    """Model for dashboard widgets"""

    heading: str
    data: dict | list = []
    layout: str = Field(default="box", pattern=r"^(box|grid|table)$")
    multipart: bool = False
