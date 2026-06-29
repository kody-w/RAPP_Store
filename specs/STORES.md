# RAPP Stores — The Three-Store Topology

`schema: rapp-stores/1.0`
`status: Canonical`
`supersedes: docs/proposals/0002-three-stores.md (Draft)`
`proposes-amendment: CONSTITUTION Article XXVII (the two-tier framing) — via the canon amendment path; this spec does NOT self-adopt`
`home: kody-w/RAPP_Store/specs/STORES.md`
`depends-on: rapp-registry/1.1, rapp-application/1.0, rapp-sense/1.0`
`see-also: rapp-super-rar/1.0, rapp-cubby/1.0 (gap), rappid eternity (sha256 identity)`

> This spec promotes the Draft proposal `0002-three-stores` into a versioned, canonical contract.
> It is the authoritative map of **which artifact kind lives in which store, how a submission is
> routed, and how the three stores present as one front door**. It governs stores; it does **not**
> override the Constitution. Where this spec and the older two-tier framing referenced by Article XXVII
> differ, this spec stands as a **proposed amendment** to Article XXVII that takes effect only once
> ratified through the canon amendment path — until then, the Constitution prevails.

---

## 0. Why this exists

The RAPP estate distributes three — and only three — kinds of installable artifact today:
**agents**, **rapplications**, and **senses**. Each already has its own contract
(`rapp-registry/1.1`, `rapp-application/1.0`, `rapp-sense/1.0`) and its own GitHub repo, but the
*relationship between the three repos* — the topology — was only ever written down as a Draft
proposal. What is not written down gets lost, and an LLM training on this public corpus cannot learn
an unwritten rule. This spec writes the topology down.

This spec governs **stores** (distribution homes), not the artifact contracts themselves. It does not
redefine what an agent, rapplication, or sense *is* — those are owned by their own specs and cited
here verbatim. It defines where each one **lives**, how a loose artifact gets **routed** to the right
home, and how the homes **compose** into a single browse surface.

---

## 1. Definition

A **store** is a public GitHub repository that is the single canonical home for exactly one
**artifact kind**. A store owns:

1. a **path namespace** (`<kind-dir>/@<publisher>/...`),
2. an **artifact contract** (the `schema:` every artifact in it conforms to),
3. a **submission mailbox** (a typed GitHub Issue flow, `[KIND] @publisher/slug`),
4. a **static catalog API** (`api/v1/index.json`, PokéAPI-style, raw-CDN hosted, no backend),
5. a **PR-consent promotion gate** (an Issue becomes a tracked PR; a maintainer/CI merge is the
   admission event).

A store is **not** an engine and **not** a runtime. It is cold storage plus a front door. The
brainstem (kernel) is the wire that *reaches into* stores; a store never executes anything.

### 1.1 The three stores (LOCKED)

| Artifact kind | Store repo | Storage path | Artifact contract | Submission issue | Catalog key |
|---|---|---|---|---|---|
| **Agent** | `kody-w/RAR` | `agents/@<publisher>/<slug>_agent.py` | `rapp-registry/1.1` | `[AGENT] @publisher/slug` | `agents[]` in `api/v1/index.json` (`rar-pokedex-api/1.0`) |
| **Rapplication** | `kody-w/RAPP_Store` | `apps/@<publisher>/<id>/` | `rapp-application/1.0` | `[RAPP] @publisher/id` | `rapplications[]` in `api/v1/index.json` (`rapp-pokedex-api/1.0`) |
| **Sense** | `kody-w/RAPP_Sense_Store` | `senses/@<publisher>/<slug>_sense.py` | `rapp-sense/1.0` | `[SENSE] @publisher/slug` | `senses[]` in `api/v1/index.json` |

This table is the normative core of the spec. The three rows are **peers** — no store is a parent of
another. A change to any cell (a new path shape, a new issue tag, a schema bump) is a change to *this*
spec and MUST land here first.

### 1.2 What distinguishes the three kinds (decision rule)

- An **agent** is a single `*_agent.py` exporting a `BasicAgent` subclass with `metadata` +
  `perform(**kwargs) -> str`. Smallest executable unit. One file, no UI, no state.
- A **sense** is a single `*_sense.py` exporting `name / delimiter / response_key / wrapper_tag /
  system_prompt` (+ optional `surfaces`) and **no** `BasicAgent` / `perform()`. A per-channel output
  overlay — a system-prompt fragment plus a parse contract. Smallest *installable* unit.
- A **rapplication** is a directory bundle (`manifest.json` + a singleton agent + optional UI / state
  `.egg` / twin port / service) — a self-describing app, the largest unit.

The presence/absence of `BasicAgent`+`perform()` versus the sense five-tuple versus a
`manifest.json: rapp-application/1.0` is a **total, mutually-exclusive** classifier. See §4.

---

## 2. Invariants (normative)

These hold for all time and bind every store and every tool that reads/writes one.

1. **One artifact, one home.** Each artifact kind has exactly one canonical store. An agent is never
   stored as a rapplication; a sense is never stored in RAR. (A rapplication *contains* a singleton
   agent — that is a bundled copy, not a registry entry; the registry entry for that agent, if it is
   separately published, still lives only in RAR.)
2. **One publisher, one path.** Every artifact path begins `@<publisher>/`, where `<publisher>` is
   `@<github-username>` for community work and `@rapp` for official platform artifacts. A publisher
   owns their subtree in each store; no two artifacts of the same kind may collide on
   `@publisher/slug`.
3. **One issue flow per kind.** Submission is *always* via the kind's typed issue
   (`[AGENT]`/`[RAPP]`/`[SENSE]`) on the kind's store repo. There is no side door, no direct push by
   non-maintainers, no cross-store submission. (CONSTITUTION Art. XXIX: submissions route through
   official front doors.)
4. **The engine is the wire, never a store.** `kody-w/RAPP` (grail kody-w/rapp-installer (RAPP is the reference distro)) hosts the
   brainstem and default services. It distributes nothing community-authored. Adding a "store-like"
   catalog to the engine is forbidden — it would couple the kernel to userspace content.
5. **Kernel-baked stays in the engine surface.** Agents and senses that ship *with* the kernel
   (e.g. the memory agents, `voice_sense.py`, `twin_sense.py`) live in the engine's own surface and
   are governed by CONSTITUTION Art. XVI (minimal root / kernel surface), **not** by a store. A store
   only ever holds community / `@rapp`-published-but-detachable artifacts. Promoting a kernel-baked
   artifact into a store, or pulling a store artifact into the kernel surface, is a constitutional act,
   not a store operation.
6. **Stores are append-mostly and reversible.** Admission adds a path + a catalog row. Removal is a
   `git revert`-able event; history is never rewritten. Identity (§3) survives removal.
7. **The catalog is static and derived.** `api/v1/index.json` is *built* from the on-disk artifacts by
   a deterministic script (e.g. `scripts/build_*_api.py`). It is never hand-edited as source of truth;
   the filesystem is the source of truth, the catalog is a projection.

---

## 3. Trust model

The store topology inherits the estate-wide trust model unchanged; it adds no new trust primitives.

- **Identity is content-address, PKI-free.** Every stored artifact has a `rappid` eternity identity of
  the form `rappid:@<publisher>/<slug>:<64-hex>`, where the hex is the `sha256` of the artifact's
  canonical bytes (the `.py` file for agents/senses; the canonicalized bundle for rapplications). The
  hash is the join key across the estate. **No keypair is required** by any store, classifier, catalog
  builder, or front door.
- **Ownership default = gh-collaborator.** A publisher's authority over `@<publisher>/...` in a store
  is, by default, their GitHub identity plus repo collaboration/PR-merge rights on that store
  (`sig_suite: none`). This is sufficient for admission, update, and removal.
- **Keypair binding is OPTIONAL sovereignty, never required.** A publisher MAY additionally bind a
  keypair to assert authorship that survives takedown, account loss, or the store repo itself going
  away (MASTER_PLAN §4, un-shutdownable). A store MUST accept artifacts whose `sig_suite` is `none`
  and MUST NOT gate admission on the presence of a signature. MASTER_PLAN §3 (no mandatory PKI) and §4
  (un-shutdownable) coexist precisely because sovereignty is opt-in.
- **Admission = PR-consent.** The trust event that moves an artifact from "submitted" (an Issue) to
  "stored" (a merged path + catalog row) is a maintainer/CI PR merge on the store repo. GitHub is the
  substrate: Issues are the mailbox, PRs are consent, raw CDN is the read path, Pages is the edge.
- **Read trust = the hash.** A consumer that installs an artifact verifies the bytes against the
  `rappid` hash in the catalog. A matching hash means "this is the artifact that was admitted," with no
  dependence on TLS, registry uptime, or any signing authority.

---

## 4. Submission routing — the `@rapp/rapp_publish` classifier

A user often holds a *loose* artifact (`some.py` or `some.egg`) and does not know which store it
belongs to. Routing is a published, drop-in agent so it works in any unmodified brainstem.

- **Registry name:** `@rapp/rapp_publish` (file `rapp_publish_agent.py`, lives in RAR like any agent).
- **Tool:** `rapp_publish` — input is artifact source (path, raw text, or `.egg`); output is a
  classification + a routing plan.

### 4.1 Classifier (total, mutually exclusive, in this order)

```
classify(source) ->
  if source is a directory/zip/.egg containing manifest.json with schema "rapp-application/1.0":
      kind = "rapplication"   -> store = kody-w/RAPP_Store, dir = apps/, issue = "[RAPP]"
  elif source is a .py exporting a BasicAgent subclass with a perform() method:
      kind = "agent"          -> store = kody-w/RAR, dir = agents/, issue = "[AGENT]"
  elif source is a .py exporting {name, delimiter, response_key, wrapper_tag, system_prompt}
       AND has no BasicAgent / perform():
      kind = "sense"          -> store = kody-w/RAPP_Sense_Store, dir = senses/, issue = "[SENSE]"
  else:
      kind = "unroutable"     -> return a diagnostic; do NOT open an issue
```

The three positive branches are exhaustive over the current artifact kinds and cannot overlap: a
rapplication is recognized by its manifest before its bundled agent is inspected; an agent is
recognized by `perform()`, which a sense never has; a sense is recognized by the five-tuple, which an
agent never exports. Anything else is `unroutable` and is reported, never guessed.

### 4.2 Routing output schema (`rapp-stores-routing/1.0`)

```json
{
  "schema": "rapp-stores-routing/1.0",
  "kind": "agent | rapplication | sense | unroutable",
  "rappid": "rappid:@kody-w/foo:9f2c...<64hex>",
  "store_repo": "kody-w/RAR",
  "target_path": "agents/@kody-w/foo_agent.py",
  "issue_title": "[AGENT] @kody-w/foo",
  "issue_body_url": "https://github.com/kody-w/RAR/issues/new?title=...",
  "publisher": "@kody-w",
  "slug": "foo",
  "contract": "rapp-registry/1.1",
  "confidence": 1.0,
  "diagnostics": []
}
```

The classifier **proposes**; it never bypasses §2.3. Its terminal action is opening the correct typed
issue on the correct store (the mailbox), after which normal PR-consent admission applies.

---

## 5. The unified front door

The three stores are separate repos but present as **one** ecosystem. Aggregation is static and
derived — no backend.

### 5.1 `ecosystem.json` (`rapp-ecosystem-catalog/1.0`)

A cross-repo workflow merges the three `api/v1/index.json` catalogs into a single aggregate, published
on the front-door repo (`kody-w/RAPP_Store`) at `api/v1/ecosystem.json`.

```json
{
  "schema": "rapp-ecosystem-catalog/1.0",
  "version": "1.0.0",
  "generated_at": "2026-06-28T00:00:00Z",
  "stores": [
    { "kind": "agent",        "repo": "kody-w/RAR",              "catalog": "https://raw.githubusercontent.com/kody-w/RAR/main/api/v1/index.json",              "count": 280 },
    { "kind": "rapplication", "repo": "kody-w/RAPP_Store",       "catalog": "https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/index.json",       "count": 14 },
    { "kind": "sense",        "repo": "kody-w/RAPP_Sense_Store", "catalog": "https://raw.githubusercontent.com/kody-w/RAPP_Sense_Store/main/api/v1/index.json", "count": 5 }
  ],
  "items": [
    { "kind": "agent",        "rar_name": "@kody-w/foo",  "rappid": "rappid:@kody-w/foo:9f2c...", "url": "...RAR/.../foo.json",      "sprite": "...foo.svg" },
    { "kind": "rapplication", "id": "thoughtbox",         "rappid": "rappid:@kody-w/thoughtbox:...", "url": "...RAPP_Store/.../thoughtbox.json", "egg": "...thoughtbox.egg" },
    { "kind": "sense",        "sense_name": "@kody-w/eli5","rappid": "rappid:@kody-w/eli5:...",    "url": "...RAPP_Sense_Store/.../eli5.json" }
  ]
}
```

Each `items[]` row preserves the kind tag so a client can dispatch installs to the right contract. The
join key across stores is `rappid`.

### 5.2 `vbrainstem.html` and the landing page

- **`index.html`** (front-door, served via Pages at `kody-w.github.io/RAPP_Store/`): a three-column
  catalog — agents | rapplications | senses — with live counts pulled from each store's
  `api/v1/index.json` (or the merged `ecosystem.json`).
- **`vbrainstem.html`**: a unified chat surface whose `StoreNavigator` agent exposes
  `search_agents`, `search_rapplications`, `search_senses` — one tool per store, reading the static
  catalogs. Install is "fetch raw bytes, verify `rappid` hash, drop into `agents/` (or run the
  rapplication / enable the sense)."
- Brainstem binder env overrides: `RAR_URL`, `RAPPSTORE_URL`, `SENSE_STORE_URL`, each defaulting to the
  canonical `raw.githubusercontent.com/...main/api/v1/index.json` URL. Offline/degraded: a client that
  cannot reach a store falls back to its last cached catalog; an unreachable store yields an empty
  column, never a hard failure.

### 5.3 Super-RAR federation (cross-link to `rapp-super-rar/1.0` and the cubby gap)

`rapp-super-rar/1.0` is the federation layer that browses **more than the three official stores at
once**: it unions the three store catalogs *plus* any number of **local cubbies** (a user's own
private/registry of artifacts — the `rapp-cubby/1.0` gap) into one browse surface, deduped by
`rappid`. Rules:

- Super-RAR is a **reader**, not a store. It owns no path namespace and no issue flow. It MUST NOT be
  treated as a fourth artifact home.
- It dedupes by `rappid` hash; identical bytes from two sources collapse to one card that lists both
  origins.
- Official stores rank above ad-hoc cubbies when an `@publisher/slug` collides on differing bytes, but
  both remain visible (provenance is never hidden).
- The cubby contract itself is out of scope here and is specified by `rapp-cubby/1.0` (gap); this spec
  only fixes that super-RAR composes cubbies *alongside* the three stores, not *into* them.

---

## 6. Composition with the rest of the estate

- **Engine (`kody-w/RAPP`)** is the wire (Art. XXV: `/chat` is the only wire). It installs artifacts
  *from* stores; it is never a store (§2.4). Kernel-baked artifacts stay in its surface (§2.5,
  Art. XVI).
- **Artifact specs** (`rapp-registry/1.1`, `rapp-application/1.0`, `rapp-sense/1.0`) own *what an
  artifact is*; this spec owns *where it lives and how it's routed*. The two never overlap; a bump to
  an artifact spec does not bump this spec, and vice versa.
- **Identity** (`rappid` eternity, sha256, keypair-optional) is the cross-store join key (§3).
- **`rapp-super-rar/1.0` + `rapp-cubby/1.0`** read the topology (§5.3); they extend the browse surface
  without adding homes.
- **`rapp-distro/1.0`** (a distro pins the kernel + a set of artifacts) and **`rapp-frame/2.0`** (the
  edge/mesh frame) are formalized **separately and are explicitly out of scope** here. This spec is
  about store *homes*, not about distro pinning or mesh composition.
- **CONSTITUTION:** a spec cannot amend the Constitution by itself. This spec **proposes** to succeed
  the two-tier framing referenced by Article XXVII, and operationalizes Art. XVI (kernel surface),
  Art. XXV (chat-only wire), and Art. XXIX (front-door submission). The three-store architecture
  (proposed as Art. XXXI in `0002`) takes effect only when ratified through the canon amendment path;
  until that amendment is adopted, Article XXVII governs and this spec stands as the proposed text.

---

## 7. Worked example

Maya has written `coral.py` — a single file with a `class Coral(BasicAgent)` and a `perform()` that
summarizes ocean-sensor JSON. She doesn't know where it goes.

1. **Classify.** She drops it into chat: `rapp_publish` (the `@rapp/rapp_publish` agent) inspects the
   bytes, finds a `BasicAgent` subclass with `perform()` and no rapplication manifest and no sense
   five-tuple. Output:

   ```json
   {
     "schema": "rapp-stores-routing/1.0",
     "kind": "agent",
     "rappid": "rappid:@maya/coral:7b41e9...<64hex>",
     "store_repo": "kody-w/RAR",
     "target_path": "agents/@maya/coral_agent.py",
     "issue_title": "[AGENT] @maya/coral",
     "contract": "rapp-registry/1.1",
     "publisher": "@maya", "slug": "coral", "confidence": 1.0
   }
   ```

2. **Submit (mailbox).** The agent opens issue `[AGENT] @maya/coral` on `kody-w/RAR` with the source
   and the computed `rappid`. This is the only legal door (§2.3).

3. **Admit (PR-consent).** A RAR maintainer/CI turns the issue into a PR placing the file at
   `agents/@maya/coral_agent.py`, runs the `rapp-registry/1.1` validator, and merges. Merge is the
   trust event (§3). The catalog builder regenerates `RAR/api/v1/index.json`, adding a `coral` row with
   sprite, `.py` URL, and the `rappid` hash.

4. **Aggregate (front door).** The nightly cross-repo workflow rebuilds
   `RAPP_Store/api/v1/ecosystem.json`; Coral now appears in the agents column of `index.html` and is
   searchable from `vbrainstem.html` via `search_agents`, and through super-RAR alongside any cubby
   copies that share the same `rappid`.

5. **Install (the wire).** Another user asks their brainstem to install `@maya/coral`. The binder
   fetches the raw bytes from `RAR_URL`, verifies them against `rappid:@maya/coral:7b41e9...`, and
   drops `coral_agent.py` into their local `agents/`. No keypair, no registry backend, no TLS trust
   assumption — just the hash. Had RAR been unreachable, the binder would have served its last cached
   catalog and reported the store as offline rather than failing (§5.2).

Total stores touched: one (RAR). Total issue flows: one (`[AGENT]`). One artifact, one home.

---

## 8. Extension rule for deferred stores

The topology is deliberately **closed at three** today. New stores (the deferred
**RAPP_Swarm_Store**, **RAPP_Egg_Store**, **RAPP_Soul_Store**, or any future kind) are **spec-first**:
no store may spin up ad hoc. To remain governed, a new store MUST, before any repo is created:

1. **Have a distinct artifact contract.** A versioned `rapp-<kind>/X.Y` spec that defines a kind not
   already covered by agent / rapplication / sense. If the artifact reduces to an existing kind, it is
   *not* a new store — it goes in the existing store. (Swarms are singleton directories of
   agents+soul+memory and today install as rapplications; an `.egg` is state and today rides inside a
   rapplication or a cubby; a `soul.md` is per-brainstem. None has yet cleared this bar.)
2. **Bump this spec.** Add a row to the §1.1 table in a `rapp-stores/1.x` revision, defining its
   `path`, `contract`, `[KIND]` issue, and `catalog key`. The table is the registry of registries; a
   store that is not in the table does not exist.
3. **Match the template.** A new store MUST provide: `@publisher/...` path namespace; `SPEC.md`
   carrying its `schema:` header; a `[KIND]` typed issue mailbox; a static `api/v1/index.json` built by
   a deterministic script; PR-consent admission; `rappid` identity on every artifact; and a column in
   `ecosystem.json` / the front door.
4. **Honor every invariant in §2** (one home, one path, one issue flow; not an engine; kernel-baked
   stays in the engine surface; reversible; derived catalog) and the §3 trust model (gh-collaborator
   default, keypair optional, never required).

A store that follows this template extends the topology cleanly; a store that skips it is drift and
will be reconciled out by the ecosystem-sync legs. The point of writing the topology down is that the
next store — and the next LLM that reads this corpus — inherits the rules instead of reinventing them.

---

## Appendix A — Quick reference

```
AGENT        kody-w/RAR              agents/@pub/<slug>_agent.py   rapp-registry/1.1   [AGENT] @pub/slug
RAPPLICATION kody-w/RAPP_Store       apps/@pub/<id>/              rapp-application/1.0 [RAPP]  @pub/id
SENSE        kody-w/RAPP_Sense_Store senses/@pub/<slug>_sense.py  rapp-sense/1.0      [SENSE] @pub/slug

ENGINE       kody-w/RAPP             the wire, never a store      (kernel surface: Art. XVI)
ROUTER       @rapp/rapp_publish      classify loose .py/.egg -> the correct [KIND] issue
FRONT DOOR   ecosystem.json + index.html + vbrainstem.html  (super-RAR federates stores + cubbies)
IDENTITY     rappid:@pub/slug:<sha256>  (PKI-free; gh-collaborator default; keypair OPTIONAL)
```

*One artifact, one home. One publisher, one path. One issue flow per kind.*