# @wildhaven/cockpit

> **Local-first control plane for SSH-reachable hosts.**
> One terminal. N continuums. Zero leaks.

## What this is

A rapplication with three surfaces sharing one local state dir:

- **Singleton** (`singleton/cockpit_agent.py`) — LLM-callable agent.
  The chat face. Drops into a RAPP brainstem's `agents/` dir.
- **Organ** (`organs/cockpit_organ.py`) — local HTTP backplane on
  127.0.0.1. Host-header rebind guard. Browser-callable.
- **UI** (`ui/index.html`) — browser cockpit. Talks to the organ.
- **CLI** (`tools/cockpit_cli.py`, also installable as `rappctl`) —
  the same control surface as the agent, in a real terminal, without
  needing a brainstem.

All four read and write the same `~/.cockpit/{state.json,audit.jsonl}`.
The operator's machine owns everything; nothing leaves the box.

## Why this is in the public catalog but with private source

This catalog entry is **publicly discoverable** so anyone reading the
RAPP Store knows the cockpit pattern exists and what shape it has.
The actual source files live in the **private**
[`kody-w/RAPP_Store_Private`](https://github.com/kody-w/RAPP_Store_Private)
repository.

Without read access on that repo, every `*_url` field in `index_entry.json`
returns HTTP 404 and the rapp does nothing. With a PAT scoped for read
on the private repo (or `gh auth token`), every URL returns 200 and the
rapp installs normally.

This is the **public discovery, private substance** pattern — see
the RAPP Store docs for the gating mechanism.

## Install (with access)

```bash
TOKEN=$(gh auth token)

mkdir -p ~/.cockpit
cd ~/.cockpit

curl -fsSL -H "Authorization: Bearer $TOKEN" \
  https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/tools/cockpit_cli.py \
  -o ~/.local/bin/rappctl

chmod +x ~/.local/bin/rappctl
rappctl --help
```

## Verify access (without it)

```bash
# This must return 404. If it returns 200, the gate is broken.
curl -sSL -o /dev/null -w "%{http_code}\n" \
  https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/singleton/cockpit_agent.py
```

## Constitution

- **Local-first.** Operator state lives in `~/.cockpit/`. Importable
  and exportable as JSON.
- **Browsers can't ask for passwords.** Bootstrap-key flows spawn a
  real `Terminal.app` via `osascript`. The cockpit never holds a
  password.
- **Host-header rebind guard.** The organ rejects any request whose
  `Host:` header isn't `127.0.0.1`, `localhost`, `[::1]`, or `::1`.
- **State is two flat files.** `state.json` (host inventory) and
  `audit.jsonl` (action log). No databases, no servers, no daemons
  beyond the optional organ process.

## Schema

This rapplication conforms to `rapp-application/1.0`. See `manifest.json`
and `index_entry.json` for the catalog descriptor.
