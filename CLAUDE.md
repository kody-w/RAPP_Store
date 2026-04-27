# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This is the **content layer** of the RAPP platform — a public catalog of "rapplications" (single-file Python agents). The engine (Tier 1 brainstem, Tier 2 swarm, Tier 3 worker) lives in [`kody-w/RAPP`](https://github.com/kody-w/RAPP); trust/identity metadata lives in the RAR registry. This repo ships **only content** — agents, services, UIs, and the catalog that points to them.

There is no build system, test suite, or package manager at the repo root. Each rapplication is independent, and the brainstem in the consuming repo is what executes them.

## Catalog mechanics

- `index.json` is the canonical catalog (`schema: "rapp-store/1.0"`). The brainstem's binder service fetches it from `https://raw.githubusercontent.com/kody-w/rapp_store/main/index.json` (overridable via `RAPPSTORE_URL`).
- `index.html` is a static GitHub Pages browser that fetches `./index.json` at runtime and renders cards. No build step.
- Each catalog entry points to `singleton_url` (one `.py` file) and optionally `service_url`, `ui_url`, `egg_url`, `singleton_sha256` (for integrity), and `available_versions` (for pinning to `versions/<v>/<file>`).
- **Anytime you change a singleton or service file, you must also update `index.json`**: bump the version, recompute `singleton_sha256` / `singleton_lines` / `singleton_bytes`, and bump the rapp's `manifest.json`. The catalog is the contract — the files alone aren't reachable.

## Rapplication layouts (two flavors)

**Composite (multi-file authoring → collapsed singleton):** `bookfactory/`, `execbrief/`, `momentfactory/`, `twin_workshop/`, `pitch_deck/`.

```
<name>/
  manifest.json          # rapp-application/1.0
  source/                # editable multi-file specialists (the authoring surface)
  singleton/<name>_agent.py   # generated SHIP-TIME artifact — drop into agents/
  tools/build.py         # collapses source/ → singleton/ (rapp-specific, no shared toolchain)
  ui/index.html          # optional iframe UI
  eggs/*.egg             # optional state snapshots (immutable — never overwrite)
```

Build a singleton: `python3 <name>/tools/build.py`. The collapse is mechanical (extract SOULs, rename leaf classes with `_Internal` prefix, inline one shared `_llm_call` helper, expose one public `*Agent` class). Edit `source/`, never the generated singleton — your edits to the singleton are blown away on rebuild.

**Service rapps (hand-written, agent + HTTP service):** `binder/`, `dashboard/`, `kanban/`, `swarms/`, `vibe_builder/`, `webhook/`.

```
<name>/
  manifest.json
  <name>_agent.py        # BasicAgent subclass — conversational interface
  <name>_service.py      # HTTP dispatch — same surface over /api/<name>/...
  versions/<v>/          # pinned snapshots (binder may install these by version)
```

The agent and service typically share a JSON state file under `.brainstem_data/<name>.json` in the consuming brainstem's working tree.

`senses/` is a third, lightweight shape — not BasicAgent classes but small modules exporting `name`, `delimiter`, `response_key`, `wrapper_tag`, `system_prompt`. They append a translation/companion view to a main reply.

## The singleton contract

Every shipped `*_agent.py` must satisfy SPEC §5 (in `kody-w/RAPP/pages/docs/SPEC.md`):

1. One file. Imports `from agents.basic_agent import BasicAgent` (provided by the host brainstem — never vendored).
2. Exactly one class extending `BasicAgent` whose name ends in `Agent` (the brainstem auto-discovers by this rule). Internal helper classes in composites are prefixed `_Internal` so discovery skips them.
3. A `metadata` dict in OpenAI function-calling schema shape (`name`, `description`, `parameters`).
4. A `perform(**kwargs) -> str` method.
5. A module-level `__manifest__` dict (schema `rapp-agent/1.0`).
6. LLM dispatch routes through `from utils.llm import call_llm` (provided by the host). Don't hard-code Azure/OpenAI clients in singletons.

For composites with a public class that doesn't end in `Agent` (e.g. `BookFactory`), add a trailing-`Agent` alias subclass at the bottom so discovery picks it up.

## Service contract

`*_service.py` modules export:
- `name = "<route prefix>"` — mounts at `/api/<name>/...`
- `handle(method, path, body)` returning `(dict|bytes, status)` or `(body, status, headers)` for binary responses.

Path is relative to the service prefix. Storage paths resolve from `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` — i.e. the host brainstem's repo root, not this repo. Don't hard-code paths.

## Eggs (`.egg`)

A `.egg` is a zip cartridge with `manifest.json` (`schema: "rapp-egg/1.0"`, `type: "rapplication"`) plus optional `agent.py`, `service.py`, `ui/...`, `state/...`. The binder service exports/imports them; treat them as immutable — never overwrite an existing file. Path-traversal guards in `binder_service.py` reject `..` segments on import; preserve those when editing.

## Submitting a rapplication

The canonical spec is `SPEC.md`. Submission goes through one of:

- **`@rapp/publish-to-rapp-store` agent** — `publish_to_rapp_store/singleton/publish_to_rapp_store_agent.py`. Validates locally, opens a `[RAPP]` issue. Two modes: `submit_bundle` (files copied into rapp_store) and `submit_repo` (federation — catalog entry points at submitter's own public GitHub repo via `raw.githubusercontent.com`).
- **Issue template** — `.github/ISSUE_TEMPLATE/submit-rapplication.yml` (structured form).
- **Direct PR** (bundle mode only) — drop a `<id>/` directory in, regenerate the relevant `index.json` entry.

Receiver flow (GH Actions):
- `process-rapplication.yml` (issues:opened/edited/reopened) → `scripts/process_rapplication.py` parses payload, calls `scripts/lib_rapp.py` validator, stages bundles under `staging/<id>/`, comments + labels `pending-review`.
- `approve-rapplication.yml` (issues:labeled, label=`approved`) → `scripts/promote_rapplication.py` moves staging → `<id>/` (bundle) or merges federation entry into `index.json`, recomputes integrity from on-disk files, commits, closes the issue.

The validator (`scripts/lib_rapp.py`) is the single source of truth for SPEC.md §6 (validation rules) and §4 (singleton AST contract). Both the agent (local pre-flight) and the receiver workflow use it. Tests in `tests/test_lib_rapp.py`, `tests/test_publish_agent.py`, `tests/test_receiver.py`. Run `python3 -m pytest tests/`.

Federation submissions add a `source: {repo, ref, path, commit_sha}` block to their catalog entry. The brainstem's binder service still installs from `singleton_url` (which uses `ref`, e.g. `main`) and verifies SHA256 — drift surfaces as a hard install failure. To publish a new version, the submitter bumps `manifest.version` in their repo and resubmits; the agent re-resolves `commit_sha`.

`publish_to_rapp_store` is in `RESERVED_IDS` — only `@kody-w` / `@rapp` can publish updates. The validator's `# rapp-validator: allow-template-placeholders` source marker exempts files (like the publish agent itself) that legitimately need to embed the template-placeholder strings as constants.
