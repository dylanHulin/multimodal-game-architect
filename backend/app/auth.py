"""Optional BYOK auth: read a user-provided Meta API key from the
`Authorization: Bearer <key>` header.

Missing, malformed, or too-short tokens resolve to None (server env keys
stay the default). This dependency never raises 401: BYOK is opt-in, the
pipeline keeps working without a user key.
"""

import logging
from typing import Optional

from fastapi import Security  # type: ignore
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # type: ignore

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)

MIN_KEY_LENGTH = 8


def user_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> Optional[str]:
    """Return the user Bearer token, or None when absent/unusable."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    token = (credentials.credentials or "").strip()
    if len(token) < MIN_KEY_LENGTH:
        logger.debug("Ignoring too-short Bearer token (%d chars).", len(token))
        return None
    return token
