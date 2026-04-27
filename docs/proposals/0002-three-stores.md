# Proposal 0002 — The Three-Store Ecosystem

| | |
|---|---|
| **Status** | Draft |
| **Sponsor** | @kody-w |
| **Drafted** | 2026-04-27 |
| **Touches** | `kody-w/RAPP` (CONSTITUTION.md, rapp_brainstem/), `kody-w/RAR` (no schema; receives a routing agent), `kody-w/RAPP_Store` (publisher namespacing, vBrainstem, presentation layer), `kody-w/RAPP_Sense_Store` (creation + bootstrap). |
| **Complies with** | Article XXVIII (proposals before changes), Article XXIX (front doors), Article XXX (pipelines end-to-end). |
| **Supersedes** | Article XXVII's two-tier framing — extends it to three peer artifact types. |

## 1. The full ecosystem today

Six repos under `kody-w/` form the RAPP platform:

| Repo | Role | What's there now |
|---|---|---|
| `kody-w/RAPP` | The engine | `rapp_brainstem/` (Flask server, default agents/services/senses), `CONSTITUTION.md`, marketing site at `kody-w.github.io/RAPP/`, install one-liner |
| `kody-w/RAR` | The agent registry | 267 bare `*_agent.py` files under `agents/@<publisher>/`, `[AGENT]` issue submission flow, `registry.json` |
| `kody-w/RAPP_Store` | The rapplication catalog + ecosystem front door | 7 bundles (binder, dashboard, kanban, swarms, webhook, bookfactory, twin_workshop) + a 5-sense `senses/` directory **that doesn't conform to the rapp spec** + the `vbrainstem.html` chat surface + landing page |
| `kody-w/RAPP_Sense_Store` | *(empty, just created)* | nothing yet — this proposal bootstraps it |
| `kody-w/rapp-installer` | The one-line install script | `install.sh` that pulls RAPP and starts the brainstem. **Out of scope of this proposal** — included for ecosystem completeness. |
| `kody-w/openrappter` | Sibling brainstem implementation | Cloud-only variant; consumes the same agent contract. **Out of scope** — referenced but not governed here. |

### What's wrong with the current state

1. **Senses don't have a home.** The 5 senses in `RAPP_Store/senses/` violate the rapp spec (no `manifest.json`, no `BasicAgent`, no `perform()`). The 2 kernel-baked senses (`voice_sense.py`, `twin_sense.py` in RAPP) are fine where they are, but the modular community senses need a real registry with a real submission flow.
2. **No publisher namespacing in RAPP_Store.** Rapps live at the root: `bookfactory/`, `kanban/`, etc. When `@alice/cool_thing` submits, where does it go? RAR solved this with `@<publisher>/<slug>` — RAPP_Store didn't.
3. **No unified ecosystem-wide presentation.** Each store has its own landing page; there's no single browse surface that shows agents + rapplications + senses in one place. The vBrainstem in RAPP_Store could be that surface but currently only loads from RAPP_Store's catalog.
4. **No automated submission routing.** A user holding a `.py` file doesn't know whether it's an agent, a rapplication, or a sense. There's no single entry point that classifies and routes the submission to the right repo's `[X]` issue flow.

## 2. The three-store model

Three peer artifact types, three peer stores, one front door:

| Tier | Artifact | Repo | Path inside repo | Submission |
|---|---|---|---|---|
| **Agents** | Bare `*_agent.py` files (one file, one class extending `BasicAgent`, one `perform()`). The registry case. | `kody-w/RAR` | `agents/@<publisher>/<slug>_agent.py` | `[AGENT] @publisher/slug` issue |
| **Rapplications** | Bundles: agent + UI / service / eggs. The application case. | `kody-w/RAPP_Store` | `apps/@<publisher>/<id>/` *(new — currently root-level)* | `[RAPP] @publisher/id` issue |
| **Senses** | Modular per-channel output overlays. `name` + `delimiter` + `response_key` + `wrapper_tag` + `system_prompt` + (new) `surfaces`. | `kody-w/RAPP_Sense_Store` | `senses/@<publisher>/<slug>_sense.py` *(new)* | `[SENSE] @publisher/slug` issue |

> **One artifact, one home. One publisher, one path. One issue flow per artifact type.**

`RAPP_Store` keeps both roles — its rapplication catalog AND the unified presentation layer (vBrainstem, landing page). The other two stores are pure backends with their own minimal landing pages.

`kody-w/RAPP` (the engine) is unchanged in role: it's the wire, not a store. Its kernel-baked agents/services/senses remain where they are (Article XVI: the engine's surface vs. the brainstem's workspace).

## 3. What we're explicitly NOT doing yet

User-evident demand exists for three artifact types. Two more were on the table; deferring:

- **`RAPP_Swarm_Store`.** Swarms-as-source (multi-file `source/` trees that build into a singleton) are already accommodated inside individual rapplications' `source/` directories. The shipped artifact is the singleton, which is either a bare agent (RAR) or a rapplication (RAPP_Store) depending on whether it ships UI/service/eggs. A separate swarm registry would only matter if community demand emerges for **forking the source trees** rather than installing the collapsed singletons. No such demand visible today. Re-evaluate if/when a swarm-fork issue lands.
- **`RAPP_Egg_Store`.** State cartridges currently ship inside rapplications' `eggs/` dirs. Standalone `.egg` distribution would matter if users want to share *just state* (e.g., "import my BookFactory configuration"). No demand visible. Re-evaluate later.
- **`RAPP_Soul_Store`.** Souls are per-brainstem identity files (`soul.md`). Sharing souls would matter if "calibrated personalities" become a tradeable artifact. Premature.

If demand for any of these surfaces, they each spin out as their own peer repo following the same template — separate proposal at that time.

## 4. Per-repo organization

### 4.1 `kody-w/RAR` — the agent registry

**Already in this shape.** No structural changes needed.

```
RAR/
├── agents/
│   └── @<publisher>/
│       └── <slug>_agent.py
├── cards/                       holographic card metadata (existing)
├── scripts/
│   ├── process_issues.py        existing — handles [AGENT] submissions
│   ├── generate_holo_cards.py
│   └── lib_rar.py               (rename security_scan.py here for parity)
├── tests/
├── .github/
│   ├── ISSUE_TEMPLATE/agent-submission.yml
│   └── workflows/{process,approve,build-registry}.yml
├── SPEC.md                       agent contract (one file, BasicAgent, perform)
├── README.md  CLAUDE.md
├── registry.json                 catalog (built from agents/)
├── index.html                    landing page
└── store.html                    full browse UI (existing)
```

**Adds (this proposal):**
- A new bare agent: `agents/@rapp/rapp_publish_agent.py` — the routing agent (§5).

### 4.2 `kody-w/RAPP_Store` — rapplication catalog + ecosystem front door

```
RAPP_Store/
├── apps/                         ← NEW: rapplications, publisher-namespaced
│   └── @<publisher>/
│       └── <id>/
│           ├── manifest.json
│           ├── index_entry.json
│           ├── singleton/<id>_agent.py
│           ├── README.md
│           ├── ui/index.html              (optional)
│           ├── service/<id>_service.py    (optional)
│           ├── eggs/*.egg                 (optional)
│           ├── source/                    (optional, build-time)
│           └── tools/build.py             (optional)
├── docs/
│   └── proposals/
├── scripts/
│   ├── lib_rapp.py
│   ├── process_rapplication.py
│   └── promote_rapplication.py
├── tests/
├── .github/
│   ├── ISSUE_TEMPLATE/submit-rapplication.yml
│   └── workflows/{process,approve}-rapplication.yml
├── SPEC.md
├── README.md  CLAUDE.md
├── index.json                    rapplication catalog
├── ecosystem.json                ← NEW: aggregated catalog of all three
├── index.html                    landing — gateway to all three stores
└── vbrainstem.html               chat — loads from all three catalogs
```

**Removed from root:**
- `senses/` → migrates to `RAPP_Sense_Store`.
- The 7 root-level rapp directories → move under `apps/@rapp/`.

**Migration of catalog URLs** (this is the breaking part):
- Old: `https://raw.githubusercontent.com/kody-w/rapp_store/main/bookfactory/singleton/bookfactory_agent.py`
- New: `https://raw.githubusercontent.com/kody-w/rapp_store/main/apps/@rapp/bookfactory/singleton/bookfactory_agent.py`

Acceptable cost — no users yet. The window is now.

### 4.3 `kody-w/RAPP_Sense_Store` — the sense library *(NEW)*

```
RAPP_Sense_Store/
├── senses/
│   └── @<publisher>/
│       └── <slug>_sense.py
├── docs/
│   └── proposals/
│       └── 0001-bootstrap.md
├── scripts/
│   ├── lib_senses.py
│   ├── process_sense.py
│   └── promote_sense.py
├── tests/
├── .github/
│   ├── ISSUE_TEMPLATE/submit-sense.yml
│   └── workflows/{process,approve}-sense.yml
├── SPEC.md
├── README.md  CLAUDE.md
├── index.json
└── index.html
```

**Sense contract** (proposed `SPEC.md` for the new store):
```python
# <slug>_sense.py
name = "eli5"                    # required, snake_case
delimiter = "|||ELI5|||"         # required, must be unique across senses
response_key = "eli5_response"   # required, the JSON field clients read
wrapper_tag = "eli5"             # required, the chat-XML tag clients render
system_prompt = "..."            # required, what the LLM appends after the main reply
surfaces = ["chat", "voice"]     # NEW: which channels this sense applies to.
                                 # Default: ["chat"]. Allowed: chat / voice / mobile / cards.
```

The `surfaces` field is the modular-per-channel piece — the brainstem only composes a sense's `system_prompt` when the active channel matches.

**Initial migration** (Proposal 0001 of `RAPP_Sense_Store`):
- 5 senses from `RAPP_Store/senses/` → `senses/@rapp/{eli5,emoji,haiku,headline,tldr}_sense.py`
- The 2 kernel-baked senses (`voice_sense.py`, `twin_sense.py`) **stay in RAPP** — they're load-bearing platform features, not community-submitted ones.

### 4.4 `kody-w/RAPP` — the engine

No structural changes. Updates:

- `rapp_brainstem/utils/services/binder_service.py`: extend to know about all three sources. Currently fetches `RAPPSTORE_URL` (one catalog). New env vars: `RAR_URL`, `SENSE_STORE_URL`, defaulting to the canonical raws. Install routes by artifact type:
  - agent → `agents/<filename>`
  - rapplication → existing flow (services/, ui/, eggs/)
  - sense → `utils/senses/<filename>`
- `CONSTITUTION.md`: new **Article XXXI — Three Stores, Three Artifacts** formalizing the model. Article XXVII gets a forward-reference to XXXI rather than rewriting (preserves history).
- `rapp_brainstem/agents/`: add `binder_agent.py` (per the issue [#22](https://github.com/kody-w/RAPP/issues/22) already filed) — chat-callable surface for the binder service, now three-source aware.

### 4.5 `kody-w/rapp-installer` — out of scope

The one-line install script remains as is. Mentioned for completeness.

## 5. The submission routing agent

A single bare agent in RAR — `@rapp/rapp_publish_agent` — is the public entry point for any artifact submission. It:

1. Accepts a path / URL / inline source.
2. Detects artifact type (presence of `BasicAgent` + `perform()` → agent; presence of `manifest.json` with `rapp-application/1.0` → rapplication; presence of `name`/`delimiter`/`response_key`/`wrapper_tag`/`system_prompt` and no `BasicAgent` → sense).
3. Routes to the correct repo's `[X]` issue flow per Article XXIX.

This **replaces and supersedes** the existing `publish_to_rapp_store_agent.py` (which is rapp-only). The existing agent file is deleted; references update to point at `@rapp/rapp_publish_agent` in RAR.

Why one agent across all three: the user shouldn't have to know which store their artifact belongs in. The agent classifies. Same UX as `git push` — one command, infrastructure routes the bytes.

## 6. The unified browse surface

`kody-w.github.io/RAPP_Store/` becomes the **front door for the entire ecosystem.**

- `index.html` (landing page) — gateway with three sections: agents (RAR), rapplications (this repo), senses (RAPP_Sense_Store). Counts pulled live from each catalog.
- `vbrainstem.html` (chat) — already loads `StoreNavigator` from RAR. Extended to query all three catalogs. The model gains tools for `search_agents`, `search_rapplications`, `search_senses`. One chat surface, three-store knowledge.
- `ecosystem.json` (aggregated catalog) — built by a new workflow that periodically merges the three catalog files into one canonical aggregate. External consumers (Copilot tools, search engines, third-party brainstems) hit one URL.

The other two stores keep their own landing pages — they're the **submission-side entry points** (where you land if you Googled "how do I submit a sense"). The presentation aggregator is a convenience, not a replacement.

## 7. Migration plan

Each step is its own implementation PR linking back to this proposal.

| | Step | Repo | Mechanism |
|---|---|---|---|
| A | Bootstrap RAPP_Sense_Store (SPEC, scripts, workflows, README) | `kody-w/RAPP_Sense_Store` | PR (this proposal's companion) |
| B | Migrate 5 senses from RAPP_Store/senses/ → RAPP_Sense_Store/senses/@rapp/ via `[SENSE]` issue flow | `kody-w/RAPP_Sense_Store` | 5 issues |
| C | Drop `senses/` from RAPP_Store after the 5 land in RAPP_Sense_Store | `kody-w/RAPP_Store` | PR |
| D | Publisher-namespace existing rapps: move 7 root-level dirs under `apps/@rapp/` and update index.json URLs | `kody-w/RAPP_Store` | PR (breaking — old install URLs 404) |
| E | Add `rapp_publish_agent.py` to RAR; deprecate `publish_to_rapp_store/` | `kody-w/RAR`, `kody-w/RAPP_Store` | RAR `[AGENT]` issue + RAPP_Store cleanup PR |
| F | Update brainstem's binder_service.py to know about all three sources; add `binder_agent.py` (closes RAPP#22) | `kody-w/RAPP` | PR |
| G | Constitutional amendment: Article XXXI (Three Stores, Three Artifacts) | `kody-w/RAPP` | PR |
| H | RAPP_Store landing + vBrainstem extended to aggregate all three catalogs | `kody-w/RAPP_Store` | PR |

## 8. How they all work together (the runtime story)

A user landing on `kody-w.github.io/RAPP_Store/` (the front door):

1. Sees three columns: **agents · rapplications · senses**, with live counts pulled from each store's catalog.
2. Clicks an entry. The vBrainstem loads the artifact (regardless of type) into its chat surface.
3. Opens the binder agent in chat: *"install eli5 sense and bookfactory rapplication"*. The binder agent fetches both, places each in the right brainstem directory (utils/senses/ for sense, agents/+services/+ui/ for rapplication).
4. Decides to submit their own thing. Drops a file at the publish agent: *"submit this for me"*. The agent detects type, opens the correct `[X]` issue in the correct repo via Article XXIX.

The constitution + the four constitutional articles already in place (XXVII, XXVIII, XXIX, XXX) cover the governance:

- **XXVII (extended by XXXI)** — what artifact goes where (mechanical).
- **XXVIII** — material changes need proposals (this is one).
- **XXIX** — submission flows are the front door.
- **XXX** — once a proposal is accepted, the AI executes the migration end-to-end.

## 9. Rollback

Each step's PR is a `git revert` away from undone in its own repo. The destructive moments:

- **Step C** (delete `senses/` from RAPP_Store): rollback is restoring the directory from git history; the senses also live in RAPP_Sense_Store at that point so no data loss.
- **Step D** (move rapps to `apps/@rapp/`): rollback is moving them back. Catalog URLs would re-break for anyone who installed from the new path during the window.
- **Step G** (constitutional amendment): rollback is removing Article XXXI; Article XXVII still covers the two-store case as a strict subset.

The non-destructive steps (A, B, E, F, H) only add capability and can be left in place even if the rest of the migration is paused.

## 10. Open questions

1. **`StoreNavigator` already lives in RAR as `@rapp/store_navigator_agent` and only knows about RAPP_Store.** Rename to `@rapp/ecosystem_navigator` and extend to all three? Or keep it scoped (`store_navigator` for rapps, add `agent_navigator` and `sense_navigator`, then a top-level `ecosystem_navigator` that delegates)? Leaning toward one extended navigator that takes a `scope` parameter.
2. **Do we run RAPP_Store's vBrainstem against the RAR-hosted navigator, or vendor an aggregator copy?** The current pattern (vBrainstem fetches from RAR) is the right one — keeps RAR as canonical source.
3. **Per-channel sense activation**: how does the brainstem know which channels are active for a given request? Probably via the chat client's `Accept-Surfaces: voice,chat` header (or similar). Specify in the brainstem's binder service update (step F).
4. **Auto-pruning the ecosystem aggregate**: should `ecosystem.json` rebuild on push to any of the three repos, or on a schedule? Recommend: on push to any catalog, via cross-repo `repository_dispatch`.

## 11. References

- Constitution: [Article XVI](https://github.com/kody-w/RAPP/blob/main/CONSTITUTION.md#article-xvi--the-root-is-the-engines-public-surface-the-brainstems-workspace-is-separate), [XXIV](https://github.com/kody-w/RAPP/blob/main/CONSTITUTION.md#article-xxiv--senses-are-agent-first-frontends-are-modular-consumers), [XXVII](https://github.com/kody-w/RAPP/blob/main/CONSTITUTION.md#article-xxvii--rar-holds-files-the-rapp-store-holds-bundles), [XXVIII](https://github.com/kody-w/RAPP/blob/main/CONSTITUTION.md#article-xxviii--material-changes-are-proposed-before-theyre-applied), [XXIX](https://github.com/kody-w/RAPP/blob/main/CONSTITUTION.md#article-xxix--use-the-upstreams-front-door), [XXX](https://github.com/kody-w/RAPP/blob/main/CONSTITUTION.md#article-xxx--pipelines-run-end-to-end-under-standing-authorization)
- [Proposal 0001 (RAR vs rapp_store split)](https://github.com/kody-w/RAPP_Store/blob/main/docs/proposals/0001-rar-vs-rapp-store-split.md) — foundation this proposal extends.
- [RAPP issue #22 (binder agent missing)](https://github.com/kody-w/RAPP/issues/22) — covered in step F.
- Three repos: [RAPP](https://github.com/kody-w/RAPP), [RAR](https://github.com/kody-w/RAR), [RAPP_Store](https://github.com/kody-w/RAPP_Store), [RAPP_Sense_Store](https://github.com/kody-w/RAPP_Sense_Store).
