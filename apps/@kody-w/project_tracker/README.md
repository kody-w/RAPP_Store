# Project Tracker

> Track a portfolio of AI-agent projects and their MVP statements — local-first,
> a web UI plus a headless agent over **one** JSON.

**Project Tracker** is a rapplication with two faces over a single on-device
store:

- a **web UI** (`ui/index.html`) — a 1:1 clone of the aibast-agents-library
  [*local-first project tracker*](https://microsoft.github.io/aibast-agents-library/tools/localfirst_project_tracker_tool.html)
  (Overview, Projects, Agent Library, Timeline, Data Management), and
- a headless **`ProjectTracker`** agent (`singleton/project_tracker_agent.py`)
  you drive over `/chat`.

Both speak the tool's native `projectTrackerData` JSON — `{ projects,
agents: { builtin, custom }, timeline }`, merged by project `id` — so exports
and imports **round-trip** with the hosted web tool.

## Two modes

- **Standalone** — open the UI; it persists to `localStorage`. Fully offline,
  no server, no agent required. This is the exact web tool.
- **Unified** — run the rapplication's local server and the UI and the agent
  share one file (`~/.rapp/project-tracker/projectTrackerData.json`). Projects
  the agent adds appear live in the open UI; edits in the UI are visible to the
  agent. No import/export.

## Use it

Headless (any brainstem): drop the singleton into `agents/` and the next
`/chat` exposes a `ProjectTracker` tool.

```bash
cp singleton/project_tracker_agent.py ~/.brainstem/src/rapp_brainstem/agents/
```

Actions: `add_project`, `update_project`, `set_mvp`, `attach_agents`,
`add_agent`, `list_projects`, `get_project`, `stats`, `export_tracker`,
`import_tracker`.

UI: open `ui/index.html` directly, or serve it locally to unify with the agent.

## Data model

| Project field | |
|---|---|
| `customerName` · `status` · `type` | status ∈ planning/poc/active/production/completed; type ∈ legal/hr/it/compliance/customer-service/other |
| `mvpUseCase` · `mvpDescription` · `mvpTimeline` | the MVP statement |
| `agents[]` · `stakeholders` · `competingSolution` · `contractDetails` · `notes` | context |

## Local-first & privacy

The portfolio lives **on your device only**, outside this bundle. Nothing here
ships any project data — the UI's initial seed is empty and the agent is
generic. Interoperates with the AIBAST project-tracker web tool's JSON; not
affiliated with, and claiming no authority over, Microsoft or AIBAST.

License: MIT.
