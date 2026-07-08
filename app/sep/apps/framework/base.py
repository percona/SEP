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

"""Define ``BaseApp``, the uniform registry entry for a mounted SEP app."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.utils.fields import URIPath
from app.sep.apps.framework.schema import AppSchema
from app.sep.apps.nav_icons import NavIcon


class BaseApp(BaseModel):
    """Represent a mounted SEP app as a uniform registry entry.

    Authored directly by a declarative app (``app = BaseApp(...)``) or
    synthesized by :func:`app.sep.apps.framework.registry.build_app_registry`
    from a legacy ``App`` settings entry, so legacy and definition-based apps
    share one shape. ``enabled`` is an activation-list fact stamped by the
    registry rather than author-set; ``display_name`` defaults to ``name``.
    ``key`` is stamped from the module path (scoped for nested sub-apps) when
    the definition leaves it unset, but an author may set it explicitly to
    override the derivation.

    :param key: The scoped app key. Left unset, the registry stamps the
        module-path-derived key; set explicitly, the author's value wins.
    :param name: The app's internal name.
    :param display_name: The human-facing label; defaults to ``name`` when absent.
    :param uri_path: The Jinja mount prefix and sidebar link target.
    :param css_class: The sidebar CSS class.
    :param sidebar: Whether the app appears in the sidebar.
    :param group: The nav group key this app nests under; ``None`` renders it
        as a top-level sidebar entry.
    :param nav_order: The app's sort position within the sidebar; ``None`` sorts
        last.
    :param react_route: The canonical React route the shell mounts and links to;
        ``None`` resolves to ``/apps/<key>`` in the ``GET /api/apps`` response.
    :param nav_icon: The sidebar icon key; ``None`` falls back to the frontend's
        default app icon.
    :param enabled: The seed-time enabled default; stamped by the registry.
    :param custom_ui: Whether the app ships a bespoke React UI.
    :param api_router: The plugin's JSON ``APIRouter``, when it exposes one.
    :param jinja_router: The plugin's Jinja ``APIRouter``.
    :param app_schema: The plugin's schema definition, aliased ``schema`` for
        authoring; ``None`` for legacy-wrapped apps.
    :param parent_key: The key of the parent app that structurally owns this one,
        or ``None`` for a top-level app. A child is registered by its parent's
        ``child_apps`` (never a ``settings.yaml`` entry) and owns no ``AppState``
        row: its runtime enabled/lifecycle state derives from the parent's (see
        :attr:`state_key`), and it cannot be toggled independently.
    :param child_apps: Pre-built child apps this app structurally owns. The
        registry appends each right after this app and stamps its ``enabled`` from
        this app's, so a child is mounted and snapshotted exactly when its parent
        is. Each child must set ``parent_key`` to this app's key.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    key: str = ""
    name: str
    display_name: str
    uri_path: str
    css_class: str = ""
    sidebar: bool = True
    group: str | None = None
    nav_order: int | None = None
    react_route: URIPath | None = None
    nav_icon: NavIcon | None = None
    enabled: bool = True
    custom_ui: bool = False
    api_router: APIRouter | None = None
    jinja_router: APIRouter | None = None
    app_schema: AppSchema | None = Field(default=None, alias="schema")
    parent_key: str | None = None
    child_apps: tuple["BaseApp", ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _default_display_name(cls, data: Any) -> Any:
        """Set ``display_name`` to ``name`` when it was not supplied."""
        if not isinstance(data, dict):
            return data

        if data.get("display_name") is not None:
            return data

        name = data.get("name")
        if not isinstance(name, str):
            return data
        return {**data, "display_name": name}

    @property
    def state_key(self) -> str:
        """Return the app key whose ``AppState`` row governs this app's runtime state.

        A child app owns no ``AppState`` row: its enabled/lifecycle state is the
        parent's, so every state lookup resolves through ``parent_key``. A
        top-level app resolves to its own ``key``.

        :return: ``parent_key`` for a child app, otherwise ``key``.
        """
        return self.parent_key or self.key
