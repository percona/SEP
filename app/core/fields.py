"""Define reusable fields and validators."""

import importlib.util
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


def validate_module_is_importable(v: str) -> str:
    """Validate importable module as string."""
    if importlib.util.find_spec(v) is None:
        raise ValueError(f"No module named {v}")
    return v


def validate_attribute_is_importable(v: str) -> str:
    """Validate importable module.attribute as string."""
    # TODO: Find a way to validate attribute without circular import
    if v:
        try:
            module_name, _ = v.rsplit(".", 1)
        except ValueError as exc:
            raise ValueError(
                "Must follow the format module.class",
            ) from exc
        else:
            validate_module_is_importable(module_name)
    return v


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
StrImportableModule = Annotated[str, AfterValidator(validate_module_is_importable)]
StrImportableAttribute = Annotated[
    str,
    AfterValidator(validate_attribute_is_importable),
]
RequiredStr = Annotated[str, Field(min_length=1)]
URIPath = Annotated[str, Field(pattern=r"^\/[^\s]*$")]
