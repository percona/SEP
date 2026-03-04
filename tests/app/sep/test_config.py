"""Define tests for the app.sep.config module."""

import pytest
from jinja2 import DictLoader, Environment

from app.sep.config import PMMSettings, SEPSettings


def test_pmm_api_key_masked_in_repr():
    """Test that api_key is masked in repr output."""
    pmm = PMMSettings(api_key="my-pmm-api-key")
    assert "my-pmm-api-key" not in repr(pmm)


def test_pmm_api_key_accepts_secretstr():
    """Test that PMMSettings accepts SecretStr for api_key."""
    pmm = PMMSettings(api_key="test-key")
    assert pmm.api_key.get_secret_value() == "test-key"


class TestFooterExtra:
    """Define tests for the FOOTER_EXTRA setting."""

    def test_footer_extra_defaults_to_none(self):
        """Assert FOOTER_EXTRA defaults to None when not configured."""
        settings = SEPSettings()
        assert settings.FOOTER_EXTRA is None

    def test_footer_extra_accepts_string_value(self):
        """Assert FOOTER_EXTRA can be set to a string value."""
        settings = SEPSettings(FOOTER_EXTRA="SEP-562 dev")
        assert settings.FOOTER_EXTRA == "SEP-562 dev"


FOOTER_ITEMS_WITH_EXTRA = 2

SIDEBAR_TEMPLATE = """\
{%- block sidebar -%}
<footer>
    <ul role="menu">
        <li role="none">{{ footer_text }}</li>
        {% if footer_extra %}
            <li role="none">{{ footer_extra }}</li>
        {% endif %}
    </ul>
</footer>
{%- endblock sidebar -%}
"""


@pytest.fixture
def sidebar_env():
    """Return a Jinja2 environment with the sidebar footer snippet."""
    return Environment(
        loader=DictLoader({"sidebar.html": SIDEBAR_TEMPLATE}),
        autoescape=True,
    )


class TestSidebarFooterExtra:
    """Define tests for the footer_extra rendering in the sidebar template."""

    def test_footer_extra_not_rendered_when_none(self, sidebar_env):
        """Assert no extra list item renders when footer_extra is None."""
        template = sidebar_env.get_template("sidebar.html")
        rendered = template.render(footer_text="SEP v1.0", footer_extra=None)
        assert "SEP v1.0" in rendered
        assert rendered.count("<li") == 1

    def test_footer_extra_not_rendered_when_empty_string(self, sidebar_env):
        """Assert no extra list item renders when footer_extra is empty string."""
        template = sidebar_env.get_template("sidebar.html")
        rendered = template.render(footer_text="SEP v1.0", footer_extra="")
        assert rendered.count("<li") == 1

    def test_footer_extra_rendered_when_set(self, sidebar_env):
        """Assert an extra list item renders when footer_extra is set."""
        template = sidebar_env.get_template("sidebar.html")
        rendered = template.render(footer_text="SEP v1.0", footer_extra="SEP-562 dev")
        assert "SEP v1.0" in rendered
        assert "SEP-562 dev" in rendered
        assert rendered.count("<li") == FOOTER_ITEMS_WITH_EXTRA
