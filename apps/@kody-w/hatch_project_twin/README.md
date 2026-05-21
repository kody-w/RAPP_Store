# HatchProjectTwin

Hatch a project twin from the global RAPP brainstem kernel into a **project-anchored twin** the global brainstem can autonomously manage.

## The architecture (two homes by design, one source of truth)

```
PRIMARY (operator-visible, project-anchored):
  <project_path>/.brainstem/src/rapp_brainstem/
    brainstem.py · local_storage.py · agents/ · soul.md
    rappid.json · manifest.json · HATCH_RECEIPT.json
    .env · .copilot_token · .copilot_session

CANONICAL (spec-discoverable, for the global brainstem's built-in Twin agent):
  ~/.rapp/twins/<32-hex-rappid-hash>/   →  symlink to PRIMARY
```

The symlink is the bridge. Your twin's files live inside your project tree where you can see and edit them. The canonical `~/.rapp/twins/` root catalogs every twin on the device per `TWIN_LIFECYCLE_SPEC` §2 (filesystem-as-source-of-truth). The built-in `Twin` agent in the global brainstem picks up the symlinked workspace exactly like any other twin, so the global can boot, list, and `/chat` with project twins **without any parallel registry**.

## Spec conformance (required, not optional)

This rapplication is built to be a "good neighbor" — it slots into the canonical RAPP brainstem ecosystem without inventing parallel systems:

- **`rappid.json`** matches `twin_egg_hatcher_agent.py`'s writer exactly. Schema `rapp-rappid/2.0`, `kind: "project"`, `parent_rappid` set to the operator's rappid from `~/.brainstem/rappid.json`, `_hatched_by: "hatch_project_twin_agent.py"`. Per `ESTATE_SPEC` §1 the rappid IS the global address.
- **`HATCH_RECEIPT.json`** is emitted with the same fields the canonical hatcher writes (`hatcher_version`, `rappid`, `kind`, `source`, `hatched_at`, `workspace`, `files`, `re_hatched`).
- **`manifest.json`** carries `port_hint` so `Twin(action="boot", rappid_uuid=…)` works out of the box (per `NEIGHBORHOOD_PROTOCOL` §6 / `TWIN_LIFECYCLE_SPEC` §8).
- **No `~/.brainstem/projects.json`** — ports are discovered by scanning `~/.rapp/twins/*/manifest.json`. One registry. On disk. Per `TWIN_LIFECYCLE_SPEC` §2.
- **No invented schemas** — we don't create `~/.brainstem/neighborhood.json` (that file is not canonical; the existence of the [`rapp-neighborhood-protocol/1.0`](https://github.com/kody-w/RAPP/blob/main/NEIGHBORHOOD_PROTOCOL.md) does not imply a single device-side address-book file).
- **Tracker export uses the canonical 32-hex rappid hash** as the project id — same value that names `~/.rapp/twins/<hash>/`. No parallel id namespace; re-runs merge in place in the localfirst tracker.
- **Gap-filling, additive, default-safe** (per `NEIGHBORHOOD_EGG_SPEC` §9): never overwrites a project's `soul.md`, `.env`, or `rappid.json` unless explicitly told to.

## What it does

When invoked with a `project_path`:

1. Copies the global kernel files (`brainstem.py`, `local_storage.py`, `requirements.txt`, `start.sh`, `start.ps1`, `index.html`, `VERSION`, `agents/basic_agent.py`) verbatim into `<project_path>/.brainstem/src/rapp_brainstem/`.
2. Derives `(owner, repo)` for the rappid: tries `git remote get-url origin` first; falls back to the operator's GitHub handle + project slug.
3. Mints a fresh `rapp-rappid/2.0` (or reuses the existing rappid for idempotent re-hatches).
4. Writes `rappid.json`, `manifest.json` (with `port_hint`), and `HATCH_RECEIPT.json`.
5. Symlinks `~/.rapp/twins/<hash>/` → the project anchor so the global brainstem's `Twin` agent sees it.
6. Auto-picks a free port (skipping every port already in any twin's `manifest.json::port_hint` and skipping the global brainstem's own port).
7. Writes / preserves `.env`, inherits `GITHUB_TOKEN`, `GITHUB_MODEL`, `TEAMS_CHANNEL_EMAIL`, etc. from global.
8. Inherits `.copilot_token` + `.copilot_session` so the project twin chats immediately.
9. Emits a `projectTrackerData`-shaped JSON sidecar that merges cleanly into the [localfirst project tracker tool](https://microsoft.github.io/aibast-agents-library/tools/localfirst_project_tracker_tool.html).

## Why "good neighbor"

The vision (from the requestor): *"instead of managing your projects manually, you would just use your global brainstem to go talk to the neighborhood to autonomously manage your projects."* For that to work, every project twin a tool creates needs to look identical to every other twin on disk. This rapplication takes that as a hard requirement: the project twin HatchProjectTwin produces is indistinguishable from a twin hatched by `twin_egg_hatcher_agent.py` — same schemas, same disk layout, same discoverability — with the project-anchored landing as the one declared delta.

## Parameters

| Param | Type | Default | Notes |
|---|---|---|---|
| `project_path` | string | required | Absolute path to the project root. |
| `port` | integer | auto | Auto-picked from 7073+; skips every port in `~/.rapp/twins/*/manifest.json::port_hint`. |
| `owner` | string | derived | Override the rappid's owner segment. Default: from `git remote get-url origin`, else operator's GitHub handle. |
| `repo` | string | derived | Override the rappid's repo segment. Default: from git remote, else `<project-slug>-brainstem`. |
| `replace_env` | boolean | false | Regenerate `.env` even when it exists. |
| `force_soul` | boolean | false | Overwrite project `soul.md` with global. |
| `include_auth` | boolean | true | Copy `.copilot_token` + `.copilot_session` from global. |
| `emit_tracker_export` | boolean | true | Write `project_tracker_export.json` sidecar. |
| `tracker_out` | string | `<target>/project_tracker_export.json` | Override sidecar path. |

## Output

JSON with:

- `rappid`, `twin_hash`, `parent_rappid` — identity (spec-shaped)
- `project_brainstem` — the project-anchored dir
- `canonical_twin_link` — `{link, target, status}` for the `~/.rapp/twins/<hash>/` symlink
- `port`, `url`, `start_command`
- `copied`, `auth_copied`, `preserved`, `missing_in_global` — file-level audit
- `owner`, `repo`, `owner_source` (`git-remote` / `operator-github` / `fallback-local` / `param`)
- `tracker_export_path`, `tracker_export` — the localfirst sidecar
- `spec_compliance` — a self-attestation block listing the spec axes the agent honors

## How to use

### From `/chat` (the global brainstem)

```
Use HatchProjectTwin: project_path="/absolute/path/to/your/project"
```

The global hot-loads agents per request, so dropping the singleton into `~/.brainstem/src/rapp_brainstem/agents/` makes it immediately callable.

### Autonomously from the global brainstem

Because the project twin lives at `~/.rapp/twins/<hash>/` (via symlink), the global brainstem's built-in `Twin` agent can `boot`, `list`, and `/chat` with project twins by rappid hash. The global can fork → boot → query a fleet of project twins in one conversation.

### From the cartridge UI

Mount this rapplication in vBrainstem or a local brainstem's binder. Fill in the project path, click Hatch, hit "Download tracker JSON" for the localfirst tracker merge.

## Idempotency

Re-running the hatch on the same project path:
- **Reuses** the existing `rappid.json` (the rappid is stable across re-forks).
- **Preserves** the existing port from `manifest.json::port_hint`.
- **Re-links** the canonical `~/.rapp/twins/<hash>/` symlink to the current anchor (force=true).
- **Updates** `HATCH_RECEIPT.json` with the latest `hatched_at` and `re_hatched: true`.

## License

BSD-style (matches upstream RAPP).
