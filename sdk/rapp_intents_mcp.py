#!/usr/bin/env python3
"""RAPP Intents: one connection that gives any assistant every installed rapplication and agent.

Apple's App Intents lesson: an app declares its actions once, and every surface (Siri,
Shortcuts, Spotlight) picks them up. Here, the surfaces are AI assistants (Claude Code,
Copilot CLI, any MCP host) and the declarations are small JSON files in ~/.rapp/intents/:

  {"kind": "agent",      "id": "bot_x_ray", "path": ".../bot_x_ray_agent.py", "env": {...}}
      one RAPP agent.py; its metadata becomes one tool, perform() runs it
  {"kind": "agents_dir", "id": "brainstem", "path": ".../agents"}
      every *_agent.py in a Brainstem's agents folder, one tool each
  {"kind": "mcp",        "id": "bot_x_ray_app", "command": ["node", ".../mcp.js"], "cwd": "..."}
      an MCP server an app ships itself; its tools are passed through, prefixed

Connect once (claude mcp add / Copilot's mcp-config.json); installs and uninstalls show up
and disappear on the next tools/list with no reconnecting. Userland only: talks to agent files
and app servers, never edits the Brainstem kernel. Standard library only.
"""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

HOME = Path(os.environ.get("RAPP_INTENTS_DIR") or (Path.home() / ".rapp" / "intents"))
PROTOCOL = "2025-06-18"
SAFE = lambda s: "".join(c if c.isalnum() or c in "_-" else "_" for c in s)[:64]

RUNNER = r'''
import sys, json, types, importlib.util, os, io, contextlib
path, kwargs = sys.argv[1], json.loads(sys.stdin.read())
try:
    import agents.basic_agent  # noqa
except Exception:
    class BasicAgent:
        def __init__(self, name=None, metadata=None):
            self.name, self.metadata = name, metadata
    pkg = types.ModuleType("agents"); mod = types.ModuleType("agents.basic_agent")
    mod.BasicAgent = BasicAgent; pkg.basic_agent = mod
    sys.modules["agents"], sys.modules["agents.basic_agent"] = pkg, mod
    sys.modules["basic_agent"] = mod
spec = importlib.util.spec_from_file_location("_intent_agent", path)
m = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(m)
    base = sys.modules["agents.basic_agent"].BasicAgent
    cls = [v for k, v in vars(m).items() if isinstance(v, type) and issubclass(v, base) and v is not base]
    a = cls[-1]()
    if sys.argv[2] == "meta":
        out = json.dumps(a.metadata)
    else:
        out = str(a.perform(**kwargs))
print(out)
'''


def _intents():
    out = []
    if HOME.is_dir():
        for f in sorted(HOME.glob("*.json")):
            try:
                out.append(json.loads(f.read_text()))
            except Exception:
                pass
    return out


def _run_agent(path, mode, kwargs=None, env=None, timeout=900, python=None):
    e = dict(os.environ, **(env or {}))
    brain = e.get("RAPP_INTENTS_BRAINSTEM")  # optional: real BasicAgent from a Brainstem source dir
    if brain:
        e["PYTHONPATH"] = brain + os.pathsep + e.get("PYTHONPATH", "")
    p = subprocess.run([python or sys.executable, "-c", RUNNER, str(path), mode], input=json.dumps(kwargs or {}),
                       capture_output=True, text=True, timeout=timeout, env=e, cwd=str(Path(path).parent))
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip()[-1500:])
    return p.stdout.strip()


class _Child:
    """A pass-through to an MCP server an app ships itself (stdio, newline-delimited JSON-RPC)."""

    def __init__(self, command, cwd=None, env=None):
        self.p = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, env=dict(os.environ, **(env or {})))
        self.n = 0
        self.lock = threading.Lock()
        self.call("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                 "clientInfo": {"name": "rapp-intents", "version": "1.0.0"}})
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.p.stdin.flush()

    def call(self, method, params):
        with self.lock:
            self.n += 1
            self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}) + "\n")
            self.p.stdin.flush()
            while True:
                line = self.p.stdout.readline()
                if not line:
                    raise RuntimeError("the app's connector stopped")
                msg = json.loads(line)
                if msg.get("id") == self.n:
                    if "error" in msg:
                        raise RuntimeError(msg["error"].get("message", "error"))
                    return msg["result"]

    def alive(self):
        return self.p.poll() is None


class Server:
    def __init__(self):
        self.children = {}
        self.meta_cache = {}
        self.routes = {}

    def _child(self, it):
        key = it["id"]
        c = self.children.get(key)
        if not c or not c.alive():
            c = self.children[key] = _Child(it["command"], it.get("cwd"), it.get("env"))
        return c

    def _agent_meta(self, path, env, python=None):
        st = Path(path).stat()
        k = (str(path), st.st_mtime_ns)
        if k not in self.meta_cache:
            self.meta_cache[k] = json.loads(_run_agent(path, "meta", env=env, timeout=120, python=python))
        return self.meta_cache[k]

    def tools(self):
        tools, routes = [], {}
        for it in _intents():
            try:
                if it["kind"] in ("agent", "agents_dir"):
                    paths = [Path(it["path"])] if it["kind"] == "agent" else sorted(
                        p for p in Path(it["path"]).glob("*_agent.py") if p.name != "basic_agent.py")
                    for p in paths:
                        try:
                            md = self._agent_meta(p, it.get("env"), it.get("python"))
                        except Exception:
                            continue
                        name = SAFE(md.get("name") or p.stem) if it["kind"] == "agent" else SAFE(f"{it['id']}__{md.get('name') or p.stem}")
                        tools.append({"name": name, "description": md.get("description", "")[:1000],
                                      "inputSchema": md.get("parameters") or {"type": "object", "properties": {}}})
                        routes[name] = ("agent", str(p), it.get("env"), it.get("python"))
                elif it["kind"] == "mcp":
                    for t in self._child(it).call("tools/list", {}).get("tools", []):
                        name = SAFE(f"{it['id']}__{t['name']}")
                        tools.append(dict(t, name=name))
                        routes[name] = ("mcp", it, t["name"])
            except Exception as e:
                sys.stderr.write(f"rapp-intents: skipped {it.get('id')}: {e}\n")
        self.routes = routes
        return tools

    def call(self, name, args):
        if name not in self.routes:
            self.tools()
        r = self.routes.get(name)
        if not r:
            return {"content": [{"type": "text", "text": f"No tool named {name} (was it uninstalled?)"}], "isError": True}
        try:
            if r[0] == "agent":
                return {"content": [{"type": "text", "text": _run_agent(r[1], "call", args, r[2], python=r[3])}]}
            return self._child(r[1]).call("tools/call", {"name": r[2], "arguments": args})
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    def handle(self, msg):
        m, i, p = msg.get("method"), msg.get("id"), msg.get("params") or {}
        if i is None:
            return None
        if m == "initialize":
            res = {"protocolVersion": p.get("protocolVersion", PROTOCOL),
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "rapp-intents", "version": "1.0.0"},
                   "instructions": "Every installed rapplication and RAPP agent on this computer, behind one connection."}
        elif m == "tools/list":
            res = {"tools": self.tools()}
        elif m == "tools/call":
            res = self.call(p.get("name"), p.get("arguments") or {})
        elif m == "ping":
            res = {}
        else:
            return {"jsonrpc": "2.0", "id": i, "error": {"code": -32601, "message": f"unknown method {m}"}}
        return {"jsonrpc": "2.0", "id": i, "result": res}


def main():
    if "--list" in sys.argv:
        for t in Server().tools():
            print(t["name"], "-", t["description"][:90])
        return
    s = Server()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            out = s.handle(json.loads(line))
        except Exception as e:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}
        if out:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
