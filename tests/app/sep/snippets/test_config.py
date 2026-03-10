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

"""Tests for SnippetSudoOption, including OPTIONAL_DEFAULT_TRUE."""

import pytest

from app.sep.snippets.config import SnippetSudoOption
from app.sep.snippets.models.snippet import BaseSnippet, SUDO_INPUT_NAME


class TestSnippetSudoOptionProperties:
    """Test the is_optional and sudo_default properties."""

    @pytest.mark.parametrize(
        ("option", "expected"),
        [
            (SnippetSudoOption.NEVER, False),
            (SnippetSudoOption.ALWAYS, False),
            (SnippetSudoOption.OPTIONAL, True),
            (SnippetSudoOption.OPTIONAL_DEFAULT_TRUE, True),
            (SnippetSudoOption.OPTIONAL_DEFAULT_FALSE, True),
        ],
    )
    def test_is_optional(self, option, expected):
        """Verify is_optional returns correct value for each sudo option."""
        assert option.is_optional is expected

    @pytest.mark.parametrize(
        ("option", "expected"),
        [
            (SnippetSudoOption.NEVER, False),
            (SnippetSudoOption.ALWAYS, False),
            (SnippetSudoOption.OPTIONAL, False),
            (SnippetSudoOption.OPTIONAL_DEFAULT_TRUE, True),
            (SnippetSudoOption.OPTIONAL_DEFAULT_FALSE, False),
        ],
    )
    def test_sudo_default(self, option, expected):
        """Verify sudo_default returns correct value for each sudo option."""
        assert option.sudo_default is expected


class TestSnippetSudoOptionAlias:
    """Test that OPTIONAL_DEFAULT_FALSE is an alias for OPTIONAL."""

    def test_alias_identity(self):
        """Verify OPTIONAL_DEFAULT_FALSE is the same object as OPTIONAL."""
        assert SnippetSudoOption.OPTIONAL_DEFAULT_FALSE is SnippetSudoOption.OPTIONAL

    def test_alias_value(self):
        """Verify OPTIONAL_DEFAULT_FALSE has the same numeric value as OPTIONAL."""
        assert (
            SnippetSudoOption.OPTIONAL_DEFAULT_FALSE.value
            == SnippetSudoOption.OPTIONAL.value
        )


class TestSudoFormGeneration:
    """Test that _to_form generates the correct checkbox state."""

    def test_optional_default_false_produces_unchecked_checkbox(self):
        """Verify sudo checkbox is unchecked when sudo_default is False."""
        html = BaseSnippet._to_form(
            "[]",
            frozenset({"host1"}),
            add_sudo_field=True,
            sudo_default=False,
        )
        assert SUDO_INPUT_NAME in html
        assert 'type="checkbox"' in html
        checkbox_tag = html.split('type="checkbox"')[0].rsplit("<", 1)[1]
        assert "checked" not in checkbox_tag

    def test_optional_default_true_produces_checked_checkbox(self):
        """Verify sudo checkbox is checked when sudo_default is True."""
        html = BaseSnippet._to_form(
            "[]",
            frozenset({"host1"}),
            add_sudo_field=True,
            sudo_default=True,
        )
        assert 'type="checkbox"' in html
        checkbox_tag = html.split('type="checkbox"')[0].rsplit("<", 1)[1]
        assert "checked" in checkbox_tag

    def test_no_sudo_field_when_not_optional(self):
        """Verify no sudo field is rendered when add_sudo_field is False."""
        html = BaseSnippet._to_form(
            "[]",
            frozenset({"host1"}),
            add_sudo_field=False,
        )
        assert SUDO_INPUT_NAME not in html


class TestSudoExecutionModel:
    """Test that _get_execution_model sets correct sudo default."""

    def test_sudo_default_false(self):
        """Verify execution model sudo field defaults to False."""
        model = BaseSnippet._get_execution_model(
            "[]",
            add_sudo_field=True,
            sudo_default=False,
        )
        assert model.model_fields["sudo"].default is False

    def test_sudo_default_true(self):
        """Verify execution model sudo field defaults to True."""
        model = BaseSnippet._get_execution_model(
            "[]",
            add_sudo_field=True,
            sudo_default=True,
        )
        assert model.model_fields["sudo"].default is True

    def test_no_sudo_field_when_not_optional(self):
        """Verify no sudo field exists when add_sudo_field is False."""
        model = BaseSnippet._get_execution_model(
            "[]",
            add_sudo_field=False,
        )
        assert "sudo" not in model.model_fields
