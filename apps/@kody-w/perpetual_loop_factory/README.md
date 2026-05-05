# Perpetual Loop Factory rapplication

**Drop one `.py` — get a four-brainstem self-correcting infinite loop.**

A factory pattern locked into a single drop-in agent. One spawn call instantiates a complete perpetual frame chain locally:

- **Rotating twin council** — N project twins (default 3) summoned via the existing `@kody-w/twin_agent`, each given a role-flavored `soul.md` (Composer / Critic / Synthesizer) derived from the loop's goal.
- **Custom worker agent** — auto-generated per loop, dropped into every rotator's `agents/` directory; each frame appends/edits the artifact and commits with `[frame N]` prefix on its own git branch.
- **Custom diversity audit agent** — dropped into the optional sidecar twin's workspace; whispers concrete anti-monotony directives to the next-up peer via `Twin.chat`.
- **Three small daemons** in `~/.rapp/loops/<loop_name>/`:
  - `pump.py` — round-robin watchdog that rescues stalled rotation
  - `pulse.py` — every-N-seconds diversity audit pulse
  - `dashboard_server.py` + `dashboard.html` — same-origin live observability (no GitHub API, no rate limits)

The whole pattern from "I want to perpetually generate X" to "the chain is alive and committing" is ONE tool call.

## Layout

```
perpetual_loop_factory/
  manifest.json
  index_entry.json
  README.md
  singleton/
    perpetual_loop_factory_agent.py    ← the deployable agent
  ui/
    index.html                          ← the launcher dashboard (cartridge UI)
```

## Use from inside the binder UI

Open `/api/binder/ui/perpetual_loop_factory` and:
1. Type a `loop_name` (kebab-case)
2. Describe what each frame produces (one paragraph)
3. Pick `artifact_path` (default `artifact.md`), `num_rotators` (default 3), `use_diversity_monk` (default on)
4. Click **Spawn**

Every loop you spawn gets its own dedicated dashboard URL and shows up in the right pane with live status + twin chips + a stop button.

## Use directly via the brainstem

```python
PerpetualLoopFactory(
    action="spawn",
    loop_name="infinite-poem",
    description="Each frame appends one stanza referring to a previous noun.",
    artifact_path="poem.md",
    num_rotators=3,
    use_diversity_monk=True,
    poll_interval_s=60,
)
```

Other actions: `list`, `stop`, `status`, `help`.

## What lives where

| Path | Purpose |
|---|---|
| `~/.rapp/loops/<loop_name>/` | per-loop workspace (git worktree, daemons, dashboard, manifest) |
| `~/.rapp/loops/<loop_name>/repo/` | git repo with the artifact, on branch `<loop_name>-loop` |
| `~/.rapp/loops/<loop_name>/loop.json` | manifest of twins + daemons + ports |
| `~/.rapp/twins/<rappid>/` | each twin's own brainstem workspace |
| `~/.rapp/STOP_FRAMES` | global kill switch — touch this and **all** loops idle |

## Verified spawn

Local shakedown spawned `test-haiku` (2 rotators + diversity monk):
- All 3 brainstems booted on distinct ports with auto-propagated Copilot tokens
- Pump + pulse + dashboard daemons running
- Frame 1 committed on `test-haiku-loop` branch — a real haiku written by the auto-generated `TestHaikuFrame` worker agent
- Dashboard live at `http://127.0.0.1:8091/dashboard.html`

## Engineering notes

- **Stdlib + brainstem** only. No third-party deps. Single ~1355-line file.
- **Embedded templates** for: soul.md, worker agent, audit agent, pump.py, pulse.py, dashboard.html, dashboard_server.py. Rendered with simple `{{name}}` substitution.
- **FD-safe Popen**: uses `os.open` + parent-side `os.close` so detached children's stdio survives garbage collection.
- **Auth propagation**: copies the parent brainstem's cached `.copilot_token` into each twin's workspace before booting, so spawned brainstems authenticate immediately.
- **Port allocation** tracks already-allocated ports within a single spawn so multi-twin loops don't collide.

## License

MIT — copy, drop, ship.
