---
name: rapp-store
description: Use this skill to author, validate, and submit rapplications (single-file agent + UI bundles) to kody-w/RAPP_Store. Covers the catalog mechanics, the SPEC §6 validation rules, both submission modes (bundle and federation), and the brainstem-installable publishing agent.
---

# RAPP store — author & publish guide

This file is the operating manual for any AI working with the RAPP store. It explains what a rapplication is, how the catalog works, and the four ways to submit one. Read end-to-end before authoring.

## What this repo is

`kody-w/RAPP_Store` is the **content layer** of the RAPP platform — a public catalog of "rapplications". The execution engine (the brainstem) lives in `kody-w/RAPP`; trust/identity metadata is in the RAR registry. This repo ships **only content** — agents, services, UIs, and the catalog (`index.json`) that points at them.

There is no build system, package manager, or test runner at the repo root. Each rapplication is independent; the consumer brainstem is what executes them.

## What a rapplication is

A **rapplication** = an agent **plus** a UI, bundled together. If you have an agent without a UI, that's a swarm-agent and belongs in `kody-w/RAR` via the `[AGENT]` issue flow — submission to RAPP store will be rejected with `E_NO_UI`.

Minimum bundle layout:

```
my_rapp/
  manifest.json              # rapp-application/1.0
  my_rapp_agent.py           # singleton (one file, BasicAgent subclass)
  ui/index.html              # any web UI; loaded in the brainstem iframe
  README.md
  index_entry.json           # merge base for the catalog entry
```

Optional additions:

```
  my_rapp_service.py         # HTTP dispatch, mounted at /api/my_rapp/...
  versions/<v>/<file>        # pinned snapshots for back-compat
  eggs/*.egg                 # immutable state cartridges (zip)
```

## The singleton contract (SPEC §4)

Every shipped `*_agent.py` MUST satisfy these rules — they're enforced by `scripts/lib_rapp.py` and the receiver workflow:

1. **One file.** Imports `from agents.basic_agent import BasicAgent` (provided by the host brainstem — never vendored).
2. **Exactly one public class** whose name ends in `Agent` and extends `BasicAgent`. Internal helper classes must be prefixed `_Internal` so brainstem auto-discovery skips them.
3. **A `metadata` dict** in OpenAI function-calling schema shape: `name`, `description`, `parameters`.
4. **A `perform(**kwargs) -> str` method.**
5. **A module-level `__manifest__` dict** (schema `rapp-agent/1.0`).
6. **LLM dispatch** routes through `from utils.llm import call_llm` (provided by the host). Don't hard-code Azure/OpenAI clients.
7. **No template placeholders.** The validator rejects any unresolved `{{PLACEHOLDER}}`, `YOUR LOGIC GOES HERE`, `RAPP AGENT TEMPLATE`, etc. (Add the comment marker `# rapp-validator: allow-template-placeholders` only if you legitimately need to embed those strings as constants — e.g. you're authoring a validator.)

## The manifest (SPEC §6)

```json
{
  "schema": "rapp-application/1.0",
  "id": "my_rapp",
  "name": "My Rapp",
  "version": "0.1.0",
  "publisher": "@your-handle",
  "summary": "One-line description.",
  "category": "productivity",
  "tags": ["tag1", "tag2"],
  "agent": "my_rapp_agent.py",
  "ui": "ui/index.html",
  "quality_tier": "experimental"
}
```

**Locked enum** for `category` (adding requires a follow-up proposal):
- `productivity` — tools that make individual work faster
- `creative` — content + media pipelines
- `analysis` — surveys, audits, scoring
- `data` — ingestion, transform, query
- `integration` — external system glue
- `platform` — meta tools (binder, swarms, vibe_builder)
- `workspace` — personal task / state mgmt

**`id` rule:** `^[a-z][a-z0-9_]*$`. No dashes, no uppercase. Reserved IDs (`scripts`, `tests`, `versions`, `eggs`, `senses`, `docs`, `apps`) are rejected.

**`publisher` rule:** Must match the GitHub handle of the submitter (case-insensitive), or be `@rapp` / `@rarbookworld` (only `@kody-w` / `@rapp` token holders can publish under those).

**`quality_tier`:** Submitters cannot self-elevate above `community`. Only `experimental` and `deprecated` pass through; anything else is downgraded by the receiver. Maintainer-merged PRs raise tiers.

## The catalog

`index.json` is the canonical catalog. Schema `rapp-store/1.0`. The brainstem fetches it from `https://raw.githubusercontent.com/kody-w/rapp_store/main/index.json` (overridable via `RAPPSTORE_URL`).

Every entry has:
- `singleton_url` — fetchable raw URL of the agent .py
- `singleton_sha256`, `singleton_lines`, `singleton_bytes` — integrity, recomputed on every promotion
- `ui_url` — fetchable raw URL of the UI
- Optional `service_url`, `available_versions`, `source` (federation block)

**Anytime you change a singleton or service file, you must update `index.json`**: bump the version, recompute `singleton_sha256` / `singleton_lines` / `singleton_bytes`, bump `manifest.version`. The catalog is the contract.

## Submission paths (four ways)

### 1. Web UI — `submit.html`

`https://kody-w.github.io/RAPP_Store/submit.html`. Drop a `.zip` of the rapp directory or paste a public GitHub URL. OAuth or PAT auth. Use this if you're a human submitting one rapp.

### 2. Brainstem agent — `@rapp/rapp_publish_agent`

A single bare agent that auto-routes any RAPP-ecosystem artifact to its right home. Canonical source: [`kody-w/RAR/agents/@rapp/rapp_publish_agent.py`](https://github.com/kody-w/RAR/blob/main/agents/%40rapp/rapp_publish_agent.py). Drop the file into any brainstem's `agents/` folder.

The agent classifies the input *path* and routes accordingly:

| Detected | Where it goes | Issue prefix |
|---|---|---|
| `.py` with `class X(BasicAgent)` + `perform()` (no UI) | `kody-w/RAR` | `[AGENT]` |
| Directory or `.zip` with `manifest.json` (`schema=rapp-application/1.0`) | `kody-w/RAPP_Store` | `[RAPP]` |
| `.py` with module-level `name` / `delimiter` / `response_key` / `wrapper_tag` / `system_prompt` | `kody-w/RAPP_Sense_Store` | `[SENSE]` |

Customers don't need to know the topology — they hand the agent a path, it detects and routes. Same UX as `git push`.

```python
# from inside the host brainstem
agent = brainstem.agents["rapp_publish"]

# Just classify (no submission):
agent.perform(action="detect", path="/path/to/my_thing")
# → {"kind": "rapplication", "destination": {"repo": "kody-w/RAPP_Store", ...}}

# Classify + open the right issue:
agent.perform(action="submit", path="/path/to/my_rapp")
# → opens [RAPP] in kody-w/RAPP_Store

# Dry-run preview without opening an issue:
agent.perform(action="submit", path="/path/to/my_thing", dry_run=True)

# Print routing rules:
agent.perform(action="spec")
```

Auth: reads `GH_TOKEN` or `GITHUB_TOKEN` from env. Without one, falls back to dry-run and prints a manual-submission URL.

Detection rules (mechanical, AST-based):
- **Rapplication**: directory or `.zip` containing a `manifest.json` whose `schema` is `rapp-application/1.0`.
- **Bare agent**: `.py` file that imports `BasicAgent` *and* has a class ending in `Agent` extending `BasicAgent` *and* defines `perform()`.
- **Sense**: `.py` file that does *not* import `BasicAgent` and exports the five module-level strings (`name`, `delimiter`, `response_key`, `wrapper_tag`, `system_prompt`).
- Anything else → `unknown` (the agent prints why).

Use this whenever the user wants to publish or contribute *anything* to the RAPP ecosystem and you don't already know which store it belongs in.

### 3. Issue template

`.github/ISSUE_TEMPLATE/submit-rapplication.yml` is a structured form. Equivalent to the web UI but native to GitHub.

### 4. Direct PR (bundle mode only)

Drop a `<id>/` directory into the repo and edit `index.json` by hand. Maintainer-only path; bypasses the receiver workflow.

## Submission body format

The receiver workflow (`process-rapplication.yml` → `scripts/process_rapplication.py`) parses two fenced blocks from the issue body:

**Bundle mode:**

````
```json
{
  "submission_type": "bundle",
  "id": "my_rapp",
  "version": "0.1.0",
  "publisher": "@your-handle",
  "name": "My Rapp",
  "category": "productivity",
  "tags": ["tag1", "tag2"]
}
```

```bundle
<base64-encoded zip — the zip contains a top-level my_rapp/ folder>
```
````

**Federation mode:**

````
```json
{
  "submission_type": "federation",
  "id": "my_rapp",
  "version": "0.1.0",
  "publisher": "@your-handle",
  "name": "My Rapp",
  "category": "productivity",
  "tags": ["tag1", "tag2"],
  "source": {
    "repo": "your-handle/your-rapps",
    "ref": "main",
    "path": "my_rapp"
  }
}
```
````

Title format: `[RAPP] @publisher/id vX.Y.Z`. The workflow's `if:` filter only fires on titles starting with `[RAPP]`.

## Receiver flow

1. Issue opened/edited → `process-rapplication.yml` triggers.
2. `scripts/process_rapplication.py` extracts the JSON + bundle blocks.
3. `scripts/lib_rapp.py` validates against SPEC §6.
4. **On success:** files staged under `staging/<id>/` (bundle) or `staging/_pending.json` updated (federation), validation report posted as a comment, labels `pending-review` + `rapplication-submission` applied, staging committed to main.
5. **On failure:** error report posted as a comment, label `failed` applied, no commit.

## Approval flow

A maintainer reviews the comment on the issue and adds the `approved` label. That triggers `approve-rapplication.yml`:

1. `scripts/promote_rapplication.py` reads `staging/_pending.json` for the issue.
2. Bundle: moves `staging/<id>/` → `<id>/` at repo root, recomputes integrity from on-disk files, merges entry into `index.json`, bumps `index.json.generated_at`.
3. Federation: re-validates the source repo (in case `main` moved), re-resolves `commit_sha`, merges entry into `index.json`.
4. Promotion committed, issue closed, `promoted` label applied.

## Bundle vs federation tradeoffs

| | Bundle | Federation |
|---|---|---|
| Files in `RAPP_Store` | yes (copied to `<id>/`) | no (catalog points at your repo) |
| Updates require | new submission | bump `manifest.version` in your repo, resubmit |
| Bundle size cap | 5 MB | n/a (your repo) |
| Best for | one-shot rapps, tightly-coupled bundles | actively-developed rapps, your own repo as source of truth |

## Common validation errors

| Error code | Meaning | Fix |
|---|---|---|
| `E_NO_UI` | manifest doesn't declare `ui` | Add `"ui": "ui/index.html"` (rapps require a UI) |
| `E_BARE_AGENT_BELONGS_IN_RAR` | manifest has no agent, no service, no eggs | Submit to `kody-w/RAR` instead |
| `E_PUBLISHER_MISMATCH` | manifest publisher ≠ GitHub submitter | Update either the manifest or use a different account |
| `E_VERSION_NOT_BUMPED` | version <= existing catalog entry | Bump `manifest.version` (semver) |
| `E_TEMPLATE_PLACEHOLDER` | `{{PLACEHOLDER}}` etc. in singleton | Fill in the template; remove the placeholder strings |
| `E_NO_BASIC_AGENT_IMPORT` | singleton missing the BasicAgent import | Add `from agents.basic_agent import BasicAgent` |
| `E_MULTIPLE_AGENT_CLASSES` | more than one public class ending in `Agent` | Prefix internal helpers with `_Internal` |
| `E_DIR_NAME_MISMATCH` | folder name ≠ `manifest.id` | Rename the folder to match |
| `E_RESERVED_ID` | id collides with a platform-reserved name | Pick a different id |
| `E_BUNDLE_TOO_LARGE` | zip > 5 MB | Trim assets; consider federation mode |
| `E_PATH_TRAVERSAL` | zip contains `..` segments | Re-zip from inside the rapp dir |

The full ruleset and the validator implementation live in `scripts/lib_rapp.py`. Tests in `tests/test_lib_rapp.py` are the source of truth — reading them is faster than reading the validator.

## Authoring workflow (recommended)

```bash
# 1. Scaffold
mkdir -p my_rapp/ui
cd my_rapp
# author manifest.json, my_rapp_agent.py, ui/index.html, README.md, index_entry.json

# 2. Dry-run with the unified router agent — confirms detection + previews payload
python3 -c "
from agents.rapp_publish_agent import RappPublishAgent
print(RappPublishAgent().perform(action='submit', path='.', dry_run=True))
"

# 3. Submit (needs GH_TOKEN or GITHUB_TOKEN with public_repo scope)
python3 -c "
from agents.rapp_publish_agent import RappPublishAgent
print(RappPublishAgent().perform(action='submit', path='.'))
"
# → opens [RAPP] in kody-w/RAPP_Store; receiver workflow runs in <30s.
```

Or use `submit.html` for a graphical equivalent.

The same agent handles a bare `.py` (routes to RAR) or a sense file (routes to Sense_Store) — the customer doesn't need to know which.

## Composite layouts (advanced)

Some rapps (`bookfactory`, `execbrief`, `momentfactory`, `twin_workshop`, `pitch_deck`) author as multi-file specialists in `source/` and **build** a singleton via `tools/build.py`:

```
my_rapp/
  manifest.json
  source/                # editable specialists (the authoring surface)
  singleton/<name>_agent.py   # generated SHIP-TIME artifact
  tools/build.py         # collapses source/ → singleton/
```

Edit `source/`. Rebuild with `python3 my_rapp/tools/build.py`. Never hand-edit the generated singleton — your edits get blown away.

## Service-rapp layouts (advanced)

Some rapps (`binder`, `dashboard`, `kanban`, `swarms`, `vibe_builder`, `webhook`) ship both an agent AND an HTTP service:

```
my_rapp/
  manifest.json
  my_rapp_agent.py       # conversational interface
  my_rapp_service.py     # HTTP dispatch
  versions/<v>/          # pinned snapshots
```

The service exports `name = "<route prefix>"` and `handle(method, path, body)`. State is shared via `.brainstem_data/<name>.json` in the consuming brainstem's working tree.

## Eggs

A `.egg` is a zip cartridge with `manifest.json` (`schema: "rapp-egg/1.0"`, `type: "rapplication"`) plus optional `agent.py`, `service.py`, `ui/...`, `state/...`. The binder service exports/imports them. **Treat them as immutable** — never overwrite an existing egg file.

## Where to ask for help

- Validator code: `scripts/lib_rapp.py`
- Tests as ground truth: `tests/test_lib_rapp.py`, `tests/test_receiver.py`
- Workflows: `.github/workflows/process-rapplication.yml`, `approve-rapplication.yml`
- Engine source: [`kody-w/RAPP`](https://github.com/kody-w/RAPP)
- For bare agents (no UI): [`kody-w/RAR`](https://github.com/kody-w/RAR)
