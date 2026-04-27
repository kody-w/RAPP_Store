# rapp_store

**[📦 Browse the store](https://kody-w.github.io/RAPP_Store/)** · **[📋 SPEC](./SPEC.md)** · **[🔌 RAR (bare agents)](https://github.com/kody-w/RAR)** · **[⚙️ RAPP engine](https://github.com/kody-w/RAPP)**

Public catalog of RAPP **rapplications** — bundled directories that pair a single-file agent with a UI, a service, or a state cartridge. Drop them into your local brainstem and they work.

> **Looking for bare agents?** A single `*_agent.py` with no UI / service / eggs belongs in **[kody-w/RAR](https://github.com/kody-w/RAR)** — the registry for one-file agents. Per [Constitution Article XXVII](https://github.com/kody-w/RAPP/blob/main/CONSTITUTION.md#article-xxvii--rar-holds-files-the-rapp-store-holds-bundles), bundle goes here, bare goes there.

This repo was extracted from [`kody-w/RAPP`](https://github.com/kody-w/RAPP) on 2026-04-26 as the content layer of the platform. The engine (Tier 1 brainstem, Tier 2 swarm, Tier 3 worker) lives in `kody-w/RAPP`. Trust metadata (signing, identity, provenance) lives in the RAR registry. This repo is just **content** — rapplications you can fetch and run.

## Catalog

[`index.json`](./index.json) is the canonical catalog (`schema: "rapp-store/1.0"`). Each entry points to a `singleton_url` (a single `.py` file) and optionally `ui_url` / `egg_url`. The brainstem's binder service consumes this index.

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
