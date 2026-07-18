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

from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.status import (
    HTTP_200_OK,
    HTTP_303_SEE_OTHER,
)

from app.core.security import crypto_timestamp_serializer
from app.sep.apps.framework.base import BaseApp
from app.sep.artifact_constants import ARTIFACT_DOWNLOAD_SALT
from app.sep.routes.artifacts import collect_base_dirs


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
        """Merge distinct per-app declarations into one map."""
        snippet_dir = Path("/tmp/snippets")
        dipper_dir = Path("/tmp/dipper")
        first = BaseApp(
            name="snippets",
            uri_path="/snippets",
            artifact_base_dirs={"snippet": lambda: snippet_dir},
        )
        second = BaseApp(
            name="dipper",
            uri_path="/dipper",
            artifact_base_dirs={"dipper": lambda: dipper_dir},
        )
        mocker.patch(
            "app.sep.routes.artifacts.get_app_registry",
            return_value=[first, second],
        )

        result = collect_base_dirs()

        assert result.keys() == {"snippet", "dipper"}
        assert result["snippet"]() == snippet_dir
        assert result["dipper"]() == dipper_dir


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

        with patch(
            "app.sep.apps.snippets.app.snippets_settings.SNIPPETS_DIR", tmp_path
        ):
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

    def test_expired_token_causes_redirect(self, test_client, tmp_path):
        """Redirect (via SEP exception handler) when token TTL is exceeded."""
        payload = {
            "type": "snippet",
            "filename": "test_script.sh",
            "md5": "abc123",
        }
        token = _make_token(payload)

        with (
            patch("app.sep.routes.artifacts.sep_settings.ARTIFACT_DOWNLOAD_TTL", 0),
            patch("app.sep.apps.snippets.app.snippets_settings.SNIPPETS_DIR", tmp_path),
        ):
            response = test_client.get(
                f"/artifacts/download/{token}", follow_redirects=False
            )

        assert response.status_code == HTTP_303_SEE_OTHER

    def test_tampered_token_causes_redirect(self, test_client):
        """Redirect (via SEP exception handler) for a token with a tampered signature."""
        response = test_client.get(
            "/artifacts/download/this.is.not.a.valid.token", follow_redirects=False
        )
        assert response.status_code == HTTP_303_SEE_OTHER

    def test_wrong_salt_token_causes_redirect(self, test_client):
        """Redirect for a token signed with the wrong salt."""
        payload = {"type": "snippet", "filename": "test.sh", "md5": "abc"}
        token = _make_token(payload, salt="wrong-salt")
        response = test_client.get(
            f"/artifacts/download/{token}", follow_redirects=False
        )
        assert response.status_code == HTTP_303_SEE_OTHER

    def test_valid_token_nonexistent_file_causes_redirect(self, test_client, tmp_path):
        """Redirect (via SEP exception handler) when token is valid but file does not exist."""
        payload = {
            "type": "snippet",
            "filename": "nonexistent.sh",
            "md5": "abc123",
        }
        token = _make_token(payload)

        with patch(
            "app.sep.apps.snippets.app.snippets_settings.SNIPPETS_DIR", tmp_path
        ):
            response = test_client.get(
                f"/artifacts/download/{token}", follow_redirects=False
            )

        assert response.status_code == HTTP_303_SEE_OTHER

    def test_path_traversal_in_filename_causes_redirect(self, test_client, tmp_path):
        """Redirect when the token filename contains a path traversal sequence."""
        payload = {
            "type": "snippet",
            "filename": "../../etc/passwd",
            "md5": "abc123",
        }
        token = _make_token(payload)

        with patch(
            "app.sep.apps.snippets.app.snippets_settings.SNIPPETS_DIR", tmp_path
        ):
            response = test_client.get(
                f"/artifacts/download/{token}", follow_redirects=False
            )

        assert response.status_code == HTTP_303_SEE_OTHER

    def test_invalid_artifact_type_causes_redirect(self, test_client):
        """Redirect for a token with an unsupported artifact type."""
        payload = {"type": "backup", "filename": "backup.tar.gz", "md5": "abc"}
        token = _make_token(payload)
        response = test_client.get(
            f"/artifacts/download/{token}", follow_redirects=False
        )
        assert response.status_code == HTTP_303_SEE_OTHER
