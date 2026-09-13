import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_workspace_bootstrap_is_additive_and_immutably_pinned():
    config = json.loads((ROOT / ".rapp/bootstrap.json").read_bytes())
    pin = config["operator"]
    assert re.fullmatch(r"[a-f0-9]{40}", pin["source_commit"])
    assert re.fullmatch(r"[a-f0-9]{64}", pin["sha256"])
    assert pin["url"] == f"https://raw.githubusercontent.com/kody-w/rapp-tools/{pin['source_commit']}/rapp_workspace.py"
    assert config["local_only"] is True
    state = json.loads((ROOT / ".rapp/bootstrap-managed.json").read_bytes())
    for relative, expected in state["files"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
    assert state["root_skill"] == "SKILL.md"
    root_skill = (ROOT / "SKILL.md").read_text()
    assert "singleton contract" in root_skill
    assert root_skill.count("<!-- rapp-workspace-bootstrap:begin -->") == 1


def test_skills_are_linked_without_mixing_application_catalog_entries():
    assert "https://kody-w.github.io/RAR/skills.html" in (ROOT / "index.html").read_text()
    catalog = json.loads((ROOT / "index.json").read_bytes())
    assert all(entry.get("id") != "rapp_workspace_refresh" for entry in catalog["rapplications"])
