---
id: "401"
title: Submit to the store
track: Ship
minutes: 5
audience: Makers ready to share
summary: The SDK validates with the store's own validator, then opens a [RAPP] submission issue. Nothing goes out until you confirm.
---
## What you'll learn
- `submit` is a dry run first. With `confirm=true` it opens an issue, and the store's receiver validates it again before anyone merges it.
- Keep the LICENSE and NOTICE files of anything that isn't yours.

## Paste this to your AI
> Call RapplicationSdk action=submit for "<id>" and show me the dry run. Wait for my "yes" before calling it again with confirm=true.

## Done when
You see the issue URL, and the store's validation workflow passes on it.
