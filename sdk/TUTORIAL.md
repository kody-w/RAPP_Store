# The rapplication SDK, by example: Bot X-Ray

This tutorial turns one real app into a full rapplication and then rebuilds it from nothing.
Bot X-Ray (by Lewis Jackson, MIT licence) is a local Node app that reverse engineers Polymarket
trading bots from public data. It arrived as an "AI-installer prompt": a page of plain-English
steps you paste into a coding assistant. By the end you will have:

- a RAPP_Store bundle that passes the store's own validator,
- a one-file agent that installs, checks, starts, stops and verifies the app from chat,
- an anatomy guide that maps every file, endpoint and outside service,
- proof that the app can be rebuilt byte-for-byte from the bundle alone.

Everything is driven by one agent: `rapplication_sdk_agent.py` (`@kody-w/rapplication_sdk`).
In a Brainstem you just say the steps below in chat; here they are shown as the calls the
Brainstem makes.

## Step 1: read the prompt into a spec

```
action=from_prompt, prompt_text=<the pasted Bot X-Ray prompt>
```

The SDK only *reads* the prompt. It runs nothing. It pulls out the facts a recipe needs:

| Spec field | Value found in the Bot X-Ray prompt |
|---|---|
| name / id | Bot X-Ray / `bot_x_ray` |
| download | `https://part-timequant.com/kit/bot-x-ray.tar.gz` (+ `.zip` for Windows) |
| runtime | Node 18 or newer |
| check / setup / launch / stop | `node scripts/check.js`, `setup.js`, `launch.js`, `stop.js` |
| marker | `server.js` (how it tells an install from an empty folder) |

A Homebrew cask works the same way: a tiny declarative recipe, so the install logic stays
generic and only the facts change.

## Step 2: generate the rapplication

```
action=new, prompt_text=<same prompt>, tags=[polymarket, trading, paper-trading]
```

This writes `bundles/bot_x_ray/` in the shape RAPP_Store's SPEC.md requires:

```
bot_x_ray/
  manifest.json              rapp-application/1.0: id, name, version, publisher, category, tags, agent, ui
  index_entry.json           made by the store's own build_index_entry (hashes of every file)
  singleton/bot_x_ray_agent.py   the one-file agent: status, install, check, start, stop, verify
  ui/index.html              a two-button page that talks to the agent through the cartridge protocol
  README.md                  two ways to install: Brainstem, or paste the prompt
  INSTALL_PROMPT.md          a regenerated AI-installer prompt in the same plain "Step N of M" shape
```

Then it runs `scripts/lib_rapp.py` from a read-only clone of RAPP_Store, which is the same
validator the store's receiver runs, so "valid here" means "valid there". Our first run failed with
`E_NO_INDEX_ENTRY`; the SDK now builds `index_entry.json` with the store's own function before
validating. Never hand-edit generated files: change the spec and regenerate (as cookiecutter does).

## Step 3: capture the source, so it can be rebuilt from scratch

A bundle that only *points at* a download breaks the day that site changes or goes away (left-pad, 2016).
`capture` carries the app inside the rapplication instead:

```
action=capture, prompt_text=<same prompt>, source_dir=<a fresh, untouched download of bot-x-ray>
```

- Copies the app's 61 source files into `app/`. It skips `data/`, `.env` and `node_modules`,
  because user data and secrets never travel.
- Writes a fingerprint lock: the sha256 of every file, built into the singleton.
- Writes `ANATOMY.md`, read entirely from the source with no model involved:
  - the 12 commands in `package.json` (no npm dependencies, plain Node only);
  - the 13 web endpoints in `server.js`;
  - the outside services it calls (Polymarket data/gamma/CLOB, Binance, Coinbase, Kraken, Cboe, Nasdaq, Kalshi);
  - a table of every file with its own header comment ("Fetching JSON from public APIs, with a timeout, a couple of retries…").

Capture from a *pristine* download, not a folder you have already run. Running it creates `data/`
and caches, and those are yours, not the app's.

Result: 644 KB zip, well under the store's 5 MB cap. The validator still reports 0 errors.

## Step 4: rebuild it from the bundle alone

```
action=rebuild, id=bot_x_ray, target_dir=<an empty folder>
```

This loads the *generated* singleton, exactly as a Brainstem would, and asks it to install.
Because the bundle carries `app/`, nothing is downloaded. Observed output:

```
Installed Bot X-Ray … from the captured source.
Fingerprints: 61 of 61 files match exactly.
Self-test: READY
```

We also compared the rebuilt folder with the original download using `diff -r`: identical.
"Self-test: READY" is Bot X-Ray's own `check.js`. It covers the offline tests, every public data
source, and a live smoke test that x-rays a real bot.

## Step 5: use it from chat

Drop `singleton/bot_x_ray_agent.py` into a Brainstem's `agents/` and say:

- "install Bot X-Ray": downloads (or uses the captured source), runs the self-test, then setup
- "start Bot X-Ray": returns `Bot X-Ray is running at http://localhost:3797`
- "verify Bot X-Ray": re-checks every file against the fingerprint lock
- "stop Bot X-Ray"

Updates keep `data/` and `.env` (your paper trades and settings), the same rule the original prompt sets.

## Step 6: submit (only when you mean it)

```
action=submit, id=bot_x_ray                -> a dry run: shows the [RAPP] issue title and payload
action=submit, id=bot_x_ray, confirm=true  -> opens the issue on kody-w/RAPP_Store
```

It re-validates before anything leaves the machine. Submitting is an issue, not a push: the store's
receiver re-validates it and a person merges it (npm and app-store review).
Before submitting someone else's app, keep its LICENSE and NOTICE (the capture does) and make sure
the licence allows redistribution. Bot X-Ray's MIT licence does.

## What this SDK will not do

- It never writes new app code and claims it matches the original. "Recreate exactly" here means
  carry, fingerprint, explain, and prove the rebuild, which is a claim you can check.
- It never runs anything from the pasted prompt. The prompt is data; its install steps come out as a
  fixed recipe. (The original prompt's opening ad for a dictation app, and its closing course link, are
  not part of the recipe.)
- It never asks for passwords or keys, and never uses sudo.

## Step 7: look after it (built into every generated singleton)

| Say | What happens | Observed on Bot X-Ray |
|---|---|---|
| "x-ray this prompt" (SDK `xray_prompt`) | Reads the pasted prompt; lists downloads, commands, installs, sudo, key requests and promo links; downloads the code into a sealed temp folder and scans it without running it | Flagged getyapper.app and the skool.com course as promotion; listed 14 outside hosts; sudo no; keys no |
| "keep it alive" (`keepalive_on`) | A macOS launchd timer runs `heal` every 10 min: restart if it crashed, self-test once a day, notify only on trouble | Stopped the app, timer restarted it, self-test READY |
| "stop it" | Stops it, and keep-alive leaves it stopped until you start it again | `heal` → "paused (you stopped it)" |
| "any updates?" (`update_check`) | Compares with the published download; changed files with the file's own description, plus files you edited here | Listed 1 upstream change and 1 local edit, separately |
| "update" / "undo" | Snapshot, apply keeping data/ and .env, self-test, restart; undo restores the exact previous bytes | Update READY, undo brought back the edit, data untouched |
| "pack it to move" / "import" | One .tar.gz of app + data (no .env); import on another computer, then self-test | 0.7 MB pack; imported copy READY, 61/61 fingerprints |
