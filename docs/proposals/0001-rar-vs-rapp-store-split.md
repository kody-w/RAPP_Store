# Proposal 0001 — RAR vs rapp_store split + migration

| | |
|---|---|
| **Status** | Draft |
| **Sponsor** | @kody-w |
| **Drafted** | 2026-04-27 |
| **Touches** | `index.json`, `SPEC.md` §6, `scripts/lib_rapp.py`, several rapp directories, `kody-w/RAPP` `CONSTITUTION.md` (Articles XXVII–XXIX) |
| **Complies with** | `kody-w/RAPP` `CONSTITUTION.md` Article XXVIII (proposals before changes) and Article XXIX (use the upstream's front door) |

## 1. Context

`rapp_store/index.json` currently holds 35 entries. Of those:

- **22** are `rarbookworld-*` sub-personas of the BookFactory and MomentFactory composite rapps. They already exist in `kody-w/RAR` under `@rarbookworld/<slug>` (registry entries plus actual `agents/@rarbookworld/<slug>_agent.py` files). The rapp_store catalog hosting them duplicates RAR's role.
- **7** are bare `*_agent.py` files: `learn_new`, `swarm_factory`, `pitch_deck`, `vibe_builder`, `execbrief`, `momentfactory`, `publish_to_rapp_store`. They have no `manifest.ui`, no `manifest.service`, no `eggs/`. The user installs one file. RAR's exact use case.
- **1** is `bookfactoryagent-demo` — appears to be cruft from the early extraction.
- **5** are senses (`tldr_sense.py` etc.). These are a third artifact type entirely, governed by Article XXIV. Out of scope for this proposal.

That leaves **6 entries** that are actual rapplications (agent + UI / service / eggs): `binder`, `dashboard`, `kanban`, `swarms`, `webhook`, `bookfactory`. (Plus `twin_workshop` once it's brought to spec.)

A store sells finished products. A registry indexes building blocks. They serve different users, want different metadata, and want different browse paths. Keeping bare agents and rapplications in one catalog has produced a list where ~80% of entries are noise to the end user.

## 2. Proposed change

Codify the split in the constitution (Articles XXVII–XXIX, separate proposal in `kody-w/RAPP`), then groom the catalog in this repo:

> **Bundle (agent + UI / service / eggs) → rapp_store. Bare agent.py → RAR. Senses → their own home (Article XXIV).**

### 2.1 Per-entry classification

| Entry | Has UI | Has service | Has eggs | Verdict |
|---|---|---|---|---|
| binder | — | ✓ | — | rapp_store |
| dashboard | — | ✓ | — | rapp_store |
| kanban | — | ✓ | — | rapp_store |
| swarms | — | ✓ | — | rapp_store |
| webhook | — | ✓ | — | rapp_store |
| bookfactory | ✓ | — | ✓ | rapp_store |
| twin_workshop | ✓ | — | — | rapp_store *(needs spec compliance — see step F)* |
| `learn_new` | — | — | — | **→ RAR** |
| `swarm_factory` | — | — | — | **→ RAR** |
| `pitch_deck` | — | — | — | **→ RAR** |
| `vibe_builder` | — | — | — | **→ RAR** |
| `execbrief` | — | — | — | **→ RAR** |
| `momentfactory` | — | — | — | **→ RAR** |
| `publish_to_rapp_store` | — | — | — | **→ RAR** |
| `rarbookworld-*` (×22) | — | — | — | **→ RAR** *(already there; just delete from index.json)* |
| `bookfactoryagent-demo` | — | — | — | **drop (cruft)** |

Final rapp_store catalog: **7 entries** (`binder`, `dashboard`, `kanban`, `swarms`, `webhook`, `bookfactory`, `twin_workshop`).

### 2.2 Validator enforcement

`scripts/lib_rapp.py` gains an error code `E_BARE_AGENT_BELONGS_IN_RAR`. The validator rejects any submission whose manifest declares neither `ui` nor `service` and ships no `eggs/`. The rejection comment links the submitter to RAR's `[AGENT]` issue flow with a copy-pasteable example. Federation submissions are checked the same way: the receiver inspects the *source* repo's manifest before staging.

`SPEC.md` §6 gets a corresponding rule (rule 11) enumerating the new error code.

## 3. Migration steps

Each step is its own implementation PR in this repo (or, for step D, issues on `kody-w/RAR`). Each PR/issue links back to this proposal.

| | Step | Repo | Mechanism |
|---|---|---|---|
| A | Add `E_BARE_AGENT_BELONGS_IN_RAR` to validator + tests | `kody-w/rapp_store` | PR |
| B | Drop the 22 `rarbookworld-*` entries from `index.json` (already in RAR) | `kody-w/rapp_store` | PR |
| C | Drop `bookfactoryagent-demo` entry from `index.json` | `kody-w/rapp_store` | PR (can fold into B) |
| D | Submit the 7 bare agents to RAR via **RAR's actual `[AGENT]` issue flow** (Article XXIX) | `kody-w/RAR` | one issue per agent |
| E | After D lands: delete the 7 directories from rapp_store, remove their `index.json` entries; install URL becomes the RAR registry path | `kody-w/rapp_store` | PR (one or many) |
| F | Bring `twin_workshop` to spec: add `manifest.json`, `index_entry.json`, `README.md` | `kody-w/rapp_store` | PR |
| G | Lock the category enum in `SPEC.md` and validator: `productivity`, `creative`, `analysis`, `data`, `integration`, `platform`, `workspace`. Remap existing entries | `kody-w/rapp_store` | PR |
| H | Make `quality_tier` load-bearing: `featured` (≤7), `community` (default for federation submissions), `experimental` (warned), `deprecated` (hidden, installable) | `kody-w/rapp_store` | PR |

### 3.1 Step D — RAR submission protocol

Per Article XXIX, every migration to RAR uses RAR's documented submission flow exactly as an outside contributor would. Concretely:

1. For each of the 7 bare agents, open an issue on `kody-w/RAR` with title `[AGENT] @rapp/<slug>` (the `@rapp/` namespace override needs maintainer acceptance — see RAR's `process_issues.py` rule).
2. Body contains a fenced ` ```python ` block with the agent's full source (RAR's parser detects `__manifest__` and stages it as `submit_agent`).
3. Issue body links back to this proposal: `Migrating from rapp_store per [Proposal 0001](https://github.com/kody-w/RAPP_Store/blob/main/docs/proposals/0001-rar-vs-rapp-store-split.md).`
4. RAR's `process-issues.yml` validates and stages to `staging/@rapp/<slug>_agent.py`.
5. Maintainer adds the `approved` label; RAR's `approve-agent.yml` promotes to `agents/@rapp/<slug>_agent.py` and republishes `registry.json`.
6. Only after the RAR side has landed do we do step E in this repo.

We do **not** push directly to RAR's `agents/` directory or hand-edit `registry.json`. The submission API is the contract, and exercising it surfaces real bugs an outside submitter would hit.

## 4. Rollback

- Steps A–C and E–H are git-revertable in this repo.
- Step D is additive on RAR; rolling back means closing the RAR issues / reverting the RAR promotions. Standard git revert applies on RAR.
- The destructive moment is step E (deletion from rapp_store). If the RAR side is missing or broken, install URLs in older brainstems break. Mitigation: don't run step E until step D has landed and been smoke-tested.
- If the migration is aborted between D and E, the catalog has temporary duplicate entries (rapp_store + RAR). Annoying, not broken.

## 5. Open questions

1. **`@rapp` publisher namespace acceptance on RAR.** RAR's process_issues.py requires the issue creator's GitHub login to match the publisher — unless a maintainer explicitly accepts the override. The maintainer (`@kody-w`) does both repos, so this is a one-time grant. Worth confirming the RAR workflow handles this cleanly the first time.
2. **`publish_to_rapp_store` placement.** By the rule, it belongs in RAR. That's slightly awkward (it's the agent that submits *to this store*), but the rule wins. RAR is its home.
3. **Senses cataloguing.** Out of scope here, but eventually they need a home — own SPEC, own catalog file, or move under `kody-w/RAPP/rapp_brainstem/senses/` per Article XXIV. Tracking as a follow-up proposal.

## 6. References

- `kody-w/RAPP` `CONSTITUTION.md` Article III (Single File Agents) — defines what a bare agent is.
- `kody-w/RAPP` `CONSTITUTION.md` Article XXIV (Senses Are Agent-First) — covers the senses tier explicitly excluded from this proposal.
- `kody-w/RAPP` `CONSTITUTION.md` Article XXVII (RAR Holds Files; the Rapp Store Holds Bundles) — this proposal's primary rule.
- `kody-w/RAPP` `CONSTITUTION.md` Article XXVIII (Material Changes Are Proposed Before They're Applied) — the rule this proposal complies with.
- `kody-w/RAPP` `CONSTITUTION.md` Article XXIX (Use the Upstream's Front Door) — applies to step D.
- `kody-w/rapp_store` `SPEC.md` §6 — the validation rules updated by step A.
- `kody-w/RAR` `scripts/process_issues.py` — the submission parser that step D feeds.
