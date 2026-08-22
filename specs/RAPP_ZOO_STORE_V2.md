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
  identity.
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
Consumers fetch discovery with `cache: no-store`; the selected generation and
all artifacts may be cached forever because their URLs are immutable.

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
reused as a live id.

An issue becomes eligible only when a maintainer adds
`zoo-v2-eligible`. `scripts/zoo_v2_store.py` then independently verifies that
the issue author is in the deterministic actor allowlist: the repository
owner plus the comma-separated `RAPP_ZOO_V2_ACTORS` repository variable.
Changing labels does not bypass actor validation.

Issue JSON is never passed to a shell, template evaluator, Python importer,
`eval`, or `exec`. Unknown fields and unknown operations are rejected.

## 5. Two-step catalog PR

`.github/workflows/zoo-v2-catalog-pr.yml` creates a reviewable branch:

1. Parse and validate the eligible issue, current generation, URLs, hashes,
   license evidence, operation, allowlist, and tombstone history.
2. Write and test one new immutable generation.
3. Commit and push that generation; capture the resulting full commit SHA.
4. Rewrite only `api/v2/discovery.json` to name the new generation at that
   exact commit.
5. Validate the local tree, commit the pointer separately, and open a PR.

This ordering avoids a self-referential Git hash. The generation commit exists
before its SHA is placed in discovery. The workflow never pushes catalog
changes to `main`, never closes the control issue, and never enables
auto-merge. The PR merge remains the human consent event.

## 6. Schemas and validator

- `schemas/zoo-v2/discovery.schema.json`
- `schemas/zoo-v2/generation.schema.json`
- `schemas/zoo-v2/command.schema.json`
- `scripts/zoo_v2_store.py`

The Python validator is stdlib-only and is the executable source of truth.
Run:

```bash
python3 -m pytest tests -q
python3 scripts/zoo_v2_store.py validate-tree --root .
```

Add `--network` to re-fetch and hash every live artifact and license evidence.

## 7. Sample-data boundary

The initial generation contains only `@synthetic/synthetic-echo`. Its source
and MIT evidence live under `samples/zoo-v2/`. It is intentionally trivial,
non-production, credential-free, and carries its unresolved external
conformance/admission blocker.
