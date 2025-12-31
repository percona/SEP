"""Models for the Dipper plugin."""

import hashlib
import logging
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import aiofiles

from app.core.utils import json_serializer
from app.sep.plugins.dipper.constants import DIPPER_PAYLOADS_DIR
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.models.snippet import BaseSnippetArgs, FilePreview, Snippet

logger = logging.getLogger(__name__)


@dataclass
class DipperScript:
    """Represent a Dipper payload script stored on the SEP server filesystem."""

    filename: str
    size: int
    md5_digest: str
    meta: dict[str, Any]

    @classmethod
    async def from_filename(cls, filename: str) -> "DipperScript":
        """Load and parse a payload script by filename."""
        path = cls.get_path(filename)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        size = path.stat().st_size
        md5_digest = await cls._md5(path)
        meta = await Snippet.get_meta_by_path(path)
        return cls(filename=filename, size=size, md5_digest=md5_digest, meta=meta or {})

    @staticmethod
    def get_path(filename: str) -> Path:
        """Return the absolute filesystem path for a payload script."""
        return (DIPPER_PAYLOADS_DIR / filename).resolve()

    @property
    def path(self) -> Path:
        """Return the absolute filesystem path for this payload."""
        return self.get_path(self.filename)

    @cached_property
    def title(self) -> str:
        """Return a human-friendly title."""
        return self.meta.get("title", self.filename)

    @cached_property
    def description(self) -> str:
        """Return a human-friendly description."""
        return self.meta.get("description", "")

    @property
    def execution_interpreter(self) -> str | None:
        """Return the interpreter configured for this script."""
        return Snippet._get_execution_interpreter(self.path)  # noqa: SLF001

    async def get_preview(self) -> FilePreview:
        """Return a cached preview of the script content."""
        return await FilePreview.from_path(
            self.path,
            snippets_settings.PREVIEW_MAX_CHARS,
            snippets_settings.PREVIEW_MAX_LINES,
            file_hash=self.md5_digest,
        )

    def get_execution_model(self) -> type[BaseSnippetArgs]:
        """Return a Pydantic model to validate execution parameters."""
        parameters = self.meta.get("parameters", [])
        return Snippet._get_execution_model(  # noqa: SLF001
            json_serializer(parameters, sort_keys=True),
        )

    def to_form(self, executor_hosts: list[str], form_action: str = "") -> str:
        """Return an HTML form for executing the script."""
        parameters = self.meta.get("parameters", [])
        return Snippet._to_form(  # noqa: SLF001
            json_serializer(parameters, sort_keys=True),
            frozenset(executor_hosts),
            form_action=form_action,
        )

    @staticmethod
    async def _md5(path: Path) -> str:
        md5 = hashlib.md5(usedforsecurity=False)
        async with aiofiles.open(path, "rb") as f:
            while True:
                chunk = await f.read(1024 * 1024)
                if not chunk:
                    break
                md5.update(chunk)
        return md5.hexdigest()
