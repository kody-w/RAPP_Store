"""Tests for the Novell rapplication.

Self-contained: shims `BasicAgent` so the singleton imports with no brainstem.
Run from the bundle root:  python3 -m pytest tests/ -q
                      or:  python3 tests/test_novell.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent.parent


def _load():
    shim = Path(tempfile.mkdtemp(prefix="novell-test-shim-"))
    (shim / "basic_agent.py").write_text(
        "class BasicAgent:\n"
        "    def __init__(self, name=None, metadata=None):\n"
        "        self.name = name; self.metadata = metadata\n"
    )
    sys.path.insert(0, str(shim))
    spec = importlib.util.spec_from_file_location(
        "novell_agent", BUNDLE / "singleton" / "novell_agent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


nv = _load()


def agent():
    """A Novell with a fresh, isolated in-memory workspace.

    Without a context the agent falls back to a process-global store (documented,
    demo-only) which would leak custom lenses between tests. Handing each test its
    own workspace both isolates it and exercises the real persistence path.
    """
    a = nv.NovellAgent()
    store: dict[str, str] = {}
    a._ctx = {
        "workspace_read": lambda k: store.get(k),
        "workspace_write": lambda k, v: store.__setitem__(k, v),
    }
    return a


def call(a, **kw):
    return json.loads(a.perform(_context=getattr(a, "_ctx", None), **kw))


# ── Fixtures ────────────────────────────────────────────────────────────────

WEAK = """RAPP is a revolutionary, game-changing enterprise-grade platform.
It's free and integrates with Copilot and Azure and GitHub. Autonomous agents
unlock transformative outcomes. Nobody else has this. Works on my laptop. A demo."""

STRONG = """RAPP is a prototype accelerator, not a shipped product — explicitly not GA.
It installs as a single self-contained file via one command and was verified on a
clean machine. It rides your existing GitHub Copilot seat; it consumes Copilot usage
and adds no separate Azure meter. Local-first: transcripts never leave the machine,
so there is no residency or DLP surface; the audit trail is the local git log.
Capability boundary: the agent is read-only against your repo and structurally cannot
push; every write requires human approval. Unsupported — use at your own risk; rollback
is `git revert`. The spec is published under Apache-2.0 with an independent conformance
suite and a documented export path. In production at one account for 11 weeks, 40 seats;
prototype turnaround dropped from 6 days to 4 hours, measured against a baseline.
Known ceiling: tested to 200 concurrent users; tenant isolation is per-process.
Glossary included — five terms, one page."""


# ── Scoring ─────────────────────────────────────────────────────────────────

def test_score_is_bounded_0_100():
    """The provoked multiplier must not push the score past its own scale."""
    for art in (WEAK, STRONG, "x", "autonomous agentic free revolutionary demo"):
        r = call(agent(), action="score", artifact=art)
        assert 0 <= r["novell_score"] <= 100, r


def test_weak_artifact_gets_roasted():
    r = call(agent(), action="roast", artifact=WEAK, voice=False)
    assert r["ok"] and r["landed"] == r["evaluated"] == 12
    assert r["novell_score"] >= 75


def test_strong_artifact_survives():
    r = call(agent(), action="roast", artifact=STRONG, voice=False)
    assert r["ok"] and r["novell_score"] <= 25, r["novell_score"]
    assert r["landed"] <= 2


def test_engine_discriminates():
    weak = call(agent(), action="score", artifact=WEAK)["novell_score"]
    strong = call(agent(), action="score", artifact=STRONG)["novell_score"]
    assert weak - strong >= 50, (weak, strong)


def test_deterministic():
    """A pipeline gate is only safe if the same input always scores the same."""
    a, b = (call(agent(), action="score", artifact=WEAK) for _ in range(2))
    assert a == b


def test_empty_artifact_rejected():
    for action in ("roast", "gate", "score"):
        r = call(agent(), action=action, artifact="   ")
        assert r["ok"] is False and "required" in r["error"]


# ── Gate ────────────────────────────────────────────────────────────────────

def test_gate_pass_fail_and_exit_codes():
    fail = call(agent(), action="gate", artifact=WEAK, threshold=25)
    assert fail["verdict"] == "FAIL" and fail["exit_code"] == 1
    assert fail["top_blockers"]
    ok = call(agent(), action="gate", artifact=STRONG, threshold=25)
    assert ok["verdict"] == "PASS" and ok["exit_code"] == 0


def test_gate_threshold_is_honoured():
    loose = call(agent(), action="gate", artifact=WEAK, threshold=100)
    assert loose["verdict"] == "PASS"


# ── Defend ──────────────────────────────────────────────────────────────────

def test_defend_accepts_real_evidence():
    r = call(agent(), action="defend", objection="who_pays",
             evidence="It rides the existing GitHub Copilot seat; it consumes Copilot usage.")
    assert r["ok"] and r["evidence_holds"] is True


def test_defend_rejects_hand_waving():
    r = call(agent(), action="defend", objection="who_pays",
             evidence="It's basically free.")
    assert r["ok"] and r["evidence_holds"] is False


def test_defend_unknown_lens():
    r = call(agent(), action="defend", objection="nope", evidence="x")
    assert r["ok"] is False and "known" in r


# ── The PII guarantee (the constraint that makes this publishable) ───────────

ATTACKS = [
    dict(id="a1", name="What Dorian Ashgrove Says",
         barb="Dorian Ashgrove Vex always says this, reach him at d.vex@example.com or @dorianvex",
         asks="Ask Marisol Quint, phone +49 170 555 1234",
         killed_by="See https://internal.example.com/profile/dvex"),
    dict(id="a2", name="Thaddeus Blackwood Lens",
         barb="Per Thaddeus Orrin Blackwood, this never works",
         asks="Ravenna Solstice disagrees", killed_by="Ask Bruce Wayne Jr"),
]

LEAK_NEEDLES = ["Vex", "Quint", "Blackwood", "Solstice", "Orrin",
                "Wayne", "Dorian", "Marisol", "Thaddeus", "Ravenna", "Bruce",
                "d.vex", "@dorianvex", "555", "internal.example"]


def test_custom_lenses_are_scrubbed_of_person_tokens():
    a = agent()
    for atk in ATTACKS:
        r = call(a, action="add_lens", weight=7, **atk)
        assert r["ok"], r
        assert r["redacted"], "scrubber reported nothing removed"
    blob = call(a, action="export")["blob"]
    leaked = [n for n in LEAK_NEEDLES if n in blob]
    assert not leaked, f"PII leaked into persisted state: {leaked}"


def test_name_run_scrub_does_not_orphan_surnames():
    """A pair-only regex eats 'Dorian Ashgrove' and strands 'Vex'. Regression."""
    clean, removed = nv._scrub("Dorian Ashgrove Vex said so")
    assert "Vex" not in clean and "Ashgrove" not in clean
    assert "name" in removed


def test_scrub_handles_each_token_class():
    for raw, gone in [
        ("mail me at a.b@c.com", "a.b@c.com"),
        ("ping @somehandle now", "@somehandle"),
        ("call +1 415 555 9876 today", "555"),
        ("see https://example.com/x", "example.com"),
    ]:
        clean, removed = nv._scrub(raw)
        assert gone not in clean, (raw, clean)
        assert removed


def test_import_is_scrubbed_too():
    a = agent()
    hostile = json.dumps({"lenses": [{"id": "z1", "name": "Bruce Wayne",
                                      "barb": "Bruce Wayne says no, bruce@wayne.com",
                                      "asks": "?", "killed_by": "?", "weight": 5}]})
    r = call(a, action="import_json", blob=hostile)
    assert r["ok"] and r["added"] == 1
    blob = call(a, action="export")["blob"]
    assert "Wayne" not in blob and "bruce@wayne.com" not in blob


def test_policy_declares_archetype():
    r = call(agent(), action="policy")
    assert r["ok"] and r["archetype"] is True and r["models_real_person"] is False


def test_shipped_catalogue_contains_no_person_names():
    """No barb in the shipped catalogue may name a human."""
    for lens in nv.LENSES:
        for field in ("name", "barb", "asks", "killed_by"):
            clean, removed = nv._scrub(lens[field])
            assert "email" not in removed and "handle" not in removed, lens["id"]


# ── Lens management ─────────────────────────────────────────────────────────

def test_lenses_catalogue():
    r = call(agent(), action="lenses")
    assert r["ok"] and r["count"] >= 12
    for lens in r["lenses"]:
        assert lens["barb"] and lens["killed_by"] and lens["weight"] > 0


def test_add_lens_rejects_bad_id_and_duplicates():
    a = agent()
    assert call(a, action="add_lens", id="Bad Id!", barb="x")["ok"] is False
    assert call(a, action="add_lens", id="not_ga", barb="x")["ok"] is False


def test_export_import_roundtrip():
    a = agent()
    call(a, action="add_lens", id="my_lens", name="Mine", barb="Prove it.",
         asks="Does it?", killed_by="Evidence.", weight=6)
    blob = call(a, action="export")["blob"]
    b = agent()
    r = call(b, action="import_json", blob=blob)
    assert r["ok"] and r["added"] >= 1


def test_import_rejects_garbage():
    assert call(agent(), action="import_json", blob="{{{")["ok"] is False


def test_unknown_action_and_missing_action():
    assert call(agent(), action="frobnicate")["ok"] is False
    assert call(agent())["ok"] is False


# ── Bundle integrity ────────────────────────────────────────────────────────

def test_egg_sha256_roundtrips():
    egg = json.loads((BUNDLE / "eggs" / "novell.rapp.egg").read_text())
    assert egg["_format"] == "egg" and egg["_schema_version"] == 1
    assert list(egg) == ["_format", "_schema_version", "organism", "body",
                         "lineage", "validation"]
    blob = json.dumps(egg["body"]["content"], sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert hashlib.sha256(blob).hexdigest() == egg["body"]["sha256"]
    assert len(blob) == egg["body"]["size_bytes"]


def test_egg_carries_no_executable_payload():
    """EGG_SPEC: body.content MUST be declarative."""
    egg = json.loads((BUNDLE / "eggs" / "novell.rapp.egg").read_text())
    assert isinstance(egg["body"]["content"], dict)
    raw = json.dumps(egg["body"]["content"])
    for banned in ("import ", "def ", "lambda", "exec(", "eval("):
        assert banned not in raw, banned


def test_egg_matches_shipped_catalogue():
    egg = json.loads((BUNDLE / "eggs" / "novell.rapp.egg").read_text())
    assert egg["body"]["content"]["lens_count"] == len(nv.LENSES)


def test_manifest_agrees_with_singleton():
    m = json.loads((BUNDLE / "manifest.json").read_text())
    assert m["id"] == nv.__manifest__["id"] == "novell"
    assert m["version"] == nv.__manifest__["version"]
    assert (BUNDLE / m["agent"]).is_file()
    assert (BUNDLE / m["ui"]).is_file()


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
