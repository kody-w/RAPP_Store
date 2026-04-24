"""
dashboard_service.py — Optional HTTP layer for the Dashboard rapplication.

GET  /api/dashboard          — all metrics (latest values + counts)
GET  /api/dashboard/<metric> — one metric's full history
POST /api/dashboard/<metric> — log a data point from external systems

Reads/writes the same .brainstem_data/dashboard.json that
dashboard_agent.py uses. The agent works without this service.
"""

import json
import os
from datetime import datetime

name = "dashboard"

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".brainstem_data")
_STATE_FILE = os.path.join(_DATA_DIR, "dashboard.json")


def _read():
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE) as f:
            return json.load(f)
    return {"metrics": {}}


def _write(data):
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def handle(method, path, body):
    data = _read()

    # GET /api/dashboard — overview of all metrics
    if method == "GET" and path == "":
        overview = {}
        for name, m in data.get("metrics", {}).items():
            points = m.get("points", [])
            overview[name] = {
                "unit": m.get("unit", ""),
                "latest": points[-1] if points else None,
                "count": len(points),
            }
        return {"metrics": overview}, 200

    # GET /api/dashboard/<metric> — full history for one metric
    if method == "GET" and path:
        metric_name = path.split("/")[0]
        m = data.get("metrics", {}).get(metric_name)
        if not m:
            return {"error": f"metric '{metric_name}' not found"}, 404
        return {"metric": metric_name, "unit": m.get("unit", ""), "points": m.get("points", [])}, 200

    # POST /api/dashboard/<metric> — log a data point
    if method == "POST" and path:
        metric_name = path.split("/")[0]
        value = body.get("value")
        if value is None:
            return {"error": "value required"}, 400
        unit = body.get("unit", "")
        if metric_name not in data["metrics"]:
            data["metrics"][metric_name] = {"unit": unit, "points": []}
        if unit:
            data["metrics"][metric_name]["unit"] = unit
        data["metrics"][metric_name]["points"].append({
            "value": value,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        data["metrics"][metric_name]["points"] = data["metrics"][metric_name]["points"][-100:]
        _write(data)
        return {"status": "ok", "metric": metric_name, "value": value}, 201

    # DELETE /api/dashboard/<metric> — delete a metric
    if method == "DELETE" and path:
        metric_name = path.split("/")[0]
        if metric_name not in data.get("metrics", {}):
            return {"error": f"metric '{metric_name}' not found"}, 404
        del data["metrics"][metric_name]
        _write(data)
        return {"status": "ok"}, 200

    return {"error": "not found"}, 404
