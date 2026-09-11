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

"""Test the install-readiness facts collected for every host.

Collected for a machine with nothing installed on it yet, not only ones already
running a database — that bare-machine case is exactly what an install decision is
about, so both facts have to survive a host answering neither.
"""

from unittest.mock import patch

from app.sep.apps.om_inventory.payload.probe import collect_install_readiness

FREE_BYTES = 107374182400


class TestPackageManagerDetection:
    """Identify which package manager, if any, this host installs through."""

    def test_the_first_match_wins(self) -> None:
        """A host reporting more than one tool is described by the one tried first."""
        with patch(
            "shutil.which", side_effect=lambda binary: binary in {"apt-get", "yum"}
        ):
            facts = collect_install_readiness()

        assert facts["package_manager"] == "apt"

    def test_dnf_is_preferred_over_the_yum_symlink(self) -> None:
        """RHEL8+ symlinks ``yum`` to ``dnf`` — report the tool that is actually there."""
        with patch("shutil.which", side_effect=lambda binary: binary in {"dnf", "yum"}):
            facts = collect_install_readiness()

        assert facts["package_manager"] == "dnf"

    def test_zypper_is_recognised(self) -> None:
        """SUSE hosts are not left unclassified for using the fourth tool checked."""
        with patch("shutil.which", side_effect=lambda binary: binary == "zypper"):
            facts = collect_install_readiness()

        assert facts["package_manager"] == "zypper"

    def test_none_of_the_four_is_reported_as_none(self) -> None:
        """An unrecognised host reports absence, not a wrong guess."""
        with patch("shutil.which", return_value=None):
            facts = collect_install_readiness()

        assert facts["package_manager"] is None


class TestDataDirFreeBytes:
    """Report free space on the filesystem an install would land on."""

    def test_the_free_byte_count_is_reported(self) -> None:
        """The ordinary case: root's filesystem answers."""
        usage = type("Usage", (), {"free": FREE_BYTES})()
        with (
            patch("shutil.which", return_value=None),
            patch("shutil.disk_usage", return_value=usage) as disk_usage,
        ):
            facts = collect_install_readiness()

        assert facts["data_dir_free_bytes"] == FREE_BYTES
        assert disk_usage.call_args.args == ("/",)

    def test_an_unreadable_filesystem_is_none_not_an_exception(self) -> None:
        """A permission or mount failure must not cost the rest of the host record."""
        with (
            patch("shutil.which", return_value=None),
            patch("shutil.disk_usage", side_effect=OSError("permission denied")),
        ):
            facts = collect_install_readiness()

        assert facts["data_dir_free_bytes"] is None
