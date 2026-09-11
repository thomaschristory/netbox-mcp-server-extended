"""Validation-only NetBox custom script backing netbox-mcp-server-extended dry runs.

Install this file on the NetBox host under SCRIPTS_ROOT (default:
$INSTALL_ROOT/netbox/scripts/netbox_mcp_server_extended.py) or upload it via
POST /api/extras/scripts/upload/. The MCP server executes it with commit=false,
so NetBox itself validates the requested change inside a database transaction
that is always rolled back: nothing persists, and no webhooks or event rules
fire (NetBox skips event tracking on commit=false runs).

The script refuses to run with commit=true — it is a validator, never a writer.
Real writes go through the normal REST API with the caller's token permissions.
"""

import json
from typing import Any

from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError, RestrictedError
from extras.scripts import ChoiceVar, IntegerVar, Script, StringVar, TextVar
from rest_framework.exceptions import ValidationError as DRFValidationError
from utilities.api import get_serializer_for_model
from utilities.exceptions import AbortRequest, AbortScript


class MCPWriteValidator(Script):
    """Validate a single create/update/delete without persisting it."""

    class Meta:
        name = "MCP Write Validator"
        description = (
            "Validation-only executor for netbox-mcp-server-extended dry runs. "
            "Applies the requested change with the same REST serializers as the "
            "API and relies on commit=false to roll everything back."
        )
        commit_default = False

    operation = ChoiceVar(
        choices=(("create", "create"), ("update", "update"), ("delete", "delete")),
        description="Write operation to validate",
    )
    object_type = StringVar(
        description="Dotted object type as used by the MCP tools (e.g. dcim.device)",
    )
    object_id = IntegerVar(
        required=False,
        description="Target object ID (update/delete only)",
    )
    payload = TextVar(
        required=False,
        description="JSON request body (create/update only)",
    )
    nonce = StringVar(
        required=False,
        description="Echoed in the verdict so the caller can match runs",
    )

    _nonce = ""

    def run(self, data: dict[str, Any], commit: bool) -> str:
        """Validate the requested write and return a JSON verdict.

        Args:
            data: Validated script variables (operation, object_type,
                object_id, payload, nonce).
            commit: Must be false; the script refuses to run as a writer.

        Returns:
            JSON verdict string, stored by NetBox as the job's output.

        Raises:
            AbortScript: If invoked with commit=true.
        """
        if commit:
            raise AbortScript(
                "MCPWriteValidator is validation-only and must be executed with "
                "commit=false. Perform real writes through the REST API."
            )

        self._nonce = data.get("nonce") or ""
        operation = data["operation"]
        object_type = data["object_type"]
        object_id = data.get("object_id")

        try:
            app_label, model_name = object_type.split(".", 1)
            model = apps.get_model(app_label, model_name)
        except (ValueError, LookupError) as e:
            return self._result(False, [f"Unknown object_type {object_type!r}: {e}"])

        payload: dict[str, Any] = {}
        raw_payload = data.get("payload")
        if raw_payload:
            try:
                payload = json.loads(raw_payload)
            except json.JSONDecodeError as e:
                return self._result(False, [f"payload is not valid JSON: {e}"])
            if not isinstance(payload, dict):
                return self._result(False, ["payload must be a JSON object"])

        instance = None
        if operation in ("update", "delete"):
            if not object_id:
                return self._result(False, [f"object_id is required for {operation}"])
            try:
                instance = model.objects.get(pk=object_id)
            except ObjectDoesNotExist:
                return self._result(False, [f"{object_type} id={object_id} does not exist"])

        if operation == "delete":
            return self._validate_delete(object_type, instance)
        return self._validate_save(operation, object_type, model, instance, payload)

    def _validate_delete(self, object_type: str, instance: Any) -> str:
        """Attempt the deletion inside the (rolled back) transaction."""
        label = f"{object_type} id={instance.pk} ({instance})"
        try:
            instance.delete()
        except (ProtectedError, RestrictedError) as e:
            return self._result(False, [f"Deletion blocked by dependent objects: {e}"])
        except AbortRequest as e:
            # NetBox signal handlers (e.g. PROTECTION_RULES) veto deletes this way.
            return self._result(False, [str(getattr(e, "message", e))])
        detail = f"Would delete {label}"
        self.log_success(detail)
        return self._result(True, [], detail)

    def _validate_save(
        self,
        operation: str,
        object_type: str,
        model: Any,
        instance: Any,
        payload: dict[str, Any],
    ) -> str:
        """Validate and apply a create/update with the REST serializer."""
        serializer_class = get_serializer_for_model(model)
        context = {"request": getattr(self, "request", None)}
        if operation == "update":
            serializer = serializer_class(instance, data=payload, partial=True, context=context)
        else:
            serializer = serializer_class(data=payload, context=context)

        if not serializer.is_valid():
            return self._result(False, self._flatten_errors(serializer.errors))
        try:
            obj = serializer.save()
        except (DjangoValidationError, DRFValidationError, IntegrityError) as e:
            return self._result(False, [f"save() failed validation: {e}"])
        except AbortRequest as e:
            # e.g. assigning a tag that is restricted to other object types.
            return self._result(False, [str(getattr(e, "message", e))])

        detail = f"Would {operation} {object_type} ({obj})"
        self.log_success(detail)
        return self._result(True, [], detail)

    @staticmethod
    def _flatten_errors(errors: Any) -> list[str]:
        """Flatten DRF serializer errors into human-readable strings."""
        flat: list[str] = []
        if isinstance(errors, dict):
            for field, messages in errors.items():
                if isinstance(messages, (list, tuple)):
                    flat.extend(f"{field}: {message}" for message in messages)
                else:
                    flat.append(f"{field}: {messages}")
        else:
            flat.append(str(errors))
        return flat

    def _result(self, valid: bool, errors: list[str], detail: str = "") -> str:
        """Emit the machine-readable verdict consumed by the MCP server."""
        if valid:
            self.log_info("Dry run valid; the transaction will be rolled back")
        else:
            for error in errors:
                self.log_failure(error)
        # Wire-protocol key read by netbox_write_client._interpret_job; both
        # sides must change in lockstep if it is ever renamed.
        return json.dumps(
            {
                "mcp_dry_run": {
                    "valid": valid,
                    "errors": errors,
                    "detail": detail,
                    "nonce": self._nonce,
                }
            }
        )
