# Proposal 0007 — Chat-operated applications and `local-docker/1`

Status: **proposed; experimental implementation for review**, not a release,
catalog admission, featured designation, or platform-constitution amendment.

## Problem

A single agent is a useful entrypoint, not a sufficient description of an
application. Chat-operated applications also need executable components, typed
jobs, provider disclosure, owned state, preserving lifecycle, and portable
results. Copying only their entrypoint can leave an apparently installed but
broken or unsafe application.

## Decision proposed

Extend the existing application model with `rapp-application/2.0`, an explicit
complete file lock and current-Grail runtime pin. The mandatory feature
`local-docker/1` selects the closed `rapp-local-docker/1` declaration. It is not
a second Store runtime or model loop. Unchanged Grail discovers the normal
BasicAgent entrypoint; the application owns its bounded local Docker adapter.
RAPP Work remains an optional business-workflow consumer, not a dependency.

The extension retains identity, publisher, version, capabilities, dependencies,
providers, state, lifecycle, and provenance. Locked references declare:

- component sources/images and the complete revision-loader layout;
- host/guest profiles and measured, not invented, resource requirements;
- typed inputs, outputs, modes, providers, and limitations for jobs;
- owned roots/volumes, sealed inputs, preserving stop/detach/reinstall, and
  credential/export exclusions;
- tool-free Copilot CLI cloud inference and truthful usage/cost limitations;
- canonical RAPP/1 receipts/capsules and their structural-only verification;
- independent readiness facts, rather than a single “works” badge.

Python admission, generated installer, browser preflight and discovery must
reject unknown mandatory features. All referenced files are locked, read and
type-checked before installation writes. Device checks run only on explicit
installation/use; browsing and validating do not call Docker or read custody.
An unsupported or incomplete rich app never falls back to a bare singleton,
service, historical egg, or browser execution.

## Compatibility and governance

Existing `rapp-application/1.0` simple applications keep their current contract
and bytes. Existing native macOS releases retain Proposal 0006 semantics;
independent Zoo v2 data and admission remain unchanged. The root catalog stays
`rapp-store/1.0`. No bulk migration, regenerated stale catalog, historical egg
rewrite, release download invention, or automatic featured placement occurs.

The narrow content-layer amendments accompanying this proposal distinguish a
portable entrypoint from a complete versioned application. They do not claim
maintainer ratification or external RAPP/1/Apple acceptance. New listings still
enter through the `[RAPP]` receiver and maintainer approval. A draft PR alone
admits nothing.

For this extension, admission uses commit-pinned public federation. Source-ZIP
promotion remains refused for version 2 until a publisher-namespaced,
preserving complete-layout transaction is qualified; old bundle promotion
must not silently reduce or overwrite the new contract. Version-1 submissions
are unchanged, and verified installation cartridges remain separate.

## Main authoring example: RAPP Dock / Scotty

The unlisted `samples/dock_scotty/` template demonstrates five journeys:
Scrapling collection, gateway-authored/Presenton-exported editable decks,
OpenSEO projects with paid metrics disabled, Dify economy knowledge retrieval
with gateway-grounded citations, and AI-selected/native-rendered OpenShorts.
One visible bot, Scotty, operates them through Brainstem chat.

Required first-card disclosure:

> Local application execution; Copilot cloud inference; tested on Apple
> Silicon with some amd64 guests under emulation.

The profile describes development observations, not a minimum specification or
a successful fresh installation of the published candidate. The template is
synthetic authoring material, not a runnable release or copied owner evidence.
Its candidate is experimental, fresh installation remains pending, and Dify/
OpenShorts recreation remains pending until candidate-specific proof exists.
Separately, the tested Apple Silicon reference has qualified Dify full
recreation and OpenShorts drained-completed-state recreation. The latter does
not recover in-flight renderer memory. Sanitized reference summaries are
labeled as such and cannot confer those results on the teaching fixture.
Fresh-machine installation remains pending, OpenShorts public cold rebuild
is blocked on npm/PyPI retrieval, Presenton native generation remains opt-in
and the Dify native plugin is not installed.

Copilot uses the adopter's own entitlement/usage. Other paid providers are
disabled. Process/time/byte limits are not a monetary spend cap. Usage can be
app-window-attributed or unavailable; unknown cost stays unknown.

Receipts are RAPP/1 `memory.tool-call` frames in session eggs. Rapplication
capsules contain selected outputs plus producing source, not a full database,
Docker image archive, credential store, or application-state backup. Store
installation cartridges and canonical RAPP/1 eggs remain distinct formats.

## Acceptance

1. All existing simple/native/Zoo Python and browser tests still pass.
2. Shared static contract tests cover feature refusal, complete locked
   references, type/size/path/digest failures, and Python/JavaScript agreement.
3. Installer tests prove the full bootstrap/descriptor/hash-scoped support
   layout against an isolated exact-Grail fixture, with receipt-last recovery
   and preserving detach/reinstall; never the owner's live runtime.
4. Discovery and UI preserve required features and honest readiness; no rich
   app gets a singleton-only, service-only, or browser-run shortcut.
5. Synthetic public template data contains no owner paths, identities,
   credentials, outputs, receipts, capsules, or real operation identifiers.
6. Fresh public materialization, installed-candidate journeys, preserving
   reinstall, and per-app recreation are separate release gates. Pending
   evidence cannot become an installability claim.

## Non-goals

No Store server, second Brainstem, global queue, credential custody, native-AI
parity campaign, paid-provider enablement, production Docker mutation,
notification transport, destructive uninstall, auto-merge, or catalog bypass.
