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

"""Define tests for the app.sep.routes.artifacts module."""

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
)

from app.core.security import crypto_timestamp_serializer
from app.sep.apps.framework.base import BaseApp
from app.sep.artifact_constants import ARTIFACT_DOWNLOAD_SALT, STATIC_ARTIFACT_BASE_DIRS
from app.sep.routes.artifacts import collect_base_dirs
from app.sep.snippets.constants import ARTIFACT_TYPE_SNIPPET


def _make_token(payload: dict, salt: str = ARTIFACT_DOWNLOAD_SALT) -> str:
    return crypto_timestamp_serializer.dumps(payload, salt=salt)


class TestCollectBaseDirs:
    """Cover the registry flatten that builds the artifact base-dir map."""

    def test_raises_on_duplicate_artifact_type(self, mocker) -> None:
        """Raise ``ValueError`` naming a type two apps both declare."""
        first = BaseApp(
            name="first",
            uri_path="/first",
            artifact_base_dirs={"shared": lambda: Path("/tmp/first")},
        )
        second = BaseApp(
            name="second",
            uri_path="/second",
            artifact_base_dirs={"shared": lambda: Path("/tmp/second")},
        )
        mocker.patch(
            "app.sep.routes.artifacts.get_app_registry",
            return_value=[first, second],
        )

        with pytest.raises(ValueError, match="shared"):
            collect_base_dirs()

    def test_flattens_distinct_artifact_types(self, mocker) -> None:
        """Merge distinct per-app declarations over the static seed."""
        dipper_dir = Path("/tmp/dipper")
        other_dir = Path("/tmp/other")
        dipper = BaseApp(
            name="dipper",
            uri_path="/dipper",
            artifact_base_dirs={"dipper": lambda: dipper_dir},
        )
        other = BaseApp(
            name="other",
            uri_path="/other",
            artifact_base_dirs={"other": lambda: other_dir},
        )
        mocker.patch(
            "app.sep.routes.artifacts.get_app_registry",
            return_value=[dipper, other],
        )

        result = collect_base_dirs()

        assert result.keys() == {ARTIFACT_TYPE_SNIPPET, "dipper", "other"}
        assert result["dipper"]() == dipper_dir
        assert result["other"]() == other_dir

    def test_seeds_the_static_snippet_type_without_the_snippets_app(
        self, mocker
    ) -> None:
        """Resolve the snippet type from the static map, with no app declaring it."""
        mocker.patch(
            "app.sep.routes.artifacts.get_app_registry",
            return_value=[BaseApp(name="atw", uri_path="/atw")],
        )

        assert ARTIFACT_TYPE_SNIPPET in collect_base_dirs()

    def test_raises_when_an_app_redeclares_a_static_type(self, mocker) -> None:
        """Reject an app that re-declares a statically registered type."""
        redeclaring = BaseApp(
            name="snippets",
            uri_path="/snippets",
            artifact_base_dirs={ARTIFACT_TYPE_SNIPPET: lambda: Path("/tmp/other")},
        )
        mocker.patch(
            "app.sep.routes.artifacts.get_app_registry", return_value=[redeclaring]
        )

        with pytest.raises(ValueError, match=ARTIFACT_TYPE_SNIPPET):
            collect_base_dirs()

    def test_does_not_mutate_the_static_map(self, mocker) -> None:
        """Return a fresh dict so an app declaration cannot leak into the constant."""
        declaring = BaseApp(
            name="dipper",
            uri_path="/dipper",
            artifact_base_dirs={"dipper": lambda: Path("/tmp/dipper")},
        )
        mocker.patch(
            "app.sep.routes.artifacts.get_app_registry", return_value=[declaring]
        )

        collect_base_dirs()

        assert "dipper" not in STATIC_ARTIFACT_BASE_DIRS


class TestDownloadArtifact:
    """Tests for the GET /artifacts/download/{token} endpoint."""

    def test_valid_snippet_token_existing_file_returns_200(self, test_client, tmp_path):
        """Return 200 and file content for a valid snippet token pointing to an existing file."""
        script_file = tmp_path / "test_script.sh"
        script_file.write_text("#!/bin/bash\necho hello")

        payload = {
            "type": "snippet",
            "filename": "test_script.sh",
            "md5": "abc123",
        }
        token = _make_token(payload)

        with patch("app.sep.snippets.config.snippets_settings.SNIPPETS_DIR", tmp_path):
            response = test_client.get(f"/artifacts/download/{token}")

        assert response.status_code == HTTP_200_OK

    def test_valid_dipper_token_existing_file_returns_200(self, test_client, tmp_path):
        """Return 200 and file content for a valid dipper token pointing to an existing file."""
        script_file = tmp_path / "collect.sh"
        script_file.write_text("#!/bin/bash\necho dipper")

        payload = {
            "type": "dipper",
            "filename": "collect.sh",
            "md5": "def456",
        }
        token = _make_token(payload)

        with patch("app.sep.apps.dipper.app.DIPPER_PAYLOADS_DIR", tmp_path):
            response = test_client.get(f"/artifacts/download/{token}")

        assert response.status_code == HTTP_200_OK

    def test_expired_token_returns_400(self, test_client, tmp_path):
        """Reject with 400 once the token is older than the configured TTL.

        The signed timestamp is what expires, so the token is minted an hour in
        the past rather than the TTL being set to ``0`` — at ``0`` a
        just-minted token has age ``0``, which is not yet *over* the limit, and
        the request would fall through to the file lookup and 404 instead.
        """
        payload = {
            "type": "snippet",
            "filename": "test_script.sh",
            "md5": "abc123",
        }
        an_hour_ago = time.time() - 3600
        with patch("itsdangerous.timed.time.time", return_value=an_hour_ago):
            token = _make_token(payload)

        with (
            patch("app.sep.routes.artifacts.sep_settings.ARTIFACT_DOWNLOAD_TTL", 60),
            patch("app.sep.snippets.config.snippets_settings.SNIPPETS_DIR", tmp_path),
        ):
            response = test_client.get(
                f"/artifacts/download/{token}", follow_redirects=False
            )

        assert response.status_code == HTTP_400_BAD_REQUEST

    def test_tampered_token_returns_400(self, test_client):
        """Reject with 400 a token whose signature was tampered with."""
        response = test_client.get(
            "/artifacts/download/this.is.not.a.valid.token", follow_redirects=False
        )
        assert response.status_code == HTTP_400_BAD_REQUEST

    def test_wrong_salt_token_returns_400(self, test_client):
        """Reject with 400 a token signed with the wrong salt."""
        payload = {"type": "snippet", "filename": "test.sh", "md5": "abc"}
        token = _make_token(payload, salt="wrong-salt")
        response = test_client.get(
            f"/artifacts/download/{token}", follow_redirects=False
        )
        assert response.status_code == HTTP_400_BAD_REQUEST

    def test_valid_token_nonexistent_file_returns_404(self, test_client, tmp_path):
        """Return 404 when the token is valid but the file does not exist."""
        payload = {
            "type": "snippet",
            "filename": "nonexistent.sh",
            "md5": "abc123",
        }
        token = _make_token(payload)

        with patch("app.sep.snippets.config.snippets_settings.SNIPPETS_DIR", tmp_path):
            response = test_client.get(
                f"/artifacts/download/{token}", follow_redirects=False
            )

        assert response.status_code == HTTP_404_NOT_FOUND

    def test_path_traversal_in_filename_returns_400(self, test_client, tmp_path):
        """Reject with 400 a token whose filename carries a path-traversal sequence."""
        payload = {
            "type": "snippet",
            "filename": "../../etc/passwd",
            "md5": "abc123",
        }
        token = _make_token(payload)

        with patch("app.sep.snippets.config.snippets_settings.SNIPPETS_DIR", tmp_path):
            response = test_client.get(
                f"/artifacts/download/{token}", follow_redirects=False
            )

        assert response.status_code == HTTP_400_BAD_REQUEST

    def test_invalid_artifact_type_returns_400(self, test_client):
        """Reject with 400 a token naming an unsupported artifact type."""
        payload = {"type": "backup", "filename": "backup.tar.gz", "md5": "abc"}
        token = _make_token(payload)
        response = test_client.get(
            f"/artifacts/download/{token}", follow_redirects=False
        )
        assert response.status_code == HTTP_400_BAD_REQUEST
