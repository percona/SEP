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
"""Tests for the app-package strip the restricted embedded image runs."""

from collections.abc import Iterable
from pathlib import Path

import pytest
import yaml

from app import BASE_DIR
from sidecar.restrict_apps import activated_apps, INFRASTRUCTURE_PACKAGES, restrict
from tests.sidecar.conftest import EMBEDDED_PROFILE

APPS_ROOT = BASE_DIR / "app" / "sep" / "apps"

ACTIVATED_IN_SYNTHETIC_TREE = frozenset({"inventory", "atw", "mysql_backups"})
"""The apps the synthetic-tree profiles activate.

Held separate from the baked profile's own list so a change to what the image
ships cannot quietly turn the synthetic-tree assertions into tautologies.
"""


def _real_package_names() -> frozenset[str]:
    """Return the app package directory names present in the repository.

    The bytecode cache is excluded so a synthetic tree built from this set is
    the same whether or not the suite has already run against the real one.

    :return: Every package directory under ``app/sep/apps``.
    """
    return frozenset(
        child.name
        for child in APPS_ROOT.iterdir()
        if child.is_dir() and child.name != "__pycache__"
    )


def _write_profile(path: Path, module_names: Iterable[str]) -> Path:
    """Write a settings profile activating ``module_names``.

    :param path: The file to write.
    :param module_names: The apps the profile activates.
    :return: The written profile.
    """
    document = {
        "default": {"SEP": {"APPS": [{"MODULE_NAME": name} for name in module_names]}}
    }
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def _build_apps_tree(root: Path, package_names: Iterable[str]) -> Path:
    """Build a synthetic apps root holding a package per name.

    :param root: The directory to create and populate.
    :param package_names: The package directories to create.
    :return: The populated apps root.
    """
    root.mkdir(parents=True)
    for name in package_names:
        (root / name).mkdir()
        (root / name / "__init__.py").touch()
    return root


@pytest.fixture
def synthetic_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Build a profile and an apps root mirroring the repository's packages.

    :param tmp_path: The per-test temporary directory.
    :return: The profile and the apps root.
    """
    profile = _write_profile(tmp_path / "settings.yaml", ACTIVATED_IN_SYNTHETIC_TREE)
    apps_root = _build_apps_tree(tmp_path / "apps", _real_package_names())
    return profile, apps_root


def test_activated_apps_reads_the_profile_activation_list(embedded_profile_data: dict):
    """Assert the derivation returns the baked profile's module names."""
    expected = {
        entry["MODULE_NAME"]
        for entry in embedded_profile_data["default"]["SEP"]["APPS"]
    }

    assert activated_apps(EMBEDDED_PROFILE) == expected


def test_activated_apps_does_not_list_snippets():
    """Assert the retired snippets activation stays out of the derived set."""
    assert "snippets" not in activated_apps(EMBEDDED_PROFILE)


def test_restrict_keeps_the_activated_apps_and_infrastructure(
    synthetic_tree: tuple[Path, Path],
):
    """Assert the survivors are the activated apps plus the infrastructure ones."""
    profile, apps_root = synthetic_tree

    retained = restrict(profile, apps_root)

    assert retained == ACTIVATED_IN_SYNTHETIC_TREE | INFRASTRUCTURE_PACKAGES
    for name in retained:
        assert (apps_root / name).is_dir()


def test_restrict_removes_every_other_package(synthetic_tree: tuple[Path, Path]):
    """Assert no package outside the retained set survives."""
    profile, apps_root = synthetic_tree

    retained = restrict(profile, apps_root)

    survivors = {child.name for child in apps_root.iterdir() if child.is_dir()}
    assert survivors == set(retained)


def test_restrict_keeps_the_apps_root_loose_modules(synthetic_tree: tuple[Path, Path]):
    """Assert the modules sitting directly at the apps root are not candidates."""
    profile, apps_root = synthetic_tree
    loose_modules = ("__init__.py", "labels.py", "nav_icons.py")
    for name in loose_modules:
        (apps_root / name).touch()

    restrict(profile, apps_root)

    for name in loose_modules:
        assert (apps_root / name).is_file()


def test_restrict_removes_pycache(synthetic_tree: tuple[Path, Path]):
    """Assert the bytecode cache is stripped along with the unshipped packages."""
    profile, apps_root = synthetic_tree
    (apps_root / "__pycache__").mkdir()

    restrict(profile, apps_root)

    assert not (apps_root / "__pycache__").exists()


def test_restrict_is_idempotent(synthetic_tree: tuple[Path, Path]):
    """Assert a re-run against an already-stripped tree removes nothing."""
    profile, apps_root = synthetic_tree
    first = restrict(profile, apps_root)

    second = restrict(profile, apps_root)

    assert second == first
    assert {child.name for child in apps_root.iterdir() if child.is_dir()} == set(first)


def test_restrict_rejects_an_activated_app_with_no_package(tmp_path: Path):
    """Assert an activation naming an absent package fails the build."""
    profile = _write_profile(tmp_path / "settings.yaml", ["nonexistent"])
    apps_root = _build_apps_tree(tmp_path / "apps", INFRASTRUCTURE_PACKAGES)

    with pytest.raises(FileNotFoundError, match="nonexistent"):
        restrict(profile, apps_root)


def test_restrict_rejects_a_profile_with_no_activation_list(tmp_path: Path):
    """Assert a profile carrying no activation list fails the build."""
    profile = tmp_path / "settings.yaml"
    profile.write_text(yaml.safe_dump({"default": {"SEP": {}}}), encoding="utf-8")
    apps_root = _build_apps_tree(tmp_path / "apps", INFRASTRUCTURE_PACKAGES)

    with pytest.raises(KeyError):
        restrict(profile, apps_root)


def test_every_activated_app_has_a_package_in_the_repo():
    """Assert the baked profile activates nothing the repository does not ship."""
    assert activated_apps(EMBEDDED_PROFILE) <= _real_package_names()


def test_infrastructure_packages_are_not_activatable_apps():
    """Assert the always-retained packages are disjoint from the activated ones."""
    assert INFRASTRUCTURE_PACKAGES.isdisjoint(activated_apps(EMBEDDED_PROFILE))


def test_infrastructure_packages_exist_in_the_repo():
    """Assert every always-retained package is a real package directory."""
    assert _real_package_names() >= INFRASTRUCTURE_PACKAGES
