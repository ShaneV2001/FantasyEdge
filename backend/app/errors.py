"""Domain errors the API maps to HTTP responses (see `app.main`).

Only these are translated to 4xx/503; any other exception (including a stray KeyError or
ValueError from a bug) surfaces as a 500 instead of masquerading as "not found".
"""

from __future__ import annotations

from typing import Literal

NotFoundKind = Literal["team", "league", "player", "user", "roster"]


class NotFound(LookupError):
    """A requested entity does not exist (HTTP 404, body carries `kind`)."""

    def __init__(self, kind: NotFoundKind, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


class InvalidInput(ValueError):
    """The request is well-formed but asks for something impossible (HTTP 422)."""


class AuthRequired(PermissionError):
    """A platform refused our login (HTTP 401, body carries `kind` so the UI can say what to do)."""

    def __init__(self, kind: Literal["espn_auth", "espn_private"], detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


class NotReady(RuntimeError):
    """Raised when the local store is missing data the request needs (run `tasks.py data`)."""
