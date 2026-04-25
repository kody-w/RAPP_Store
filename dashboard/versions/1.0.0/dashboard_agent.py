"""
dashboard_agent.py — Metrics you talk to.

Agent-first: track and query metrics through conversation with any LLM.
"Log API latency at 230ms" or "show me this week's metrics" — no UI needed.

The optional dashboard_service.py exposes the same data over HTTP for
charting UIs.

Storage: .brainstem_data/dashboard.json
"""

import json
import os
from datetime import datetime
from agents.basic_agent import BasicAgent


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/dashboard",
    "version": "1.0.0",
    "display_name": "Dashboard",
    "description": "Track and query metrics through conversation.",
    "author": "RAPP",
    "tags": ["analytics", "metrics", "rapplication"],
    "category": "analytics",
    "quality_tier": "official",
    "requires_env": [],
    "example_call": "Log API latency at 230ms",
}


def _data_path():
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".brainstem_data", "dashboard.json"
    )


def _read():
    path = _data_path()
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"metrics": {}}


def _write(data):
    path = _data_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class DashboardAgent(BasicAgent):
    def __init__(self):
        self.name = "Dashboard"
        self.metadata = {
            "name": self.name,
            "description": (
                "Tracks and queries metrics through conversation. Use this to "
                "log a data point (e.g. 'API latency is 230ms'), view current "
                "metrics, or get a summary. Works like a personal metrics "
                "dashboard you talk to."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["log", "list", "get", "delete"],
                        "description": "What to do. 'log' records a value, 'list' shows all metrics, 'get' shows one metric's history, 'delete' removes a metric.",
                    },
                    "metric": {
                        "type": "string",
                        "description": "Metric name (e.g. 'api_latency', 'daily_users', 'build_time').",
                    },
                    "value": {
                        "type": "number",
                        "description": "The value to log (for 'log' action).",
                    },
                    "unit": {
                        "type": "string",
                        "description": "Unit of measurement (e.g. 'ms', 'users', 'seconds'). Optional.",
                    },
                },
                "required": ["action"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get("action", "list")
        data = _read()

        if action == "log":
            metric_name = kwargs.get("metric", "")
            value = kwargs.get("value")
            unit = kwargs.get("unit", "")
            if not metric_name or value is None:
                return json.dumps({"status": "error", "summary": "Need 'metric' and 'value' to log."})

            if metric_name not in data["metrics"]:
                data["metrics"][metric_name] = {"unit": unit, "points": []}
            if unit:
                data["metrics"][metric_name]["unit"] = unit

            data["metrics"][metric_name]["points"].append({
                "value": value,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
            # Keep last 100 points per metric
            data["metrics"][metric_name]["points"] = data["metrics"][metric_name]["points"][-100:]
            _write(data)
            unit_str = f" {unit}" if unit else ""
            return json.dumps({
                "status": "ok",
                "summary": f"Logged {metric_name} = {value}{unit_str}",
            })

        if action == "get":
            metric_name = kwargs.get("metric", "")
            if metric_name not in data["metrics"]:
                return json.dumps({"status": "ok", "summary": f"No metric '{metric_name}' found."})
            m = data["metrics"][metric_name]
            points = m["points"]
            unit = m.get("unit", "")
            if not points:
                return json.dumps({"status": "ok", "summary": f"{metric_name}: no data points yet."})
            latest = points[-1]
            values = [p["value"] for p in points]
            unit_str = f" {unit}" if unit else ""
            return json.dumps({
                "status": "ok",
                "summary": (
                    f"**{metric_name}** ({len(points)} points)\n"
                    f"  Latest: {latest['value']}{unit_str} ({latest['timestamp']})\n"
                    f"  Min: {min(values)}{unit_str} | Max: {max(values)}{unit_str} | "
                    f"Avg: {sum(values)/len(values):.1f}{unit_str}"
                ),
                "metric": m,
            })

        if action == "list":
            if not data["metrics"]:
                return json.dumps({"status": "ok", "summary": "No metrics tracked yet."})
            lines = []
            for name, m in data["metrics"].items():
                points = m["points"]
                unit = m.get("unit", "")
                unit_str = f" {unit}" if unit else ""
                if points:
                    latest = points[-1]
                    lines.append(f"  - **{name}**: {latest['value']}{unit_str} ({len(points)} points)")
                else:
                    lines.append(f"  - **{name}**: no data")
            return json.dumps({
                "status": "ok",
                "summary": f"{len(data['metrics'])} metrics:\n" + "\n".join(lines),
                "metrics": {k: {"unit": v.get("unit", ""), "latest": v["points"][-1] if v["points"] else None, "count": len(v["points"])} for k, v in data["metrics"].items()},
            })

        if action == "delete":
            metric_name = kwargs.get("metric", "")
            if metric_name not in data["metrics"]:
                return json.dumps({"status": "ok", "summary": f"Metric '{metric_name}' not found."})
            del data["metrics"][metric_name]
            _write(data)
            return json.dumps({"status": "ok", "summary": f"Deleted metric '{metric_name}'"})

        return json.dumps({"status": "error", "summary": f"Unknown action: {action}"})
