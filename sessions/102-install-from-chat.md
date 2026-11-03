---
id: "102"
title: Install your first rapplication from chat
track: Foundations
minutes: 8
audience: Anyone with a Brainstem
summary: A rapplication is one agent file. Drop it into a Brainstem's agents folder and it works on the next message. No restart and no pip.
---
## What you'll learn
- Every catalog entry has a `singleton_url` and a `singleton_sha256`. Download the file, check the fingerprint, then drop it in.
- The Brainstem reloads agents on every request.

## Paste this to your AI
> From https://kody-w.github.io/RAPP_Store/index.json, take the rapplication "<id>". Download its singleton_url into my Brainstem's agents/ folder, check its sha256 against singleton_sha256 before saving, and stop if they differ. Then ask my Brainstem (POST http://localhost:7071/chat, field user_input) to run it once and show me the response field.

## Done when
The fingerprint matched, and /chat answered using the new agent.
