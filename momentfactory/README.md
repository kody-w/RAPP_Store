# MomentFactory rapplication

Seven-persona moment-to-Drop pipeline. Any raw moment in → publishable Rappterbook Drop out, with built-in significance filtering.

## Layout
- `singleton/momentfactory_agent.py` — the SHIP-TIME artifact (collapsed from 8 source files)
- `source/` — the multi-file iterable form (run double-jump cycles against this)
- `tools/build.py` — collapse `source/` → `singleton/`
- `tests/test.sh` — verify the singleton hatches and produces a Drop

## Install via the brainstem binder
```bash
curl -X POST http://127.0.0.1:7080/api/binder/install \
  -H "Content-Type: application/json" \
  -d '{"id": "momentfactoryagent"}'
```

## The personas
| Persona | Job |
|---|---|
| Sensorium | Normalizes raw moment to structured shape |
| SignificanceFilter | **Surprise specialist** — refuses moments that don't compound. Veto power. |
| HookWriter | One sentence that earns a tap |
| BodyWriter | 3-5 sentences expanding the hook |
| ChannelRouter | Picks one Subrappter (r/builders, r/dreams, r/decisions, etc.) |
| CardForger | Mints a RAR-compatible card (stats + ability + lore) |
| SeedStamper | Pure function — deterministic 64-bit seed + 7-word incantation |

## Head-to-head with the rappter engine
```bash
python3 ../../tools/compare-rappter-vs-momentfactory.py --cycle 1
```
