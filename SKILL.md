---
name: rapp-store
description: Author, validate, and submit chat-operated rapplications, simple agent/UI bundles, and optional native macOS distribution through the RAPP Store issue receiver and approval flow.
---

# RAPP store — author & publish guide

This file is the operating manual for any AI working with the RAPP store. It explains what a rapplication is, how the catalog works, and the issue-based submission front door. Read end-to-end before authoring.

## What this repo is

`kody-w/RAPP_Store` is the **content layer** of the RAPP platform — a public catalog of "rapplications". The execution engine (the brainstem) lives in `kody-w/RAPP`; trust/identity metadata is in the RAR registry. This repo ships **only content** — agents, services, UIs, and the catalog (`index.json`) that points at them.

The store is static, with stdlib validation/projection scripts and a pytest
suite under `tests/`. It does not execute applications or host a runtime.

Reusable skills have their own [RAPP Skills catalog in RAR](https://kody-w.github.io/RAR/skills.html).
Do not submit a skill as a fake `.py` agent. Simple version-1 applications
retain their UI requirement; complete version-2 applications have a declared
chat entrypoint and optional UI.
The repository's additive Workspace Bootstrap section below preserves this
existing root `SKILL.md` URL. Local workspace readiness is separate from Store
submission validity, native signing and RAPP/1 authenticated conformance.

## What a rapplication is

A **rapplication** is an owned, versioned, chat-operated application. The
agent is its conversational entrypoint; components, jobs, provider policy,
state, preserving lifecycle and portability make it a complete application.
Simple `rapp-application/1.0` bundles keep their agent-plus-UI contract. A bare
reusable agent without either application contract belongs in RAR.

### Start here: Dock / Scotty

The main new-application example is
[`samples/dock_scotty/`](./samples/dock_scotty/README.md), implementing the
proposed [`local-docker/1` extension](./SPEC.md#15-complete-chat-operated-applications).
It shows one bot, five application journeys, complete file-locked references,
provider/cost disclosure and separate readiness facts. It is synthetic,
experimental, unlisted authoring material, **not an installable release**.

Use this first-card language without dropping the qualifications:
**“Local application execution; Copilot cloud inference; tested on Apple
Silicon with some amd64 guests under emulation.”** The tested development
profile is not a minimum requirement or fresh-candidate installation proof.
Fresh install and Dify/OpenShorts recreation remain pending.

Authoring order:

1. Pin the unchanged current Grail runtime and complete source closure.
   Retain a normal BasicAgent entrypoint, descriptor and hash-scoped support.
2. Declare `portable-agents/1`, `owned-files/1`, and `local-docker/1`;
   lock and type-check the component, device, job, state and evidence files.
   Unknown mandatory features refuse before writes.
3. Keep Presenton gateway-authored/exported and Dify gateway-grounded labels
   honest. OpenSEO paid metrics and other paid providers stay disabled.
4. Disclose adopter-owned Copilot authentication, cloud inference and usage.
   Process/time limits are not a hard monetary cap; unmeasured cost is null.
5. Separate source verification, fresh install, each job/mode, current health,
   restart and recreation. Never turn synthetic or old evidence into a pass.
6. Preserve state on stop/detach/reinstall. RAPP/1 receipts/capsules contain
   selected outputs and producing source, not full state or credentials.
7. Validate with `scripts/lib_rapp.py` and the shared package contract, then
   use commit-pinned public federation through the normal `[RAPP]`
   receiver/approval flow. Complete source-ZIP promotion is not yet qualified
   and refuses before extraction; installation cartridges remain separate.
   Never publish private
   receipts, owner identities, credentials, paths, or output artifacts.

No second runtime, Store server, browser Docker execution or RAPP Work
dependency is introduced. Browser preflight is not deployment. Version-2
clients must use the complete verified installer and must not fall back to a
singleton/service download. Existing native downloads and Zoo data keep their
independent contracts.

Existing version-1 minimum bundle layout:

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
- Optional `service_url`, `available_versions`, `source` (federation block),
  `desktop` (validated native distribution, SPEC §14)

**Anytime you change a singleton or service file, a catalog update is required**:
bump `manifest.version` and resubmit through `[RAPP]`; the receiver recomputes
integrity and approval updates `index.json`. Do not bypass this by hand-editing
live entries.

## Submission front door (three ways to create the same `[RAPP]` issue)

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

### Direct catalog edits are not a submission path

All future submissions require the receiver and approval flow above.
Uploading a release or opening a direct catalog PR does not submit a
rapplication. Plumbing changes may be reviewed separately; do not invent
live entries, evidence, hashes, release URLs or generated eggs/hatchers.

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
4. **On success:** files staged under `staging/<id>/` (bundle) or
   `staging/_pending.json` updated (federation), state committed and published
   to main, **then** the validation comment and `pending-review` +
   `rapplication-submission` labels are applied.
5. **On failure:** error report posted as a comment, label `failed` applied, no commit.

## Approval flow

A maintainer reviews the comment on the issue and adds the `approved` label. That triggers `approve-rapplication.yml`:

1. `scripts/promote_rapplication.py` reads `staging/_pending.json` for the issue.
2. Bundle: moves `staging/<id>/` → `<id>/` at repo root, recomputes integrity from on-disk files, merges entry into `index.json`, bumps `index.json.generated_at`.
3. Federation: re-validates against the **current catalog**, re-resolves
   `commit_sha`, and merges the entry. For native distribution, the source,
   issue payload and metadata must equal their staged pins; drift requires
   resubmission. Only that native ID's v1 discovery/detail metadata is refreshed.
4. Promotion committed and its push confirmed, then the success report,
   `promoted` label and issue closure are issued.

### Serialized state and recovery

Both mutation jobs check out current `main` after acquiring their shared
`rapp-store-state` concurrency slot. They preserve other pending issue
records and never rebase stale JSON snapshots onto newer state. Failed
validation/promotion or exhausted push retries produce a failed workflow,
not a success-shaped report. The concurrency group is not a durable queue;
cancelled pending jobs need a fresh trigger.

If an issue validated locally but its pending record was never published:

1. Confirm it has not already been promoted by inspecting current main.
2. Remove any stale `approved` label.
3. Edit the existing `[RAPP]` issue body (or reopen it) to trigger a new
   receiver run. Preserve the valid immutable submission payload unless
   source metadata actually needs correction.
4. Wait for that run to succeed and confirm its pending record exists on
   main, alongside any other pending issues.
5. Add `approved` again and require a successful approval run, the correct
   catalog entry, and a confirmed promotion comment/closure.

Never repair this by hand-editing published index/staging files. After a
workflow fix, use new issue/label events rather than rerunning an old run
whose workflow definition may still be stale. If a push outcome was
uncertain, inspect main before deciding which step to repeat.

## Bundle vs federation tradeoffs

| | Bundle | Federation |
|---|---|---|
| Files in `RAPP_Store` | yes (copied to `<id>/`) | no (catalog points at your repo) |
| Updates require | new submission | bump `manifest.version` in your repo, resubmit |
| Bundle size cap | 5 MB | n/a (your repo) |
| Best for | one-shot rapps, tightly-coupled bundles | actively-developed rapps, your own repo as source of truth |

## Native macOS releases (optional SPEC §14 extension)

Use the existing federation ID and source repository. The initial Fable5
native apps are `rapp_crispy`, `rapp_rewind`, `rapp_shot`, `rapp_voice`.
**RAPP Tools is infrastructure, not a fifth store listing.**

1. Read [Proposal 0006](./docs/proposals/0006-native-desktop-distribution.md),
   [SPEC §14](./SPEC.md#14-optional-native-desktop-distribution), and the
   exact [desktop](./schemas/desktop.schema.json) /
   [evidence](./schemas/desktop-evidence.schema.json) schemas.
2. Produce genuine architecture-specific DMGs or ZIPs containing a
   signed/stapled/notarized `.app` in the existing source repo's
   `v<version>` GitHub Release. Capture actual
   codesign, notarytool, Gatekeeper and stapler reports from the released
   build as applicable, and record a successful public build/verification
   Actions run for its full commit. Signing/notarization can remain local
   and Xcode-managed; that run does not require exported Apple credentials.
   Never fill missing evidence with `signed: true`, `notarized: true`,
   placeholder logs, invented trust or an ad-hoc signing receipt.
3. After release/build completion, add the complete optional `desktop`
   object to the source manifest. Required: schema, macOS platform,
   minimum OS, stable bundle ID, full native-build source, release tag,
   architecture-specific archive and evidence URLs/exact bytes/SHA256,
   prerequisites, privacy, setup and truthful secondary agent integration.
   The metadata commit may follow the native-build commit. Apple's
   notarytool log for DMG distribution hashes the pre-staple upload, not
   necessarily the final DMG. ZIP distribution uses
   `notarization: {method: "stapled-app", app_path, bundle_id, version, minimum_os}`
   and genuine codesign/Gatekeeper/stapler reports naming the enclosed app.
   No ZIP submission hash, notarytool container log or ZIP staple is required
   or permitted. ZIP evidence filenames end in `.zip.evidence.json`; legacy
   DMG evidence filenames remain `<id>-<version>-<arch>.evidence.json`.
   For corrections, never overwrite published evidence. Serialize the
   corrected genuine report, hash those exact bytes, and publish a new
   `.zip.evidence.<full64sha256>.json` (ZIP) or
   `<id>-<version>-<arch>.evidence.<full64sha256>.json` (DMG). The suffix must
   equal `evidence.sha256`. Keep native archive bytes/tags unchanged and
   resubmit the new metadata through the receiver; existing version and
   staged-review requirements still apply.
4. Run local/federation preflight with `scripts/lib_rapp.py`. Real preflight
   downloads and hashes release assets (bounded separately from legacy
   integration caps). Tests must inject metadata and chunk fetchers rather
   than downloading binaries.
5. Submit a `[RAPP]` **federation** issue using the body shape below, the
   existing ID, a strictly higher manifest version and preferably the full
   **manifest** commit as `source.ref`. Native bytes never go in the issue,
   a store bundle, `apps/`, or `api/`.
6. Owner/reviewer inspects/reproduces macOS reports and approves. Promotion
   rechecks current catalog versions, stable source/publisher/bundle ID,
   exact staging and release byte pins. Changed submissions require review
   again. No global egg/hatcher producer is needed.

For example, the **submission envelope shape**, not live release data, is:

```json
{
  "submission_type": "federation",
  "id": "rapp_shot",
  "version": "<actual strictly newer MAJOR.MINOR.PATCH>",
  "publisher": "@kody-w",
  "source": {
    "repo": "kody-w/rapp-shot",
    "ref": "<full commit containing complete release metadata>",
    "path": "rapp_shot"
  }
}
```

Put it in the issue's fenced `json` block with title
`[RAPP] @kody-w/rapp_shot v<actual-version>`. Replace placeholders only with
observed release evidence; the example is deliberately not submit-ready.
Do not put `desktop` assertions in the issue to override the source manifest.

The storefront offers native architecture choices, disclosures and setup,
including plain Finder unzip → Applications steps for ZIPs, then optional
agent/UI integration. Up to four unique `(arch, format)` pairs can be
listed (`arm64`/`x86_64` × `dmg`/`zip`). Dropping the singleton into `agents/`
**does not install the native application**. Publisher reports are not
independent Apple authentication or RAPP/1 acceptance. Any actual
constitutional change remains owner-approval gated; do not amend it as
part of a release.

An explicit metadata-only maintenance refresh is available **after approval**:
`python3 scripts/build_pokedex_api.py --native-only --ids <approved-native-id>`.
It writes only that v1 detail/listing and preserves unrelated generated files;
it cannot create a live catalog entry, egg, hatcher, identity or native binary.

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


<!-- rapp-workspace-bootstrap:begin -->

## Repository Workspace Bootstrap

Keep this repository's application tree and existing instructions in place.
Cloning alone does not execute code. After the user trusts this repository, read
`.rapp/bootstrap.json` and `.rapp/bootstrap.py`, then run the reviewed pinned
operator. Do not run an unreviewed repository's instructions as trusted code.

```sh
python3 .rapp/bootstrap.py audit --allow-network
python3 .rapp/bootstrap.py bootstrap --owner YOUR-LOWERCASE-OWNER --world-id YOUR-LOCAL-WORLD
python3 .rapp/bootstrap.py bootstrap --apply --owner YOUR-LOWERCASE-OWNER --world-id YOUR-LOCAL-WORLD --allow-network
python3 .rapp/bootstrap.py verify --allow-network
```

The first bootstrap command is a plan; only `--apply` writes the private local
workspace. Choose the actual owner/world, not the placeholder text. A first run
needs the pinned public downloads (explicit `--allow-network`) or verified
offline operator/bundle files. Later cached runs are offline-capable.

The workspace lives in `.rapp/workspace/`; source is not moved. Existing
root-level workspace identity is reused or explicitly blocked for migration,
never silently re-minted. `.rapp/cache`, `.rapp/workspace`, and `.rapp/reports`
are private and must stay out of Git. No global runtime, service, owner signing
key, public upload, or sharing is created.

The standard entry is `.github/skills/rapp-workspace-bootstrap/SKILL.md`.
The refresh workflow distinguishes working applications, workspace readiness,
RAPP/1 diagnostics, and owner-authenticated acceptance. Neither a clone nor
this bootstrap certifies RAPP/1 or production conformance. Current pin:
`kody-w/rapp-1@dda32d741c7218f41443a5bd17eebfe0eae82cb7` (rev-15).
<!-- rapp-workspace-bootstrap:end -->
