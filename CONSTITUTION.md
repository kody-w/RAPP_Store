# RAPP Store — Constitution

> The principles that govern this repo. Read this before you change the catalog,
> the validator, the submission flow, or the surfaces that present them.

[SPEC.md](./SPEC.md) is the wire contract for a rapplication bundle. The
[platform constitution](https://github.com/kody-w/RAPP/blob/main/CONSTITUTION.md)
in `kody-w/RAPP` governs the engine. This document is the **content-layer
authoring discipline** — the rules that keep the store shippable as it grows
from 3 rapps to 3,000.

If anything below conflicts with the platform constitution, the platform wins.

---

## Article 0 — The Catalog Is The Contract

> 📒 **`index.json` is canonical. The files alone are not reachable.**

A rapplication exists if and only if it has an entry in `index.json` whose
`singleton_url` resolves and whose `singleton_sha256` matches. A `.py` file
sitting in `apps/` with no catalog entry is invisible to the brainstem. A
catalog entry whose URL 404s is a broken contract.

Anytime you change a singleton or service file, you **must** also update
`index.json`: bump `version`, recompute `singleton_sha256` /
`singleton_lines` / `singleton_bytes`, and bump the rapp's `manifest.json`.
The validator (`scripts/lib_rapp.py`) and the promotion workflow do this
automatically for staged submissions; for direct edits, you do it by hand.

---

## Article I — This Is The Content Layer

> 🧬 **No engine code lives here. No runtime, no API, no auth, no
> brainstem.**

The brainstem is in `kody-w/RAPP`. Trust/identity is in `kody-w/RAR`.
Senses are in `kody-w/RAPP_Sense_Store`. This repo ships **only** the
catalog, the rapplication bundles, the submission tooling, the validator,
and the static surfaces (`index.html`, `vbrainstem.html`, `submit.html`)
that present them.

If you're tempted to add a server, an API endpoint, a credential store, an
agent runtime, or a database to this repo — stop. The thing you want
belongs upstream in the engine, or it doesn't belong in the platform yet.

### What this rules out

- ❌ A Python server in this repo.
- ❌ Vendoring `BasicAgent`, `call_llm`, or any other engine surface into
  rapplication singletons. Singletons import from the host brainstem at
  load time.
- ❌ Secret storage of any kind. No tokens, no credentials, no `.env`.
- ❌ User accounts. The vBrainstem authenticates against GitHub Models
  using the user's own token; the store itself stores nothing.

---

## Article II — One File Ships, One File Runs

A rapplication's deployable unit is a single `*_agent.py` file that
satisfies SPEC §5. Composite rapps (BookFactory, etc.) author in `source/`
and **build** to a singleton via `tools/build.py`. The singleton is the
ship-time artifact. The `source/` tree is the authoring surface — it is
not what installs.

> **Edits to a generated singleton are blown away on rebuild. Edit
> `source/`, build the singleton, commit both.**

Service rapps (Binder-class) hand-write both `*_agent.py` and
`*_service.py`. They share the one-file-per-surface discipline; the
service is one file, not a package.

---

## Article III — SHA256 Is The Trust Boundary

> 🔐 **There is no signing infrastructure. There is no PKI. There is a
> hash and a URL.**

Every catalog entry pins `singleton_sha256` (and `service_sha256` when a
service ships). The brainstem's binder fetches `singleton_url` and
verifies the hash before installing. Drift between the hash and the file
is a hard install failure — the binder refuses to mount.

This is the entire trust mechanism. It works because:

1. The catalog entry is governed by this repo's review process.
2. The hash binds the entry to a specific byte sequence.
3. The fetch fails closed, not open.

Adding a signing scheme, a key escrow, or a chain-of-trust before this
breaks at scale would be infrastructure load in the wrong place.

---

## Article IV — Federation Over Mirroring

> 🌐 **A submitter's catalog entry may point at their own GitHub repo.
> The store does not become a mirror.**

The `submit_repo` mode of `@rapp/publish-to-rapp-store` adds a
`source: {repo, ref, path, commit_sha}` block to the catalog entry. The
brainstem's binder still installs from `singleton_url` (which uses `ref`,
typically `main`) and verifies SHA256. To publish a new version, the
submitter bumps `manifest.version` in their repo and resubmits; the agent
re-resolves `commit_sha`.

This means the store stays small. We track *what's available* and *whether
it's trustworthy*; we don't host everything.

The `submit_bundle` mode (files copied into `apps/<publisher>/<id>/`)
remains available for submitters who want the store to host their files.
Both modes pass the same validator.

---

## Article V — Bundles Belong Here, Bare Agents Go To RAR

> 📦 **A rapplication has at least one of: UI, service, eggs. A bare
> `*_agent.py` is not a rapplication.**

Per [Proposal 0001](./docs/proposals/0001-rar-vs-rapp-store-split.md),
single-file agents with no UI / service / eggs go to
[`kody-w/RAR`](https://kody-w.github.io/RAR/) (the agent registry). They
have a different audience and a different submission flow.

The store sells finished products. The registry indexes building blocks.
A submission that looks like a registry entry is rejected by the
validator with a pointer to RAR.

---

## Article VI — Publisher Namespacing Is Mandatory

Every rapplication lives at `apps/@<publisher>/<id>/`. There is no
root-level rapp directory. `@rapp` is reserved for official content;
community publishers use their GitHub username (`@<github-username>`).

Two publishers can claim the same `id` without collision because the path
namespaces them. The catalog's top-level `id` field is the public handle
and must be unique across the catalog — collisions are resolved by the
review process, not by the directory layout.

---

## Article VII — Reserved IDs Are Reserved Forever

The IDs listed in `RESERVED_IDS` (`scripts/lib_rapp.py`) cannot be claimed
by community publishers. Today: `binder`, `dashboard`, `kanban`, `swarms`,
`webhook`, `vibe_builder`, `learn_new`, `swarm_factory`, `senses`,
`publish_to_rapp_store`. Removing an entry from this list does not free
the name — once an ID is reserved or used, it stays bound to its
publisher.

A reserved ID may be removed from the live catalog (as `binder` /
`dashboard` / `kanban` / `swarms` / `webhook` / `twin_workshop` were on
2026-04-28) without releasing the namespace.

---

## Article VIII — The Validator Is The Single Source Of Truth

`scripts/lib_rapp.py` defines what a valid rapplication looks like. SPEC.md
documents it; the validator enforces it. Both the publish agent (local
pre-flight) and the receiver workflow (issue → staging) call the same
validator.

> **If the validator passes a bundle, the bundle is valid. If you think
> it's wrong, fix the validator and the spec in the same PR.**

Tests in `tests/test_lib_rapp.py`, `tests/test_publish_agent.py`,
`tests/test_receiver.py` lock current behavior. Run `python3 -m pytest
tests/` before any change to validation logic.

---

## Article IX — Eggs Are Immutable

A `.egg` is a zip cartridge with `manifest.json` (`schema:
"rapp-egg/1.0"`, `type: "rapplication"`) plus optional `agent.py`,
`service.py`, `ui/...`, `state/...`. The binder service exports/imports
them.

> **Eggs are immutable. Never overwrite an existing egg file.** New state
> ships as a new egg with a new filename.

Path-traversal guards in `binder_service.py` reject `..` segments on
import. Preserve those when editing.

---

## Article X — Quality Tiers Are Earned

The `quality_tier` field is `"official"` or `"community"`. `"official"`
means published by `@rapp`, reviewed end-to-end, and committed to long-
term maintenance. `"community"` means it passes the validator and a
human-eyeballed review, but the publisher owns the maintenance burden.

> **A community rapp does not become official by self-declaration.** The
> tier is set by the reviewer at promotion time, not by the submitter's
> manifest.

Featured placement (the editorial picks on `index.html`) is a separate
axis from quality tier. A community rapp can be featured; an official rapp
need not be.

---

## Article XI — Senses Are Co-Shelved, Not Mirrored

Per [Proposal 0002](./docs/proposals/0002-three-stores.md), senses live in
their own home (`kody-w/RAPP_Sense_Store`). The `senses[]` block in
`index.json` and the `senses/` directory in this repo are a **co-shelving
convenience** for the vBrainstem — they are read directly from raw URLs,
not mirrored from the sense store.

If those raw URLs ever drift, the store does not patch — it points at the
real source. This applies to RAR (`StoreNavigator` and other
RAR-resident agents loaded by the vBrainstem) too.

---

## Article XII — The Pages App Is The Front Door

> 🚪 **User-facing nav links go to `kody-w.github.io/<repo>/`, not
> `github.com/kody-w/<repo>`.**

Sending a user to the GitHub repo browser when they want the store, the
catalog, or the vBrainstem is a UX failure. The Pages app *is* the store;
the repo is the development substrate.

Exceptions:
- Issue-submission links must go to `github.com/<repo>/issues/new` —
  Pages can't create issues.
- Rendered Markdown docs (SPEC.md, SKILL.md, this file, the platform
  Constitution) link to `github.com/<repo>/blob/main/<file>.md` — Pages
  serves `.md` as raw text; github.com renders it.
- Programmatic source-fetch URLs (`raw.githubusercontent.com`,
  `RAW_BASE`) are not user-facing and stay raw.

---

## Article XIII — Defer To The Platform Constitution

This document covers the content layer. Everything about how the brainstem
runs, what counts as kernel vs. service, how slots compose, how proposals
become amendments, and the engine's authoring discipline is governed by
[`kody-w/RAPP/CONSTITUTION.md`](https://github.com/kody-w/RAPP/blob/main/CONSTITUTION.md).

In particular:

- **Article XXIV (platform)** — Senses are translations. This repo's
  `senses/` co-shelf follows that contract; it does not redefine it.
- **Article XXVII–XXIX (platform)** — The split between RAR (registry)
  and RAPP_Store (catalog) and the proposals-before-changes rule are
  upstream. This repo follows them.
- **Article XXXI (platform)** — The three-store ecosystem
  (RAR / RAPP_Store / RAPP_Sense_Store) is the platform-level frame; this
  document is the RAPP_Store-specific charter inside it.

---

## Amendments

Material changes to this document are proposed in
[`docs/proposals/`](./docs/proposals/) before they are applied, mirroring
platform Article XXVIII. A proposal that touches both this constitution
and the platform constitution lives in `kody-w/RAPP/docs/proposals/` and
is referenced from here.
