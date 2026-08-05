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
"""Strip the app packages the embedded settings profile does not activate.

Run as a build step in ``Containerfile.sidecar`` when the ``SEP_RESTRICT_APPS``
build argument is ``1``. The baked profile's activation list is the only
declaration of which apps the restricted image ships, so the retained set is
derived from it rather than repeated in the build recipe.
"""

import argparse
import shutil
from pathlib import Path

import yaml

INFRASTRUCTURE_PACKAGES = frozenset({"framework", "shared"})
"""Packages the strip retains that are not activatable apps.

The SEP core reaches ``framework`` and the backup apps reach ``shared``, so
neither is removable even though neither appears in ``SEP.APPS``.
"""


def activated_apps(profile: Path) -> set[str]:
    """Return the app module names the baked profile activates.

    :param profile: The baked settings profile.
    :return: The ``SEP.APPS`` module names.
    :raises OSError: When the profile cannot be read.
    :raises yaml.YAMLError: When the profile is not parseable YAML.
    :raises KeyError: When the profile carries no activation list, or an entry
        in it declares no module name.
    """
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    return {entry["MODULE_NAME"] for entry in document["default"]["SEP"]["APPS"]}


def restrict(profile: Path, apps_root: Path) -> frozenset[str]:
    """Remove every app package the profile does not activate.

    Only directories are candidates, so the loose modules at the apps root
    survive. Re-running against an already-stripped tree removes nothing.

    :param profile: The baked settings profile.
    :param apps_root: The ``app/sep/apps`` directory to thin.
    :return: The package directory names left in place.
    :raises FileNotFoundError: When a retained package — an activated app or an
        infrastructure one — has no directory.
    :raises KeyError: When the profile carries no activation list, or an entry
        in it declares no module name.
    :raises yaml.YAMLError: When the profile is not parseable YAML.
    :raises OSError: When the profile cannot be read, ``apps_root`` cannot be
        listed, or a package cannot be removed.
    """
    retained = frozenset(activated_apps(profile) | INFRASTRUCTURE_PACKAGES)
    present = {child.name for child in apps_root.iterdir() if child.is_dir()}

    missing = retained - present
    if missing:
        raise FileNotFoundError(
            f"Retained packages have no directory under {apps_root}: {sorted(missing)}"
        )

    for name in present - retained:
        shutil.rmtree(apps_root / name)
    return retained


def main() -> None:
    """Parse the profile and apps-root paths, then strip.

    :raises Exception: Propagates every failure ``restrict`` reports —
        ``FileNotFoundError``, ``KeyError``, ``yaml.YAMLError`` and ``OSError``
        — so a bad profile or a missing package fails the build step.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("apps_root", type=Path)
    arguments = parser.parse_args()
    restrict(arguments.profile, arguments.apps_root)


if __name__ == "__main__":
    main()
