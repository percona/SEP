"""Define models for the SEP app."""

from typing import Any

from pydantic import ConfigDict, BaseModel
from pydantic import field_validator
from pydantic import HttpUrl
from pydantic import model_validator

from app.core.config import BaseCaseInsensitiveModel
from app.core.fields import StrImportableModule, RequiredStr
from app.core.fields import URIPath
from app.core.utils import slugify


class Plugin(BaseCaseInsensitiveModel):
    """Represent a SEP plugin.

    This model defines the structure for a plugin, including its name, module,
    URI path, and CSS class. It includes custom validators to resolve the module
    path and set default values based on the plugin's name.

    Attributes
    ----------
    name : str
        The name of the plugin.
    module_name : StrImportableModule
        The name of the module associated with the plugin. This field is automatically
        prefixed with "app.sep.plugins." during validation.
    uri_path : HttpUrl or URIPath, optional
        The URI path where the plugin is accessible. Defaults to an empty string,
        but is automatically set to a slugified version of the plugin name if
        not provided.
    css_class : str, optional
        The CSS class associated with the plugin. Defaults to an empty string,
        but is automatically set to a slugified version of the plugin name if
        not provided.

    """

    model_config = ConfigDict(frozen=True)
    name: str
    module_name: StrImportableModule
    uri_path: HttpUrl | URIPath = ""
    css_class: str = ""

    def __hash__(self) -> int:
        return hash(self.module_name)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Plugin):
            return self.module_name == other.module_name
        raise NotImplementedError

    @field_validator("module_name", mode="before")
    @classmethod
    def resolve_module_path(cls, v: str) -> str:
        """Resolve the full module path for the plugin.

        This method takes the module name provided and prefixes it with
        "app.sep.plugins." to resolve the full import path.

        Parameters
        ----------
        v : str
            The module name to resolve.

        Returns
        -------
        str
            The full module path with the "app.sep.plugins." prefix.

        """
        return f"app.sep.plugins.{v}"

    @model_validator(mode="before")
    @classmethod
    def _set_default_from_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and (name := data.get("name")):
            slug = slugify(name)
            data["uri_path"] = data.get("uri_path") or f"/{slug}"
            data["css_class"] = data.get("css_class") or slug
        return data


class AltersCreate(BaseModel):
    """Represent an Alters creation form.

    Attributes
    ----------
    task_name : str
        The name of the task to be created.
    hostname : str
        The target hostname for the task execution.
    connect_to : str
        The connection type, which could be a hostname or `localhost`.
    schema_name : str
        The database schema name on which the task will operate.
    table_name : str
        The table name within the schema to be altered.
    recursion_method : str
        The method for handling recursion.
    alter : str
        The specific alter command to be executed.
    dsn_table : str, optional
        The DSN table for recursion method when using `dsn`.
        Defaults to an empty string.

    """
    task_name: RequiredStr
    hostname: RequiredStr
    connect_to: RequiredStr
    schema_name: RequiredStr
    table_name: RequiredStr
    recursion_method: RequiredStr
    alter: RequiredStr
    dsn_table: str = ""
