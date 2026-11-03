"""The dashboard's login session: one cookie, read by the JSON API and the dashboard alike.

Starlette's SessionMiddleware (added by api.create_app) signs and writes the cookie, and
exposes it as ``request.session`` (``scope["session"]``). Everything that reads or changes
the session goes through the helpers here, so the JSON API (api.py), the dashboard pages and
the login form agree on what "logged in" means:

- ``log_in(session)`` after the API key was checked (the login form, or a ``?key=`` on a
  dashboard page): the session is authenticated from then on.
- ``is_logged_in(session)`` before serving a request that has no API key.
- ``csrf_token(session)`` for a page that calls the JSON API with the session cookie: the page
  sends it back as ``X-CSRF-Token`` on POST, PUT and DELETE, which ``csrf_ok`` checks.

TODO(4d): the dashboard is still Flask, mounted under FastAPI (web.py). Its pages reach the
same session through ``ScopeSessionInterface``, which reads and writes ``scope["session"]``
instead of a Flask cookie. The FastAPI dashboard calls these helpers on ``request.session``.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import MutableMapping
from typing import Any

# A new name: a 0.10.x Flask session cookie is simply ignored (one logout on upgrade)
SESSION_COOKIE = "qbt_rules_session"
# Flask's PERMANENT_SESSION_LIFETIME, which 0.10.x logins used
SESSION_MAX_AGE = 31 * 24 * 3600

_AUTHENTICATED = "authenticated"
_CSRF = "csrf_token"


def session_secret(api_key: str) -> str:
    """The key that signs the session cookie.

    Derived from the API key, so a restart keeps everyone logged in and changing the key logs
    everyone out. Hashed, so the API key never doubles as the signing key. With no API key
    nobody can log in, so a random secret signs nothing useful.
    """
    if not api_key:
        return secrets.token_hex(32)
    return hashlib.sha256(f"qbt-rules-dashboard-session:{api_key}".encode()).hexdigest()


def log_in(session: MutableMapping[str, Any]) -> None:
    """Mark the session authenticated: call only after the API key matched."""
    session[_AUTHENTICATED] = True


def is_logged_in(session: MutableMapping[str, Any]) -> bool:
    return session.get(_AUTHENTICATED) is True


def csrf_token(session: MutableMapping[str, Any]) -> str:
    """This session's CSRF token, created on first use."""
    token = session.get(_CSRF)
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session[_CSRF] = token
    return token


def csrf_ok(session: MutableMapping[str, Any], sent: str | None) -> bool:
    """Whether ``sent`` (the X-CSRF-Token header) is this session's token."""
    expected = session.get(_CSRF)
    return bool(
        sent and isinstance(expected, str) and expected and secrets.compare_digest(sent, expected)
    )
