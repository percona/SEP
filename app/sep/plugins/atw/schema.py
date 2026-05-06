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

"""Define the PluginSchema for the ATW plugin."""

from app.sep.plugins.atw.models import ATWCategory, ParentCategory
from app.sep.plugins.framework.schema import (
    Choice,
    ChoiceField,
    Column,
    FormSection,
    ListView,
    PluginSchema,
)

_PARENT_CATEGORY_CHOICES = [
    Choice(label=category.value, value=category.name) for category in ParentCategory
]
_CATEGORY_CHOICES = [
    Choice(label=category.value, value=category.name) for category in ATWCategory
]

atw_schema = PluginSchema(
    name="atw",
    display_name="Ask Know The World",
    description=(
        "Browse curated troubleshooting snippets by issue category and launch"
        " execution through the snippets API flow."
    ),
    forms=[
        FormSection(
            title="Category Browser",
            fields=[
                ChoiceField(
                    name="parent_category",
                    label="Parent Category",
                    required=False,
                    choices=_PARENT_CATEGORY_CHOICES,
                ),
                ChoiceField(
                    name="category",
                    label="Category",
                    required=False,
                    choices=_CATEGORY_CHOICES,
                ),
            ],
        ),
    ],
    list_view=ListView(
        columns=[
            Column(key="parent_category_label", label="Parent Category", sortable=True),
            Column(key="category_label", label="Category", sortable=True),
            Column(key="snippet_count", label="Snippets", sortable=True),
        ],
        default_sort="parent_category_label",
    ),
)
