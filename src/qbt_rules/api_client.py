"""The CLI's client for a running server's JSON API (`qbt-rules execute`, `jobs`, `stats`).

Every call raises ClientError with a message meant for the person at the terminal; the
CLI prints it and exits 1. The API key goes in the X-API-Key header, never the URL.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

TIMEOUT = 10  # seconds, per request
POLL_INTERVAL = 2  # seconds between polls while waiting for a job
MAX_WAIT = 300  # seconds before giving up on a job
FINISHED = frozenset({"completed", "failed", "cancelled"})


class ClientError(Exception):
    """A request the server refused or couldn't be sent: the message says which.

    ``status`` is the HTTP status of a refusal and ``detail`` the API's own message.
    """

    def __init__(self, message: str, status: int | None = None, detail: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


def validate_torrent_hash(torrent_hash: str) -> str:
    """The hash in lower case. qBittorrent's info hashes are 40 hex characters (SHA-1)."""
    if len(torrent_hash) != 40:
        raise ValueError(f"Invalid torrent hash length: {len(torrent_hash)} (expected 40)")
    try:
        int(torrent_hash, 16)
    except ValueError:
        raise ValueError("Invalid torrent hash format: must be hexadecimal") from None
    return torrent_hash.lower()


class Client:
    """One server (client.server_url) and the key to it (client.api_key, else server.api_key)."""

    def __init__(self, server_url: str, api_key: str) -> None:
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, str | int] | None = None,
        expect: int = 200,
        not_found: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self.server_url}{path}"
        try:
            response = requests.request(
                method,
                url,
                params=params,
                headers={"X-API-Key": self.api_key},
                timeout=TIMEOUT,
            )
        except requests.exceptions.ConnectionError:
            raise ClientError(
                f"Cannot connect to the server at {self.server_url}. Is it running? Start it "
                "with `qbt-rules serve`, or point client.server_url "
                "(QBT_RULES_CLIENT_SERVER_URL) at it"
            ) from None
        except requests.exceptions.Timeout:
            raise ClientError(f"The server at {self.server_url} timed out") from None
        except requests.exceptions.RequestException as e:
            raise ClientError(f"Request to {url} failed: {e}") from None

        if response.status_code == expect:
            body: dict[str, Any] = response.json()
            return body
        if response.status_code == 404 and not_found:
            raise ClientError(not_found)
        if response.status_code in (401, 403):
            raise ClientError(
                "Authentication failed: check client.api_key (QBT_RULES_CLIENT_API_KEY_FILE), "
                "or server.api_key, which it falls back to"
            )
        detail = _message(response)
        raise ClientError(
            f"Server error {response.status_code}: {detail}", response.status_code, detail
        )

    def execute(
        self, context: str | None, torrent_hash: str | None, dry_run: bool
    ) -> dict[str, Any]:
        """Queue a job (POST /api/execute). Returns the queued job."""
        params: dict[str, str | int] = {}
        if context:
            params["context"] = context
        if torrent_hash:
            params["hash"] = torrent_hash
        if dry_run:
            params["dry_run"] = "true"
        job = self._request("POST", "/api/execute", params, expect=202)
        if dry_run and job.get("dry_run") is not True:
            # A server older than per-job dry-run (0.10.0) ignores the parameter and would
            # run the job for real: cancel it before it starts
            raise ClientError(self._cancel_unconfirmed_dry_run(str(job["job_id"])))
        return job

    def _cancel_unconfirmed_dry_run(self, job_id: str) -> str:
        try:
            self.cancel(job_id)
            outcome = f"Cancelled job {job_id} before it ran."
        except ClientError:
            outcome = (
                f"Could not cancel job {job_id}; it may already be running. Check it with "
                f"`qbt-rules jobs status {job_id}`."
            )
        return (
            "The server didn't confirm dry-run for this job (it's older than per-job dry-run "
            f"support), so it would have run for real. {outcome} Upgrade the server, or set "
            "dry_run on the server instead (QBT_RULES_DRY_RUN=true)."
        )

    def job(self, job_id: str) -> dict[str, Any]:
        """One job (GET /api/jobs/{id})."""
        return self._request("GET", f"/api/jobs/{job_id}", not_found=f"Job not found: {job_id}")

    def jobs(self, status: str | None, context: str | None, limit: int) -> dict[str, Any]:
        """Recent jobs, newest first (GET /api/jobs)."""
        params: dict[str, str | int] = {"limit": limit}
        if status:
            params["status"] = status
        if context:
            params["context"] = context
        return self._request("GET", "/api/jobs", params)

    def cancel(self, job_id: str) -> dict[str, Any]:
        """Cancel a pending job (DELETE /api/jobs/{id})."""
        try:
            return self._request(
                "DELETE", f"/api/jobs/{job_id}", not_found=f"Job not found: {job_id}"
            )
        except ClientError as e:
            if e.status == 400:
                # "Cannot cancel job in status: completed"
                raise ClientError(e.detail, e.status, e.detail) from None
            raise

    def stats(self) -> dict[str, Any]:
        """Job counts, timings, queue and worker (GET /api/stats)."""
        return self._request("GET", "/api/stats")

    def wait(
        self,
        job_id: str,
        on_poll: Callable[[str], None] = lambda status: None,
        max_wait: float | None = None,
        interval: float = POLL_INTERVAL,
    ) -> dict[str, Any]:
        """Poll a job until it has finished (completed, failed or cancelled), and return it."""
        max_wait = MAX_WAIT if max_wait is None else max_wait
        waited = 0.0
        while True:
            job = self.job(job_id)
            if job["status"] in FINISHED:
                return job
            if waited >= max_wait:
                raise ClientError(f"Job {job_id} did not finish within {max_wait:g}s")
            on_poll(str(job["status"]))
            time.sleep(interval)
            waited += interval


def _message(response: requests.Response) -> str:
    """The API's {"error","message"} message, else the body's start."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or response.reason
    if isinstance(body, dict) and "message" in body:
        return str(body["message"])
    return response.text[:200]
