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
"""Cover the app-package strip the restricted embedded image runs."""

import shutil
import sys
from collections.abc import Iterable
from configparser import ConfigParser
from pathlib import Path

import pytest
import yaml

from app import BASE_DIR
from sidecar import verify_image_apps
from sidecar.restrict_apps import activated_apps, INFRASTRUCTURE_PACKAGES, restrict
from tests.app.sep import test_import_boundary
from tests.sidecar.conftest import EMBEDDED_PROFILE

APPS_ROOT = BASE_DIR / "app" / "sep" / "apps"
ALEMBIC_INI = BASE_DIR / "alembic.ini"

RESTRICTED_DEPARTURE_KINDS = 2
"""The departures a restricted tree can report: a set mismatch and a lost module."""

USAGE_EXIT_CODE = 2
"""The status ``argparse`` exits with when it refuses the command line."""

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


def _stripped_packages() -> frozenset[str]:
    """Return the app packages the app-restricted image's strip removes.

    :return: Every package directory outside the retained set.
    """
    retained = activated_apps(EMBEDDED_PROFILE) | INFRASTRUCTURE_PACKAGES
    return _real_package_names() - retained


def _owns_migrations(package_name: str) -> bool:
    """Report whether an app package roots its own Alembic branch.

    :param package_name: The app package to inspect.
    :return: Whether it holds a ``migrations/versions`` directory.
    """
    return (APPS_ROOT / package_name / "migrations" / "versions").is_dir()


def _versions_path(package_name: str) -> str:
    """Return the repo-relative path an app's ``version_locations`` entry ends with.

    :param package_name: The app package to address.
    :return: The entry's trailing path segments.
    """
    return f"app/sep/apps/{package_name}/migrations/versions"


def _sep_version_locations() -> tuple[str, ...]:
    """Return the ``[sep] version_locations`` entries as ``alembic.ini`` writes them.

    Interpolation stays off so the entries keep their ``%(here)s`` prefix, which
    resolves against ``alembic.ini`` rather than the process's directory. The
    split mirrors ``scripts/sync_alembic_version_locations.py``, which writes the
    value with a hardcoded ``:`` rather than reading ``version_path_separator``;
    that key names a separator Alembic resolves through its own keyword table, so
    reading it back is not the same as knowing how the value was joined.

    :return: The configured entries, in configuration order.
    """
    parser = ConfigParser(interpolation=None)
    parser.read(ALEMBIC_INI, encoding="utf-8")
    return tuple(parser["sep"]["version_locations"].split(":"))


def _configures_app(entries: Iterable[str], package_name: str) -> bool:
    """Report whether the entries address an app's migrations directory.

    Comparing trailing segments rather than resolved paths keeps the
    uninterpolated ``%(here)s`` prefix out of the comparison.

    :param entries: The configured ``version_locations`` entries.
    :param package_name: The app package to look for.
    :return: Whether any entry addresses that app's ``migrations/versions``.
    """
    return any(entry.endswith(_versions_path(package_name)) for entry in entries)


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
    activated = activated_apps(EMBEDDED_PROFILE)

    assert activated, "the baked profile activates no apps"
    assert "snippets" not in activated


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


def test_restrict_rejects_a_missing_infrastructure_package(tmp_path: Path):
    """Assert an absent always-retained package fails the build."""
    profile = _write_profile(tmp_path / "settings.yaml", ACTIVATED_IN_SYNTHETIC_TREE)
    apps_root = _build_apps_tree(tmp_path / "apps", ACTIVATED_IN_SYNTHETIC_TREE)

    with pytest.raises(FileNotFoundError, match="framework"):
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
    activated = activated_apps(EMBEDDED_PROFILE)

    assert activated, "the baked profile activates no apps"
    assert activated <= _real_package_names()


def test_infrastructure_packages_are_not_activatable_apps():
    """Assert the always-retained packages are disjoint from the activated ones."""
    activated = activated_apps(EMBEDDED_PROFILE)

    assert activated, "the baked profile activates no apps"
    assert INFRASTRUCTURE_PACKAGES.isdisjoint(activated)


def test_infrastructure_packages_exist_in_the_repo():
    """Assert every always-retained package is a real package directory."""
    assert _real_package_names() >= INFRASTRUCTURE_PACKAGES


def test_infrastructure_packages_match_the_import_boundary_guard():
    """Assert the strip and the import-boundary guard retain the same packages."""
    assert INFRASTRUCTURE_PACKAGES == test_import_boundary.INFRASTRUCTURE_PACKAGES


def test_stripped_apps_owning_migrations_stay_in_version_locations():
    """Assert a stripped app that owns migrations keeps its configured location."""
    entries = _sep_version_locations()
    stripped_owners = sorted(
        name for name in _stripped_packages() if _owns_migrations(name)
    )

    assert stripped_owners, (
        "no app the strip removes owns migrations, so this guard covers nothing; "
        "if the baked profile now activates every app that owns an Alembic "
        "branch, the orphan-head filter has nothing left to protect and this "
        "test should go with it"
    )
    for name in stripped_owners:
        assert _configures_app(entries, name), (
            f"The app-restricted image strips {name!r}, which owns migrations, "
            f"but [sep] version_locations in alembic.ini configures no entry "
            f"ending in {_versions_path(name)!r}. skip_unresolvable_heads in "
            f"app/sep/migrations/_orphan_heads.py tells a stripped app apart "
            f"from version skew by finding a configured location that is not a "
            f"directory on disk, so an image missing this entry hard-fails its "
            f"upgrade against a database a full image migrated. Restore the "
            f"entry rather than relaxing this test."
        )


def test_stripped_apps_owning_no_migrations_need_no_version_locations_entry():
    """Assert a stripped app that roots no branch is neither required nor listed.

    Such an app is exempt from the sibling assertion, and carries no entry of its
    own: an entry whose directory never exists on any image would report a
    stripped app to the orphan-head filter even on the unrestricted one.
    """
    entries = _sep_version_locations()
    stripped_non_owners = sorted(
        name for name in _stripped_packages() if not _owns_migrations(name)
    )

    assert stripped_non_owners, "every app the strip removes owns migrations"
    listed = [name for name in stripped_non_owners if _configures_app(entries, name)]
    assert not listed, (
        f"[sep] version_locations in alembic.ini configures entries for {listed!r}, "
        f"which the app-restricted image strips and which own no "
        f"migrations/versions directory. Those locations resolve nowhere on any "
        f"image, so skip_unresolvable_heads in "
        f"app/sep/migrations/_orphan_heads.py would read them as a stripped app "
        f"and stop treating an unresolvable revision as version skew. Drop the "
        f"entries, or restore the migrations they point at."
    )


@pytest.fixture
def stripped_tree(synthetic_tree: tuple[Path, Path]) -> tuple[Path, Path]:
    """Strip the synthetic tree and restore the loose module the strip spares.

    :param synthetic_tree: The profile and the unstripped apps root.
    :return: The same profile and the now-stripped apps root.
    """
    profile, apps_root = synthetic_tree
    restrict(profile, apps_root)
    (apps_root / verify_image_apps.LOOSE_MODULE).touch()
    return profile, apps_root


@pytest.fixture
def image_tree(tmp_path: Path) -> Path:
    """Build an app home shaped like the restricted image's, already stripped.

    ``verify_image_apps.main`` resolves both the profile and the apps root from
    one app home, so driving it needs that layout rather than the two
    independent paths ``synthetic_tree`` yields.

    :param tmp_path: The per-test temporary directory.
    :return: The app home to hand ``--app-home``.
    """
    app_home = tmp_path / "app_home"
    apps_root = _build_apps_tree(
        app_home / "app" / "sep" / "apps", _real_package_names()
    )
    profile = _write_profile(app_home / "settings.yaml", ACTIVATED_IN_SYNTHETIC_TREE)
    restrict(profile, apps_root)
    (apps_root / verify_image_apps.LOOSE_MODULE).touch()
    return app_home


def _run_main(app_home: Path, mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Invoke the checker's entry point as the piped-in script is invoked.

    :param app_home: The tree to check.
    :param mode: The direction to assert.
    :param monkeypatch: The argv patcher.
    """
    monkeypatch.setattr(
        sys, "argv", ["verify_image_apps", "--app-home", str(app_home), mode]
    )
    verify_image_apps.main()


def test_checker_activated_apps_reads_the_profile_activation_list(
    embedded_profile_data: dict,
):
    """Assert the checker's own derivation returns the baked profile's names."""
    expected = {
        entry["MODULE_NAME"]
        for entry in embedded_profile_data["default"]["SEP"]["APPS"]
    }

    assert verify_image_apps.activated_apps(EMBEDDED_PROFILE) == expected


def test_checker_infrastructure_packages_match_the_strip():
    """Assert the checker and the strip retain the same non-app packages."""
    assert verify_image_apps.INFRASTRUCTURE_PACKAGES == INFRASTRUCTURE_PACKAGES


def test_present_packages_ignores_loose_modules(tmp_path: Path):
    """Assert only directories count as shipped app packages."""
    apps_root = _build_apps_tree(tmp_path / "apps", ACTIVATED_IN_SYNTHETIC_TREE)
    for name in ("__init__.py", "labels.py", "nav_icons.py"):
        (apps_root / name).touch()

    assert verify_image_apps.present_packages(apps_root) == ACTIVATED_IN_SYNTHETIC_TREE


def test_restricted_mode_accepts_a_stripped_tree(stripped_tree: tuple[Path, Path]):
    """Assert a tree the strip just produced reports no departure."""
    profile, apps_root = stripped_tree

    assert verify_image_apps.restricted_problems(profile, apps_root) == []


def test_restricted_mode_rejects_an_unstripped_tree(synthetic_tree: tuple[Path, Path]):
    """Assert every package the strip should have removed is named."""
    profile, apps_root = synthetic_tree
    (apps_root / verify_image_apps.LOOSE_MODULE).touch()
    unshipped = _real_package_names() - (
        ACTIVATED_IN_SYNTHETIC_TREE | INFRASTRUCTURE_PACKAGES
    )

    problems = verify_image_apps.restricted_problems(profile, apps_root)

    assert unshipped, "the synthetic tree activates every package it holds"
    assert len(problems) == 1
    for name in unshipped:
        assert name in problems[0]


def test_restricted_mode_rejects_a_stripped_activated_app(
    stripped_tree: tuple[Path, Path],
):
    """Assert a package the profile activates going missing is named."""
    profile, apps_root = stripped_tree
    removed = min(ACTIVATED_IN_SYNTHETIC_TREE)
    shutil.rmtree(apps_root / removed)

    problems = verify_image_apps.restricted_problems(profile, apps_root)

    assert len(problems) == 1
    assert removed in problems[0]


def test_restricted_mode_rejects_a_missing_loose_module(
    stripped_tree: tuple[Path, Path],
):
    """Assert the apps-root loose module going missing is reported on its own."""
    profile, apps_root = stripped_tree
    (apps_root / verify_image_apps.LOOSE_MODULE).unlink()

    problems = verify_image_apps.restricted_problems(profile, apps_root)

    assert len(problems) == 1
    assert verify_image_apps.LOOSE_MODULE in problems[0]


def test_restricted_mode_reports_every_departure_at_once(
    synthetic_tree: tuple[Path, Path],
):
    """Assert a set mismatch does not mask a missing loose module."""
    profile, apps_root = synthetic_tree

    problems = verify_image_apps.restricted_problems(profile, apps_root)

    assert len(problems) == RESTRICTED_DEPARTURE_KINDS


def test_unrestricted_mode_accepts_an_unstripped_tree(
    synthetic_tree: tuple[Path, Path],
):
    """Assert a tree keeping the unactivated packages reports no departure."""
    profile, apps_root = synthetic_tree

    assert verify_image_apps.unrestricted_problems(profile, apps_root) == []


def test_unrestricted_mode_rejects_a_stripped_tree(stripped_tree: tuple[Path, Path]):
    """Assert the strip reaching an image that must ship every app is reported."""
    profile, apps_root = stripped_tree

    problems = verify_image_apps.unrestricted_problems(profile, apps_root)

    assert len(problems) == 1
    for name in ACTIVATED_IN_SYNTHETIC_TREE:
        assert name in problems[0]


def test_main_prints_the_verified_app_set(
    image_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Assert a passing run names the mode and every package it verified."""
    _run_main(image_tree, "restricted", monkeypatch)

    printed = capsys.readouterr().out
    assert "restricted" in printed
    for name in ACTIVATED_IN_SYNTHETIC_TREE | INFRASTRUCTURE_PACKAGES:
        assert name in printed


def test_main_exits_when_an_unshipped_package_survived(
    image_tree: Path, monkeypatch: pytest.MonkeyPatch
):
    """Assert a restricted image keeping an unactivated package fails the run."""
    (image_tree / "app" / "sep" / "apps" / "unshipped").mkdir()

    with pytest.raises(SystemExit) as excinfo:
        _run_main(image_tree, "restricted", monkeypatch)

    assert "unshipped" in str(excinfo.value)


def test_main_rejects_an_unknown_mode(
    image_tree: Path, monkeypatch: pytest.MonkeyPatch
):
    """Assert a mode outside the two directions is refused by the parser."""
    with pytest.raises(SystemExit) as excinfo:
        _run_main(image_tree, "bogus", monkeypatch)

    assert excinfo.value.code == USAGE_EXIT_CODE
