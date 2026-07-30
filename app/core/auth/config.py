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

"""Define authentication-provider configuration."""

import logging
from enum import Enum
from typing import Any, ClassVar, Self

from pydantic import model_validator
from pydantic_settings import SettingsConfigDict

from app.core.auth.base import BaseAuthProvider
from app.core.auth.providers.casdoor.provider import CasdoorAuthProvider
from app.core.auth.providers.grafana.provider import GrafanaAuthProvider
from app.core.config import BaseYamlSettings
from app.core.utils import import_var

logger = logging.getLogger(__name__)


class AuthProviderEnum(Enum):
    """Define an enumeration for authentication providers.

    Built-in members map a provider name to its class. ``CUSTOM`` is a sentinel
    that selects an out-of-tree provider by importable class path
    (``PROVIDER_CLASS``) instead of a built-in class.
    """

    CASDOOR = CasdoorAuthProvider
    GRAFANA = GrafanaAuthProvider
    CUSTOM = "custom"


class _LegacyCasdoorSettings(BaseYamlSettings):
    """Define the reader for the deprecated top-level ``CASDOOR`` config.

    Reuse the standard settings sources (env ``CASDOOR__*`` and the top-level
    ``CASDOOR:`` YAML block) so the legacy value parses identically to how it did
    before ``CASDOOR`` moved under ``AUTH.PROVIDER``. Read it as a raw mapping,
    not a constructed provider, so a partial legacy value (e.g. leftover
    ``CASDOOR__*`` secrets whose structure has moved to ``AUTH.PROVIDER``) is
    detected without failing construction before the shim decides whether to use
    or ignore it.

    :param CASDOOR: The raw legacy Casdoor config, or ``None`` when unset.
    """

    CASDOOR: dict[str, Any] | None = None


def _read_legacy_casdoor() -> dict[str, Any] | None:
    """Read the deprecated top-level ``CASDOOR`` config, or ``None`` when unset.

    :return: The raw legacy Casdoor config mapping, or ``None``.
    """
    return _LegacyCasdoorSettings().CASDOOR


class AuthSettings(BaseYamlSettings):
    """Define authentication configuration.

    Auth has exactly one active provider, so ``PROVIDER`` is a single-entry map
    ``{<name>: <config>}`` keyed by the provider name (canonical env
    ``AUTH__PROVIDER__<NAME>__*``). The name resolves to a provider class via
    :class:`AuthProviderEnum` -- a built-in member, or ``CUSTOM`` carrying an
    importable ``PROVIDER_CLASS``.

    :cvar SETTINGS_PREFIXES: The settings prefixes for auth configuration.
    :param PROVIDER: The single active provider, keyed by name.
    """

    model_config = SettingsConfigDict(
        **{**BaseYamlSettings.model_config, "arbitrary_types_allowed": True}
    )
    SETTINGS_PREFIXES: ClassVar[list[str]] = ["AUTH"]
    PROVIDER: dict[str, BaseAuthProvider] = {}

    @model_validator(mode="before")
    @classmethod
    def _resolve_provider(cls, data: Any) -> Any:
        """Fold in the legacy ``CASDOOR`` config and resolve provider classes.

        Run a fixed sequence -- no reliance on cross-validator ordering:

        1. When the deprecated top-level ``CASDOOR`` config is present, log a
           deprecation warning and reconcile it with ``PROVIDER``: merge it under
           the ``casdoor`` entry (legacy values fill gaps; explicit
           ``AUTH.PROVIDER`` values win on conflict), adding the entry when no
           provider is configured. If a *non-casdoor* provider is configured
           instead, ignore the legacy config.
        2. Drop any entry whose value is ``None`` -- an overlay can set
           ``<name>: null`` to remove a provider the ``default`` settings block
           merged in. The drop runs after the legacy fold above, so an explicit
           ``null`` wins over a legacy ``CASDOOR`` resurrection.
        3. Resolve each remaining entry's class via :class:`AuthProviderEnum` (a
           built-in member, or ``CUSTOM`` via ``import_var(PROVIDER_CLASS)``) and
           construct the provider.

        :param data: The raw settings input.
        :return: The input with ``PROVIDER`` mapped to constructed providers.
        :raises ValueError: Propagates from ``_resolve_entry`` for an
            unresolvable provider entry.
        """
        if not isinstance(data, dict):
            return data
        provider = dict(data.get("PROVIDER") or {})
        legacy = _read_legacy_casdoor()
        if legacy:
            casdoor_key = next(
                (key for key in provider if key.lower() == "casdoor"), None
            )
            if provider and casdoor_key is None:
                logger.warning(
                    "Ignoring the deprecated top-level CASDOOR config because a "
                    "non-casdoor provider is configured; migrate to "
                    "AUTH__PROVIDER__CASDOOR__*."
                )
            else:
                logger.warning(
                    "The top-level CASDOOR config is deprecated; migrate to "
                    "AUTH__PROVIDER__CASDOOR__* (AUTH.PROVIDER.CASDOOR)."
                )
                if casdoor_key is None:
                    provider["casdoor"] = legacy
                elif isinstance(provider[casdoor_key], dict):
                    provider[casdoor_key] = {**legacy, **provider[casdoor_key]}
        return {
            **data,
            "PROVIDER": {
                name: cls._resolve_entry(name, entry)
                for name, entry in provider.items()
                if entry is not None
            },
        }

    @staticmethod
    def _resolve_entry(name: str, entry: Any) -> BaseAuthProvider:
        """Resolve one ``PROVIDER`` entry to a constructed provider instance.

        :param name: The provider name (the map key).
        :param entry: The provider config dict, or an already-constructed
            provider instance.
        :return: The constructed provider instance.
        :raises ValueError: When ``name`` is not a known provider, or a
            ``CUSTOM`` entry omits ``PROVIDER_CLASS``.
        """
        if isinstance(entry, BaseAuthProvider):
            return entry
        entry = dict(entry)
        try:
            member = AuthProviderEnum[name.upper()]
        except KeyError:
            available = ", ".join(
                sorted(member.name.lower() for member in AuthProviderEnum)
            )
            raise ValueError(
                f"Unknown auth provider {name!r}; available: {available}."
            ) from None
        if member is AuthProviderEnum.CUSTOM:
            class_key = next(
                (key for key in entry if key.upper() == "PROVIDER_CLASS"), None
            )
            class_path = entry.pop(class_key) if class_key else None
            if not class_path:
                raise ValueError(
                    "A CUSTOM auth provider requires PROVIDER_CLASS "
                    "(an importable BaseAuthProvider subclass path)."
                )
            provider_class = import_var(class_path)
        else:
            provider_class = member.value
        return provider_class.model_validate(entry)

    @model_validator(mode="after")
    def _exactly_one_provider(self) -> Self:
        """Require exactly one configured provider.

        :return: The validated settings instance.
        :raises ValueError: When zero or more than one provider is configured.
        """
        if len(self.PROVIDER) != 1:
            raise ValueError(
                "Exactly one auth provider must be configured; got "
                f"{len(self.PROVIDER)} ({sorted(self.PROVIDER)})."
            )
        return self

    @property
    def active_provider(self) -> BaseAuthProvider:
        """Return the single active authentication provider.

        :return: The active provider.
        """
        return next(iter(self.PROVIDER.values()))


auth_settings = AuthSettings()


def get_active_auth_provider() -> BaseAuthProvider:
    """Return the active authentication provider.

    :return: The single configured authentication provider.
    """
    return auth_settings.active_provider


_REMOVED_AUTH_USER_MODEL_DEFAULT = "app.models.CasdoorUser"


class _LegacyAuthUserModelSettings(BaseYamlSettings):
    """Define the reader for the removed ``AUTH_USER_MODEL`` setting.

    :param AUTH_USER_MODEL: The removed setting's value, or ``None`` when unset.
    """

    AUTH_USER_MODEL: str | None = None


def detect_removed_auth_user_model() -> None:
    """Reject non-default ``AUTH_USER_MODEL`` overrides and warn on the removal.

    ``Settings`` uses ``extra="ignore"``, so a stale ``AUTH_USER_MODEL`` in the
    environment or YAML is silently dropped. Read it explicitly: emit a
    deprecation warning when the (default) value is present, and fail fast when
    it names a non-default class -- a deliberate override that would otherwise be
    ignored.

    :raises ValueError: When ``AUTH_USER_MODEL`` names a non-default class.
    """
    legacy = _LegacyAuthUserModelSettings().AUTH_USER_MODEL
    if not legacy:
        return
    if legacy != _REMOVED_AUTH_USER_MODEL_DEFAULT:
        raise ValueError(
            f"AUTH_USER_MODEL is removed but is set to a non-default class "
            f"{legacy!r}. Select a provider via AUTH__PROVIDER__* instead "
            f"(e.g. AUTH__PROVIDER__CUSTOM__PROVIDER_CLASS)."
        )
    logger.warning(
        "AUTH_USER_MODEL is removed and its value is ignored; select a provider "
        "via AUTH__PROVIDER__* (AUTH.PROVIDER)."
    )
