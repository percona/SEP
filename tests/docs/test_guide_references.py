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

"""Reference-integrity test for the app developer guide.

The app developer guide sources every code
example from a real file, tagging each with an HTML-comment marker naming the
file and containing symbol -- ``<!-- src: <path> [:: <symbol>] -->`` -- or, for
the two examples no app exercises, ``<!-- constructed -->``. Prose has no test to
keep it honest, so this parser enforces two contracts against the working tree:

* **Every example is cited.** Every fenced ``python`` block is immediately
  preceded (ignoring blank lines) by a ``src:`` or ``constructed`` marker.
* **Every citation resolves.** Each ``src:`` path exists, and each cited symbol
  is still defined in that file (via ``ast``) -- so a framework rename, move, or
  deletion fails CI instead of silently rotting the example.

Verbatim snippet-text matching is deliberately *not* enforced: byte/line-range
comparison is brittle under the framework's churn, and the drift that matters
(rename / move / delete) is exactly what symbol existence catches.
"""

import ast
import pathlib
import re

import pytest

_REPO_ROOT = pathlib.Path(__file__).parents[2]
_GUIDE_PATH = _REPO_ROOT / "docs/development/app-developer-guide.md"

_SRC_MARKER_RE = re.compile(
    r"^<!--\s*src:\s*(?P<path>\S+?)"
    r"(?:\s*::\s*(?P<symbol>[A-Za-z_][A-Za-z0-9_]*))?\s*-->$"
)
_CONSTRUCTED_RE = re.compile(r"^<!--\s*constructed\s*-->$")
_SRC_PREFIX_RE = re.compile(r"^<!--\s*src:")
_FENCE_RE = re.compile(r"^```(?P<lang>[A-Za-z0-9_+-]*)\s*$")


class _SrcMarker:
    """Hold a well-formed ``src:`` citation and the guide line it sits on."""

    def __init__(self, line: int, path: str, symbol: str | None) -> None:
        self.line = line
        self.path = path
        self.symbol = symbol

    def __repr__(self) -> str:
        target = f"{self.path} :: {self.symbol}" if self.symbol else self.path
        return f"{target} (guide line {self.line})"


class _ParsedGuide:
    """Hold the markers, constructed tags, malformed comments, and uncited blocks.

    :ivar src_markers: Every well-formed ``src:`` citation.
    :ivar malformed: ``(line, text)`` for each comment that opens ``<!-- src:``
        but does not match the marker grammar.
    :ivar uncited_python_blocks: Guide lines of ``python`` fences with no
        immediately preceding ``src:``/``constructed`` marker.
    """

    def __init__(self) -> None:
        self.src_markers: list[_SrcMarker] = []
        self.malformed: list[tuple[int, str]] = []
        self.uncited_python_blocks: list[int] = []


def _parse_guide() -> _ParsedGuide:
    """Parse the guide into markers, code fences, and comments.

    Walks the guide line by line, tracking whether the cursor is inside a fenced
    code block so that fence content is never mistaken for prose. For each
    opening ``python`` fence it inspects the nearest preceding non-blank line
    (blank lines ignored) and records the block as uncited unless that line is a
    ``src:`` or ``constructed`` marker.

    A missing guide file yields an empty result rather than raising, so a wrong
    or moved guide path surfaces as a clean ``test_guide_exists`` assertion
    failure instead of an import-time error during pytest collection.

    :return: The parsed guide.
    """
    result = _ParsedGuide()
    if not _GUIDE_PATH.is_file():
        return result
    in_block = False
    last_kind = "other"
    for lineno, raw in enumerate(_GUIDE_PATH.read_text().split("\n"), start=1):
        stripped = raw.strip()
        fence = _FENCE_RE.match(stripped)
        if fence:
            if not in_block:
                if fence.group("lang") == "python" and last_kind not in (
                    "src",
                    "constructed",
                ):
                    result.uncited_python_blocks.append(lineno)
                in_block = True
            else:
                in_block = False
            last_kind = "fence"
            continue
        if in_block or not stripped:
            continue
        if _CONSTRUCTED_RE.match(stripped):
            last_kind = "constructed"
        elif marker := _SRC_MARKER_RE.match(stripped):
            result.src_markers.append(
                _SrcMarker(lineno, marker.group("path"), marker.group("symbol"))
            )
            last_kind = "src"
        elif _SRC_PREFIX_RE.match(stripped):
            result.malformed.append((lineno, stripped))
            last_kind = "malformed"
        else:
            last_kind = "other"
    return result


def _module_level_names(tree: ast.Module) -> set[str]:
    """Collect names bound at module level, including methods one nesting level down.

    :param tree: The parsed module.
    :return: Every module-level class, function, and assignment-target name, plus
        the method names defined directly inside a module-level class.
    """
    names = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            targets = []
        names.update(t.id for t in targets if isinstance(t, ast.Name))
        if isinstance(node, ast.ClassDef):
            names.update(
                member.name
                for member in node.body
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
            )
    return names


def _module_defines(source: str, symbol: str) -> bool:
    """Return whether ``symbol`` is defined at module level in ``source``.

    A match is any module-level class, function, or assignment target named
    ``symbol``, or a method defined one nesting level below a module-level class
    (so a marker may cite ``Class`` or a bare module-level ``name`` alike).

    :param source: The Python source to parse.
    :param symbol: The name the citation claims is defined.
    :return: ``True`` when the name is bound at one of those scopes.
    """
    return symbol in _module_level_names(ast.parse(source))


_GUIDE = _parse_guide()


def test_guide_exists() -> None:
    """Assert the guide file the whole suite reads is present."""
    assert _GUIDE_PATH.is_file(), f"guide not found at {_GUIDE_PATH}"


def test_at_least_one_src_marker() -> None:
    """Assert the guide still carries source markers.

    A guide that has silently lost every ``src:`` marker would pass the
    per-block and per-citation checks vacuously, so guard the whole safety net.
    """
    assert _GUIDE.src_markers, (
        "no `<!-- src: ... -->` markers found in the guide; the reference safety "
        "net has vanished"
    )


def test_no_malformed_src_markers() -> None:
    """Assert every ``src:``-prefixed comment matches the marker grammar.

    A near-miss marker (missing path, stray text, no closing ``-->``) must fail
    loudly rather than be silently treated as "not a citation".
    """
    assert not _GUIDE.malformed, "malformed `src:` markers:\n" + "\n".join(
        f"  guide line {line}: {text}" for line, text in _GUIDE.malformed
    )


def test_every_python_block_is_cited() -> None:
    """Assert every ``python`` code block carries a source or constructed marker."""
    assert not _GUIDE.uncited_python_blocks, (
        "python code blocks with no preceding `<!-- src: ... -->` or "
        "`<!-- constructed -->` marker at guide line(s): "
        + ", ".join(str(line) for line in _GUIDE.uncited_python_blocks)
    )


@pytest.mark.parametrize("marker", _GUIDE.src_markers, ids=repr)
def test_citation_resolves(marker: _SrcMarker) -> None:
    """Assert a cited path exists and, if named, its symbol is still defined."""
    target = _REPO_ROOT / marker.path
    assert target.is_file(), f"cited path does not exist: {marker}"
    if marker.symbol is not None:
        assert _module_defines(target.read_text(), marker.symbol), (
            f"cited symbol not defined in file: {marker}"
        )
