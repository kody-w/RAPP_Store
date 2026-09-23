# Rapplication Spec

Existing simple manifest: `rapp-application/1.0`. Complete chat-operated
application: `rapp-application/2.0` (§15; proposed extension).

A **rapplication** is a portable, self-describing, chat-operated application.
Its Python agent is the conversational entrypoint; a complete contract can
also declare components, jobs, providers, owned state, lifecycle and portable
results. Sections 1–13 retain the existing version-1 integration contract,
§14 retains native desktop distribution, and §15 adds complete applications
without rewriting existing catalog entries or artifacts.

A rapplication runs one of two ways. **In‑process** (`runtime: "agent"`, the default): its agent loads into the host brainstem's `agents/` dir — simple, fine for one or two. **Twin‑port** (`runtime: "twin"`): the rapplication **hatches into its own specialized brainstem‑twin on its own port**, carrying only its own agents and persona, and the host brainstem reaches it over **twin‑chat** instead of absorbing it (§13). Twin‑port is the answer to crowding: drop many `.egg`s into one global brainstem and each hatches as its own port‑addressable app — still fully usable from the global `brainstem.py`, but never tangling its agent namespace, tool list, or state.

An optional **native desktop distribution** (§14) supplements the agent/UI
integration with genuine macOS release downloads. A singleton does not install
the native application. This extension does not amend the Constitution or
assert Apple or RAPP/1 trust.

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
    *.egg                OPTIONAL  immutable state snapshots (zip cartridges); also the hatch cartridge for twin-runtime rapps (§13)
  twin/                  OPTIONAL  twin-runtime app (manifest.runtime == "twin", §13) — hatches on its own port
    soul.md              the specialized persona for this rapplication's twin
    agents/
      *_agent.py         the app's agents — loaded into the hatched twin, NOT the host brainstem
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
| `runtime` | string | no | `"agent"` (default) — the singleton loads **in‑process** on the host brainstem. `"twin"` — the rapplication **hatches into its own brainstem‑twin on its own port** and is reached over twin‑chat (§13). Use `"twin"` for multi‑agent apps and whenever a user may drop several rapps into one host. |
| `twin` | object | conditional | Required when `runtime == "twin"`. `{ "soul": "twin/soul.md", "agents": ["twin/agents/*_agent.py"], "port": "auto" }`. See §13. |
| `license` | string | no | SPDX or free-form. |
| `quality_tier` | string | no | `featured` / `official` / `verified` / `community` / `experimental` / `deprecated` / `private`. Submitters cannot self-declare above `community` (or `experimental` / `deprecated` — those are submitter-allowed self-marks). The receiver's `build_index_entry()` downgrades anything higher to `community`. The `private` tier is reserved for gated rapplications (§11); see that section for the rules that govern it. Tier promotions to `verified`, `official`, or `featured` happen via maintainer-merged PR only. |
| `access` | string | no | `"public"` (default) or `"private"`. When `"private"`, the rapplication is **gated** — its source files live in a private repo and `*_url` fields require an authenticated fetch. See §11. |
| `private_repo` | string | conditional | Required when `access == "private"`. `"<owner>/<repo>"` of the private repo holding the source. Every `*_url` field on the manifest and `index_entry` MUST point at `raw.githubusercontent.com/<owner>/<repo>/...`. |
| `desktop` | object | no | Optional `rapp-desktop/1.0` public native-release metadata (§14). Existing singleton/UI requirements remain; native submissions must use public federation. |

Other fields (`tagline`, `manifest_name`, `produced_by`, `optional_dependencies`,
`tool`, `runtime`, etc.) are tolerated and pass through to the catalog entry.
The manifest, not an unvalidated `index_entry.json` override, is their source
of truth. Receiver-owned `schema`, authoring paths (`agent`, `service`, `ui`),
`source`, `singleton_*`, `service_*`, `ui_*`, ID and quality-tier handling are
excluded or rebuilt. Integrity is recomputed rather than trusted from metadata.
`desktop` is a validated contract, not an unchecked metadata escape hatch.

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

**Gated entries (§11) are exempt from the receive-side rewrite and recomputation.** When `access == "private"`, the catalog cannot fetch the source bytes (the URL 404s for the catalog's own anonymous fetcher) and so cannot recompute SHAs or rewrite URLs. The submitter ships the canonical `*_url` (pointing at their `private_repo`) and the canonical `*_sha256`; the validator confirms the URL shape matches `private_repo` and otherwise treats the integrity fields as authoritative. Installers verify SHA after authenticated fetch.

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
3. `id` is snake_case and not a reserved name. `RESERVED_IDS` (`scripts/lib_rapp.py`) is the authoritative set: the repo-internal dirs (`scripts`, `tests`, `versions`, `eggs`, `senses`, `docs`, `apps`) plus the platform app-ids reserved forever per CONSTITUTION Art. VII (`binder`, `dashboard`, `kanban`, `swarms`, `webhook`, `vibe_builder`, `learn_new`, `swarm_factory`, `publish_to_rapp_store`, `twin_workshop`).
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
12. **Gated entries (§11)** relax rules 1, 5, and 6 — the validator cannot fetch the source bytes from a private repo and cannot AST-check what it can't read. For an entry with `access == "private"` the validator instead enforces:
    - `private_repo` is present and matches the regex `^[a-zA-Z0-9][a-zA-Z0-9_.-]*/[a-zA-Z0-9_.-]+$`.
    - Every `*_url` field on `manifest.json` and `index_entry.json` starts with `https://raw.githubusercontent.com/<private_repo>/`.
    - Every `*_url` is verified to return HTTP 404 on an anonymous fetch — the gate is real, not a misconfigured-public-repo. (The validator does NOT attempt authenticated fetches; the gate is the observable behavior.)
    - `*_sha256` fields are present for every `*_url` that is part of the install set (singleton, ui, service, organ, tools).
    - `quality_tier` defaults to `private` if unset; submitters cannot self-elevate gated entries above `private`. Promotion to `verified`/`official`/`featured` is reserved for the maintainers of the **private** repo, not the public catalog.

A failure on any rule rejects the submission with a specific error code (see `scripts/lib_rapp.py`).

## 7. Submission paths

A rapplication can enter the catalog in **three modes**, and any mode can be triggered from a local bundle, a public GitHub repo URL, or a private GitHub repo URL.

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

### Mode C — Gated federation (private source, public catalog)

A federation entry whose `singleton_url` (and other `*_url` fields) point at a **private** GitHub repo. The catalog publishes the existence and metadata of the rapplication; the source bytes are gated behind `raw.githubusercontent.com`'s authenticated-only access for private repos. The catalog **does not** carry, store, or proxy any auth credentials — it merely documents the gate via the `access: "private"` flag and `private_repo` field. The full contract lives in §11.

```json
{
  "id": "cockpit",
  "version": "1.0.0",
  "access": "private",
  "private_repo": "kody-w/RAPP_Store_Private",
  "singleton_url": "https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/singleton/cockpit_agent.py",
  "singleton_sha256": "c77195ef84de42e4c1a13c509d0262e6c44c1ee2e27abcb26673bec40eb753ef",
  "auth_hint": "gh auth token  →  curl -H \"Authorization: Bearer $TOKEN\" <singleton_url>"
}
```

Mode C inherits Mode B's `source.type = "federation"` block but replaces `commit_sha` resolution (which would fail anonymously) with a static URL-shape check. Use Mode C when the rapplication should be discoverable on the public catalog but its source must remain private.

### Submission triggers

All future submissions MUST use the `[RAPP]` issue receiver and maintainer
approval front door. Release uploads and direct catalog PRs alone are not
submissions. The issue can be created through:

1. **`@rapp/publish-to-rapp-store` agent (local CLI)** — call its `submit_bundle <path>` (mode A) or `submit_repo <github-url>` (mode B). The agent validates locally, then opens a GitHub issue with a structured payload.
2. **Issue template** — open an issue with the `[RAPP]` template, fill in either *(a)* a bundle attachment or *(b)* a repo URL field. The receiver workflow handles the rest.
3. **The Pages submission UI** (`submit.html`) — produces the same structured
   `[RAPP]` issue. The former direct-PR catalog-edit path is not a submission
   lane. Native releases use federation, not an inline bundle.

### Receiver flow

1. Workflow parses the issue payload (bundle attachment OR `repo: <url>` field).
2. **Mode A:** download the zip, extract, validate per §6.
   **Mode B:** fetch `manifest.json` and the singleton from `raw.githubusercontent.com`, validate per §6 (file existence checks become HTTP GETs).
3. On pass: write pending state (and `staging/<id>/` for mode A), commit and
   confirm publication to current `main`, **then** comment
   `Validated. Awaiting maintainer approval.` and label `pending-review`.
4. Maintainer adds `approved` label.
5. Approval workflow:
   - **Mode A:** promote `staging/<id>/` → `<id>/`, recompute integrity, merge into `index.json`.
   - **Mode B:** revalidate against the current catalog, resolve `commit_sha`,
     recompute integrity from the fetched files, and merge a federation entry
     into `index.json`. No files copied. Native entries additionally retain
     the exact staged issue/manifest/metadata pins and refresh scoped v1
     discovery (§14); a moved source or stale version requires resubmission.
6. Commit, comment `Approved. Available at <singleton_url>`, close issue.

Both issue mutation workflows share `rapp-store-state` concurrency and
explicitly check out **current `main` when the serialized job starts**, not
the issue event's earlier SHA. Pending updates replace only the matching
issue record; approval removes only that record. Unrelated pending items
must survive processing, reprocessing and promotion.

Validation/promotion failures fail the workflow. Success reports, labels and
closure require successful state publication, not merely local validation.
Push retries retry the same commit without rebasing stale catalog/pending
JSON; exhausted retries fail explicitly. A non-fast-forward or uncertain push
requires inspection and a fresh issue event against current main.
Actions concurrency is not a durable event queue: cancelled pending runs
also require a normal retrigger.

To recover an unpromoted issue after a failed/lost pending-state publication:
remove a stale `approved` label, edit or reopen the same `[RAPP]` issue, wait
for a new successful receiver run and the correct pending record on main,
then apply `approved` again. Verify the new approval run succeeds, the catalog
entry is correct, and unrelated pending/catalog entries remain intact.
Do not patch `index.json` or `staging/_pending.json` by hand. When deploying
a workflow fix, create fresh issue/label events; rerunning a historical run
can retain its old workflow definition.

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

### 9.5 MCP is the canonical transport (Chat Is The Only Wire)

The cartridge host (above) and the `proxyBrainstemFetch` shim in `vbrainstem.html` both realize one rule: **Chat Is The Only Wire** — every capability reaches a rapplication through `/chat`, never a bespoke endpoint. MCP ([Model Context Protocol](https://github.com/kody-w/rapp-mcp)) is the now-canonical wire-level transport for that rule. An MCP client is a **Layer-2 caller of `/chat`**, exactly like the cartridge host's `rapp:chat` message and the vBrainstem proxy — it is *transport*, not a new unit or taxonomy. Rapplications stay the only catalog artifact; MCP just carries the call.

Two reference shims (`rapp-mcp-spec/1.0`) live in [`kody-w/rapp-mcp`](https://github.com/kody-w/rapp-mcp):

- **`rapp_mcp.py`** — serves drop-in `*_agent.py` singletons (the same files this catalog distributes) as MCP tools, so any MCP host can invoke them.
- **`rapp_brainstem_mcp.py`** — bridges a *running* brainstem over `/chat` to any MCP host, so the whole conversation surface (agents + memory + senses) is reachable as one MCP endpoint.

## 10. Reserved IDs

The following IDs are reserved by the platform and cannot be claimed by community publishers: `binder`, `dashboard`, `kanban`, `swarms`, `webhook`, `vibe_builder`, `learn_new`, `swarm_factory`, `senses`, `publish_to_rapp_store`. The reserved list lives in `scripts/lib_rapp.py`.

---

## 11. Gated rapplications (`access: "private"`)

`schema: rapp-gated/1.0`  (additive layer over `rapp-application/1.0`)

A **gated rapplication** is a rapplication whose catalog entry is public but whose source files live in a private GitHub repo. The catalog publishes the existence, shape, and metadata of the rapp; GitHub's raw-content service publishes the bytes only to callers with read access on the private repo.

The pattern is **public discovery, private substance**.

### 11.1 The contract

A catalog entry IS a gated rapplication iff `access == "private"`. When that holds:

1. `private_repo` is set to `"<owner>/<repo>"` and the repo is private on GitHub.
2. Every `*_url` field on `manifest.json` and `index_entry.json` MUST start with `https://raw.githubusercontent.com/<private_repo>/`.
3. Anonymous `GET` on every `*_url` MUST return HTTP 404 (this is the gate).
4. `*_sha256` is present for every `*_url` that participates in install.
5. The bundle layout (§1) and singleton contract (§4) still apply on the **inside** of the private repo. The submitter is responsible for keeping the private bundle valid; the public catalog only stores metadata.
6. `quality_tier` is `private` (the default for gated entries) unless promoted by the maintainer of the private repo.

The public catalog's validator enforces 1–4 (see §6 rule 12). It does NOT validate the singleton AST — it has no way to fetch the source. That validation responsibility moves to whoever holds the private repo.

### 11.2 The gate

The gate is **not catalog-side**. It is GitHub's. When an unauthenticated client requests a path under `raw.githubusercontent.com/<private-owner>/<private-repo>/...`, GitHub returns HTTP 404 — indistinguishable from "the path does not exist." When a client attaches `Authorization: Bearer <pat>` and the PAT has at least *Contents: read* on the private repo, GitHub returns the bytes with HTTP 200.

The catalog never sees the bytes. The catalog never sees the PAT. The catalog merely documents the existence of the gate via the `access: "private"` flag.

This means:
- Revocation is **GitHub's responsibility**. Remove a collaborator from the private repo → they lose access immediately.
- Audit is **GitHub's responsibility**. The private repo's audit log records every authenticated raw fetch.
- The catalog is operationally read-only with respect to access decisions.

### 11.3 Installer behavior

An installer (brainstem, `gh-rapp` CLI, vBrainstem) MUST:

1. Inspect `access` on the entry. If `access != "private"` (including missing), fetch normally.
2. If `access == "private"`, look up a token for `private_repo` from the user's local credential store. Conventional sources:
   - `gh auth token` (the GitHub CLI's stored token).
   - `GITHUB_TOKEN` environment variable.
   - A `~/.netrc` machine entry for `raw.githubusercontent.com`.
   - Brainstem-specific keychain entries (`brainstem keychain set rapp-store/<private_repo>`).
3. If a token is found, attach `Authorization: Bearer <token>` to every `*_url` fetch.
4. If no token is found, surface a clear error referencing `auth_hint` (see §11.4) — do NOT fall through to the unauthenticated fetch and return a "404, source missing" message that hides the auth root cause.
5. After fetching the bytes, hash and verify against the catalog's `*_sha256`. A mismatch is a hard install failure (catalog drift from the private repo).
6. After install, **discard the token**. The rapplication runs without it. If the rapp itself needs GitHub access, it acquires its own token through its own surfaces.

### 11.4 Author surfaces (`auth_hint`, `access_note`)

A gated entry SHOULD carry two human-readable fields aimed at the installer's user when the auth lookup fails:

- `auth_hint` — short, command-shaped. e.g. `"gh auth token  →  curl -H \"Authorization: Bearer $TOKEN\" <singleton_url>"`. The installer surfaces this when it can't find a token automatically.
- `access_note` — a paragraph describing who is expected to have access and how to request it. Lives in `manifest.json`; brainstems may surface it in the catalog UI even before install.

Neither field is enforced. They exist so that the human downstream of an `access: "private"` denial gets actionable information instead of a bare 404.

### 11.5 Security boundaries (what this is NOT)

- **Not code-protection.** A user with access can copy the source out trivially. The gate is "did you have read access at fetch time," not "is this code unrunnable without a key." Use code signing or runtime DRM if you need the latter.
- **Not transport encryption beyond TLS.** The bytes ride normal HTTPS. Anyone who can MITM your TLS can see the bytes. (This is GitHub's threat model, not ours.)
- **Not a license.** Whether a viewer of the source is allowed to use, modify, or redistribute it is a question for the rapp's `LICENSE` and the org's contributor agreements, not for the catalog.
- **Not a multi-tier auth model.** There's `public` and `private`. Org-scoped or team-scoped distinctions are expressed by repo membership on the private side, not by the catalog. If you need that, run multiple private repos.
- **Not catalog enforcement.** The catalog is an honest broker — it documents the gate. The installer + GitHub are the enforcement layer.

### 11.6 Worked example

The first gated rapplication is `@wildhaven/cockpit` (landed 2026-05-03):

```json
{
  "id": "cockpit",
  "name": "Cockpit",
  "version": "1.0.0",
  "manifest_name": "@wildhaven/cockpit",
  "publisher": "@wildhaven",
  "summary": "Local-first control plane for SSH-reachable hosts.",
  "category": "platform",
  "tags": ["rapplication", "cockpit", "local-first", "ssh", "private"],

  "access": "private",
  "private_repo": "kody-w/RAPP_Store_Private",
  "quality_tier": "private",

  "singleton_url":     "https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/singleton/cockpit_agent.py",
  "singleton_sha256":  "c77195ef84de42e4c1a13c509d0262e6c44c1ee2e27abcb26673bec40eb753ef",
  "ui_url":            "https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/ui/index.html",
  "ui_sha256":         "c87f637e83fa9ad93f44c75ddb07edd5882951bda8ce73174ca5e44cd17b47c6",
  "organ_url":         "https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/organs/cockpit_organ.py",
  "organ_sha256":      "bcf456228f17a18ed72d75f1ac4f482315920b1f7a58bf6e8a8c3e607402a038",

  "auth_hint":   "gh auth token  →  curl -H \"Authorization: Bearer $TOKEN\" <singleton_url>",
  "access_note": "Source files live in kody-w/RAPP_Store_Private. Unauthenticated raw fetches return HTTP 404. With a PAT scoped for read on the private repo, every URL returns 200."
}
```

Verification (anyone can run these):

```bash
# Catalog presence is public:
curl -fsSL https://raw.githubusercontent.com/kody-w/RAPP_Store/main/index.json \
  | jq '.rapplications[] | select(.id=="cockpit")'

# Source is gated:
curl -sSL -o /dev/null -w "%{http_code}\n" \
  https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/singleton/cockpit_agent.py
# → 404 (anonymous)

curl -sSL -H "Authorization: Bearer $(gh auth token)" -o /dev/null -w "%{http_code}\n" \
  https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/singleton/cockpit_agent.py
# → 200 (with PAT having read on RAPP_Store_Private)
```

### 11.7 Why this is in SPEC.md

Without `access` as a first-class field, every gated rapplication has to invent its own access mechanism — bespoke install scripts, custom token formats, side-channel auth. By making `access` part of the catalog contract, the catalog becomes a uniform discovery layer for **everything** — public, private, customer-scoped, org-scoped — under one schema and one auth pattern.

The pattern is also substrate-aligned: GitHub already runs the auth layer (PATs with fine-grained scopes), the storage layer (private repos), and the delivery layer (`raw.githubusercontent.com`). Building on that gets us no servers to operate, no relays to keep secure, no custom token formats, and no new failure modes — the gate is exactly what GitHub already does for every private-repo fetch.

See [Proposal 0005](docs/proposals/0005-gated-rapplications.md) for the design rationale.

---

## 12. Workspace contract (per-rapp file scratchpad)

`schema: rapp-workspace/1.0`

Every installed rapplication on a local brainstem gets a **persistent, isolated workspace directory** where the user and the rapp can collaborate via files. This is the home for transcripts, vault dumps, CSVs, generated outputs, and anything else that doesn't fit a `perform()` keyword arg. It is distinct from the `.brainstem_data/<name>.json` convention, which is for rapp-private state the user does not touch.

### 12.1 Location and lifecycle

```
${BRAINSTEM_ROOT}/.brainstem_data/workspaces/<id>/
```

- **Created** by the binder on install (modes A and B both).
- **Preserved** on uninstall — workspaces are user data, not engine data.
- **Preserved** across version upgrades — same `<id>` keeps the same dir.
- **Isolated** — one rapp MUST NOT read or write into another's workspace. The brainstem enforces this; SPEC does not authorize cross-rapp access.
- **Path-traversal guarded** — `..` segments are rejected on every workspace operation.

Cloud mode (vBrainstem) emulates the same wire shape with a session-scoped, in-memory store. Files do not persist past the tab. Rapps SHOULD assume their workspace is ephemeral and re-prompt the user as needed.

### 12.2 Agent surface (Python)

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

### 12.3 UI surface (cartridge protocol)

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

### 12.4 User surface

The brainstem's UI SHOULD render a per-rapp **Workspace** affordance:

- a drop zone that writes uploaded files into the workspace dir;
- a file list with size and mtime;
- an "Open folder" button (local mode);
- an inbox of pending `request_files` prompts the rapp has issued.

The exact UX is the brainstem's call. The contract is that *something* lets the user put files in and see what's there — the rapp's UI relies on this surface existing alongside its own iframe.

### 12.5 Why this is in SPEC.md

The workspace contract is part of what a rapp can rely on when it installs. New brainstem implementations (third-party hosts, CI harnesses, agent-driven testing tools) implement the same wire shape and become drop-in hosts. UIs and singletons that opt in get free upgrades whenever the host adds capabilities (cloud sync, workspace sharing, audit logs) without code changes.

See [Proposal 0004](docs/proposals/0004-per-rapp-workspaces.md) for the design rationale.

## 13. Twin-port runtime (hatched rapplications)

`runtime: "twin"`

### 13.1 The problem this solves

The §4 model installs a rapplication's agent into the **host** brainstem's `agents/` dir. That is
fine for one or two. But the store exists so a user can drop **many** rapplications into one global
`brainstem.py` — and when every rapp's agents pile into one `agents/` dir they crowd the agent
namespace, bloat the single LLM tool list, blur which tool belongs to which app, and tangle their
state. There is no isolation and no organization.

**Twin-port runtime fixes this.** A `runtime: "twin"` rapplication does not load into the host. It
**hatches into its own brainstem-twin on its own port** — a dedicated brainstem instance that
carries *only* that rapplication's agents and a persona specialized for it — and the global
brainstem reaches it over **twin-chat**. Drop ten `.egg`s and you get ten isolated, port-addressable
apps, each a focused twin, all still usable from the one global brainstem. Nothing crowds.

### 13.2 The bundle (`twin/`)

A twin-runtime rapplication declares `"runtime": "twin"` and ships a `twin/` directory:

```
<id>/
  manifest.json          runtime: "twin", twin: { soul, agents, port }
  twin/
    soul.md              REQUIRED  the specialized persona for this app's twin
    agents/
      *_agent.py         REQUIRED  the app's agents (one or many) — loaded into the twin, not the host
    requirements.txt     OPTIONAL  extra deps for the twin
    VERSION              OPTIONAL  kernel/app version pin
  eggs/
    <id>.egg             the hatch cartridge: a zip of twin/ + manifest + initial state
```

The `.egg` is the **hatch unit** — pull it by URL (see `rapp-egg-hub`) and hatch it locally. The host
brainstem's own `agents/` dir is never written.

### 13.3 The hatch

Dropping an `.egg` (or installing a `runtime:"twin"` rapplication) into a global brainstem **hatches** it:

1. **Allocate a free port** — the hatcher picks the next free port (e.g. `7073`, `7074`, … — the
   same shape as a running brainstem fleet).
2. **Materialize an isolated twin root** —
   `${BRAINSTEM_ROOT}/.brainstem_data/twins/<id>/` containing the rapp's `agents/`, its `soul.md`,
   its own workspace, and its own `.brainstem_data/`. Fully isolated from the host and from sibling twins.
3. **Boot a brainstem there** — the same `brainstem.py` / `rapp-brainstem-sdk`, bound to the
   allocated port, loading **only** that twin's agents.
4. **Register it** in the twins registry (§13.4).

The host's agent namespace, tool list, and state are untouched. Eviction reverses it: stop the
process, drop the registry entry; the twin root persists (state is preserved) unless purged.

### 13.4 The twins registry (discovery)

`${BRAINSTEM_ROOT}/.brainstem_data/twins.json`:

```json
{
  "schema": "rapp-twins/1.0",
  "twins": [
    { "id": "spine_dag", "name": "SpineDAG", "port": 7073, "pid": 41021,
      "status": "running", "rappid": "<uuid>", "chat": "http://127.0.0.1:7073/chat",
      "soul": "SpineDAG — a DAG-reasoning specialist", "hatched": "2026-05-26T01:00:00Z" }
  ]
}
```

The global brainstem reads `twins.json` to know which rapplications are live and how to reach each
one. This is the routing table for federation (§13.5) and the source of truth for the zoo (§13.6).

### 13.5 Federation via twin-chat (the host still uses it)

The global brainstem reaches a hatched rapplication over the neighborhood **twin-chat** protocol
(`rapp-twin-chat/1.0` — see [rapp-neighborhood-protocol](https://github.com/kody-w/rapp-neighborhood-protocol)),
same-host transport `5a-http` to the twin's `chat` endpoint:

- **`say`** → the twin's `/chat`: conversational, routed into the twin's *specialized* agents and
  answered as that app would.
- **`console`** → operate the twin (invoke a specific agent / method). For non-local reach it is
  sealed + token-gated per the neighborhood spec; same-host localhost may go in the clear.

So when the user is chatting with the global brainstem and asks for something an app handles, the
brainstem **delegates over twin-chat** — *"ask the SpineDAG twin to collapse this graph"* → `say` to
`http://127.0.0.1:7073/chat` → relay the reply — and that app's agents **never enter the global
brainstem's tool list**. The global brainstem is a hub/router over a little neighborhood of
specialized twins, not a junk drawer of everyone's agents.

A twin MAY also advertise itself to the global brainstem the same way any neighbor does (host a
peer, register its `rappid`); on one machine the `twins.json` entry is enough.

### 13.6 Lifecycle (the zoo)

`hatch` · `start` · `stop` · `list` · `evict` — managed by
[rapp-zoo](https://github.com/kody-w/rapp-zoo), the local twin-estate keeper. Drop an `.egg` →
**hatch**; the twin keeps running across host restarts if you want it always-on (it's just another
brainstem on a port). `list` reads `twins.json`; `stop`/`evict` tear a twin down. Multiple `.egg`s →
multiple twins, each its own port and persona, all enumerable and all reachable.

### 13.7 The hatcher (`rapplicationloadingagent` evolves)

The loader agent no longer copies a rapp's agents into the host's `agents/` dir for `runtime:"twin"`
rapps. Instead it **hatches** (§13.3) and exposes:

| Method | Does |
|---|---|
| `hatch(egg \| id)` | allocate port → materialize twin root → boot → register |
| `stop(id)` / `evict(id)` | tear the twin down (state kept unless purged) |
| `list()` | the live twins from `twins.json` |
| `ask(id, text)` | a twin-chat `say` to that twin → its reply (how the host talks to an app) |

`runtime:"agent"` rapps keep the legacy in-process path unchanged.

### 13.8 The cartridge protocol still applies

A twin-runtime rapp's UI (§9) talks to **its twin** rather than the host: the parent forwards
`rapp:invoke` / `rapp:chat` to the twin's `/chat` (the `twins.json` `chat` URL) instead of the host
brainstem. Everything in §9 is unchanged from the UI's point of view — it just lands in the app's own
specialized twin.

### 13.9 Why this is in SPEC.md

Twin-port hatching is part of the rapplication contract: a `runtime:"twin"` rapp is guaranteed to
hatch into an **isolated, port-addressable, twin-chat-reachable** instance on any conforming host. So
an author can ship a whole multi-agent app as one `.egg`, and a user can drop a dozen of them into one
global brainstem without it degrading into an unnavigable pile of agents. Builds on
[rapp-neighborhood-protocol](https://github.com/kody-w/rapp-neighborhood-protocol) (twin-chat +
§5a transports), [rapp-brainstem-sdk](https://github.com/kody-w/rapp-brainstem-sdk) (the per-twin
headless brainstem), [rapp-egg-hub](https://github.com/kody-w/rapp-egg-hub) (`.egg` cartridges), and
[rapp-zoo](https://github.com/kody-w/rapp-zoo) (hatch/start/stop/list).

## 14. Optional native desktop distribution

`desktop.schema == "rapp-desktop/1.0"` is an optional extension for **public
federated macOS releases**, not a replacement for the required singleton and
UI. Absence preserves existing validation/install behavior. Presence is
accepted only with complete, verified public release references. A native
bundle cannot be submitted inline, copied into `apps/`, or mirrored under
`api/`; use the existing source repository and existing catalog ID.

The exact structural schemas are
[`schemas/desktop.schema.json`](./schemas/desktop.schema.json) and
[`schemas/desktop-evidence.schema.json`](./schemas/desktop-evidence.schema.json).
`scripts/lib_rapp.py` / `scripts/lib_desktop.py` also enforce the cross-field,
continuity and network/byte checks below. Unknown keys **inside** these
versioned contracts are rejected.

### 14.1 Manifest and catalog fields

All fields in this table are required when `desktop` is present:

| Field | Contract |
|---|---|
| `schema` | Exactly `rapp-desktop/1.0`. |
| `platform` | Exactly `macos`. |
| `minimum_os` | macOS `MAJOR.MINOR[.PATCH]`, canonical numeric components (for example `14.0`). |
| `bundle_id` | Stable reverse-DNS identifier, at least three components. Cannot change for an existing native ID. |
| `source` | Exactly `{repo, commit_sha}`. `repo` is the same canonical `owner/repo` as federation; `commit_sha` is the full lowercase 40-hex **native-build** commit. |
| `release_tag` | Exactly `v<manifest.version>`; version is canonical `MAJOR.MINOR.PATCH`. The public tag must resolve to `desktop.source.commit_sha`. |
| `artifacts` | One to four objects as below. Each `(arch, format)` pair must be unique; `universal` and implicit architecture are not supported. |
| `prerequisites` | 1–20 nonempty plain-text items, at most 1,000 characters each. Disclose required tools/models, OS permissions and optional integrations. Use an explicit “none beyond …” item if appropriate. |
| `privacy` | Nonempty plain text, at most 4,000 characters. Describe capture/permissions, storage and any remote data transfer or optional provider. |
| `setup` | 1–20 nonempty plain-text steps, at most 1,000 characters each. Explain installing the native application and granting appropriate permissions. |
| `agent_integration` | Nonempty plain text, at most 4,000 characters. Explain what the secondary singleton/UI does and its prerequisites. It must not claim a `.py` drop installs the native application. |

Each `artifacts[]` object has exactly:

| Field | Contract |
|---|---|
| `arch` | `arm64` or `x86_64`. |
| `format` | `dmg` or `zip`. ZIPs contain a signed, stapled, notarized `.app`; they are not unsigned-source or Python integration bundles. |
| `url` | Exactly `https://github.com/<source.repo>/releases/download/<release_tag>/<id>-<version>-<arch>.<format>`. |
| `bytes` | Exact positive integer size of the final downloadable archive, at most 1,073,741,824 bytes (1 GiB). Booleans/floats are not integers here. |
| `sha256` | SHA-256 of those final bytes: 64 lowercase hex characters. |
| `evidence` | Exactly `{url, bytes, sha256}` for the public evidence JSON. URL uses the same repo/tag. DMGs accept `<id>-<version>-<arch>.evidence.json` or `<id>-<version>-<arch>.evidence.<sha256>.json`; ZIPs accept `<id>-<version>-<arch>.zip.evidence.json` or `<id>-<version>-<arch>.zip.evidence.<sha256>.json`. If present, the full 64-lowercase-hex filename suffix MUST equal `evidence.sha256`. Exact positive byte count is at most 262,144 (256 KiB); SHA-256 hashes the exact evidence file bytes. |

No URL credentials, HTTP/file/custom schemes, alternate owner/repository,
mutable `latest` URLs, percent-encoded aliases, traversal, query strings,
fragments or ports are allowed in these references. Metadata never contains
tokens or signing credentials. Gated/private native releases are not
supported by this initial extension.

The singleton's literal `__manifest__.version` must equal the native manifest
version. On update, version must beat the **current** catalog and the publisher,
existing federation repository and native bundle ID must remain unchanged.
An existing native entry cannot silently remove `desktop`.

**Immutable evidence corrections:** never overwrite a published evidence
asset. If a report needs correction, regenerate the genuine report, serialize
its final bytes, calculate that file's SHA-256, and upload a **new**
content-addressed evidence filename in the same release. Update the source
manifest's evidence URL/bytes/hash through a new metadata commit and the
`[RAPP]` receiver/approval flow; do not rewrite old reports, the native archive,
or its tag. The suffix is the evidence digest, not the archive digest or a
hash of normalized/re-serialized JSON. This does not relax existing catalog
version rules, staged-entry review, signing checks or exact app-path binding.
Malformed paths remain invalid even when the file has a valid digest name.

### 14.2 Evidence report (publisher-supplied, inspectable)

The referenced JSON object has exactly:

- **`schema`:** `rapp-desktop-evidence/1.0`.
- **`subject`:** exactly `{id, version, bundle_id, arch, url, bytes, sha256}`,
  matching this manifest and the **final** downloadable DMG or ZIP artifact.
- **`source`:** exactly the manifest's `desktop.source`.
- **`workflow_run`:** `https://github.com/<source.repo>/actions/runs/<positive-integer>`.
  The anonymous GitHub run API must report that exact URL/repository,
  `head_sha == desktop.source.commit_sha`, `status: completed`,
  `conclusion: success`. This may be a public build or artifact-verification
  run; signing/notarization can remain local and Xcode-managed. It does not
  require exporting Apple signing credentials to third-party CI.
- **`signing`:** exactly `{team_id, authority, architectures, codesign_details,
  codesign_verify}`. Team ID is ten uppercase alphanumeric characters.
  Authority is `Developer ID Application: <name> (<team_id>)`.
  `architectures` is the one-element array matching the artifact's arch.
  `codesign_details` is actual `codesign -dvvv` output containing matching
  `Identifier=`, `TeamIdentifier=`, `Authority=` lines and hardened-runtime
  information (`CodeDirectory` flags must contain the `0x10000` hardened
  runtime bit and name `runtime`, not merely mention it elsewhere).
  `codesign_verify` is a command report from
  `codesign --verify --deep --strict --verbose=2` on the released application;
  output must include “valid on disk” and “satisfies its Designated Requirement”.
- **`notarization`:** depends on the archive format:
  - **DMG:** exactly `{submission_id, submitted_sha256, log}`.
    Submission ID is the real UUID. `log` is the unmodified JSON from
    `xcrun notarytool log`, with matching `jobId`, `status: Accepted`,
    integer `statusCode: 0`, exact DMG `archiveFilename`,
    `sha256 == submitted_sha256`, and `issues: null` or `[]`.
    Additional Apple log fields are retained. The submitted hash refers to
    the **pre-staple upload** and can differ from final `subject.sha256`;
    never falsify the Apple log to make them equal.
  - **ZIP:** exactly `{method: "stapled-app", app_path, bundle_id, version,
    minimum_os}`. `app_path` is the enclosed top-level `.app` basename
    (for example `RAPP Shot.app`), at most 200 characters, without traversal
    or path separators. Bundle ID, version and minimum OS must match the
    manifest and the app's Info.plist. `codesign_details` must name
    `<app_path>/Contents/MacOS/`; codesign verification and Gatekeeper
    output must name that same application. Stapler's `Processing:` line
    must name the exact `.app` basename, not a similarly named `.app.zip`;
    stapler output must name the
    **app**, not the ZIP. This path supports an app notarized/stapled by
    Xcode-managed distribution without requiring a notarytool container log.
    No ZIP submission UUID, upload hash, fabricated container ticket or ZIP
    staple is required or permitted.
- **`gatekeeper`:** command report from `spctl --assess --type execute
  --verbose=4` on the released application. Requires accepted output,
  `source=Notarized Developer ID`, and exact application-path binding for
  ZIP evidence. Some genuine macOS/Xcode versions omit `origin=`; absence
  is accepted, but an emitted origin must match the codesign authority.
  Developer ID authority and matching `TeamIdentifier` remain mandatory in
  the codesign report. Never synthesize an origin line to satisfy validation.
- **`stapler`:** command report from `xcrun stapler validate` on the
  final DMG **or the enclosed app for ZIP distribution**, including
  “The validate action worked!”. ZIP archives cannot themselves be stapled.

Every command report is exactly `{exit_code: 0, output: "<actual combined
command output>"}`. A success Boolean or an invented string is not evidence.
The issuer must capture the reports from the actual released build;
reviewers should independently inspect version, bundle ID, minimum OS and
architecture from the mounted/unzipped application and reproduce the macOS
checks. The ZIP's independent `subject.sha256`/`bytes` still bind the final
download exactly; app-staple evidence does not replace archive integrity.

**Important trust limit:** the receiver verifies public references, report
bindings, and actual downloaded byte hashes. It does **not** authenticate
Apple logs cryptographically, mount/unpack/execute native archives, or certify the truth of a
publisher's reports. The storefront calls these *publisher release reports*;
macOS/Gatekeeper performs native signature checks. This is neither Apple
certification by the Store nor RAPP/1 acceptance. Native entries cannot
self-supply `signed`, `notarized`, `trust`, `rappid`, `parent_rappid`,
`identity`, `wire_contract`, `ecosystem_acceptance`, `egg_url` or `hatcher_url`
through this extension.

### 14.3 Validation, staging and approval

1. Local `validate_dir(..., fetcher=..., artifact_fetcher=...)` and public
   `validate_federation(...)` apply the same native contract and verification.
   A local `index_entry.desktop`, if present, must equal the manifest.
   Native `validate_zip` / bundle submissions fail with
   `E_DESKTOP_FEDERATION_ONLY`. Here `validate_zip` means the inline
   integration-submission bundle validator, not the native artifact
   verifier: native release ZIPs are accepted through federation references.
2. Federation resolves a full **manifest** commit and fetches integration
   files from it. Failure to resolve is fatal for native entries (legacy
   federation retains best-effort behavior). A mutable-ref manifest must
   equal the immutable commit's bytes.
3. GitHub's public stable release, tag target, asset names/URLs/sizes/SHA256
   digests and successful build/verification-run references must match. Evidence bytes
   are fetched and hash/size verified; report subjects and outputs must
   match. Only then are native archives streamed and checked against exact byte/hash
   pins. No native files are persisted.
4. Existing 5 MiB bundle, 200 KiB singleton and 500 KiB UI caps are unchanged.
   Native DMGs/ZIPs use a separate 1 GiB cap each, at most four artifacts, 64 KiB
   chunks, 30-second socket timeout and 900-second per-download budget.
   Evidence is capped at 256 KiB; other metadata fetches at 5 MiB.
   Fetchers are injectable; unit tests use tiny inert byte fixtures, never
   network downloads. No tokens are read or forwarded. HTTPS redirects
   are constrained to GitHub and its release-asset CDN hosts.
5. The `[RAPP]` receiver stages the validated entry and issue payload
   fingerprint. Native submission metadata must match fetched
   ID/version/publisher; the manifest is authoritative for `desktop`.
6. Approval checks the current catalog, exact issue payload, staged
   manifest commit and complete entry, and repeats release/evidence/archive
   verification. Any stale version, changed source/tag/artifact or
   changed metadata requires resubmission rather than silent promotion.

To avoid self-reference, the native build/release commit and the later
manifest-metadata commit may differ. `desktop.source.commit_sha` identifies
the former; catalog `source.commit_sha` identifies the latter. Prefer the
full latter commit in the issue's `source.ref`. Native `singleton_url`,
`ui_url` and `service_url` use that immutable manifest commit even when the
submitted ref was a branch.

### 14.4 Storefront and v1 discovery

Validated native entries show architecture-specific macOS downloads,
full artifact hashes/bytes, evidence links, prerequisites, privacy and
setup. ZIP downloads explicitly explain: double-click the ZIP in Finder,
drag the extracted `.app` to Applications, and launch it from Applications.
The Python singleton/UI is secondary integration, never a native
installer. Invalid native metadata offers no download fallback.
Non-native entries use **explicit** egg/hatcher references only; kind
`rapp` does not imply generated artifacts exist.

Approval invokes a scoped metadata-only projection into
`api/v1/rapplication/<id>.json` and that ID's `api/v1/index.json` row.
These retain existing v1 schemas with `distribution: desktop`, `desktop`,
source and integration metadata. They intentionally omit invented
`rappid`, lineage, sprites, eggs, hatchers and install shell commands.
Existing unrelated records/files and index metadata are preserved.

For an already approved catalog entry, an explicit maintenance refresh is:

```bash
python3 scripts/build_pokedex_api.py --native-only --ids <approved-native-id>
```

This command never fetches releases or changes the canonical catalog.
Do not run the global legacy producer to manufacture missing federation
artifacts. No Zoo v2 path is involved.

The rationale and owner-approval boundary are in
[Proposal 0006](./docs/proposals/0006-native-desktop-distribution.md).
The existing four Fable5 catalog IDs remain `rapp_crispy`, `rapp_rewind`,
`rapp_shot`, `rapp_voice`; RAPP Tools is infrastructure, not another entry.
No constitutional amendment is made by this optional extension.

## 15. Complete chat-operated applications

[Proposal 0007](./docs/proposals/0007-chat-operated-rapplications.md) introduces
the explicit `rapp-application/2.0` contract and mandatory `local-docker/1`
feature. The root catalog remains `rapp-store/1.0`; existing simple entries,
native release descriptors, historical artifacts and Zoo v2 remain intact.
This is an experimental implementation proposed for review, not a catalog
admission, externally ratified protocol or automatic release.

### 15.1 Complete source contract

[`schemas/application.schema.json`](./schemas/application.schema.json)
describes the manifest. Version 2 retains `id`, `name`, `version`, `publisher`,
`summary`, `category`, `tags`, `agent`, and optional `ui`, with:

| Declaration | Meaning |
|---|---|
| `agents` | The exact file-locked BasicAgent entrypoints; `agent` names one |
| `runtime` | Unchanged Grail repository, full commit and version |
| `files` | Complete safe relative-path → SHA-256 map, not just singleton bytes |
| `requires` | Mandatory feature versions; unknown features refuse |
| `profiles`, `permissions`, `capabilities` | Explicit requirements, never silently discarded |
| `dependencies` | Exact application identity/version/package hash, or `[]` |
| `services` | Locked definitions and immutable images, or `[]` |
| `state` | Version, preserving behavior and locked initial seeds |
| `lifecycle` | Qualified install/upgrade/uninstall/recovery behavior |
| `providers` | Provider policy and honest spend/egress enforcement |
| `provenance` | Explicit source, qualification, deployment and job facts |
| `local_docker` | Required exactly when `requires` includes `local-docker/1` |

The exact runtime is:

```json
{
  "repo": "microsoft/aibast-agents-library",
  "commit": "c60521e2cacbcbfa585a118c1275093d7bb15b74",
  "version": "0.6.16"
}
```

Grail owns chat and agent discovery. The Store does not ship BasicAgent, a
second inference loop, server, identity system or worker daemon. RAPP Work
is optional business workflow content, not a technical runtime dependency.
Version-1 twin metadata does not grant version-2 support for another engine.

Version-2 validation is closed on behavior-bearing fields. All declared
files must exist and match their hashes; undeclared executable dependencies
cannot be hidden inside metadata. Portable source/state-declaration paths
use printable ASCII, bounded to 512 characters, avoiding host-specific Unicode
case/normalization aliases. This does not restrict end-user job input text or
input filenames. Relative paths exclude traversal, hidden
members, ambiguous components, symlinks and case-folded destination
collisions. Application metadata is generated, not trusted from an
`index_entry.json` override. README is part of the lock; a UI is optional.
The 5 MiB package/20 MiB expanded-source limits remain separate from external
component materialization, which is declared rather than bundled as images.

Byte-length fields marked `x-wire-integer` must use JSON integer tokens,
not decimal or exponent spellings. The unchanged revision loader and
materializer read the original locked bytes and reject floating-point
file/artifact lengths. Other integer annotations use finite, integral,
safe JSON-number semantics, excluding booleans.
Browser wire preflight uses `RappStoreContract.parseJSON`, which retains this
token distinction without modifying the declared data; an already-parsed
JavaScript object alone cannot recover discarded numeric spelling.
The gateway's fixed concurrency policy is the numeric value `2` (excluding
booleans), not a serialized loader byte-count field.

Public federation resolves a full commit, re-reads the manifest at that
commit and fetches **every** locked file before admission. A source movement
refuses rather than mixing revisions. Private metadata alone cannot qualify
this complete installation contract. Native macOS distribution retains its
own version-1 extension rather than mixing installer semantics.

Complete applications currently use **public federation for Store
submission**. Their staged `source.ref` is the resolved full commit, so
approval cannot follow a subsequently moved branch. The existing source-ZIP
promotion path does not yet provide a qualified publisher-namespaced,
preserving complete-layout transaction; version-2 source ZIPs therefore
refuse **before extraction or promotion writes**, with
`E_APPLICATION_FEDERATION_ONLY`. This does not disable the separately
verified `rapp-egg/2.0` installation cartridge. Existing version-1 source
bundle behavior is unchanged.

### 15.2 `local-docker/1`

[`schemas/local-docker.schema.json`](./schemas/local-docker.schema.json) is
the closed feature contract. It requires `schema: rapp-local-docker/1` and:

- `component_lock`: locked public component/source/image inputs, platforms,
  dependencies/licenses and honest local build observations.
- `loader`: `scotty-revision-loader/1` plus locked `entrypoint`, `descriptor`
  and the complete content-named `support` subtree. `support` is the canonical
  relative directory path without a trailing slash; member resolution adds
  the separator rather than accepting multiple path aliases.
- `requirements_file`: explicit Python/current-Grail/Git/Docker/Compose/Buildx,
  host/guest architectures, resource observations and adopter login needs.
  Public image materialization uses Buildx/BuildKit, not the legacy builder;
  the Buildx plugin is checked only during explicit device preflight/use.
- `jobs_file`: closed typed job inputs, outputs, modes, providers and
  limitations. Bounds, enums, typed arrays and closed objects are supported;
  arbitrary publisher-supplied regular expressions are not part of this
  feature. There is no command-string execution escape hatch.
- `state_lifecycle_file`: owned roots/volumes, sealed inputs, preserving
  start/stop/detach/reinstall/recovery and credential/export exclusions.
- `intelligence`: official Copilot CLI in Docker, pinned version, model,
  concurrency, cloud inference, tools disabled, usage disclosure and
  disabled other paid providers.
- `exhaust`: canonical RAPP/1 `memory.tool-call` frames, session receipts,
  selected-output/source rapplication capsules and verification scope.
- `readiness`: independent package/install/job/health/lifecycle facts plus
  a locked evidence reference, not a universal “ready” flag.

File references are not arbitrary JSON escape hatches. Python admission,
embedded installer and browser file preflight dereference and type-check
them against the same advertised feature. Unknown mandatory declarations
refuse before installation or bundle extraction writes. Static preflight
does not invoke Docker, inspect credentials or infer device health.
Explicit installation/use performs the separate device preflight.

The component reference uses the existing **`rapp-dock-components/1` public
materializer lock**, not a parallel array projection or a second runtime
lane. The synthetic authoring fixture uses that same format with explicit
`blocked-build` entries, null recipes/references and nonempty blockers.
The lock is preserved losslessly and must match the runtime's scoped
`deploy/local/components.lock.json` byte-for-byte. Applications reference
existing component IDs; image environment names are unique. Registry/base
images are digest-pinned public references. Recipe/helper files resolve inside
the declared support tree and must match both the application lock and their
own byte/digest pins.

Public input sets and their wheel/system/model/npm dependency manifests are
dereferenced and type-checked, including SHA-512/integrity agreement for npm.
Unknown fields/kinds, unapproved origins, missing pins and contradictory
counts refuse. Exact dependency lengths may be absent only where the existing
materializer enforces its declared 2 GiB per-input bound and records the actual
length after digest verification; absence is not proof of a completed fetch.
Derived OpenShorts build recipes are also distributed as locked
`generated/dockerfiles/<component-id>.Dockerfile` files matching the declared
recipe hash and base-image list. Store validation does not import or execute
the supplied materializer to derive them.

`blocked-build` cannot qualify installation. Recorded network/transport
blockers stay explicit and may coexist with an experimental code-only canary;
cached image observations never establish public replay or fresh-device
qualification. No fake archive digest or size is synthesized merely to
translate one data format into the other.

The installer verifies the exact Grail baseline and installs the complete
bootstrap, descriptor and hash-scoped support layout. It checks ownership,
collisions and existing receipts before writes, writes the receipt last and
supports recovery without replaying application jobs. Detach/uninstall
preserves app data and retained, unqualified container layers. It must not
delete volumes, daemon-prune, or substitute a bare singleton.

### 15.3 Readiness and truthful listing language

The main authoring template is
[`samples/dock_scotty/`](./samples/dock_scotty/README.md). It is **unlisted,
experimental, synthetic authoring material**, not a deployed app or runnable
release. Its first-card disclosure is:

> Local application execution; Copilot cloud inference; tested on Apple
> Silicon with some amd64 guests under emulation.

This describes the development reference profile, not successful fresh
installation of the public candidate, a minimum resource specification, or
whole-bundle Intel/amd64 qualification. Resource observations, source/package
verification, fresh install, each job/mode, timestamped current health,
restart and full recreation are separate facts. Fresh install and Dify/
OpenShorts recreation remain pending in this sample. Missing evidence stays
pending/unknown; synthetic evidence never certifies runtime outcomes.

The shipped development modes are native Scrapling collection;
gateway-authored, Presenton-exported editable PPTX/PDF; actual OpenSEO
projects with paid data disabled; Dify economy retrieval with gateway-grounded
cited answers; and AI-selected/native-rendered OpenShorts. Native Presenton
generation is not the default and a native Dify model plugin is not claimed.

The adopter supplies their own Copilot entitlement/authentication. Copilot
consumes usage/credits; other paid providers stay disabled. Process, byte,
time and concurrency bounds are not a hard monetary spend cap or guaranteed
generation-token ceiling. App-window usage is not exact per-job billing.
Unmeasured monetary cost and hard spend cap remain `null`.

RAPP/1 receipt verification is unsigned and structural-only. A capsule
carries selected outputs and producing source, **not** full database state,
Docker images, secrets or a complete backup. Installation cartridges
(`rapp-egg/2.0`) and canonical RAPP/1 eggs are different artifacts.

### 15.4 Discovery, browsers and admission

Complete catalog/discovery rows retain `application_schema`, the full
`application`, `requires`, runtime and readiness. They default to
`installable: false` until a complete reviewed content-addressed package and
installer are published and applicable readiness gates pass. No
`singleton_url`, `service_url`, legacy egg, shell command or browser-run
fallback may bypass feature, closure or device checks.

The scoped `--application-only --ids <approved-id>` projection preserves
unrelated v1/native records, index metadata and immutable artifacts; it
does not alter the root catalog or Zoo. Global legacy producers must refuse
complete applications rather than generate partial eggs.

Browser validation is a static preflight, never execution authority.
Unknown, malformed or pending rich-app cards show blockers and disclosures,
not an “install” or “run in browser” shortcut. Existing simple and native UI
behavior is unchanged. New applications still require the `[RAPP]` receiver
and maintainer approval. Opening a draft plumbing PR does not admit the
unlisted template or authorize publication of private evidence.
