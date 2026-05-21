"""Hatch a project-anchored twin from the global brainstem kernel.

Sibling to twin_egg_hatcher_agent.py: both produce twins under ~/.rapp/twins/.
The hatcher hatches from eggs/repos/cwd-with-rappid; this agent hatches a
fresh project-anchored twin straight from the global kernel.

The hatched twin lives in two places by design:

  PRIMARY (operator-visible, project-anchored):
    <project_path>/.brainstem/src/rapp_brainstem/
      brainstem.py, local_storage.py, agents/, soul.md, rappid.json,
      manifest.json, HATCH_RECEIPT.json, .env, .copilot_token/session

  CANONICAL (spec-discoverable, for the global brainstem's built-in Twin agent):
    ~/.rapp/twins/<32-hex-rappid-hash>/   →  symlink to the PRIMARY dir

The symlink is the bridge: the project owns the files; the canonical
~/.rapp/twins/ root catalogs every twin on the device per
TWIN_LIFECYCLE_SPEC §2 (filesystem-as-source-of-truth). The built-in
Twin agent in the global brainstem picks up the symlinked workspace
exactly like any other twin, so the global can boot, list, and /chat
with project twins without any parallel registry.

Spec conformance:
  - rappid.json shape matches twin_egg_hatcher_agent.py (`rapp-rappid/2.0`,
    `kind: project`, `parent_rappid` from the global brainstem).
  - HATCH_RECEIPT.json is emitted with the same fields the hatcher writes.
  - manifest.json carries `port_hint` so the canonical Twin(boot) verb works.
  - No ~/.brainstem/projects.json — ports are discovered by scanning
    ~/.rapp/twins/*/manifest.json. One registry, on disk.
  - tracker_export uses the canonical rappid 32-hex hash as the project id.

Kernel files (brainstem.py, basic_agent.py, etc.) are copied verbatim from
the global install at ~/.brainstem/src/rapp_brainstem. The kernel itself
is never edited — projects differ via .env, soul.md, and their own agents/.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agents.basic_agent import BasicAgent


RAPP_HOME = Path(os.environ.get("RAPP_HOME", str(Path.home() / ".rapp")))
TWINS_DIR = RAPP_HOME / "twins"
HATCH_RECEIPT_NAME = "HATCH_RECEIPT.json"
HATCHER_VERSION = "hatch_project_twin/0.1.0"

KERNEL_FILES = [
    "brainstem.py",
    "local_storage.py",
    "requirements.txt",
    "start.sh",
    "start.ps1",
    "index.html",
    "VERSION",
]
AGENT_HELPERS = ["basic_agent.py"]
AUTH_FILES = [".copilot_token", ".copilot_session"]
ENV_KEYS_TO_INHERIT = ["GITHUB_TOKEN", "GITHUB_MODEL", "VOICE_ZIP_PASSWORD", "TEAMS_CHANNEL_EMAIL"]
DEFAULT_PORT_FLOOR = 7073

_HASH_RE = re.compile(r":([a-f0-9]{32})@")
_AGENT_NAME_RE = re.compile(r"""self\.name\s*=\s*['"]([^'"]+)['"]""")
_AGENT_DESC_RE = re.compile(r"""['"]description['"]\s*:\s*\(?\s*['"]([^'"]+)['"]""")


def _global_brainstem_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _hash_from_rappid(rappid: str) -> str:
    if rappid and rappid.startswith("rappid:"):
        m = _HASH_RE.search(rappid)
        if m:
            return m.group(1)
    return rappid or ""


def _mint_v2_rappid(kind: str, owner: str, repo: str) -> str:
    h = uuid.uuid4().hex  # 32 hex, no dashes
    return f"rappid:v2:{kind}:@{owner}/{repo}:{h}@github.com/{owner}/{repo}"


def _slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s.strip().lower()).strip("-")
    return s or "project"


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _ports_taken_by_twins() -> set:
    """Scan ~/.rapp/twins/*/manifest.json for port_hint. Filesystem-as-truth."""
    taken = set()
    if not TWINS_DIR.exists():
        return taken
    for entry in TWINS_DIR.iterdir():
        if entry.name.startswith("."):
            continue
        mpath = entry / "manifest.json"
        if not mpath.exists():
            continue
        try:
            m = json.loads(mpath.read_text())
            p = m.get("port_hint") or m.get("port")
            if isinstance(p, int):
                taken.add(p)
        except (json.JSONDecodeError, OSError):
            pass
    return taken


def _pick_port(floor: int, also_avoid: set) -> int:
    taken = _ports_taken_by_twins() | (also_avoid or set())
    port = floor
    while port < 7200:
        if port not in taken and _port_is_free(port):
            return port
        port += 1
    raise RuntimeError(f"no free port in [{floor}, 7200)")


def _read_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def _write_env(path: Path, env: dict) -> None:
    lines = ["# Generated by HatchProjectTwin — edit values, never the kernel.", ""]
    for k in ["GITHUB_TOKEN", "GITHUB_MODEL", "SOUL_PATH", "AGENTS_PATH", "PORT", "VOICE_ZIP_PASSWORD", "TEAMS_CHANNEL_EMAIL"]:
        if k in env:
            lines.append(f"{k}={env[k]}")
    path.write_text("\n".join(lines) + "\n")


def _read_global_rappid() -> dict:
    """Read ~/.brainstem/rappid.json (operator identity, minted at install)."""
    p = Path.home() / ".brainstem" / "rappid.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _derive_owner_repo(project_root: Path) -> tuple:
    """Try git remote first; fall back to operator-anchored synthetic coords."""
    try:
        out = subprocess.run(
            ["git", "-C", str(project_root), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=4
        )
        if out.returncode == 0:
            url = out.stdout.strip()
            m = re.search(r"github\.com[:/]+([^/]+)/([^/.\s]+)(?:\.git)?", url)
            if m:
                return m.group(1), m.group(2)
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None, None


def _parse_agent_meta(filepath: Path) -> tuple:
    fallback = filepath.stem.replace("_agent", "").replace("_", " ").title().replace(" ", "")
    try:
        src = filepath.read_text(errors="replace")
    except OSError:
        return fallback, ""
    n = _AGENT_NAME_RE.search(src)
    d = _AGENT_DESC_RE.search(src)
    return (
        n.group(1) if n else fallback,
        d.group(1) if d else "",
    )


def _link_canonical_twin(twin_hash: str, target_dir: Path, force: bool = True) -> dict:
    """Symlink ~/.rapp/twins/<hash>/ -> target_dir so the canonical Twin agent finds it."""
    TWINS_DIR.mkdir(parents=True, exist_ok=True)
    link = TWINS_DIR / twin_hash
    status = "linked"
    if link.is_symlink():
        current = os.readlink(link)
        if Path(current).resolve() == target_dir.resolve():
            return {"link": str(link), "target": str(target_dir), "status": "already-linked"}
        if not force:
            return {"link": str(link), "target": str(target_dir), "status": "exists-other", "current": current}
        link.unlink()
        status = "relinked"
    elif link.exists():
        return {"link": str(link), "target": str(target_dir), "status": "exists-real-dir", "warning": "canonical path is a real directory; left untouched to avoid data loss"}
    link.symlink_to(target_dir, target_is_directory=True)
    return {"link": str(link), "target": str(target_dir), "status": status}


def _build_tracker_export(project_root: Path, target_dir: Path, port: int, rappid: str, agents_dir: Path, copilot_ok: bool) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    twin_hash = _hash_from_rappid(rappid)

    custom_agents, agent_names = [], []
    if agents_dir.exists():
        for f in sorted(agents_dir.glob("*_agent.py")):
            if f.name == "basic_agent.py":
                continue
            name, desc = _parse_agent_meta(f)
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
                continue
            agent_names.append(name)
            custom_agents.append({
                "name": name,
                "description": desc or f"Project agent at {f.name}",
                "category": "brainstem",
                "status": "new",
            })

    project = {
        "id": twin_hash,
        "customerName": project_root.name,
        "type": "Project Twin (HatchProjectTwin)",
        "status": "active",
        "description": (
            f"Project-anchored brainstem twin. Twin lives at {target_dir}; "
            f"symlinked at ~/.rapp/twins/{twin_hash}/ so the global brainstem's "
            f"Twin agent can manage it. Copilot auth: "
            f"{'inherited' if copilot_ok else 'not configured'}."
        ),
        "stakeholders": "",
        "competingSolution": "",
        "contractDetails": "",
        "mvpUseCase": f"Resident twin at http://localhost:{port}",
        "mvpTimeline": "",
        "agents": agent_names,
        "createdDate": now,
        "updatedDate": now,
    }
    timeline = {
        "date": now,
        "title": f"Project twin forked: {project_root.name}",
        "description": f"Forked global kernel into {target_dir}; symlinked at ~/.rapp/twins/{twin_hash}/ on port {port}.",
    }
    return {
        "projects": [project],
        "agents": {"builtin": [], "custom": custom_agents},
        "timeline": [timeline],
        "exportDate": now,
    }


class HatchProjectTwinAgent(BasicAgent):
    def __init__(self):
        self.name = "HatchProjectTwin"
        self.metadata = {
            "name": self.name,
            "description": (
                "Fork the global RAPP brainstem kernel into a project-anchored twin. "
                "The twin's files live in <project_path>/.brainstem/src/rapp_brainstem; "
                "a symlink at ~/.rapp/twins/<hash>/ makes it discoverable by the global "
                "brainstem's built-in Twin agent (so the global can boot, list, and chat "
                "with project twins without parallel registries). Spec-compliant rappid.json, "
                "manifest.json (with port_hint), and HATCH_RECEIPT.json are written. Use when "
                "the user wants a project-resident brainstem the global can manage."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Absolute path to the project root. The twin lands at <project_path>/.brainstem/src/rapp_brainstem.",
                    },
                    "port": {"type": "integer", "description": "Optional port; auto-picked from 7073+ skipping ports already in any ~/.rapp/twins/*/manifest.json."},
                    "replace_env": {"type": "boolean", "description": "Regenerate .env even if it exists. Default false."},
                    "force_soul": {"type": "boolean", "description": "Overwrite project soul.md with global. Default false."},
                    "include_auth": {"type": "boolean", "description": "Copy .copilot_token + .copilot_session from global. Default true."},
                    "emit_tracker_export": {"type": "boolean", "description": "Write projectTrackerData JSON sidecar. Default true."},
                    "tracker_out": {"type": "string", "description": "Override path for tracker export JSON."},
                    "owner": {"type": "string", "description": "Override rappid owner segment. Default: derived from `git remote get-url origin` or operator's github handle."},
                    "repo": {"type": "string", "description": "Override rappid repo segment. Default: derived from git remote or project basename + '-brainstem'."},
                },
                "required": ["project_path"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        project_path = (kwargs.get("project_path") or "").strip()
        if not project_path:
            return json.dumps({"error": "project_path is required"})
        project_root = Path(project_path).expanduser().resolve()
        if not project_root.exists() or not project_root.is_dir():
            return json.dumps({"error": f"project_path not a directory: {project_root}"})

        global_dir = _global_brainstem_dir()
        target_dir = project_root / ".brainstem" / "src" / "rapp_brainstem"
        target_agents = target_dir / "agents"
        target_agents.mkdir(parents=True, exist_ok=True)

        # --- Kernel + helpers (canonical hatcher pattern: copy verbatim) ---
        copied, missing = [], []
        for fname in KERNEL_FILES:
            src = global_dir / fname
            if src.exists():
                shutil.copy2(src, target_dir / fname)
                copied.append(fname)
            else:
                missing.append(fname)
        for fname in AGENT_HELPERS:
            src = global_dir / "agents" / fname
            if src.exists():
                shutil.copy2(src, target_agents / fname)
                copied.append(f"agents/{fname}")

        # --- soul.md: preserve if exists, copy from global as starter ---
        preserved = []
        force_soul = bool(kwargs.get("force_soul", False))
        target_soul = target_dir / "soul.md"
        if target_soul.exists() and not force_soul:
            preserved.append("soul.md")
        elif (global_dir / "soul.md").exists():
            shutil.copy2(global_dir / "soul.md", target_soul)
            copied.append("soul.md")

        # --- Identity: derive coords + mint rappid ---
        global_rappid_doc = _read_global_rappid()
        parent_rappid = global_rappid_doc.get("rappid")
        operator_github = global_rappid_doc.get("github")

        owner = kwargs.get("owner") or None
        repo = kwargs.get("repo") or None
        owner_source = "param"
        if not owner or not repo:
            git_owner, git_repo = _derive_owner_repo(project_root)
            owner = owner or git_owner or operator_github or "local"
            repo = repo or git_repo or f"{_slug(project_root.name)}-brainstem"
            owner_source = "git-remote" if git_owner else ("operator-github" if operator_github else "fallback-local")

        # Reuse rappid if a project rappid.json already exists (idempotent re-fork).
        existing_rappid_path = target_dir / "rappid.json"
        rappid = None
        if existing_rappid_path.exists():
            try:
                existing = json.loads(existing_rappid_path.read_text())
                if existing.get("schema", "").startswith("rapp-rappid/"):
                    rappid = existing.get("rappid")
                    preserved.append("rappid.json (reused existing rappid)")
            except (json.JSONDecodeError, OSError):
                pass
        if not rappid:
            rappid = _mint_v2_rappid(kind="project", owner=owner, repo=repo)

        twin_hash = _hash_from_rappid(rappid)
        now = datetime.now(timezone.utc).isoformat()

        # --- Port: prefer existing manifest.port_hint (idempotency), else auto-pick ---
        existing_manifest_path = target_dir / "manifest.json"
        port = kwargs.get("port")
        if port is None and existing_manifest_path.exists():
            try:
                em = json.loads(existing_manifest_path.read_text())
                p = em.get("port_hint") or em.get("port")
                if isinstance(p, int):
                    port = p
            except (json.JSONDecodeError, OSError):
                pass
        if port is None:
            # Avoid the global brainstem's port too.
            global_env = _read_env(global_dir / ".env")
            global_port = None
            try:
                global_port = int(global_env.get("PORT", 7071))
            except (TypeError, ValueError):
                global_port = 7071
            port = _pick_port(DEFAULT_PORT_FLOOR, also_avoid={global_port})
        else:
            port = int(port)

        # --- rappid.json (matches twin_egg_hatcher's writer) ---
        rappid_doc = {
            "schema": "rapp-rappid/2.0",
            "rappid": rappid,
            "hash": twin_hash,
            "kind": "project",
            "namespace": f"@{owner}/{_slug(project_root.name)}",
            "host": "github.com",
            "owner": owner,
            "repo": repo,
            "name": _slug(project_root.name),
            "display_name": project_root.name,
            "parent_rappid": parent_rappid,
            "parent_repo": global_rappid_doc.get("anchor_repo") and f"https://github.com/{global_rappid_doc['anchor_repo']}",
            "born_at": now,
            "role": "project-twin",
            "description": f"Project-anchored brainstem twin for {project_root.name}. Forked from global kernel.",
            "_planted_by": f"@{operator_github}" if operator_github else None,
            "_planted_at_path": str(target_dir),
            "_owner_source": owner_source,
            "_hatched_by": "hatch_project_twin_agent.py",
            "_hatcher_version": HATCHER_VERSION,
        }
        existing_rappid_path.write_text(json.dumps(rappid_doc, indent=2) + "\n")
        copied.append("rappid.json")

        # --- manifest.json (port_hint is the canonical "where do I boot this twin" field) ---
        manifest_doc = {
            "schema": "rapp-twin-manifest/1.0",
            "rappid": rappid,
            "hash": twin_hash,
            "name": _slug(project_root.name),
            "kind": "project",
            "port_hint": port,
            "anchor_path": str(target_dir),
            "url": f"http://localhost:{port}",
            "updated_at": now,
        }
        existing_manifest_path.write_text(json.dumps(manifest_doc, indent=2) + "\n")
        copied.append("manifest.json")

        # --- .env: gap-fill, preserve user edits unless replace_env=True ---
        target_env = target_dir / ".env"
        global_env = _read_env(global_dir / ".env")
        replace_env = bool(kwargs.get("replace_env", False))
        if target_env.exists() and not replace_env:
            cur = _read_env(target_env)
            cur["PORT"] = str(port)
            cur.setdefault("SOUL_PATH", "./soul.md")
            cur.setdefault("AGENTS_PATH", "./agents")
            _write_env(target_env, cur)
            preserved.append(".env (port updated)")
        else:
            env = {"SOUL_PATH": "./soul.md", "AGENTS_PATH": "./agents", "PORT": str(port)}
            for k in ENV_KEYS_TO_INHERIT:
                if k in global_env:
                    env[k] = global_env[k]
            _write_env(target_env, env)
            copied.append(".env")

        # --- Copilot auth: inherit so the project twin chats immediately ---
        include_auth = bool(kwargs.get("include_auth", True))
        auth_copied = []
        if include_auth:
            for fname in AUTH_FILES:
                src = global_dir / fname
                dst = target_dir / fname
                if src.exists() and not dst.exists():
                    shutil.copy2(src, dst)
                    auth_copied.append(fname)
                elif dst.exists():
                    preserved.append(fname)

        # --- HATCH_RECEIPT.json (matches twin_egg_hatcher's shape) ---
        receipt = {
            "hatcher_version": HATCHER_VERSION,
            "rappid": rappid,
            "name": _slug(project_root.name),
            "kind": "project",
            "source": "hatch-project-twin-from-global",
            "hatched_at": now,
            "workspace": str(target_dir),
            "files": copied,
            "re_hatched": "rappid.json (reused existing rappid)" in preserved,
        }
        (target_dir / HATCH_RECEIPT_NAME).write_text(json.dumps(receipt, indent=2) + "\n")
        copied.append(HATCH_RECEIPT_NAME)

        # --- Symlink the canonical twin location → the project-anchored dir ---
        link_result = _link_canonical_twin(twin_hash, target_dir, force=True)

        # --- Tracker export sidecar (uses canonical rappid hash as id) ---
        tracker_export = None
        tracker_out_path = None
        if bool(kwargs.get("emit_tracker_export", True)):
            tracker_export = _build_tracker_export(
                project_root=project_root,
                target_dir=target_dir,
                port=port,
                rappid=rappid,
                agents_dir=target_agents,
                copilot_ok=bool(auth_copied) or any(f.startswith(".copilot") for f in preserved),
            )
            tracker_out_path = Path(kwargs.get("tracker_out") or (target_dir / "project_tracker_export.json"))
            tracker_out_path.parent.mkdir(parents=True, exist_ok=True)
            tracker_out_path.write_text(json.dumps(tracker_export, indent=2))

        return json.dumps({
            "ok": True,
            "rappid": rappid,
            "twin_hash": twin_hash,
            "parent_rappid": parent_rappid,
            "project_brainstem": str(target_dir),
            "canonical_twin_link": link_result,
            "port": port,
            "url": f"http://localhost:{port}",
            "copied": copied,
            "auth_copied": auth_copied,
            "preserved": preserved,
            "missing_in_global": missing,
            "owner": owner,
            "repo": repo,
            "owner_source": owner_source,
            "start_command": f"cd {target_dir} && ./start.sh",
            "tracker_export_path": str(tracker_out_path) if tracker_out_path else None,
            "tracker_export": tracker_export,
            "spec_compliance": {
                "rappid_schema": "rapp-rappid/2.0",
                "twin_workspace_discoverable_by_global_twin_agent": True,
                "filesystem_as_source_of_truth": True,
                "no_parallel_registry": True,
                "uses_canonical_twins_dir": str(TWINS_DIR),
            },
        }, indent=2)
