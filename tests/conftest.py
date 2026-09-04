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

"""Provide the settings every test module needs before it imports application code.

``ENCRYPTION_KEY`` is required at settings construction and has no default, so
it has to exist before the first module that touches ``settings`` is imported.
This runs at conftest import, which pytest performs ahead of collecting the
modules beneath it, and it is minted rather than pinned in
``[tool.pytest.ini_options] env`` so no working key is committed. Test data is
per-run and never leaves the process, so a key that differs between runs and
between parallel workers costs nothing.
"""

import os

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
