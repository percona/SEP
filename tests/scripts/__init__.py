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

import importlib.util
import sys
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
    """Return ``scripts/<name>.py`` loaded as a module named ``name``.

    The scripts are CLIs outside any package, so a test importing one has to load
    it by path. Loading is memoised through ``sys.modules``: two test modules that
    need the same script share one instance rather than the second re-registering
    the key the first claimed.

    :param name: The script's module name, without the ``.py`` suffix.
    :return: The loaded module.
    :raises RuntimeError: When the script cannot be loaded from ``scripts/``.
    """
    cached = sys.modules.get(name)
    if isinstance(cached, ModuleType):
        return cached

    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
