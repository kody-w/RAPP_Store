# RAPP Dock / Scotty

**One chat-operated rapplication that runs five real open-source apps on your
own computer in Docker.** You talk to **Scotty**, a normal Brainstem agent, or
use the included UI. Scotty starts the apps it needs, runs the job, polls it to
completion and hands back verified files on your disk.

| Ask Scotty | App | What you get |
|---|---|---|
| “Read https://example.com and summarize it with sources.” | [Scrapling](https://github.com/D4Vinci/Scrapling) | The collected page plus a cited summary |
| “Make a six-slide deck from these notes.” | [Presenton](https://github.com/presenton/presenton) | An editable PPTX and a PDF |
| “Create an SEO project for example.com.” | [OpenSEO](https://github.com/every-app/open-seo) | A real OpenSEO project (paid data off) |
| “Answer this from my document.” | [Dify](https://github.com/langgenius/dify) | A knowledge base built from your files and a cited answer |
| “Make three captioned clips from this talk.” | [OpenShorts](https://github.com/mutonby/openshorts) | Vertical, captioned MP4 clips with transcript ranges |

Experimental · local execution · Copilot cloud inference · tested on Apple
Silicon with some amd64 guests under emulation.

## What has actually been verified

- **Installed five-job acceptance passed.** The previous build of this same app
  (Dock source `33dcaa8`, cartridge SHA-256 `03bbb211…6f5d`) was installed into a
  fresh, isolated, unchanged Grail. All five jobs ran for real: a cited
  example.com scrape, a six-slide PPTX + PDF deck, a native OpenSEO project with
  paid metrics disabled, a cited Dify answer from two enrolled documents, and
  three decoded, audio-bearing OpenShorts clips. A preserving uninstall and
  reinstall kept the SEO project, and every job receipt stayed valid after stop.
- **This build** is the newer Dock revision 9 (source `d0f153e`, which is
  reviewed commit `9384158` plus its regenerated capability lock), plus one
  public-template change (`6bfc50c`) that removes upstream default credentials
  from the shipped evidence (see "No upstream default credentials" below).
  Public support is `3d47c453…bc2d6e3`. It adds bounded, read-only recovery for
  Docker status reads after idle (see the limits below). It was rebuilt with the same public producer and Store
  assembler, then installed from the Store's own egg and hatcher into a fresh,
  isolated Grail and Dock home. Real Scrapling (example.com) and Presenton jobs
  completed there and wrote their files to disk.
- OpenSEO, Dify and OpenShorts were not re-run on this build, so the package
  marks them `pending` for this build. Restart and full recreation are also
  `pending` for this build.

The package readiness data (`manifest.json` → `local_docker.readiness` and
`generated/candidate-evidence.json`) records exactly these facts.

## Requirements

- **macOS on Apple Silicon** is the tested profile (Python 3.11+ and Git).
  Other hosts are not qualified.
- **Docker Desktop** running locally, with the **Compose** and **Buildx**
  plugins. The Docker VM on the reference machine had 16 CPUs and about 31 GiB;
  that is not a minimum.
- **Enough memory for Dify and OpenShorts.** They are the heavy apps and run
  under amd64 emulation on Apple Silicon. Dock starts apps on demand and
  reclaims idle stacks, but plan for several GiB free when either runs.
- **GitHub Copilot sign-in for the AI steps.** The intelligence gateway runs
  the official GitHub Copilot CLI in a container. Give it a private env file
  (mode `0600`) containing `COPILOT_GITHUB_TOKEN=` set to a token for your
  Copilot-entitled account. By default the file is
  `~/.rapp-dock/secrets/copilot.env`; set `RAPP_DOCK_COPILOT_ENV` to use another
  path. Copilot usage counts against your own entitlement. Monetary cost is not
  measured and there is no hard spend cap. DataForSEO, Gemini, OpenRouter and
  every other paid provider stay disabled.
- **The unchanged current Grail** Brainstem
  (`microsoft/aibast-agents-library` `rapp_brainstem` at commit
  `c60521e2cacbcbfa585a118c1275093d7bb15b74`, version 0.6.16). The installer
  verifies these exact kernel bytes and refuses anything else.

## Install in a Brainstem

1. In the RAPP Store, open **RAPP Dock / Scotty** and choose **Download complete
   installer**. You get `dock_scotty_1_0_0_<sha>_hatcher_agent.py`, which embeds
   the complete, hash-locked package.
2. Stop your Brainstem. If you want non-default Dock settings, set them in the
   environment the Brainstem starts with, now and every later start. The
   installer binds them into its receipt:
   - `RAPP_DOCK_HOME` (default `~/.rapp-dock`): Dock state, inputs and outputs.
   - `RAPP_DOCK_COPILOT_ENV`: the Copilot env file described above.
   - `RAPP_DOCK_PORT_BASE` (default `18080`): six loopback ports from here.
3. Put the hatcher file in the Brainstem's `agents/` folder and start the
   Brainstem.
4. In chat, ask: **“Install RAPP Dock.”** The hatcher (`dock_scotty_install`)
   verifies Python, the exact Grail, Docker, Compose and the whole locked file
   closure. It then installs Scotty and retires itself. Use `inspect` first if
   you only want the static check; it makes no changes.
5. The Brainstem reloads agents on each chat turn, so **Scotty** is available
   from the next message.

The hatcher retires itself after installing. To remove the app later, put the
same hatcher file back in `agents/` and ask it to `uninstall`. Uninstall stops
Dock's own containers and **keeps** your data, volumes and retained image
layers. It never prunes Docker.

## First run

1. Open the RAPP Dock UI from your Brainstem, or just chat with Scotty.
2. **Status:** choose *Refresh status* (or ask “What's running?”). You see
   Docker's state and every app: `not-started`, `running`, `stopped` and so on,
   with local links once an app runs. Nothing starts until you ask for work.
3. **Scrape:** enter `https://example.com` in *Scrape a web page* and choose
   *Scrape*. Scotty starts the gateway and Scrapling, then returns an operation
   ID. The *Operation progress* panel polls it and shows the real phase. The
   first start of an app takes longest.
4. **Results:** when the job succeeds, *Results* lists each verified artifact
   with its full path, type, size and SHA-256. Files live under
   `RAPP_DOCK_HOME/outputs/`.
5. **Deck:** paste some notes into *Make a deck from text* for an editable PPTX
   and a PDF.
6. **Documents and video:** put files in `RAPP_DOCK_HOME/inputs/` or your
   Desktop, Documents, Downloads, Movies, Music or Pictures folder. Other
   folders must be enrolled in the Dock's private `input-roots.json`, and
   Scotty refuses anything else and names the allowed roots. Then use the Dify
   form with a question, or the OpenShorts form with a 45 s–10 min spoken video.
7. **History and lineage:** *Recent operations*, *History* (by day or date
   range, in your timezone) and *Lineage* (for an operation ID) read recorded
   evidence. They never re-run work.
8. **Stop:** *Stop all Dock apps* stops only Dock's containers and keeps data.

In chat, the same things are plain requests, such as “scrape example.com and
summarize it”, “is that done yet?” or “what did I make today?”. Scotty polls the
earlier operation instead of re-running it.

## The UI

`ui/index.html` is a single self-contained page (no external scripts or fonts).
It uses the Store cartridge protocol: `rapp:get_cartridge`, then `rapp:invoke`
with Scotty's own arguments. Every button is a real Scotty action: `dock_status`,
`start`, `stop`, `logs`, `run`, `operation`, `cancel`, `retry`, `bundle`,
`operations`, `history` and `lineage`. It shows Scotty's own status, error code
and message verbatim, and it is fully keyboard-operable. It needs a host that
can invoke the installed agent. The Store's in-browser vBrainstem cannot run
Docker, so it cannot run these jobs.

## Honest limits

- **OpenShorts public cold rebuild is blocked.** Rebuilding its three images
  from public sources on the reference Mac failed. A pinned PyPI wheel
  (`absl_py-2.5.0`) download timed out, and `registry.npmjs.org` tarball
  downloads failed (curl code 35, SSL unexpected EOF). So OpenShorts needs
  its three locked images (`openshorts-backend`, `openshorts-renderer`,
  `openshorts-frontend`) to already be present. The other components declare
  locked public inputs (registry digests or Dockerfile recipes) with no recorded
  blockers, but a cold rebuild of the whole bundle has not been qualified.
- A status read right after Docker Desktop has been idle can still time out.
  Scotty then reports `docker-timeout` and `unknown` state instead of guessing.
  In an install test of this Dock revision the first read did exactly that,
  and the next read a few seconds later observed Docker normally. Just refresh
  or retry.
- **Keep one Dock home per namespace.** Presenton stores its admin login in its
  Docker volume (`<namespace>-presenton_app_data`, for example
  `rapp-dock-presenton_app_data`). If you replace or reset `RAPP_DOCK_HOME`
  while that volume still exists, Presenton never becomes ready and deck jobs
  fail with `app-not-ready`, because the new home has a different login. Keep
  the original home, or back up and then remove that volume. This happened in
  an install test of this Dock revision, which used a namespace left over from
  an earlier test.
- Verification used cached, locked images on one Apple Silicon Mac. That is not
  proof of a public cold rebuild, another device or Intel/amd64 support.
- Jobs are driven by Copilot through the gateway. The installed acceptance used
  scripted chat plans to check the job path, not a rating of live
  conversation quality.
- Presenton decks are gateway-authored and Presenton-exported. Native Presenton
  AI generation is opt-in. Dify uses economy keyword retrieval with a
  gateway-grounded answer, not a native Dify model plugin.
- Long-running stop and soak qualification is still open. Restart and full
  recreation for this build are `pending`. On the reference profile, Dify full
  recreation and drained-state OpenShorts recreation were qualified separately.
  In-flight OpenShorts renders cannot be recovered.
- RAPP/1 receipts are unsigned structural evidence. A bundle (capsule) carries
  selected outputs and the producing source, not databases, images or secrets.

## No upstream default credentials

Public Store packages never vendor upstream default credential literals. The
Dify and Presenton upstream files carried as evidence (`*.source` and their
`compose.projection.json`) had published example defaults (passwords, API
keys and an example Kibana encryption key) for optional profiles that RAPP
Dock never deploys. They are redacted in this package:
`${NAME:-value}` becomes `${NAME}`, and a literal credential assignment becomes
`NAME: ${NAME}`. Each redacted file's `source.lock.json` entry records:

- `sha256` of the shipped, redacted bytes;
- `upstream_sha256` of the original upstream blob, which still equals
  `reviewed_source_files`;
- `redactions`: the variable names and line numbers, never the values.

The Dock's recipe loader verifies these records. RAPP Dock generates each
app's own credentials locally, in the Dock home's private `secrets/`
directory, and never uses upstream defaults. Your Copilot token is the one
credential you supply.

## Licenses

The RAPP Dock / Scotty code is MIT-licensed. Each upstream app and image keeps
its own license. Notably, **Dify** uses a modified Apache 2.0 with extra
conditions: no multi-tenant service without written permission, and do not
remove its logo or copyright from the console. See [LICENSE.md](LICENSE.md) and
`components.lock.json` for every component.
