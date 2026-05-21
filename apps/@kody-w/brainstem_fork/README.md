# BrainstemFork

Fork the global RAPP brainstem kernel into a project-specific instance.

## What it does

When invoked with a `project_path`, the agent:

1. Copies the global brainstem kernel files (`brainstem.py`, `local_storage.py`, `requirements.txt`, `start.sh`, `start.ps1`, `index.html`, `VERSION`, `agents/basic_agent.py`) **verbatim** from `~/.brainstem/src/rapp_brainstem` into `<project_path>/.brainstem/src/rapp_brainstem`.
2. Auto-picks a free port from 7073+ (skipping the global brainstem's port and any port already used by another forked project).
3. Generates or updates the project `.env` with the picked port plus inherited `GITHUB_TOKEN`, `GITHUB_MODEL`, `TEAMS_CHANNEL_EMAIL`, etc. from the global `.env`.
4. Preserves any existing project `soul.md` and `agents/*.py` — the project's identity stays project-shaped.
5. Inherits `.copilot_token` and `.copilot_session` so the forked brainstem chats immediately without re-auth.
6. Registers the project in `~/.brainstem/projects.json` (path + port) so future forks know which ports are taken.
7. Emits a `projectTrackerData`-shaped JSON sidecar at `<project>/.brainstem/src/rapp_brainstem/project_tracker_export.json` that merges cleanly into the [localfirst project tracker tool](https://microsoft.github.io/aibast-agents-library/tools/localfirst_project_tracker_tool.html).

The kernel itself is never edited. Projects differ via their own `.env`, `soul.md`, and `agents/` — the same `brainstem.py` runs everywhere.

## Why

Running multiple brainstems on the same machine — one per active project — keeps memory, agents, and soul scoped to the project without forking the codebase. The global brainstem stays the source of truth for the kernel; project brainstems are short-lived satellites that share its DNA.

## Parameters

| Param | Type | Default | Notes |
|---|---|---|---|
| `project_path` | string | required | Absolute path to the project root. |
| `port` | integer | auto | Auto-picks from 7073+ if omitted. |
| `replace_env` | boolean | false | If true, regenerate `.env` even when it exists. |
| `force_soul` | boolean | false | If true, overwrite the project `soul.md` with the global one. |
| `include_auth` | boolean | true | Copy `.copilot_token` + `.copilot_session` from global. |
| `emit_tracker_export` | boolean | true | Write the localfirst-tracker JSON sidecar. |
| `tracker_out` | string | `<target>/project_tracker_export.json` | Override the sidecar path. |

## Output

The agent returns a JSON document with:

- `project_brainstem` — absolute path of the new project brainstem dir
- `port`, `url` — chosen port and local URL
- `copied`, `auth_copied`, `preserved`, `missing_in_global` — file-level audit
- `registry` — path of `~/.brainstem/projects.json`
- `start_command` — exact shell command to boot the forked brainstem
- `tracker_export_path` — path of the sidecar JSON
- `tracker_export` — the inline sidecar payload (mergeable into the localfirst tracker)

## How to use

### From `/chat`

```
Use BrainstemFork: project_path="/absolute/path/to/your/project"
```

The brainstem hot-loads agents on every request, so dropping this file into `agents/` makes it immediately callable — no restart.

### From the cartridge UI

Mount this rapplication in vBrainstem (`kody-w.github.io/RAPP_Store/vbrainstem.html`) or a local brainstem's binder. Fill in the project path, pick options, click Fork. The result panel includes a "Download tracker JSON" button and a link to the localfirst project tracker tool.

### Merging into the localfirst tracker

1. Run the fork.
2. Download `project_tracker_export.json` (or grab the file from the project dir).
3. Open the [localfirst project tracker](https://microsoft.github.io/aibast-agents-library/tools/localfirst_project_tracker_tool.html).
4. Click "Merge Import Data (JSON)" and pick the file. The preview shows what's new vs. update — projects upsert by stable `id` (sha1 of project path), so re-runs merge in place.

## State

Stateless per call. The only persistent artifact on disk is `~/.brainstem/projects.json` (port-collision avoidance + visibility), written by the agent itself when it runs. No pre-populated `.egg` ships with this rapplication.

## License

BSD-style. Match upstream RAPP licensing.
