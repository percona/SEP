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

"""Guard the import boundaries the ``app/`` tree depends on.

Guards the boundary between every module and the activatable apps, and
the form-backfill contract against its orchestrator.

The PMM-embedded side-car image strips non-activated packages from
``app/sep/apps/``, so a module that ships in the image must hold no import-time
edge into a package the image strips. This module walks the ``app/`` tree with
:mod:`ast` and enforces the rule that subsumes it, consulting no deployment
configuration: no module holds an import-time edge into an activatable app
package other than the one it lives in.

Both halves bind. A module that lives in no app package — everything outside
``app/sep/apps/`` plus, inside it, ``framework``/``shared`` and the apps-level
modules — may reach none of them. A module inside app package ``X`` may reach
``X`` freely and nothing else.

Two node shapes count, because both execute at import: a static ``import`` /
``from ... import``, and a dynamic import call whose target is a string literal
(``import_module("app.sep.apps.alerts.config")``,
``import_var("app.sep.apps.alerts.config:alerts_settings")``).

Two limitations are deliberate, so the guard is not mistaken for a total one:

- A dynamic import whose target is *computed* cannot be resolved statically.
  Restricting the dynamic check to literal arguments is what keeps the
  registry's activation-list-driven ``import_module(plugin.module_name)`` from
  tripping the guard — that call is the blessed activation seam, not a
  violation.
- A module-scope call to a function *imported from another module* whose body
  imports an app package is out of scope. Resolving it needs a whole-tree
  function index plus import-alias resolution, and carries false-positive risk
  the intra-module form does not.

A second walker, :func:`_declared_imports`, counts every import including
``TYPE_CHECKING`` blocks and function bodies. It pins three edges the
import-time rule cannot see: nothing under ``app/sep/apps/`` may import the
``form_backfill`` orchestrator, ``form_backfill_inventory`` may not import
``form_backfill_registry``, and no module may *defer* an edge into another
app package into a function body. Deferring does not remove the edge. In the
image that strips the package it relocates the failure into a lifespan or a
request, which is how the side-car shipped unable to serve its main API.
"""

import ast
import os
import shutil
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest

from app import BASE_DIR
from tests.app.import_ast import absolute_base, package_of

APPS_ROOT = BASE_DIR / "app" / "sep" / "apps"

INFRASTRUCTURE_PACKAGES = frozenset({"framework", "shared"})

DYNAMIC_IMPORT_CALLEES = frozenset({"import_module", "import_var"})

DYNAMIC_IMPORT_TARGET_KEYWORDS = frozenset({"name", "path"})

FORM_BACKFILL_ORCHESTRATOR = "app.sep.apps.framework.form_backfill"

FORM_BACKFILL_REGISTRY = "app.sep.apps.framework.form_backfill_registry"


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


def _simple_call_name(node: ast.Call) -> str | None:
    """Return the bare name a call invokes, when the callee is a simple reference.

    :param node: The call node to inspect.
    :return: The callee name, or ``None`` for attribute or computed callees.
    """
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _call_names_in_expr(node: ast.AST) -> set[str]:
    """Collect bare-name call targets inside ``node``, including nested calls.

    :param node: The expression subtree to scan.
    :return: Callee names resolved to simple references.
    """
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and (name := _simple_call_name(child)):
            names.add(name)
    return names


def _call_names_skipping_function_bodies(node: ast.AST) -> set[str]:
    """Collect bare-name call targets while skipping nested function bodies.

    Descends module and class bodies — both execute on import — but never into
    a ``FunctionDef`` / ``AsyncFunctionDef`` body. Decorator expressions and
    signature defaults on skipped functions are still scanned, because both
    evaluate at import time.

    :param node: The module or nested node to descend.
    :return: Callee names resolved to simple references.
    """
    names: set[str] = set()
    if isinstance(node, ast.Call) and (name := _simple_call_name(node)):
        names.add(name)
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            for decorator in child.decorator_list:
                names |= _call_names_in_expr(decorator)
            for default in child.args.defaults:
                names |= _call_names_in_expr(default)
            for default in child.args.kw_defaults:
                if default is not None:
                    names |= _call_names_in_expr(default)
            continue
        names |= _call_names_skipping_function_bodies(child)
    return names


def _index_top_level_functions(
    module: ast.Module,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Index a module's top-level function definitions by name.

    :param module: The parsed module to index.
    :return: Top-level ``FunctionDef`` / ``AsyncFunctionDef`` nodes keyed by name.
    """
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in module.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions[node.name] = node
    return functions


def _reachable_local_functions(
    module: ast.Module,
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> set[str]:
    """Return local functions whose bodies may execute when the module loads.

    Seeds from module-scope statements, class bodies, decorator calls, and
    signature defaults; expands transitively through calls made by already-
    reached functions. Only bare-name calls to a top-level local definition
    are traced.

    :param module: The parsed module to analyse.
    :param functions: Top-level function definitions keyed by name.
    :return: Names of local functions reachable at import time.
    """
    pending = list(_call_names_skipping_function_bodies(module))
    reachable: set[str] = set()
    while pending:
        name = pending.pop()
        if name in reachable or name not in functions:
            continue
        reachable.add(name)
        for statement in functions[name].body:
            pending.extend(_call_names_skipping_function_bodies(statement))
    return reachable


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
        base = absolute_base(node, package)
        if base:
            yield base, node.lineno
            for alias in node.names:
                yield f"{base}.{alias.name}", node.lineno
    elif isinstance(node, ast.Call):
        target = _dynamic_import_target(node)
        if target is not None:
            yield target, node.lineno


def _descend_import_time_nodes(
    node: ast.AST, package: str
) -> Iterator[tuple[str, int]]:
    """Descend ``node`` for import-time edges, skipping function bodies.

    :param node: The module or nested node to descend.
    :param package: The dotted package the importing module belongs to.
    :return: An iterator of dotted module paths with their line numbers.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if _is_type_checking_guard(child):
            for fallback in child.orelse:
                yield from _import_time_imports(fallback, package)
            continue
        yield from _import_time_imports(child, package)


def _import_time_imports(node: ast.AST, package: str) -> Iterator[tuple[str, int]]:
    """Yield ``(module, lineno)`` for each import executed when the module loads.

    Descends the module body and class bodies — both execute on import — but
    never into a function body, at any nesting depth. :func:`ast.walk` cannot
    express that: it queues a node's children before yielding the node, so
    skipping a ``FunctionDef`` mid-walk still lets its already-queued body
    surface. An ``if TYPE_CHECKING:`` guard is descended on its ``else`` branch
    only, since that is the branch a real interpreter runs.

    For a module, also traces intra-module call chains: a top-level function
    whose body imports and is reached from an import-time call site — including
    transitively through other local functions — contributes its body imports.

    :param node: The module or nested node to descend.
    :param package: The dotted package the importing module belongs to.
    :return: An iterator of dotted module paths with their line numbers.
    """
    yield from _direct_import_edges(node, package)
    if isinstance(node, ast.Import | ast.ImportFrom):
        return
    if isinstance(node, ast.Module):
        functions = _index_top_level_functions(node)
        yield from _descend_import_time_nodes(node, package)
        for name in _reachable_local_functions(node, functions):
            yield from _import_time_imports(functions[name], package)
        return
    yield from _descend_import_time_nodes(node, package)


def _declared_imports(tree: ast.AST, package: str) -> Iterator[tuple[str, int]]:
    """Yield every import ``tree`` declares, including ``TYPE_CHECKING`` and function bodies.

    :param tree: The parsed module.
    :param package: The dotted package the importing module belongs to.
    :return: An iterator of dotted module paths with their line numbers.
    """
    for node in ast.walk(tree):
        yield from _direct_import_edges(node, package)


def _imports_target(imported: str, target: str) -> bool:
    """Report whether ``imported`` is ``target`` or a submodule of it.

    The trailing-dot prefix is required so ``form_backfill`` does not match
    ``form_backfill_registry`` or ``form_backfill_inventory``.

    :param imported: The dotted path an import edge resolves.
    :param target: The module that must not be reached.
    :return: Whether the edge reaches ``target``.
    """
    return imported == target or imported.startswith(f"{target}.")


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


def _skip_vanished_directory(error: OSError) -> None:
    """Swallow a directory that vanished mid-walk, and re-raise anything else.

    :param error: The failure :func:`os.walk` hit while scanning a directory.
    :raises OSError: When the scan failed for any reason other than the directory
        being gone.
    """
    if not isinstance(error, FileNotFoundError):
        raise error


def _module_paths_under(root: Path) -> Iterator[Path]:
    """Yield every ``*.py`` module under ``root``, tolerating a vanished directory.

    ``Path.rglob`` is not usable here. It re-scans each directory it descends into,
    and on the oldest Python this project supports that scan is guarded against a
    permission failure only, so a scaffold package another worker removes after it was
    listed but before the descent reaches it aborts the whole walk. :func:`os.walk`
    reports such a failure to a handler instead, which lets a missing directory be
    skipped while every other scan failure still raises.

    Symlinked directories are left unwalked, matching what the ``rglob`` walk did and
    keeping a link loop from trapping the walk.

    :param root: The tree root to walk.
    :return: An iterator of module paths, in whatever order the walk reaches them.
    """
    for directory, _, filenames in os.walk(root, onerror=_skip_vanished_directory):
        for filename in filenames:
            if filename.endswith(".py"):
                yield Path(directory) / filename


def test_skip_vanished_directory_swallows_a_directory_that_is_gone(
    tmp_path: Path,
) -> None:
    """Let the walk continue past a directory removed since it was listed.

    :param tmp_path: The directory the missing path is addressed under.
    """
    error = FileNotFoundError(2, "No such file or directory")
    error.filename = str(tmp_path / "gone")
    assert _skip_vanished_directory(error) is None


def test_skip_vanished_directory_reraises_any_other_scan_failure() -> None:
    """Fail loudly when a directory is there but cannot be scanned.

    A directory the walk may not read is not a directory that vanished, and
    swallowing it would drop every module under it from the guard silently.
    """
    with pytest.raises(PermissionError):
        _skip_vanished_directory(PermissionError(13, "Permission denied"))


def test_module_paths_under_yields_every_nested_module(tmp_path: Path) -> None:
    """Yield modules at every depth, and nothing that is not a module.

    :param tmp_path: The tree root the modules are written under.
    """
    (tmp_path / "pkg" / "sub").mkdir(parents=True)
    (tmp_path / "top.py").touch()
    (tmp_path / "pkg" / "mid.py").touch()
    (tmp_path / "pkg" / "sub" / "deep.py").touch()
    (tmp_path / "pkg" / "notes.txt").touch()
    assert sorted(_module_paths_under(tmp_path)) == [
        tmp_path / "pkg" / "mid.py",
        tmp_path / "pkg" / "sub" / "deep.py",
        tmp_path / "top.py",
    ]


def test_module_paths_under_walks_past_a_directory_that_vanished(
    tmp_path: Path,
) -> None:
    """Keep walking when a directory disappears after it was listed.

    This is the failure the tolerant read alone cannot cover: the walk re-scans each
    directory it descends into, and on the oldest Python this project supports that
    scan is guarded against a permission failure but not against the directory having
    been removed in the meantime. Removing it between the root's own modules and the
    descent reproduces exactly that window.

    :param tmp_path: The tree root the modules are written under.
    """
    (tmp_path / "kept").mkdir()
    (tmp_path / "kept" / "a.py").touch()
    doomed = tmp_path / "doomed"
    doomed.mkdir()
    (doomed / "b.py").touch()
    (tmp_path / "top.py").touch()

    walk = _module_paths_under(tmp_path)
    assert next(walk) == tmp_path / "top.py"
    shutil.rmtree(doomed)
    assert sorted(walk) == [tmp_path / "kept" / "a.py"]


def test_module_paths_under_does_not_follow_a_symlinked_directory(
    tmp_path: Path,
) -> None:
    """Leave a symlinked directory unwalked, so a link loop cannot trap the walk.

    :param tmp_path: The tree root the modules and the link are created under.
    """
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "a.py").touch()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    assert sorted(_module_paths_under(tmp_path)) == [tmp_path / "real" / "a.py"]


def _guarded_module_paths() -> Iterator[Path]:
    """Yield every ``app/**/*.py`` module the boundary rule binds.

    The walk applies no name filter, unlike :func:`_app_package_names`. Skipping an
    underscore-prefixed directory here would look like a cheap way to step around the
    scaffold packages another worker creates mid-scan, but the names those tests use
    are not uniformly underscore-prefixed, the same prefix would catch
    ``app/sep/apps/__init__.py``, and any name-based skip leaves a real module
    unchecked the day one is named to match. Churn is absorbed by the walk and the
    read instead: :func:`_module_paths_under` skips a directory that vanished, and
    :func:`_parse_module` treats a path that vanished as no module to check.

    :return: An iterator of source paths, the whole ``app/`` tree.
    """
    yield from sorted(_module_paths_under(BASE_DIR / "app"))


def _apps_tree_module_paths() -> Iterator[Path]:
    """Yield every ``app/sep/apps/**/*.py`` module the apps-tree guards scan.

    :return: An iterator of source paths under ``app/sep/apps/``.
    """
    yield from sorted(_module_paths_under(APPS_ROOT))


def _parse_module(path: Path) -> ast.Module | None:
    """Parse ``path``, or report that it vanished before it could be read.

    The scaffolder writes into the live source tree by design, so a scaffold test
    running on another ``pytest-xdist`` worker creates and removes real packages under
    ``app/sep/apps/`` while this walk is listing and reading it. A path listed a moment
    ago can therefore be gone by the time it is read, and a path that no longer exists
    is not a module to check.

    Only that case is tolerated. A parse or decode failure still raises, because those
    are failures of a module that is really there — swallowing them would narrow the
    guard to whatever happens to read cleanly.

    :param path: The source path to read and parse.
    :return: The parsed module, or ``None`` when the path no longer exists.
    :raises SyntaxError: When the module is there but does not parse.
    :raises UnicodeDecodeError: When the module's bytes are not UTF-8.
    :raises OSError: When the read fails for any reason other than the path being
        gone — a permission failure, say.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return ast.parse(source)


def _parsed_modules(paths: Iterable[Path]) -> Iterator[tuple[Path, ast.Module]]:
    """Parse each of ``paths``, skipping any that vanished before it was read.

    :param paths: The source paths to parse.
    :return: An iterator of ``(path, tree)`` pairs over the paths that still exist.
    """
    for path in paths:
        if (tree := _parse_module(path)) is not None:
            yield path, tree


def _owning_app_package(path: Path, app_packages: set[str]) -> str | None:
    """Return the activatable app package ``path`` lives in, if any.

    :param path: The source path to classify.
    :param app_packages: The activatable app package names.
    :return: The owning app package, or ``None`` for a module outside them --
        including ``framework``/``shared`` and the apps-level modules.
    """
    if not path.is_relative_to(APPS_ROOT):
        return None
    head = path.relative_to(APPS_ROOT).parts[0]
    return head if head in app_packages else None


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


def _violations(
    modules: Iterable[tuple[Path, ast.Module]] | None = None,
) -> list[str]:
    """Collect every import-time edge into an app package other than the owner's.

    Deduplicated by ``(path, line, target)``, on the same reasoning as
    :func:`_deferred_violations`: the line collapses a statement's base module
    and its aliases, and the resolved package keeps a statement reaching two of
    them from collapsing to whichever resolved first.

    :param modules: The ``(path, tree)`` pairs to scan. Defaults to the whole
        guarded tree parsed from disk (:func:`_parsed_guarded_modules`).
        Passing pairs directly lets a case drive the collector over a
        synthetic tree attributed to a real path.
    :return: One ``path:line -> module`` entry per violating import.
    """
    app_packages = _app_package_names(APPS_ROOT)
    found: list[str] = []
    seen: set[tuple[Path, int, str]] = set()
    for path, tree in _parsed_guarded_modules() if modules is None else modules:
        owner = _owning_app_package(path, app_packages)
        for module, lineno in _import_time_imports(tree, package_of(path, BASE_DIR)):
            target = _app_package_of(module, app_packages)
            if target is None or target == owner:
                continue
            if (path, lineno, target) in seen:
                continue
            seen.add((path, lineno, target))
            found.append(f"{path.relative_to(BASE_DIR)}:{lineno} -> {module}")
    return found


def test_no_module_imports_another_app_package() -> None:
    """Reject every import-time edge into an app package other than the owner's."""
    violations = _violations()
    assert not violations, (
        "no module may import an activatable app package other than the one it"
        " lives in at import time (the PMM-embedded image strips them):\n"
        + "\n".join(violations)
    )


@pytest.mark.parametrize(
    ("importer", "source", "expected"),
    [
        pytest.param(
            "app/sep/main.py",
            "from app.sep.apps.alerts.config import AlertsSettings\n",
            ["app/sep/main.py:1 -> app.sep.apps.alerts.config"],
            id="import-time-edge-reported-once",
        ),
        pytest.param(
            "app/sep/apps/inventory/deps.py",
            "from app.sep.apps.inventory.sync import run_inventory_sync\n",
            [],
            id="own-package-edge-exempt",
        ),
        pytest.param(
            "app/sep/main.py",
            "from app.sep.apps import alerts, dipper\n",
            [
                "app/sep/main.py:1 -> app.sep.apps.alerts",
                "app/sep/main.py:1 -> app.sep.apps.dipper",
            ],
            id="two-packages-on-one-line-both-reported",
        ),
        pytest.param(
            "app/sep/main.py",
            "def _lazy():\n    from app.sep.apps.alerts.config import AlertsSettings\n",
            [],
            id="deferred-edge-left-to-the-other-guard",
        ),
    ],
)
def test_violations_over_a_synthetic_tree(
    importer: str, source: str, expected: list[str]
) -> None:
    """Reject an import-time edge driven over a synthetic tree attributed to a real path.

    Mirrors :func:`test_deferred_violations_over_a_synthetic_tree` for the import-time
    collector, so the rule the live-tree case asserts vacuously — a green tree yields
    an empty list either way — is pinned against a tree that does violate it. The
    first case also pins the dedup collapsing one statement, since
    :func:`_direct_import_edges` yields the base module and the alias path for it.

    :param importer: The real path the synthetic source is attributed to.
    :param source: The module source to parse.
    :param expected: The rendered violations the collector must report.
    """
    path = BASE_DIR / importer
    assert _violations([(path, ast.parse(source))]) == expected


def test_violations_tolerate_a_path_that_vanished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report nothing, rather than raising, when a listed path is already gone.

    :param monkeypatch: The fixture used to point the walk at a vanished path.
    """
    monkeypatch.setattr(
        f"{__name__}._guarded_module_paths",
        lambda: iter([APPS_ROOT / "_vanished_app" / "app.py"]),
    )
    assert _violations() == []


def _parsed_guarded_modules() -> Iterator[tuple[Path, ast.Module]]:
    """Parse every module the boundary rule binds.

    :return: An iterator of ``(path, tree)`` pairs over the guarded tree.
    """
    yield from _parsed_modules(_guarded_module_paths())


def _deferred_violations(
    modules: Iterable[tuple[Path, ast.Module]] | None = None,
) -> list[str]:
    """Collect every deferred edge into an app package other than the owner's.

    A deferred edge is one :func:`_declared_imports` sees and
    :func:`_import_time_imports` does not: a function-body import, or one
    under ``TYPE_CHECKING``.

    Deduplicated by ``(path, line, target)``: a ``from ... import`` yields the
    base module *and* one path per alias, so a single statement would otherwise
    be reported once per name it binds. Keying on the line alone would also
    collapse a statement reaching *two* app packages (``from app.sep.apps
    import alerts, dipper``) down to whichever resolved first, so the resolved
    package is part of the key. Within one package the earliest spelling
    renders, because :func:`_direct_import_edges` yields the base module before
    the aliases. A base module resolving to no app package is skipped outright,
    which is what lets the multi-package form report each package it names.

    :param modules: The ``(path, tree)`` pairs to scan. Defaults to the whole
        guarded tree parsed from disk (:func:`_parsed_guarded_modules`).
        Passing pairs directly lets a case drive the collector over a
        synthetic tree attributed to a real path.
    :return: One ``path:line -> module`` entry per violating import.
    """
    app_packages = _app_package_names(APPS_ROOT)
    found: list[str] = []
    seen: set[tuple[Path, int, str]] = set()
    for path, tree in _parsed_guarded_modules() if modules is None else modules:
        owner = _owning_app_package(path, app_packages)
        package = package_of(path, BASE_DIR)
        at_import = set(_import_time_imports(tree, package))
        for module, lineno in _declared_imports(tree, package):
            if (module, lineno) in at_import:
                continue
            target = _app_package_of(module, app_packages)
            if target is None or target == owner:
                continue
            if (path, lineno, target) in seen:
                continue
            seen.add((path, lineno, target))
            found.append(f"{path.relative_to(BASE_DIR)}:{lineno} -> {module}")
    return found


def test_no_module_defers_an_import_into_another_app_package() -> None:
    """Reject a deferred edge into an app package other than the owner's.

    The PMM-embedded image strips the package from disk, so deferring the import
    into a function body postpones the failure into a lifespan or a request
    rather than removing it, which is how the side-car shipped unable to serve
    its main API.
    """
    violations = _deferred_violations()
    assert not violations, (
        "no module may import an activatable app package other than the one it"
        " lives in, even from a function body (the PMM-embedded image strips"
        " them):\n" + "\n".join(violations)
    )


@pytest.mark.parametrize(
    ("importer", "source", "expected"),
    [
        pytest.param(
            "app/sep/main.py",
            "def _lazy():\n    from app.sep.apps.alerts.config import AlertsSettings\n",
            ["app/sep/main.py:2 -> app.sep.apps.alerts.config"],
            id="function-body-edge-reported-once",
        ),
        pytest.param(
            "app/sep/main.py",
            "if TYPE_CHECKING:\n"
            "    from app.sep.apps.alerts.config import AlertsSettings\n",
            ["app/sep/main.py:2 -> app.sep.apps.alerts.config"],
            id="type-checking-edge-reported",
        ),
        pytest.param(
            "app/sep/main.py",
            "from app.sep.apps.alerts.config import AlertsSettings\n",
            [],
            id="import-time-edge-not-deferred",
        ),
        pytest.param(
            "app/sep/main.py",
            "def _lazy():\n"
            "    from app.sep.apps.alerts.config import AlertsSettings\n"
            "_lazy()\n",
            [],
            id="function-body-reachable-at-import-not-deferred",
        ),
        pytest.param(
            "app/sep/apps/inventory/deps.py",
            "def _lazy():\n"
            "    from app.sep.apps.inventory.sync import run_inventory_sync\n",
            [],
            id="own-package-edge-exempt",
        ),
        pytest.param(
            "app/sep/main.py",
            "def _lazy():\n    from app.sep.apps import alerts, dipper\n",
            [
                "app/sep/main.py:2 -> app.sep.apps.alerts",
                "app/sep/main.py:2 -> app.sep.apps.dipper",
            ],
            id="two-packages-on-one-line-both-reported",
        ),
    ],
)
def test_deferred_violations_over_a_synthetic_tree(
    importer: str, source: str, expected: list[str]
) -> None:
    """Reject a deferred edge driven over a synthetic tree attributed to a real path.

    Each source is parsed as if it were the module at ``importer``, so both the
    owner exemption and the rendered path come from that real path, mirroring
    :func:`test_import_time_edges_ignore_a_modules_own_app_package`. The first two
    cases pin the function-body and ``TYPE_CHECKING`` shapes this guard exists to
    catch; the function-body case also pins the dedup collapsing one statement,
    since :func:`_direct_import_edges` yields the base module and the alias path
    for it. Three cases pin what the guard must NOT report: an import-time edge
    (``_violations``' business, not this guard's), a function-body edge the
    module reaches at import through a call, and an edge into the importer's own
    app package. The last case pins the other half of the dedup: one statement
    reaching two app packages reports both, which keying on ``(path, line)``
    alone would collapse to whichever resolved first.
    """
    path = BASE_DIR / importer
    assert _deferred_violations([(path, ast.parse(source))]) == expected


def test_deferred_violations_tolerate_a_path_that_vanished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report nothing, rather than raising, when a listed path is already gone.

    :param monkeypatch: The fixture used to point the walk at a vanished path.
    """
    monkeypatch.setattr(
        f"{__name__}._guarded_module_paths",
        lambda: iter([APPS_ROOT / "_vanished_app" / "app.py"]),
    )
    assert _deferred_violations() == []


def test_parse_module_skips_a_path_that_vanished(tmp_path: Path) -> None:
    """Treat a path removed before it was read as not a module to check.

    :param tmp_path: The directory the missing path is addressed under.
    """
    assert _parse_module(tmp_path / "vanished.py") is None


def test_parse_module_skips_a_dangling_symlink(tmp_path: Path) -> None:
    """Treat a symlink with no target as not a module to check.

    A walk yields a dangling symlink like any other file, since it is not a directory
    to descend into, so the read behind it must not be the thing that fails.

    :param tmp_path: The directory the symlink is created in.
    """
    link = tmp_path / "dangling.py"
    link.symlink_to(tmp_path / "missing_target.py")
    assert _parse_module(link) is None


def test_parse_module_parses_a_module_that_exists(tmp_path: Path) -> None:
    """Parse a real file, so tolerating a vanished path is not tolerating every path.

    :param tmp_path: The directory the module is written to.
    """
    path = tmp_path / "present.py"
    path.write_text(
        "from app.sep.apps.alerts.config import alerts_settings\n", encoding="utf-8"
    )
    tree = _parse_module(path)
    assert tree is not None
    assert [target for target, _ in _declared_imports(tree, "app.sep")] == [
        "app.sep.apps.alerts.config",
        "app.sep.apps.alerts.config.alerts_settings",
    ]


def test_parse_module_rejects_a_module_it_cannot_parse(tmp_path: Path) -> None:
    """Fail loudly on a module that exists but does not parse.

    Only a vanished path is tolerated. Swallowing a parse failure would let a real,
    stable module drop out of the walk unnoticed.

    :param tmp_path: The directory the module is written to.
    """
    path = tmp_path / "broken.py"
    path.write_text("def _lazy(:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        _parse_module(path)


def test_parse_module_rejects_bytes_it_cannot_decode(tmp_path: Path) -> None:
    """Fail loudly on a module whose bytes are not UTF-8.

    The tolerance is existence-based on purpose, and only ``FileNotFoundError`` names
    that case. A module whose bytes cannot be decoded is really there, so letting it
    pass would silently narrow the guard to whatever happens to read cleanly.

    :param tmp_path: The directory the module is written to.
    """
    path = tmp_path / "garbled.py"
    path.write_bytes(b"import os\n\xff\xfe\n")
    with pytest.raises(UnicodeDecodeError):
        _parse_module(path)


def test_parsed_modules_walks_past_a_path_that_vanished() -> None:
    """Keep parsing the paths that are still there after skipping one that is not.

    The vanished path comes first, so a walk that aborted on it would never reach the
    real module behind it — which is what the concurrent-scaffold failure looked like.
    """
    present = BASE_DIR / "app" / "sep" / "main.py"
    parsed = list(_parsed_modules([APPS_ROOT / "_vanished_app" / "app.py", present]))
    assert [path for path, _ in parsed] == [present]
    assert isinstance(parsed[0][1], ast.Module)


def _apps_tree_modules_not_guarded(guarded: set[Path] | None = None) -> set[Path]:
    """Return the apps-tree modules the guarded walk leaves out.

    The narrow apps-tree sample is taken *before* the wider guarded walk, and a path
    that no longer exists is dropped, so neither half of a scaffold test's churn can
    fail this comparison: a package created between the two walks lands in the later,
    wider one, and a package removed between them fails the existence check. Only a
    structural exclusion survives both.

    :param guarded: The guarded walk's result to compare against. Defaults to a fresh
        :func:`_guarded_module_paths` walk; passing a set lets a case prove the
        comparison still reports a real gap.
    :return: Paths under ``app/sep/apps/`` the guarded walk does not cover.
    """
    apps_tree = set(_apps_tree_module_paths())
    covered = set(_guarded_module_paths()) if guarded is None else guarded
    return {path for path in apps_tree - covered if path.exists()}


@pytest.fixture(scope="module")
def guarded_paths() -> set[Path]:
    """Walk the guarded tree once for every case that asserts membership in it.

    :return: Every source path :func:`_guarded_module_paths` yields.
    """
    return set(_guarded_module_paths())


@pytest.mark.parametrize(
    "relative",
    [
        "app/sep/main.py",
        "app/sep/apps/framework/form_backfill.py",
        "app/sep/apps/shared/disk_script_source.py",
        "app/sep/apps/__init__.py",
        "app/sep/apps/labels.py",
        "app/sep/apps/nav_icons.py",
        "app/sep/apps/inventory/app.py",
        "app/sep/apps/alters/app.py",
    ],
)
def test_guarded_module_paths_covers_every_app_module(
    relative: str, guarded_paths: set[Path]
) -> None:
    """Bind the rule to the apps-tree modules an outside-only walk would skip."""
    assert BASE_DIR / relative in guarded_paths


def test_guarded_module_paths_leaves_no_apps_tree_module_out() -> None:
    """Reject any walk that covers only part of the activatable-app tree.

    The cases above sample the regions an outside-only walk skipped wholesale.
    A narrower exclusion — one app package, one subtree — would leave every
    sample present, and the live-tree test green, since a walk that reaches
    fewer files finds fewer violations.
    """
    assert _apps_tree_modules_not_guarded() == set()


def test_apps_tree_gap_survives_the_transient_path_tolerance() -> None:
    """Report a gap when the guarded walk genuinely skips part of the apps tree.

    Tolerating a path that appears or vanishes mid-scan must not turn the coverage
    check into one that reports nothing: handed a walk missing a whole real subtree, it
    still names every module left out. The assertion is a subset rather than an
    equality because a scaffold package another worker creates would legitimately show
    up alongside the excluded subtree; ``framework`` is a committed package, so its own
    modules cannot come and go.
    """
    framework_modules = set(_module_paths_under(APPS_ROOT / "framework"))
    partial = {
        path for path in _guarded_module_paths() if path not in framework_modules
    }
    assert framework_modules <= _apps_tree_modules_not_guarded(partial)


@pytest.mark.parametrize(
    ("importer", "source", "expected"),
    [
        pytest.param(
            "app/sep/apps/inventory/deps.py",
            "from app.sep.apps.inventory.sync import run_inventory_sync",
            set(),
            id="own-package-exempt",
        ),
        pytest.param(
            "app/sep/apps/framework/form_backfill.py",
            "from app.sep.apps.inventory.sync import run_inventory_sync",
            {"inventory"},
            id="no-owner-nothing-exempt",
        ),
        pytest.param(
            "app/sep/apps/inventory/deps.py",
            "from app.sep.apps.alters.app import app",
            {"alters"},
            id="sibling-package-not-exempt",
        ),
        pytest.param(
            "app/sep/apps/mysql_backups/restore/app.py",
            "from app.sep.apps.mysql_backups.restore.app import app",
            set(),
            id="own-package-subtree-exempt",
        ),
        pytest.param(
            "app/sep/apps/inventory/deps.py",
            "def _lazy():\n"
            "    from app.sep.apps.inventory.sync import run_inventory_sync\n"
            "_lazy()",
            set(),
            id="own-package-through-local-call",
        ),
    ],
)
def test_import_time_edges_ignore_a_modules_own_app_package(
    importer: str, source: str, expected: set[str]
) -> None:
    """Ignore an edge only when it resolves the importing module's own package.

    Each source is parsed as if it were the module at ``importer``, so the owner
    the rule exempts is the one :func:`_owning_app_package` derives from that
    real path.
    """
    path = BASE_DIR / importer
    app_packages = _app_package_names(APPS_ROOT)
    owner = _owning_app_package(path, app_packages)
    reached = {
        target
        for module, _ in _import_time_imports(
            ast.parse(source), package_of(path, BASE_DIR)
        )
        if (target := _app_package_of(module, app_packages)) is not None
        and target != owner
    }
    assert reached == expected


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
        pytest.param(
            "def _lazy():\n"
            "    from app.sep.apps.alerts.config import alerts_settings\n"
            "_lazy()",
            {"alerts"},
            id="module-scope-local-call",
        ),
        pytest.param(
            "def _lazy():\n"
            "    from app.sep.apps.alerts.config import alerts_settings\n"
            "def _middle():\n"
            "    _lazy()\n"
            "_middle()",
            {"alerts"},
            id="transitive-local-call",
        ),
        pytest.param(
            "def _a():\n    _b()\ndef _b():\n    _a()\n_a()",
            set(),
            id="mutually-recursive-local-call",
        ),
        pytest.param(
            "def _lazy():\n"
            "    from app.sep.apps.alerts.config import alerts_settings\n"
            "class Holder:\n"
            "    _lazy()",
            {"alerts"},
            id="class-body-local-call",
        ),
        pytest.param(
            "def _lazy():\n"
            "    from app.sep.apps.alerts.config import alerts_settings\n"
            "@_lazy()\n"
            "def _main():\n"
            "    pass",
            {"alerts"},
            id="decorator-call",
        ),
        pytest.param(
            "def _lazy():\n"
            "    from app.sep.apps.alerts.config import alerts_settings\n"
            "@_lazy\n"
            "def _main():\n"
            "    pass",
            set(),
            id="bare-decorator-reference",
        ),
        pytest.param(
            "def _lazy():\n"
            "    from app.sep.apps.alerts.config import alerts_settings\n"
            "def _main(x=_lazy()):\n"
            "    pass",
            {"alerts"},
            id="signature-default-call",
        ),
        pytest.param(
            "def _lazy():\n"
            "    from app.sep.apps.alerts.config import alerts_settings\n"
            "def _main(*, x=_lazy()):\n"
            "    pass",
            {"alerts"},
            id="signature-keyword-default-call",
        ),
        pytest.param(
            "def _outer():\n"
            "    def _lazy():\n"
            "        from app.sep.apps.alerts.config import alerts_settings\n"
            "    _lazy()",
            set(),
            id="nested-function-only-reachable",
        ),
        pytest.param(
            "import os\nos.path.join('a', 'b')",
            set(),
            id="imported-symbol-call",
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


@pytest.mark.parametrize(
    ("imported", "target"),
    [
        pytest.param(
            "app.sep.apps.framework.form_backfill",
            FORM_BACKFILL_ORCHESTRATOR,
            id="exact-orchestrator",
        ),
        pytest.param(
            "app.sep.apps.framework.form_backfill.FormBackfillContext",
            FORM_BACKFILL_ORCHESTRATOR,
            id="orchestrator-alias",
        ),
        pytest.param(
            "app.sep.apps.framework.form_backfill_registry.FormBackfillEntry",
            FORM_BACKFILL_REGISTRY,
            id="registry-alias",
        ),
    ],
)
def test_imports_target_matches_at_a_module_boundary(
    imported: str, target: str
) -> None:
    """Match a module at a dotted boundary, including a ``from`` alias."""
    assert _imports_target(imported, target)


@pytest.mark.parametrize(
    "imported",
    [
        pytest.param(
            "app.sep.apps.framework.form_backfill_registry",
            id="registry",
        ),
        pytest.param(
            "app.sep.apps.framework.form_backfill_inventory",
            id="inventory",
        ),
    ],
)
def test_imports_target_rejects_a_shared_name_prefix(imported: str) -> None:
    """Refuse a prefix match against ``form_backfill_registry`` or ``_inventory``."""
    assert not _imports_target(imported, FORM_BACKFILL_ORCHESTRATOR)


def test_declared_imports_count_type_checking_guards() -> None:
    """Surface an import written inside ``if TYPE_CHECKING:``.

    Without this, the orchestrator and inventory guards would pass vacuously
    if :func:`_declared_imports` ever started skipping the same branch
    :func:`_import_time_imports` skips.
    """
    source = (
        "if TYPE_CHECKING:\n"
        "    from app.sep.apps.framework.form_backfill import FormBackfillContext\n"
    )
    tree = ast.parse(source)
    declared = {module for module, _ in _declared_imports(tree, "app.sep")}
    import_time = {module for module, _ in _import_time_imports(tree, "app.sep")}
    assert FORM_BACKFILL_ORCHESTRATOR in declared
    assert FORM_BACKFILL_ORCHESTRATOR not in import_time


def _orchestrator_import_edges(
    modules: Iterable[tuple[Path, ast.Module]] | None = None,
) -> list[str]:
    """Collect every declared import of the form-backfill orchestrator.

    The orchestrator's own module is exempt, and an edge is reported once per
    statement rather than once per name the statement binds.

    :param modules: The ``(path, tree)`` pairs to scan. Defaults to the whole
        ``app/sep/apps/`` tree parsed from disk, skipping any path that vanished
        mid-scan. Passing pairs directly lets a case drive the collector over a
        synthetic tree attributed to a real path.
    :return: One ``path:line -> module`` entry per importing statement.
    """
    orchestrator_path = APPS_ROOT / "framework" / "form_backfill.py"
    if modules is None:
        modules = _parsed_modules(_apps_tree_module_paths())
    found: list[str] = []
    seen: set[tuple[Path, int]] = set()
    for path, tree in modules:
        if path == orchestrator_path:
            continue
        for module, lineno in _declared_imports(tree, package_of(path, BASE_DIR)):
            if not _imports_target(module, FORM_BACKFILL_ORCHESTRATOR):
                continue
            if (path, lineno) in seen:
                continue
            seen.add((path, lineno))
            found.append(f"{path.relative_to(BASE_DIR)}:{lineno} -> {module}")
    return found


def test_no_apps_module_imports_the_form_backfill_orchestrator() -> None:
    """Reject any import of the orchestrator from under ``app/sep/apps/``.

    The orchestrator is a one-shot ``python -m`` entry point. Counting
    ``TYPE_CHECKING`` imports is the point: an annotation-only edge is invisible
    to :func:`_import_time_imports` yet still couples the contract to its
    consumer.
    """
    found = _orchestrator_import_edges()
    assert not found, (
        "no module under app/sep/apps/ may import"
        f" {FORM_BACKFILL_ORCHESTRATOR} (runtime or TYPE_CHECKING):\n"
        + "\n".join(found)
    )


@pytest.mark.parametrize(
    ("importer", "source", "expected"),
    [
        pytest.param(
            "app/sep/apps/alerts/app.py",
            "from app.sep.apps.framework.form_backfill import FormBackfillContext\n",
            ["app/sep/apps/alerts/app.py:1 -> app.sep.apps.framework.form_backfill"],
            id="runtime-edge-reported",
        ),
        pytest.param(
            "app/sep/apps/alerts/app.py",
            "if TYPE_CHECKING:\n"
            "    from app.sep.apps.framework.form_backfill import FormBackfillContext\n",
            ["app/sep/apps/alerts/app.py:2 -> app.sep.apps.framework.form_backfill"],
            id="type-checking-edge-reported",
        ),
        pytest.param(
            "app/sep/apps/framework/form_backfill.py",
            "from app.sep.apps.framework.form_backfill import FormBackfillContext\n",
            [],
            id="orchestrator-itself-exempt",
        ),
        pytest.param(
            "app/sep/apps/alerts/app.py",
            "from app.sep.apps.framework.form_backfill_registry import"
            " FormBackfillEntry\n",
            [],
            id="registry-is-not-the-orchestrator",
        ),
    ],
)
def test_orchestrator_import_edges_over_a_synthetic_tree(
    importer: str, source: str, expected: list[str]
) -> None:
    """Report an orchestrator edge driven over a synthetic tree attributed to a real path.

    :param importer: The real path the synthetic source is attributed to.
    :param source: The module source to parse.
    :param expected: The rendered edges the collector must report.
    """
    path = BASE_DIR / importer
    assert _orchestrator_import_edges([(path, ast.parse(source))]) == expected


def test_orchestrator_import_edges_tolerate_a_path_that_vanished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report nothing, rather than raising, when a listed path is already gone.

    :param monkeypatch: The fixture used to point the walk at a vanished path.
    """
    monkeypatch.setattr(
        f"{__name__}._apps_tree_module_paths",
        lambda: iter([APPS_ROOT / "_vanished_app" / "app.py"]),
    )
    assert _orchestrator_import_edges() == []


def test_form_backfill_inventory_does_not_import_the_registry() -> None:
    """Reject any edge from inventory into the registry, including ``TYPE_CHECKING``.

    ``FormBackfillContext`` lives in ``form_backfill_registry``, so an inventory
    edge into the registry would reintroduce the ``TYPE_CHECKING`` cycle this
    guard exists to prevent.
    """
    path = APPS_ROOT / "framework" / "form_backfill_inventory.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    reached = [
        f"{path.relative_to(BASE_DIR)}:{lineno} -> {module}"
        for module, lineno in _declared_imports(tree, package_of(path, BASE_DIR))
        if _imports_target(module, FORM_BACKFILL_REGISTRY)
    ]
    assert not reached, (
        "form_backfill_inventory.py may not import form_backfill_registry.py:\n"
        + "\n".join(reached)
    )
