# CoE Starter Kit

**Bill Whalen's Agent Team (BWAT) starter kit, packaged as one rapplication.** Run it and it
bootstraps an outcome‑first delivery team into your brainstem — no install script, no cloud,
stdlib‑only.

## What you get — 5 agents

| Agent | Role |
|-------|------|
| **Outcome Framer** | Frame the outcome before any build work begins. |
| **Intake** | Log raw ideas + solutions into a local backlog. |
| **Outcome Validator** | Verify delivery against the frame before any close. |
| **PM** | Sprint planning + status reports. |
| **Bill's Twin** | Bill's digital twin — walks you through the flow in his voice. |

## Run it

- **Preview (dry run):** `perform(dry_run=true)` — shows exactly what would be fetched and where it
  would land. No writes.
- **Install:** `perform()` — pulls each agent over HTTPS, verifies it against the manifest's
  `sha256` (refuses on mismatch), writes them into your `agents/` directory, and records the join.

On your next chat turn the brainstem hot‑reloads and all five are callable.

## Notes

- Self‑contained, standard‑library only. Works offline after the initial fetch.
- Source of truth: [kody-w/billwhalen-agent-team](https://github.com/kody-w/billwhalen-agent-team).
- No customer data, names, or tenant details — the kit is the team scaffold only.

MIT · publisher `@bill` · part of the RAPP Store.
