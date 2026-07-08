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

"""Define tests for the app.core.utils.path module."""

import pytest

from app.core.utils.path import (
    payload_uri,
    PayloadReferenceError,
    resolve_payload_reference,
    to_payload_reference,
)

_PLUGIN_REL = "app/sep/plugins/mysql_backups/binlog_payload"
_APPS_REL = "app/sep/apps/mysql_backups/binlog_payload"


@pytest.fixture
def base_dir(tmp_path, monkeypatch):
    """Redirect the module's ``BASE_DIR`` anchor to an isolated temp root."""
    monkeypatch.setattr("app.core.utils.path.BASE_DIR", tmp_path)
    return tmp_path


def _write(path):
    """Create ``path`` (and parents) with a recognizable payload body."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("print('payload')")
    return path


class TestPayloadReferenceError:
    """Test the PayloadReferenceError exception type."""

    def test_is_value_error_subclass(self):
        """Assert PayloadReferenceError is a ValueError for except-compatibility."""
        assert issubclass(PayloadReferenceError, ValueError)


class TestToPayloadReference:
    """Test the to_payload_reference builder helper."""

    def test_builds_base_dir_relative_reference(self, base_dir):
        """Assert an in-repo path becomes a file:// reference relative to BASE_DIR."""
        payload_path = base_dir / _PLUGIN_REL
        assert to_payload_reference(payload_path) == f"file://{_PLUGIN_REL}"

    def test_reference_round_trips_through_resolver(self, base_dir):
        """Assert a reference built by the helper resolves back to the same file."""
        payload_path = _write(base_dir / _PLUGIN_REL)
        reference = to_payload_reference(payload_path)
        assert resolve_payload_reference(reference) == payload_path

    def test_symlinked_deploy_root_still_anchors(self, tmp_path, monkeypatch):
        """Assert a path reached via a symlinked deploy root anchors relative to BASE_DIR."""
        real_root = tmp_path / "real"
        real_root.mkdir()
        _write(real_root / _PLUGIN_REL)
        link_root = tmp_path / "current"
        link_root.symlink_to(real_root)
        monkeypatch.setattr("app.core.utils.path.BASE_DIR", real_root)
        via_symlink = link_root / _PLUGIN_REL
        assert to_payload_reference(via_symlink) == f"file://{_PLUGIN_REL}"


class TestResolvePayloadReference:
    """Test the resolve_payload_reference resolver."""

    def test_relative_reference_resolves(self, base_dir):
        """Assert a repo-relative reference resolves against BASE_DIR."""
        payload_path = _write(base_dir / _PLUGIN_REL)
        resolved = resolve_payload_reference(f"file://{_PLUGIN_REL}")
        assert resolved == payload_path
        assert resolved.read_text() == "print('payload')"

    def test_legacy_absolute_reference_resolves(self, base_dir):
        """Assert a stored absolute reference still resolves when the file exists."""
        payload_path = _write(base_dir / _PLUGIN_REL)
        resolved = resolve_payload_reference(f"file://{payload_path}")
        assert resolved == payload_path

    def test_plugins_apps_alias_resolves_relocated_reference(self, base_dir):
        """Assert a plugins/ absolute reference resolves to the on-disk apps/ file."""
        apps_path = _write(base_dir / _APPS_REL)
        plugins_ref = f"file://{base_dir / _PLUGIN_REL}"
        assert resolve_payload_reference(plugins_ref) == apps_path

    def test_unresolvable_reference_raises_and_logs(self, base_dir, mocker):
        """Assert an unresolvable reference raises PayloadReferenceError and logs it."""
        reference = f"file://{_PLUGIN_REL}"
        log_error = mocker.patch("app.core.utils.path.logger.error")
        with pytest.raises(PayloadReferenceError, match=_PLUGIN_REL):
            resolve_payload_reference(reference)
        log_error.assert_called_once()
        assert _PLUGIN_REL in str(log_error.call_args)

    def test_non_file_scheme_reference_raises(self, base_dir):
        """Assert a reference without the file:// scheme is rejected, not silently resolved."""
        with pytest.raises(PayloadReferenceError, match="not a file:// reference"):
            resolve_payload_reference(_PLUGIN_REL)

    def test_relative_reference_escaping_base_dir_raises(self, base_dir):
        """Assert a relative reference resolving outside BASE_DIR is rejected."""
        with pytest.raises(PayloadReferenceError, match="escapes BASE_DIR"):
            resolve_payload_reference("file://../../etc/passwd")

    def test_absolute_reference_outside_base_dir_is_trusted(
        self, tmp_path, monkeypatch
    ):
        """Assert an absolute reference outside BASE_DIR resolves; the escape guard is relative-only."""
        base = tmp_path / "base"
        base.mkdir()
        monkeypatch.setattr("app.core.utils.path.BASE_DIR", base)
        outside = _write(tmp_path / "elsewhere" / "payload_script")
        assert resolve_payload_reference(f"file://{outside}") == outside


class TestPayloadUri:
    """Test the payload_uri convenience helper."""

    def test_returns_same_as_manual_path_construction(self, base_dir):
        """Assert payload_uri produces the same reference as the hand-rolled pattern."""
        anchor = str(base_dir / _PLUGIN_REL)
        expected = to_payload_reference(
            base_dir / _PLUGIN_REL / ".." / "binlog_payload"
        )
        assert payload_uri(anchor, "binlog_payload") == expected

    def test_builds_reference_relative_to_base_dir(self, base_dir):
        """Assert the returned string is a file:// reference relative to BASE_DIR."""
        anchor = str(base_dir / "app" / "sep" / "plugins" / "mysql_backups" / "spec.py")
        result = payload_uri(anchor, "binlog_payload")
        assert result == f"file://{_PLUGIN_REL}"

    def test_round_trips_through_resolver(self, base_dir):
        """Assert a payload_uri reference resolves back to the on-disk file."""
        payload_file = _write(base_dir / _PLUGIN_REL)
        anchor = str(base_dir / "app" / "sep" / "plugins" / "mysql_backups" / "spec.py")
        reference = payload_uri(anchor, "binlog_payload")
        assert resolve_payload_reference(reference) == payload_file
