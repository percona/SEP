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

"""Render tests for ``templates/tasks/partials/scheduled-tasks.html.j2``.

Regression coverage for SEP-1103: the edit row of an existing periodic task
must propagate the persisted ``execute_request.chain_on_failure`` value into
the embedded ``chain-builder.html`` partial so the **Continue chain on
failure** checkbox hydrates correctly.
"""

import re
from types import SimpleNamespace

from app.sep.config import sep_settings

_TEMPLATE = "tasks/partials/scheduled-tasks.html.j2"
_EDIT_FORM_ID = "edit-periodic-task-form-1"
_EDIT_CHAIN_BUILDER_RE = re.compile(
    r'<div class="chain-builder[^"]*"[^>]*?data-form-id="'
    + re.escape(_EDIT_FORM_ID)
    + r'"[^>]*>',
    re.DOTALL,
)


def _stub_url_for(*_args: object, **_kwargs: object) -> str:
    """Return a constant placeholder URL so the rendered HTML stays parseable in tests."""
    return "/"


def _make_periodic_task(*, chain_on_failure: bool) -> SimpleNamespace:
    """Build a minimal periodic task whose execute_request carries ``chain_on_failure``."""
    return SimpleNamespace(
        id=1,
        task="my-task",
        period="every 5 minutes",
        interval=SimpleNamespace(every=5, period="minutes"),
        crontab=None,
        start_time=None,
        last_run_at=None,
        next_run_at=None,
        total_run_count=0,
        enabled=True,
        execute_request=SimpleNamespace(
            chain_task_names=["other-task"],
            chain_on_failure=chain_on_failure,
        ),
    )


def _render(periodic_task: SimpleNamespace) -> str:
    """Render the scheduled-tasks partial with one ``periodic_task`` in edit mode.

    Uses :data:`sep_settings.JINJA_ENVIRONMENT` via :meth:`~jinja2.Environment.overlay`
    so all production filters and globals are available; only ``url_for`` and
    ``csrf_token`` are stubbed out for the render.
    """
    env = sep_settings.JINJA_ENVIRONMENT.overlay()
    env.globals["url_for"] = _stub_url_for
    env.globals["csrf_token"] = "test-csrf"
    template = env.get_template(_TEMPLATE)
    return template.render(
        periodic_tasks=[periodic_task],
        chainable_tasks=[SimpleNamespace(name="other-task")],
        tasks=[SimpleNamespace(name="my-task")],
        AVAILABLE_TIMEZONES=["UTC"],
        detail_route=None,
    )


def test_edit_row_carries_data_chain_on_failure_when_persisted_true() -> None:
    """Assert the edit row's chain-builder hydrates ``data-chain-on-failure`` from the persisted value."""
    rendered = _render(_make_periodic_task(chain_on_failure=True))

    edit_chain_builder_match = _EDIT_CHAIN_BUILDER_RE.search(rendered)
    assert edit_chain_builder_match is not None, (
        f"chain-builder for {_EDIT_FORM_ID} not rendered"
    )

    assert 'data-chain-on-failure="true"' in edit_chain_builder_match.group(0)


def test_edit_row_omits_data_chain_on_failure_when_persisted_false() -> None:
    """Assert the edit row omits ``data-chain-on-failure`` when the persisted value is ``False``."""
    rendered = _render(_make_periodic_task(chain_on_failure=False))

    edit_chain_builder_match = _EDIT_CHAIN_BUILDER_RE.search(rendered)
    assert edit_chain_builder_match is not None, (
        f"chain-builder for {_EDIT_FORM_ID} not rendered"
    )

    assert "data-chain-on-failure" not in edit_chain_builder_match.group(0)
