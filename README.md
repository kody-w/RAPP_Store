# rapp_store

**[📦 Browse the store](https://kody-w.github.io/RAPP_Store/)** · **[🦎 Pokédex API](#pokédex-api)** · **[📋 SPEC](./SPEC.md)** · **[🔒 Gated rapps (§11)](./SPEC.md#11-gated-rapplications-access-private)** · **[🔌 RAPP Agent Registry](https://github.com/kody-w/RAR)** · **[⚙️ RAPP engine](https://github.com/kody-w/RAPP)**

Public catalog of RAPP **rapplications** — chat-operated applications, from
simple agent/UI integrations to explicitly packaged local application stacks.
Native macOS release downloads remain an independent optional distribution.
Existing integrations load into a brainstem; native applications install separately. Browse the
[store](https://kody-w.github.io/RAPP_Store/) or [Pokédex API](#pokédex-api).

## RAPP Dock / Scotty

[**RAPP Dock / Scotty**](./apps/@kody-w/dock_scotty/README.md) is the real,
installable complete application: Scotty runs Scrapling, Presenton, OpenSEO,
Dify and OpenShorts in local Docker from chat or its UI. Installed five-job
acceptance passed on its previous build, and this build was installed fresh
from the Store files and re-ran a scrape and a deck.

To author your own complete application, start from the
[authoring template](./samples/dock_scotty/README.md):
one visible bot operates five application journeys through Brainstem chat,
with declared components, typed jobs, providers, owned state, preserving
lifecycle and portable results. An agent is the entrypoint, not the whole app.
RAPP is the technical platform; RAPP Work can consume it but is not required.

> **Local application execution; Copilot cloud inference; tested on Apple
> Silicon with some amd64 guests under emulation.**

That is the development reference profile, not proof of a fresh installation
of this public candidate or a minimum machine specification. The **unlisted,
experimental authoring sample uses synthetic fixtures**; it is not a runnable
release, catalog listing, featured badge, or preinstalled app. Fresh install
and candidate-specific execution remain pending.

**Reference-profile recreation is qualified:** Dify's full 15-role,
read-only/custody-bound down/recreate preserved data and credentials and
produced a fresh answer. OpenShorts is qualified for **drained completed
state**, with authenticated ingress, a read-only renderer, preserved clip
hashes and a fresh render; in-flight renderer memory is not recoverable.
These sanitized reference facts do not certify the synthetic template or a
new machine. Fresh-machine install remains pending; OpenShorts public cold
rebuild is blocked on npm/PyPI retrieval. Presenton native generation remains
opt-in and Dify's native plugin is not installed.

| Journey | Shipped development mode |
|---|---|
| Scrapling | Native collection with cited gateway summaries |
| Presenton | **Gateway-authored, Presenton-exported** editable PPTX and PDF |
| OpenSEO | Actual native projects; paid metrics disabled |
| Dify | Economy indexing/retrieval; gateway-grounded cited answers, not the native provider plugin |
| OpenShorts | AI-selected clips; native captioned vertical-video rendering |

The adopter supplies their own Copilot entitlement and authentication.
Copilot consumes usage/credits; other paid providers remain disabled. Unknown
cost stays unknown, and bounded processes are **not** a hard monetary spend
cap. Canonical RAPP/1 receipts and selected-output/source capsules are not full
state backups; verification is unsigned and structural-only.

See [Proposal 0007](./docs/proposals/0007-chat-operated-rapplications.md),
[SPEC §15](./SPEC.md#15-complete-chat-operated-applications), and the
[application](./schemas/application.schema.json) /
[local Docker](./schemas/local-docker.schema.json) contracts. The extension
requires `local-docker/1`; unsupported clients must refuse instead of
installing a bare singleton. Existing simple/native/Zoo listings and the
root catalog remain unchanged. Submission still requires `[RAPP]` review.
Complete applications submit through commit-pinned public federation.
Source-ZIP promotion is refused until its preserving layout is qualified;
verified installation cartridges are a different artifact, not a fallback.

> Legacy local producer outputs may include a singleton `.py` and portable
> `.egg` cartridge ([brainstem-egg/2.2-rapplication schema](https://github.com/kody-w/RAPP/blob/main/rapp_brainstem/utils/bond.py)).
> Federation does not imply that an egg, hatcher, lineage or protocol
> identity exists. Only explicitly published artifacts are offered.

> **Looking for bare agents?** A reusable `*_agent.py` without an application
> contract belongs in **[kody-w/RAR](https://github.com/kody-w/RAR)**. Existing
> simple applications retain their UI contract; complete chat-operated apps
> follow §15 and may use chat without a separate UI.

This repo was extracted from [`kody-w/RAPP`](https://github.com/kody-w/RAPP) on 2026-04-26 as the content layer of the platform. The engine (Tier 1 brainstem, Tier 2 swarm, Tier 3 worker) lives in `kody-w/RAPP`. Trust metadata (signing, identity, provenance) lives in the RAR registry. This repo is just **content** — rapplications you can fetch and run.

## Native macOS distribution (optional)

The backward-compatible `desktop: rapp-desktop/1.0` extension describes
real native releases in their **existing source repositories**. It requires
a minimum OS, stable bundle ID, full native-build commit, versioned tag,
architecture-specific DMG or ZIP URLs/exact bytes/SHA256, bound public signing and
notarization reports, and prerequisites/privacy/setup disclosures.

The existing Fable5 IDs remain **`rapp_crispy`, `rapp_rewind`, `rapp_shot`,
`rapp_voice`**. RAPP Tools is infrastructure, not another listing.
This plumbing change does not itself publish releases or alter their live
catalog entries.

Native downloads are GitHub Release assets, never mirrored/inline store
binaries. The Python singleton is secondary integration; dropping it into
`agents/` does **not** install the native app. The receiver checks actual
release/evidence byte pins and public tag/build references. Publisher
reports are not independent Apple authentication or RAPP/1 acceptance;
reviewers and macOS/Gatekeeper must verify the native application.

For ZIP distribution, Finder unzips the archive and the user drags the
enclosed application to Applications. Evidence describes that app's
Developer ID/hardened-runtime signature, Gatekeeper notarization assessment
and app staple, together with the final ZIP hash/size. ZIP archives cannot
themselves be stapled; no container ticket is invented. Local Xcode-managed
signing/notarization does not require exporting Apple credentials to CI.

See [SPEC §14](./SPEC.md#14-optional-native-desktop-distribution),
[Proposal 0006](./docs/proposals/0006-native-desktop-distribution.md), and the
[desktop](./schemas/desktop.schema.json) /
[evidence](./schemas/desktop-evidence.schema.json) schemas. The native
extension makes no constitutional amendment; Proposal 0007 is a separately
reviewed, explicitly proposed chat-application extension.

## Gated rapplications (private substance, public discovery)

Most catalog entries are public — anyone can fetch the source with a normal `curl`. But some rapplications **shouldn't be world-fetchable**: an operator's internal control plane, engine IP distributed inside an org, customer-specific bundles built on top of an open base. For those, the catalog supports **gated rapplications** — a public catalog entry whose source files live in a **private** GitHub repo.

The catalog publishes the rapp's existence, shape, and metadata. GitHub's `raw.githubusercontent.com` returns HTTP 404 for unauthenticated callers and HTTP 200 only for callers with read access on the private repo. Public discovery, private substance.

```jsonc
// in index.json's rapplications[]:
{
  "id": "cockpit",
  "manifest_name": "@wildhaven/cockpit",
  "access": "private",
  "private_repo": "kody-w/RAPP_Store_Private",
  "singleton_url": "https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/singleton/cockpit_agent.py",
  "singleton_sha256": "c77195ef…",
  "auth_hint": "gh auth token  →  curl -H \"Authorization: Bearer $TOKEN\" <singleton_url>"
}
```

```bash
# Anyone can verify the gate is real:
curl -sSL -o /dev/null -w "%{http_code}\n" \
  https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/singleton/cockpit_agent.py
# → 404 (anonymous)

# With a PAT scoped for read on the private repo:
curl -sSL -H "Authorization: Bearer $(gh auth token)" -o /dev/null -w "%{http_code}\n" \
  https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/singleton/cockpit_agent.py
# → 200
```

The full contract — manifest fields, validator behavior, installer responsibilities, security boundaries — lives in [**SPEC §11**](./SPEC.md#11-gated-rapplications-access-private). The design rationale is in [Proposal 0005](./docs/proposals/0005-gated-rapplications.md).

This is **federation Mode C** in the submission-paths taxonomy (see [SPEC §7](./SPEC.md#7-submission-paths)) — federation referencing a private repo, with the gate being GitHub's own access control. No servers, no relays, no custom auth code; the PAT is the access token.

## Pokédex API

Modeled on [PokeAPI](https://pokeapi.co/) — the catalog is a tree of static JSON files served from `raw.githubusercontent.com`. No backend, no auth, no rate limits, no infra to operate. Push to `main` → the API "deploys."

```
https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/index.json
https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/rapplication/<id>.json
https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/sprite/<id>.svg
https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/egg/<id>.egg
```

Legacy local `<id>.json` records contain stats, lineage and published
egg/sprite/singleton/UI URLs. Native federated records instead carry
`distribution: desktop`, validated `desktop` metadata, pinned source and
agent/UI integration fields. Native projection does not manufacture a
`rappid`, parent, sprite, egg or hatcher. Consumers must tolerate absent
legacy artifact fields.

The [`rapp-zoo`](https://github.com/kody-w/rapp-zoo) consumes this API in its **Discover** tab — sprites + cards + one-click egg downloads. Drag the egg back onto any brainstem to hatch the rapp.

The legacy full producer (`python3 scripts/build_pokedex_api.py`) walks
`apps/@*/` and rebuilds local JSON/sprite/egg outputs, then projects approved
native federation metadata. **Do not run it to invent missing federation
artifacts.** Native promotion instead runs a deterministic, scoped refresh:

```bash
python3 scripts/build_pokedex_api.py --native-only --ids <approved-native-id>
```

The scoped command reads the already-approved canonical catalog, writes
only that ID's v1 detail/list row, preserves unrelated generated files,
performs no network fetch, and never changes `index.json` at the root.

## Legacy catalog

[`index.json`](./index.json) at the repo root remains the canonical catalog
(`schema: "rapp-store/1.0"`) consumed by the brainstem's binder service.
Approved manifests supply local or federated entries; native v1 discovery
is a metadata-only projection of those reviewed entries.

```
https://raw.githubusercontent.com/kody-w/rapp_store/main/index.json
```

## RAPP Zoo v2 prototype summons

The additive [Zoo v2 Store extension](./specs/RAPP_ZOO_STORE_V2.md) provides a
static prototype-summon data plane without changing the v1 catalog or Pokédex.
`api/v2/discovery.json` is a small mutable pointer whose only target is an
immutable generation document at a full 40-character commit-pinned GitHub Raw
URL. Prototype artifacts and MIT license evidence are also commit-pinned and
SHA-256 verified.

Store v2 writes are serialized through one restartable issue branch at a time.
Every attempt derives content/predecessor-bound generation, branch, and tag
names. An atomic create-only remote lock ref, carrying workflow/issue/attempt
owner metadata, is the repository-wide authority; Actions concurrency only
coalesces contention and is not a queue. Exact-owner lease cleanup runs in
`finally`, while crashes leave an explicit lock requiring audited admin-only
recovery after the owner run and PR are proven inactive. Every generation
commit receives an annotated
`zoo-v2-generation-*` permanent tag before discovery can point at it. Required
current-main validation checks both the predecessor URL and exact digest, and
the scheduled audit proves tag and raw reachability independent of the PR
merge method. An active repository ruleset prevents generation-tag updates and
deletion. Every PR's changed paths are checked by trusted-main code; protected
Store changes are limited to authorized same-repository release/bootstrap
branches. The complete local three-dot Git diff is used instead of the
3,000-file-limited PR-files API. The required status is bound to a dedicated
validator GitHub App by exact context plus App ID; its protected environment
holds the App ID, slug, bot login/database ID, and private key. The App is
narrowly limited to commit-status write, issue write, pull-request write/read,
and contents read. Only its installation token may write Zoo lifecycle
markers, labels, issue closure, or stale-PR retirement; default Actions tokens
and `github-actions[bot]` comments are untrusted. The generation-tag ruleset is dedicated and has no bypass
actors. Administrator branch/ruleset configuration is out-of-band, with a
committed audit required before release. See the extension spec for App
permissions, environment protection, configuration, and bootstrap order.
Immediately before a tag is published, release re-fetches and revalidates
`main`, then uses an atomic main lease with the tag push. A stale retained
attempt is verified and permanently archived; a rerun derives a different
attempt from the new predecessor rather than moving or deleting a tag.
Label, manual, and scheduled reconciliation fully paginate the bounded open
eligible issue set, repair add-only PR/processed markers, and select the oldest
unprocessed command without relying on a trigger issue number. Scheduled runs
therefore drain coalesced or dropped issue notifications in order; incomplete
API scans and contradictory markers fail closed.

Create, update, and deprecate commands arrive as structured, inert GitHub
Issue JSON. An actor allowlist and deterministic validator turn an eligible
issue into a tested two-commit catalog PR; nothing auto-merges. Live records
are explicitly `prototype`, use the exact `RAPP/1` wire term and `rappid`
identity form, preserve external blockers, and set ecosystem acceptance to
`not-asserted`.

## Layout

Each rapplication is a directory with at least:

- `manifest.json` — metadata that the catalog generator reads
- `singleton/<name>_agent.py` — the converged single-file agent
- `source/` — pre-collapse component agents (optional, for reference)
- `ui/index.html` — optional iframe UI
- `eggs/*.egg` — optional state snapshots
- `README.md` — what the rapp does and how to use it

## Submitting a rapplication

All future submissions go through the **`[RAPP]` issue receiver and
maintainer approval** front door. Use
[the submission UI](https://kody-w.github.io/RAPP_Store/submit.html),
the publishing agent, or the issue template. The shared validator enforces
[SPEC §6](./SPEC.md#6-validation-rules-the-receiver-enforces-these), including
the singleton contract and mandatory UI:

- one file
- one class extending `BasicAgent`
- one `metadata` dict (OpenAI function-calling schema)
- one `perform(**kwargs) -> str`

Native submissions use **federation** with genuine public source-release
artifacts and complete §14 evidence; update the existing ID with a strictly
higher version. Do not hand-edit live catalog entries, submit inline native
binaries, or fabricate hashes/signing evidence. Direct catalog PRs and
release uploads alone are not submissions. See [SKILL.md](./SKILL.md) for
the exact issue envelope and staged approval sequence.

## Validation

[`Store validation`](./.github/workflows/store-validation.yml) runs on every
PR targeting `main` and every push to `main`, using Python 3.11 and Node 24.
It installs [`requirements-test.txt`](./requirements-test.txt) and runs the
**complete** `tests/` suite, including native metadata/receiver tests,
Node-executed storefront tests, producer determinism and Zoo v2 regressions.
Permissions are read-only; no signing credentials or catalog-publication
steps are involved. Producer tests write only isolated fixture outputs.

To run the same suite locally with Python and Node installed:

```bash
mkdir -p .ci-work/tmp
TMPDIR="$PWD/.ci-work/tmp" python3 -m venv .ci-work/venv
TMPDIR="$PWD/.ci-work/tmp" .ci-work/venv/bin/python -m pip install -r requirements-test.txt
node --version
TMPDIR="$PWD/.ci-work/tmp" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .ci-work/venv/bin/python -m pytest tests -q --basetemp=.ci-work/pytest
```

## Related

- **Engine:** [`kody-w/RAPP`](https://github.com/kody-w/RAPP) — brainstem, swarm, worker, install one-liner
- **Constitution:** Article XV (tier portability), Article XVI (catalog vs workspace), the "RAR is metadata, never authority" rule
- **Vault:** decision narratives in [`kody-w/RAPP/pages/vault/`](https://github.com/kody-w/RAPP/tree/main/pages/vault)
