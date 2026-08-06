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

"""Tests for the ``BaseApp`` registry-entry definition."""

from pathlib import Path

from fastapi import APIRouter
from sqlalchemy_celery_beat.models import Period

from app.core.celery.models import IntervalSchedule
from app.sep.apps.framework.base import AppPeriodicTask, BaseApp, StaticMount


class TestBaseAppDisplayName:
    """Tests for the ``display_name``-defaults-to-``name`` behavior."""

    def test_display_name_defaults_to_name_when_omitted(self) -> None:
        """An absent ``display_name`` falls back to ``name``."""
        app = BaseApp(name="Snippet Manager", uri_path="/snippets")
        assert app.display_name == "Snippet Manager"

    def test_explicit_display_name_is_honored(self) -> None:
        """A ``display_name`` distinct from ``name`` is preserved."""
        app = BaseApp(
            name="snippets", display_name="Snippet Manager", uri_path="/snippets"
        )
        assert app.display_name == "Snippet Manager"

    def test_display_name_none_falls_back_to_name(self) -> None:
        """A ``None`` ``display_name`` falls back to ``name``."""
        app = BaseApp(name="Snippet Manager", display_name=None, uri_path="/snippets")
        assert app.display_name == "Snippet Manager"


class TestBaseAppArbitraryTypes:
    """Tests for carrying live router objects."""

    def test_accepts_live_api_router(self) -> None:
        """A live ``APIRouter`` is accepted on the router fields."""
        api_router = APIRouter()
        jinja_router = APIRouter()
        app = BaseApp(
            name="Checksums",
            uri_path="/checksums",
            api_router=api_router,
            jinja_router=jinja_router,
        )
        assert app.api_router is api_router
        assert app.jinja_router is jinja_router

    def test_router_fields_default_to_none(self) -> None:
        """Both router fields default to ``None`` when unset."""
        app = BaseApp(name="Inventory", uri_path="/inventory")
        assert app.api_router is None
        assert app.jinja_router is None


class TestBaseAppSchemaAlias:
    """Tests for the ``app_schema`` field aliased ``schema`` for authoring."""

    def test_schema_field_is_aliased(self) -> None:
        """The ``app_schema`` field carries the ``schema`` authoring alias."""
        assert BaseApp.model_fields["app_schema"].alias == "schema"

    def test_accepts_schema_alias_keyword(self) -> None:
        """A declarative author may pass the ``schema=`` alias keyword."""
        app = BaseApp(name="Checksums", uri_path="/checksums", schema=None)
        assert app.app_schema is None

    def test_schema_defaults_to_none(self) -> None:
        """A legacy-wrapped app carries no schema."""
        app = BaseApp(name="Checksums", uri_path="/checksums")
        assert app.app_schema is None


class TestBaseAppArtifactBaseDirs:
    """Cover the ``artifact_base_dirs`` registry-collected download map."""

    def test_artifact_base_dirs_defaults_to_empty(self) -> None:
        """Return an empty mapping when the field is unset."""
        app = BaseApp(name="Inventory", uri_path="/inventory")
        assert app.artifact_base_dirs == {}

    def test_artifact_base_dirs_default_is_not_shared(self) -> None:
        """Keep the default mapping distinct across instances."""
        first = BaseApp(name="Inventory", uri_path="/inventory")
        second = BaseApp(name="Checksums", uri_path="/checksums")
        assert first.artifact_base_dirs is not second.artifact_base_dirs

    def test_artifact_base_dirs_carries_thunk_declaration(self) -> None:
        """Carry a declared thunk that resolves to its ``Path`` when called."""
        app = BaseApp(
            name="Dipper",
            uri_path="/dipper",
            artifact_base_dirs={"dipper": lambda: Path("/tmp/payloads")},
        )
        assert app.artifact_base_dirs["dipper"]() == Path("/tmp/payloads")


class TestBaseAppPeriodicTaskSchedules:
    """Cover the ``periodic_task_schedules`` beat-contribution seam."""

    def test_periodic_task_schedules_defaults_to_none(self) -> None:
        """Return ``None`` when the field is unset."""
        app = BaseApp(name="Inventory", uri_path="/inventory")
        assert app.periodic_task_schedules is None

    def test_periodic_task_schedules_carries_list_declaration(self) -> None:
        """Carry a plain list of app-owned schedule specs."""
        interval = IntervalSchedule(every=10, period=Period.MINUTES)
        specs = [
            AppPeriodicTask(
                name="sep__example",
                task="example_task",
                schedule=lambda: interval,
            ),
        ]
        app = BaseApp(
            name="Example",
            uri_path="/example",
            periodic_task_schedules=specs,
        )
        assert app.periodic_task_schedules is specs
        assert app.periodic_task_schedules[0].name == "sep__example"
        assert app.periodic_task_schedules[0].schedule() == interval

    def test_periodic_task_schedules_carries_callable_declaration(self) -> None:
        """Carry a declared factory that returns specs when called."""
        interval = IntervalSchedule(every=10, period=Period.MINUTES)
        specs = [
            AppPeriodicTask(
                name="sep__example",
                task="example_task",
                schedule=lambda: interval,
            ),
        ]

        def _factory() -> list[AppPeriodicTask]:
            return specs

        app = BaseApp(
            name="Example",
            uri_path="/example",
            periodic_task_schedules=_factory,
        )
        assert app.periodic_task_schedules is _factory
        assert app.periodic_task_schedules() == specs


class TestBaseAppStaticMounts:
    """Cover the ``static_mounts`` registry-collected authenticated mounts."""

    def test_static_mounts_defaults_to_empty(self) -> None:
        """Return an empty tuple when the field is unset."""
        app = BaseApp(name="Inventory", uri_path="/inventory")
        assert app.static_mounts == ()

    def test_static_mounts_carries_declaration(self) -> None:
        """Carry a declared mount on a plain ``BaseApp``."""
        mount = StaticMount(
            path="/static/dipper",
            directory=Path("/tmp/payloads"),
            name="dipper_files",
        )
        app = BaseApp(name="Dipper", uri_path="/dipper", static_mounts=(mount,))
        assert app.static_mounts == (mount,)


class TestBaseAppUsesTaskData:
    """Cover the ``uses_task_data`` shared task-route opt-in."""

    def test_uses_task_data_defaults_to_false(self) -> None:
        """Return ``False`` when the field is unset, so the shared routes stay off."""
        app = BaseApp(name="Inventory", uri_path="/inventory")
        assert app.uses_task_data is False

    def test_uses_task_data_accepts_explicit_opt_in(self) -> None:
        """Carry an explicit opt-in on a plain ``BaseApp``."""
        app = BaseApp(name="ATW", uri_path="/atw", uses_task_data=True)
        assert app.uses_task_data is True
