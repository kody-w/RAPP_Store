# Store checks and owner-reviewed publication

The Store remains a static, no-build Pages site. `index.json` is still canonical.
These workflows do not deploy, merge PRs, configure repository settings, provision
an App, or grant RAPP/1 authenticated acceptance.

## Required-check contract

An administrator must configure and verify protection separately. Merely adding
these workflows does **not** make an unprotected branch protected.

| Exact check/context | Producer and scope | Passing means |
| --- | --- | --- |
| `Complete store suite` | Store validation; read-only, no secrets | All `tests/`, including browser-contract, native, legacy and workflow doubles, pass at the candidate |
| `Pages checks` | Store validation; read-only, stdlib only | No new local link/HTML/lint regression or local-core budget overrun; explicitly listed existing debt remains |
| `Submission binding` | Store validation; read-only GitHub metadata | An issue-generated PR still matches its issue, exact head and current-main base, and changes only its submission paths; ordinary PRs do not receive publication authority |
| `Zoo v2 current-main` | Dedicated validator **GitHub App commit status**, not the Actions job named `current-main` | Trusted-main tooling classified and validated the inert candidate against current main, with the audited App identity |

All four are required before completion is recorded. A missing,
pending, skipped, failed or wrong-actor result is not success. A green Store suite,
Pages lane or unrelated scanner cannot replace the App-bound context. Require
up-to-date branches and owner review in addition to checks. No workflow enables
auto-merge or bypasses an existing rule.

Completion also checks the latest explicit validator dispatch for this PR/head
and reviewed main commit. An unavailable App cannot revoke an older status:
an old green App status therefore cannot hide a newer failed/pending dispatch.
The diagnostic Actions run is required **in addition to**, not instead of, the
App-authored status.

The validator must retain its existing protected-path policy, including fork
refusals and the narrowly authorized Zoo issue/bootstrap lanes. A workflow-edit
PR can therefore be refused by the **existing** protected-path classifier even
after its App is provisioned. Follow the audited bootstrap procedure; do not
rename an ordinary status or widen the path policy to make it pass.

## Validator App unavailable: diagnosis and recovery

The token-using Zoo workflows check all five settings **before token creation**:

- `ZOO_V2_VALIDATOR_APP_ID`
- `ZOO_V2_VALIDATOR_PRIVATE_KEY`
- `ZOO_V2_VALIDATOR_APP_SLUG`
- `ZOO_V2_VALIDATOR_APP_LOGIN`
- `ZOO_V2_VALIDATOR_APP_USER_ID`

Missing settings yield **`validator App unavailable: missing …`**, listing names
only. The required App status remains absent, never fabricated with
`GITHUB_TOKEN`. Invalid committed audit/configuration or mint failure also fails
closed. This is an infrastructure failure, distinct from an unauthorized
protected diff. The September 2026 baseline had an unavailable App and
unprotected `main`; this change does not claim either prerequisite is repaired.

An authorized administrator, outside publisher CI, must:

1. Install the dedicated App and configure the `zoo-v2-validator` environment.
   Use the permissions and identity checks already defined by
   `scripts/configure_zoo_v2_protection.py`; do not introduce a second authority.
2. Use that script's `verify` command for a read-only live-settings audit, or its
   **mutating** `configure-verify` command only with separate administrator
   authorization. Both accept `--repository`, `--validator-app-id`,
   `--validator-app-slug`, `--validator-app-login`, and `--validator-app-user-id`.
   `--audit-output` records the resulting public configuration audit.
3. Review/commit the audit through the existing authorized bootstrap process.
   `verify-audit` checks the committed document offline; it is not evidence that
   live settings have never changed. Preserve additional branch requirements.
4. Separately require the Store suite, Pages and binding checks above. The
   existing Zoo configuration helper owns the App-bound Zoo prerequisite, not
   this whole expanded required-check set.
5. Rerun validation for the PR's exact head/current main. Never substitute a
   successful status when the administrator is unavailable.

No credential values belong in reports, issues, PR bodies, or this repository.

## Third-party submissions: two reviewed PRs, no main push

The `[RAPP]` issue, public bundle/federation formats, receiver and validators are
unchanged. Both community and official publishers use the same path:

1. Open/edit/reopen the public submission issue. Processing runs the existing
   receiver on trusted main without publisher credentials. It isolates staged
   records under `staging/issue-<number>/`, binds the complete issue text and
   validated metadata, and opens a **staging-only PR** from a content-bound
   `rapplication/stage/…` branch. Nothing changes on main yet.
2. Review the staged public bytes. The repository owner merges this exact checked
   staging PR. The catalog is unchanged and the issue remains open. Do not add
   `approved` until this PR has landed.
3. Add `approved`. The promoter revalidates the staged submission against the
   current catalog and requires unchanged issue content, source pin and metadata.
   It prepares a separate `rapplication/promotion/…` PR. Bundle destinations now
   match `apps/@publisher/id/` catalog URLs. Previous distributables and version
   snapshots are preserved; native binaries remain in their publisher's release.
4. Review all four checks and the exact base/head. Only the repository owner
   merges, and that merge is what changes the public catalog on main. The
   trusted-main completion workflow first verifies the current issue binding and
   that the actual merge is the exact checked tree on its reviewed parent. Only
   then does it check the successful exact-head checks and dedicated App status,
   and it adds `promoted` and closes the issue only if all of them pass.
   Otherwise it reports what is true, with the refusal code, in the job log and
   in one issue comment, for example “merged at `<sha>`; the catalog on main
   changed; completion not recorded (validator App unavailable)”. It adds no label,
   leaves the issue open and fails the job. While the validator App is
   unavailable, this is the steady state: publication happens at the owner's
   merge, and completion stays unrecorded. An unmerged, non-owner or unverified
   merge writes nothing and never reports publication.

Staging is **public**, not an internal-release or sanitization channel. Complete
applications unsupported by this main-branch validator are rejected, not routed
through a legacy exception. Existing pre-migration `staging/_pending.json` records
must be reprocessed into an issue-isolated staging PR before new approval.

Candidate branches are immutable. A retry of the same event/base/tree reuses its
branch and pending PR; a different issue/source/base requires revalidation and a
new candidate. Old bot-created candidates are retired when replaced. Edits clear
approval; a failed attempt is not labelled promoted and cannot close the issue.
Never merge a stale candidate or rebase it manually; rerun the corresponding
issue workflow from current main. Keep the source available through review.

`GITHUB_TOKEN` PR creation does not normally trigger PR workflows. The publisher
therefore explicitly dispatches:

- `store-validation.yml` on the **candidate branch**, with exact head/base inputs,
  read-only permissions, no secrets and a SHA equality guard;
- `zoo-v2-pr-validation.yml` on **trusted main**, with PR number/exact head inputs.
  Candidate files remain inert in this credential-bearing job.

Dispatch success means queued, **not checked**. If branch push, PR creation or
either dispatch fails, reporting stays “not published”: nothing has merged.
Missing App authority blocks **recorded** completion, never the truthful report
after the owner's merge (step 4). Repository settings must allow Actions to create
PRs; a denial is an explicit failure, never a reason to push main.

## Pages lint and measured budgets

Run strict source lint:

```sh
python3 scripts/pages_check.py
```

The CI regression lane acknowledges only the reviewed exact findings in
`docs/pages-check-baseline.json`:

```sh
python3 scripts/pages_check.py --baseline docs/pages-check-baseline.json
```

The checker parses root HTML and documentation HTML, checks local file/fragment
targets (including canonical `#rapp=` links), requires real directory indexes,
checks HTML nesting/IDs, and performs basic name/label/keyboard source lint.
It does not execute JavaScript, crawl the internet, emulate Jekyll, measure
contrast/focus/reflow, or certify WCAG. Existing raw-Markdown navigation,
unlabelled inputs, pointer-only targets and blocking federation loading remain
visible debt, not a newly claimed accessibility pass. Broken links, malformed
HTML and budget overruns cannot be baseline-exempted. The previously missing
Proposals route now has a real HTML index with rendered Markdown links.

Budgets are **65,536 decoded bytes per HTML document** and **65,536 deterministic
gzip bytes / at most three resources for the local application core** (homepage,
canonical catalog and static same-page assets). The core limit is **not** a full
startup limit: runtime/external fetches are listed as excluded. Exceeding either
checked local budget fails.

Measurements on 2026-09-23, main baseline `29b33b0`:

| Resource | Decoded bytes | Local gzip-9 bytes | Observed HTTP gzip body bytes |
| --- | ---: | ---: | ---: |
| `index.html` | 53,476 | 14,077 | 14,264 |
| `index.json` | 74,964 | 19,040 | not re-fetched in this change |
| `submit.html` | 34,194 | 9,329 | not re-fetched in this change |
| `vbrainstem.html` | 1,525 | 801 | not re-fetched in this change |
| External RAR `registry.json` | **6,654,528** | 528,153 | **542,955** |

The checked local core totals **33,117 gzip bytes / two resources**. The public
homepage fetched for this observation matched the baseline bytes. Local gzip
is deterministic compression, **not** network transfer measurement. The two
HTTP observations above were anonymous GETs requesting gzip; no browser
waterfall, paint timing, or mobile/accessibility pass was measured.

The source still waits for RAR, senses and the sequential Zoo generation fetch
before rendering. RAR **alone** exceeds the intended 65,536-byte full initial
application-view target by more than eightfold on the observed wire. That target
is **not met**. Deferred/progressive federation loading belongs to a later
front-end change; neither a passing local-core check nor this baseline conceals
that debt. CI remains offline and does not silently treat a remote fetch failure
as zero bytes.

## Local validation

```sh
mkdir -p .v/work
TMPDIR="$PWD/.v/work" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  python3 -m pytest tests -q --basetemp=.v/run
```

Do not commit `.v/`. Parse workflow YAML; run `actionlint` if already installed.
Regression tests use local Git repositories and inert GitHub doubles, not live
settings, App secrets, production applications or public pushes.
