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

"""Guard the import boundary between core modules and activatable apps.

The PMM-embedded side-car image strips non-activated packages from
``app/sep/apps/``, so any module outside that tree holding an import-time edge
into ``app.sep.apps.<app>`` breaks the image at import. This module walks the
``app/`` tree with :mod:`ast` and fails on every such edge.

Two node shapes count, because both execute at import: a static ``import`` /
``from ... import``, and a dynamic import call whose target is a string literal
(``import_module("app.sep.apps.alerts.config")``,
``import_var("app.sep.apps.alerts.config:alerts_settings")``).

Two limitations are deliberate, so the guard is not mistaken for a total one:

- A dynamic import whose target is *computed* cannot be resolved statically.
  Restricting the dynamic check to literal arguments is what keeps the
  registry's activation-list-driven ``import_module(plugin.module_name)`` from
  tripping the guard -- that call is the blessed activation seam, not a
  violation.
- A function that imports in its body and is then *called* at module scope does
  execute the import at import time, but resolving that needs call-graph
  tracing. Function bodies are skipped, so this shape is not caught; the
  codebase's deferred imports are all called from request/task paths.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import BASE_DIR

APPS_ROOT = BASE_DIR / "app" / "sep" / "apps"

INFRASTRUCTURE_PACKAGES = frozenset({"framework", "shared"})

DYNAMIC_IMPORT_CALLEES = frozenset({"import_module", "import_var"})

DYNAMIC_IMPORT_TARGET_KEYWORDS = frozenset({"name", "path"})


def _app_package_names(apps_root: Path) -> set[str]:
    """Return every activatable app package directory under ``app/sep/apps/``.

    :param apps_root: The ``app/sep/apps`` directory to scan.
    :return: The app package names, excluding infrastructure packages.
    """
    return {
        child.name
        for child in apps_root.iterdir()
        if child.is_dir()
        and not child.name.startswith("_")
        and child.name not in INFRASTRUCTURE_PACKAGES
    }


def _dynamic_import_target(node: ast.Call) -> str | None:
    """Return the literal module path a dynamic import call resolves.

    :param node: The call node to inspect.
    :return: The dotted module path, or ``None`` when the call is not a dynamic
        import or its target is computed rather than literal.
    """
    callee = node.func
    name = (
        callee.attr
        if isinstance(callee, ast.Attribute)
        else getattr(callee, "id", None)
    )
    if name not in DYNAMIC_IMPORT_CALLEES:
        return None
    target = next(
        (
            keyword.value
            for keyword in node.keywords
            if keyword.arg in DYNAMIC_IMPORT_TARGET_KEYWORDS
        ),
        node.args[0] if node.args else None,
    )
    if not isinstance(target, ast.Constant) or not isinstance(target.value, str):
        return None
    return target.value.split(":", 1)[0]


def _absolute_base(node: ast.ImportFrom, package: str) -> str | None:
    """Return the absolute dotted path ``node``'s module part resolves to.

    :param node: The ``from ... import`` node to resolve.
    :param package: The dotted package the importing module belongs to.
    :return: The absolute module path, or ``None`` when the level climbs past
        the package root.
    """
    if node.level == 0:
        return node.module
    anchor = package.split(".")[: len(package.split(".")) - node.level + 1]
    if not anchor:
        return None
    return ".".join([*anchor, node.module] if node.module else anchor)


def _direct_import_edges(node: ast.AST, package: str) -> Iterator[tuple[str, int]]:
    """Yield the import edges ``node`` itself declares, ignoring its children.

    A ``from ... import`` yields both its module and one path per alias, because
    ``from app.sep.apps import alerts`` names the loaded package in the alias
    rather than in the module. A relative form is resolved against ``package``
    first, so ``from .apps.alerts import config`` is classified exactly as its
    absolute spelling would be.

    :param node: The node to classify.
    :param package: The dotted package the importing module belongs to.
    :return: An iterator of dotted module paths with their line numbers.
    """
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name, node.lineno
    elif isinstance(node, ast.ImportFrom):
        base = _absolute_base(node, package)
        if base:
            yield base, node.lineno
            for alias in node.names:
                yield f"{base}.{alias.name}", node.lineno
    elif isinstance(node, ast.Call):
        target = _dynamic_import_target(node)
        if target is not None:
            yield target, node.lineno


def _import_time_imports(node: ast.AST, package: str) -> Iterator[tuple[str, int]]:
    """Yield ``(module, lineno)`` for each import executed when the module loads.

    Descends the module body and class bodies -- both execute on import -- but
    never into a function body, at any nesting depth. :func:`ast.walk` cannot
    express that: it queues a node's children before yielding the node, so
    skipping a ``FunctionDef`` mid-walk still lets its already-queued body
    surface. An ``if TYPE_CHECKING:`` guard is descended on its ``else`` branch
    only, since that is the branch a real interpreter runs.

    :param node: The module or nested node to descend.
    :param package: The dotted package the importing module belongs to.
    :return: An iterator of dotted module paths with their line numbers.
    """
    yield from _direct_import_edges(node, package)
    if isinstance(node, ast.Import | ast.ImportFrom):
        return
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if _is_type_checking_guard(child):
            for fallback in child.orelse:
                yield from _import_time_imports(fallback, package)
            continue
        yield from _import_time_imports(child, package)


def _is_type_checking_guard(node: ast.AST) -> bool:
    """Report whether ``node`` is an ``if TYPE_CHECKING:`` block.

    :param node: The statement to classify.
    :return: Whether the statement guards annotation-only imports.
    """
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"


def _package_of(path: Path) -> str:
    """Return the dotted package a module resolves its relative imports against.

    :param path: The source path to derive the package from.
    :return: The dotted package name, which for an ``__init__.py`` is its own
        directory.
    """
    return ".".join(path.relative_to(BASE_DIR).parts[:-1])


def _core_module_paths() -> Iterator[Path]:
    """Yield every ``app/**/*.py`` module outside the activatable-app tree.

    :return: An iterator of source paths subject to the boundary rule.
    """
    for path in sorted((BASE_DIR / "app").rglob("*.py")):
        if not path.is_relative_to(APPS_ROOT):
            yield path


def _app_package_of(module: str, app_packages: set[str]) -> str | None:
    """Return the activatable app package ``module`` reaches, if it reaches one.

    :param module: The dotted module path an import edge resolves.
    :param app_packages: The activatable app package names.
    :return: The app package name, or ``None`` when the path is outside them.
    """
    parts = module.split(".")
    if parts[:3] != ["app", "sep", "apps"] or not parts[3:4]:
        return None
    return parts[3] if parts[3] in app_packages else None


def _violations() -> list[str]:
    """Collect every import-time edge from a core module into an app package.

    :return: One ``path:line -> module`` entry per violating import.
    """
    app_packages = _app_package_names(APPS_ROOT)
    found: list[str] = []
    seen: set[tuple[Path, int]] = set()
    for path in _core_module_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module, lineno in _import_time_imports(tree, _package_of(path)):
            if _app_package_of(module, app_packages) is None:
                continue
            if (path, lineno) in seen:
                continue
            seen.add((path, lineno))
            found.append(f"{path.relative_to(BASE_DIR)}:{lineno} -> {module}")
    return found


def test_no_core_module_imports_an_app_package() -> None:
    """Reject every import-time edge from outside ``app/sep/apps/`` into an app."""
    violations = _violations()
    assert not violations, (
        "modules outside app/sep/apps/ must not import an activatable app package"
        " at import time (the PMM-embedded image strips them):\n"
        + "\n".join(violations)
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "from app.sep.apps.alerts.config import alerts_settings",
            {"alerts"},
            id="submodule-from-import",
        ),
        pytest.param(
            "from app.sep.apps import alerts",
            {"alerts"},
            id="package-level-from-import",
        ),
        pytest.param(
            "from app.sep.apps import alerts, dipper",
            {"alerts", "dipper"},
            id="package-level-from-import-multiple",
        ),
        pytest.param(
            "import app.sep.apps.alerts.config",
            {"alerts"},
            id="plain-import",
        ),
        pytest.param(
            'import_module("app.sep.apps.alerts.config")',
            {"alerts"},
            id="dynamic-literal-target",
        ),
        pytest.param(
            'import_var("app.sep.apps.alerts.config:alerts_settings")',
            {"alerts"},
            id="dynamic-literal-var-target",
        ),
        pytest.param(
            "class Holder:\n"
            "    from app.sep.apps.alerts.config import alerts_settings\n",
            {"alerts"},
            id="class-body-import",
        ),
        pytest.param(
            "import_module(plugin.module_name)",
            set(),
            id="dynamic-computed-target",
        ),
        pytest.param(
            "def _lazy():\n"
            "    from app.sep.apps.alerts.config import alerts_settings\n",
            set(),
            id="function-body",
        ),
        pytest.param(
            "class Holder:\n"
            "    def lazy(self):\n"
            "        from app.sep.apps.alerts.config import alerts_settings\n",
            set(),
            id="method-body",
        ),
        pytest.param(
            "if TYPE_CHECKING:\n"
            "    from app.sep.apps.alerts.config import AlertsSettings\n",
            set(),
            id="type-checking-guard",
        ),
        pytest.param(
            "if TYPE_CHECKING:\n"
            "    from app.sep.apps.alerts.config import AlertsSettings\n"
            "else:\n"
            "    from app.sep.apps.alerts.config import alerts_settings\n",
            {"alerts"},
            id="type-checking-guard-else-branch",
        ),
        pytest.param(
            "from .apps.alerts.config import alerts_settings",
            {"alerts"},
            id="relative-same-level",
        ),
        pytest.param(
            "from ..sep.apps.alerts.config import alerts_settings",
            {"alerts"},
            id="relative-parent-level",
        ),
        pytest.param(
            "from . import apps",
            set(),
            id="relative-shared-package",
        ),
        pytest.param(
            'import_var(path="app.sep.apps.alerts.config:alerts_settings")',
            {"alerts"},
            id="dynamic-keyword-target",
        ),
        pytest.param(
            "from app.sep.apps import labels, nav_icons",
            set(),
            id="shared-modules",
        ),
        pytest.param(
            "from app.sep.apps.framework.registry import get_app_registry",
            set(),
            id="infrastructure-package",
        ),
    ],
)
def test_import_time_edges_resolve_only_stripped_app_packages(
    source: str, expected: set[str]
) -> None:
    """Resolve an app package only for edges that execute when the module loads.

    Each source is parsed as if it were a module in ``app.sep``, so the relative
    cases resolve against the package a core module like ``app/sep/main.py``
    would carry.
    """
    app_packages = _app_package_names(APPS_ROOT)
    reached = {
        package
        for module, _ in _import_time_imports(ast.parse(source), "app.sep")
        if (package := _app_package_of(module, app_packages)) is not None
    }
    assert reached == expected


@pytest.mark.parametrize("name", ["labels", "nav_icons"])
def test_shared_app_modules_are_not_treated_as_app_packages(name: str) -> None:
    """Omit the shared ``app/sep/apps/*.py`` modules from the app package set."""
    assert name not in _app_package_names(APPS_ROOT)


@pytest.mark.parametrize("name", sorted(INFRASTRUCTURE_PACKAGES))
def test_infrastructure_packages_are_not_treated_as_app_packages(name: str) -> None:
    """Omit ``framework`` and ``shared`` from the app package set."""
    assert (APPS_ROOT / name).is_dir()
    assert name not in _app_package_names(APPS_ROOT)
