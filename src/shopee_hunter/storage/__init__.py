"""Local persistence: schema, migrations, and the one repository that owns every query."""

from __future__ import annotations

from .db import SCHEMA_VERSION, connect, migrate
from .repository import Repository

__all__ = ["SCHEMA_VERSION", "Repository", "connect", "migrate"]
