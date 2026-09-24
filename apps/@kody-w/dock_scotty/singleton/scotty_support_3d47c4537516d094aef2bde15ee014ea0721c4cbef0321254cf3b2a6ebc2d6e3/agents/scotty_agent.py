"""Scotty: a normal current-Grail BasicAgent, not a Brainstem or model loop."""

import os
from pathlib import Path

from agents.basic_agent import BasicAgent

try:
    from scotty_distribution import DistributionRefused
    from scotty_observations import BLOCKED_ACTIONS, ScottyObservations
    from scotty_contract import (
        ACTIONS, ContractError, REPLY_RULES, encode_result, envelope, metadata,
        normalize_request, validate_request,
    )
    from local_dock import (
        LocalDock, LocalDockError, context_hint, discover_jobs, historical_view, safe_error,
    )
except ModuleNotFoundError:
    # The Grail auto-installs missing imports. A partial capability must instead
    # fail explicitly; it must never ask pip to find a similarly named package.
    raise RuntimeError(
        "Install the complete reviewed Scotty capability bundle."
    ) from None


class ScottyAgent(BasicAgent):
    def __init__(self):
        self._catalog = discover_jobs()
        self._dock = None
        super().__init__(
            name="Scotty",
            metadata=metadata(self._catalog["jobs"]),
        )

    def _controller(self):
        if self._dock is None:
            self._dock = LocalDock.shared()
        return self._dock

    def _observe(self, request):
        if request["action"] == "dock_status" and request.get("application"):
            request = {**request, "action": "application_status"}
        tree_status = None
        scope_file = os.environ.get("SCOTTY_WORK_SCOPE_FILE")
        if scope_file and request["action"] == "tree":
            try:
                from scotty_work_tree import from_scope_file
                tree_status = from_scope_file(Path(scope_file))
            except (DistributionRefused, ImportError, OSError, ValueError):
                return {"status": "blocked", "code": "explicit-work-adapter-unavailable",
                        "effects_performed": [], "application_provider_calls": 0,
                        "llm_inferred": False, "tree": {"status": "not_observed"}}
        snapshot_file = os.environ.get("SCOTTY_NAS_SNAPSHOT_FILE")
        if request.get("application") == "intelligence":
            return {"status": "observed", "effects_performed": [], "application_provider_calls": 0,
                    "llm_inferred": False, "applications": [],
                    "paid_calls": {"mode": "stub", "entries": []}}
        return ScottyObservations(
            tree_status=tree_status,
            nas_snapshot_file=Path(snapshot_file) if snapshot_file else None,
        ).perform(request)

    @staticmethod
    def _observation_result(action, observed, *, application=None, result=None, message=""):
        answer = envelope(action, observed.get("status", "unknown"), application=application, result=result, message=message)
        if action in ("dock_status", "application_status") and isinstance(result, dict) and result.get("observed_at"):
            answer["observed_at"] = result["observed_at"]
            if result.get("docker_error"):
                answer["error"] = result["docker_error"]
        # Compatibility fields remain explicitly historical, never current Docker readiness.
        for key, value in observed.items():
            if key not in answer:
                answer[key] = value
        answer["historical_observation"] = True
        if "applications" in answer:
            applications = []
            for item in answer["applications"]:
                selected = {key: item[key] for key in (
                    "application", "source_commit", "installation_state", "installation_performed",
                ) if key in item}
                qualification = item.get("recorded_qualification")
                if isinstance(qualification, dict):
                    selected["recorded_qualification"] = {key: qualification[key] for key in (
                        "status", "runtime_observed_now", "production_authority",
                        "scotty_application_job_dispatch",
                    ) if key in qualification}
                applications.append(selected)
            answer["applications"] = applications
        if "paid_calls" in answer:
            inventory = answer["paid_calls"]
            answer["paid_calls"] = {
                **{key: value for key, value in inventory.items() if key != "entries"},
                "entries": [
                    {key: item[key] for key in (
                        "id", "application", "provider", "operation", "billing", "status",
                        "enabled", "estimated_cost", "stub",
                    ) if key in item}
                    for item in inventory.get("entries", [])
                ],
            }
        if observed.get("code"):
            answer["error"] = safe_error(observed["code"])
        return answer

    @staticmethod
    def _operation_result(action, record):
        native = record.get("result") if isinstance(record.get("result"), dict) else {}
        status = record["status"]
        if record.get("kind") == "job":
            result = dict(native.get("result") or {})
            if record.get("native"):
                result["native"] = record["native"]
        else:
            result = dict(native)
        if record.get("cancellation"):
            result["cancellation"] = record["cancellation"]
        if record.get("reconciliation"):
            result["reconciliation"] = record["reconciliation"]
        if record.get("admission"):
            result["admission"] = record["admission"]
        if record.get("recovery_of"):
            result["recovery"] = {
                "original_operation_id": record["recovery_of"], "mode": "read-only-native-collection",
                "native_submission_replayed": False, "inference_replayed": False,
            }
        application_progress = record.get("application_progress") or {}
        if application_progress:
            result["applications"] = list(application_progress.values())
        for field in ("output_dir", "outputs_dir", "state_home"):
            result.pop(field, None)
        if status in ("queued", "running"):
            message = "Work is " + status + "; observed phase: " + str(record.get("phase") or status) + ". Poll this operation ID to collect it."
            if application_progress:
                stopped = [app for app, state in application_progress.items() if state.get("stopped") is True]
                pending = [f"{app} ({state['phase']})" for app, state in application_progress.items() if state.get("stopped") is not True]
                message = ("Stopped: " + ", ".join(stopped) + ". " if stopped else "") + (
                    "Still stopping: " + ", ".join(pending) + "."
                    if pending else "Application containers are stopped; final network checks continue."
                )
        elif status in ("failed", "cancelled", "interrupted"):
            message = (record.get("error") or safe_error(status))["message"]
        elif status == "partial":
            message = native.get("message") or "Only part of the requested work completed; inspect the verified outputs."
        else:
            message = native.get("message") or "The requested operation completed and its result was observed."
        answer = envelope(action, status, operation=record, result=result, message=str(message)[:500])
        if action == "bundle":
            capsule = record["capsule"]
            answer["result"] = {"capsule": capsule}
            answer["artifacts"] = [{
                "name": Path(capsule["path"]).name, "path": capsule["path"],
                "media_type": "application/vnd.rapp.egg", "bytes": capsule["bytes"],
                "sha256": capsule["sha256"], "verified": True,
            }]
            answer["provenance"]["capsule_data_complete"] = capsule["data_complete"]
            answer["message"] = "A canonical RAPP/1 capsule was verified; import is inert."
        return answer

    def perform(self, **kwargs):
        action = kwargs.get("action")
        try:
            kwargs = normalize_request(kwargs)
            action = kwargs.get("action")
            if isinstance(action, str) and action in BLOCKED_ACTIONS and action not in (*ACTIONS, "remove"):
                observed = self._observe(kwargs)
                return encode_result(self._observation_result(
                    action, observed, application=kwargs.get("application"),
                    message="That legacy action is unavailable. Use installed local run/start/stop actions instead.",
                ))
            request = validate_request(
                kwargs, self._catalog["jobs"],
                operation_lookup=lambda op_id: self._controller().ops.get(op_id),
            )
            action = request.pop("action")
            application = request.get("application")
            if action in ("history", "lineage"):
                projection = historical_view(action, self._dock.home if self._dock is not None else None, **request)
                answer = envelope(
                    action, "observed", application=application, result=projection,
                    message="Historical evidence retrieved; no new work ran. Current artifact availability was not checked.",
                )
                answer["observed_at"] = projection["snapshot_utc"]
                answer["historical_evidence"] = True
                answer["provenance"]["verification"] = projection["verification"]
                return encode_result(answer)
            if action in ("tree", "paid_calls", "paid_call_stub"):
                observed = self._observe({"action": action, **request})
                extra = None
                message = "Historical integration metadata; no paid third-party call was dispatched."
                if action == "paid_calls":
                    extra = {"local_intelligence": {
                        "runtime": "copilot-cli-in-docker", "authorized": True,
                        "adapter_installed": any(item["application"] == "intelligence" and item["state"] == "installed" for item in self._catalog["applications"]),
                        "model": os.environ.get("RAPP_DOCK_AI_MODEL", "gpt-5-mini"),
                        "calls": None, "usage_tokens": None, "third_party_paid_providers": "disabled",
                    }}
                elif action == "tree":
                    message = "Explicit Work-tree observation." if observed.get("status") == "observed" else "No usable explicit Work-tree adapter is configured."
                return encode_result(self._observation_result(action, observed, application=application, result=extra, message=message))
            if action == "jobs":
                return encode_result(envelope(action, "observed", application=application,
                    result=discover_jobs(application, request.get("query")), message="Installed outcome jobs; run a known job directly."))
            if action in ("dock_status", "application_status"):
                observed = self._observe({"action": action, **request})
                current = self._controller().status(application)
                message = (
                    "Current Docker state is unknown; no empty or stopped state is assumed."
                    if current["docker_state"] == "unknown" else
                    "No local adapters are installed; historical qualification is separate."
                    if current["docker_state"] == "not-needed" else
                    "Current Dock container state observed; Docker network state is unknown. Historical qualification is separate."
                    if (current.get("networks") or {}).get("state") == "unknown" else
                    "Current Dock container state observed; historical qualification is separate."
                )
                return encode_result(self._observation_result(action, observed, application=application, result=current, message=message))
            dock = self._controller()
            if action == "run":
                app = request["job"].split(".", 1)[0]
                record = dock.run_job(app, request["job"], request["arguments"], wait_seconds=request["wait_seconds"])
            elif action in ("start", "stop", "restart"):
                record = dock.lifecycle(action, application, wait_seconds=request["wait_seconds"])
            elif action == "operation":
                record = dock.operation(request["operation_id"], wait_seconds=request["wait_seconds"])
            elif action == "cancel":
                record = dock.cancel(request["operation_id"], wait_seconds=request["wait_seconds"])
            elif action == "retry":
                record = dock.retry(request["operation_id"], wait_seconds=request["wait_seconds"])
            elif action == "bundle":
                record = dock.bundle(request["operation_id"])
            elif action == "operations":
                return encode_result(envelope(action, "observed", application=application,
                    result=dock.operations(application), message="Recent operations; use an exact returned ID to collect a result."))
            elif action == "logs":
                return encode_result(envelope(action, "observed", application=application,
                    result=dock.logs(application), message="Bounded redacted logs from the selected Dock project."))
            else:
                raise ContractError("Select an advertised action.")
            return encode_result(self._operation_result(action, record))
        except ContractError as error:
            return encode_result(envelope(action if action in ACTIONS else "invalid", "refused",
                message=error.message,
                result={"job": kwargs.get("job"), "expected_arguments": error.expected_schema} if error.expected_schema else None,
                error={"code": error.code, "message": error.message,
                                            "retryable": False, "retry_scope": "correct-arguments"}))
        except LocalDockError as error:
            failure = safe_error(error.code)
            answer = envelope(action if action in ACTIONS else "invalid",
                              "refused" if error.code.startswith("history-invalid-") or error.code == "history-stale-cursor" else
                              "blocked" if error.code in ("not-installed", "quiescing", "stopping", "queue-full", "detaching") else "failed",
                              message=failure["message"], error=failure)
            if error.code == "input-not-enrolled" and self._dock is not None:
                answer["result"] = {"allowed_input_roots": [str(root) for root in self._dock.input_roots],
                                    "verified_prior_outputs_allowed": True}
            if error.code == "not-installed":
                answer.update(execution_available=False, plan=None)
            return encode_result(answer)
        except Exception:
            failure = safe_error("unexpected-error")
            return encode_result(envelope(action if action in ACTIONS else "invalid", "failed",
                                          message=failure["message"], error=failure))

    def system_context(self):
        hint = context_hint()
        return REPLY_RULES + ("\nCached operation hints (poll before claiming completion): " + hint if hint else "")
