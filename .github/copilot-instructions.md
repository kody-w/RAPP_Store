# Rapplication Store Instructions

## Structure

Each rapplication lives under `rapp_store/<name>/` with:

```
manifest.json          Schema: rapp-application/1.0
source/                Multi-file authoring surface (individual agents)
singleton/             Collapsed single-file artifact (the shipped unit)
eggs/                  Stateful snapshots (.egg files)
tools/build.py         Collapses source/ → singleton/
```

## Catalog

[rapp_store/index.json](./index.json) is the store manifest (schema: `rapp-store/1.0`). Every rapplication entry needs: `id`, `name`, `version`, `singleton_filename`, `singleton_url`.

## Build

```bash
python3 rapp_store/<name>/tools/build.py
```

This collapses the multi-file `source/` agents into a single deployable `singleton/<name>_agent.py` via the double-jump loop.

## Rules

- The singleton file must satisfy the same v1 agent contract as any other `*_agent.py`
- Source agents in `source/` are the authoring surface — edit these, not the singleton
- After rebuilding, update `manifest.json` version and `index.json` entry
- Eggs are immutable snapshots — never overwrite an existing `.egg` file
