# AgentTeam — `@kody-w/agent-team-singleton`

> **Plan a project the way the Agent Team Starter Kit would.**
> The persona-routing + outcome-framing brain of [`billwhalenmsft/agent-team-starter-kit`](https://github.com/billwhalenmsft/agent-team-starter-kit), ported to a single rapplication.

A rapplication adapted from Bill Whalen's Agent Team Starter Kit — a framework that deploys an autonomous AI team across GitHub Issues + Azure Functions, with 18 specialized personas (Outcome Framer, DevOps PM, D365 Developer, AI Specialist, Power Platform Dev, Architect, Security Reviewer, …). The kit itself is a GH-Actions / Azure deployment; this rapp is the *brain* of that kit, callable in any RAPP brainstem.

---

## What it does

Give it a project goal. It returns:

1. An **outcome frame** — measurable success metric, definition of done, KPIs.
2. A **persona route** — which of the 18 personas should engage, in what order, with one-line reasons. The three core personas (Outcome Framer, Intake/Logger, Outcome Validator) are always included per the kit's meta-rule.
3. A **paste-ready GitHub issue body** — markdown in the kit's expected shape (`## Outcome / ## Success metric / ## Scope / ## Specialists requested / ## Acceptance criteria / ## Open questions`). Drops straight into a real deployment of the kit.
4. **Needs-you questions** — the escalations the team would surface back to a human before starting.

Useful standalone (you get a structured plan back without standing up Azure). Useful as a companion to the real kit (paste the `issue_body`, label `agent-task`, the kit's workflows take over).

## How it works

- **Headless** — drop `agent_team_agent.py` into any RAPP brainstem's `agents/` directory. Call from `/chat`, from another agent, or from anywhere that runs an installed agent.
- **UI mode** — open the rapplication in a vBrainstem (cloud or tethered). The UI gives you a goal/domain/constraints composer on the left, a four-card output (Outcome · Route · Issue body · Needs-you) on the right, and copy/download for the issue body.

The agent dispatches LLM calls through `from utils.llm import call_llm` (host-provided shim). No API keys in this file. Returns a strict JSON envelope.

## Actions

| Action | What it returns |
|---|---|
| `route` *(default)* | Full envelope: outcome frame + persona route + issue body + needs-you. |
| `frame_outcome` | Outcome frame thoroughly filled; route is just the three core personas. |
| `route_personas` | Persona route filled with the right specialists in order; minimal outcome stub. |
| `draft_issue` | Issue body filled paste-ready; other fields consistent with the body. |

## Inputs

| Field | Required | Notes |
|---|---|---|
| `goal` | yes | The raw project request — what the team needs to deliver. |
| `action` | no | One of the four above. Defaults to `route`. |
| `domain` | no | Bias persona routing: `d365`, `ai`, `power-platform`, `analytics`, `generic`. |
| `constraints` | no | Deadlines, budget, compliance, must-use stack, must-not-use. |

## Example call

```jsonc
{
  "action": "route",
  "goal": "Build a Dataverse-backed intake form that routes customer feedback through Power Automate into a Copilot Studio bot, with a Power BI dashboard for the support lead.",
  "domain": "power-platform"
}
```

Returns (truncated):

```jsonc
{
  "outcome_frame": {
    "success_metric": "Support lead can act on feedback within 24h of submission, measured by median age of open feedback in the dashboard.",
    "definition_of_done": [
      "Dataverse 'CustomerFeedback' entity with intake form deployed",
      "Power Automate flow routes high-severity items to the bot's escalation queue",
      "Power BI report tile pinned to the support lead's workspace"
    ],
    "kpis": ["median feedback age", "% routed to bot", "lead engagement rate"]
  },
  "persona_route": [
    { "persona": "Outcome Framer",   "why": "Confirm the success metric.",                           "order": 0 },
    { "persona": "Intake/Logger",    "why": "Capture the request and log progress.",                 "order": 0 },
    { "persona": "DevOps PM",        "why": "Scope the multi-product plan.",                         "order": 1 },
    { "persona": "D365 Developer",   "why": "Stand up the Dataverse entity + intake form.",          "order": 2 },
    { "persona": "Power Platform Dev","why": "Build the Power Automate flow + Copilot Studio bot.",  "order": 3 },
    { "persona": "Analytics Developer","why": "Pick Power BI; build the report tile.",               "order": 4 },
    { "persona": "Security Reviewer","why": "Check no PII leaks via the Power Automate connectors.", "order": 5 },
    { "persona": "QA Engineer",      "why": "Validate the routing path before close.",               "order": 6 },
    { "persona": "Outcome Validator","why": "Confirm 24h-action SLA is met before close.",           "order": 7 }
  ],
  "issue_body": "## Outcome\nSupport lead acts on customer feedback within 24h…\n\n## Success metric\n…",
  "needs_you_questions": [
    "Which Dataverse environment should the entity live in?",
    "Is there an existing Copilot Studio bot to extend, or should we author a new one?"
  ]
}
```

## Install

```bash
curl -L -o ~/.brainstem/src/rapp_brainstem/agents/agent_team_agent.py \
  https://raw.githubusercontent.com/kody-w/rapp_store/main/apps/@kody-w/agent_team/singleton/agent_team_agent.py
```

Or chat-driven via the binder agent: *"install agent_team"*.

The UI mounts automatically when the rapplication is selected in the [vBrainstem](https://kody-w.github.io/RAPP_Store/vbrainstem.html).

## Files

```
@kody-w/agent_team/
  manifest.json           rapp-application/1.0
  index_entry.json        catalog snippet
  README.md               this
  singleton/
    agent_team_agent.py   single file, BasicAgent contract
  ui/
    index.html            cartridge-protocol-aware iframe UI
```

## Inspired by

[`billwhalenmsft/agent-team-starter-kit`](https://github.com/billwhalenmsft/agent-team-starter-kit) — the persona roster, routing rules, and outcome-first delivery model come from that kit's `PERSONAS.md` and workflow design. Bill ships the deployment; this rapp ports the brain.

## License

MIT (matching the source kit).

## Publisher

[`@kody-w`](https://github.com/kody-w).
