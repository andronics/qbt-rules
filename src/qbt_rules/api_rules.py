"""The rules editor's JSON API (the dashboard's /rules/edit page calls it; scripts can too).

rules.yml is edited as text: the browser sends the whole file and the server writes exactly
those bytes, so comments, ordering and formatting all survive. Every write carries the ETag of
the version it was edited from (If-Match) and is refused with 412 if the file has changed
since; every write is validated first (rules_validation) and refused with 422 if anything
would fail or misfire; every write keeps a copy of what it replaced (config_store). The rules
engine hot-reloads rules.yml, so a save applies to the next job without a restart.

config.yaml is exposed read-only, with credentials masked: see
config_store.redacted_config_view() for why.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from qbt_rules import api_models as m
from qbt_rules import schema
from qbt_rules.api import (
    AUTH_ERRORS,
    MAX_REQUEST_BYTES,
    NO_CONFIG_MESSAGE,
    TOO_LARGE_MESSAGE,
    ApiError,
    CompatJSONResponse,
    KeyOrSession,
    error_responses,
    services,
)
from qbt_rules.config_loader import Config as RulesConfig
from qbt_rules.config_store import (
    EditableFile,
    FileConflictError,
    FileNotWritableError,
    redacted_config_view,
)
from qbt_rules.rules_validation import validate_rules_text

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rules"], dependencies=KeyOrSession)

_CONTENT_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/json": {"schema": m.RulesContent.model_json_schema()}},
    }
}


class _TooLarge(Exception):
    pass


def _rules(request: Request) -> RulesConfig:
    rules = services(request).rules
    if rules is None:
        raise ApiError(503, NO_CONFIG_MESSAGE)
    return rules


def _store(request: Request) -> EditableFile:
    """The rules.yml the editor reads and writes (one per app, for its file lock)."""
    rules = _rules(request)
    store: EditableFile | None = getattr(request.app.state, "rules_store", None)
    if store is None:
        store = EditableFile(rules.rules_file, rules.history_dir)
        request.app.state.rules_store = store
    return store


def _editor_state(request: Request, store: EditableFile) -> dict[str, Any]:
    """Whether rules.yml can be saved from the editor right now, and why not"""
    if not request.app.state.config.editor_enabled:
        return {
            "editable": False,
            "readonly_reason": "Saving is turned off (server.editor_enabled: false)",
        }
    ok, reason = store.writable()
    return {"editable": ok, "readonly_reason": reason}


def _strip_etag(value: object) -> str | None:
    """'W/"abc"' / '"abc"' / 'abc' -> 'abc'"""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.startswith("W/"):
        value = value[2:]
    return value.strip('"') or None


def _is_json(content_type: str) -> bool:
    mimetype = content_type.split(";", 1)[0].strip().lower()
    return mimetype == "application/json" or (
        mimetype.startswith("application/") and mimetype.endswith("+json")
    )


async def read_json_body(request: Request) -> dict[str, Any]:
    """The body as a JSON object, or {} when it isn't one (Flask's get_json(silent=True)).

    413 once more than MAX_REQUEST_BYTES has arrived, for a body sent without a
    Content-Length (a declared one is refused earlier, by api.BodyLimit).
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            raise _TooLarge
        chunks.append(chunk)
    if not _is_json(request.headers.get("content-type", "")):
        return {}
    try:
        data = json.loads(b"".join(chunks))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def _content(request: Request) -> tuple[str, dict[str, Any]]:
    try:
        body = await read_json_body(request)
    except _TooLarge:
        raise ApiError(413, TOO_LARGE_MESSAGE) from None
    content = body.get("content")
    if not isinstance(content, str):
        raise ApiError(400, "Body must be JSON with a 'content' string")
    return content, body


@router.get(
    "/api/rules/source",
    summary="rules.yml as text, with its ETag",
    response_model=m.RulesSource,
    responses={**error_responses(503), **AUTH_ERRORS},
)
def rules_source(request: Request) -> CompatJSONResponse:
    """The ETag (also in the `ETag` header) is what a save sends back as If-Match."""
    store = _store(request)
    snapshot = store.read()
    return CompatJSONResponse(
        {**snapshot.to_dict(), "path": str(store.path), **_editor_state(request, store)},
        headers={"ETag": f'"{snapshot.etag}"', "Cache-Control": "no-store"},
    )


@router.post(
    "/api/rules/validate",
    summary="Validate a candidate rules.yml without saving it",
    response_model=m.Validation,
    openapi_extra=_CONTENT_BODY,
    responses={**error_responses(400, 403, 413), **AUTH_ERRORS},
)
async def rules_validate(request: Request) -> CompatJSONResponse:
    """Each issue has its severity, message, path and line and column."""
    content, _ = await _content(request)
    return CompatJSONResponse(await run_in_threadpool(validate_rules_text, content))


@router.put(
    "/api/rules/source",
    summary="Save rules.yml",
    response_model=m.SavedRules,
    openapi_extra=_CONTENT_BODY,
    responses={
        **error_responses(400, 403, 413, 428, 503),
        412: {"model": m.Conflict, "description": "rules.yml changed since that ETag"},
        422: {"model": m.Invalid, "description": "Validation found errors: not saved"},
        **AUTH_ERRORS,
    },
)
async def rules_save(request: Request) -> CompatJSONResponse:
    """Send the ETag the edit started from as `If-Match` (or `etag` in the body). 200 when
    saved or unchanged; the new ETag is in the body and the `ETag` header."""
    store = _store(request)
    content, body = await _content(request)
    # The validation and the file write block: off the event loop
    return await run_in_threadpool(_save, request, store, content, body)


def _save(
    request: Request, store: EditableFile, content: str, body: dict[str, Any]
) -> CompatJSONResponse:

    state = _editor_state(request, store)
    if not state["editable"]:
        raise ApiError(403, state["readonly_reason"])

    if_match = _strip_etag(request.headers.get("If-Match")) or _strip_etag(body.get("etag"))
    if not if_match:
        raise ApiError(
            428,
            "Send the ETag from GET /api/rules/source as If-Match, so a save cannot overwrite "
            "changes made since",
        )

    validation = validate_rules_text(content)
    if not validation["valid"]:
        raise ApiError(
            422,
            f"rules.yml has {validation['counts']['error']} error(s) -- not saved",
            {"validation": validation},
        )

    try:
        snapshot, changed = store.write(content, if_match)
    except FileNotWritableError as e:
        raise ApiError(403, str(e)) from None
    except FileConflictError as e:
        raise ApiError(
            412, "rules.yml changed since you opened it", {"current": e.current.to_dict()}
        ) from None

    if changed:
        try:
            _rules(request).reload_rules(force=True)
        except Exception as e:
            logger.warning(f"Saved rules.yml but reloading it failed: {e}")

    return CompatJSONResponse(
        {
            "saved": changed,
            "etag": snapshot.etag,
            "modified_at": snapshot.modified_at,
            "size": snapshot.size,
            "validation": validation,
        },
        headers={"ETag": f'"{snapshot.etag}"'},
    )


@router.get(
    "/api/rules/history",
    summary="Previous versions of rules.yml, newest first",
    response_model=m.History,
    responses={**error_responses(503), **AUTH_ERRORS},
)
def rules_history(request: Request) -> CompatJSONResponse:
    """The versions editor saves replaced."""
    return CompatJSONResponse({"versions": _store(request).history()})


@router.get(
    "/api/rules/history/{version_id}",
    summary="One previous version's content",
    response_model=m.HistoryVersion,
    responses={**error_responses(404, 503), **AUTH_ERRORS},
)
def rules_history_version(request: Request, version_id: str) -> CompatJSONResponse:
    """Restore it by saving it."""
    content = _store(request).read_version(version_id)
    if content is None:
        raise ApiError(404, f"No saved version {version_id}")
    return CompatJSONResponse({"id": version_id, "content": content})


@router.get(
    "/api/rules/catalog",
    summary="The fields, operators and actions rules can use",
    response_model=m.Catalog,
    responses=AUTH_ERRORS,
)
def rules_catalog(request: Request) -> CompatJSONResponse:
    """For the editor's autocomplete, plus the contexts the schedule fires."""
    catalog = schema.catalog()
    rules = services(request).rules
    schedule = rules.schedule if rules is not None else []
    catalog["schedule_contexts"] = sorted({str(entry.get("context")) for entry in schedule})
    return CompatJSONResponse(catalog)


@router.get(
    "/api/config/source",
    summary="config.yaml as text, read-only, with credentials masked",
    response_model=m.ConfigSource,
    responses={**error_responses(503), **AUTH_ERRORS},
)
def config_source(request: Request) -> CompatJSONResponse:
    config_file = _rules(request).config_file
    try:
        view = redacted_config_view(config_file.read_text("utf-8"))
    except FileNotFoundError:
        view = {
            "content": "",
            "redacted": [],
            "issues": [
                {
                    "severity": "info",
                    "message": f"{config_file} does not exist: every setting comes from its "
                    "environment variable or its default",
                    "path": "",
                    "line": None,
                    "column": None,
                    "end_line": None,
                    "end_column": None,
                }
            ],
        }
    return CompatJSONResponse(
        {**view, "path": str(config_file)}, headers={"Cache-Control": "no-store"}
    )
