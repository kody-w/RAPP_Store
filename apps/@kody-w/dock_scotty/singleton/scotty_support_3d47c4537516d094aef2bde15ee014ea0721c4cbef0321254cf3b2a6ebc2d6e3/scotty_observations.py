"""Deterministic Scotty tool data for the unchanged current Grail.

There is no server, inference adapter, conversation store, or execution grant
here. Work tree access is optional and supplied explicitly.
"""

from __future__ import annotations

import importlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scotty_distribution import (
    CURRENT_GRAIL_COMMIT,
    ROOT,
    DistributionRefused,
    verify_capability,
)

APPLICATIONS = ("scrapling", "dify", "open-seo", "openshorts", "presenton")
READ_ACTIONS = (
    "dock_status",
    "application_status",
    "tree",
    "paid_calls",
    "paid_call_stub",
)
BLOCKED_ACTIONS = (
    "plan",
    "install",
    "deploy",
    "configure",
    "start",
    "stop",
    "restart",
    "job",
    "backup",
    "restore",
    "update",
    "rollback",
    "remove",
)
ACTIONS = (*READ_ACTIONS, *BLOCKED_ACTIONS)
MAX_RESULT_BYTES = 32 * 1024


class _SnapshotRefused(DistributionRefused):
    pass


def _result(action: str, status: str, **data: Any) -> dict[str, Any]:
    result = {
        "capability": "Scotty",
        "engine": "current-grail",
        "action": action,
        "status": status,
        "origin": "deterministic-local-tool-result",
        "llm_inferred": False,
        "application_provider_calls": 0,
        "effects_performed": [],
        **data,
    }
    if len(json.dumps(result, allow_nan=False).encode("utf-8")) > MAX_RESULT_BYTES:
        return _result(action, "blocked", code="result-bound-exceeded", result=None)
    return result


def _validate(request: dict[str, Any]) -> tuple[str, str | None, str | None]:
    if not isinstance(request, dict) or set(request) - {
        "action",
        "application",
        "integration_id",
    }:
        raise DistributionRefused("unknown tool argument")
    action = request.get("action")
    application = request.get("application")
    integration_id = request.get("integration_id")
    if not isinstance(action, str) or action not in ACTIONS:
        raise DistributionRefused("unsupported action")
    if application is not None and (
        not isinstance(application, str) or application not in APPLICATIONS
    ):
        raise DistributionRefused("unknown application")
    if integration_id is not None and (
        not isinstance(integration_id, str)
        or len(integration_id) > 128
        or re.fullmatch(r"[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*", integration_id) is None
    ):
        raise DistributionRefused("invalid integration id")
    if action == "application_status" and application is None:
        raise DistributionRefused("application is required")
    if action == "paid_call_stub" and integration_id is None:
        raise DistributionRefused("integration id is required")
    if integration_id is not None and action != "paid_call_stub":
        raise DistributionRefused("integration id is not applicable")
    if application is not None and action not in {
        "application_status",
        "paid_calls",
        *BLOCKED_ACTIONS,
    }:
        raise DistributionRefused("application is not applicable")
    return action, application, integration_id


class ScottyObservations:
    def __init__(
        self,
        *,
        tree_status: Callable[[], dict[str, Any]] | None = None,
        nas_snapshot_file: Path | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 30:
            raise DistributionRefused("invalid observation time bound")
        self._tree_status = tree_status
        self._nas_snapshot_file = nas_snapshot_file
        self._timeout_seconds = timeout_seconds

    def _recipes(self) -> Any:
        verify_capability()
        module = importlib.import_module("deploy.stacks.recipes")
        expected = ROOT / "deploy/stacks/recipes.py"
        if Path(module.__file__).resolve() != expected.resolve():
            raise DistributionRefused(
                "recipe module is not from the reviewed capability bundle"
            )
        return module

    def _daemon_observation(self) -> dict[str, Any]:
        if self._nas_snapshot_file is None:
            return {
                "status": "not_observed",
                "reason": "No explicit external read-only NAS snapshot is configured.",
            }
        module = importlib.import_module("dock_nas")
        if Path(module.__file__).resolve() != (ROOT / "dock_nas.py").resolve():
            raise _SnapshotRefused(
                "NAS snapshot reader is not from the reviewed bundle"
            )
        try:
            snapshot = module.read_snapshot(self._nas_snapshot_file)
        except module.ObservationError:
            raise _SnapshotRefused("configured NAS snapshot was refused") from None
        return {
            "status": "observed",
            "source": "external-private-read-only-snapshot",
            **snapshot,
        }

    def perform(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            action, application, integration_id = _validate(request)
        except DistributionRefused:
            return _result(
                "invalid", "refused", code="invalid-tool-arguments", result=None
            )
        if action in BLOCKED_ACTIONS:
            return _result(
                action,
                "blocked",
                application=application,
                execution_available=False,
                plan=None,
                result=None,
                reason="This installed capability has no lifecycle execution interface or authority.",
                required=[
                    "qualified execution adapter",
                    "exact owner-approved plan",
                    "authenticated through-effect authority and host fence",
                ],
            )
        deadline = time.monotonic() + self._timeout_seconds
        try:
            if action == "tree":
                if self._tree_status is None:
                    return _result(
                        action,
                        "blocked",
                        code="optional-work-tree-not-configured",
                        tree={"status": "not_observed"},
                        result=None,
                    )
                data = self._tree_status()
                if not isinstance(data, dict):
                    raise DistributionRefused("invalid tree observation")
                selected = {
                    key: data[key]
                    for key in (
                        "world_id",
                        "entries",
                        "hive_authority",
                        "deployment_authority",
                    )
                }
                result = _result(action, "observed", tree=selected)
            else:
                recipes = self._recipes()
                if action == "paid_calls":
                    result = _result(
                        action,
                        "observed",
                        paid_calls=recipes.paid_call_inventory(application),
                    )
                elif action == "paid_call_stub":
                    result = _result(
                        action,
                        "blocked",
                        paid_call=recipes.stub_paid_call(integration_id),
                        result=None,
                        generated_artifacts=[],
                    )
                else:
                    applications = []
                    for name in (
                        (application,) if application is not None else APPLICATIONS
                    ):
                        if time.monotonic() >= deadline:
                            raise DistributionRefused("observation deadline exceeded")
                        observed = recipes.inspect(name)
                        applications.append(
                            {
                                key: observed[key]
                                for key in (
                                    "application",
                                    "source_commit",
                                    "static_validation",
                                    "renderable",
                                    "sdk_executor_qualified",
                                    "render_blockers",
                                    "installation_state",
                                    "installation_performed",
                                    "recorded_qualification",
                                )
                            }
                        )
                    result = _result(
                        action,
                        "observed",
                        grail={"commit": CURRENT_GRAIL_COMMIT, "version": "0.6.16"},
                        daemon_observation=self._daemon_observation(),
                        applications=applications,
                        work_tree="explicit-optional-adapter"
                        if self._tree_status
                        else "not_configured",
                        grail_inference={
                            "provider": "github-copilot-api",
                            "availability": "not_assessed_by_capability",
                            "permission": "requires-owner-authentication-and-network-budget-approval",
                        },
                    )
            if time.monotonic() >= deadline:
                raise DistributionRefused("observation deadline exceeded")
            if len(json.dumps(result, allow_nan=False).encode()) > MAX_RESULT_BYTES:
                raise DistributionRefused("observation result exceeded its bound")
            return result
        except _SnapshotRefused:
            return _result(
                action,
                "blocked",
                code="configured-nas-snapshot-refused",
                result=None,
                daemon_observation={
                    "status": "refused",
                    "scope": "daemon-aggregate-only",
                    "application_status": "not_observed",
                    "authority": "none",
                },
                reason="The configured snapshot is missing, stale, insecure or unverified; no daemon counts are assumed.",
            )
        except (
            DistributionRefused,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            ImportError,
        ):
            return _result(
                action,
                "blocked",
                code="observation-unavailable-or-unverified",
                result=None,
                reason="Review the installed capability bytes and explicit optional adapter; no effect was performed.",
            )
