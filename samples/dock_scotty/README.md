# RAPP Dock / Scotty — main chat-operated rapplication template

> **Looking for the working Dock app?** This directory is a synthetic authoring
> fixture that deliberately does not run jobs. The real, installable
> application is [`apps/@kody-w/dock_scotty/`](../../apps/@kody-w/dock_scotty/README.md).

**Experimental · synthetic authoring sample · unlisted · not an installable
release.** This example is a complete, hash-locked manifest/layout contract;
its deliberately non-executing agent demonstrates the boundary without
shipping developer machines, credentials or private evidence.

> **Local application execution; Copilot cloud inference; tested on Apple
> Silicon with some amd64 guests under emulation.**

That sentence describes the **development reference profile** of Dock, not
a fresh installation of this public template, a minimum machine requirement,
or whole-bundle Intel Mac support. The source-only sample does not install
Docker, materialize images, start jobs or deploy Scotty. Do not copy its
singleton alone into a runtime and call that a Dock installation.

## What a rapplication is

A rapplication is an owned, versioned, chat-operated application, not merely
a single-file agent. It declares executable components, typed jobs, providers,
state, preserving lifecycle and portability. Scotty is its one visible bot,
discovered as a normal BasicAgent by unchanged current Grail. Chat is primary;
a separate UI is optional.

RAPP supplies the technical foundation. RAPP Work may use the application for
business workflows but is not a dependency. There is no second Brainstem,
Store server, model loop, notification service or application manager here.

## Five shipped development journeys

These are the implementation modes the template describes, **not synthetic
test passes**. Exact job input/output declarations are in
[`generated/job-contracts.json`](generated/job-contracts.json).

| Ask Scotty | Mode and result | Honest limitation |
|---|---|---|
| “Read this public page and summarize it with sources.” | `scrapling.scrape`: native HTTP/browser collection with a gateway-authored cited summary | Public web egress is needed; private destinations are refused. Collection may survive a summary-provider failure. |
| “Make a six-slide editable deck and PDF.” | `presenton.deck`: **gateway-authored, Presenton-exported** PPTX/PDF | This is not default native Presenton AI generation; external image providers are off. |
| “Create an SEO project for this site.” | `open-seo.project_create`: actual native project creation/reuse | DataForSEO paid metrics and unsupported traffic/competitor claims remain disabled. Asking about an existing result must not recreate the project. |
| “Build a knowledge base from these documents and answer this question.” | `dify.knowledge_build`: economy indexing/retrieval plus a gateway-grounded answer with citations; `dify.knowledge_answer` answers later questions | Not native Dify model-plugin execution. No paid embeddings. The build's original question belongs in the same build job. |
| “Make three captioned vertical clips from this spoken video.” | `openshorts.clips`: gateway AI selection and native rendering, retaining transcript/source ranges | Speech-containing local video, 45 seconds–10 minutes; 1–5 clips. Silent/vision features, publishing and paid Gemini are off. |

`intelligence.chat` is a tool-free diagnostic job, not a sixth user journey.
Inputs are data, never shell commands. Mutating work is requested explicitly;
follow-up questions inspect the earlier operation instead of replaying it.
Cancellation, failure and interruption must never be labeled successful work.

The reported development evaluation baseline was **12/14 exercised scenarios**.
Sequence grading and an unnecessary duplicate-safe SEO follow-up run were
remaining issues; the injection scenario was unrun in that baseline. Those
private scorecards are not distributed and do not qualify this sample.
Candidate-specific installed-package tests must produce new evidence.

## Contract and generated layout

[`manifest.json`](manifest.json) uses `rapp-application/2.0` with mandatory
`portable-agents/1`, `owned-files/1` and **`local-docker/1`**. Its
`rapp-local-docker/1` block references:

- [`components.lock.json`](components.lock.json): the implemented
  `rapp-dock-components/1` format, with six explicitly **blocked-build**
  components, null references/recipes and nonempty blockers—not fake release
  digests or fetchable image IDs. The application/service map makes
  Scrapling's browser dependency on Presenton explicit. A real export keeps
  its complete image/artifact/input-set lock unchanged; no parallel catalog
  or fabricated source revision is introduced.
- [`generated/host-profiles.json`](generated/host-profiles.json): Python 3.11+,
  exact Grail, Git, Docker/Compose/Buildx, local daemon, Apple Silicon/amd64 emulation
  and adopter-owned Copilot authentication. The observed 16-CPU / 31.3-GiB
  Docker VM is a reference, not a minimum or an enforced spend/resource cap.
  Public materialization requires Buildx/BuildKit; a legacy Docker builder is
  not an equivalent prerequisite. Cached image readiness is not proof of a
  public-only rebuild or fresh-device installation.
- [`generated/job-contracts.json`](generated/job-contracts.json): seven exact
  job IDs grouped into the five journeys plus diagnostics.
- [`generated/state-lifecycle.json`](generated/state-lifecycle.json): logical
  owned roots/volumes, sealed inputs, preserving policies and credential
  exclusion. These are declarations relative to application-owned custody,
  not developer-home paths.
- [`generated/synthetic-evidence.json`](generated/synthetic-evidence.json):
  explicit synthetic pending evidence; no real operation IDs or output data.
- `singleton/scotty_agent.py`, its descriptor, and a support directory named
  by the actual SHA-256 of its complete support inventory.

Every referenced declaration is itself in the manifest file lock and is
dereferenced/type-checked, not passed through as arbitrary JSON. Unknown
mandatory features, malformed references, missing files, tampering and loader
collisions must refuse before writes. Browsing/static validation needs neither
Docker nor credentials. Explicit installation/use has separate device checks.

`source/` is the authoring surface; do not patch generated `singleton/` files.
The template builder is deterministic and has no network/Docker behavior:

```bash
python3 -B samples/dock_scotty/tools/build_template.py --check
```

For edits that change the support revision, generate a **new clean candidate
directory** with `--output <project-relative-directory>/dock_scotty`; do not
overwrite an installed application or published immutable package. A real
distribution replaces template components with verified public locks, includes
the qualified Store delegate and entire runtime closure, and receives a new
manifest version and candidate evidence. The live runtime's bootstrap is not
edited by this authoring example.

To bind a **separately reviewed public distribution** to this Store contract,
use a new output directory:

```bash
python3 -B samples/dock_scotty/tools/assemble_candidate.py \
  --payload <public-distribution-directory> \
  --output <project-relative-directory>/dock_scotty \
  --publisher @your-handle
```

The assembler reads source and declarations, never imports supplied code or
runs Docker. It preserves the complete `rapp-dock-components/1` lock rather
than inventing missing archive sizes/digests. Static installer/closure checks
must pass before output writes. Derived OpenShorts Dockerfiles, nested public
dependency locks and their source pins remain mandatory. It emits **pending**
candidate evidence, not runtime qualification. Never pass a coordinator
directory, owner validation tree, receipt collection or installed application
as input.

Use `--version <new-semver>` for a subsequent outer application release.
The loader's literal internal metadata and bootstrap bytes stay stable
within `scotty-revision-loader/1`; support revisions and outer release
versions do not rewrite that bootstrap.

## Readiness is a vector

| Fact | This public template |
|---|---|
| Candidate | Experimental; not admitted, featured, installed or deployed |
| Runtime package verification | Pending; static synthetic-fixture checks are not runtime qualification |
| Fresh installation, by host profile | Pending |
| Every job/mode | Pending for this candidate |
| Current health | Unknown; no current observation timestamp |
| Restart | Pending for this candidate |
| Full recreation | **Dify pending; OpenShorts pending**; retain containers/layers |
| Provider prerequisites | Adopter Copilot auth required; other paid providers disabled |
| Acceptance-suite revision | Unassigned/pending for this candidate |

### Qualified reference-profile recreation (separate from this candidate)

The sanitized [reference-readiness vector](generated/reference-readiness.json)
records the owner's updated qualification on the tested Apple Silicon profile.
It contains no owner paths, identifiers, credentials or job artifacts.

| Reference fact | Qualification and scope |
|---|---|
| Dify full recreation | **Qualified**: all 15 roles read-only with explicit custody; down/recreate preserved datasets, documents, indexing and credentials; a fresh answer succeeded afterward |
| OpenShorts full recreation | **Qualified for drained completed state**: read-only renderer, authenticated ingress, completed clip hashes preserved, and a fresh render after recreation |
| OpenShorts in-flight renderer memory | **Not recoverable**; completed-state qualification does not imply in-flight resumption |
| Fresh-machine installation | **Pending** |
| OpenShorts public cold rebuild | **Blocked on npm/PyPI retrieval**, independent of reference-runtime recreation |
| Presenton native generation | **Opt-in**; the default remains gateway-authored/Presenton-exported |
| Dify native plugin | **Not installed**; the default remains gateway-grounded |

These reference facts are also carried as non-authoritative manifest
`metrics.reference_readiness`, not as a pass for this synthetic payload.
The candidate-specific readiness fields above remain pending until that
candidate is exercised. No old or private receipt is rewritten or relabeled.

Warm restart, full down/recreate, fresh install and preserving reinstall are
different tests. A fresh namespace on one Mac does not establish a second
device or Intel compatibility. An old observation is not current health.
Images built locally must record their **actual** image IDs; derived images
are not pretend registry artifacts or guaranteed byte-identical rebuilds.

Release gates: public input closure/materialization; isolated exact-Grail
loader installation; installed-candidate scrape → six-slide deck → capsule;
all five journeys; preserving detach/reinstall; and each application's
restart/recreation proof. A failed or missing gate stays explicit.

## Providers and cost

App AI uses the **official Copilot CLI 1.0.88 in Docker**, default model
`gpt-5-mini`, concurrency 2, cloud inference and no tools. The adopter supplies
their own account entitlement/authentication. No credentials are included,
copied from another user, printed, logged, exported or stored in the template.

Copilot consumes usage/credits under the adopter's plan. Usage is measured
when available, may be app-window-attributed rather than exact per-job
billing, and may be unknown. **Monetary cost: unknown (`null`). Hard spend
cap: none (`null`).** Process/time/byte/concurrency bounds are not a hard
monetary cap or guaranteed generation-token ceiling. All other paid providers
(including DataForSEO, OpenRouter, Gemini and external image providers) remain
disabled unless separately enabled by the owner in an appropriate qualified
application policy.

Local application execution does not mean offline inference or entirely local
data processing: requested AI inputs reach Copilot cloud inference. Public
scraping/materialization also need their declared egress.

## State, lifecycle and portability

Installation copies the complete verified source layout, checks existing
ownership/collisions and commits its receipt last. Recovery must distinguish
an interrupted source install from completed application work; it cannot
blindly replay jobs.

Start/use is bounded and local. Stop preserves state. Detach/uninstall drains
or stops owned work, removes only owned hash-matching source and **retains app
data, existing identities, credentials and unqualified writable layers**.
No volume deletion, daemon prune or broad cleanup. The tested reference
topologies now have the scoped recreation qualifications above; a different
or newly installed candidate stays stop/retain until its own topology is
qualified. OpenShorts' in-flight renderer memory is not made recoverable
merely because completed clip files survive.

Successful and failed jobs produce canonical **RAPP/1** provenance:
`memory.tool-call` frames in **session receipt eggs**. A **rapplication
capsule** carries selected outputs and producing source. It is **not** a full
database export, image archive, credential store or complete state backup.
Verification is **unsigned, structural-only**, not authenticated trust.
Inputs/outputs use actual hash links; missing lineage remains unknown.
Never redact a hash-bound receipt/capsule while retaining its old identity.

Store installation cartridges (`rapp-egg/2.0`) are distinct from canonical
RAPP/1 eggs. None of the owner's receipts, capsules, conversations or outputs
are shipped here. The sample contains only synthetic declarations and source.

## Review, not publication by implication

Follow [SPEC §15](../../SPEC.md#15-complete-chat-operated-applications) and
[Proposal 0007](../../docs/proposals/0007-chat-operated-rapplications.md).
All new listings still use the `[RAPP]` receiver and maintainer approval.
Complete applications use commit-pinned public federation. Source-ZIP
promotion refuses until a preserving complete-layout path is qualified;
the verified installation cartridge is a separate artifact.
This template and a draft PR are neither release authorization nor an
installable badge. Existing native macOS downloads, simple applications,
the public catalog and independent Zoo data remain unchanged.
