"""Define reusable fields and validators."""

from os import PathLike
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator
from pydantic import BeforeValidator
from pydantic import DirectoryPath
from pydantic import Field
from pydantic import FilePath
from pydantic import HttpUrl


def resolve_relative_path(v: PathLike | str) -> Path:
    """Resolve relative paths with BASE_DIR."""
    return Path(__file__).resolve().parent.parent.parent / v


def validate_http_url(v: str) -> str:
    """Validate HTTP URL as string."""
    url = HttpUrl(v)
    return str(url).strip("/")


RelativeFilePath = Annotated[
    FilePath,
    BeforeValidator(resolve_relative_path),
    Field(validate_default=True),
]
RelativeDirectoryPath = Annotated[
    DirectoryPath,
    BeforeValidator(resolve_relative_path),
    Field(validate_default=True),
]
StrHttpUrl = Annotated[str, AfterValidator(validate_http_url)]
RequiredStr = Annotated[str, Field(min_length=1)]
