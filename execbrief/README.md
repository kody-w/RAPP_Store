# ExecBrief rapplication

Four-persona executive brief pipeline. Topic in, polished brief out.

Pipeline: **Scout** (research) → **Analyst** (insights/risks) → **Strategist** (3 recommendations) → **Writer** (sub-400-word brief)

## Layout
- `singleton/execbrief_agent.py` — the SHIP-TIME artifact (collapsed from 5 source files)
- `source/` — the multi-file iterable form
- `tools/build.py` — collapse `source/` → `singleton/`

## Install
Drop `singleton/execbrief_agent.py` into your brainstem's `agents/` directory. Or install via the store:
```
Ask your brainstem: "install ExecBrief from the store"
```

## Use
```
Create an executive brief about why Microsoft needs a unified agent sharing standard
```

The pipeline runs 4 LLM calls (one per persona) and returns a formatted executive brief under 400 words with a clear ask at the end.

## Iterate
1. Edit a persona file in `source/`
2. Run `python3 tools/build.py` to regenerate the singleton
3. Reinstall to pick up the new singleton
