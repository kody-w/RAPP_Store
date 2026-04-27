"""
webhook_agent.py — Query incoming events from external systems.

Agent-first: works through any LLM. Ask "what happened on GitHub today?"
or "show me the last 5 webhook events" — no UI needed.

The optional webhook_service.py exposes a POST endpoint for external
systems to send events to, plus a GET endpoint for the UI.

Storage: .brainstem_data/webhook_events.jsonl
"""

import json
import os
from datetime import datetime
from agents.basic_agent import BasicAgent


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/webhook",
    "version": "1.0.0",
    "display_name": "Webhook",
    "description": "Query and summarize incoming webhook events from external systems.",
    "author": "RAPP",
    "tags": ["integration", "webhook", "rapplication"],
    "category": "integration",
    "quality_tier": "official",
    "requires_env": [],
    "example_call": "What webhook events came in today?",
}


def _events_path():
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".brainstem_data", "webhook_events.jsonl"
    )


def _read_events(max_events=200):
    path = _events_path()
    if not os.path.exists(path):
        return []
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass
    return events[-max_events:]


class WebhookAgent(BasicAgent):
    def __init__(self):
        self.name = "Webhook"
        self.metadata = {
            "name": self.name,
            "description": (
                "Queries incoming webhook events from external systems (GitHub, "
                "Slack, etc.). Use this when the user asks about recent events, "
                "notifications, or activity from connected services. Can filter "
                "by source or keyword."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "search", "summary", "count"],
                        "description": "What to do. 'list' shows recent events, 'search' filters by keyword, 'summary' gives a digest, 'count' returns totals.",
                    },
                    "source": {
                        "type": "string",
                        "description": "Filter by source (e.g. 'github', 'slack'). Optional.",
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keywords to filter events by. Optional.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max events to return. Default 10.",
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["action"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get("action", "list")
        source = kwargs.get("source", "").lower()
        keywords = [k.lower() for k in (kwargs.get("keywords") or [])]
        limit = int(kwargs.get("limit", 10))

        events = _read_events()

        if source:
            events = [e for e in events if e.get("source", "").lower() == source]

        if keywords:
            def matches(e):
                hay = json.dumps(e).lower()
                return any(kw in hay for kw in keywords)
            events = [e for e in events if matches(e)]

        if action == "count":
            by_source = {}
            for e in events:
                s = e.get("source", "unknown")
                by_source[s] = by_source.get(s, 0) + 1
            return json.dumps({
                "status": "ok",
                "summary": f"{len(events)} events total. By source: {by_source}",
                "total": len(events),
                "by_source": by_source,
            })

        if action == "summary":
            recent = events[-limit:]
            if not recent:
                return json.dumps({"status": "ok", "summary": "No events recorded yet."})
            sources = set(e.get("source", "unknown") for e in recent)
            lines = [f"{len(recent)} recent events from: {', '.join(sorted(sources))}"]
            for e in reversed(recent[-5:]):
                ts = e.get("received_at", "?")
                src = e.get("source", "?")
                evt = e.get("event_type", e.get("type", "event"))
                lines.append(f"  - [{src}] {evt} at {ts}")
            return json.dumps({"status": "ok", "summary": "\n".join(lines)})

        # action == "list" or default
        recent = events[-limit:]
        if not recent:
            return json.dumps({"status": "ok", "summary": "No events recorded yet.", "events": []})
        lines = []
        for e in reversed(recent):
            ts = e.get("received_at", "?")
            src = e.get("source", "?")
            evt = e.get("event_type", e.get("type", "event"))
            detail = e.get("summary", e.get("text", ""))
            line = f"  - [{src}] {evt} at {ts}"
            if detail:
                line += f" — {detail[:120]}"
            lines.append(line)
        return json.dumps({
            "status": "ok",
            "summary": f"{len(recent)} events:\n" + "\n".join(lines),
            "events": recent,
        })
