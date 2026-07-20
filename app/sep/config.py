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

"""Define SEP settings."""

import logging
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path
from string import Template
from typing import Annotated, Any, ClassVar, Literal, Self
from urllib.parse import urlparse

from annotated_types import Gt
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from pydantic import (
    AliasChoices,
    AliasGenerator,
    BaseModel,
    computed_field,
    ConfigDict,
    Field,
    field_validator,
    HttpUrl,
    model_validator,
    PositiveInt,
    SecretStr,
)
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from pydantic_settings.sources import DotEnvSettingsSource, EnvSettingsSource

from app import BASE_DIR
from app.core.celery.models import CrontabSchedule, IntervalSchedule, Period
from app.core.config import (
    BaseYamlAppSettings,
)
from app.core.db.config import DatabaseOptions
from app.core.models import BaseCaseInsensitiveModel, BaseLowercaseModel
from app.core.requests.bundle_upload import CredentialPlacement, RESERVED_UPLOAD_FIELDS
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.settings_override.registry import (
    hot_field,
    materialize_template,
    nested_overridable_field,
)
from app.core.utils import (
    deep_dict_update,
    slugify,
)
from app.core.utils.fields import (
    CredentialHttpUrl,
    NonEmptyStr,
    RelativeDirectoryPathField,
    StrImportableAttribute,
    StrRelativePath,
    TimedeltaSeconds,
    UniqueList,
    URIPath,
)
from app.sep.apps.nav_icons import NavIcon
from app.sep.middleware import messages
from app.sep.utils.jinja import DEFAULT_FILTERS, syntax_highlight_css

logger = logging.getLogger(__name__)

_LEGACY_BACKUP_MODULE_NAMES = frozenset({"backup", "backups"})


def _module_or_package_exists(target: Path) -> bool:
    """Return whether ``target`` names a module file or package directory.

    Probe the filesystem instead of importing, so settings-construction validators
    can confirm a dotted path resolves without triggering circular imports through
    plugin ``__init__`` modules.

    :param target: The import path rendered as a filesystem path, extension omitted.
    :return: ``True`` when a ``target/__init__.py`` package or ``target.py`` module
        file exists on disk.
    """
    return (target / "__init__.py").is_file() or target.with_suffix(".py").is_file()


class App(BaseCaseInsensitiveModel):
    """Represent a SEP plugin.

    This model defines the structure for a plugin, including its name, module,
    URI path, and CSS class. It includes custom validators to resolve the module
    path and set default values based on the plugin's name.

    :param name: The name of the plugin. Optional: a MODULE_NAME-only entry
        omits it and the :class:`app.sep.apps.framework.registry.AppRegistry`
        derives descriptive metadata from the module basename instead.
    :param module_name: The name of the module associated with the plugin. This field is
        automatically prefixed with ``app.sep.apps.`` during validation.
    :param uri_path: The URI path where the plugin is accessible. Defaults to an empty
        string, but is automatically set to a slugified version of the plugin name if
        not provided.
    :param css_class: The CSS class associated with the plugin. Defaults to an empty
        string, but is automatically set to a slugified version of the plugin name if
        not provided.
    :param sidebar: Whether to add this plugin to the sidebar. Defaults to True.
    :param group: The nav group key this plugin nests under (read from YAML as
        ``GROUP``); ``None`` renders it as a top-level sidebar entry.
    :param nav_order: The plugin's sort position within the sidebar (read from
        YAML as ``NAV_ORDER``); ``None`` sorts last.
    :param react_route: The canonical React route (read from YAML as
        ``REACT_ROUTE``); ``None`` resolves to ``/apps/<key>`` in the listing.
    :param nav_icon: The sidebar icon key (read from YAML as ``NAV_ICON``),
        validated against the :class:`~app.sep.apps.nav_icons.NavIcon` vocabulary;
        an unknown value fails settings validation at load.
    :param enabled: Whether the plugin ships enabled. Read only at first-startup
        seed time to set the initial :class:`app.sep.models.AppState` row;
        defaults to ``True`` so every plugin already in ``settings.yaml`` keeps
        shipping enabled. Set ``ENABLED: false`` to seed a plugin disabled.
    :param api_router_path: Optional dot-separated import path to the plugin's
        JSON ``APIRouter`` instance (e.g. ``"app.sep.apps.checksums.api_routes.router"``).
        When set, the router is mounted under ``/api/apps/{key}`` by the
        shared API router loop. Three input states:

        * **Field omitted** — auto-derive from ``module_name`` when the
          plugin ships ``api_routes.router`` (convention).
        * **Explicit string** — use as-is; fail-fast if the path cannot be
          imported.
        * **Explicit ``null``** — opt the plugin out of the JSON API mount,
          even if a conventional module exists.
    :param celery_module_path: Optional dot-separated import path to the plugin's
        Celery task module (e.g. ``"app.sep.apps.snippets.celery"``). The path is a
        *module*, not an attribute, so it feeds the worker ``include`` list rather
        than being resolved to an object. Three input states, mirroring
        ``api_router_path``:

        * **Field omitted** — auto-derive ``<module_name>.celery`` when the plugin
          ships a ``celery.py`` (convention).
        * **Explicit string** — use as-is, filesystem-probed for existence during
          settings construction (import-free, like ``module_name``) so a typo fails
          at load rather than only when the Celery worker imports it. The path is a
          trusted operator setting at the same trust level as
          ``module_name``/``api_router_path`` and is not confined to the plugin's
          own package.
        * **Explicit ``null``** — opt the plugin out of the Celery include list,
          even if a conventional ``celery.py`` exists.
    """

    name: str | None = None
    module_name: str
    uri_path: HttpUrl | URIPath = ""
    css_class: str = ""
    sidebar: bool = True
    group: str | None = None
    nav_order: int | None = None
    react_route: URIPath | None = None
    nav_icon: NavIcon | None = None
    enabled: bool = True
    api_router_path: StrImportableAttribute | None = None
    celery_module_path: str | None = None

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, App):
            return self.module_name == other.module_name
        raise NotImplementedError

    @field_validator("module_name", mode="before")
    @classmethod
    def resolve_module_path(cls, v: str) -> str:
        """Resolve the full module path for the plugin.

        This method takes the module name provided and prefixes it with
        ``app.sep.apps.`` to resolve the full import path. Legacy MySQL
        backups plugin names (``backup``, ``backups``) are remapped to
        ``mysql_backups`` with a deprecation warning before prefixing; the
        legacy aliases will not be supported in the next version.

        :param v: The module name to resolve.
        :type v: str
        :return: The full module path with the ``app.sep.apps.`` prefix.
        :rtype: str
        """
        if v in _LEGACY_BACKUP_MODULE_NAMES:
            logger.warning(
                "App MODULE_NAME %r is deprecated; remapping to "
                "'mysql_backups'. The legacy value will not be supported "
                "in the next version — update settings.yaml to use "
                "'mysql_backups'.",
                v,
            )
            v = "mysql_backups"
        return f"app.sep.apps.{v}"

    @field_validator("module_name")
    @classmethod
    def validate_module_exists(cls, v: str) -> str:
        """Confirm the plugin module exists on disk without importing its parent.

        ``importlib`` resolution executes the parent package's ``__init__``, which
        imports the plugin route/model graph. For a nested module
        (``mysql_backups.restore``) that both cycles back through ``app.sep.deps``
        and registers cross-track models on the shared metadata while settings are
        still constructing. A filesystem probe keeps construction import-free; the
        real import happens when the registry is built, after settings are ready.

        :param v: The resolved ``app.sep.apps.``-prefixed module path.
        :return: The validated module path.
        :raises ValueError: When no module file or package exists at the path.
        """
        relative = v.removeprefix("app.sep.apps.")
        target = Path(__file__).parent / "apps" / Path(*relative.split("."))
        if _module_or_package_exists(target):
            return v
        raise ValueError(f"No module named {v}")

    @model_validator(mode="before")
    @classmethod
    def _set_default_from_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and (name := data.get("name")):
            slug = slugify(name)
            data["uri_path"] = data.get("uri_path") or f"/{slug}"
            data["css_class"] = data.get("css_class") or slug
        return data

    @model_validator(mode="after")
    def _default_api_router_from_convention(self) -> Self:
        """Auto-derive ``api_router_path`` from ``module_name`` when not set.

        Run only when the field was not present in the input data.
        ``None`` in the input is a deliberate opt-out and is preserved.

        Probe by filesystem, not by import, so that this validator can run
        during settings construction without triggering circular imports
        through plugin ``__init__`` modules. Fail-fast on a missing
        ``router`` attribute is still enforced later in
        ``build_apps_router`` via ``import_var``.

        :return: ``self`` with ``api_router_path`` populated when the
            plugin module ships an ``api_routes.py`` file.
        :rtype: Self
        """
        if "api_router_path" in self.model_fields_set:
            return self
        relative = self.module_name.removeprefix("app.sep.apps.")
        candidate_file = (
            Path(__file__).parent
            / "apps"
            / Path(*relative.split("."))
            / "api_routes.py"
        )
        if candidate_file.is_file():
            self.api_router_path = f"{self.module_name}.api_routes.router"
        return self

    @model_validator(mode="after")
    def _default_celery_module_from_convention(self) -> Self:
        """Auto-derive ``celery_module_path`` from ``module_name`` when not set.

        Run only when the field was not present in the input data. ``None`` in the
        input is a deliberate opt-out and is preserved.

        Probe by filesystem, not by import, so this validator can run during
        settings construction without triggering circular imports through plugin
        ``__init__`` modules -- exactly as ``_default_api_router_from_convention``
        does for ``api_routes.py``.

        :return: ``self`` with ``celery_module_path`` populated when the plugin
            module ships a ``celery.py`` file.
        """
        if "celery_module_path" in self.model_fields_set:
            return self
        relative = self.module_name.removeprefix("app.sep.apps.")
        candidate_file = (
            Path(__file__).parent / "apps" / Path(*relative.split(".")) / "celery.py"
        )
        if candidate_file.is_file():
            self.celery_module_path = f"{self.module_name}.celery"
        return self

    @model_validator(mode="after")
    def _validate_celery_module_exists(self) -> Self:
        """Confirm ``celery_module_path`` resolves to a module file on disk.

        The convention-derived path is set only after its own filesystem probe, but
        an explicit override skips that check, so a typo would surface only when the
        Celery worker tries to import the module. Probe by filesystem (import-free,
        consistent with ``validate_module_exists``) so a bad override fails during
        settings construction instead. The path is repo-root-relative, so an
        override is not confined to the plugin's own package.

        :return: ``self`` unchanged when the path exists or is unset.
        :raises ValueError: When the path names no module file or package on disk.
        """
        if self.celery_module_path is None:
            return self
        target = BASE_DIR / Path(*self.celery_module_path.split("."))
        if _module_or_package_exists(target):
            return self
        raise ValueError(f"No module named {self.celery_module_path}")

    @computed_field
    @property
    def router_path(self) -> str:
        """Return the plugin's router path.

        :return: The router path derived from the module name.
        :rtype: str
        """
        return f"{self.module_name}.router"


class SessionOptions(BaseModel):
    """Configuration options for a SEP session.

    :param COOKIE_NAME: The key of the authentication cookie. Defaults to "authToken".
    :type COOKIE_NAME: str
    :param MAX_AGE: Maximum age of the session cookie. Defaults to 7 days.
    :type MAX_AGE: TimedeltaSeconds
    :param SAMESITE: SameSite policy for the session cookie. Defaults to 'lax'.
    :type SAMESITE: Literal["lax", "strict", "none"]
    :param SECURE: Whether the session cookie should be accessible only via HTTPS.
        Defaults to True.
    :type SECURE: bool
    :param PATH: Cookie ``Path`` attribute. When ``None`` (the default), the
        cookie is not scoped to a specific path and the browser applies its
        default. When set, the value must start with ``/``.
    :type PATH: URIPath | None
    """

    model_config = ConfigDict(
        alias_generator=AliasGenerator(
            serialization_alias=lambda field_name: field_name.lower(),
        ),
    )
    COOKIE_NAME: str = Field(default="authToken", serialization_alias="key")
    MAX_AGE: TimedeltaSeconds = timedelta(days=7)
    SAMESITE: Literal["lax", "strict", "none"] = "lax"
    SECURE: bool = True
    PATH: URIPath | None = None


def _reject_removed_syncer_pmm(data: Any) -> Any:
    """Reject a removed per-syncer ``pmm`` override key.

    The per-syncer ``pmm:`` override was removed; PMM synchronizers now
    read the top-level ``PMM`` section directly. A leftover ``pmm`` key (any case) is
    rejected with a ``ValueError`` -- which pydantic wraps into a ``ValidationError``
    -- so upgraded deployments fail fast at startup instead of silently honoring dead
    config. ``SEPSettings.add_syncer_extra_kwargs`` re-validates each merged
    ``SyncOptions``, so a ``pmm`` carried via ``SYNCER_EXTRA_KWARGS`` is rejected there
    too.

    :param data: The raw input mapping passed to the model.
    :return: The input unchanged when no ``pmm`` key is present.
    :raises ValueError: When the input carries a ``pmm`` key (any case).
    """
    if isinstance(data, dict) and any(
        isinstance(k, str) and k.lower() == "pmm" for k in data
    ):
        raise ValueError(
            "Per-syncer 'pmm:' override is no longer honored (removed in SEP-1477); "
            "PMM synchronizers read the top-level 'PMM' section. Remove the stale "
            "'pmm' key from SEP.SYNCERS / SEP.SYNCER_EXTRA_KWARGS."
        )
    return data


class SyncerExtraKwargs(BaseLowercaseModel):
    """Global keyword arguments merged into every configured synchronizer."""

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def reject_removed_pmm(cls, data: Any) -> Any:
        """Reject a removed per-syncer ``pmm`` override key.

        :param data: The raw input mapping passed to the model.
        :return: The input unchanged when no ``pmm`` key is present.
        :raises ValueError: When the input carries a ``pmm`` key.
        """
        return _reject_removed_syncer_pmm(data)


class SyncOptions(BaseLowercaseModel):
    """Represent a synchronizer for the SEP app.

    This model represents a synchronizer component within the SEP application,
    including its importable attribute and any additional keyword arguments required for
    its operation.

    :param syncer: The importable attribute name for the synchronizer. This field is
        automatically prefixed with "app.sep.sync.syncers." during validation.
    :type syncer: StrImportableAttribute
    """

    model_config = ConfigDict(extra="allow")
    syncer: StrImportableAttribute

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, SyncOptions):
            return self.syncer == other.syncer
        raise NotImplementedError

    @model_validator(mode="before")
    @classmethod
    def reject_removed_pmm(cls, data: Any) -> Any:
        """Reject a removed per-syncer ``pmm`` override key.

        :param data: The raw input mapping passed to the model.
        :return: The input unchanged when no ``pmm`` key is present.
        :raises ValueError: When the input carries a ``pmm`` key.
        """
        return _reject_removed_syncer_pmm(data)

    @field_validator("syncer", mode="before")
    @classmethod
    def resolve_syncer_path(cls, v: str) -> str:
        """Resolve the full path for the syncer.

        Prefix the provided synchronizer name with "app.sep.sync.syncers." to form the
        complete import path.

        :param v: The base syncer name provided.
        :type v: str
        :return: The fully qualified path for the synchronizer.
        :rtype: str
        """
        root = "app.sep.sync.syncers."
        if not v.startswith(root):
            v = root + v
        return v


class ReportScheduleEntry(BaseLowercaseModel):
    """A single scheduled report generation with its own cadence and parameters.

    :param schedule: When to run (interval or crontab).
    :type schedule: IntervalSchedule | CrontabSchedule
    :param since: Prometheus-style start offset for the report window.
    :type since: str
    :param until: Prometheus-style end offset for the report window.
    :type until: str
    :param full: Whether to generate a full report.
    :type full: bool
    :param refresh: Re-run advisor checks before collecting results.
    :type refresh: bool
    :param sections: Optional list of report sections to include.
    :type sections: list[str] | None
    :param upload: Upload the generated report to ServiceNow after generation.
        Requires global upload credentials to be configured.
    :type upload: bool
    """

    schedule: IntervalSchedule | CrontabSchedule
    since: str = "now-7d"
    until: str = "now"
    full: bool = True
    refresh: bool = False
    sections: list[str] | None = None
    upload: bool = False


class HealthReportSettings(BaseLowercaseModel):
    """Configuration for the Health & Security Report plugin.

    :param schedules: List of report generation schedules, each with its own
        cadence and parameters.  Empty by default (no periodic generation).
    :type schedules: list[ReportScheduleEntry]
    :param upload: Master toggle for ServiceNow upload.  When ``False``
        (the default) uploading is disabled regardless of other fields.
    :type upload: bool
    :param endpoint: The ServiceNow upload API URL.
    :type endpoint: str | None
    :param api_key: API key for authenticating with the upload endpoint.
    :type api_key: SecretStr | None
    :param client_id: Customer identifier sent with each upload.
    :type client_id: str | None
    :param artifact_dir: Directory where rendered PDF artifacts are staged for
        download. Shared between the Celery worker (writer) and web (reader), so
        only lightweight job metadata transits the Celery result backend.
    :type artifact_dir: StrRelativePath
    :param artifact_ttl: Maximum age (seconds) of a staged PDF artifact before the
        cleanup task removes it. Should mirror ``CELERY.RESULT_EXPIRES`` so a
        job's metadata and its artifact expire together.
    :type artifact_ttl: PositiveInt
    :param cleanup_interval: Cadence of the ``purge_report_artifacts`` sweep that
        deletes staged PDFs older than ``artifact_ttl``.
    :type cleanup_interval: IntervalSchedule
    """

    schedules: list[ReportScheduleEntry] = []
    upload: bool = False
    endpoint: str | None = None
    api_key: SecretStr | None = None
    client_id: str | None = None
    artifact_dir: StrRelativePath = "data/health-reports"
    artifact_ttl: PositiveInt = 3600
    cleanup_interval: IntervalSchedule = IntervalSchedule(
        every=15, period=Period.MINUTES
    )

    @field_validator("endpoint", "client_id", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("endpoint", mode="after")
    @classmethod
    def _normalize_endpoint(cls, v: str | None) -> str | None:
        if v is not None:
            return v.rstrip("/")
        return v

    @field_validator("api_key", mode="before")
    @classmethod
    def _empty_secret_to_none(cls, v: Any) -> Any:
        if v is None:
            return None
        raw = v.get_secret_value() if isinstance(v, SecretStr) else v
        if isinstance(raw, str) and not raw.strip():
            return None
        return v

    @property
    def upload_disabled_reasons(self) -> list[str]:
        """Return a list of reasons why uploading is not possible.

        An empty list means upload is fully configured and ready.
        """
        if not self.upload:
            return ["Upload is disabled"]

        reasons = []
        if self.endpoint is None:
            reasons.append("Endpoint is not configured")
        else:
            parsed = urlparse(self.endpoint)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                reasons.append("Endpoint is not a valid HTTP/HTTPS address")
        if self.api_key is None:
            reasons.append("API key is not configured")
        if self.client_id is None:
            reasons.append("Client ID is not configured")
        return reasons

    @property
    def is_upload_configured(self) -> bool:
        """Return ``True`` when upload is enabled and all credentials are set."""
        return not self.upload_disabled_reasons


class BundleUploadSettings(BaseLowercaseModel):
    """Configure the generic bundle-upload client.

    :param enabled: Master toggle for bundle upload. When ``False`` (the
        default), uploading is disabled regardless of other fields.
    :param endpoint: The upload intake endpoint URL.
    :param credential: The upload credential.
    :param credential_placement: Whether the credential rides in a request header
        or a multipart form field.
    :param credential_name: The header name or form-field name carrying the
        credential.
    :param credential_scheme: The header scheme prefix (e.g. ``Bearer``); empty
        for a raw header value or a form-field credential.
    :param client_id: The customer identifier sent with each upload.
    :param metadata: Static form fields sent with every upload.
    :param response_reference_key: The top-level response key whose value is read
        into the upload result's reference.
    :param timeout: The per-request upload timeout.
    :param max_bundle_mb: The maximum accepted bundle size in megabytes.
    """

    enabled: bool = False
    endpoint: str | None = None
    credential: SecretStr | None = None
    credential_placement: CredentialPlacement = CredentialPlacement.HEADER
    credential_name: NonEmptyStr = "Authorization"
    credential_scheme: str = "Bearer"
    client_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    response_reference_key: str | None = None
    timeout: Annotated[TimedeltaSeconds, Gt(timedelta(0))] = timedelta(seconds=30)
    max_bundle_mb: PositiveInt = 100

    @field_validator("endpoint", "client_id", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("endpoint", mode="after")
    @classmethod
    def _normalize_endpoint(cls, v: str | None) -> str | None:
        if v is not None:
            return v.rstrip("/")
        return v

    @field_validator("credential", mode="before")
    @classmethod
    def _empty_secret_to_none(cls, v: Any) -> Any:
        if v is None:
            return None
        raw = v.get_secret_value() if isinstance(v, SecretStr) else v
        if isinstance(raw, str) and not raw.strip():
            return None
        return v

    @field_validator("credential_placement", mode="before")
    @classmethod
    def _normalize_placement(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.lower()
        return v

    @model_validator(mode="after")
    def _reject_field_name_collisions(self) -> Self:
        """Reject metadata / form-field-credential names that shadow reserved fields.

        The uploader always emits ``RESERVED_UPLOAD_FIELDS``; letting an operator
        name collide would silently overwrite a required field or the file part,
        so a collision fails at config load rather than at upload time.

        :return: The validated settings instance.
        """
        clashes = set(self.metadata) & RESERVED_UPLOAD_FIELDS
        if clashes:
            raise ValueError(
                f"BUNDLE_UPLOAD.metadata keys collide with reserved upload fields: "
                f"{sorted(clashes)}"
            )
        if self.credential_placement is CredentialPlacement.FORM_FIELD:
            if self.credential_name in RESERVED_UPLOAD_FIELDS:
                raise ValueError(
                    f"BUNDLE_UPLOAD.credential_name '{self.credential_name}' is a "
                    f"reserved upload field name under form-field placement"
                )
            if self.credential_name in self.metadata:
                raise ValueError(
                    f"BUNDLE_UPLOAD.credential_name '{self.credential_name}' "
                    f"duplicates a metadata field name"
                )
        return self

    @property
    def upload_disabled_reasons(self) -> list[str]:
        """Return the reasons upload is not possible; an empty list means ready."""
        if not self.enabled:
            return ["Upload is disabled"]
        reasons = []
        if self.endpoint is None:
            reasons.append("Endpoint is not configured")
        else:
            parsed = urlparse(self.endpoint)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                reasons.append("Endpoint is not a valid HTTP/HTTPS address")
        if self.credential is None:
            reasons.append("Credential is not configured")
        if self.client_id is None:
            reasons.append("Client ID is not configured")
        return reasons

    @property
    def is_upload_configured(self) -> bool:
        """Return ``True`` when upload is enabled and fully configured."""
        return not self.upload_disabled_reasons


class AppDrainSettings(BaseLowercaseModel):
    """Configure the cooperative app-drain reconciler.

    :param reconcile_interval: Cadence of the ``reconcile_disabling_apps`` safety
        net that prunes orphaned running-task rows and finalizes idle
        ``DISABLING`` apps. Defaults to every 5 minutes.
    :param stale_task_ttl: Maximum age of an
        :class:`app.sep.models.AppRunningTask` row before the reconciler treats it
        as orphaned (its task was force-killed or its worker crashed, so
        ``task_postrun`` never deleted it) and prunes it. Must exceed the longest
        expected runtime of a drainable task. Defaults to 1 hour.
    """

    reconcile_interval: IntervalSchedule = IntervalSchedule(
        every=5, period=Period.MINUTES
    )
    # Positivity uses the ``Gt`` annotation constraint rather than a
    # ``field_validator`` because runtime-override coercion re-checks
    # annotated-type constraints but does not re-run field validators; a
    # non-positive TTL would trigger the premature-pruning failure mode noted in
    # the ``stale_task_ttl`` docstring param above.
    stale_task_ttl: Annotated[TimedeltaSeconds, Gt(timedelta(0))] = timedelta(hours=1)


def _warn_legacy_apps_key() -> None:
    """Emit a deprecation warning for the legacy ``SEP.PLUGINS`` config key."""
    logger.warning(
        "The SEP.PLUGINS / SEP__PLUGINS config key is deprecated and will be "
        "removed in a future release; use SEP.APPS / SEP__APPS instead.",
    )


class SEPSettings(BaseYamlAppSettings):
    """Define settings for SEP.

    :cvar SETTINGS_PREFIXES: The prefixes for SEP-related settings in the configuration
        file. Set to ["SEP"].
    :param UVICORN_PORT: The port number used by the Uvicorn server. Defaults to 8000.
    :param SESSION: Session configuration options for the legacy ``authToken``
        cookie used by the Jinja UI.
    :param SESSION_REFRESH: Session configuration options for the SPA
        ``refreshToken`` cookie. The cookie is ``HttpOnly`` and scoped to
        ``/api/oauth`` by default. When overriding ``PATH`` via YAML or env
        vars, the value must start with ``/``.
    :param TEMPLATES_DIR: The directory containing template files. Defaults to
        ``Path("templates")``.
    :param STATIC_DIR: The directory containing static files. Defaults to
        ``Path("static")``.
    :param ALERT_DEFINITIONS_DIR: Path to the directory containing YAML alert
        definition files. When ``None``, the bundled ``alert_definitions/`` directory
        inside the alerts plugin is used.
    :param INVENTORY_ENDPOINT: The endpoint URL for the Inventory API.
    :param TASKS_ENDPOINT: The endpoint URL for the Tasks API.
    :param APPS: A list of apps used by SEP. Defaults to an empty list with
        duplicates removed.
    :param PROXY_HEADERS: Whether to use proxy headers (like ``X-Forwarded-For``).
        Defaults to ``False``.
    :param DATABASE: The database configuration options.
        Defaults to an SQLite database with the name 'sep.db'.
    :param SYNCERS: A list of synchronizers used by SEP. Defaults to an empty list with
        duplicates removed.
    :param SYNCER_EXTRA_KWARGS: Additional keyword arguments for synchronizers. Defaults
        to an empty mapping.
    :param SYNC_REFRESH_TIME: The time interval (in seconds) for browser refresh during
        synchronization. Defaults to 5 seconds.
    :param HEALTH_REPORT: Configuration for the Health & Security Report plugin.
        Upload is disabled by default.
    :param BUNDLE_UPLOAD: Configuration for the generic bundle-upload client.
        Upload is disabled by default.
    :param APP_DRAIN: Operator-tunable settings for the cooperative app-drain
        reconciler (reconcile cadence and stale running-task TTL).
    :param FOOTER_TEMPLATE: Template string for the sidebar footer text, supporting
        ``$summary`` and ``$version`` placeholders. Defaults to ``"$summary $version"``.
    :param ARTIFACT_DOWNLOAD_TTL: Maximum age (in seconds) of signed artifact download
        tokens. Defaults to 600.
    :param CONNECTIVITY_CHECK_DEFAULT: Initial state of the "Check connectivity"
        checkbox on task creation forms. When ``True``, the checkbox is pre-checked;
        when ``False`` (default), it is unchecked. Because unchecked HTML
        checkboxes submit no field, the route parameter defaults to ``False`` —
        automated clients that omit ``check_connectivity`` will skip the check
        regardless of this setting.
    :param AMBIENT_SESSION_SSO_ENABLED: Whether to sign an unauthenticated caller
        in automatically from an existing PMM/Grafana session cookie (ambient
        SSO), skipping SEP's login form. Defaults to ``False`` (opt-in). Takes
        effect only under the Grafana auth provider and requires SEP and Grafana
        to be same-site so the browser sends the session cookie to SEP.
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["SEP"]
    UVICORN_PORT: int = 8000
    SESSION: SessionOptions = nested_overridable_field(SessionOptions(), advanced=True)
    SESSION_REFRESH: SessionOptions = nested_overridable_field(
        SessionOptions(
            COOKIE_NAME="refreshToken",
            PATH="/api/oauth",
        ),
        advanced=True,
    )
    TEMPLATES_DIR: RelativeDirectoryPathField = Path("templates")
    STATIC_DIR: RelativeDirectoryPathField = Path("static")
    ALERT_DEFINITIONS_DIR: RelativeDirectoryPathField | None = None
    INVENTORY_ENDPOINT: CredentialHttpUrl = hot_field(..., advanced=True)
    TASKS_ENDPOINT: CredentialHttpUrl = hot_field(..., advanced=True)
    APPS: UniqueList[App] = Field(
        default_factory=UniqueList,
        validation_alias=AliasChoices("APPS", "PLUGINS"),
    )
    PROXY_HEADERS: bool = False
    DATABASE: DatabaseOptions = DatabaseOptions(NAME="sep.db")
    SYNCERS: UniqueList[SyncOptions] = UniqueList()
    SYNCER_EXTRA_KWARGS: SyncerExtraKwargs = SyncerExtraKwargs()
    SYNC_REFRESH_TIME: int = hot_field(5)
    HEALTH_REPORT: HealthReportSettings = HealthReportSettings()
    BUNDLE_UPLOAD: BundleUploadSettings = BundleUploadSettings()
    APP_DRAIN: AppDrainSettings = nested_overridable_field(AppDrainSettings())
    ARTIFACT_DOWNLOAD_TTL: PositiveInt = hot_field(600, advanced=True)
    CONNECTIVITY_CHECK_DEFAULT: bool = hot_field(default=True)
    AMBIENT_SESSION_SSO_ENABLED: bool = hot_field(
        default=False,
        description=(
            "Enable ambient Grafana-session SSO: sign an unauthenticated caller "
            "in automatically from an existing PMM/Grafana session cookie, "
            "skipping SEP's login form. Off by default; effective only under the "
            "Grafana auth provider and only when SEP and Grafana are same-site so "
            "the browser sends the session cookie to SEP."
        ),
    )
    FOOTER_TEMPLATE: Template = hot_field(
        Template("$summary $version"),
        materializer=materialize_template,
        advanced=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _warn_removed_pmm_frontend(cls, data: Any) -> Any:
        """Warn if the removed ``PMM_FRONTEND`` field is still set.

        :param data: The raw input data.
        :type data: Any
        :return: The input data unchanged.
        :rtype: Any
        """
        if isinstance(data, dict) and data.get("PMM_FRONTEND") is not None:
            logger.warning(
                "SEP__PMM_FRONTEND has been removed. "
                "Use PMM__FRONTEND (top-level) or SEP__PMM__FRONTEND instead.",
            )
        return data

    @model_validator(mode="before")
    @classmethod
    def _warn_legacy_plugins_key(cls, data: Any) -> Any:
        """Emit a deprecation warning when the legacy ``PLUGINS`` key is set via YAML or init.

        :param data: The raw input data.
        :return: The input data unchanged.
        """
        if isinstance(data, dict) and "PLUGINS" in data:
            _warn_legacy_apps_key()
        return data

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: EnvSettingsSource,
        dotenv_settings: DotEnvSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Emit a deprecation warning when the legacy ``SEP__PLUGINS`` env key supplies the app list.

        The before-validator covers the YAML / init path but never sees an
        env-only legacy key: the environment source keys the value by the field
        name ``APPS``, not the matched alias. Detect the stripped legacy key
        here so the deprecation warning is airtight for the env source too.

        :param settings_cls: The settings class being configured.
        :param init_settings: The init-arguments source.
        :param env_settings: The environment-variable source.
        :param dotenv_settings: The dotenv-file source.
        :param file_secret_settings: The file-secret source.
        :return: The source tuple from the base implementation, unchanged.
        """
        sources = super().settings_customise_sources(
            settings_cls,
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )
        if any(
            "plugins" in getattr(source, "env_vars", {})
            for source in (env_settings, dotenv_settings)
        ):
            _warn_legacy_apps_key()
        return sources

    @computed_field
    @cached_property
    def JINJA_ENVIRONMENT(self) -> Environment:
        """Return a Jinja2 Environment object for templates.

        This property creates, caches, and returns a
        :class:`jinja2.environment.Environment` object configured with the
        ``jinja2.ext.do`` extension, the ``syntax_highlight`` filter, and the
        ``syntax_highlight_css`` utility function as global.

        :return: The Environment configured for Jinja2.
        :rtype: Environment
        """
        env = Environment(
            loader=FileSystemLoader(sep_settings.TEMPLATES_DIR),
            autoescape=True,
            extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"],
        )
        env.filters |= DEFAULT_FILTERS
        env.globals["now"] = datetime.now
        env.globals["syntax_highlight_css"] = syntax_highlight_css
        env.globals["get_messages"] = messages.get_messages
        return env

    @computed_field
    @cached_property
    def TEMPLATES(self) -> Jinja2Templates:
        """Return a Jinja2Templates object for template rendering.

        This property creates, caches, and returns a ``Jinja2Templates`` object configured
        with the ``TEMPLATES_DIR`` directory.

        :return: The Jinja2 templates object for rendering templates.
        :rtype: Jinja2Templates
        """
        return Jinja2Templates(
            env=self.JINJA_ENVIRONMENT,
        )

    @field_validator("FOOTER_TEMPLATE", mode="before")
    @classmethod
    def coerce_footer_template(cls, v: Any) -> Any:
        """Coerce the footer template to a Template object.

        If the provided value is a string, convert it to a ``Template`` object. Else,
        return it as is.

        :param v: The footer template value to coerce.
        :type v: Any
        :return: The coerced ``Template`` object or the original input value.
        :rtype: Any
        """
        if isinstance(v, str):
            return Template(v)
        return v

    @model_validator(mode="before")
    @classmethod
    def reject_removed_sep_pmm(cls, data: Any) -> Any:
        """Reject a removed ``SEP.PMM`` section.

        ``SEP.PMM`` was removed; PMM connection/auth config now lives
        only under the top-level ``PMM`` section, and the alerts fields it used to
        carry moved to the alerts-owned ``SEP.ALERTS`` section. A leftover ``PMM``
        key under ``SEP`` (any case, including the ``SEP__PMM__*`` env-var path) is
        rejected with a ``ValueError`` -- which pydantic wraps into a
        ``ValidationError`` -- so upgraded deployments fail fast at startup instead
        of silently carrying dead config.

        :param data: The raw input mapping passed to the model.
        :return: The input unchanged when no top-level ``PMM`` key is present.
        :raises ValueError: When the input carries a ``PMM`` key.
        """
        if isinstance(data, dict) and any(
            isinstance(k, str) and k.lower() == "pmm" for k in data
        ):
            raise ValueError(
                "The 'SEP.PMM' section was removed (SEP-1477); PMM connection config "
                "now lives only under the top-level 'PMM' section, and its alerts "
                "fields moved to the 'SEP.ALERTS' section. Remove the stale 'SEP.PMM' "
                "block from settings.yaml."
            )
        return data

    @model_validator(mode="after")
    def add_syncer_extra_kwargs(self) -> Self:
        """Integrate extra keyword arguments into synchronizers.

        Merge additional keyword arguments from ``SYNCER_EXTRA_KWARGS`` into each
        synchronizer in ``SYNCERS`` and update the list accordingly.

        :return: The updated ``SEPSettings`` instance with modified ``SYNCERS``.
        :rtype: Self
        """
        syncers = UniqueList()
        extra_kwargs = self.SYNCER_EXTRA_KWARGS.model_dump(exclude_none=True)
        for syncer in self.SYNCERS:
            syncer_data = syncer.model_dump()
            deep_dict_update(syncer_data, extra_kwargs)
            syncers.append(SyncOptions.model_validate(syncer_data))
        self.SYNCERS = syncers
        return self


sep_settings: SEPSettings = OverridableSettingsProxy(
    SEPSettings, setting_class=SettingClassEnum.SEP_SETTINGS
)
