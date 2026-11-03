"""RAPPlication SDK — generate, validate, pack and (on confirm) submit full rapplications.

A rapplication here is a RAPP_Store bundle (SPEC.md, schema rapp-application/1.0):
  <id>/manifest.json, singleton/<id>_agent.py, ui/index.html, README.md, INSTALL_PROMPT.md

The generated singleton is a deterministic installer/launcher for a local app that is
described by a tiny "app spec" (download URLs, check/launch/stop commands). The same spec
also renders an AI-installer prompt in the plain-words, "Step N of M" shape, so a person
can install it by pasting the prompt into any coding assistant OR by asking their Brainstem.

Actions
  from_prompt  read a pasted AI-installer prompt and extract an app spec (no code is run)
  new          write a bundle from an app spec into <home>/bundles/<id>/
  validate     run RAPP_Store's own validator (scripts/lib_rapp.py) on the bundle
  pack         zip the bundle (what the store's Mode A submission carries)
  prompt       print the AI-installer prompt for a bundle
  submit       build the [RAPP] submission issue; dry run unless confirm=true

Precedents: cookiecutter (stamp, never hand-edit generated files), npm (immutable version,
validate before publish), Homebrew casks (a tiny declarative recipe drives the install).
Nothing is published without confirm=true; no secrets are read or written.
"""
# rapp-validator: allow-template-placeholders
import base64
import io
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from agents.basic_agent import BasicAgent

__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@kody-w/rapplication_sdk",
    "version": "1.0.0",
    "description": "Generate, validate, pack and submit full rapplications (RAPP_Store bundles + AI-installer prompt).",
}

STORE_REPO = "kody-w/RAPP_Store"
CATEGORIES = ("productivity", "creative", "analysis", "data", "integration", "platform", "workspace")
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _home():
    base = os.environ.get("RAPPLICATION_SDK_HOME")
    if base:
        return Path(base)
    agents = os.environ.get("AGENTS_PATH") or str(Path(__file__).resolve().parent)
    return Path(agents).resolve().parent / "rapplication-sdk"


def _store_checkout():
    """A read-only clone of RAPP_Store, used only for its validator."""
    d = _home() / ".store"
    if not (d / "scripts" / "lib_rapp.py").is_file():
        d.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", f"https://github.com/{STORE_REPO}.git", str(d)],
                       check=True, capture_output=True, timeout=180)
    return d


# ---------- spec ----------

def spec_from_prompt(text):
    """Pull a declarative app spec out of an AI-installer prompt. Pure text parsing."""
    urls = re.findall(r"https?://[^\s`\"')]+", text)
    tar = next((u for u in urls if u.endswith((".tar.gz", ".tgz"))), None)
    zp = next((u for u in urls if u.endswith(".zip")), None)
    cmds = list(dict.fromkeys(re.findall(r"(node scripts/[a-z_\-]+\.js)", text)))
    folder = None
    m = re.search(r"folder called ([A-Za-z0-9_\-.]+)", text)
    if m:
        folder = m.group(1).rstrip(".")
    title = re.search(r"Install ([A-Z][\w\- ]+?) on this computer", text)
    name = title.group(1).strip() if title else (folder or "app").replace("-", " ").title()
    summ = re.search(r"on this computer for me\. (.+?\.)", text)
    node = re.search(r"Node\.js (\d+)", text)
    pick = lambda key: next((c for c in cmds if key in c), None)
    return {
        "name": name,
        "id": re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"),
        "summary": summ.group(1) if summ else f"Install and run {name} locally.",
        "folder": folder or re.sub(r"[^a-z0-9]+", "-", name.lower()),
        "download": {"tar": tar, "zip": zp},
        "runtime": {"node": int(node.group(1))} if node else {},
        "check": pick("check"), "setup": pick("setup"), "launch": pick("launch"),
        "stop": pick("stop"), "marker": "server.js" if "server.js" in text else None,
        "home_url_regex": r"https?://localhost:\d+",
    }


def _clean_spec(spec, publisher, category, tags, version):
    s = dict(spec)
    s["id"] = s.get("id") or ""
    if not ID_RE.match(s["id"]):
        raise ValueError(f"id must be snake_case, got {s['id']!r}")
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}")
    if not (s.get("download") or {}).get("tar"):
        raise ValueError("spec needs download.tar (a .tar.gz URL)")
    if not s.get("launch"):
        raise ValueError("spec needs a launch command")
    s.update(publisher=publisher, category=category, tags=tags or ["rapplication"], version=version)
    return s


# ---------- capture: carry an app's source, fingerprint it, explain it ----------

SKIP_DIRS = {"data", "node_modules", ".git", "__pycache__"}
SKIP_FILES = {".env", ".DS_Store"}


def capture_files(src):
    files = {}
    for f in sorted(Path(src).rglob("*")):
        rel = f.relative_to(src)
        if not f.is_file() or f.is_symlink() or rel.parts[0] in SKIP_DIRS or f.name in SKIP_FILES:
            continue
        files[rel.as_posix()] = f
    return files


def _sha(p):
    import hashlib
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _lead_comment(path):
    try:
        lines = Path(path).read_text(errors="replace").splitlines()[:6]
    except Exception:
        return ""
    keep = [l.lstrip("/#* ").strip() for l in lines if l.strip().startswith(("//", "#", "*", "/*"))]
    return " ".join(k for k in keep if k)[:220]


def anatomy(name, src, files):
    """A plain map of the app, written from its own files (no model involved)."""
    src = Path(src)
    out = [f"# {name}: anatomy", "",
           f"Written by @kody-w/rapplication_sdk from the {len(files)} captured files. Every fact below is read",
           "from the source itself; open the file to see more.", ""]
    pkg = src / "package.json"
    if pkg.is_file():
        pj = json.loads(pkg.read_text())
        out += ["## What it is", "", pj.get("description", ""), "",
                f"Runtime: Node {pj.get('engines', {}).get('node', '?')}. "
                f"npm dependencies: {len(pj.get('dependencies', {}))} (none means plain Node only).", "",
                "## Commands", ""]
        out += [f"- `{k}`: `{v}`" for k, v in pj.get("scripts", {}).items()] + [""]
    server = src / "server.js"
    if server.is_file():
        routes = sorted(set(re.findall(r"[\"'](/api/[a-z0-9/_-]*)", server.read_text())))
        out += ["## Web endpoints (server.js)", ""] + [f"- `{r}`" for r in routes if r != "/api/"] + [""]
    hosts = {}
    for rel, f in files.items():
        if f.suffix in (".js", ".py", ".ts", ".mjs"):
            for h in re.findall(r"https://([a-z0-9.-]+\.[a-z]{2,})", f.read_text(errors="replace")):
                hosts.setdefault(h, set()).add(rel)
    if hosts:
        out += ["## Outside services it talks to", ""]
        out += [f"- {h} (in {', '.join(sorted(v)[:3])})" for h, v in sorted(hosts.items())] + [""]
    out += ["## Every file", "", "| File | Bytes | What it says it does |", "|---|---:|---|"]
    for rel, f in files.items():
        what = _lead_comment(f) if f.suffix in (".js", ".py", ".sh", ".mjs", ".css") else ""
        out.append(f"| `{rel}` | {f.stat().st_size} | {what.replace('|', '/')} |")
    return "\n".join(out) + "\n"


# ---------- generated files ----------

SINGLETON = '''"""__NAME__ — installs and runs the local app from its published download.

Generated by @kody-w/rapplication_sdk. Edit the app spec and regenerate rather than
hand-editing this file. It never asks for passwords or keys and never uses sudo.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import tempfile
import urllib.request
from pathlib import Path

try:
    from agents.basic_agent import BasicAgent
except ImportError:  # run standalone by the keep-alive timer
    class BasicAgent:
        def __init__(self, name=None, metadata=None):
            self.name, self.metadata = name, metadata

__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "__PUBLISHER__/__ID__",
    "version": "__VERSION__",
    "description": __SUMMARY_LIT__,
}

SPEC = json.loads(__SPEC_LIT__)
# sha256 of every app file this rapplication vouches for (empty = not captured)
LOCK = json.loads(__LOCK_LIT__)
BUNDLED = Path(__file__).resolve().parent.parent / "app"


def _base():
    return Path(os.environ.get("__ENVNAME___HOME") or (Path.home() / "Apps"))


def _run(cmd, cwd, timeout=600):
    p = subprocess.run(cmd, cwd=str(cwd), shell=True, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)[-3000:]



def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _tree(d):
    """sha256 of every app file (user data, secrets and caches excluded)."""
    d = Path(d)
    out = {}
    for f in sorted(d.rglob("*")):
        rel = f.relative_to(d)
        if f.is_file() and not f.is_symlink() and rel.parts[0] not in ("data", "node_modules", ".git") \\
                and f.name not in (".env", ".DS_Store"):
            out[rel.as_posix()] = _sha(f)
    return out


def _lead(path):
    try:
        lines = Path(path).read_text(errors="replace").splitlines()[:4]
    except Exception:
        return ""
    keep = [l.lstrip("/#* ").strip() for l in lines if l.strip().startswith(("//", "#", "*"))]
    return " ".join(k for k in keep if k)[:160]


def scan_code(d):
    """What the code can do, read from the files only (nothing is run)."""
    hosts, spawns, secrets, writes = {}, set(), set(), set()
    for f in Path(d).rglob("*"):
        if not f.is_file() or f.suffix not in (".js", ".mjs", ".cjs", ".py", ".sh", ".ts"):
            continue
        rel = f.relative_to(d).as_posix()
        if rel.startswith(("test/", "tests/", "node_modules/")):
            continue
        t = f.read_text(errors="replace")
        for h in re.findall(r"https?://([a-z0-9.-]+\\.[a-z]{2,})", t):
            hosts.setdefault(h, set()).add(rel)
        if re.search(r"child_process|subprocess|os\\.system|\\bexecSync\\b", t):
            spawns.add(rel)
        for k in re.findall(r"process\\.env\\.([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASS)[A-Z0-9_]*)|os\\.environ(?:\\.get)?\\(?\\[?[\\"']([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASS)[A-Z0-9_]*)", t):
            secrets.add(next(x for x in k if x))
        if re.search(r"writeFile|appendFile|open\\([^)]*[\\"']w", t):
            writes.add(rel)
    return {"talks_to": {h: sorted(v)[:3] for h, v in sorted(hosts.items())},
            "starts_other_programs": sorted(spawns), "can_use_keys_if_you_add_them": sorted(secrets),
            "writes_files": sorted(writes)}


def _state_dir():
    d = _base() / ".rapp" / SPEC["folder"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state():
    p = _state_dir() / "state.json"
    return json.loads(p.read_text()) if p.is_file() else {}


def _save(st):
    (_state_dir() / "state.json").write_text(json.dumps(st, indent=1))


def _log(st, msg):
    st.setdefault("events", []).append(time.strftime("%Y-%m-%d %H:%M ") + msg)
    st["events"] = st["events"][-50:]


def _alive(url):
    try:
        urllib.request.urlopen(url, timeout=4)
        return True
    except Exception as e:
        return getattr(e, "code", None) is not None  # an HTTP error still means it answered


def _intents_dir():
    d = Path(os.environ.get("RAPP_INTENTS_DIR") or (Path.home() / ".rapp" / "intents"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_connector(d):
    """An AI connector (MCP server) the app ships itself, if any."""
    for pat in ("scripts/mcp.js", "scripts/mcp.mjs", "mcp.js", "mcp_server.py", "scripts/mcp_server.py", "server/mcp.js"):
        f = Path(d) / pat
        if f.is_file() and "tools/list" in f.read_text(errors="replace"):
            return f
    return None


def _notify(msg):
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", f'display notification {json.dumps(msg)} with title "__NAME__"'],
                       capture_output=True)


class __CLASS__(BasicAgent):
    def __init__(self):
        super().__init__(name="__CLASS__", metadata={
            "name": "__CLASS__",
            "description": ("Look after __NAME__ on this computer: preview it safely before installing, install, "
                            "start, stop, self-test, keep it alive, check for and apply updates (with undo), "
                            "and pack it with its data to move to another computer. " + SPEC["summary"]),
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["status", "preview", "install", "check", "start", "stop",
                                                       "verify", "keepalive_on", "keepalive_off", "heal",
                                                       "update_check", "update", "undo", "export", "import",
                                                       "connect", "uninstall"],
                           "description": ("preview = download to a sealed folder and say what it would do, running nothing; "
                                           "install; start (returns its address); stop; check = self-test; verify = fingerprints; "
                                           "keepalive_on/off = restart it if it stops and self-test daily; heal = one keep-alive pass; "
                                           "update_check = what changed upstream, in plain words; update = apply, keeping data and a "
                                           "snapshot; undo = back to the previous version; export = pack app + data to move it; "
                                           "import = unpack a pack made by export; connect = make it available to every connected AI assistant "
                                           "(done automatically on install); uninstall = remove it everywhere, keeping a copy")},
                "setup_args": {"type": "string", "description": "optional arguments for the setup step, e.g. --country US"},
                "path": {"type": "string", "description": "import: the .tar.gz made by export"},
            }, "required": ["action"]},
        })

    def _dir(self):
        return _base() / SPEC["folder"]

    def _installed(self):
        d = self._dir()
        return d.is_dir() and (not SPEC.get("marker") or (d / SPEC["marker"]).exists())

    def _runtime_ok(self):
        need = SPEC.get("runtime", {}).get("node")
        if not need:
            return True, ""
        if not shutil.which("node"):
            return False, f"Node.js {need}+ is not installed (macOS: brew install node, or https://nodejs.org)."
        v = subprocess.run(["node", "-v"], capture_output=True, text=True).stdout.strip()
        ok = int(re.sub(r"[^0-9.]", "", v).split(".")[0] or 0) >= need
        return ok, v if ok else f"Node {v} is too old; {need}+ needed."

    def _fetch(self, tmp, upstream=False):
        if BUNDLED.is_dir() and not upstream:
            return BUNDLED
        tgz = Path(tmp) / "app.tar.gz"
        req = urllib.request.Request(SPEC["download"]["tar"], headers={"User-Agent": "Mozilla/5.0 (rapplication)"})
        with urllib.request.urlopen(req, timeout=120) as r:
            tgz.write_bytes(r.read())
        out = Path(tmp) / "x"
        with tarfile.open(tgz) as t:
            t.extractall(out, filter="data")
        return out / SPEC["folder"] if (out / SPEC["folder"]).is_dir() else out

    def _lay_down(self, src, keep_user=True):
        d = self._dir()
        d.mkdir(parents=True, exist_ok=True)
        for item in Path(src).iterdir():
            if keep_user and item.name in ("data", ".env"):
                if (d / item.name).exists():
                    continue
            dest = d / item.name
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            elif dest.exists():
                dest.unlink()
            (shutil.copytree if item.is_dir() else shutil.copy2)(str(item), str(dest))

    def _snapshot(self):
        d, snap = self._dir(), _state_dir() / "versions" / time.strftime("%Y%m%d-%H%M%S")
        snap.mkdir(parents=True)
        for item in d.iterdir():
            if item.name in ("data", ".env", "node_modules"):
                continue
            (shutil.copytree if item.is_dir() else shutil.copy2)(str(item), str(snap / item.name))
        return snap

    def _stop(self, by_user=False):
        if SPEC.get("stop") and self._installed():
            _run(SPEC["stop"], self._dir(), 60)
        st = _state()
        for _ in range(20):  # wait until it has really stopped answering
            if not (st.get("url") and _alive(st["url"])):
                break
            time.sleep(0.5)
        if by_user:
            st["paused"] = True  # keep-alive leaves it alone until it is started again
            _log(st, "stopped by you")
            _save(st)

    def _start(self):
        code, out = _run(SPEC["launch"], self._dir(), 120)
        m = re.search(SPEC["home_url_regex"], out)
        st = _state()
        st.pop("paused", None)
        if m:
            st["url"] = m.group(0)
        _save(st)
        return m.group(0) if m else None, out

    def _selftest(self):
        if not SPEC.get("check"):
            return True, "no self-test defined"
        code, out = _run(SPEC["check"], self._dir())
        return code == 0, out

    def _install(self, setup_args=""):
        ok, msg = self._runtime_ok()
        if not ok:
            return msg
        update = self._installed()
        if update:
            self._stop()
            self._snapshot()
        with tempfile.TemporaryDirectory() as tmp:
            self._lay_down(self._fetch(tmp))
        self._register()
        st = _state()
        st["installed"] = _tree(self._dir())
        _log(st, "installed from " + ("captured source" if BUNDLED.is_dir() else "download"))
        _save(st)
        lines = [("Updated" if update else "Installed") + f" __NAME__ in {self._dir()}"
                 + (" from the captured source." if BUNDLED.is_dir() else ".")]
        if LOCK:
            lines.append(self._verify(LOCK))
        ok, out = self._selftest()
        lines.append("Self-test: " + ("READY" if ok else "NOT READY\\n" + out[-800:]))
        if SPEC.get("setup") and not update:
            code, out = _run(f'{SPEC["setup"]} {setup_args}'.strip(), self._dir(), 120)
            lines.append(out.strip()[-600:])
        return "\\n".join(lines)

    def _verify(self, ref=None):
        ref = ref or _state().get("installed") or LOCK
        d = self._dir()
        bad = [rel for rel, h in ref.items() if not (d / rel).is_file() or _sha(d / rel) != h]
        n = len(ref)
        return (f"Fingerprints: {n - len(bad)} of {n} files match exactly."
                + ("" if not bad else " Different: " + ", ".join(bad[:8])))

    # ---- connect once: declare this app to the RAPP Intents bridge
    def _register(self):
        d, ids = _intents_dir(), []
        (d / "__ID__.json").write_text(json.dumps({
            "kind": "agent", "id": "__ID__", "name": "__NAME__", "path": str(Path(__file__).resolve()),
            "env": {"__ENVNAME___HOME": str(_base())}}, indent=1))
        ids.append("__ID__")
        conn = find_connector(self._dir())
        cmd = None
        if conn:
            run = "node" if conn.suffix in (".js", ".mjs") else sys.executable
            cmd = [shutil.which(run) or run, str(conn)]
            (d / "__ID___app.json").write_text(json.dumps({
                "kind": "mcp", "id": "__ID___app", "name": "__NAME__ (its own tools)", "command": cmd,
                "cwd": str(self._dir())}, indent=1))
        return conn

    def _unregister(self):
        for n in ("__ID__.json", "__ID___app.json"):
            f = _intents_dir() / n
            if f.exists():
                f.unlink()

    def _uninstall(self):
        self._stop()
        self._keepalive(False)
        self._unregister()
        d = self._dir()
        keep = _state_dir() / ("uninstalled-" + time.strftime("%Y%m%d-%H%M%S"))
        shutil.move(str(d), str(keep))
        st = _state()
        st.pop("url", None)
        _log(st, "uninstalled; kept in " + keep.name)
        _save(st)
        return (f"Uninstalled __NAME__. It is gone from your assistants and keep-alive is off. "
                f"Everything, including your data, is kept in {keep} in case you want it back.")

    # ---- 1. safe install
    def _preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self._fetch(tmp, upstream=not BUNDLED.is_dir())
            files = _tree(src)
            scan = scan_code(src)
            conn = find_connector(src)
        lines = [f"Preview of __NAME__ ({len(files)} files). Nothing was run.",
                 "It talks to: " + (", ".join(scan["talks_to"]) or "nothing outside this computer") + "."]
        lines.append("It starts other programs from: " + (", ".join(scan["starts_other_programs"]) or "nowhere") + ".")
        if scan["can_use_keys_if_you_add_them"]:
            lines.append("It can use these keys if you add them yourself: "
                         + ", ".join(scan["can_use_keys_if_you_add_them"]) + ". It never needs them to install.")
        lines.append("It writes files from: " + (", ".join(scan["writes_files"][:6]) or "nowhere") + ".")
        if conn:
            lines.append(f"It ships its own AI connector ({conn.relative_to(src)}). After install, every assistant "
                         "connected to RAPP Intents gets its tools; no separate setup command.")
        return "\\n".join(lines)

    # ---- 2. keep-alive
    def _plist(self):
        return Path.home() / "Library" / "LaunchAgents" / f"com.rapp.__ID__.keepalive.plist"

    def _keepalive(self, on):
        p = self._plist()
        uid = str(os.getuid())
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(p)], capture_output=True)
        if not on:
            if p.exists():
                p.unlink()
            return "Keep-alive is off."
        p.parent.mkdir(parents=True, exist_ok=True)
        log = _state_dir() / "keepalive.log"
        p.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.rapp.__ID__.keepalive</string>
<key>ProgramArguments</key><array><string>{sys.executable}</string><string>{Path(__file__).resolve()}</string><string>--heal</string></array>
<key>EnvironmentVariables</key><dict><key>__ENVNAME___HOME</key><string>{_base()}</string><key>PATH</key><string>{os.environ.get("PATH", "/usr/bin:/bin")}</string></dict>
<key>StartInterval</key><integer>600</integer>
<key>RunAtLoad</key><true/>
<key>StandardOutPath</key><string>{log}</string><key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
""")
        r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(p)], capture_output=True, text=True)
        if r.returncode:
            return "Could not turn keep-alive on: " + r.stderr.strip()
        return "Keep-alive is on: every 10 minutes it restarts __NAME__ if it stopped, and runs the self-test once a day. You only hear from it when something needs you."

    def _heal(self):
        st = _state()
        if not self._installed():
            return "not installed"
        said = []
        if st.get("paused"):
            return "paused (you stopped it; say start to resume)"
        if not (st.get("url") and _alive(st["url"])):
            url, _ = self._start()
            st = _state()
            _log(st, "restarted" if url else "restart failed")
            said.append(f"restarted at {url}" if url else "could not restart")
            if not url:
                _notify("__NAME__ stopped and would not restart. Ask your Brainstem about it.")
        today = time.strftime("%Y-%m-%d")
        if st.get("last_check") != today:
            ok, out = self._selftest()
            st["last_check"], st["last_check_ok"] = today, ok
            _log(st, "daily self-test " + ("READY" if ok else "NOT READY"))
            said.append("self-test " + ("READY" if ok else "NOT READY"))
            if not ok:
                fails = [l.strip() for l in out.splitlines() if l.strip().startswith("FAIL")][:2]
                _notify("Daily check found a problem: " + ("; ".join(fails) or "see the self-test"))
        _save(st)
        return ", ".join(said) or "healthy"

    # ---- 3. updates with a plain-words diff and undo
    def _update_check(self):
        now = _tree(self._dir())
        mine = _state().get("installed") or now
        local = sorted(k for k in now if mine.get(k) != now[k])
        with tempfile.TemporaryDirectory() as tmp:
            src = self._fetch(tmp, upstream=True)
            theirs = _tree(src)
            changed = sorted(k for k in theirs if k in mine and mine[k] != theirs[k])
            added = sorted(set(theirs) - set(mine))
            gone = sorted(set(mine) - set(theirs))
            notes = []
            for k in (changed + added)[:12]:
                a = (self._dir() / k).read_text(errors="replace").count("\\n") if (self._dir() / k).is_file() else 0
                b = (Path(src) / k).read_text(errors="replace").count("\\n")
                what = _lead(Path(src) / k)
                notes.append(f"- {k} ({'new' if k in added else f'{b - a:+d} lines'})" + (f": {what}" if what else ""))
        mine_note = ("\\nChanged on this computer since install (an update would replace these; undo brings them back): "
                     + ", ".join(local[:8])) if local else ""
        if not (changed or added or gone):
            return f"__NAME__ is up to date ({len(theirs)} files match the published version)." + mine_note
        head = f"An update is available: {len(changed)} changed, {len(added)} new, {len(gone)} removed." + mine_note
        return head + "\\n" + "\\n".join(notes) + ("\\nRemoved: " + ", ".join(gone[:8]) if gone else "") + \\
            "\\nSay 'update' to apply it (your data stays; you can undo)."

    def _update(self):
        was = bool(_state().get("url") and _alive(_state()["url"]))
        self._stop()
        snap = self._snapshot()
        with tempfile.TemporaryDirectory() as tmp:
            self._lay_down(self._fetch(tmp, upstream=True))
        st = _state()
        st["installed"] = _tree(self._dir())
        _log(st, "updated; snapshot " + snap.name)
        _save(st)
        ok, out = self._selftest()
        msg = f"Updated. Snapshot {snap.name} kept for undo. Self-test: " + ("READY" if ok else "NOT READY")
        if was:
            url, _ = self._start()
            msg += f". Running again at {url}" if url else ""
        return msg

    def _undo(self):
        vs = sorted((_state_dir() / "versions").glob("*")) if (_state_dir() / "versions").is_dir() else []
        if not vs:
            return "There is no earlier version to go back to."
        snap = vs[-1]
        self._stop()
        d = self._dir()
        for item in d.iterdir():
            if item.name in ("data", ".env", "node_modules"):
                continue
            shutil.rmtree(item) if item.is_dir() and not item.is_symlink() else item.unlink()
        for item in snap.iterdir():
            (shutil.copytree if item.is_dir() else shutil.copy2)(str(item), str(d / item.name))
        shutil.rmtree(snap)
        st = _state()
        st["installed"] = _tree(d)
        _log(st, "undo to " + snap.name)
        _save(st)
        ok, _ = self._selftest()
        return f"Back to the version from {snap.name}. Your data was not touched. Self-test: " + ("READY" if ok else "NOT READY")

    # ---- 4. move to another computer
    def _export(self):
        d = self._dir()
        out = _state_dir() / f"{SPEC['folder']}-move-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
        with tarfile.open(out, "w:gz") as t:
            t.add(Path(__file__).resolve(), arcname="rapp_agent.py")
            for f in sorted(d.rglob("*")):
                rel = f.relative_to(d)
                if f.is_file() and f.name != ".env" and rel.parts[0] != "node_modules" and not f.name.endswith((".pid", ".log")):
                    t.add(f, arcname=f"{SPEC['folder']}/{rel.as_posix()}")
        mb = out.stat().st_size / 1e6
        return (f"Packed __NAME__ with its data: {out} ({mb:.1f} MB). Your .env (keys) was left out on purpose. "
                "On the other computer, give this agent the file and say 'import'.")

    def _import(self, path):
        p = Path(path or "").expanduser()
        if not p.is_file():
            return "Give me the path of the .tar.gz made by export."
        if self._installed():
            self._stop()
            self._snapshot()
        with tempfile.TemporaryDirectory() as tmp, tarfile.open(p) as t:
            t.extractall(tmp, filter="data")
            self._lay_down(Path(tmp) / SPEC["folder"], keep_user=False)
        st = _state()
        st["installed"] = _tree(self._dir())
        self._register()
        _log(st, "imported from " + p.name)
        _save(st)
        ok, _ = self._selftest()
        return f"Imported __NAME__ with its data into {self._dir()}. Self-test: " + ("READY" if ok else "NOT READY")

    def perform(self, **kwargs):
        action = kwargs.get("action", "status")
        try:
            if action == "preview":
                return self._preview()
            if action == "install":
                return self._install(kwargs.get("setup_args", ""))
            if action == "import":
                return self._import(kwargs.get("path"))
            if action == "keepalive_off":
                return self._keepalive(False)
            d = self._dir()
            if not self._installed():
                return f"__NAME__ is not installed yet. Ask me to preview or install it (it goes in {d})."
            if action == "verify":
                return self._verify()
            if action == "check":
                ok, out = self._selftest()
                return ("READY" if ok else "NOT READY") + "\\n" + out[-1200:]
            if action == "stop":
                self._stop(by_user=True)
                return "Stopped. Keep-alive will leave it stopped until you start it again."
            if action == "start":
                url, out = self._start()
                return f"__NAME__ is running at {url}" if url else out.strip()
            if action == "keepalive_on":
                return self._keepalive(True)
            if action == "heal":
                return self._heal()
            if action == "update_check":
                return self._update_check()
            if action == "update":
                return self._update()
            if action == "undo":
                return self._undo()
            if action == "export":
                return self._export()
            if action == "uninstall":
                return self._uninstall()
            if action == "connect":
                conn = self._register()
                return ("__NAME__ is available to every assistant connected to RAPP Intents"
                        + (f", including its own tools from {conn.relative_to(self._dir())}." if conn else "."))
            st = _state()
            return json.dumps({"installed": True, "folder": str(d), "address": st.get("url"),
                               "running": bool(st.get("url") and _alive(st["url"])),
                               "keepalive": self._plist().exists(), "recent": st.get("events", [])[-5:]})
        except Exception as e:
            return f"Error: {e}"


if __name__ == "__main__" and "--heal" in sys.argv:
    print(time.strftime("%H:%M"), __CLASS__().perform(action="heal"), flush=True)
'''

UI = '''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__NAME__</title>
<style>
body{font:16px/1.5 system-ui,-apple-system,sans-serif;max-width:640px;margin:48px auto;padding:0 20px;color:#1b1b1f}
h1{font-size:28px;margin:0 0 6px}p.s{color:#555;margin:0 0 24px}
button{font:inherit;padding:12px 22px;border:0;border-radius:10px;background:#1b1b1f;color:#fff;cursor:pointer}
button.alt{background:#eee;color:#1b1b1f;margin-left:8px}#out{white-space:pre-wrap;margin-top:20px;color:#333}
</style></head><body>
<h1>__NAME__</h1><p class="s">__SUMMARY__</p>
<button id="go">Start it</button><button class="alt" id="setup">Install or update</button>
<div id="out"></div>
<script>
const out = document.getElementById('out');
function call(args){
  return new Promise((ok, bad) => {
    if (window.parent === window) { bad(new Error('Open this inside a Brainstem, or ask your Brainstem: "start __NAME__".')); return; }
    const id = Math.random().toString(36).slice(2);
    const h = e => { if (e.data && e.data.type === 'rapp:invoke:result' && e.data.id === id) {
      removeEventListener('message', h); e.data.error ? bad(new Error(e.data.error)) : ok(e.data.result); } };
    addEventListener('message', h);
    parent.postMessage({ type: 'rapp:invoke', id, args }, '*');
  });
}
async function run(action){
  out.textContent = action === 'install' ? 'Installing — about a minute…' : 'Starting…';
  try {
    const r = String(await call({ action }));
    const m = r.match(/https?:\\/\\/localhost:\\d+/);
    out.innerHTML = '';
    out.textContent = r;
    if (m) { const a = document.createElement('a'); a.href = m[0]; a.target = '_blank'; a.textContent = ' Open it'; out.appendChild(a); }
  } catch (e) { out.textContent = e.message; }
}
document.getElementById('go').onclick = () => run('start');
document.getElementById('setup').onclick = () => run('install');
</script></body></html>
'''


def render_prompt(s):
    node = s.get("runtime", {}).get("node")
    steps = []
    steps.append(("CHECK THIS COMPUTER",
                  f"Work out the operating system and shell. Run `node -v`. {node} or newer: carry on. Missing or older: tell me, offer the simplest install (macOS: `brew install node`, Windows: `winget install --id OpenJS.NodeJS.LTS -e`, Linux: the distro package or nvm) and wait for my yes."
                  if node else "Work out the operating system and shell."))
    dl = f"Install into a folder called {s['folder']} inside the folder you're in now; the download already contains that folder.\n- If ./{s['folder']} already exists, this is an update: "
    dl += (f"run `{s['stop']}` inside it first, then " if s.get("stop") else "")
    dl += f"download into a temporary folder and copy everything over except data/ and .env.\n- macOS, Linux or Git Bash: `curl -fsSL {s['download']['tar']} | tar -xz`"
    if s["download"].get("zip"):
        dl += f"\n- Windows PowerShell: download {s['download']['zip']} with Invoke-WebRequest and Expand-Archive it here."
    steps.append(("DOWNLOAD", dl))
    if s.get("check"):
        steps.append(("TEST IT", f"Run `{s['check']}`. READY: tell me in one line what works. NOT READY: read the FAIL lines, fix the cause, run it again."))
    if s.get("setup"):
        steps.append(("SET IT UP", f"Skip this if it was an update. Otherwise run `{s['setup']}` with any answers it needs, and tell me in one line what it set."))
    steps.append(("OPEN IT", f"Run `{s['launch']}`. Give me the address it prints as a link."
                  + (f" Stop it any time with `{s['stop']}`." if s.get("stop") else "")))
    n = len(steps)
    body = [f"Install {s['name']} on this computer for me. {s['summary']}", "",
            "HOW TO WORK WITH ME",
            "- Short sentences, everyday words. Explain any technical word the first time.",
            "- Before each step, say in one line what you're about to do, as \"Step 2 of %d\"." % n,
            "- Run every command yourself. Only hand me a command if it needs my password or admin rights.",
            "- If a command fails, read the error, fix the cause and retry, up to three times, then tell me plainly.",
            "- Never ask me for passwords, API keys or logins. Don't use sudo. Don't change the app's code.",
            "- If you can't ask me questions, use the defaults and keep going.",
            f"- Prefer a Brainstem? Install the rapplication {s['publisher']}/{s['id']} and say \"install {s['name']}\".", ""]
    for i, (t, txt) in enumerate(steps, 1):
        body += [f"STEP {i} OF {n}: {t}", txt, ""]
    body.append(f"Finish with one short, friendly message: where it's running, how to open it next time (`{s['launch']}`), and how to stop it.")
    return "\n".join(body) + "\n"


def write_bundle(s, home, source=None):
    root = home / "bundles" / s["id"]
    if root.exists():
        shutil.rmtree(root)
    (root / "singleton").mkdir(parents=True)
    (root / "ui").mkdir()
    lock = {}
    if source:
        files = capture_files(source)
        for rel, f in files.items():
            dest = root / "app" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            lock[rel] = _sha(f)
        (root / "ANATOMY.md").write_text(anatomy(s["name"], source, files))
    cls = "".join(p.capitalize() for p in s["id"].split("_")) + "Agent"
    spec_keep = {k: s[k] for k in ("name", "summary", "folder", "download", "runtime", "check",
                                   "setup", "launch", "stop", "marker", "home_url_regex")}
    src = (SINGLETON.replace("__SPEC_LIT__", repr(json.dumps(spec_keep, indent=1)))
           .replace("__LOCK_LIT__", repr(json.dumps(lock, indent=0, sort_keys=True)))
           .replace("__SUMMARY_LIT__", repr(s["summary"]))
           .replace("__ENVNAME__", s["id"].upper())
           .replace("__CLASS__", cls).replace("__NAME__", s["name"])
           .replace("__PUBLISHER__", s["publisher"]).replace("__ID__", s["id"])
           .replace("__VERSION__", s["version"]))
    (root / "singleton" / f"{s['id']}_agent.py").write_text(src)
    esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;")
    (root / "ui" / "index.html").write_text(UI.replace("__NAME__", esc(s["name"])).replace("__SUMMARY__", esc(s["summary"])))
    prompt = render_prompt(s)
    (root / "INSTALL_PROMPT.md").write_text(prompt)
    (root / "README.md").write_text(
        f"# {s['name']}\n\n{s['summary']}\n\n## Two ways to install\n\n"
        f"1. **Brainstem:** install `{s['publisher']}/{s['id']}`, then say \"install {s['name']}\" and \"start {s['name']}\".\n"
        f"2. **Any coding assistant:** paste `INSTALL_PROMPT.md`.\n\n"
        f"The app itself comes from {s['download']['tar']}; this rapplication only installs, checks, starts and stops it.\n")
    manifest = {"schema": "rapp-application/1.0", "id": s["id"], "name": s["name"], "version": s["version"],
                "publisher": s["publisher"], "summary": s["summary"], "category": s["category"],
                "tags": s["tags"], "agent": f"singleton/{s['id']}_agent.py", "ui": "ui/index.html",
                "quality_tier": "community"}
    if lock:
        manifest["tags"] = list(dict.fromkeys(manifest["tags"] + ["captured-source"]))
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (home / "specs").mkdir(parents=True, exist_ok=True)
    (home / "specs" / f"{s['id']}.json").write_text(json.dumps(s, indent=2))
    return root


def validate(root):
    store = _store_checkout()
    code = ("import sys,json;sys.path.insert(0,sys.argv[1]);import lib_rapp as L;"
            "import pathlib;d=pathlib.Path(sys.argv[2]);m=json.loads((d/'manifest.json').read_text());"
            "(d/'index_entry.json').write_text(json.dumps(L.build_index_entry(m,L.compute_integrity(d,m),m['id']),indent=2)+'\\n');"
            "r=L.validate_dir(__import__('pathlib').Path(sys.argv[2]),submission_type='bundle');"
            "print(json.dumps({'ok':r.ok,'errors':r.errors}))")
    p = subprocess.run([sys.executable, "-I", "-c", code, str(store / "scripts"), str(root)],
                       capture_output=True, text=True, timeout=120)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        return {"ok": False, "errors": [p.stderr[-800:]]}


def pack(root):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                z.write(f, f"{root.name}/{f.relative_to(root)}")
    out = root.parent / f"{root.name}.zip"
    out.write_bytes(buf.getvalue())
    return out


def rebuild_agent(root):
    """Load a bundle's generated singleton exactly as a Brainstem would."""
    import importlib.util
    m = json.loads((root / "manifest.json").read_text())
    spec = importlib.util.spec_from_file_location("_gen_" + m["id"], root / m["agent"])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return next(v for k, v in vars(mod).items() if k.endswith("Agent") and k != "BasicAgent" and isinstance(v, type))()


def rebuild(root, target=None):
    """Install the generated singleton into a clean folder and run its own verify + check."""
    import importlib.util
    import tempfile
    target = Path(target).expanduser() if target else Path(tempfile.mkdtemp(prefix="rebuild-"))
    m = json.loads((root / "manifest.json").read_text())
    os.environ[m["id"].upper() + "_HOME"] = str(target)
    agent = rebuild_agent(root)
    return "Rebuilt into " + str(target) + "\n" + agent.perform(action="install")


# ---------- connect once: the RAPP Intents bridge ----------

def _bridge():
    """Install the bridge to a stable place (~/.rapp/) so assistant configs never point into a lab folder."""
    dst = Path.home() / ".rapp" / "rapp_intents_mcp.py"
    here = Path(__file__).resolve().parent
    src = next((c for c in (here / "intents" / "rapp_intents_mcp.py", here / "rapp_intents_mcp.py") if c.is_file()), None)
    if src is None and not dst.is_file():  # installed on its own: fetch the bridge from the store
        import urllib.request
        dst.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen("https://kody-w.github.io/RAPP_Store/sdk/rapp_intents_mcp.py", timeout=60) as r:
            dst.write_bytes(r.read())
    if src:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            shutil.copy2(src, dst)
    if not dst.is_file():
        raise FileNotFoundError("the RAPP Intents bridge is not installed")
    return dst


def connect(host, on=True):
    py = sys.executable
    bridge = _bridge()
    if host == "claude":
        if not shutil.which("claude"):
            return "Claude Code is not installed here."
        subprocess.run(["claude", "mcp", "remove", "--scope", "user", "rapp-intents"], capture_output=True, text=True)
        if not on:
            return "Claude Code is disconnected from RAPP Intents."
        r = subprocess.run(["claude", "mcp", "add", "--scope", "user", "rapp-intents", "--", py, str(bridge)],
                           capture_output=True, text=True)
        return (r.stdout + r.stderr).strip() or "Connected."
    if host == "copilot":
        cfg = Path.home() / ".copilot" / "mcp-config.json"
        data = json.loads(cfg.read_text()) if cfg.is_file() else {"mcpServers": {}}
        if on:
            data.setdefault("mcpServers", {})["rapp-intents"] = {"type": "stdio", "command": py, "args": [str(bridge)], "tools": ["*"]}
        else:
            data.get("mcpServers", {}).pop("rapp-intents", None)
        if cfg.is_file():
            shutil.copy2(cfg, cfg.with_suffix(".json.bak"))
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(data, indent=2) + "\n")
        return f"Copilot CLI {'connected to' if on else 'disconnected from'} RAPP Intents ({cfg}; previous copy saved as .bak)."
    return "host must be claude or copilot"


def expose_agents(path, ident, on=True, python=None):
    d = Path(os.environ.get("RAPP_INTENTS_DIR") or (Path.home() / ".rapp" / "intents"))
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{ident}.json"
    if not on:
        if f.exists():
            f.unlink()
        return f"The agents in {ident} are no longer offered to assistants."
    folder = Path(path).expanduser().resolve()
    if not folder.is_dir():
        return f"No folder at {folder}."
    n = len([p for p in folder.glob("*_agent.py") if p.name != "basic_agent.py"])
    entry = {"kind": "agents_dir", "id": ident, "path": str(folder)}
    for cand in ([Path(python)] if python else []) + [folder.parent / ".venv" / "bin" / "python", Path.home() / ".brainstem" / "venv" / "bin" / "python"]:
        if cand.exists():
            entry["python"] = str(cand)  # run agents with the Brainstem's own Python and packages
            break
    f.write_text(json.dumps(entry, indent=1))
    return f"{n} agents in {folder} are now tools in every assistant connected to RAPP Intents (named {ident}__<agent>)."


PROMO = re.compile(r"\b(free to try|no card|join|academy|course|sign up|subscribe|discount|promo|affiliate|who made this|use[sd]? a free)\b", re.I)
KNOWN_TOOLS = ("nodejs.org", "github.com/nvm-sh", "brew.sh", "python.org", "docs.", "learn.microsoft.com")


def prompt_xray(text):
    """Read an AI-installer prompt and say what it would make an assistant do. Pure text; nothing runs."""
    spec = spec_from_prompt(text)
    cmds = list(dict.fromkeys(c.strip() for c in re.findall(r"`([^`\n]{3,200})`", text)
                              if re.match(r"\s*(curl|wget|node|npm|npx|python|pip|brew|winget|open|tar|bash|sh|sudo|Invoke|Expand|git|claude)", c)))
    dl_hosts = {re.sub(r"^https?://([^/]+).*", r"\1", u) for u in (spec["download"].get("tar"), spec["download"].get("zip")) if u}
    other_links, promo = [], []
    for para in re.split(r"\n\s*\n", text):
        for u in re.findall(r"https?://[^\s`\"')]+", para):
            host = re.sub(r"^https?://([^/]+).*", r"\1", u)
            if host in dl_hosts or any(k in u for k in KNOWN_TOOLS):
                continue
            other_links.append(u)
            if PROMO.search(para):
                promo.append(u)
    installs = [c for c in cmds if re.match(r"\s*(brew|winget|npm i|npm install|pip install|apt)", c)]
    return {
        "app": spec["name"],
        "downloads_from": sorted(dl_hosts),
        "commands_it_asks_the_assistant_to_run": cmds,
        "software_it_may_install": installs,
        "asks_for_admin_or_sudo": bool(re.search(r"(?<!don't use )(?<!no )\bsudo\b", text, re.I)) and not re.search(r"don.t use sudo", text, re.I),
        "asks_for_keys_or_passwords": bool(re.search(r"(paste|enter|give|provide)[^.\n]{0,40}(api key|password|token|secret)", text, re.I)),
        "links_that_are_not_the_install": sorted(set(other_links)),
        "looks_like_promotion": sorted(set(promo)),
        "spec": spec,
    }


def explain_xray(x, preview):
    L = [f"X-ray of the {x['app']} install prompt. Nothing was run."]
    L.append("Downloads from: " + (", ".join(x["downloads_from"]) or "nothing") + ".")
    L.append(f"It asks the assistant to run {len(x['commands_it_asks_the_assistant_to_run'])} commands"
             + (", including installing: " + "; ".join(x["software_it_may_install"]) if x["software_it_may_install"] else "") + ".")
    L.append("Admin/sudo: " + ("YES, read carefully" if x["asks_for_admin_or_sudo"] else "no") +
             ". Asks for keys or passwords: " + ("YES" if x["asks_for_keys_or_passwords"] else "no") + ".")
    if x["looks_like_promotion"]:
        L.append("Not part of the install (looks like promotion): " + ", ".join(x["looks_like_promotion"]) + ". I'll skip these.")
    if preview:
        L += ["", "What the downloaded code itself can do:", preview]
    return "\n".join(L)


class RapplicationSdkAgent(BasicAgent):
    def __init__(self):
        super().__init__(name="RapplicationSdk", metadata={
            "name": "RapplicationSdk",
            "description": ("The rapplication SDK. Turns an app idea or a pasted AI-installer prompt into a full "
                            "rapplication (RAPP_Store bundle with a one-file installer agent, a small UI, a README and "
                            "an AI-installer prompt), validates it with the store's own validator, packs it, and on "
                            "explicit confirmation submits it to the public store."),
            "parameters": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["connect", "disconnect", "expose_agents", "hide_agents", "xray_prompt", "from_prompt", "new", "capture", "rebuild", "validate", "pack", "prompt", "submit"]},
                "source_dir": {"type": "string", "description": "capture: folder of an installed app to carry inside the rapplication"},
                "target_dir": {"type": "string", "description": "rebuild: empty folder to rebuild the app into (default: a fresh temp folder)"},
                "prompt_text": {"type": "string", "description": "for from_prompt / new: the pasted installer prompt"},
                "spec": {"type": "object", "description": "for new: app spec (name, id, summary, folder, download{tar,zip}, runtime{node}, check, setup, launch, stop)"},
                "id": {"type": "string", "description": "rapplication id (snake_case) for validate/pack/prompt/submit"},
                "publisher": {"type": "string", "description": "@github-user, default @kody-w"},
                "category": {"type": "string", "enum": list(CATEGORIES)},
                "tags": {"type": "array", "items": {"type": "string"}},
                "version": {"type": "string"},
                "host": {"type": "string", "enum": ["claude", "copilot"], "description": "connect/disconnect: which assistant"},
                "agents_path": {"type": "string", "description": "expose_agents: a Brainstem agents folder"},
                "python": {"type": "string", "description": "expose_agents: the Python that Brainstem runs with (default: its venv)"},
                "confirm": {"type": "boolean", "description": "submit only: true actually opens the public submission issue"},
            }, "required": ["action"]},
        })

    def perform(self, **kw):
        home = _home()
        a = kw.get("action")
        try:
            if a in ("connect", "disconnect"):
                return connect(kw.get("host") or "claude", a == "connect")
            if a in ("expose_agents", "hide_agents"):
                return expose_agents(kw.get("agents_path") or "", kw.get("id") or "brainstem", a == "expose_agents", kw.get("python"))
            if a == "xray_prompt":
                x = prompt_xray(kw.get("prompt_text", ""))
                preview = None
                try:
                    sp = _clean_spec(x["spec"], kw.get("publisher") or "@kody-w", kw.get("category") or "analysis",
                                     kw.get("tags"), kw.get("version") or "1.0.0")
                    root = write_bundle(sp, home / ".previews")
                    preview = rebuild_agent(root).perform(action="preview")
                except Exception as e:
                    preview = f"(could not preview the code: {e})"
                return explain_xray(x, preview)
            if a == "from_prompt":
                return json.dumps(spec_from_prompt(kw.get("prompt_text", "")), indent=1)
            if a in ("new", "capture"):
                spec = kw.get("spec") or spec_from_prompt(kw.get("prompt_text", ""))
                source = kw.get("source_dir") if a == "capture" else None
                if a == "capture" and not (source and Path(source).expanduser().is_dir()):
                    return "capture needs source_dir: the folder of the installed app."
                s = _clean_spec(spec, kw.get("publisher") or "@kody-w", kw.get("category") or "analysis",
                                kw.get("tags"), kw.get("version") or "1.0.0")
                root = write_bundle(s, home, Path(source).expanduser() if source else None)
                v = validate(root)
                z = pack(root) if v["ok"] else None
                return json.dumps({"bundle": str(root), "valid": v["ok"], "errors": v["errors"],
                                   "zip": str(z) if z else None,
                                   "next": "Say 'submit it' to see the store submission; nothing is published until you confirm."}, indent=1)
            rid = kw.get("id") or ""
            root = home / "bundles" / rid
            if not (root / "manifest.json").is_file():
                return f"No bundle named {rid!r} in {home / 'bundles'}."
            if a == "validate":
                return json.dumps(validate(root), indent=1)
            if a == "pack":
                return str(pack(root))
            if a == "rebuild":
                return rebuild(root, kw.get("target_dir"))
            if a == "prompt":
                return (root / "INSTALL_PROMPT.md").read_text()
            if a == "submit":
                v = validate(root)
                if not v["ok"]:
                    return "Not submitting: the bundle fails validation.\n" + "\n".join(v["errors"])
                m = json.loads((root / "manifest.json").read_text())
                payload = {"submission_type": "bundle", "id": m["id"], "version": m["version"],
                           "publisher": m["publisher"], "name": m["name"], "category": m["category"], "tags": m["tags"]}
                title = f"[RAPP] {m['publisher']}/{m['id']} v{m['version']}"
                b64 = base64.b64encode(pack(root).read_bytes()).decode()
                body = f"```json\n{json.dumps(payload, indent=2)}\n```\n\n```bundle\n{b64}\n```\n"
                if not kw.get("confirm"):
                    return json.dumps({"dry_run": True, "repo": STORE_REPO, "title": title, "payload": payload,
                                       "bundle_bytes": len(b64),
                                       "to_publish": "call submit again with confirm=true"}, indent=1)
                if not shutil.which("gh"):
                    return "The GitHub CLI (gh) is needed to submit."
                p = subprocess.run(["gh", "issue", "create", "-R", STORE_REPO, "--title", title,
                                    "--label", "rapplication-submission", "--body-file", "-"],
                                   input=body, capture_output=True, text=True, timeout=120)
                return p.stdout.strip() or p.stderr.strip()
            return f"Unknown action {a!r}."
        except Exception as e:
            return f"Error: {e}"
