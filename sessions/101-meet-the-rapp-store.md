---
id: "101"
title: Meet the RAPP Store
track: Foundations
minutes: 5
audience: Any AI agent arriving for the first time
summary: Read the store the way an AI should. Start at llms.txt, then the static API. No HTML scraping and no account.
---
## What you'll learn
- The store is API first, UI second. Every page a person sees is one view over the same JSON you can read.
- `https://kody-w.github.io/RAPP_Store/llms.txt` is the map, `https://kody-w.github.io/RAPP_Store/api/v1/ai.json` lists every endpoint, and `https://kody-w.github.io/RAPP_Store/index.json` is the catalog.

## Paste this to your AI
> Read https://kody-w.github.io/RAPP_Store/llms.txt. Then fetch https://kody-w.github.io/RAPP_Store/index.json and tell me, in five bullets, the five rapplications most useful for my work, with one line each on what they do. Don't install anything yet.

## Done when
Your AI lists rapplications by id and name, and every one exists in index.json.
