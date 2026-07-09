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

"""Render a conformant SEP app skeleton for the task, script, or base flavor.

Run as ``python -m app.sep.apps.framework.scaffold --name <name> [--type
task|script|base]`` (driven by ``make startapp``). The engine validates the
module name, refuses to clobber an existing plugin, renders the flavor's
templates into ``app/sep/apps/<name>/`` and ``tests/app/sep/apps/<name>/``,
and registers the app **disabled** under the ``default:`` ``SEP.APPS`` block so
an admin enables it from the App Manager rather than the scaffolder activating it.

Templates carry ``<< var >>`` placeholders substituted by plain string
replacement — the skeletons need no loops or conditionals, and avoiding a template
engine keeps the rendered Python free of HTML autoescaping. Imports are limited to
the standard library so ``--help`` and the render path run without touching a
database — the heavy framework package is imported only transitively through the
package ``__init__``, never by this module.
"""

import argparse
import keyword
import re
import shutil
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Flavor(StrEnum):
    """Represent the supported scaffold flavors."""

    TASK = "task"
    SCRIPT = "script"
    BASE = "base"


_NAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")
_PLACEHOLDER = re.compile(r"<<\s*(\w+)\s*>>")
_TEMPLATES_DIR = Path(__file__).parent / "templates"
_REPO_ROOT = Path(__file__).resolve().parents[4]

PLUGINS_DIR = _REPO_ROOT / "app" / "sep" / "apps"
TESTS_DIR = _REPO_ROOT / "tests" / "app" / "sep" / "apps"
SETTINGS_FILE = _REPO_ROOT / "settings.yaml"


@dataclass(frozen=True, slots=True)
class ScaffoldResult:
    """Carry the outcome of a single scaffold run for the caller's summary.

    :param name: The scaffolded app's module name.
    :param flavor: The flavor rendered.
    :param app_dir: The generated package directory under ``app/sep/apps``.
    :param tests_dir: The generated test package directory under ``tests``.
    :param written: Every file the render wrote, in render order.
    :param settings_changed: Whether the ``settings.yaml`` entry was inserted (a
        pre-existing entry leaves it ``False``).
    """

    name: str
    flavor: Flavor
    app_dir: Path
    tests_dir: Path
    written: list[Path]
    settings_changed: bool


def validate_name(name: str) -> None:
    """Reject a name that is not a usable lowercase Python package identifier.

    The registry hardcodes ``app.sep.apps.<name>`` as the import path, so the
    name must be importable as-is — no silent normalization (a slugify would emit
    hyphens or an empty string). An all-underscore name and a Python keyword are
    rejected even though both satisfy :data:`_NAME_PATTERN`.

    :param name: The candidate module name.
    :raises ValueError: When the name is empty, mixed-case, hyphenated, leads with
        a digit, is all underscores, or is a Python keyword.
    """
    if (
        not _NAME_PATTERN.match(name)
        or re.search(r"[a-z0-9]", name) is None
        or keyword.iskeyword(name)
    ):
        raise ValueError(
            f"invalid app name {name!r}: NAME must be a lowercase Python identifier "
            f"matching {_NAME_PATTERN.pattern} (letters, digits, underscores; at "
            "least one letter or digit; not a Python keyword) — for example 'my_app'"
        )


def _build_context(name: str) -> dict[str, str]:
    """Derive the template variables from the module name.

    :param name: The validated module name.
    :return: The ``name`` / ``class_prefix`` (CamelCase) / ``display_name`` (Title
        Case) mapping the templates render against.
    """
    parts = [part for part in name.split("_") if part]
    return {
        "name": name,
        "class_prefix": "".join(part[:1].upper() + part[1:] for part in parts),
        "display_name": " ".join(part[:1].upper() + part[1:] for part in parts),
    }


def _target_path(name: str, relative: Path) -> Path:
    """Map a template's path under its flavor dir to its rendered destination.

    Templates under ``tests/`` land in the app's test package; everything else
    lands in the app package (preserving subdirectories such as ``snippets/``). The
    trailing ``.tmpl`` suffix is dropped.

    :param name: The app's module name.
    :param relative: The template path relative to its flavor directory.
    :return: The absolute destination path for the rendered file.
    """
    file_name = relative.name.removesuffix(".tmpl")
    if relative.parts[0] == "tests":
        return TESTS_DIR / name / Path(*relative.parts[1:-1]) / file_name
    return PLUGINS_DIR / name / Path(*relative.parts[:-1]) / file_name


def _render(text: str, context: dict[str, str], source: Path) -> str:
    """Render the template text, substituting every ``<< var >>`` placeholder.

    :param text: The raw template text.
    :param context: The template variables from :func:`_build_context`.
    :param source: The template path, named in the error on an unknown placeholder.
    :return: The rendered text.
    :raises ValueError: When a placeholder names a variable absent from ``context``.
    """

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            raise ValueError(f"unknown placeholder '<< {key} >>' in {source}")
        return context[key]

    return _PLACEHOLDER.sub(replace, text)


def render_app(name: str, flavor: Flavor, context: dict[str, str]) -> list[Path]:
    """Render every template for ``flavor`` into the app and test trees.

    :param name: The app's module name.
    :param flavor: The flavor whose template set is rendered.
    :param context: The template variables from :func:`_build_context`.
    :return: The written file paths, in render order.
    """
    template_root = _TEMPLATES_DIR / flavor
    written = []
    for template_path in sorted(template_root.rglob("*.tmpl")):
        relative = template_path.relative_to(template_root)
        rendered = _render(template_path.read_text(), context, template_path)
        target = _target_path(name, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered)
        written.append(target)
    _ruff_fix(written)
    return written


def _ruff_fix(paths: list[Path]) -> None:
    """Run ruff lint-autofix and format on ``paths``.

    Silently skips the step when ``ruff`` is not on ``$PATH`` so the
    scaffolder stays usable in minimal environments.

    :param paths: The rendered files to lint-fix and format.
    """
    py_files = [str(p) for p in paths if p.suffix == ".py"]
    if not py_files:
        return
    ruff = shutil.which("ruff")
    if ruff is None:
        return
    subprocess.run(  # noqa: S603 # nosec B603
        [ruff, "check", "--fix", "--quiet", *py_files],
        check=False,
        cwd=_REPO_ROOT,
    )
    subprocess.run(  # noqa: S603 # nosec B603
        [ruff, "format", "--quiet", *py_files],
        check=False,
        cwd=_REPO_ROOT,
    )


def _indent_width(line: str) -> int:
    """Return the number of leading spaces on ``line``.

    :param line: The settings-file line to measure.
    :return: The count of leading space characters.
    """
    return len(line) - len(line.lstrip(" "))


def _find_default_section(lines: list[str]) -> int:
    """Return the index of the top-level ``default:`` key.

    :param lines: The settings file split into lines (newline-terminated).
    :return: The index of the top-level ``default:`` line.
    :raises ValueError: When no top-level ``default:`` section exists.
    """
    for index, line in enumerate(lines):
        if _indent_width(line) == 0 and line.strip() == "default:":
            return index
    raise ValueError(
        "settings.yaml has no top-level 'default:' section; cannot register the app"
    )


def _find_apps_key(lines: list[str], default_index: int) -> int:
    """Return the index of the ``APPS:`` key inside the ``default:`` section.

    :param lines: The settings file split into lines.
    :param default_index: The index of the ``default:`` key to scan forward from.
    :return: The index of the ``APPS:`` line inside the ``default:`` section.
    :raises ValueError: When the ``default:`` section declares no ``APPS`` block.
    """
    for index in range(default_index + 1, len(lines)):
        line = lines[index]
        if _indent_width(line) == 0 and line.strip():
            break
        if line.strip() == "APPS:":
            return index
    raise ValueError(
        "settings.yaml 'default:' section has no SEP.APPS block; cannot register "
        "the app"
    )


def _default_apps_span(lines: list[str]) -> tuple[int, int]:
    """Return the ``[start, end)`` line span of the default ``SEP.APPS`` list body.

    ``start`` is the first entry line after ``APPS:``; ``end`` is one past the
    last list line (the next key at the ``APPS:`` indent or shallower ends it),
    so an insertion at ``end`` appends after the final entry.

    :param lines: The settings file split into lines.
    :return: The ``(start, end)`` index span of the list body.
    """
    apps_index = _find_apps_key(lines, _find_default_section(lines))
    apps_indent = _indent_width(lines[apps_index])
    start = apps_index + 1
    end = start
    for index in range(start, len(lines)):
        line = lines[index]
        if not line.strip():
            continue
        if _indent_width(line) <= apps_indent:
            break
        end = index + 1
    return start, end


def insert_app_entry(settings_text: str, name: str) -> tuple[str, bool]:
    """Insert a disabled ``MODULE_NAME`` entry under the default ``SEP.APPS`` block.

    A pure text transform — PyYAML cannot round-trip the file's comments, so the
    list body is edited line by line. Inserting a name that already has an entry is
    a no-op, which is what makes the registration idempotent.

    :param settings_text: The full ``settings.yaml`` contents.
    :param name: The module name to register disabled.
    :return: The (possibly unchanged) text and whether it was modified.
    :raises ValueError: When the default ``SEP.APPS`` block is absent.
    """
    lines = settings_text.splitlines(keepends=True)
    start, end = _default_apps_span(lines)
    existing = re.compile(rf"\s*-?\s*MODULE_NAME:\s*{re.escape(name)}\s*$")
    if any(existing.match(line) for line in lines[start:end]):
        return settings_text, False
    entry = f"      - MODULE_NAME: {name}\n        ENABLED: false\n"
    return "".join(lines[:end] + [entry] + lines[end:]), True


def write_settings_entry(name: str) -> bool:
    """Register ``name`` disabled in ``settings.yaml`` idempotently.

    :param name: The module name to register.
    :return: Whether the file was modified.
    """
    new_text, changed = insert_app_entry(SETTINGS_FILE.read_text(), name)
    if changed:
        SETTINGS_FILE.write_text(new_text)
    return changed


def _holds_plugin(path: Path) -> bool:
    """Return whether ``path`` holds a real plugin.

    A path holds a plugin when it is a file, a broken symlink (one that does not
    resolve yet still occupies the path), or a directory containing at least one
    entry other than ``__pycache__/``.  A truly absent path, an empty directory,
    or a directory whose only child is ``__pycache__/`` is not a plugin.

    :param path: The filesystem path to check.
    :return: ``True`` when ``path`` holds a real plugin.
    """
    if not path.exists():
        return path.is_symlink()
    if not path.is_dir():
        return True
    return any(child.name != "__pycache__" for child in path.iterdir())


def scaffold_app(name: str, flavor: Flavor) -> ScaffoldResult:
    """Validate, refuse to clobber, render, and register a new app disabled.

    The clobber guard fires before any write, so a rerun against an existing
    plugin writes nothing — no templates and no ``settings.yaml`` edit.

    :param name: The new app's module name.
    :param flavor: The flavor to render.
    :return: The scaffold outcome for the caller's summary.
    :raises ValueError: When the name is invalid.
    :raises FileExistsError: When the app or test package directory holds a real plugin.
    """
    validate_name(name)
    app_dir = PLUGINS_DIR / name
    tests_dir = TESTS_DIR / name
    for existing in (app_dir, tests_dir):
        if _holds_plugin(existing):
            raise FileExistsError(
                f"{existing} already exists; refusing to overwrite an existing plugin"
            )
    written = render_app(name, flavor, _build_context(name))
    settings_changed = write_settings_entry(name)
    return ScaffoldResult(
        name=name,
        flavor=flavor,
        app_dir=app_dir,
        tests_dir=tests_dir,
        written=written,
        settings_changed=settings_changed,
    )


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI argument parser.

    :return: The parser exposing ``--name`` and ``--type``.
    """
    parser = argparse.ArgumentParser(
        prog="python -m app.sep.apps.framework.scaffold",
        description="Scaffold a conformant SEP app skeleton.",
    )
    parser.add_argument(
        "--name", required=True, help="the app's module name (lowercase identifier)"
    )
    parser.add_argument(
        "--type",
        choices=list(Flavor),
        default=Flavor.TASK,
        type=Flavor,
        help="the app flavor to generate (default: task)",
    )
    return parser


def _print_summary(result: ScaffoldResult) -> None:
    """Summarize where the app was written and how to enable it.

    :param result: The scaffold outcome to summarise.
    """
    if result.settings_changed:
        registration = f"Registered {result.name!r} DISABLED in settings.yaml."
    else:
        registration = (
            f"{result.name!r} was already registered in settings.yaml; left unchanged."
        )
    sys.stdout.write(
        f"Scaffolded {result.flavor!r} app {result.name!r}:\n"
        f"  app:   {result.app_dir}\n"
        f"  tests: {result.tests_dir}\n"
        f"\n{registration} Enable it from the Admin App Manager (Settings -> Apps) "
        "once you have filled in the skeleton.\n"
    )


def main(argv: list[str] | None = None) -> int:
    """Run the scaffolder CLI.

    :param argv: The argument vector, or ``None`` to read ``sys.argv``.
    :return: The process exit code (``0`` on success, ``1`` on a clobber or a
        render/registration failure).
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_name(args.name)
    except ValueError as error:
        parser.error(str(error))
    try:
        result = scaffold_app(args.name, args.type)
    except (FileExistsError, ValueError) as error:
        sys.stderr.write(f"error: {error}\n")
        return 1
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
