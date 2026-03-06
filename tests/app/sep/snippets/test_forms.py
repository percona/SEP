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

"""Test HTML form element models for snippets."""

from app.sep.snippets.forms import (
    BaseHTMLElement,
    CheckboxInputElement,
    FormFieldMixin,
    ICON_CLASS,
    SelectElement,
    SpanElement,
    TextInputElement,
)


class TestBaseHTMLElementTitleRemoved:
    """Verify that `title` was removed from `BaseHTMLElement`."""

    def test_title_not_in_model_fields(self):
        """Assert `title` is no longer a model field on `BaseHTMLElement`."""
        assert "title" not in BaseHTMLElement.model_fields

    def test_no_title_attribute_on_non_form_elements(self):
        """Assert non-form elements produce no `title` attribute or info icon."""
        elem = SpanElement(label="test")
        assert "title=" not in elem.to_html()
        assert "info-icon" not in elem.to_html()


class TestFormFieldMixinDescription:
    """Verify `description` field on `FormFieldMixin` renders info icons."""

    def test_description_field_exists(self):
        """Assert `description` is a model field on `FormFieldMixin`."""
        assert "description" in FormFieldMixin.model_fields

    def test_description_excluded_from_html_attributes(self):
        """Assert `description` does not appear as an HTML attribute."""
        elem = TextInputElement(name="test", description="help text")
        assert "description=" not in elem.attributes

    def test_info_icon_rendered_with_description(self):
        """Assert an info-icon span is rendered when description is set."""
        elem = TextInputElement(name="test", description="help text")
        html = elem.to_html()
        assert 'class="info-icon"' in html
        assert 'data-tooltip="help text"' in html
        assert 'aria-label="help text"' in html
        assert f'class="{ICON_CLASS}">info</span>' in html

    def test_no_info_icon_without_description(self):
        """Assert no info icon is rendered when description is not set."""
        elem = TextInputElement(name="test")
        html = elem.to_html()
        assert "info-icon" not in html

    def test_info_icon_html_escaped(self):
        """Assert description content is HTML-escaped in the info icon."""
        elem = TextInputElement(name="test", description='<script>"xss"</script>')
        html = elem.to_html()
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_checkbox_with_description_has_info_icon(self):
        """Assert checkbox elements render both checkmark and info icon."""
        elem = CheckboxInputElement(
            name="sudo", description="Execute with sudo", label="Use sudo"
        )
        html = elem.to_html()
        assert 'class="info-icon"' in html
        assert 'data-tooltip="Execute with sudo"' in html
        assert 'class="checkmark"' in html

    def test_select_with_description_has_info_icon(self):
        """Assert select elements render info icon when description is set."""
        elem = SelectElement(
            name="host",
            children=["host1"],
            description="Select the target host",
        )
        html = elem.to_html()
        assert 'class="info-icon"' in html
        assert 'data-tooltip="Select the target host"' in html

    def test_info_icon_inside_label(self):
        """Assert info icon is rendered inside the label element."""
        elem = TextInputElement(name="test", description="help", label="Field")
        html = elem.to_html()
        label_end = html.rfind("</label>")
        icon_pos = html.find('class="info-icon"')
        assert icon_pos < label_end
