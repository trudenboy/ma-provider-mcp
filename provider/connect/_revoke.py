"""Best-effort token revocation helper for the Connect Wizard.

Lives in its own module so both :mod:`provider.connect.handlers` and
:mod:`provider.connect.actions` can import it without coupling them to each
other.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from music_assistant.mass import MusicAssistant

LOGGER = logging.getLogger(__name__)


async def revoke_token_by_id(mass: MusicAssistant, token_id: str) -> None:
    """Delete a token row and drop any WS bound to it. Best-effort, never raises.

    :param mass: MusicAssistant instance.
    :param token_id: ``jti`` of the token to revoke.
    """
    try:
        await mass.webserver.auth.database.delete("auth_tokens", {"token_id": token_id})
    except Exception:
        LOGGER.exception("Connect Wizard: token revoke failed (token_id=%s)", token_id)
        return
    try:
        mass.webserver.disconnect_websockets_for_token(token_id)
    except Exception:
        LOGGER.exception(
            "Connect Wizard: WS disconnect after revoke failed (token_id=%s)", token_id
        )
