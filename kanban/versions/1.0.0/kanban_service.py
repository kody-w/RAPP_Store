"""
kanban_service.py — Optional HTTP layer for the Kanban rapplication.

Reads/writes the same .brainstem_data/kanban.json that kanban_agent.py
uses. Drop this in services/ if you want a web UI for the board.
The agent works without it.
"""

import json
import os
import uuid
from datetime import datetime

name = "kanban"

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".brainstem_data")
_STATE_FILE = os.path.join(_DATA_DIR, "kanban.json")


def _read():
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE) as f:
            return json.load(f)
    return {"columns": ["backlog", "in-progress", "done"], "tasks": {}}


def _write(data):
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def handle(method, path, body):
    board = _read()

    # GET /api/kanban — full board
    if method == "GET" and path == "":
        return board, 200

    # POST /api/kanban/tasks — create a task
    if method == "POST" and path == "tasks":
        title = body.get("title", "Untitled")
        column = body.get("column", "backlog")
        notes = body.get("notes", "")
        if column not in board["columns"]:
            board["columns"].append(column)
        tid = str(uuid.uuid4())[:8]
        board["tasks"][tid] = {
            "title": title,
            "column": column,
            "notes": notes,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        _write(board)
        return {"status": "ok", "task_id": tid}, 201

    # PUT /api/kanban/tasks/<id> — update/move a task
    if method == "PUT" and path.startswith("tasks/"):
        tid = path[len("tasks/"):]
        if tid not in board["tasks"]:
            return {"error": "task not found"}, 404
        for key in ("title", "column", "notes"):
            if key in body:
                board["tasks"][tid][key] = body[key]
        if body.get("column") and body["column"] not in board["columns"]:
            board["columns"].append(body["column"])
        _write(board)
        return {"status": "ok", "task": board["tasks"][tid]}, 200

    # DELETE /api/kanban/tasks/<id>
    if method == "DELETE" and path.startswith("tasks/"):
        tid = path[len("tasks/"):]
        if tid not in board["tasks"]:
            return {"error": "task not found"}, 404
        board["tasks"].pop(tid)
        _write(board)
        return {"status": "ok"}, 200

    return {"error": "not found"}, 404
