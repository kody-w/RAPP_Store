"""Controller adapter for the namespace's tool-free Copilot inference transport."""

from __future__ import annotations

from pathlib import Path

from local_dock import LocalDockError

from .build import image_tag


APP = "intelligence"
TITLE = "Copilot intelligence gateway"
COMPOSE = "compose.yaml"
NEEDS = ()
START_TIMEOUT = 90
READY_TIMEOUT = 45
ENROLLED_APPS = ("intelligence", "scrapling", "presenton", "open-seo", "dify", "openshorts")
KEYS_FILE = "intelligence-keys.env"


def urls(ctx):
    return {"api": ctx.host_url("/v1"), "health": ctx.host_url("/health")}


def prepare(ctx):
    keys = {app: ctx.secret(f"intelligence-key-{app}") for app in ENROLLED_APPS}
    ctx.write_env_file(KEYS_FILE, {"INTELLIGENCE_KEYS": ",".join(f"{app}:{key}" for app, key in keys.items())})


def compose_env(ctx):
    return {
        "RAPP_DOCK_INTELLIGENCE_IMAGE": image_tag(Path(__file__).resolve().parent),
        "RAPP_DOCK_INTELLIGENCE_KEYS_ENV": str(ctx.secret_path(KEYS_FILE)),
    }


def ready(ctx):
    try:
        response = ctx.http("GET", ctx.host_url("/health"), timeout=3, max_bytes=8192)
        value = response.json()
        healthy = response.status == 200 and value.get("status") == "ok" and value.get("authentication_configured") is True
    except Exception:
        healthy = False
    return {"ready": healthy, "detail": "Gateway is configured and responsive." if healthy else "Gateway is unavailable or lacks Copilot authentication."}


def _usage(value):
    if value is None:
        return None
    totals = ("prompt_tokens", "completion_tokens", "total_tokens")
    details = {"prompt_tokens_details": "cached_tokens", "completion_tokens_details": "reasoning_tokens"}
    if not isinstance(value, dict) or set(value) - set(totals) - details.keys() or any(
        type(value.get(key)) is not int or not 0 <= value[key] <= 10**15 for key in totals
    ) or value["total_tokens"] != value["prompt_tokens"] + value["completion_tokens"]:
        raise LocalDockError("output-invalid", "The gateway returned malformed token-usage evidence.")
    result = {key: value[key] for key in totals}
    for key, name in details.items():
        if key in value:
            entry = value[key]
            if not isinstance(entry, dict) or set(entry) != {name} or type(entry[name]) is not int or not 0 <= entry[name] <= 10**15:
                raise LocalDockError("output-invalid", "The gateway returned malformed detailed token usage.")
            result[key] = {name: entry[name]}
    return result


def _chat(ctx, prompt):
    if not isinstance(prompt, str) or not 1 <= len(prompt) <= 4000:
        raise LocalDockError("invalid-input", "Provide a diagnostic prompt of 1 to 4000 characters.")
    connection = ctx.intelligence()
    ctx.phase("generating", "Asking the tool-free Copilot gateway.")
    response = ctx.http(
        "POST", connection["host_url"] + "/chat/completions",
        json_body={
            "model": connection["model"], "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": 512, "stream": False,
        },
        headers={"Authorization": "Bearer " + connection["api_key"]},
        timeout=130, max_bytes=1_048_576,
    )
    request_id = next((value for key, value in response.headers.items() if key.lower() == "x-request-id"), None)
    if request_id:
        ctx.record_native("intelligence_request_id", request_id)
    try:
        result = response.json()
        usage = _usage(result.get("usage")) if isinstance(result, dict) else None
    except (ValueError, TypeError):
        raise LocalDockError("output-invalid", "Gateway returned an invalid diagnostic result.") from None
    ctx.record_native("intelligence_usage", usage)
    if response.status != 200:
        code = "intelligence-auth-unavailable" if response.status in (401, 503) else "intelligence-unavailable"
        raise LocalDockError(code, "The intelligence diagnostic did not complete.")
    try:
        answer = result["choices"][0]["message"]["content"]
        if not isinstance(answer, str) or not answer.strip() or not request_id or result.get("model") != connection["model"]:
            raise ValueError
    except (ValueError, KeyError, IndexError, TypeError):
        raise LocalDockError("output-invalid", "Gateway returned an invalid diagnostic result.") from None
    artifact = ctx.save_output("answer.md", answer.encode("utf-8"), "text/markdown", verified=True)
    return {
        "message": "Copilot answered the diagnostic request.",
        "result": {"answer": answer[:2000], "truncated": len(answer) > 2000, "usage": usage},
        "artifacts": [artifact],
        "provider": {
            "runtime": "copilot-cli-in-docker", "model": result["model"], "observed_model": result["model"],
            "calls": 1, "request_ids": [request_id], "usage": usage,
        },
        "native": {"intelligence_request_id": request_id},
    }


JOBS = {
    "chat": {
        "description": "Ask the tool-free Copilot gateway a short diagnostic question and retain its answer.",
        "parameters": {"prompt": {"type": "string", "minLength": 1, "maxLength": 4000}},
        "required": ["prompt"], "run": _chat, "heavy": False,
        "aliases": ["intelligence", "copilot", "diagnostic"],
    }
}
