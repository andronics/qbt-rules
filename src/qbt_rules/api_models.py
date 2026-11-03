"""The JSON API's response bodies, for the OpenAPI schema (docs/openapi.json).

The routes build their bodies as dicts and send them with CompatJSONResponse, byte for byte
what the Flask API sent; these models describe those bodies. A field that is sometimes
absent (``config_problems``) is optional here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

JobStatusName = Literal["pending", "processing", "completed", "failed", "cancelled"]


class ErrorBody(BaseModel):
    """Every error: a short status name and a sentence saying what went wrong."""

    error: str = Field(examples=["Unauthorized"])
    message: str = Field(examples=["Invalid or missing API key"])


class Job(BaseModel):
    job_id: str
    context: str | None
    hash: str | None
    dry_run: bool
    status: JobStatusName
    created_at: datetime | None = Field(description="ISO 8601, UTC")
    started_at: datetime | None
    completed_at: datetime | None
    result: dict[str, Any] | None = Field(
        description="A completed job's counters: torrents_processed, rules_matched, "
        "actions_executed, ... and by_rule"
    )
    error: str | None = Field(description="A failed job's traceback")


class JobList(BaseModel):
    total: int = Field(description="Jobs matching the filters, before limit and offset")
    limit: int = Field(description="The limit applied (at most 100)")
    offset: int
    jobs: list[Job]


class CancelledJob(BaseModel):
    job_id: str
    status: Literal["cancelled"]
    message: str


class QueueHealth(BaseModel):
    backend: str
    pending_jobs: int
    processing_jobs: int


class WorkerStatus(BaseModel):
    status: Literal["running", "stopped"]
    last_job_completed: datetime | None


class Health(BaseModel):
    status: Literal["healthy"]
    version: str
    queue: QueueHealth
    worker: WorkerStatus
    timestamp: datetime
    config_problems: list[str] | None = Field(
        None,
        description="Settings the server started without (no API key); absent when none",
    )


class Unhealthy(BaseModel):
    status: Literal["unhealthy"]
    errors: list[str]
    timestamp: datetime


class JobCounts(BaseModel):
    total: int
    pending: int
    processing: int
    completed: int
    failed: int
    cancelled: int


class Performance(BaseModel):
    average_execution_time: str | None = Field(examples=["1.24s"])


class QueueDepth(BaseModel):
    backend: str
    depth: int


class Stats(BaseModel):
    jobs: JobCounts
    performance: Performance
    queue: QueueDepth
    worker: WorkerStatus
    timestamp: datetime


class Version(BaseModel):
    version: str
    api_version: str
    python_version: str


class Probe(BaseModel):
    status: str


class Issue(BaseModel):
    severity: Literal["error", "warning", "info"]
    message: str
    path: str
    line: int | None
    column: int | None
    end_line: int | None
    end_column: int | None


class Validation(BaseModel):
    valid: bool
    issues: list[Issue]
    counts: dict[str, int] = Field(description="Issues per severity")
    summary: dict[str, Any] = Field(description="The rules, refs and contexts found")


class RulesFile(BaseModel):
    content: str
    etag: str
    modified_at: datetime | None = Field(description="None when rules.yml doesn't exist yet")
    size: int


class RulesSource(RulesFile):
    path: str
    editable: bool
    readonly_reason: str | None


class SavedRules(BaseModel):
    saved: bool = Field(description="False when the content was unchanged")
    etag: str
    modified_at: datetime | None
    size: int
    validation: Validation


class Conflict(ErrorBody):
    current: RulesFile


class Invalid(ErrorBody):
    validation: Validation


class HistoryEntry(BaseModel):
    id: str
    saved_at: datetime
    size: int


class History(BaseModel):
    versions: list[HistoryEntry]


class HistoryVersion(BaseModel):
    id: str
    content: str


class Catalog(BaseModel):
    """The rules vocabulary (schema.catalog()), plus the contexts the schedule fires."""

    top_level_keys: dict[str, Any]
    rule_keys: dict[str, Any]
    condition_groups: list[str]
    fields: dict[str, Any]
    operators: dict[str, Any]
    actions: dict[str, Any]
    schedule_contexts: list[str]


class ConfigSource(BaseModel):
    content: str
    redacted: list[str] = Field(description="The dotted keys whose values are masked")
    issues: list[Issue]
    path: str


class RulesContent(BaseModel):
    """The body of POST /api/rules/validate and PUT /api/rules/source."""

    content: str = Field(description="The whole rules.yml")
    etag: str | None = Field(None, description="PUT only: the ETag, if not sent as If-Match")
