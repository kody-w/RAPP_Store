# Proposal 0006 — Optional Native Desktop Distribution

| | |
|---|---|
| **Status** | Optional plumbing implemented for review; no release or live catalog entry published by this change |
| **Scope** | Public federation metadata, `[RAPP]` receiver/approval, static storefront, scoped v1 discovery |
| **Contract** | [SPEC §14](../../SPEC.md#14-optional-native-desktop-distribution), [`desktop.schema.json`](../../schemas/desktop.schema.json), [`desktop-evidence.schema.json`](../../schemas/desktop-evidence.schema.json) |
| **Constitution** | Unchanged. Any amendment to the deployable-unit or trust articles requires explicit owner approval; this proposal does not ratify one. |

## Problem

`rapp_crispy`, `rapp_rewind`, `rapp_shot`, and `rapp_voice` already have
federated catalog IDs in their existing source repositories. A genuine
macOS application is not installed by dropping their Python integration
into `agents/`. Inventing local egg/hatcher URLs obscures that distinction.
The legacy v1 producer also misses federation because it only walks
`apps/@*/`.

RAPP Tools is build/runtime infrastructure, **not a fifth listing**.
This change creates no new IDs, binaries, release URLs, hashes, signing
claims, or live entries.

## Decision

Add optional `desktop` metadata to `rapp-application/1.0` and the resulting
`rapp-store/1.0` entry. Absence preserves the legacy agent/UI contract.
Presence supplements that contract with public, architecture-specific
DMG or ZIP downloads in the **same existing source repository's GitHub Release**.
There is no binary mirror, inline native bundle, server, credential
store, automatic installer, signing service, or new RAPP/1 trust layer.

The extension requires:

- `platform: macos`, minimum OS, stable reverse-DNS bundle identifier.
- Full native-build commit and exact `v<manifest.version>` release tag.
- One or both of `arm64` and `x86_64`, with `dmg` and/or `zip` per architecture:
  at most four unique `(arch, format)` pairs, each with an exact
  version/ID/arch/format filename, HTTPS release URL, byte count and SHA-256.
- Hash/size-bound public publisher evidence, containing actual
  Developer ID/codesign, Gatekeeper and stapler reports, plus a successful
  same-repository build/verification Actions run for that source. DMGs
  also bind the accepted notarytool upload log; ZIPs describe the enclosed
  app's notarization/staple, never a container ticket.
- Plain-text prerequisites, privacy/permissions, setup, and a truthful
  explanation of the optional Python integration.

`scripts/lib_rapp.py` delegates these optional checks to
`scripts/lib_desktop.py`. Metadata beyond receiver-owned fields now
passes through as documented; the validator does not silently drop the
new contract or other author-supplied descriptive metadata.

## Evidence is not a trust assertion

The receiver verifies anonymous GitHub release/tag/run references,
GitHub's release-asset size/digest inventory, pinned evidence bytes, report
bindings, and the final archive's streamed SHA-256/byte count. It does **not**
mount, unpack or execute native applications, authenticate Apple-server responses
cryptographically, or prove that a publisher's report is honest.

These are inspectable **publisher release reports**, not a Store-issued
Apple notarization certificate. The reviewer must inspect/reproduce them
on macOS; macOS/Gatekeeper remains responsible for validating the installed
application. `signed: true`, `notarized: true`, ad-hoc signing, an unbound
log, a missing/failed build run, and an invented `rappid` are not substitutes.
No ecosystem or protocol acceptance is asserted.

Apple's notarytool log binds the **uploaded pre-staple DMG**.
Stapling changes the final archive bytes. Evidence therefore separately
binds `notarization.submitted_sha256` to the unmodified Apple log and
`subject.sha256` to the final downloadable DMG. The report must include a
successful final-DMG stapler validation; do not rewrite Apple's log to
contain a post-staple hash.

ZIP distribution instead binds the final archive hash/size and records
`notarization: {method: "stapled-app", app_path, bundle_id, version, minimum_os}`.
The Developer ID/hardened-runtime, codesign verification, Gatekeeper
notarization assessment and stapler output must describe that same enclosed
application. ZIPs cannot be stapled; no ZIP ticket, submission UUID or
notarytool container log is invented. Local Xcode-managed signing and
notarization is supported without exporting Apple credentials to CI. The
public same-commit Actions reference can be a build or verification run.

## Submission and approval

All future submissions use the existing **`[RAPP]` issue receiver and
maintainer approval** front door. Native submissions use federation,
never `submit_bundle`, direct catalog edits, or a PR that manufactures
generated artifacts.

1. Build/sign/notarize in the existing application source repo and
   publish genuine DMG/ZIP and evidence assets in its versioned release.
2. Wait for that public build workflow to succeed.
3. Add real `desktop` metadata to the source manifest in a subsequent
   commit. This avoids a self-referential commit/hash cycle:
   `desktop.source.commit_sha` identifies the native build;
   catalog `source.commit_sha` identifies the manifest/integration.
4. Open a `[RAPP]` federation issue for the **existing ID**, preferably
   with `source.ref` set to the full manifest commit.
5. Receiver validates and stages metadata only. The reviewer checks
   public evidence, native version/architecture, prerequisites and
   privacy disclosures, then applies `approved`.
6. Promotion rechecks the **current catalog** (strictly increasing
   version, unchanged publisher/repository/bundle ID), the issue payload,
   exact staged manifest commit and entry, the tag/build/run bindings,
   and all evidence/native byte pins. Drift requires resubmission.
7. Promotion updates that catalog entry and only its v1 detail/list row.
   It does not run either global legacy producer.

The 5 MiB bundle, 200 KiB singleton and 500 KiB UI caps are unchanged.
Native DMG/ZIP archives have their own 1 GiB-per-artifact limit (at most four),
64 KiB streaming chunks and a 900-second per-download budget; evidence
is limited to 256 KiB. Fetches are anonymous HTTPS with constrained
GitHub/CDN redirects, no credential lookup and no binary persistence.

## Static surfaces and determinism

- Native details offer real **Download for macOS** architecture choices,
  exact byte/hash pins, evidence links, prerequisites, privacy and setup.
  ZIP details use plain Finder unzip → Applications instructions. Python/UI
  integration is explicitly secondary.
- Missing/invalid native metadata fails closed rather than falling back
  to a fictitious Python native installer.
- Legacy entries retain explicit egg/hatcher links. No entry receives
  a guessed link merely because its kind is `rapp`.
- `build_pokedex_api.py --native-only --ids ...` projects approved native
  metadata without network access, timestamps, lineage, sprites, eggs,
  hatchers or binaries. It preserves unrelated generated files and rows.
- Protected Zoo v2 schemas, workflow, generation and discovery paths are
  outside this proposal and remain untouched.

## Owner actions and boundaries

Real source releases, Developer ID signing material, notarization
credentials, successful public build runs and review approval are
publication prerequisites. Secrets remain outside this store. If any
are unavailable, leave `desktop` absent and do not manufacture receipts.

Whether native distribution should change constitutional Articles II
or III is a separate owner-approval question. This optional metadata
extension does not amend those articles, replace the existing singleton
contract, or claim that an external protocol has accepted the apps.

## Verification

Tests inject tiny in-memory fetch/stream doubles; none downloads a native
binary. Validator, receiver, promotion, scoped/full-producer determinism,
static DOM behavior and shared Zoo v2 tests cover fail-closed handling
and preservation of legacy outputs. Test fixtures are never release or
signing evidence.
