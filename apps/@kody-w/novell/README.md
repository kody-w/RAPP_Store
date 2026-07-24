# Novell

**The hater you run before the real one shows up.**

Novell is an adversarial pre-review rapplication. You hand him an artifact — a
pitch, a README, an architecture claim, a demo script — and he returns the
objections a hostile-but-competent skeptic would raise, ranked by severity, each
paired with the specific evidence that kills it.

The point is not the roast. The point is the **kill list**: every objection ships
with what would close it, so a draft can be repaired before anyone with an
opinion and a calendar invite ever reads it.

```
NOVELL SCORE 100/100 — He hasn't stopped talking. Nothing here is defended.
12 of 12 lenses landed.

[15] The So-What
     "Okay. What number moved?"
     He's really asking: Which business metric changed, by how much, measured how?
     Kill it with: A before/after with a unit and a timeframe. One real number
     outranks a page of adjectives.
```

---

## He is not a person

Novell is an **archetype**, not a portrait.

He is assembled from twelve reusable *stances* — the objection patterns that
recur in every enterprise-AI review regardless of who is in the chair. He
ingests no transcripts. He models no individual. He stores no names.

This is enforced in code, not promised in prose: `_scrub()` strips emails,
`@handles`, phone numbers, URLs and runs of capitalised words out of every
custom lens **before it is persisted**, so a user cannot accidentally turn their
own copy of Novell into a caricature of a colleague. `action="policy"` returns
the guarantee; the scrubber is exercised in `tests/`.

He attacks claims. He never attacks authors. Every barb in the catalogue is
aimed at a sentence in the artifact.

> Named for Novell, Inc. — the company that owned the network and still lost the
> shift. The archetype's whole personality is *"I have seen this before and I was
> right last time."* Sometimes he still is. That is exactly why you run him.

---

## The twelve lenses

| Lens | The barb | What it's really asking |
|---|---|---|
| **The GA Gate** | "Is it GA? I can't put a preview on a customer's roadmap." | Supported product, or prototype in product clothes? |
| **Body Parts** | "You stitched five things together and called it a platform. I count five things." | One product, or an integration diagram in a trenchcoat? |
| **The Meter** | "Who's the billed party? Show me the meter or it's shelfware." | What consumes budget, and whose? |
| **The Roadmap Eraser** | "The platform ships this in two quarters. You built a wrapper with an expiry date." | What survives absorption? |
| **Laptop Physics** | "Beautiful on your laptop. Now do 5,000 seats." | What breaks between 1 and n? |
| **The 2AM Question** | "It breaks at 2am Sunday. Who gets paged? Not me." | Pager, SLA, rollback. |
| **The Auditor** | "Where does the data sit, who can read it, what does the audit log say?" | Residency, DLP, retention. |
| **Demo Gravity** | "Great demo. Name one production user." | Has anyone run this in anger? |
| **Bus Factor One** | "One maintainer, one proprietary format. What happens when you're on vacation?" | Can someone else operate, fork, exit? |
| **The So-What** | "Okay. What number moved?" | Which metric changed, measured how? |
| **Novelty Tax** | "You invented five nouns. Now I have to teach my team five nouns." | Does the vocabulary earn its cost? |
| **Attack Surface** | "You gave an agent hands. What's the blast radius when it's wrong?" | Capability boundary, credential scope, human in the loop. |

Add your own with `add_lens` — they are scrubbed, weighted, and persisted to the
rapplication workspace. `export` / `import_json` move your lens set between
machines.

---

## Local-first

The scoring engine is pure Python. No network, no API key, no LLM. It works on a
plane, and it is **deterministic** — the same artifact always yields the same
score, which is what makes it safe to gate a pipeline on.

If the host brainstem exposes `utils.llm.call_llm`, `roast` additionally renders
the landed objections as prose in Novell's voice. That layer is decoration; the
findings and the verdict never depend on it.

---

## Actions

| Action | Does |
|---|---|
| `roast` | Full review — findings, score, and (if an LLM is present) prose |
| `gate` | CI shape: `verdict` PASS/FAIL + `exit_code` 0/1 against a threshold |
| `score` | Just the number |
| `lenses` | The catalogue |
| `defend` | Test whether your evidence actually closes a given objection |
| `add_lens` | Add your own stance (scrubbed before saving) |
| `export` / `import_json` | Move your custom lenses between machines |
| `policy` | The zero-PII guarantee, machine-readable |

### Pipeline gate

```python
novell(action="gate", artifact=open("PITCH.md").read(), threshold=25)
# -> {"verdict": "FAIL", "exit_code": 1, "novell_score": 68,
#     "top_blockers": [{"name": "The So-What", "fix": "A before/after with a unit..."}]}
```

Wire the `exit_code` into CI and a weak draft fails before review, not during it.

### Checking your defence

```python
novell(action="defend", objection="who_pays",
       evidence="It rides the existing GitHub Copilot seat; it consumes Copilot usage.")
# -> evidence_holds: true — "Put this sentence in the artifact itself.
#                            Novell only reads what's written down."
```

That last clause is the whole discipline. Evidence that lives in your head scores
zero, because it also scores zero in the actual meeting.

---

## Install

Drop `singleton/novell_agent.py` into your brainstem's `agents/` directory. It
auto-discovers. Pair with `ui/index.html` for the bundled rapplication — the UI
also runs standalone in a browser (it mirrors the heuristic client-side for
preview; the agent remains authoritative).

## Calibration

Verified on two fixtures: an adjective-heavy pitch with no evidence scores
**100/100, 12 of 12 lenses landing**; the same claim rewritten with a stated
non-GA status, a named entitlement, a production duration, a measured
before/after, an enumerated capability boundary and a published spec scores
**8/100, 1 lens landing**. The gap between those two documents is the product.

Licence: BSD-style. Publisher: `@kody-w`.
