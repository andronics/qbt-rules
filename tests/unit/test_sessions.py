"""The login session helpers shared by the JSON API and the dashboard."""

from typing import Any

from qbt_rules import sessions


def test_the_secret_follows_the_api_key() -> None:
    assert sessions.session_secret("k") == sessions.session_secret("k")
    assert sessions.session_secret("k") != sessions.session_secret("other")
    assert "k" not in sessions.session_secret("k")


def test_no_api_key_gets_a_random_secret() -> None:
    assert sessions.session_secret("") != sessions.session_secret("")


def test_log_in() -> None:
    session: dict[str, Any] = {}
    assert not sessions.is_logged_in(session)
    sessions.log_in(session)
    assert sessions.is_logged_in(session)
    assert not sessions.is_logged_in({"authenticated": "yes"})


def test_csrf_token_is_created_once() -> None:
    session: dict[str, Any] = {}
    token = sessions.csrf_token(session)
    assert len(token) >= 32
    assert sessions.csrf_token(session) == token
    assert sessions.csrf_ok(session, token)


def test_csrf_check_refuses_anything_else() -> None:
    session: dict[str, Any] = {}
    token = sessions.csrf_token(session)
    assert not sessions.csrf_ok(session, None)
    assert not sessions.csrf_ok(session, "")
    assert not sessions.csrf_ok(session, token + "x")
    assert not sessions.csrf_ok({}, token)
    assert not sessions.csrf_ok({"csrf_token": 1}, "1")
