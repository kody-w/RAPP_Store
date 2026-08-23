# RAPP Zoo Store v2 — prototype summon extension

`schema family: rapp-zoo-store-*/2.0`

`store status: canonical extension`

`artifact status: prototype / non-production`

`external ecosystem acceptance: not asserted`

This document defines the RAPP Store's versioned v2 surface for discovering
and dialing **prototype summons**. It is additive: `index.json`, `api/v1/`,
the Pokédex, and every existing v1 consumer remain unchanged.

The Store is a static data and review system. It does not run submitted issue
content, artifacts, or license files. It does not add an engine endpoint.

## 1. Exact wire and identity terms

- `wire_contract` is exactly **`RAPP/1`**. In this catalog it names the
  proposed chat contract; it is not evidence that another repository or
  governing body accepted the prototype.
- `identity` is a full **`rappid:@owner/slug:<64-lowercase-hex>`** content
  identity. For this single-artifact prototype surface, its hexadecimal tail
  is exactly `artifact.sha256`.
- `ecosystem_acceptance` is exactly **`not-asserted`**.
- `status` is exactly **`prototype`** for live entries.
- `external_blockers` is a non-empty list and travels forward on every
  update. The sample blocker records that independent RAPP/1 conformance and
  ecosystem admission remain incomplete.

The browser's **Dial prototype** action copies a
`rapp-zoo-prototype-summon/2.0` data envelope. It does not import or execute
the artifact.

## 2. Static data plane

The only mutable read location is:

```
api/v2/discovery.json
```

It has exactly two fields:

```json
{
  "schema": "rapp-zoo-store-discovery/2.0",
  "generation_url": "https://raw.githubusercontent.com/kody-w/RAPP_Store/<40-char-commit>/api/v2/generations/issue-123.json"
}
```

The URL must use `raw.githubusercontent.com` and an exact lowercase
40-character commit SHA. A branch, tag, abbreviated SHA, query string, or
fragment is invalid. Discovery contains no catalog records.

Each file under `api/v2/generations/` is an immutable
`rapp-zoo-store-generation/2.0` document. A generation contains sorted live
prototypes and append-only tombstones. Its `previous_generation_url` is
another full commit-pinned raw URL (or `null` for the initial generation).
Every non-bootstrap generation also records `previous_generation_sha256`, the
SHA-256 of the exact canonical bytes selected by current `main` discovery.
The URL and digest are both checked again against freshly fetched
`origin/main` on every PR update and whenever `main` advances.
Consumers fetch discovery with `cache: no-store`; the selected generation and
all artifacts may be cached forever because their URLs are immutable.

Each generation commit is protected before discovery is published by a unique
annotated tag named `zoo-v2-generation-<generation-id>`. The annotation records
the generation path, canonical content SHA-256, source issue (or bootstrap),
and predecessor URL. Discovery still uses the tag's peeled, full 40-character
commit SHA, never the tag name. This preserves GitHub Raw reachability even
when the catalog PR is squash-merged, rebased, or normally merged.

## 3. Prototype requirements

Every live prototype has:

- strict id and semver;
- a full commit-pinned raw artifact URL and SHA-256;
- an allowed media type;
- an MIT-first SPDX expression;
- a full commit-pinned license-evidence URL and SHA-256;
- recognizable MIT evidence text;
- the exact wire, identity, status, and non-acceptance terms from §1;
- at least one explicit external blocker.

The deterministic validator downloads artifact and license bytes only to
hash and inspect them as inert data. Hash drift fails closed.

## 4. Issue CRUD control plane

Three issue forms emit one fenced JSON command:

- `[ZOO V2 CREATE] <id>` adds a never-used id.
- `[ZOO V2 UPDATE] <id>` replaces a live entry with a strictly higher semver.
- `[ZOO V2 DEPRECATE] <id>` removes the live entry and appends a permanent
  tombstone with its last version and artifact hash.

There is deliberately no delete operation and no resurrection. A prior
tombstone cannot be removed, edited, reordered ahead of prior tombstones, or
reused as a live id. Updates may append external blockers but cannot remove,
reorder, or rewrite blockers inherited from the previous live entry.

An issue becomes eligible only when a maintainer adds
`zoo-v2-eligible`. `scripts/zoo_v2_store.py` then independently verifies that
the issue author is in the deterministic actor allowlist: the repository
owner plus the comma-separated `RAPP_ZOO_V2_ACTORS` repository variable.
Changing labels does not bypass actor validation.

The release lane is serialized. GitHub Actions concurrency serializes active
runs, and the release script also rejects a new issue while any different
`zoo-v2/issue-*` PR or unfinished remote issue branch exists. A rerun for the
same issue is allowed only when its generation bytes, predecessor URL/digest,
branch, tag target and annotation, discovery pointer, and PR state all match.
It resumes after the last durable stage; it never force-rewrites a mismatched
branch or tag. PR creation and the issue backlink comment are find-or-create.

Issue JSON is never passed to a shell, template evaluator, Python importer,
`eval`, or `exec`. Unknown fields and unknown operations are rejected.

## 5. Serialized, restartable catalog PR

`.github/workflows/zoo-v2-catalog-pr.yml` creates a reviewable branch:

1. Parse and validate the eligible issue, current generation, URLs, hashes,
   license evidence, operation, allowlist, and tombstone history.
2. Write and test one new immutable generation.
3. Commit and push that generation; capture the resulting full commit SHA.
4. Create and push its unique annotated permanent tag. A collision is accepted
   only when its peeled commit and complete provenance annotation are exact.
5. Rewrite only `api/v2/discovery.json` to name the new generation at that
   exact commit.
6. Validate the local tree, commit and push the pointer separately, and
   find or create the PR and issue comment.

This ordering avoids a self-referential Git hash. The generation commit exists
before its SHA is placed in discovery. The workflow never pushes catalog
changes to `main`, never closes the control issue, and never enables
auto-merge. The PR merge remains the human consent event.

`.github/workflows/zoo-v2-pr-validation.yml` publishes the
`Zoo v2 current-main` status. Both validator modules execute from an
independent checkout of current `main`; the head checkout is passed only as
the `--root` data tree and cannot shadow trusted imports. Repository branch
protection must require that exact status with strict/up-to-date semantics,
one approving PR review, stale-review dismissal, last-push approval, and admin
enforcement. Force pushes and branch deletion must be disabled. The check
verifies the candidate's one-operation
create/update/deprecate delta, predecessor URL and digest, pinned generation
commit, annotated permanent tag, and fork boundary. On every `main` push,
`.github/workflows/zoo-v2-main-advance.yml` reruns the same trusted validator
for every open Zoo v2 PR as defense in depth. Merge safety does not depend on
that asynchronous overwrite: GitHub's strict required-status barrier refuses
a head that is not up to date with the exact current base. Main-advance runs
cancel older runs, recheck the current base and head before publishing, and
record the validated base SHA in status metadata.

`.github/workflows/zoo-v2-audit.yml` runs after v2 changes reach `main`, daily,
and on demand. It proves that every generation and predecessor URL resolves to
the exact commit protected by its deterministic annotated tag and optionally
re-fetches the raw bytes. It does not rely on branch-retention or merge-method
settings.

## 6. Schemas and validator

- `schemas/zoo-v2/discovery.schema.json`
- `schemas/zoo-v2/generation.schema.json`
- `schemas/zoo-v2/command.schema.json`
- `scripts/zoo_v2_store.py`
- `scripts/zoo_v2_release.py`

The Python validator is stdlib-only and is the executable source of truth.
Run:

```bash
python3 -m pytest tests -q
python3 scripts/zoo_v2_store.py validate-tree --root .
python3 scripts/configure_zoo_v2_protection.py configure-verify \
  --repository kody-w/RAPP_Store
python3 scripts/zoo_v2_release.py validate-pr --repository kody-w/RAPP_Store
python3 scripts/zoo_v2_release.py audit-refs \
  --repository kody-w/RAPP_Store --network
```

Add `--network` to re-fetch and hash every live artifact and license evidence.

### Bootstrap one-time migration

The bootstrap generation predates both the permanent-ref rule and this
protection script. The one permitted bootstrap sequence is:

1. Merge the PR that first adds the trusted validation workflow and protection
   script to `main`; no Store v2 candidate may be released in this interval.
2. From an administrator-authenticated `gh` session, configure and verify the
   merge barrier:

   ```bash
   python3 scripts/configure_zoo_v2_protection.py configure-verify \
     --repository kody-w/RAPP_Store
   ```

3. Run the idempotent workflow **Zoo v2 bootstrap permanent-ref migration**,
   or run the following locally.

```bash
git fetch --prune origin main
python3 scripts/configure_zoo_v2_protection.py verify \
  --repository kody-w/RAPP_Store
python3 scripts/zoo_v2_release.py protect-bootstrap \
  --repository kody-w/RAPP_Store
python3 scripts/zoo_v2_release.py audit-refs \
  --repository kody-w/RAPP_Store --network
```

This creates `zoo-v2-generation-bootstrap-20260822` at the original generation
commit. It refuses an existing lightweight tag, wrong target, altered
annotation, or changed bootstrap bytes. The issue workflow repeats this check
idempotently before every release and fails closed if strict protection cannot
be read or no longer exactly matches the required policy. Re-run
`configure-verify` before every Store v2 pre-release; it is mandatory, not an
advisory audit.

## 7. Sample-data boundary

The initial generation contains only `@synthetic/synthetic-echo`. Its source
and MIT evidence live under `samples/zoo-v2/`. It is intentionally trivial,
non-production, credential-free, and carries its unresolved external
conformance/admission blocker.
