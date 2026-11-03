---
id: "301"
title: "Build a rapplication with the SDK: Bot X-Ray, start to finish"
track: Build
minutes: 15
audience: Makers and the AIs that build for them
summary: Turn a real app (Bot X-Ray, MIT licence) into a store-valid rapplication, capture its source, and rebuild it byte-for-byte from the bundle alone.
---
## What you'll learn
- `from_prompt` turns an install prompt into a recipe, and `new` makes the bundle: manifest, a one-file agent, UI, README and installer prompt.
- `capture` carries the source along with a fingerprint lock and an anatomy guide. `rebuild` proves it: 61 of 61 files match, and the app's own self-test says READY.
- Full walkthrough: https://kody-w.github.io/RAPP_Store/sdk/TUTORIAL.md

## Paste this to your AI
> Follow https://kody-w.github.io/RAPP_Store/sdk/TUTORIAL.md with the RapplicationSdk agent, steps 1 to 4, on the app I name. After each step, show me the SDK's real output, not a summary.

## Done when
`validate` reports 0 errors and `rebuild` reports every fingerprint matching.
