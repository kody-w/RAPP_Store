# TwinWorkshop — `@rapp/twin-workshop-singleton`

> **The full workshop loop, performed by the platform on itself, with the customer in the room.**
> Sixty minutes. They leave with a working personal twin agent — a `.py` file that runs in any RAPP brainstem.

A composite rapplication that walks a user through the five-stage twin-design workshop:

| Stage | What happens |
|---|---|
| **INTAKE** | Capture, free-form, what the user wants to delegate. |
| **CLARIFY** | Convert the description into a tight task contract. |
| **DESIGN** | Generate the `agent.py` source live, in front of the user. |
| **VALIDATE** | Run the generated agent against the user's own test input. |
| **SHIP** | Hand them the `.py` file for download / AirDrop. |

Each stage is a single LLM call with its own SOUL. Internal stage classes are prefixed `_Internal` so the brainstem's `*Agent` discovery only sees `TwinWorkshopAgent`.

The bundled `ui/index.html` is the iframe-mounted UI that walks the user through the five stages.

---

## Install

```bash
curl -L -o ~/.brainstem/src/rapp_brainstem/agents/twin_workshop_agent.py \
  https://raw.githubusercontent.com/kody-w/rapp_store/main/twin_workshop/singleton/twin_workshop_agent.py
```

Or use the binder agent: *"Install the twin_workshop rapplication."* — the binder service fetches both the singleton and the UI.

---

## Example call

```jsonc
// Stage 1: intake
{ "stage": "intake",
  "description": "I want an agent that answers prospect emails the way I would." }

// Stage 3: design (after a clarify pass)
{ "stage": "design",
  "task_contract": "<contract from clarify stage>" }
```

The UI orchestrates the five stages so a user never types this JSON by hand — but the agent is callable directly for power users and integrations.

---

## Files

```
twin_workshop/
  singleton/twin_workshop_agent.py    drop into agents/
  ui/index.html                        iframe-mounted UI
  manifest.json                        rapp-application/1.0
  index_entry.json                     catalog entry
  README.md                            this file
```

## Dependencies

Python 3.8+. No third-party packages. Reads `AZURE_OPENAI_*` / `OPENAI_API_KEY` from the host brainstem's environment via `utils.llm.call_llm`.

## License

BSD-style.

## Publisher

`@rapp`
