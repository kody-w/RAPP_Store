# Vibe Coding Loop

Ship batches of 10 single-file HTML demos to a Jekyll site via parallel sub-agents. The orchestrator never writes demo code; it dispatches workers, wraps the results, and ships.

This is the production loop that put 71 working browser demos onto [kody-w.github.io/learnwithkody](https://kody-w.github.io/learnwithkody/).

## What it does

The agent is **provider-agnostic** — it does NOT make LLM calls itself. Instead, it returns the exact prompt templates and shell commands you feed to whatever model your brainstem runs (GitHub Copilot SDK, Azure OpenAI, Anthropic, Ollama, etc.).

## Five actions

| Action | Returns |
|---|---|
| `ideate(domain)` | Ideation prompt — feed to your LLM, get 10 demo concepts back |
| `worker(prompt, output_path, lib)` | Worker brief to dispatch as a sub-agent |
| `wrapper(...)` | Jekyll example-post template to fill in |
| `ship(slugs)` | Shell command sequence (validate, commit, push, verify URLs) |
| `loop(domain)` | Full 4-step plan, each step with what-to-do + which action to call |

## Install

Drop the singleton into any RAPP brainstem's `agents/` directory:

```bash
curl -o agents/vibe_coding_loop_agent.py \
  https://raw.githubusercontent.com/kody-w/RAPP_Store/main/apps/@kody-w/vibe-coding-loop/singleton/vibe_coding_loop_agent.py
```

Or hatch the `.egg`:

```bash
curl -O https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/egg/vibe-coding-loop.egg
# Drop into any rapp-zoo or brainstem with egg-import support
```

## Quick start

Call `action="loop"` with a domain to get the full plan:

```python
from vibe_coding_loop_agent import VibeCodingLoopAgent
agent = VibeCodingLoopAgent()
plan = agent.perform(action="loop", domain="first-person rooftop scenes")
```

The plan is a 4-step sequence. Step 1 returns an ideation prompt — feed that to your LLM, get 10 demo concepts. Step 2 dispatches workers in parallel. Step 3 wraps results. Step 4 ships.

## Reference

- Live demo catalog: [kody-w.github.io/learnwithkody](https://kody-w.github.io/learnwithkody/)
- Agent instructions (single page, curl-able): [kody-w.github.io/loop/](https://kody-w.github.io/loop/)
- Long-form essay: [The Vibe-Coding-Demo Loop](https://kody-w.github.io/2026/05/02/the-vibe-coding-demo-loop/)
- Pointable SKILL.md: [kody-w.github.io/loop/skill.md](https://kody-w.github.io/loop/skill.md)
- Source: [kody-w/kody-w.github.io](https://github.com/kody-w/kody-w.github.io)

## License

BSD-style. Use it. Fork it. Run your own loop.
