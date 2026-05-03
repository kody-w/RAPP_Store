# rapp_store

**[📦 Browse the store](https://kody-w.github.io/RAPP_Store/)** · **[🦎 Pokédex API](#pokédex-api)** · **[📋 SPEC](./SPEC.md)** · **[🔒 Gated rapps (§11)](./SPEC.md#11-gated-rapplications-access-private)** · **[🔌 RAPP Agent Registry](https://github.com/kody-w/RAR)** · **[⚙️ RAPP engine](https://github.com/kody-w/RAPP)**

Public catalog of RAPP **rapplications** — bundled directories that pair a single-file agent with a UI, a service, or a state cartridge. Drop them into your local brainstem and they work — or browse them like Pokémon via the [Pokédex API](#pokédex-api).

> **Rapplications are organisms.** Per the unification ratified in `kody-w/RAPP` (vault note: *Rapplications Are Organisms*), every entry in this catalog is a digital organism that has graduated — passed review, earned skin (a UI bundle), suitable for hosting inside someone else's brainstem. Distributed via this catalog as both a bare singleton `.py` and a portable `.egg` cartridge ([brainstem-egg/2.2-rapplication schema](https://github.com/kody-w/RAPP/blob/main/rapp_brainstem/utils/bond.py)).

> **Looking for bare agents?** A single `*_agent.py` with no UI belongs in **[kody-w/RAR](https://github.com/kody-w/RAR)** — single-celled organisms without skin. Per [Constitution Article XXVII](https://github.com/kody-w/RAPP/blob/main/CONSTITUTION.md), bundle goes here, bare goes there.

This repo was extracted from [`kody-w/RAPP`](https://github.com/kody-w/RAPP) on 2026-04-26 as the content layer of the platform. The engine (Tier 1 brainstem, Tier 2 swarm, Tier 3 worker) lives in `kody-w/RAPP`. Trust metadata (signing, identity, provenance) lives in the RAR registry. This repo is just **content** — rapplications you can fetch and run.

## Gated rapplications (private substance, public discovery)

Most catalog entries are public — anyone can fetch the source with a normal `curl`. But some rapplications **shouldn't be world-fetchable**: an operator's internal control plane, engine IP distributed inside an org, customer-specific bundles built on top of an open base. For those, the catalog supports **gated rapplications** — a public catalog entry whose source files live in a **private** GitHub repo.

The catalog publishes the rapp's existence, shape, and metadata. GitHub's `raw.githubusercontent.com` returns HTTP 404 for unauthenticated callers and HTTP 200 only for callers with read access on the private repo. Public discovery, private substance.

```jsonc
// in index.json's rapplications[]:
{
  "id": "cockpit",
  "manifest_name": "@wildhaven/cockpit",
  "access": "private",
  "private_repo": "kody-w/RAPP_Store_Private",
  "singleton_url": "https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/singleton/cockpit_agent.py",
  "singleton_sha256": "c77195ef…",
  "auth_hint": "gh auth token  →  curl -H \"Authorization: Bearer $TOKEN\" <singleton_url>"
}
```

```bash
# Anyone can verify the gate is real:
curl -sSL -o /dev/null -w "%{http_code}\n" \
  https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/singleton/cockpit_agent.py
# → 404 (anonymous)

# With a PAT scoped for read on the private repo:
curl -sSL -H "Authorization: Bearer $(gh auth token)" -o /dev/null -w "%{http_code}\n" \
  https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/singleton/cockpit_agent.py
# → 200
```

The full contract — manifest fields, validator behavior, installer responsibilities, security boundaries — lives in [**SPEC §11**](./SPEC.md#11-gated-rapplications-access-private). The design rationale is in [Proposal 0005](./docs/proposals/0005-gated-rapplications.md).

This is **federation Mode C** in the submission-paths taxonomy (see [SPEC §7](./SPEC.md#7-submission-paths)) — federation referencing a private repo, with the gate being GitHub's own access control. No servers, no relays, no custom auth code; the PAT is the access token.

## Pokédex API

Modeled on [PokeAPI](https://pokeapi.co/) — the catalog is a tree of static JSON files served from `raw.githubusercontent.com`. No backend, no auth, no rate limits, no infra to operate. Push to `main` → the API "deploys."

```
https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/index.json
https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/rapplication/<id>.json
https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/sprite/<id>.svg
https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/egg/<id>.egg
```

Each `<id>.json` is a Pokédex entry: id, name, rappid, types, stats (`has_skin`, `singleton_lines`, `singleton_bytes`, `singleton_sha256`), parent rappid (lineage walks back to the species root), URLs to the egg + sprite + singleton + UI bundle. Each `<id>.svg` is a deterministic 6×6 sprite generated from the rappid hash. Each `<id>.egg` is a brainstem-egg/2.2-rapplication cartridge — drop into a brainstem and the rapp installs.

The [`rapp-zoo`](https://github.com/kody-w/rapp-zoo) consumes this API in its **Discover** tab — sprites + cards + one-click egg downloads. Drag the egg back onto any brainstem to hatch the rapp.

Rebuild: `python3 scripts/build_pokedex_api.py` (walks `apps/@*/`, regenerates `api/v1/` atomically — JSON entries, sprites, eggs).

## Legacy catalog

[`index.json`](./index.json) at the repo root remains the original catalog (`schema: "rapp-store/1.0"`) consumed by the brainstem's binder service. Same source data as the Pokédex API; both are generated from the per-app `manifest.json` files.

```
https://raw.githubusercontent.com/kody-w/rapp_store/main/index.json
```

## Layout

Each rapplication is a directory with at least:

- `manifest.json` — metadata that the catalog generator reads
- `singleton/<name>_agent.py` — the converged single-file agent
- `source/` — pre-collapse component agents (optional, for reference)
- `ui/index.html` — optional iframe UI
- `eggs/*.egg` — optional state snapshots
- `README.md` — what the rapp does and how to use it

## Submitting a rapplication

The catalog accepts any single-file agent that satisfies the SPEC §5 contract in `kody-w/RAPP/pages/docs/SPEC.md`:

- one file
- one class extending `BasicAgent`
- one `metadata` dict (OpenAI function-calling schema)
- one `perform(**kwargs) -> str`

Open a PR with your rapplication directory + a regenerated `index.json` entry. There is no review gate beyond the contract — RAR (the trust layer) provides identity attestation separately, but the catalog itself never refuses a contract-conformant agent.

## Related

- **Engine:** [`kody-w/RAPP`](https://github.com/kody-w/RAPP) — brainstem, swarm, worker, install one-liner
- **Constitution:** Article XV (tier portability), Article XVI (catalog vs workspace), the "RAR is metadata, never authority" rule
- **Vault:** decision narratives in [`kody-w/RAPP/pages/vault/`](https://github.com/kody-w/RAPP/tree/main/pages/vault)
