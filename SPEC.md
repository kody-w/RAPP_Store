# Rapplication Spec

`schema: rapp-application/1.0`

A **rapplication** is a portable, self-describing bundle of one Python agent (and optional UI / state / docs) that drops into any RAPP brainstem and runs. This document defines the bundle layout, the manifest schema, the singleton contract, and the validation rules. Everything in `rapp_store/` conforms to this spec; everything that gets submitted to the store is checked against it.

## 1. Bundle layout

A rapplication is a single directory whose top-level name is the rapplication `id`. Required and optional files:

```
<id>/
  manifest.json          REQUIRED  schema: rapp-application/1.0
  index_entry.json       REQUIRED  the catalog entry to merge into rapp_store/index.json
  singleton/
    <id>_agent.py        REQUIRED  the deployable single-file agent
  README.md              REQUIRED  human-readable description
  ui/
    index.html           OPTIONAL  iframe-mounted UI; entrypoint declared in manifest.ui
  eggs/
    *.egg                OPTIONAL  immutable state snapshots (zip cartridges)
  source/                OPTIONAL  multi-file authoring surface for composites (the singleton is generated from these)
  tools/
    build.py             OPTIONAL  collapse source/ → singleton/
  service/
    <id>_service.py      OPTIONAL  HTTP service module (services rapps)
  versions/
    <semver>/            OPTIONAL  pinned snapshots of (manifest.json, agent.py, service.py)
```

The submission unit is **the `<id>/` directory zipped**. The `.zip` filename SHOULD be `<id>-<version>.zip`. The zip MAY contain an extra wrapper directory (e.g. `spine_dag-1.0.0.zip` may extract to `spine_dag/...`) — extractors must tolerate one level of wrapping.

## 2. `manifest.json`

```json
{
  "schema": "rapp-application/1.0",
  "id": "spine_dag",
  "name": "SpineDAG",
  "version": "1.0.0",
  "publisher": "@rapp",
  "summary": "...",
  "category": "analysis",
  "tags": ["dag", "graph", "..."],
  "agent": "singleton/spine_dag_agent.py",
  "ui": "ui/index.html",
  "service": "service/spine_dag_service.py",
  "license": "BSD-style",
  "homepage": "https://...",
  "quality_tier": "community"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema` | string | yes | Must be exactly `"rapp-application/1.0"` |
| `id` | string | yes | snake_case, `^[a-z][a-z0-9_]*$`. Becomes the directory name. No dashes. |
| `name` | string | yes | Human display name. |
| `version` | string | yes | Semver `MAJOR.MINOR.PATCH`. On resubmit must be strictly greater than the catalog's current version. |
| `publisher` | string | yes | `@<github-username>` for community submissions, `@rapp` reserved for official rapps. |
| `summary` | string | yes | One paragraph. |
| `category` | string | yes | Locked enum: `productivity`, `creative`, `analysis`, `data`, `integration`, `platform`, `workspace`. New categories require a proposal. |
| `tags` | string[] | yes | At least `"rapplication"`. |
| `agent` | string | **yes** | Relative path to the singleton, e.g. `singleton/<id>_agent.py`. The agent runs **headless** through any standard brainstem invocation path (LLM tool call, `/chat`, the generic `/api/binder/agent` endpoint) — same as any installed agent. The binder agent is for install/uninstall, not invocation. |
| `ui` | string | **yes** | Relative path to the iframe entrypoint. The UI is the rapplication's user-facing surface; without it the artifact is just a swarm-agent and belongs in RAR. The UI talks to its agent via the cartridge protocol (§9) — `rapp:invoke` for one-shot, `rapp:chat` for conversational. |
| `service` | string | no | Relative path to an HTTP service module. Optional — most rapplications don't need one. |
| `license` | string | no | SPDX or free-form. |
| `quality_tier` | string | no | `featured` / `official` / `verified` / `community` / `experimental` / `deprecated`. Submitters cannot self-declare above `community` (or `experimental` / `deprecated` — those are submitter-allowed self-marks). The receiver's `build_index_entry()` downgrades anything higher to `community`. Tier promotions to `verified`, `official`, or `featured` happen via maintainer-merged PR only. |

Other fields (`tagline`, `manifest_name`, `produced_by`, `optional_dependencies`, `tool`, etc.) are tolerated and pass through to the catalog entry verbatim.

## 3. `index_entry.json`

The snippet to merge into `rapp_store/index.json` under `rapplications[]`. Required minimum:

```json
{
  "id": "spine_dag",
  "name": "SpineDAG",
  "version": "1.0.0",
  "summary": "...",
  "category": "analysis",
  "tags": ["..."],
  "singleton_filename": "spine_dag_agent.py",
  "singleton_url": "https://raw.githubusercontent.com/kody-w/rapp_store/main/apps/@rapp/spine_dag/singleton/spine_dag_agent.py"
}
```

Integrity fields (`singleton_sha256`, `singleton_lines`, `singleton_bytes`, and the equivalents for `service_*` / `ui_*`) are **always recomputed by the receiver** from the actual on-disk files at promotion time. Whatever the submitter ships in `index_entry.json` for these fields is overwritten. The submitter does not need to compute them.

`singleton_url` and other `*_url` fields are likewise rewritten by the receiver to point at `kody-w/rapp_store/main/apps/@<publisher>/<id>/...` (Proposal 0002 — publisher namespacing). The submitter SHOULD ship them with the canonical value but is not required to.

## 4. Singleton contract

The `singleton/<id>_agent.py` file MUST satisfy SPEC §5 of `kody-w/RAPP/pages/docs/SPEC.md`. Concretely, AST-checkable:

1. The file imports `BasicAgent` (any of the accepted import paths: `from agents.basic_agent import BasicAgent`, `from basic_agent import BasicAgent`, or `from openrappter.agents.basic_agent import BasicAgent`).
2. It defines exactly one class whose name ends in `Agent` and is not `BasicAgent` itself, extending `BasicAgent` (directly or transitively). Internal helper classes MUST be prefixed `_Internal` so the brainstem's `*Agent` auto-discovery skips them.
3. That class defines a `perform(self, **kwargs)` method (or `perform(self, ...)` with keyword args).
4. The module has a top-level `__manifest__` dict literal (AST-extractable) with `schema: "rapp-agent/1.0"` and at least `name`, `version`, `description`.
5. No `{{PLACEHOLDER}}`, `YOUR LOGIC`, `TODO REPLACE`, `RAPP AGENT TEMPLATE` template strings remain in the file.

LLM dispatch SHOULD route through `from utils.llm import call_llm` (host-provided) rather than embedding API keys or hard-coding Azure/OpenAI clients.

## 5. Service contract (optional)

If `manifest.service` is set, the service module MUST export:

- `name = "<route prefix>"` — mounts at `/api/<name>/...`.
- `handle(method, path, body)` returning `(dict|bytes, status)` or `(body, status, headers)` for binary responses.

## 6. Validation rules (the receiver enforces these)

A submission is **accepted** iff all of the following pass:

1. The bundle extracts cleanly and contains `manifest.json` at the bundle root (or one level down inside a wrapper directory).
2. `manifest.json` validates against §2.
3. `id` is snake_case and not a reserved name (`scripts`, `tests`, `versions`, `eggs`, `senses`, `binder`).
4. The directory name matches `manifest.id` (after one optional wrapper level).
5. `singleton/<id>_agent.py` (or `service/<id>_service.py`) exists and matches the path declared in `manifest.agent` / `manifest.service`.
6. The singleton passes the AST checks in §4.
7. If a catalog entry with this `id` already exists, `manifest.version` is strictly greater (semver).
8. `publisher` matches `@<issue_author_github_login>` UNLESS the issue title declares an explicit override AND a maintainer has approved it.
9. Total bundle size < 5 MB. Singleton < 200 KB. UI < 500 KB.
10. No file in the bundle escapes the bundle root (no `..` path traversal).
11. The manifest declares **both** `agent` AND `ui` (rapplications are agent + UI bundles by definition). A bundle missing either is rejected:
    - No `ui` → `E_NO_UI`. Without a UI, the artifact is just a swarm-agent — submit to `kody-w/RAR` instead.
    - No `agent` AND no `service` → `E_BARE_AGENT_BELONGS_IN_RAR` (the original Article XXVII rule, kept for the no-app-surface case).

    **Headless invocation** of a rapplication's agent is automatic and requires no extra plumbing — once installed, the agent is in the brainstem's `agents/` dir and callable via any standard path (LLM tool call, `/chat`, `/api/binder/agent` generic invoke). UI presence does not constrain headless usability.

A failure on any rule rejects the submission with a specific error code (see `scripts/lib_rapp.py`).

## 7. Submission paths

A rapplication can enter the catalog in **two modes**, and either mode can be triggered from a local bundle or from a public GitHub repo URL.

### Mode A — Bundle (copy into the catalog)

The bundle's files are copied into `rapp_store/<id>/`. URLs in the catalog point at `kody-w/rapp_store/main/<id>/...`. Use this when the rapplication should live in this repo (official rapps, contributions you don't want to maintain a separate repo for).

### Mode B — Federation (reference an external repo)

The catalog entry's `singleton_url` (and `ui_url`, `service_url`) point at the submitter's own repo via `raw.githubusercontent.com`. Nothing gets copied into `rapp_store/`. The submitter remains the source of truth; updates flow by resubmitting (which re-resolves the ref and re-pins the SHA256).

Federation entries carry a `source` block:

```json
{
  "id": "my_thing",
  "version": "0.2.0",
  "singleton_url": "https://raw.githubusercontent.com/alice/cool-rapps/main/my_thing/singleton/my_thing_agent.py",
  "singleton_sha256": "...",
  "source": {
    "type": "federation",
    "repo": "alice/cool-rapps",
    "ref": "main",
    "path": "my_thing",
    "commit_sha": "<resolved>"
  }
}
```

`source.commit_sha` is resolved at validation time via the GitHub public API (`/repos/<owner>/<repo>/commits/<ref>`, anonymous, no token required). It pins what the catalog vouched for. Brainstems still install from `singleton_url` (which uses `ref`, e.g. `main`) and verify against `singleton_sha256`; a SHA mismatch surfaces as a hard install failure.

### Submission triggers

Both modes can be triggered any of three ways:

1. **`@rapp/publish-to-rapp-store` agent (local CLI)** — call its `submit_bundle <path>` (mode A) or `submit_repo <github-url>` (mode B). The agent validates locally, then opens a GitHub issue with a structured payload.
2. **Issue template** — open an issue with the `[RAPP]` template, fill in either *(a)* a bundle attachment or *(b)* a repo URL field. The receiver workflow handles the rest.
3. **Direct PR** (mode A only) — fork, drop a `<id>/` directory in, regenerate `index.json`, open the PR. The validator runs in CI.

### Receiver flow

1. Workflow parses the issue payload (bundle attachment OR `repo: <url>` field).
2. **Mode A:** download the zip, extract, validate per §6.
   **Mode B:** fetch `manifest.json` and the singleton from `raw.githubusercontent.com`, validate per §6 (file existence checks become HTTP GETs).
3. On pass: comment `Validated. Awaiting maintainer approval.` and label `pending-review`. For mode A, also write the bundle to `staging/<id>/`.
4. Maintainer adds `approved` label.
5. Approval workflow:
   - **Mode A:** promote `staging/<id>/` → `<id>/`, recompute integrity, merge into `index.json`.
   - **Mode B:** resolve `commit_sha`, recompute integrity from the fetched files, merge a federation entry into `index.json`. No files copied.
6. Commit, comment `Approved. Available at <singleton_url>`, close issue.

## 8. Versioning

- `manifest.version` is the source of truth for the live version.
- On promotion, the receiver SHOULD copy the previous live files (if any) to `<id>/versions/<old_version>/` so old SHAs in the catalog's `available_versions` list keep resolving. This makes pinned installs reproducible.

## 9. Cartridge protocol (rapp UIs ↔ parent runtime)

`schema: rapp-cartridge/1.0`

When a rapp's UI is mounted in a parent runtime (the vBrainstem at `kody-w.github.io/RAPP_Store/vbrainstem.html`, the local brainstem's `/binder/ui/<id>` mount, or any other host that follows this protocol), the parent posts a structured **cartridge** to the iframe via `window.postMessage` and acts as a runtime bridge for any agent / chat / fetch calls the UI wants to make.

Standalone rapps (UIs loaded directly at their `ui_url`) ignore the protocol and run with whatever defaults they ship. The cartridge is purely additive.

### 9.1 The envelope

The parent posts (target origin `*`) once on iframe load, and again any time the UI re-requests it:

```jsonc
{
  "type": "rapp:cartridge",
  "schema": "rapp-cartridge/1.0",
  "rapp": { /* full catalog entry — id, name, version, publisher, manifest_name,
                singleton_url, ui_url, egg_url, summary, tagline, category,
                tags, surfaces, ... */ },
  "context": {
    "user":   { "login": "kody-w", "name": "Kody Wildfeuer", "avatar_url": "..." } | null,
    "tether": { "active": true, "base": "http://localhost:7071" } | { "active": false, "base": null },
    "session": { "id": "vbs-...", "conversation_history": [{"role":"user","content":"..."}, ...] },
    "origin":  { "vbrainstem": "https://...", "catalog_source": "kody-w/RAPP_Store" }
  },
  "capabilities": {
    "can_invoke_agent": true | false,
    "can_proxy_fetch":  true,
    "can_post_chat":    true
  }
}
```

**No auth token crosses the boundary.** UIs that need authenticated network access call `rapp:fetch` (§9.3) — the parent decides what to proxy.

### 9.2 UI → parent messages

The UI can post these back via `window.parent.postMessage(msg, '*')`:

| Message | Reply | Purpose |
|---|---|---|
| `{type: "rapp:get_cartridge"}` | `rapp:cartridge` envelope | UI loaded after the parent's first post (or wants a fresh copy after state changes) |
| `{type: "rapp:invoke", id, args}` | `{type: "rapp:invoke:result", id, result \| error}` | Run the loaded agent's `perform(**args)`. The parent runs it via Pyodide (cloud mode) or the tethered brainstem. |
| `{type: "rapp:chat", id, message}` | `{type: "rapp:chat:result", id, reply \| error}` | Submit a chat turn (including the agent as a tool) and get the assistant reply. |
| `{type: "rapp:fetch", id, url, init}` | `{type: "rapp:fetch:result", id, status, body \| error}` | Proxy a fetch through the parent (uses parent's auth + CORS context). |

`id` is an opaque string the UI sends so it can match async replies to requests. The parent echoes it verbatim.

### 9.3 Minimal listening UI (in any rapp's `ui/index.html`)

```html
<script>
let cartridge = null;
window.addEventListener('message', (ev) => {
  if (ev.data && ev.data.type === 'rapp:cartridge') {
    cartridge = ev.data;
    onCartridgeLoaded();
  }
});
window.parent.postMessage({ type: 'rapp:get_cartridge' }, '*');

function onCartridgeLoaded() {
  // cartridge.rapp.id, cartridge.rapp.name, cartridge.context.user.login, etc.
  // Render the UI using these values instead of fetching them yourself.
}

function runAgent(args) {
  return new Promise((resolve, reject) => {
    const id = Math.random().toString(36).slice(2);
    const handler = (ev) => {
      if (ev.data && ev.data.type === 'rapp:invoke:result' && ev.data.id === id) {
        window.removeEventListener('message', handler);
        ev.data.error ? reject(new Error(ev.data.error)) : resolve(ev.data.result);
      }
    };
    window.addEventListener('message', handler);
    window.parent.postMessage({ type: 'rapp:invoke', id, args }, '*');
  });
}
</script>
```

A UI written this way works in three contexts without code changes:
- Standalone (no parent posts a cartridge → falls back to defaults).
- vBrainstem cloud mode (parent runs `perform()` in Pyodide).
- vBrainstem tether mode (parent forwards to the local brainstem's `/chat` and `/api/binder/agent`).

### 9.4 Why this lives in SPEC.md

The cartridge is part of the rapplication contract — UIs that adopt it get free upgrades whenever the parent runtime adds capabilities (better LLM routing, multi-agent tool loops, voice, etc.) without any change to the UI's own code. New parent runtimes (third-party brainstems, CI test harnesses, agent-driven testing tools) implement the same protocol and become drop-in hosts.

## 10. Reserved IDs

The following IDs are reserved by the platform and cannot be claimed by community publishers: `binder`, `dashboard`, `kanban`, `swarms`, `webhook`, `vibe_builder`, `learn_new`, `swarm_factory`, `senses`, `publish_to_rapp_store`. The reserved list lives in `scripts/lib_rapp.py`.

---

## 11. Workspace contract (per-rapp file scratchpad)

`schema: rapp-workspace/1.0`

Every installed rapplication on a local brainstem gets a **persistent, isolated workspace directory** where the user and the rapp can collaborate via files. This is the home for transcripts, vault dumps, CSVs, generated outputs, and anything else that doesn't fit a `perform()` keyword arg. It is distinct from the `.brainstem_data/<name>.json` convention, which is for rapp-private state the user does not touch.

### 11.1 Location and lifecycle

```
${BRAINSTEM_ROOT}/.brainstem_data/workspaces/<id>/
```

- **Created** by the binder on install (modes A and B both).
- **Preserved** on uninstall — workspaces are user data, not engine data.
- **Preserved** across version upgrades — same `<id>` keeps the same dir.
- **Isolated** — one rapp MUST NOT read or write into another's workspace. The brainstem enforces this; SPEC does not authorize cross-rapp access.
- **Path-traversal guarded** — `..` segments are rejected on every workspace operation.

Cloud mode (vBrainstem) emulates the same wire shape with a session-scoped, in-memory store. Files do not persist past the tab. Rapps SHOULD assume their workspace is ephemeral and re-prompt the user as needed.

### 11.2 Agent surface (Python)

Singletons access their workspace through a host-provided helper:

```python
from utils.workspace import workspace_dir

def perform(self, **kwargs) -> str:
    ws = workspace_dir()  # pathlib.Path | None
    if ws is None:
        return "no workspace available — run me from a tethered brainstem."
    transcript = ws / "transcript.txt"
    if not transcript.exists():
        return "drop a transcript.txt in my workspace and try again."
    return summarize(transcript.read_text())
```

`workspace_dir()` infers the rapp identity from the calling frame's module → singleton `__manifest__`. It returns `None` outside a brainstem (Pyodide, direct CLI, tests). Singletons MUST handle that case rather than crashing.

`utils.workspace` MAY also expose convenience helpers (`list_files()`, `read_text(name)`, `write_text(name, content)`, `request_files(prompt, patterns)`) — the canonical surface is left to the brainstem implementation, but `workspace_dir()` returning a `Path` is the minimum.

### 11.3 UI surface (cartridge protocol)

The cartridge envelope (§9.1) gains a `context.workspace` block:

```jsonc
{
  "context": {
    "workspace": {
      "available": true,
      "path": "/abs/path/to/.brainstem_data/workspaces/bookfactory",  // null in cloud mode
      "mode": "local" | "cloud",
      "file_count": 3
    }
  }
}
```

`path` is informational — UIs SHOULD NOT construct fs requests from it directly. All workspace ops go through cartridge messages:

| Message | Reply | Purpose |
|---|---|---|
| `{type: "rapp:workspace:list"}` | `{type: "rapp:workspace:list:result", files: [{name, size, mtime, mime}]}` | Enumerate files in the workspace. |
| `{type: "rapp:workspace:read", id, name}` | `{type: "rapp:workspace:read:result", id, content, encoding}` | Read a file. `encoding` is `"utf-8"` for text, `"base64"` for binary. |
| `{type: "rapp:workspace:write", id, name, content, encoding}` | `{type: "rapp:workspace:write:result", id, ok \| error}` | Create/overwrite a file. |
| `{type: "rapp:workspace:delete", id, name}` | `{type: "rapp:workspace:delete:result", id, ok \| error}` | Remove a file. |
| `{type: "rapp:workspace:request_files", id, prompt, patterns}` | `{type: "rapp:workspace:request_files:result", id, names: [...] \| cancelled: true}` | Ask the user to drop files matching a pattern. The host surfaces the prompt; the message resolves when the user supplies a file or dismisses. |
| `{type: "rapp:workspace:open_in_finder"}` | `{type: "rapp:workspace:open_in_finder:result", ok \| error}` | Reveal the workspace folder in the OS file browser. Local mode only — cloud returns `error: "not_supported"`. |

The host enforces isolation: `name` is treated as a relative leaf, not a path. Any `..` or absolute path is rejected with `error: "invalid_name"`.

### 11.4 User surface

The brainstem's UI SHOULD render a per-rapp **Workspace** affordance:

- a drop zone that writes uploaded files into the workspace dir;
- a file list with size and mtime;
- an "Open folder" button (local mode);
- an inbox of pending `request_files` prompts the rapp has issued.

The exact UX is the brainstem's call. The contract is that *something* lets the user put files in and see what's there — the rapp's UI relies on this surface existing alongside its own iframe.

### 11.5 Why this is in SPEC.md

The workspace contract is part of what a rapp can rely on when it installs. New brainstem implementations (third-party hosts, CI harnesses, agent-driven testing tools) implement the same wire shape and become drop-in hosts. UIs and singletons that opt in get free upgrades whenever the host adds capabilities (cloud sync, workspace sharing, audit logs) without code changes.

See [Proposal 0004](docs/proposals/0004-per-rapp-workspaces.md) for the design rationale.
