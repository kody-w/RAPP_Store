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
| `agent` | string | yes if no `service` | Relative path to the singleton, e.g. `singleton/<id>_agent.py`. |
| `service` | string | yes if no `agent` | Relative path to the service module, e.g. `service/<id>_service.py`. |
| `ui` | string | no | Relative path to the iframe entrypoint. |
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
11. The manifest declares at least one of `ui`, `service`, or ships an `eggs/` directory. Per Constitution Article XXVII, a bare `agent.py` with no application surface belongs in `kody-w/RAR`, not the rapp store. Error code: `E_BARE_AGENT_BELONGS_IN_RAR`. The rejection comment links the submitter to RAR's `[AGENT]` issue flow.

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

## 9. Reserved IDs

The following IDs are reserved by the platform and cannot be claimed by community publishers: `binder`, `dashboard`, `kanban`, `swarms`, `webhook`, `vibe_builder`, `learn_new`, `swarm_factory`, `senses`, `publish_to_rapp_store`. The reserved list lives in `scripts/lib_rapp.py`.
