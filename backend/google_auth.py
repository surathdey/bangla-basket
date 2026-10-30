"""Direct Google ID-token verification (self-hosted auth path).

This is the additive contingency for the legacy Emergent Auth relay used
by ``POST /api/auth/session``: when the app sends an ``id_token`` instead
of a relay ``session_token``, the token is verified locally against
``GOOGLE_CLIENT_ID`` -- no relay, no extra network hop beyond Google's
key fetch (cached by the google-auth library).

Setup the user must complete (see README "Gated items"):
  1. Create a Google Cloud OAuth client (Web or iOS/Android as the app
     needs) and set ``GOOGLE_CLIENT_ID`` to its client ID.
  2. The app sends the Google ID token it already obtains from the
     Google sign-in SDK as ``{"id_token": ...}`` to /api/auth/session.
  3. The rest of the session flow (user upsert, 7-day session row,
     first-login handling) is identical to the relay path.

Raises ``ValueError`` on any verification failure; the caller converts
that to HTTP 401.
"""
import os

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")


def verify_google_id_token(token: str) -> dict:
    """Verify a Google ID token; return {"email","name","picture"}."""
    if not GOOGLE_CLIENT_ID:
        raise ValueError("GOOGLE_CLIENT_ID is not set on the backend")
    try:
        info = google_id_token.verify_oauth2_token(
            token, google_requests.Request(), GOOGLE_CLIENT_ID)
    except Exception as e:
        raise ValueError(f"invalid Google ID token: {e}") from e
    email = info.get("email")
    if not email:
        raise ValueError("Google ID token has no email")
    if info.get("email_verified") is False:
        raise ValueError("Google email not verified")
    return {
        "email": email,
        "name": info.get("name") or email.split("@")[0],
        "picture": info.get("picture"),
    }
