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

"""Cover the app scaffolder in-process across all three flavors.

Each flavor test scaffolds a throwaway app into the *real* source tree (the
registry hardcodes the ``app.sep.apps.<name>`` import path, so a generated
app must live there to import), builds a fresh registry from the short
``MODULE_NAME``, runs the conformance detectors, and exercises the derived
router through the contract client — then removes the generated package, test
package, and ``sys.modules`` entries in a ``finally``. ``settings.yaml`` is never
mutated in place: the ``tmp_settings`` fixture points the engine at a per-test
copy, so the throwaway registration cannot dirty the worktree or race a parallel
worker.
"""

import importlib
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, FastAPI, status
from fastapi.testclient import TestClient

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.requests.remote_api import RemoteAPI
from app.sep.apps.framework import scaffold
from app.sep.apps.framework.apps import TaskExecutionApp
from app.sep.apps.framework.base import BaseApp
from app.sep.apps.framework.conformance import (
    check_capability_route_consistency,
    check_route_collisions,
    check_schema_derivation_succeeds,
    check_view_fields_reference_real_fields,
)
from app.sep.apps.framework.registry import build_app_registry
from app.sep.config import App
from app.sep.deps import get_api_authenticated_user, IsApiAuthenticated
from tests.app.sep.apps.framework.contract_suite import (
    app_base_url,
    build_contract_client,
    build_valid_create_body,
)
from tests.app.sep.apps.framework.kit import (
    MockInventoryAPI,
    MockTaskAPI,
    SEEDED_TASK_NAME,
)


@pytest.fixture
def tmp_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a per-test ``settings.yaml`` copy the engine writes to instead."""
    copy = tmp_path / "settings.yaml"
    copy.write_text(scaffold.SETTINGS_FILE.read_text())
    monkeypatch.setattr(scaffold, "SETTINGS_FILE", copy)
    return copy


@contextmanager
def _scaffolded(
    name: str, flavor: scaffold.Flavor
) -> Iterator[scaffold.ScaffoldResult]:
    """Yield a scaffolded ``name``, removing the trees and module entries on exit."""
    try:
        yield scaffold.scaffold_app(name, flavor)
    finally:
        shutil.rmtree(scaffold.PLUGINS_DIR / name, ignore_errors=True)
        shutil.rmtree(scaffold.TESTS_DIR / name, ignore_errors=True)
        for module in list(sys.modules):
            if module == f"app.sep.apps.{name}" or module.startswith(
                f"app.sep.apps.{name}."
            ):
                del sys.modules[module]
        importlib.invalidate_caches()


def _task_conformance(app: TaskExecutionApp) -> list[str]:
    """Return every conformance violation for a derived task/script app."""
    return [
        *check_capability_route_consistency(app),
        *check_view_fields_reference_real_fields(app),
        *check_schema_derivation_succeeds(app),
    ]


def _mount_api_first(app_def: BaseApp, user: CasdoorUser) -> TestClient:
    """Mount a ``BaseApp``'s API router behind the production auth guard."""
    apps_router = APIRouter(prefix="/apps")
    apps_router.include_router(app_def.api_router, prefix=app_def.uri_path)
    api_router = APIRouter(prefix="/api", dependencies=[IsApiAuthenticated])
    api_router.include_router(apps_router)
    fastapi_app = FastAPI()
    fastapi_app.include_router(api_router)
    fastapi_app.dependency_overrides[get_api_authenticated_user] = lambda: user
    return TestClient(fastapi_app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "bad_name", ["My App!", "123app", "", "demo-app", "___", "class", "Demo"]
)
def test_rejects_invalid_name(bad_name: str) -> None:
    """Reject names that are not lowercase Python identifiers, keywords, or empty."""
    with pytest.raises(ValueError, match="invalid app name"):
        scaffold.validate_name(bad_name)


@pytest.mark.parametrize(
    "good_name", ["demo_task", "myapp", "_scaffold_smoke_task", "app2"]
)
def test_accepts_valid_name(good_name: str) -> None:
    """Accept lowercase identifiers, including a leading underscore."""
    scaffold.validate_name(good_name)


def test_type_defaults_to_task() -> None:
    """Assert ``--type`` defaults to the ``task`` flavor when omitted."""
    args = scaffold.build_parser().parse_args(["--name", "demo"])

    assert args.type == scaffold.Flavor.TASK


def test_unknown_flavor_rejected() -> None:
    """Reject an unknown ``--type`` value at the argparse boundary."""
    with pytest.raises(SystemExit):
        scaffold.build_parser().parse_args(["--name", "demo", "--type", "bogus"])


def test_settings_insertion_is_idempotent() -> None:
    """Insert a disabled entry once; a second insert of the same name is a no-op."""
    original = scaffold.SETTINGS_FILE.read_text()

    once, changed_first = scaffold.insert_app_entry(original, "scaffold_idem_demo")
    twice, changed_second = scaffold.insert_app_entry(once, "scaffold_idem_demo")

    assert changed_first
    assert not changed_second
    assert twice == once
    assert once.count("MODULE_NAME: scaffold_idem_demo") == 1
    assert "      - MODULE_NAME: scaffold_idem_demo\n        ENABLED: false\n" in once


def test_insertion_fails_without_default_plugins_block() -> None:
    """Fail loudly rather than corrupt a settings file lacking the default block."""
    with pytest.raises(ValueError, match="default"):
        scaffold.insert_app_entry("development:\n  SEP:\n    APPS:\n", "demo")


def test_refuses_to_clobber_existing_plugin(tmp_settings: Path) -> None:
    """Raise before any write when the target plugin directory holds a real plugin."""
    name = "_scaffold_smoke_clobber"
    app_dir = scaffold.PLUGINS_DIR / name
    app_dir.mkdir(parents=True)
    (app_dir / "routes.py").write_text("")
    before = tmp_settings.read_text()
    try:
        with pytest.raises(FileExistsError):
            scaffold.scaffold_app(name, scaffold.Flavor.TASK)

        assert tmp_settings.read_text() == before
        assert not (scaffold.TESTS_DIR / name).exists()
    finally:
        shutil.rmtree(app_dir, ignore_errors=True)


def test_refuses_to_clobber_existing_tests_package(tmp_settings: Path) -> None:
    """Raise before any write when only the target test package holds a real plugin."""
    name = "_scaffold_smoke_clobber_tests"
    tests_dir = scaffold.TESTS_DIR / name
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_routes.py").write_text("")
    before = tmp_settings.read_text()
    try:
        with pytest.raises(FileExistsError):
            scaffold.scaffold_app(name, scaffold.Flavor.TASK)

        assert tmp_settings.read_text() == before
        assert not (scaffold.PLUGINS_DIR / name).exists()
    finally:
        shutil.rmtree(tests_dir, ignore_errors=True)


def test_empty_app_dir_does_not_block_scaffold(tmp_settings: Path) -> None:
    """Scaffold when the target app directory exists but is empty."""
    name = "_scaffold_smoke_empty_app"
    app_dir = scaffold.PLUGINS_DIR / name
    app_dir.mkdir(parents=True)
    try:
        with _scaffolded(name, scaffold.Flavor.TASK):
            assert (app_dir / "__init__.py").exists()
    finally:
        shutil.rmtree(app_dir, ignore_errors=True)


def test_pycache_only_app_dir_does_not_block_scaffold(tmp_settings: Path) -> None:
    """Scaffold when the target app directory contains only ``__pycache__/``."""
    name = "_scaffold_smoke_pycache_app"
    app_dir = scaffold.PLUGINS_DIR / name
    (app_dir / "__pycache__").mkdir(parents=True)
    try:
        with _scaffolded(name, scaffold.Flavor.TASK):
            assert (app_dir / "__init__.py").exists()
    finally:
        shutil.rmtree(app_dir, ignore_errors=True)


def test_empty_tests_dir_does_not_block_scaffold(tmp_settings: Path) -> None:
    """Scaffold when the target tests directory exists but is empty."""
    name = "_scaffold_smoke_empty_tests"
    tests_dir = scaffold.TESTS_DIR / name
    tests_dir.mkdir(parents=True)
    try:
        with _scaffolded(name, scaffold.Flavor.TASK):
            assert (tests_dir / "__init__.py").exists()
    finally:
        shutil.rmtree(tests_dir, ignore_errors=True)


def test_pycache_only_tests_dir_does_not_block_scaffold(tmp_settings: Path) -> None:
    """Scaffold when the target tests directory contains only ``__pycache__/``."""
    name = "_scaffold_smoke_pycache_tests"
    tests_dir = scaffold.TESTS_DIR / name
    (tests_dir / "__pycache__").mkdir(parents=True)
    try:
        with _scaffolded(name, scaffold.Flavor.TASK):
            assert (tests_dir / "__init__.py").exists()
    finally:
        shutil.rmtree(tests_dir, ignore_errors=True)


def test_pycache_plus_real_file_still_aborts(tmp_settings: Path) -> None:
    """Abort when the target directory has ``__pycache__/`` alongside a real file."""
    name = "_scaffold_smoke_pycache_real"
    app_dir = scaffold.PLUGINS_DIR / name
    (app_dir / "__pycache__").mkdir(parents=True)
    (app_dir / "routes.py").write_text("")
    before = tmp_settings.read_text()
    try:
        with pytest.raises(FileExistsError):
            scaffold.scaffold_app(name, scaffold.Flavor.TASK)

        assert tmp_settings.read_text() == before
    finally:
        shutil.rmtree(app_dir, ignore_errors=True)


def test_registers_app_disabled(tmp_settings: Path) -> None:
    """Write the registration entry disabled under the default ``SEP.APPS``."""
    name = "_scaffold_smoke_disabled"
    with _scaffolded(name, scaffold.Flavor.TASK):
        assert (
            f"      - MODULE_NAME: {name}\n        ENABLED: false\n"
            in tmp_settings.read_text()
        )


def test_summary_points_to_app_manager_without_changelog(
    tmp_settings: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Assert the summary points at the Admin App Manager and omits a changelog command."""
    name = "_scaffold_smoke_summary"
    try:
        assert scaffold.main(["--name", name, "--type", "task"]) == 0
        out = capsys.readouterr().out
        assert "Admin App Manager" in out
        assert "changelog" not in out.lower()
    finally:
        shutil.rmtree(scaffold.PLUGINS_DIR / name, ignore_errors=True)
        shutil.rmtree(scaffold.TESTS_DIR / name, ignore_errors=True)


def test_summary_notes_preexisting_registration(
    tmp_settings: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Report the registration as pre-existing when the settings entry already exists."""
    name = "_scaffold_smoke_preregistered"
    tmp_settings.write_text(
        scaffold.insert_app_entry(tmp_settings.read_text(), name)[0]
    )
    try:
        assert scaffold.main(["--name", name, "--type", "task"]) == 0
        out = capsys.readouterr().out
        assert "already registered" in out.lower()
        assert "Admin App Manager" in out
    finally:
        shutil.rmtree(scaffold.PLUGINS_DIR / name, ignore_errors=True)
        shutil.rmtree(scaffold.TESTS_DIR / name, ignore_errors=True)


def test_main_reports_missing_plugins_block_without_traceback(
    tmp_settings: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit non-zero with a clean error, not a traceback, when registration fails."""
    name = "_scaffold_smoke_noblock"
    tmp_settings.write_text("development:\n  SEP:\n    APPS:\n")
    try:
        assert scaffold.main(["--name", name, "--type", "task"]) == 1
        assert "error:" in capsys.readouterr().err
    finally:
        shutil.rmtree(scaffold.PLUGINS_DIR / name, ignore_errors=True)
        shutil.rmtree(scaffold.TESTS_DIR / name, ignore_errors=True)


def test_task_flavor_scaffolds_conformant_app(
    tmp_settings: Path, regular_user: CasdoorUser
) -> None:
    """Assert a scaffolded ``task`` app imports, conforms, and serves its CRUD surface."""
    name = "_scaffold_smoke_task"
    with _scaffolded(name, scaffold.Flavor.TASK):
        importlib.import_module(f"app.sep.apps.{name}")
        registry = build_app_registry([App(module_name=name)])
        app = registry.get(name)
        assert isinstance(app, TaskExecutionApp)
        assert app.jinja_router is None
        assert not _task_conformance(app)
        assert not check_route_collisions(registry)

        tasks_api = MockTaskAPI()
        tasks_api.seed_task(SEEDED_TASK_NAME, owner=app.owner)
        client = build_contract_client(
            app,
            user=regular_user,
            tasks_api=tasks_api,
            inventory_api=MockInventoryAPI(),
        )
        base = app_base_url(app)

        assert client.get(f"{base}/schema").status_code == status.HTTP_200_OK
        assert isinstance(client.get(f"{base}/").json(), list)
        body = build_valid_create_body(app)
        assert client.post(f"{base}/", json=body).status_code == status.HTTP_201_CREATED


def test_script_flavor_scaffolds_snippet_routes(
    tmp_settings: Path, regular_user: CasdoorUser
) -> None:
    """Assert a scaffolded ``script`` app derives the ``/snippet/*`` routes, no Jinja."""
    name = "_scaffold_smoke_script"
    with _scaffolded(name, scaffold.Flavor.SCRIPT):
        importlib.import_module(f"app.sep.apps.{name}")
        registry = build_app_registry([App(module_name=name)])
        app = registry.get(name)
        assert isinstance(app, TaskExecutionApp)
        assert app.jinja_router is None
        assert not _task_conformance(app)

        tasks_api = AsyncMock(spec=RemoteAPI)
        tasks_api.get.return_value = {"items": [], "total": 0}
        tasks_api.post.return_value = {"id": 1}
        client = build_contract_client(app, user=regular_user, tasks_api=tasks_api)
        base = app_base_url(app)

        assert client.get(f"{base}/schema").status_code == status.HTTP_200_OK
        assert (
            client.get(
                f"{base}/snippet/schema", params={"snippet_filename": "sample.sh"}
            ).status_code
            == status.HTTP_200_OK
        )
        assert (
            client.post(
                f"{base}/snippet/execute",
                params={"snippet_filename": "sample.sh"},
                json={"executor_host": "exec-1", "args": {"message": "hi"}},
            ).status_code
            == status.HTTP_201_CREATED
        )


def test_base_flavor_scaffolds_api_first_app(
    tmp_settings: Path, regular_user: CasdoorUser
) -> None:
    """Assert a scaffolded API-first ``base`` app exposes ``/schema`` and a sample route."""
    name = "_scaffold_smoke_base"
    with _scaffolded(name, scaffold.Flavor.BASE):
        importlib.import_module(f"app.sep.apps.{name}")
        registry = build_app_registry([App(module_name=name)])
        app = registry.get(name)
        assert app is not None
        assert app.jinja_router is None
        assert app.api_router is not None
        assert not check_route_collisions(registry)

        client = _mount_api_first(app, regular_user)

        assert client.get(f"/api/apps/{name}/schema").status_code == status.HTTP_200_OK
        assert client.get(f"/api/apps/{name}/").status_code == status.HTTP_200_OK
