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

"""Load the ``scripts/`` CLIs under test as importable modules."""

import importlib
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def write_file(tmp_path: Path, name: str, text: str) -> Path:
    """Write ``text`` to ``tmp_path/name`` and return the path.

    :param tmp_path: pytest's per-test temporary directory.
    :param name: The filename to create under ``tmp_path``.
    :param text: UTF-8 contents to write.
    :return: The newly-written path.
    """
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def load_script(name: str) -> ModuleType:
    """Return ``scripts/<name>.py`` as the one module object for that script.

    Delegates to :func:`importlib.import_module` under the package-qualified
    name. The previous by-path load registered the bare name
    (``sys.modules["classify_ty_diagnostics"]``), which Python treats as a
    module unrelated to ``scripts.classify_ty_diagnostics``, so a test file
    reaching one script both ways held two copies of every class in it,
    exception classes included, and a ``pytest.raises`` reported ``DID NOT
    RAISE`` against an exception the traceback showed being raised. The old
    memo could not prevent that: it guarded the bare-name key, which is not the
    key a package import claims.

    ``scripts`` is a package whose ``__init__`` is a licence header, so the
    delegation adds no import side effects.

    :param name: The script's module name, without the ``.py`` suffix.
    :return: The loaded module.
    :raises RuntimeError: When the script cannot be imported from ``scripts/``.
    """
    try:
        return importlib.import_module(f"scripts.{name}")
    except ImportError as exc:
        raise RuntimeError(f"cannot load {SCRIPTS_DIR / f'{name}.py'}") from exc
