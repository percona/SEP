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
"""Assert an image ships the app set its own baked profile implies.

``verify_image_apps.sh`` pipes this into the image's own interpreter, so the
artifact that gets published is what is checked rather than a rebuild of it.
Only the standard library and ``yaml`` are importable here: the image carries no
repository checkout.

The expected set is re-derived from the baked profile rather than imported from
``restrict_apps``, which the build deletes from the image. A check that imported
the code producing the tree could only ever agree with it.
"""

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

APP_HOME = Path("/home/sep/app")
"""The image's application root, holding both the baked profile and the tree.

Written literally rather than read from ``$APP_HOME`` so a moved root fails on a
missing ``settings.yaml`` instead of being followed silently.
"""

INFRASTRUCTURE_PACKAGES = frozenset({"framework", "shared"})
"""Packages the strip retains that are not activatable apps.

Declared here rather than imported from ``restrict_apps``, for the reason the
module docstring gives. ``tests/sidecar/test_app_strip.py`` pins the two copies
equal, so the independence costs no drift.
"""

LOOSE_MODULE = "labels.py"
"""A module sitting directly at the apps root, which the strip must not remove."""


def activated_apps(profile: Path) -> frozenset[str]:
    """Return the app module names the baked profile activates.

    :param profile: The baked settings profile.
    :return: The ``SEP.APPS`` module names.
    :raises OSError: When the profile cannot be read.
    :raises yaml.YAMLError: When the profile is not parseable YAML.
    :raises KeyError: When the profile carries no activation list, or an entry
        in it declares no module name.
    """
    document: dict[str, Any] = yaml.safe_load(profile.read_text(encoding="utf-8"))
    return frozenset(
        entry["MODULE_NAME"] for entry in document["default"]["SEP"]["APPS"]
    )


def present_packages(apps_root: Path) -> frozenset[str]:
    """Return the app package directories the image ships.

    The bytecode cache is not filtered out: the strip removes it along with the
    unshipped packages, so an exact comparison keeps that guarded.

    :param apps_root: The image's ``app/sep/apps`` directory.
    :return: Every directory name directly under it.
    :raises OSError: When ``apps_root`` cannot be listed.
    """
    return frozenset(child.name for child in apps_root.iterdir() if child.is_dir())


def retained_packages(profile: Path) -> frozenset[str]:
    """Return the packages a stripped image is expected to keep.

    :param profile: The baked settings profile.
    :return: The activated apps plus the infrastructure packages.
    :raises OSError: When the profile cannot be read.
    :raises yaml.YAMLError: When the profile is not parseable YAML.
    :raises KeyError: When the profile carries no activation list, or an entry
        in it declares no module name.
    """
    return activated_apps(profile) | INFRASTRUCTURE_PACKAGES


def restricted_problems(profile: Path, apps_root: Path) -> list[str]:
    """Report how a restricted image's app tree departs from its baked profile.

    :param profile: The baked settings profile.
    :param apps_root: The image's ``app/sep/apps`` directory.
    :return: One entry per departure, empty when the tree matches.
    :raises OSError: When the profile cannot be read or ``apps_root`` cannot be
        listed.
    :raises yaml.YAMLError: When the profile is not parseable YAML.
    :raises KeyError: When the profile carries no activation list, or an entry
        in it declares no module name.
    """
    expected = retained_packages(profile)
    present = present_packages(apps_root)

    problems: list[str] = []
    if present != expected:
        problems.append(f"expected {sorted(expected)}, found {sorted(present)}")
    if not (apps_root / LOOSE_MODULE).is_file():
        problems.append(f"the apps-root loose module {LOOSE_MODULE} did not survive")
    return problems


def unrestricted_problems(profile: Path, apps_root: Path) -> list[str]:
    """Report whether an unrestricted image's app tree looks stripped.

    At least one package outside the baked profile's retained set must survive,
    which is what "the strip did not run" means for an image that ships every
    app.

    :param profile: The baked settings profile.
    :param apps_root: The image's ``app/sep/apps`` directory.
    :return: One entry when nothing outside the retained set survives, empty
        otherwise.
    :raises OSError: When the profile cannot be read or ``apps_root`` cannot be
        listed.
    :raises yaml.YAMLError: When the profile is not parseable YAML.
    :raises KeyError: When the profile carries no activation list, or an entry
        in it declares no module name.
    """
    expected = retained_packages(profile)
    present = present_packages(apps_root)

    if present - expected:
        return []
    return [
        f"no package outside the baked profile's retained set survived, so this "
        f"image was stripped: found {sorted(present)} within {sorted(expected)}"
    ]


def main() -> None:
    """Compare the running image's app tree against its baked profile.

    Prints the verified app set on success so a build log records which set was
    asserted, and so a caller can tell a real pass from a checker that never ran.

    :raises SystemExit: With the joined problems when the tree does not match.
    :raises Exception: Propagates every failure the comparison reports —
        ``OSError``, ``yaml.YAMLError`` and ``KeyError`` — so an unreadable or
        malformed profile fails the step loudly.
    """
    checks = {
        "restricted": restricted_problems,
        "unrestricted": unrestricted_problems,
    }
    parser = argparse.ArgumentParser(prog="verify_image_apps", description=__doc__)
    parser.add_argument("mode", choices=tuple(checks))
    parser.add_argument("--app-home", type=Path, default=APP_HOME)
    arguments = parser.parse_args()

    profile = arguments.app_home / "settings.yaml"
    apps_root = arguments.app_home / "app" / "sep" / "apps"

    problems = checks[arguments.mode](profile, apps_root)
    if problems:
        sys.exit("\n".join(problems))

    present = sorted(present_packages(apps_root))
    print(
        f"verified {arguments.mode}: {len(present)} app packages ({', '.join(present)})"
    )


if __name__ == "__main__":
    main()
