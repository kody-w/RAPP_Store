# BookFactory rapplication

Five-persona content pipeline. Source material in → publishable chapter out.

## Layout
- `singleton/bookfactory_agent.py` — the SHIP-TIME artifact (collapsed from 13 source files)
- `source/` — the multi-file iterable form (run double-jump cycles against this)
- `tools/build.py` — collapse `source/` → `singleton/`
- `tests/test.sh` — verify the singleton hatches and produces output

## Install via the brainstem binder
```bash
curl -X POST http://127.0.0.1:7080/api/binder/install \
  -H "Content-Type: application/json" \
  -d '{"id": "bookfactoryagent"}'
```

The brainstem materializes `singleton/bookfactory_agent.py` into the active twin's `agents/` directory and records the install in `<twin_root>/.binder.json`.

## Iterate
1. Edit a persona file in `source/`
2. Run `python3 tools/build.py` to regenerate the singleton
3. Run `bash tests/test.sh` to verify
4. Reinstall via `/api/binder/install` to pick up the new singleton
