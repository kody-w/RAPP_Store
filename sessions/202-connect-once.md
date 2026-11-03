---
id: "202"
title: "Connect once: RAPP Intents for every assistant"
track: Trust
minutes: 7
audience: Claude Code, Copilot CLI and any MCP host
summary: One connection gives your assistant every installed rapplication, every app's own tools, and every Brainstem agent. New installs appear and uninstalls disappear, with no setup per app.
---
## What you'll learn
- The pattern comes from Apple's App Intents: an app declares itself once, and every surface picks it up.
- Installed rapplications write a small declaration to `~/.rapp/intents/`. The bridge `https://kody-w.github.io/RAPP_Store/sdk/rapp_intents_mcp.py` serves all of them as tools.

## Paste this to your AI
> Install https://kody-w.github.io/RAPP_Store/sdk/rapplication_sdk_agent.py into my Brainstem. Call RapplicationSdk with action=connect, host=claude (or copilot). Then call action=expose_agents with my Brainstem's agents folder. List the tools I now have.

## Done when
`claude mcp list` shows rapp-intents as connected, and one tool call through it returns a real answer.
