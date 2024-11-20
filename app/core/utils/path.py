"""Define path-related utilities."""

from os import PathLike
from pathlib import Path

from app import BASE_DIR


def resolve_relative_path(path: PathLike | str) -> Path:
    """Resolve relative paths with BASE_DIR.

    :param path: The relative path to resolve.
    :type path: PathLike | str
    :return: The resolved absolute path.
    :rtype: Path
    :raises ValueError: If the path cannot be resolved.
    """
    try:
        return BASE_DIR / path
    except TypeError as exc:
        raise ValueError from exc
