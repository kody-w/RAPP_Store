# Proposal 0003 — Kernel Is What Chat Requires

| | |
|---|---|
| **Status** | Draft |
| **Sponsor** | @kody-w |
| **Drafted** | 2026-04-27 |
| **Touches** | `kody-w/RAPP/CONSTITUTION.md` (proposed Article XXXII). No code changes. |
| **Complies with** | Article XXVIII (proposals before amendments). |

## 1. Context

The brainstem repeatedly faces the same architectural question: should this code live inline in `brainstem.py`, or extract into a `*_service.py` under `utils/services/`?

We already had it wrong once: I proposed extracting auth, models, and voice into services because they "looked self-contained." The user pointed out this was bad framing — those are necessary for `/chat` to function, while the binder isn't. The rule is sharper than "self-contained":

> **A brainstem without a binder still serves chat. A brainstem without auth, models, or voice does not.**

That's the kernel-vs-service line, and it deserves a constitutional capture so the next time someone has the "should this be a service?" debate, they have a one-line test instead of a vibe.

## 2. The rule

Add **Article XXXII — Kernel Is What Chat Requires** to `kody-w/RAPP/CONSTITUTION.md`. The article states:

- A capability is **kernel** if removing it breaks `/chat`. Examples: auth (Copilot token), models (active-model selection), voice (per-channel reply config), agent discovery, sense composition, soul loading, the tool-call loop.
- A capability is a **service** if removing it leaves `/chat` working but disables some optional capability. Each service stands alone — services don't depend on each other. Examples: the binder (admin UI for browsing / installing rapplications — a brainstem can run any rapp without it once the rapp's files are in place), neighborhood (peer-brainstem comms), every rapplication's own `*_service.py`.
- The litmus test: *"Can the brainstem still answer a chat turn if I delete this?"* Yes → service. No → kernel.

The chat experience by itself — soul + installed `*_agent.py` + senses + tool-call loop — is the brainstem's full default. Services are admin and extension on top.

This sits comfortably alongside the existing articles:

- **Article I (the brainstem stays light)** — XXXII is the operational definition of "light."
- **Article XVI (the engine's surface vs. the workspace)** — XVI is about *where files live*; XXXII is about *what code must run*.
- **Article III (single file agents)** — XXXII covers what's NOT an agent (kernel and services).

## 3. Implementation

A single doc-only PR appending Article XXXII to `kody-w/RAPP/CONSTITUTION.md`. No URL changes, no script changes, no test changes. Companion PR to this proposal in the constitution repo.

## 4. Rollback

`git revert` of the constitutional amendment. The article is purely additive.

## 5. References

- Constitution [Article I](https://github.com/kody-w/RAPP/blob/main/CONSTITUTION.md#article-i--the-brainstem-stays-light) — "the brainstem stays light."
- Constitution [Article XVI](https://github.com/kody-w/RAPP/blob/main/CONSTITUTION.md#article-xvi--the-root-is-the-engines-public-surface-the-brainstems-workspace-is-separate) — engine surface vs. workspace.
- Constitution [Article XXVIII](https://github.com/kody-w/RAPP/blob/main/CONSTITUTION.md#article-xxviii--material-changes-are-proposed-before-theyre-applied) — this proposal complies with the proposals-first rule.
