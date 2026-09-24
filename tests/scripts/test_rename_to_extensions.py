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

"""Tests for the ``scripts/rename_to_extensions.py`` CLI.

The fixtures spell the pre-rename names on purpose: they are the input the
script exists to rewrite, which is why this file is on the script's own
exclusion list.
"""

import json
from collections import Counter

import pytest

from tests.scripts import load_script

rename = load_script("rename_to_extensions")

_ROWS = json.loads(rename.DEFAULT_MAP.read_text(encoding="utf-8"))["rows"]


def _rules(rows: list[dict[str, object]] = _ROWS) -> tuple[list, dict]:
    rename_map = rename.RenameMap(rows)
    report = rename.Report()
    rules = rename.build_guarded_rules(rename_map) + rename.build_rules(
        rename_map, report
    )
    return rules, rename.active_protections(rename_map)


_PACKAGES = rename.package_dirs(rename.RenameMap(_ROWS))
_REVISION = "app/sep/migrations/versions/2026_01_01_0000-0123456789ab_x.py"


def _history(text: str) -> tuple[str, int]:
    rules, protections = _rules()
    return rename.rewrite_history_imports(
        _REVISION, text, rules, protections, _PACKAGES
    )


def _rewrite_file(path: str, text: str) -> str:
    rules, protections = _rules()
    return rename.rewrite_file(
        path, text, rules, protections, _PACKAGES, rename.Report()
    )


def _rewrite(text: str, *, prose: bool = True) -> tuple[str, Counter[str]]:
    rules, protections = _rules()
    new_text, counts, _ = rename.rewrite(text, rules, protections, prose=prose)
    return new_text, counts


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "from app.sep.deps import SessionDep",
            "from app.extensions.deps import SessionDep",
        ),
        (
            "tests/app/sep/apps/atw/test_models.py",
            "tests/app/extensions/apps/atw/test_models.py",
        ),
        (
            'REPO_ROOT / "app" / "sep" / "apps"',
            'REPO_ROOT / "app" / "extensions" / "apps"',
        ),
        ("sep_app.include_router(router)", "extensions_app.include_router(router)"),
        ("sep_settings.APPS", "extensions_settings.APPS"),
        (
            "class SepTaskResponse(BaseModel):",
            "class ExtensionsTaskResponse(BaseModel):",
        ),
        ("export function sepRetry()", "export function extensionsRetry()"),
        ("SEP_TEST_POSTGRES_DSN", "EXTENSIONS_TEST_POSTGRES_DSN"),
        ("import '@sep/api';", "import '@pmm-extensions/api';"),
        (
            'init_periodic_tasks_db(tasks, "sep__")',
            'init_periodic_tasks_db(tasks, "extensions__")',
        ),
        ("name = 'sep__sync_snippets'", "name = 'extensions__sync_snippets'"),
        (
            'version_table="alembic_version_sep"',
            'version_table="alembic_version_extensions"',
        ),
        ("alembic --name sep upgrade heads", "alembic --name extensions upgrade heads"),
        (
            "databases = tasks, inventory, sep",
            "databases = tasks, inventory, extensions",
        ),
        ('"[alembic]\\ndatabases = sep\\n"', '"[alembic]\\ndatabases = extensions\\n"'),
        (
            "from .sep.apps.atw.factories import AtwIncidentFactory",
            "from .extensions.apps.atw.factories import AtwIncidentFactory",
        ),
        (
            "from ..sep.apps.alerts.config import alerts_settings",
            "from ..extensions.apps.alerts.config import alerts_settings",
        ),
        ('--tag "sep:builder"', '--tag "extensions:builder"'),
        ("FROM localhost/sep:builder", "FROM localhost/extensions:builder"),
        ('name = "sep"', 'name = "pmm-extensions"'),
        (
            'f"sep-{version}-py3-none-any.whl"',
            'f"pmm_extensions-{version}-py3-none-any.whl"',
        ),
        (
            "postgresql://sep:sep@db/sep_test",
            "postgresql://extensions:extensions@db/extensions_test",
        ),
        ('DatabaseOptions(NAME="sep.db")', 'DatabaseOptions(NAME="extensions.db")'),
        ('username="sep-service"', 'username="extensions-service"'),
        ('first_name="SEP"', 'first_name="PMM Extensions"'),
        ("class SEPPluginPeriodicTask(", "class ExtensionsAppPeriodicTask("),
        (
            'ASSERTION_SALT = "sep.auth.grafana.v1"',
            'ASSERTION_SALT = "extensions.auth.grafana.v1"',
        ),
        ('".sep-run-result.json"', '".pmm-extensions-run-result.json"'),
        (
            "An SEP app talks to SEP's own API.",
            "A PMM Extensions app talks to PMM Extensions' own API.",
        ),
        ("the SEP-side proxy", "the PMM Extensions side proxy"),
        ('"SEP\'s persisted token"', '"PMM Extensions\' persisted token"'),
        ('client, "percona", "SEP", 42', 'client, "percona", "SEP", 42'),
        (
            "three services (SEP, Inventory, Tasks)",
            "three services (Extensions, Inventory, Tasks)",
        ),
    ],
)
def test_rewrite_renames_each_shape(old: str, new: str) -> None:
    """Rename each textual shape a map name takes."""
    assert _rewrite(old)[0] == new


@pytest.mark.parametrize(
    "text",
    [
        "Fixes SEP-1234 and SEP-XXX in branch sep-1278-e2e.",
        "path.split(os.sep) and ','.join(parts, sep=',')",
        "def loc_to_dot_sep(loc):",
        "https://github.com/percona/SEP/compare/v0.13.0...HEAD",
        'PRE_RENAME_CIPHERTEXT_MARKER = "sep.enc.v1."',
        '_LEGACY_SEP_SETTINGS_TOKEN = "SEP_SETTINGS"',
        "podman image push x labbox:5555/sep:latest",
        "PMM's --sep-token principal",
        "SEPARATOR = '|'",
        "import { sepThemeOptions, sepPrimaryLight } from '@percona/percona-ui';",
        'sep = ","\nok = sep.isascii() and sep.isspace()\n',
        "const sep = '/';\nconst last = sep.at(-1);\n",
        "See https://example.org/sep-api/ and https://sep.example.com/SEP_x.",
    ],
)
def test_rewrite_leaves_protected_spans(text: str) -> None:
    """Leave ticket keys, separators, external names and leftovers byte-identical."""
    assert _rewrite(text)[0] == text


def test_prose_rules_skip_prose_only_paths() -> None:
    """Rename code references but not prose in the docs pull request's files."""
    text = "SEP serves `app/sep/main.py`."
    assert _rewrite(text, prose=False)[0] == "SEP serves `app/extensions/main.py`."


def test_rewrite_is_idempotent() -> None:
    """Report no replacements on a second pass over its own output."""
    text = "from app.sep.main import sep_app  # SEP's @sep/api, sep__x, alembic_version_sep\n"
    once, counts = _rewrite(text)
    twice, second_counts = _rewrite(once)
    assert counts
    assert twice == once
    assert not second_counts


def test_counts_are_attributed_to_rows() -> None:
    """Attribute each replacement to the map row its names came from."""
    _, counts = _rewrite('alembic_version_sep; "sep__x"; @sep/api')
    assert counts == Counter({"alembic": 1, "beat": 1, "fescope": 1})


def test_guarded_names_stay_without_their_row() -> None:
    """Leave a guarded name untouched when the map lacks its row."""
    rows = [row for row in _ROWS if row["key"] != "plugintask"]
    rules, protections = _rules(rows)
    text = "SEPPluginPeriodicTaskManager.list(session)"
    assert rename.rewrite(text, rules, protections, prose=True)[0] == text


def test_absent_row_contributes_no_rule() -> None:
    """Record a row the rules expect but the map lacks, and apply nothing for it."""
    rename_map = rename.RenameMap([row for row in _ROWS if row["key"] != "sse"])
    report = rename.Report()
    rules = rename.build_rules(rename_map, report)
    assert "sse" in report.absent_rows
    assert rules
    assert all(rule.row != "sse" for rule in rules)


def test_item_annotations_are_stripped_but_calls_kept() -> None:
    """Drop parenthesised notes after a space but keep a call's own parentheses."""
    rename_map = rename.RenameMap(_ROWS)
    assert rename_map.pair("appname", 1) == ('Celery("sep")', 'Celery("extensions")')
    assert rename_map.items("header", "new") == ["X-Upstream-Error"]


def test_history_file_keeps_its_name_but_follows_its_directory() -> None:
    """Move a migration revision with its package without renaming the file."""
    rules, protections = _rules()
    path = "app/sep/migrations/versions/2026_06_15_1725-64f10ead74f6_add_seppluginperiodictask.py"
    moves = rename.plan_moves([path], rules, protections)
    assert moves == {
        path: "app/extensions/migrations/versions/2026_06_15_1725-64f10ead74f6_add_seppluginperiodictask.py"
    }


def test_collisions_report_a_new_name_already_in_use() -> None:
    """Flag a rename whose target identifier the file already defines."""
    rules, protections = _rules()
    clashes = rename.collisions(
        "sep_keys = 1\nextensions_keys = 2\n", rules, protections
    )
    assert clashes == ["sep_keys -> extensions_keys"]


def test_history_imports_follow_the_package_and_bind_back_renamed_names() -> None:
    """Rewrite only a revision's imports, binding renamed names to the old ones."""
    rules, protections = _rules()
    text = (
        "from app.sep.apps.shared.om.config import OM_SCHEMA_SYMBOL, om_schema\n"
        "from app.sep.config import sep_settings\n"
        "from alembic import op\n"
        "\n"
        'op.create_table("x", schema=sep_settings.DATABASE.SCHEMA)\n'
    )
    expected = (
        "from app.extensions.apps.shared.om.config import OM_SCHEMA_SYMBOL, om_schema\n"
        "from app.extensions.config import extensions_settings as sep_settings\n"
        "from alembic import op\n"
        "\n"
        'op.create_table("x", schema=sep_settings.DATABASE.SCHEMA)\n'
    )
    assert _history(text) == (expected, 2)
    assert _history(expected) == (expected, 0)


def test_revision_slugs_of_history_files_are_guarded() -> None:
    """Keep naming a history revision by its file name in comments."""
    rules, protections = _rules()
    protections |= rename.revision_slug_protection(
        [
            "app/sep/migrations/versions/2026_09_24_1200-ee2b220c8c73_rename_sep_settings_override_token.py"
        ]
    )
    text = "#: The rename_sep_settings_override_token revision under test.\n"
    assert rename.rewrite(text, rules, protections, prose=True)[0] == text


def test_pre_rename_constants_keep_their_frozen_values() -> None:
    """Leave the old names a forward migration reads, and the constant's name."""
    text = 'PRE_RENAME_VERSION_TABLE = "alembic_version_sep"\n'
    assert _rewrite(text)[0] == text


def test_generated_spec_names_follow_the_package() -> None:
    """Rename the generated API spec and client, the only bare ``sep.`` outside Python."""
    assert _rewrite("'../../api/specs/sep.json' and `generated/sep.ts`")[0] == (
        "'../../api/specs/extensions.json' and `generated/extensions.ts`"
    )


def test_a_mapped_endpoint_inside_a_url_is_still_renamed() -> None:
    """Mask a URL only from the generic rules, not from the mapped rows."""
    text = (
        "curl http://localhost:8000/api/sep/app-info and https://example.org/sep-api/"
    )
    assert _rewrite(text)[0] == (
        "curl http://localhost:8000/api/extensions/app-info and https://example.org/sep-api/"
    )


@pytest.mark.parametrize(
    ("path", "old", "new"),
    [
        (
            "app/core/x.py",
            "from app import sep\n\nsep.main()\nreload(sep)\n",
            "from app import extensions\n\nextensions.main()\nreload(extensions)\n",
        ),
        (
            "app/core/x.py",
            "from app import sep as pkg\n\npkg.main()\n",
            "from app import extensions as pkg\n\npkg.main()\n",
        ),
        (
            "app/core/x.py",
            "from app import (\n    core,\n    sep,\n)\n\nsep.main(sep=',')\n",
            "from app import (\n    core,\n    extensions,\n)\n\nextensions.main(sep=',')\n",
        ),
        (
            "app/core/x.py",
            "from .. import sep\n\nsep.main()\n",
            "from .. import extensions\n\nextensions.main()\n",
        ),
        (
            "tests/app/conftest.py",
            "from . import sep as tests_pkg\n",
            "from . import extensions as tests_pkg\n",
        ),
        (
            "scripts/x.py",
            "from . import sep\n\nsep.main()\n",
            "from . import sep\n\nsep.main()\n",
        ),
    ],
)
def test_a_package_imported_by_name_is_rebound(path: str, old: str, new: str) -> None:
    """Rename a package bound by a ``from`` import, and its uses when unaliased."""
    assert _rewrite_file(path, old) == new


def test_a_package_binding_that_is_also_a_parameter_is_rejected() -> None:
    """Refuse a file whose package binding a function parameter shadows."""
    text = "from app import sep\n\n\ndef f(sep):\n    return sep.x\n"
    with pytest.raises(rename.UnsupportedImportError, match="parameter"):
        _rewrite_file("app/core/x.py", text)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "import app.sep.config as config\n",
            "import app.extensions.config as config\n",
        ),
        (
            "from app.sep.config import sep_settings  # configuration\n",
            "from app.extensions.config import extensions_settings as sep_settings  # configuration\n",
        ),
        (
            "from ..sep.config import sep_settings\n",
            "from ..extensions.config import extensions_settings as sep_settings\n",
        ),
        ("from app import sep\n", "from app import extensions as sep\n"),
        (
            "def upgrade():\n    from app.sep.config import (\n        OTHER,\n        sep_settings,\n    )\n",
            "def upgrade():\n    from app.extensions.config import (\n        OTHER,\n        extensions_settings as sep_settings,\n    )\n",
        ),
        (
            "from os import sep\nimport os.path\n",
            "from os import sep\nimport os.path\n",
        ),
    ],
)
def test_history_import_forms(old: str, new: str) -> None:
    """Point each supported import form at the moved modules, keeping its bindings."""
    assert _history(old)[0] == new
    assert _history(new)[0] == new


@pytest.mark.parametrize(
    "text",
    [
        "import app.sep.config\n",
        "from app.sep.config import (\n    sep_settings,  # the settings\n)\n",
    ],
)
def test_unsupported_history_imports_are_rejected(text: str) -> None:
    """Refuse an import whose rewrite would break the body or drop a comment."""
    with pytest.raises(rename.UnsupportedImportError):
        _history(text)


def test_an_unsupported_import_stops_the_run_before_anything_changes(
    tmp_path, monkeypatch
) -> None:
    """Plan every edit before the first move, so a rejection leaves the tree as it was."""
    files = {
        "app/sep/main.py": "from app.sep.config import sep_settings\n",
        _REVISION: "import app.sep.config\n",
    }
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text, encoding="utf-8")
    monkeypatch.setattr(rename, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(rename, "tracked_files", lambda: list(files))

    with pytest.raises(rename.UnsupportedImportError, match=_REVISION):
        rename.run(rename.RenameMap(_ROWS), dry_run=False, side_repo=None)

    assert {
        path: (tmp_path / path).read_text(encoding="utf-8") for path in files
    } == files
