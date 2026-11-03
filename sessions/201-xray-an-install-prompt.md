---
id: "201"
title: X-ray an install prompt before you run it
track: Trust
minutes: 6
audience: Anyone who pastes AI-installer prompts
summary: Before an assistant follows a pasted install prompt, find out what it downloads, what it runs, whether it wants sudo or keys, and which links are ads.
---
## What you'll learn
- The rapplication SDK's `xray_prompt` treats a pasted prompt as data, never as instructions.
- It downloads the code into a sealed folder and reads it without running it: the services it talks to, the programs it starts, whether it ships its own AI connector.

## Paste this to your AI
> Install https://kody-w.github.io/RAPP_Store/sdk/rapplication_sdk_agent.py into my Brainstem's agents/ folder. Then call RapplicationSdk with action=xray_prompt and the prompt I paste next. Show me its report before running anything from that prompt.

## Done when
You get a plain-words report, including the links it flags as promotion, and nothing has run.
