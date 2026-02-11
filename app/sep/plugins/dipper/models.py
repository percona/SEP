"""Models for the Dipper plugin."""

from pathlib import Path
from typing import ClassVar

from app.sep.plugins.dipper.constants import DIPPER_PAYLOADS_DIR
from app.sep.snippets.models.snippet import BaseSnippet


class DipperScript(BaseSnippet):
    """Represent a Dipper payload script stored on the SEP server filesystem."""

    BASE_DIR: ClassVar[Path] = DIPPER_PAYLOADS_DIR
