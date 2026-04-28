# WildhavenCEO — `@blazingbeard/wildhaven-ceo-singleton`

> **Talk to your workspace.**
> A CEO workspace agent: drop a vault of strategy / legal / budget / pitch / playbook documents in, then ask questions and get answers in a confident operator's voice.

A rapplication patterned after [`kody-w/wildhaven-ceo`](https://github.com/kody-w/wildhaven-ceo) — the "Molly portal" idea generalized into something any operator can deploy with their own vault.

---

## What it does

You don't read the vault. The agent reads it for you. You ask:

> *"How are the rentals doing this month?"*

And it answers in your voice, with the exact numbers from the vault you supplied:

> Strong: Quillen, Airbnb, Marcia, 11th St. Marginal: Rocco, Braden. Problem: Farmington, Merryman, Timberline, Water — these four lost money in 2025. **This week, ask Kody about Farmington — that's the biggest lever.**

Five workflows, each tuned to a real operator pattern:

| Workflow | When to use it |
|---|---|
| **Ask** | Daily Q&A. Most calls are this. |
| **Decide** | Yes/no business decisions, structured: Decision · Reasoning · Risk · Next action |
| **Respond to** | "X asked me Y, what do I say?" → drafts a paste-ready reply matching the asker's register |
| **Daily brief** | 5-bullet brief for today: #1 move, decisions waiting, stakeholder update, number to watch, one thing to drop |
| **Quarterly review** | Hits / misses / surprises against vault targets, plus next quarter's #1 |

## How it works

- **Headless** — drop `wildhaven_ceo_agent.py` into any RAPP brainstem's `agents/` directory. The LLM gets it as a tool. Call from `/chat`, from another agent, or from anywhere that runs an installed agent.
- **UI mode** — open the rapplication in a vBrainstem (cloud or tethered). The UI gives you a vault-context panel on the left, a workflow picker + composer on the right, output rendered as markdown with copy/download.

The agent talks to its LLM through `from utils.llm import call_llm` (host-provided shim). No API keys in this file. Works in Tier 1 (local brainstem), Tier 2 (swarm), Tier 3 (worker), and the cloud vBrainstem's Pyodide mount.

## Install

```bash
curl -L -o ~/.brainstem/src/rapp_brainstem/agents/wildhaven_ceo_agent.py \
  https://raw.githubusercontent.com/kody-w/rapp_store/main/apps/@blazingbeard/wildhaven_ceo/singleton/wildhaven_ceo_agent.py
```

Or chat-driven via the binder agent (after `kody-w/RAPP#25` lands): *"install wildhaven_ceo"*.

The UI is mounted automatically when the rapplication is selected in the [vBrainstem](https://kody-w.github.io/RAPP_Store/vbrainstem.html).

## Example call

```jsonc
{
  "action": "decide",
  "question": "Should I file the patent this week?",
  "workspace_context": "(paste the latest pitch/business-plan.md, legal/patent/* docs, the wallet summary)"
}
```

Returns:

> **Decision: Yes — file Tuesday.**
> Reasoning:
> • $160 cost vs. priority-date insurance worth orders of magnitude more (per `legal/patent/provisional-patent-application.md`).
> • Wallet has the budget (per `wallet/portfolio-summary.md`).
> • Two competitor mentions in your `strategy/threat-watch.md` that haven't filed yet.
> Risk: filing without a final patent attorney review could weaken claim breadth. One-hour call before submit.
> **Next action: book the patent-attorney call for Monday morning. File Tuesday.**

## Files

```
@blazingbeard/wildhaven_ceo/
  manifest.json           rapp-application/1.0
  index_entry.json        catalog snippet
  README.md               this
  singleton/
    wildhaven_ceo_agent.py   (single file, BasicAgent contract)
  ui/
    index.html              (cartridge-protocol-aware iframe UI)
```

## Persona

The system prompt establishes the operator voice. From the agent file:

> You are a CEO workspace agent. You speak in the voice of the operator running the company — direct, decisive, plain language, skin in the game. The user is the operator. They aren't asking for advice from a consultant; they're talking to a thinking partner who already knows the business as well as they do.

Workflow-specific framing layers on top. See `singleton/wildhaven_ceo_agent.py` for the full SOUL.

## Inspired by

[kody-w/wildhaven-ceo](https://github.com/kody-w/wildhaven-ceo) — the Wildhaven AI Homes LLC CEO portal. The "talk to the workspace" pattern; specifically `prompts-for-molly.md` and `HOME.md`.

## License

BSD-style.

## Publisher

[`@blazingbeard`](https://github.com/blazingbeard) — first community publisher in `kody-w/rapp_store`.
