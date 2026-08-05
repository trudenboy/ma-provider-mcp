"""Invocation-local proof that MCP elicitation was accepted."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _ConfirmationGrant:
    """Opaque capability grant scoped to one dispatcher target invocation."""

    marker: object
    command: str
    capabilities: frozenset[str]


_MARKER = object()
_CURRENT_GRANT: ContextVar[_ConfirmationGrant | None] = ContextVar(
    "mcp_confirmation_grant",
    default=None,
)


@contextmanager
def _dispatcher_confirmation(command: str, capabilities: frozenset[str]) -> Iterator[None]:
    """Scope accepted confirmation capabilities to one target invocation."""
    token = _CURRENT_GRANT.set(_ConfirmationGrant(_MARKER, command, capabilities))
    try:
        yield
    finally:
        _CURRENT_GRANT.reset(token)


def capability_was_confirmed(command: str, capability: str) -> bool:
    """Return whether the active dispatcher invocation confirmed a capability."""
    grant = _CURRENT_GRANT.get()
    return bool(
        grant is not None
        and grant.marker is _MARKER
        and grant.command == command
        and capability in grant.capabilities
    )
