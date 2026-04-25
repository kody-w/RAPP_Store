"""
kanban_agent.py — Task board you talk to.

Agent-first: works through any LLM (brainstem chat, Copilot Studio,
Claude, etc.) with no UI required. The optional kanban_service.py
exposes the same data over HTTP for drag-and-drop web UIs.

Storage: .brainstem_data/kanban.json via the local storage shim.
"""

import json
import uuid
from datetime import datetime
from agents.basic_agent import BasicAgent


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/kanban",
    "version": "1.0.0",
    "display_name": "Kanban",
    "description": "Task board you can talk to. Create, move, and query tasks through conversation.",
    "author": "RAPP",
    "tags": ["workspace", "tasks", "rapplication"],
    "category": "workspace",
    "quality_tier": "official",
    "requires_env": [],
    "example_call": "Create a task called 'Fix auth bug' in the backlog",
}

_DATA_KEY = "kanban_v1"


def _data_path():
    import os
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".brainstem_data", "kanban.json"
    )


def _read():
    import os
    path = _data_path()
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"columns": ["backlog", "in-progress", "done"], "tasks": {}}


def _write(data):
    import os
    path = _data_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class KanbanAgent(BasicAgent):
    def __init__(self):
        self.name = "Kanban"
        self.metadata = {
            "name": self.name,
            "description": (
                "Task board you can talk to. Use this to create tasks, move them "
                "between columns (backlog, in-progress, done), list tasks, or "
                "update task details. Call this whenever the user wants to track, "
                "organize, or manage work items."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "move", "list", "update", "delete"],
                        "description": "What to do.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Task title (for create/update).",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Task ID (for move/update/delete). Use 'list' first to find IDs.",
                    },
                    "column": {
                        "type": "string",
                        "description": "Target column (for create/move). Default columns: backlog, in-progress, done.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes or description for the task.",
                    },
                },
                "required": ["action"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get("action", "list")
        board = _read()

        if action == "create":
            title = kwargs.get("title", "Untitled")
            column = kwargs.get("column", "backlog")
            notes = kwargs.get("notes", "")
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
            return json.dumps({
                "status": "ok",
                "summary": f'Created task "{title}" in {column} (ID: {tid})',
                "task_id": tid,
            })

        if action == "move":
            tid = kwargs.get("task_id", "")
            column = kwargs.get("column", "")
            if tid not in board["tasks"]:
                return json.dumps({"status": "error", "summary": f"Task {tid} not found."})
            if column not in board["columns"]:
                board["columns"].append(column)
            old_col = board["tasks"][tid]["column"]
            board["tasks"][tid]["column"] = column
            _write(board)
            return json.dumps({
                "status": "ok",
                "summary": f'Moved "{board["tasks"][tid]["title"]}" from {old_col} to {column}',
            })

        if action == "list":
            if not board["tasks"]:
                return json.dumps({"status": "ok", "summary": "Board is empty.", "board": board})
            lines = []
            for col in board["columns"]:
                tasks_in_col = [(tid, t) for tid, t in board["tasks"].items() if t["column"] == col]
                if tasks_in_col:
                    lines.append(f"\n**{col}** ({len(tasks_in_col)})")
                    for tid, t in tasks_in_col:
                        line = f"  - [{tid}] {t['title']}"
                        if t.get("notes"):
                            line += f" — {t['notes']}"
                        lines.append(line)
            return json.dumps({
                "status": "ok",
                "summary": "\n".join(lines),
                "board": board,
            })

        if action == "update":
            tid = kwargs.get("task_id", "")
            if tid not in board["tasks"]:
                return json.dumps({"status": "error", "summary": f"Task {tid} not found."})
            if kwargs.get("title"):
                board["tasks"][tid]["title"] = kwargs["title"]
            if kwargs.get("notes"):
                board["tasks"][tid]["notes"] = kwargs["notes"]
            if kwargs.get("column"):
                board["tasks"][tid]["column"] = kwargs["column"]
            _write(board)
            return json.dumps({
                "status": "ok",
                "summary": f'Updated task {tid}: "{board["tasks"][tid]["title"]}"',
            })

        if action == "delete":
            tid = kwargs.get("task_id", "")
            if tid not in board["tasks"]:
                return json.dumps({"status": "error", "summary": f"Task {tid} not found."})
            title = board["tasks"].pop(tid)["title"]
            _write(board)
            return json.dumps({"status": "ok", "summary": f'Deleted task "{title}"'})

        return json.dumps({"status": "error", "summary": f"Unknown action: {action}"})
