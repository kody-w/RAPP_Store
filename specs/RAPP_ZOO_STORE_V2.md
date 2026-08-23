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
  "generation_url": "https://raw.githubusercontent.com/kody-w/RAPP_Store/<40-char-commit>/api/v2/generations/issue-123-<64-char-attempt-hash>.json"
}
```

The URL must use `raw.githubusercontent.com` and an exact lowercase
40-character commit SHA. A branch, tag, abbreviated SHA, query string, or
fragment is invalid. Its repository path is exactly
`api/v2/generations/<valid-generation-id>.json`; prefixes, suffixes, shadow
directories, traversal, and generation ids outside the schema are invalid.
The executable parser and both JSON schemas use the same generation-id
language. Discovery contains no catalog records.

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
An active, dedicated repository ruleset named **Zoo v2 generation tags**
includes only `refs/tags/zoo-v2-generation-*`, has no excludes or bypass
actors/modes, and forbids update, non-fast-forward update, and deletion. The
annotated tag check proves provenance; the ruleset prevents the proven ref
from subsequently being rewritten or removed. Other named rulesets remain
untouched.

For an issue attempt, `<generation-id>` is
`issue-<number>-<64-lowercase-hex>`. The hexadecimal component is derived from
the canonical attempt fields other than the id itself, including the exact
predecessor URL and digest. The generation path, issue branch
`zoo-v2/<generation-id>`, and permanent tag are therefore specific to both
content and predecessor rather than being a single issue-wide name.

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

The release lane is serialized by the atomic remote
`refs/heads/zoo-v2/release-lock` ref. The ref points to a unique metadata commit
that binds repository, issue, generation attempt, workflow run, actor, and a
stable rerun lease key. A normal push can create the absent ref exactly once;
all concurrent creators but one are rejected. After acquisition, and again
immediately before every branch or tag publication, the release script
re-fetches `main` and repeats complete queue and predecessor validation. It
also fetches the exact selected issue endpoint and requires it to remain open,
eligible, non-tombstoned, non-processed, and authored by an allowed actor.
Title, body, complete label-name set, and `updated_at` must equal the
reconciled snapshot. Trusted code regenerates the generation from those fresh
issue bytes and the current predecessor and requires byte identity. Any edit,
closure, or label race therefore aborts before the generation branch and tag
are published atomically.
Cleanup uses `--force-with-lease` against the exact owner commit in `finally`,
so it cannot delete a replacement lock. A process crash deliberately leaves a
detectable lock. The same workflow run and issue attempt can adopt that exact
lease on rerun.

GitHub Actions `concurrency` is only a contention-coalescing optimization. It
is not a queue and is not authoritative. The release script also rejects a new
issue while any different `zoo-v2/issue-*` PR or unfinished remote issue branch
exists. A rerun for the same attempt is allowed only when its generation bytes,
predecessor URL/digest, branch, tag target and annotation, discovery pointer,
and PR state all match. It resumes after the last durable stage. If ``main` advanced, trusted main-advance automation verifies and closes the stale
unmerged PR, adds `zoo-v2-superseded`, and records an exact structured marker
containing its PR, candidate head, attempt, invalidating base, exact failed
status ID, generation commit/path, and tag. The invalidating base must be an
actual commit reachable from freshly fetched `origin/main`; its discovery must
invalidate the candidate predecessor. The marker is accepted only when the
candidate head has that exact dedicated-App-authored failure status binding
the complete base SHA and attempt digest.
The immutable branch and tag remain evidence. Scheduled reconciliation permits
a retry only after validating that marker, exact closed-unmerged PR, stale
predecessor, generation bytes, and permanent tag through GitHub/Git. It then
derives a unique attempt from current discovery. Arbitrary PR closure remains
blocked. Multiple audited supersessions remain retryable and retain the
original command bytes.

Queue inspection first enumerates the bounded set of retained issue branches,
then queries GitHub for each exact head branch. It never relies on a fixed
repository-wide PR window. Malformed responses, a branch/PR bound, or an API
failure fails closed.

The catalog workflow runs for issue-label notifications, manual dispatch, and
twice-hourly schedule. Every run independently paginates all open
`zoo-v2-eligible` issues, with an explicit 500-issue bound and one extra page
probe. It reconciles processed, exact-PR, closed-unmerged, and explicitly
`zoo-v2-tombstoned` states, then selects the oldest unprocessed command by
creation timestamp and issue number. It never requires an issue number from
the triggering event. Thus coalesced/dropped notifications cannot lose a
command: scheduled runs keep selecting the next item after the current PR
merges. Incomplete pages, malformed fields, premature processed labels,
multiple open PRs, and unaudited closed-unmerged PRs fail closed. Labels and
comments are add-only audit records. Marker comments are trusted only when
their author is type `Bot`, exact bot login/database ID, and exact
`performed_via_github_app` ID/slug from the committed protection audit.
Repository owners and shared `github-actions[bot]` are never trusted marker
authors. PR-open markers link exact PR numbers and attempts but never mark an
issue processed.

Stale-lock recovery is never automatic. A repository administrator must invoke
`zoo_v2_release.py recover-lock` with the exact observed owner SHA, their
authenticated actor, and a reason. Recovery verifies administrator permission,
requires the recorded Actions run to be completed, performs complete exact-head
PR inspection, and refuses if the run or an owner PR may still be active. It
writes an issue audit comment (or a dedicated bootstrap recovery issue) before
deleting the exact lease. The token used for recovery therefore needs only
repository administration, Actions read, issue write, PR read, and contents
write capabilities; routine catalog runs retain their narrower declared
permissions.

```bash
# Deliberate break-glass action after inspecting the lock commit and owner run.
export GITHUB_ACTOR="$(gh api user --jq .login)"
python3 scripts/zoo_v2_release.py recover-lock \
  --repository owner/repo \
  --expected-owner-sha <exact-40-character-lock-commit> \
  --admin-actor "$GITHUB_ACTOR" \
  --reason "Audited reason the completed owner cannot clean up"
```

Issue JSON is never passed to a shell, template evaluator, Python importer,
`eval`, or `exec`. Unknown fields and unknown operations are rejected.

## 5. Serialized, restartable catalog PR

`.github/workflows/zoo-v2-catalog-pr.yml` creates a reviewable branch:

1. Reconcile the complete eligible issue set and select its oldest pending
   command, independent of the triggering event payload.
2. Parse and validate the eligible issue, current generation, URLs, hashes,
   license evidence, operation, allowlist, and tombstone history.
3. Write and test one new immutable generation.
4. Acquire the atomic repository release lock, re-fetch current `main`, and
   repeat complete queue and predecessor validation.
5. Commit that generation locally and capture its resulting full commit SHA.
6. Rewrite only `api/v2/discovery.json` to name the new generation at that
   exact commit and commit the pointer locally.
7. Re-fetch and revalidate current `main` and the issue, then atomically push
   the complete attempt branch and its unique annotated permanent tag under
   compare-and-swap leases on exact `main` and the absent/exact attempt branch.
   A collision is accepted only when the peeled commit, annotation, generation,
   and discovery bytes are exact.
8. Find or create the PR and structured issue backlink, then release only the
   exact lock lease.

This ordering avoids a self-referential Git hash. The generation commit exists
before its SHA is placed in discovery. The workflow never pushes catalog
changes to `main` and never enables auto-merge. The PR merge remains the human
consent event. Opening a PR does not complete a command.

After a merge, `.github/workflows/zoo-v2-merge-completion.yml` re-fetches the
exact merged PR and current `main`, verifies the merged attempt bytes,
discovery pointer, introducing commit, and permanent tag, then idempotently
writes a trusted structured completion marker, adds `zoo-v2-processed`, and
closes the issue. The marker records the exact merged PR, attempt, generation
path/commit, tag, and merge timestamp. Reconciliation recognizes a processed
label only after independently validating that trusted marker and exact merged
PR through the API. The PR-open backlink allows recovery if completion is
interrupted. Neither path depends on retained head branches or repository-wide
PR history, so automatic head deletion cannot lose completion.

`.github/workflows/zoo-v2-pr-validation.yml` publishes the
`Zoo v2 current-main` status for every PR. It checks out current `main` as the
trusted tooling/base tree and the exact candidate head as inert data. After
verifying both full 40-character SHAs and fetching the trusted base into the
candidate object database, trusted code computes
`git diff --name-only --no-renames -z <base>...<head>`. It refuses shallow
history, a missing merge base, malformed/non-UTF-8/NUL/newline paths, more than
10,000 paths, or more than 1 MiB of path data. This avoids the GitHub PR-files
API's 3,000-file ceiling. Every returned path is classified, so a protected
path late in a large diff still gates.

Protected paths are `api/v2/**`, the Zoo v2 schemas and issue forms, the Zoo
v2 workflows, the Store/release/protection scripts, this specification, and
the committed protection audit. A protected diff is refused unless it is from
the same repository on an exact
`zoo-v2/issue-<number>-<64-char-attempt-hash>` branch or the one-time
`zoo-v2/bootstrap-protection` branch. Issue branches may change only their
matching exact generation plus discovery, and `validate-pr` independently
requires that those are the complete changed-file set; the bootstrap branch
cannot change `api/v2/**`. A fork can pass only when it changes no protected
path. Thus "not a Zoo branch" is never a bypass for a protected diff.

Both validator modules execute from an
independent checkout of current `main`; the head checkout is passed only as
the `--root` data tree and cannot shadow trusted imports. Repository branch
protection must use `required_status_checks.checks` to require the exact
`{context: "Zoo v2 current-main", app_id: <validator App ID>}` pair with
strict/up-to-date semantics. A generic context-only status, the GitHub Actions
App, or any other App cannot satisfy the barrier. The default `GITHUB_TOKEN`
has no `statuses: write` permission in either status publisher. Validation,
completion, queue reconciliation, and main-advance retirement workflows
mint an installation token for the dedicated App from the protected
`zoo-v2-validator` environment. Only that token may publish the trusted
context, processed/superseded comments and labels, issue closure, or stale-PR
closure. Missing token or identity configuration fails closed before lifecycle
reconciliation.

Protection also requires one approving PR review, stale-review dismissal,
last-push approval, and admin enforcement. Force pushes and branch deletion
must be disabled. The check verifies the candidate's one-operation
create/update/deprecate delta, predecessor URL and digest, pinned generation
commit, annotated permanent tag, and fork boundary. On every `main` push,
`.github/workflows/zoo-v2-main-advance.yml` reruns the same trusted validator
for every open retained Zoo v2 branch as defense in depth, using exact
per-branch PR queries rather than a truncated repository-wide list. A stale
candidate receives the App-authored failing status; trusted workflow
automation then fetches `main`, requires the marker's invalidating base to be
an ancestor of `origin/main`, matches its full SHA and attempt to the exact
App-authored failed status on the exact candidate head, re-fetches the exact
still-open PR, proves discovery at that base invalidates its predecessor and
its branch/tag evidence is exact, records the superseded marker and label, and
closes it. An arbitrary candidate/local commit can never serve as an
invalidating base. A merge race aborts retirement. Merge
safety does not depend on
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
  --repository kody-w/RAPP_Store \
  --validator-app-id "$ZOO_V2_VALIDATOR_APP_ID" \
  --validator-app-slug "$ZOO_V2_VALIDATOR_APP_SLUG" \
  --validator-app-login "$ZOO_V2_VALIDATOR_APP_LOGIN" \
  --validator-app-user-id "$ZOO_V2_VALIDATOR_APP_USER_ID" \
  --audit-output .github/zoo-v2-protection-audit.json
python3 scripts/configure_zoo_v2_protection.py verify-audit \
  --repository kody-w/RAPP_Store \
  --validator-app-id "$ZOO_V2_VALIDATOR_APP_ID" \
  --validator-app-slug "$ZOO_V2_VALIDATOR_APP_SLUG" \
  --validator-app-login "$ZOO_V2_VALIDATOR_APP_LOGIN" \
  --validator-app-user-id "$ZOO_V2_VALIDATOR_APP_USER_ID"
python3 scripts/zoo_v2_release.py validate-pr --repository kody-w/RAPP_Store
python3 scripts/zoo_v2_release.py audit-refs \
  --repository kody-w/RAPP_Store --network
```

Add `--network` to re-fetch and hash every live artifact and license evidence.

### Bootstrap one-time migration

The bootstrap generation predates both the permanent-ref rule and this
protection script. The one permitted bootstrap sequence is:

1. Create a dedicated GitHub App (not a reusable Actions or CI App), install it
   on this repository, and grant only these repository permissions:
   **Commit statuses: Read and write**, **Issues: Read and write**, **Pull
   requests: Read and write**, and **Contents: Read-only**. Record its numeric
   App ID, canonical slug, bot login (`<slug>[bot]`), bot user database ID, and
   private key. No Administration, Actions, checks, deployments, members,
   metadata-write, or contents-write permission is required.
2. Create the protected GitHub environment **`zoo-v2-validator`**. Require
   appropriate environment reviewers and restrict deployment branches
   according to repository policy. Add environment secrets
   `ZOO_V2_VALIDATOR_APP_ID`, `ZOO_V2_VALIDATOR_APP_SLUG`,
   `ZOO_V2_VALIDATOR_APP_LOGIN`, `ZOO_V2_VALIDATOR_APP_USER_ID`, and
   `ZOO_V2_VALIDATOR_PRIVATE_KEY`; do not add them as ordinary repository
   secrets. Obtain the bot database ID with
   `gh api "users/${ZOO_V2_VALIDATOR_APP_LOGIN}" --jq .id`. Every value passed
   to the configuration tool must match. Missing/mismatched values are a hard
   failure.
3. Merge the PR that adds the trusted validation workflow and protection
   script to `main`; no Store v2 candidate may be released in this interval.
   Confirm the workflow can mint the App installation token and that the
   resulting commit status is authored by that App.
4. From an administrator-authenticated `gh` session, configure and verify the
   merge barrier and immutable-generation-tag ruleset:

   ```bash
   export ZOO_V2_VALIDATOR_APP_ID=<numeric-app-id>
   export ZOO_V2_VALIDATOR_APP_SLUG=<canonical-app-slug>
   export ZOO_V2_VALIDATOR_APP_LOGIN="${ZOO_V2_VALIDATOR_APP_SLUG}[bot]"
   export ZOO_V2_VALIDATOR_APP_USER_ID="$(
     gh api "users/${ZOO_V2_VALIDATOR_APP_LOGIN}" --jq .id
   )"
   python3 scripts/configure_zoo_v2_protection.py configure-verify \
     --repository kody-w/RAPP_Store \
     --validator-app-id "$ZOO_V2_VALIDATOR_APP_ID" \
     --validator-app-slug "$ZOO_V2_VALIDATOR_APP_SLUG" \
     --validator-app-login "$ZOO_V2_VALIDATOR_APP_LOGIN" \
     --validator-app-user-id "$ZOO_V2_VALIDATOR_APP_USER_ID" \
     --audit-output .github/zoo-v2-protection-audit.json
   ```

   The tool first reads branch protection, preserves every existing status
   check (except unbound/wrong-App copies of the trusted context), review count
   and setting, restrictions, linear-history flag, lock, creation block, and
   other safeguard accepted by the branch API, then adds the exact App-bound
   Zoo check. It rewrites only the named generation-tag ruleset to its
   dedicated exact pattern/rules and empty bypass list; unrelated rulesets are
   preserved. Verification accepts branch-protection supersets but rejects any
   generic/wrong-App trusted status and any named-ruleset extra scope, rule, or
   bypass.

5. Review and commit the generated canonical audit on the protected
   `zoo-v2/bootstrap-protection` branch. The audit is the durable evidence that
   an administrator completed the out-of-band platform configuration. It
   records the exact validator App ID, slug, bot login/database ID, narrowly
   required permissions, check binding, and empty tag-ruleset bypass list. The
   ordinary workflows read this file and compare all identity values to the
   protected environment configuration; they do not call GitHub Administration
   APIs.

6. Only after that audit merges, run the idempotent workflow **Zoo v2 bootstrap
   permanent-ref migration**,
   or run the following locally.

```bash
git fetch --prune origin main
python3 scripts/configure_zoo_v2_protection.py verify-audit \
  --repository kody-w/RAPP_Store \
  --validator-app-id "$ZOO_V2_VALIDATOR_APP_ID" \
  --validator-app-slug "$ZOO_V2_VALIDATOR_APP_SLUG" \
  --validator-app-login "$ZOO_V2_VALIDATOR_APP_LOGIN" \
  --validator-app-user-id "$ZOO_V2_VALIDATOR_APP_USER_ID"
python3 scripts/zoo_v2_release.py protect-bootstrap \
  --repository kody-w/RAPP_Store
python3 scripts/zoo_v2_release.py audit-refs \
  --repository kody-w/RAPP_Store --network
```

This creates `zoo-v2-generation-bootstrap-20260822` at the original generation
commit. It refuses an existing lightweight tag, wrong target, altered
annotation, or changed bootstrap bytes. The issue workflow repeats this check
idempotently before every release. Both bootstrap and issue release commands
fail before any push if the committed audit is absent or malformed. Live
branch/ruleset administration remains an out-of-band mandatory platform
prerequisite: standard `GITHUB_TOKEN` permissions are never represented as
having Administration read access. Re-run `configure-verify`, review its audit
diff, and merge the audit before every Store v2 pre-release; this is mandatory,
not an advisory audit.

## 7. Sample-data boundary

The initial generation contains only `@synthetic/synthetic-echo`. Its source
and MIT evidence live under `samples/zoo-v2/`. It is intentionally trivial,
non-production, credential-free, and carries its unresolved external
conformance/admission blocker.
