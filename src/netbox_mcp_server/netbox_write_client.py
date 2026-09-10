"""Write path for the extended NetBox MCP server.

Real writes go straight to the NetBox REST API with the configured token's
permissions. Dry runs are delegated to the MCPWriteValidator custom script
(netbox_scripts/netbox_mcp_server_extended.py) executed with commit=false:
NetBox validates the change with its own REST serializers inside a transaction
that is always rolled back, so nothing persists and no webhooks fire.

Dry runs fail closed: if the script is missing, the RQ worker is down, or the
job cannot be confirmed, an error is raised — a dry run never falls back to
executing the real write.

NetBox deprecates custom scripts in 4.7 and plans to remove them in 5.0. Issue
#39 tracks the move of this backend to the replacement mechanism. Keep the
four guarantees above when you re-target it.
"""

import json
import pathlib
import threading
import time
import uuid
from importlib import resources
from typing import Any

import httpx

from netbox_mcp_server.netbox_client import NetBoxRestClient

DRY_RUN_SCRIPT_DEFAULT = "netbox_mcp_server_extended.MCPWriteValidator"
DRY_RUN_TIMEOUT_DEFAULT = 60.0
SCRIPT_DOCS_URL = (
    "https://github.com/thomaschristory/netbox-mcp-server-extended"
    "/blob/main/netbox_scripts/README.md"
)


SCRIPT_FILENAME = "netbox_mcp_server_extended.py"


def packaged_script_path() -> str:
    """Locate the validator script that ships with this package.

    The distribution carries a copy of the NetBox-side script, so an error
    message can tell the user which file to install on the NetBox host. An
    editable install resolves to the checkout instead, because hatchling
    materializes the packaged copy only in a built wheel.

    Returns:
        The path of the validator script, or the documentation URL when
        neither the package nor a checkout exposes a readable file.
    """
    try:
        packaged = resources.files("netbox_mcp_server") / "netbox_scripts" / SCRIPT_FILENAME
        if packaged.is_file():
            return str(packaged)
    except (ModuleNotFoundError, OSError):
        pass

    # Editable install or a plain checkout: src/netbox_mcp_server/ -> repo root.
    checkout = pathlib.Path(__file__).resolve().parents[2] / "netbox_scripts" / SCRIPT_FILENAME
    if checkout.is_file():
        return str(checkout)
    return SCRIPT_DOCS_URL


_TERMINAL_JOB_STATUSES = {"completed", "errored", "failed"}


class DryRunError(RuntimeError):
    """A dry run could not produce a trustworthy verdict."""


class DryRunUnavailableError(DryRunError):
    """Dry-run infrastructure (script, RQ worker, permissions) is unavailable."""


def _job_status(job: dict[str, Any]) -> str:
    """Extract the job status value from a NetBox Job representation."""
    status = job.get("status")
    if isinstance(status, dict):
        return str(status.get("value", "")).lower()
    return str(status or "").lower()


def _log_tail(data: dict[str, Any]) -> str:
    """Build a short diagnostic tail from a job's script log, tolerating any shape."""
    log = data.get("log")
    if not isinstance(log, list):
        return str(log)
    return "; ".join(
        str(entry.get("message", entry)) if isinstance(entry, dict) else str(entry)
        for entry in log[-5:]
    )


class NetBoxWriteClient:
    """Wraps NetBoxRestClient with real writes and script-backed dry runs.

    NetBox's script-run response only reports the script's newest job, so a
    lock serializes enqueue and job-id capture within this process, and a
    nonce echoed through the verdict catches mix-ups with runs from other
    actors.
    """

    def __init__(
        self,
        client: NetBoxRestClient,
        dry_run_script: str = DRY_RUN_SCRIPT_DEFAULT,
        dry_run_timeout: float = DRY_RUN_TIMEOUT_DEFAULT,
        poll_interval: float = 1.0,
    ) -> None:
        self._client = client
        self._dry_run_script = dry_run_script
        self._dry_run_timeout = dry_run_timeout
        self._poll_interval = poll_interval
        self._dry_run_lock = threading.Lock()

    def create(
        self,
        endpoint: str,
        object_type: str,
        data: dict[str, Any],
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Create an object, or validate the creation when ``dry_run`` is true.

        Args:
            endpoint: NetBox API endpoint (e.g. 'dcim/sites').
            object_type: Dotted object type (e.g. 'dcim.site'), used by the
                dry-run script to resolve the model.
            data: NetBox API POST body for the object.
            dry_run: When true (default), validate via the MCPWriteValidator
                script without persisting; when false, perform the real write.

        Returns:
            The created object dict, or a dry-run verdict dict
            ({'valid', 'operation', 'object_type', ...}).

        Raises:
            DryRunUnavailableError: Dry-run infrastructure is missing or down.
            DryRunError: The dry run finished without a trustworthy verdict.
            httpx.HTTPStatusError: The real write was rejected by NetBox.
        """
        if dry_run:
            return self._dry_run("create", object_type, payload=data)
        url = self._client._build_url(endpoint)
        response = self._client.session.post(url, json=data)
        response.raise_for_status()
        return response.json()

    def update(
        self,
        endpoint: str,
        object_type: str,
        object_id: int,
        data: dict[str, Any],
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Partially update an object, or validate the update when ``dry_run`` is true.

        Args:
            endpoint: NetBox API endpoint (e.g. 'dcim/sites').
            object_type: Dotted object type (e.g. 'dcim.site').
            object_id: ID of the object to update.
            data: Fields to change (NetBox API PATCH body).
            dry_run: When true (default), validate without persisting.

        Returns:
            The updated object dict, or a dry-run verdict dict.

        Raises:
            DryRunUnavailableError: Dry-run infrastructure is missing or down.
            DryRunError: The dry run finished without a trustworthy verdict.
            httpx.HTTPStatusError: The real write was rejected by NetBox.
        """
        if dry_run:
            return self._dry_run("update", object_type, payload=data, object_id=object_id)
        url = self._client._build_url(endpoint, object_id)
        response = self._client.session.patch(url, json=data)
        response.raise_for_status()
        return response.json()

    def delete(
        self,
        endpoint: str,
        object_type: str,
        object_id: int,
        dry_run: bool = True,
    ) -> dict[str, Any] | bool:
        """Delete an object, or validate the deletion when ``dry_run`` is true.

        Args:
            endpoint: NetBox API endpoint (e.g. 'dcim/sites').
            object_type: Dotted object type (e.g. 'dcim.site').
            object_id: ID of the object to delete.
            dry_run: When true (default), validate without deleting.

        Returns:
            A dry-run verdict dict when ``dry_run`` is true; otherwise True if
            NetBox confirmed the deletion (HTTP 204).

        Raises:
            DryRunUnavailableError: Dry-run infrastructure is missing or down.
            DryRunError: The dry run finished without a trustworthy verdict.
            httpx.HTTPStatusError: The real delete was rejected by NetBox.
        """
        if dry_run:
            return self._dry_run("delete", object_type, object_id=object_id)
        url = self._client._build_url(endpoint, object_id)
        response = self._client.session.delete(url)
        response.raise_for_status()
        return response.status_code == 204

    def _dry_run(
        self,
        operation: str,
        object_type: str,
        payload: dict[str, Any] | None = None,
        object_id: int | None = None,
    ) -> dict[str, Any]:
        """Execute the validation script with commit=false and await its verdict."""
        nonce = uuid.uuid4().hex
        script_data: dict[str, Any] = {
            "operation": operation,
            "object_type": object_type,
            "nonce": nonce,
        }
        if object_id is not None:
            script_data["object_id"] = object_id
        if payload is not None:
            script_data["payload"] = json.dumps(payload)

        url = f"{self._client.api_url}/extras/scripts/{self._dry_run_script}/"
        with self._dry_run_lock:
            try:
                response = self._client.session.post(
                    url, json={"data": script_data, "commit": False}
                )
            except httpx.HTTPError as e:
                raise DryRunUnavailableError(
                    f"Could not reach NetBox to start the dry run: {e}"
                ) from e
            job_id = self._extract_job_id(response)

        job = self._wait_for_job(job_id)
        return self._interpret_job(job, operation, object_type, nonce, object_id)

    def _extract_job_id(self, response: httpx.Response) -> int:
        """Validate the script-run response and return the enqueued job's ID."""
        if response.status_code == 404:
            raise DryRunUnavailableError(
                f"Dry-run script '{self._dry_run_script}' was not found: it is "
                "not installed on the NetBox host, or the token lacks the "
                "extras.run_script permission. Copy this file into SCRIPTS_ROOT "
                f"on the NetBox host: {packaged_script_path()}"
            )
        if response.status_code == 403:
            raise DryRunUnavailableError(
                "NetBox denied the dry-run request (403): the token needs the "
                "extras.run_script permission and, on NetBox 4.6.8+, write "
                f"ability. Details: {response.text}"
            )
        # A stopped RQ worker is reported as 503 (400 on some releases).
        if response.status_code in (400, 503) and "worker" in response.text.lower():
            raise DryRunUnavailableError(
                "No RQ worker is running for NetBox's 'default' queue; dry runs cannot execute."
            )
        if not response.is_success:
            raise DryRunError(
                f"NetBox rejected the dry-run request "
                f"(HTTP {response.status_code}): {response.text}"
            )

        try:
            body = response.json()
        except ValueError as e:
            raise DryRunError(
                "NetBox returned a non-JSON response while starting the dry run."
            ) from e
        result = body.get("result") if isinstance(body, dict) else None
        job_id = result.get("id") if isinstance(result, dict) else None
        if job_id is None:
            raise DryRunError("NetBox returned no job to poll for the dry run.")
        return job_id

    def _wait_for_job(self, job_id: int) -> dict[str, Any]:
        """Poll the NetBox job until it reaches a terminal status.

        Transient failures are retried until the deadline; a 403 fails
        immediately, since a missing permission will not resolve by waiting.
        """
        url = f"{self._client.api_url}/core/jobs/{job_id}/"
        deadline = time.monotonic() + self._dry_run_timeout
        last_status = "unknown"
        last_error: str | None = None
        while True:
            try:
                response = self._client.session.get(url)
            except httpx.HTTPError as e:
                last_error = str(e)
            else:
                if response.status_code == 403:
                    raise DryRunUnavailableError(
                        "NetBox denied reading the dry-run job (403): the "
                        "token lacks the core.view_job permission."
                    )
                if response.is_success:
                    try:
                        job = response.json()
                    except ValueError:
                        job = None
                    if isinstance(job, dict):
                        last_status = _job_status(job)
                        last_error = None
                        if last_status in _TERMINAL_JOB_STATUSES:
                            return job
                    else:
                        last_error = "non-JSON job response"
                else:
                    last_error = f"HTTP {response.status_code}: {response.text}"

            if time.monotonic() >= deadline:
                detail = f" Last error: {last_error}" if last_error else ""
                raise DryRunUnavailableError(
                    f"Dry-run job {job_id} did not finish within "
                    f"{self._dry_run_timeout:.0f}s (status: {last_status!r}). "
                    f"Check the NetBox RQ worker.{detail}"
                )
            time.sleep(self._poll_interval)

    def _interpret_job(
        self,
        job: dict[str, Any],
        operation: str,
        object_type: str,
        nonce: str,
        object_id: int | None = None,
    ) -> dict[str, Any]:
        """Turn a finished script job into a structured dry-run verdict.

        The verdict repeats ``object_id`` for update and delete, so a caller
        can confirm the target before it repeats the call with dry_run=False.
        """
        data = job.get("data")
        if not isinstance(data, dict):
            data = {}
        output = data.get("output")
        verdict: dict[str, Any] | None = None
        if isinstance(output, str) and output:
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                candidate = parsed.get("mcp_dry_run")
                if isinstance(candidate, dict):
                    verdict = candidate

        # Trust a parseable verdict on any terminal status — some releases
        # mark failed validations as 'failed' even under commit=false.
        if verdict is None:
            raise DryRunError(
                f"Dry-run job for {operation} {object_type} ended with status "
                f"{_job_status(job)!r} and no usable verdict. "
                f"Log tail: {_log_tail(data)}"
            )
        if verdict.get("nonce") != nonce:
            raise DryRunError(
                "Dry-run verdict does not match this request: a concurrent "
                "validator run collided, or the MCPWriteValidator script on "
                "NetBox is outdated. Nothing was written; retry."
            )

        result: dict[str, Any] = {
            "valid": bool(verdict.get("valid")),
            "operation": operation,
            "object_type": object_type,
            "detail": verdict.get("detail", ""),
        }
        if object_id is not None:
            result["object_id"] = object_id
        if result["valid"]:
            result["_dry_run"] = (
                "Validated by NetBox (executed with commit=false and rolled "
                "back — nothing was written). Call again with dry_run=False "
                "to execute."
            )
        else:
            result["errors"] = verdict.get("errors", [])
            result["_dry_run"] = "Validation FAILED — nothing was written."
        return result
