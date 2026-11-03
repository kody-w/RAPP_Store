---
id: "302"
title: "Keep it alive, update with undo, move it"
track: Operate
minutes: 8
audience: Owners who never want to babysit an app
summary: Every generated rapplication can restart itself after a crash, self-test daily, explain an update in plain words, undo it, and move to another computer with its data.
---
## What you'll learn
- `keepalive_on`: a timer heals the app every 10 minutes. A stop you ask for is respected.
- `update_check` shows what changed, file by file, in the file's own words. `update` keeps your data and a snapshot, and `undo` restores the exact previous bytes.
- `export` and `import` move the app and its data. Keys in .env are never packed.

## Paste this to your AI
> For my installed rapplication "<id>": turn keep-alive on, check for updates and explain them in plain words, and don't apply anything until I say so.

## Done when
`status` shows it running with keep-alive on, and the update report lists actual files.
