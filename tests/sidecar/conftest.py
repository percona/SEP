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
"""Shared fixtures for the side-car image's baked configuration."""

from pathlib import Path

import pytest
import yaml

from app import BASE_DIR

SIDECAR_DIR = BASE_DIR / "sidecar"
EMBEDDED_PROFILE = SIDECAR_DIR / "settings.embedded.yaml"
SETTINGS_ENV_HELPER = SIDECAR_DIR / "settings-env.sh"

SUITE_ENV_OVERRIDES = (
    "AUTH__PROVIDER__CASDOOR__CLIENT_ID",
    "AUTH__PROVIDER__CASDOOR__CLIENT_SECRET",
    "AUTH__PROVIDER__CASDOOR__ALLOWED_ISSUERS",
    "ALLOWED_HOSTS",
    "ALLOW_CONCURRENT_SESSIONS",
    "SEP__MESSAGES__LEVEL",
    "SEP_INTERNAL_TOKEN",
)
"""Names ``[tool.pytest.ini_options] env`` injects for the app suite.

They target the same settings fields the profile carries, so leaving them set
would overlay the file under test with a second auth provider and a narrower
``ALLOWED_HOSTS`` -- the profile would be validated only in part.
"""


@pytest.fixture
def embedded_profile_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Resolve the baked profile as the process's ``settings.yaml``.

    Settings classes open the relative ``Path("settings.yaml")`` per
    instantiation, so a copy in the process CWD is what a freshly constructed
    class reads.

    :param tmp_path: The per-test temporary directory.
    :param monkeypatch: The environment and CWD patcher.
    :return: The directory holding the profile copy.
    """
    (tmp_path / "settings.yaml").write_text(
        EMBEDDED_PROFILE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    for name in SUITE_ENV_OVERRIDES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FASTAPI_ENV", "production_docker")
    return tmp_path


@pytest.fixture
def embedded_profile_data() -> dict:
    """Return the parsed baked profile.

    :return: The profile's YAML content.
    """
    return yaml.safe_load(EMBEDDED_PROFILE.read_text(encoding="utf-8"))
