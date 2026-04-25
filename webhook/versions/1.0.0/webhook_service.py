"""
webhook_service.py — Optional HTTP layer for the Webhook rapplication.

POST /api/webhook/ingest — external systems send events here.
GET  /api/webhook/events — UI reads the event log.

Stores events in the same .brainstem_data/webhook_events.jsonl that
webhook_agent.py reads. The agent works without this service.
"""

import json
import os
from datetime import datetime, timezone

name = "webhook"

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".brainstem_data")
_EVENTS_FILE = os.path.join(_DATA_DIR, "webhook_events.jsonl")


def _append_event(event):
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_EVENTS_FILE, "a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _read_events(limit=50):
    if not os.path.exists(_EVENTS_FILE):
        return []
    events = []
    with open(_EVENTS_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass
    return events[-limit:]


def handle(method, path, body):
    # POST /api/webhook/ingest — receive an event from an external system
    if method == "POST" and path == "ingest":
        event = {
            "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": body.get("source", "unknown"),
            "event_type": body.get("event_type", body.get("type", "event")),
            "summary": body.get("summary", body.get("text", "")),
            "payload": body,
        }
        _append_event(event)
        return {"status": "ok", "received": True}, 201

    # GET /api/webhook/events — read recent events
    if method == "GET" and path in ("events", ""):
        limit = 50
        events = _read_events(limit)
        return {"events": events, "total": len(events)}, 200

    return {"error": "not found"}, 404
