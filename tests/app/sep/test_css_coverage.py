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

"""Assert sidebar icon rules in base.css match settings.yaml plugin CSS classes."""

from pathlib import Path

import pytest
import yaml


def _plugin_css_classes() -> list[str]:
    """Return all CSS class names declared for plugins in settings.yaml."""
    with Path("settings.yaml").open() as f:
        data = yaml.safe_load(f)
    return [
        plugin["CSS_CLASS"]
        for plugin in data.get("default", {}).get("SEP", {}).get("APPS", [])
        if "CSS_CLASS" in plugin
    ]


class TestSidebarIconCSSCoverage:
    """Assert each plugin CSS class has a matching sidebar icon rule in base.css."""

    @pytest.mark.parametrize("css_class", _plugin_css_classes())
    def test_plugin_css_class_has_sidebar_icon_rule(self, css_class: str) -> None:
        """Assert a declared plugin CSS class has a matching ``::before`` icon rule.

        :param css_class: CSS class name from settings.yaml APPS list.
        :type css_class: str
        """
        css = Path("static/css/base.css").read_text()
        assert f".list-item.{css_class} .icon::before" in css

    def test_missing_rule_is_detected(self) -> None:
        """Assert the guard catches a plugin class with no matching icon rule.

        Simulates the regression where a plugin's CSS_CLASS was renamed (e.g. to
        ``mysql_backups``) but the corresponding ``::before`` rule was not added
        — leaving the sidebar icon invisible.
        """
        css_missing_mysql_backups = (
            ".list-item.archive .icon::before { content: 'archive'; }\n"
            ".list-item.checksums .icon::before { content: 'rule'; }\n"
        )
        assert ".list-item.mysql_backups .icon::before" not in css_missing_mysql_backups
