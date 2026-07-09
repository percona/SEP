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

"""Define path-related utilities."""

import logging
from os import PathLike
from pathlib import Path
from typing import TypeAlias

from app import BASE_DIR

logger = logging.getLogger(__name__)

PathInput: TypeAlias = str | PathLike[str]
_PLUGIN_APP_ALIASES = (
    ("/app/sep/plugins/", "/app/sep/apps/"),
    ("/app/sep/apps/", "/app/sep/plugins/"),
)


class PayloadReferenceError(ValueError):
    """Define exception raised when a task payload ``file://`` reference cannot be resolved."""


def resolve_relative_path(path: PathInput) -> Path:
    """Resolve relative paths with BASE_DIR.

    :param path: The relative path to resolve.
    :type path: str | bytes | PathLike
    :return: The resolved absolute path.
    :rtype: Path
    :raises ValueError: If the path cannot be resolved.
    """
    try:
        return BASE_DIR / path
    except TypeError as exc:
        raise ValueError(f"Unable to resolve path: {path}") from exc


def payload_uri(anchor_file: PathInput, name: PathInput) -> str:
    """Build a ``file://`` payload reference anchored next to *anchor_file*.

    Combine the directory of *anchor_file* with *name* and delegate to
    :func:`to_payload_reference` for ``BASE_DIR``-relative ``file://``
    construction.

    :param anchor_file: The caller's ``__file__`` token.
    :param name: Sibling file or directory name to resolve.
    :return: A ``file://`` reference relative to ``BASE_DIR``.
    """
    return to_payload_reference(Path(anchor_file).parent / name)


def to_payload_reference(path: Path) -> str:
    """Build a stored task payload reference relative to ``BASE_DIR``.

    The reference is location-independent: it stores the package-relative path
    under the ``BASE_DIR`` anchor rather than a deployment-absolute path, so a
    later relocation of the deployment root does not orphan it. Both ``path``
    and the anchor are resolved before the relative computation so a symlinked
    deployment root — where the caller's unresolved path diverges from the
    already-resolved ``BASE_DIR`` — still anchors instead of raising.

    :param path: An absolute path under ``BASE_DIR`` to the payload file.
    :return: A ``file://`` reference relative to ``BASE_DIR``.
    :raises ValueError: If ``path`` is not located under ``BASE_DIR``.
    """
    return f"file://{Path(path).resolve().relative_to(BASE_DIR.resolve())}"


def resolve_payload_reference(reference: str) -> Path:
    """Resolve a ``file://`` task payload reference to an existing file.

    Accept both the current ``BASE_DIR``-relative form and legacy absolute
    references. When a candidate path sits under ``app/sep/plugins`` or
    ``app/sep/apps``, also try the aliased sibling location so a
    ``plugins``/``apps`` relocation re-anchors without a per-plugin change.

    Only relative references are containment-checked against ``BASE_DIR``.
    Absolute references are system-generated at task-creation time and are
    trusted as-is, so the escape guard is intentionally asymmetric.

    :param reference: The stored ``file://`` payload reference.
    :return: The first candidate path that resolves to an existing file.
    :raises PayloadReferenceError: If ``reference`` does not carry the
        ``file://`` scheme, a relative reference escapes ``BASE_DIR``, or no
        candidate resolves to a file.
    """
    stripped = reference.strip()
    if not stripped.startswith("file://"):
        raise PayloadReferenceError(
            f"Task payload reference is not a file:// reference: {reference}"
        )
    raw = stripped.removeprefix("file://").strip()
    candidate = Path(raw)
    if candidate.is_absolute():
        base_candidate = candidate
    else:
        base_candidate = resolve_relative_path(raw)
        if not base_candidate.resolve().is_relative_to(BASE_DIR.resolve()):
            logger.error("Task payload reference escapes BASE_DIR: %s", reference)
            raise PayloadReferenceError(
                f"Task payload reference escapes BASE_DIR: {reference}"
            )
    candidates = [base_candidate]
    text = str(base_candidate)
    for old, new in _PLUGIN_APP_ALIASES:
        if old in text:
            candidates.append(Path(text.replace(old, new)))
    for path in candidates:
        if path.is_file():
            return path
    logger.error("Unresolvable task payload reference: %s", reference)
    raise PayloadReferenceError(f"Unresolvable task payload reference: {reference}")
