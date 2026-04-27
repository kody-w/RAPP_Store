# PublishToRappStore — `@rapp/publish-to-rapp-store`

> **Submit a rapplication, from your repo or your laptop.**
> A rapplication that publishes other rapplications. Drop it in your local brainstem's `agents/` directory and ask it to submit your work to `kody-w/rapp_store`.

---

## What it does

Validates your rapplication against [SPEC.md](https://github.com/kody-w/rapp_store/blob/main/SPEC.md) using the same rules the receiver workflow runs server-side, then opens a `[RAPP]` issue with a structured submission payload. A maintainer (or the approval workflow) labels the issue `approved` and your rapp lands in [`index.json`](https://github.com/kody-w/rapp_store/blob/main/index.json).

Two submission modes:

| Mode | When to use | What ends up in the catalog |
|---|---|---|
| **BUNDLE** | You want the files to live in `kody-w/rapp_store` | Files copied to `rapp_store/<id>/`; `singleton_url` points at `kody-w/rapp_store/main/...` |
| **FEDERATION** | You want your own repo to remain the source of truth | Catalog gets an entry with `singleton_url` pointing at `raw.githubusercontent.com/<your-repo>` and a pinned `commit_sha`. Nothing is copied. |

Both modes run the same SPEC.md validation. Federation works because GitHub serves any public repo's raw files via a stable, anonymous CDN — no token, no API quota.

---

## Install

```bash
curl -L -o ~/.brainstem/src/rapp_brainstem/agents/publish_to_rapp_store_agent.py \
  https://raw.githubusercontent.com/kody-w/rapp_store/main/publish_to_rapp_store/singleton/publish_to_rapp_store_agent.py
```

Or use the binder agent: *"Install the publish_to_rapp_store rapplication."*

---

## Actions

```jsonc
// Pre-flight a local rapp (directory or .zip) against SPEC.md.
{ "action": "validate_local", "path": "/path/to/my_rapp" }

// Pre-flight a federated rapp at a public GitHub URL.
// Accepts: https://github.com/<owner>/<repo>
//          https://github.com/<owner>/<repo>/tree/<ref>/<subpath>
{ "action": "validate_repo", "repo_url": "https://github.com/alice/cool-rapps/tree/main/my_rapp" }

// Zip a local rapp dir (writes <id>-<version>.zip next to it).
{ "action": "bundle", "path": "/path/to/my_rapp" }

// Validate + open a [RAPP] issue with the bundle attached as base64.
{ "action": "submit_bundle", "path": "/path/to/my_rapp" }

// Validate + open a [RAPP] issue with a federation block (no files copied).
{ "action": "submit_repo", "repo_url": "https://github.com/alice/cool-rapps/tree/main/my_rapp" }

// Check whether your submission was approved.
{ "action": "status", "issue_number": 42 }

// Print the spec summary.
{ "action": "spec" }
```

`dry_run: true` prints what would be sent without actually opening an issue. Useful when you don't have a `GH_TOKEN` set yet and want to inspect the payload.

---

## Authentication

`submit_*` actions need a GitHub token in `GH_TOKEN` or `GITHUB_TOKEN`. A fine-grained personal access token with **public_repo: issues: write** is enough.

If no token is set, `submit_*` returns the constructed issue title/body/labels and tells you the URL to paste them into manually. The validation half still runs.

The submitter identity comes from (in order): the `submitter` parameter, the `GITHUB_ACTOR` env var, otherwise the publisher-identity check is skipped (validation still runs but doesn't enforce that `manifest.publisher` matches your GitHub login).

---

## Federation: how it works

Your rapp lives in `https://github.com/alice/cool-rapps/my_rapp/`:

```
cool-rapps/
  my_rapp/
    manifest.json
    index_entry.json
    README.md
    singleton/my_rapp_agent.py
    ui/index.html
```

You run:

```jsonc
{ "action": "submit_repo", "repo_url": "https://github.com/alice/cool-rapps/tree/main/my_rapp" }
```

The agent:
1. Fetches `https://raw.githubusercontent.com/alice/cool-rapps/main/my_rapp/manifest.json` (anonymous, no auth)
2. Fetches the singleton, runs the AST contract checks
3. Resolves `main` → a commit SHA via the public commits API
4. Computes SHA256 of the singleton bytes
5. Opens a `[RAPP]` issue with a `submission_type: federation` payload

On approval, the catalog gets:

```json
{
  "id": "my_rapp",
  "singleton_url": "https://raw.githubusercontent.com/alice/cool-rapps/main/my_rapp/singleton/my_rapp_agent.py",
  "singleton_sha256": "<computed at validation>",
  "source": {
    "type": "federation",
    "repo": "alice/cool-rapps",
    "ref": "main",
    "path": "my_rapp",
    "commit_sha": "<resolved>"
  }
}
```

Brainstems install from `singleton_url`. Their binder verifies the SHA256 — if you change `main` without resubmitting, installs fail with a clear mismatch error.

To publish a new version: bump `manifest.version` in your repo, push, then resubmit. The agent re-resolves the SHA and the catalog entry updates.

---

## License

BSD-style.

## Publisher

`@rapp`
