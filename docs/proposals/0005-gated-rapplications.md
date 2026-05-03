# Proposal 0005 — Gated Rapplications

| | |
|---|---|
| **Status** | Accepted (implemented in catalog `index.json` and as `@wildhaven/cockpit`) |
| **Sponsor** | @kody-w |
| **Drafted** | 2026-05-03 |
| **Touches** | `SPEC.md` §2, §3, §6, §7, new §12. `scripts/lib_rapp.py` (validator relaxations). `index.json` schema extended with `access` field. No brainstem changes — installers gain a 1-step PAT lookup before fetch. |
| **Complies with** | Article I (this repo defines the contract; brainstems implement it). Article XXXVII (rapplications are organisms). The Constitution's principle that engine IP and operator-private content stay out of public repos. |

## 1. Context

Today every rapplication in the catalog points its `singleton_url` /
`ui_url` / `service_url` at a public path on `raw.githubusercontent.com`.
Anyone who can reach the raw service can fetch the bytes. That is the
right default for the public catalog — the public catalog is for
discovery, and discovery requires reachable artifacts.

But many rapplications **shouldn't be world-fetchable**:

- The operator's own internal tools (a control plane for their fleet,
  a vault wrapper bound to a specific workspace).
- Engine IP that an organization wants to distribute internally but
  not to the open internet.
- Early-stage rapps an author wants discoverable by a small set of
  invited collaborators while still iterating.
- Customer-specific bundles built on top of an open base — where the
  base is public but the customization is not.

The pragmatic shape today is "fork the public catalog into a private
one." That works for substance but breaks discovery — the private
catalog exists in a separate world that nobody outside the gate knows
about. There's no way to tell someone "you should look at this
rapplication; here's its catalog page" without also handing them
the source.

The pattern wanted is **public discovery, private substance**: the
catalog publishes the existence and shape of the rapp; the source
lives somewhere only authorized users can fetch. The catalog and the
source are coupled by URL only — no custom auth code, no relay, no
new schema vocabulary.

## 2. The rule

A catalog entry MAY declare `access: "private"` and a
`private_repo: "<owner>/<repo>"`. When it does:

1. Every `*_url` field on the entry (`singleton_url`, `organ_url`,
   `ui_url`, `service_url`, `tools_url`, etc.) MUST point at a path on
   `raw.githubusercontent.com/<owner>/<repo>/<ref>/...` where
   `<owner>/<repo>` matches `private_repo` and the repo is private on
   GitHub.
2. Unauthenticated fetches against any such URL return HTTP 404. This
   is the gate — GitHub's raw service does it for free.
3. An installer that sees `access: "private"` MUST attach a
   `Authorization: Bearer <token>` header on every `*_url` fetch,
   where the token is a PAT (classic or fine-grained) with at least
   *Contents: read* on `private_repo`. With the header, the same URLs
   return 200 and install proceeds normally.
4. The integrity fields (`*_sha256`) on a gated entry are computed by
   the entry's author (the catalog has no way to recompute them
   because the catalog can't read the bytes). The installer verifies
   the fetched bytes against the entry's SHA after fetch.
5. A gated entry is otherwise a normal rapplication — the bundle
   shape (§1), the singleton contract (§4), the validation rules
   (§6) all still apply *to whoever holds the source repo*. The
   public-catalog validator validates only the metadata.

This is **federation Mode C** in §7's submission-paths taxonomy:
federation referencing a private repo, with the gate being GitHub's
own access control.

## 3. Why this lives in SPEC.md

The catalog stops being a discovery layer if every gated rapplication
has to invent its own access mechanism. By making `access` a
first-class field that installers know to honor, the catalog becomes
a uniform discovery layer for **everything** — public, private,
customer-scoped, org-scoped — with one schema and one auth pattern.

The pattern is also **substrate-aligned**. GitHub already runs the
auth layer (PATs with fine-grained scopes), the storage layer (private
repos), and the delivery layer (raw.githubusercontent.com). Building
on that gets us:

- No servers to operate.
- No relays to keep secure.
- No custom token formats.
- No new failure modes — the gate is exactly what GitHub already does
  for every private-repo fetch.

A maintainer who wants to revoke access for a person revokes their
collaborator status on the private repo. A consumer who loses their
PAT loses access automatically. Auth lifecycle is GitHub's problem.

## 4. What "private" means at the boundary

Three things, in order:

**At catalog read time.** `access: "private"` is a hint to the
installer. The catalog entry itself is public — anyone reading
`index.json` sees that the rapp exists, what it does, and where its
source claims to live. They just can't fetch the source.

**At fetch time.** The gate is GitHub's. The catalog does not enforce
the gate; it merely documents that one exists. An installer that
ignores `access: "private"` and tries to fetch the URL without a
token gets 404 and a sad-path message. An installer that respects
`access: "private"` and attaches a token gets 200 (if the token has
the right scope) or 404 (if it doesn't) — same outcome either way
when the user lacks access, because GitHub doesn't distinguish
"private" from "absent" for unauthorized callers.

**At install time.** Once fetched, a gated rapp is no different
from a public one. The brainstem hashes it, mounts it, registers it.
The brainstem does not retain the PAT. The brainstem does not need
to know the rapp was private — that was the installer's job.

## 5. What this is NOT

- It is **not** a content-protection scheme. A user who has access can
  trivially copy the source out. The gate is "did you have read
  access at fetch time," not "is this code unrunnable without a key."
  Use code signing or runtime DRM if you need the latter; nothing in
  this proposal does that.
- It is **not** a license. Whether a viewer of the source is allowed
  to use, modify, or redistribute it is a question for the rapp's
  `LICENSE` and the org's contributor agreements.
- It is **not** a multi-tier auth model. There's `public` and
  `private`. Org-scoped or team-scoped distinctions are expressed by
  repo membership on the private side, not by the catalog.

## 6. Worked example

The first gated rapplication is `@wildhaven/cockpit`, landed
2026-05-03. Its catalog presence:

```json
{
  "id": "cockpit",
  "manifest_name": "@wildhaven/cockpit",
  "access": "private",
  "private_repo": "kody-w/RAPP_Store_Private",
  "singleton_url": "https://raw.githubusercontent.com/kody-w/RAPP_Store_Private/main/apps/@wildhaven/cockpit/singleton/cockpit_agent.py",
  "singleton_sha256": "c77195ef84de42e4c1a13c509d0262e6c44c1ee2e27abcb26673bec40eb753ef"
}
```

Verified live: unauthenticated `curl` on the singleton URL → HTTP 404.
Authenticated `curl -H "Authorization: Bearer <pat>"` → HTTP 200,
SHA256 matches the catalog entry. The brainstem installs from the
authenticated bytes; nothing about the install path is special.

## 7. Open questions (small, non-blocking)

- **Multiple gates per entry?** A future entry could in principle
  point different `*_url` fields at different private repos. The
  current spec keeps it to one — `private_repo` is single-valued —
  because cross-repo dependency graphs are out of scope here.
- **GitHub-flavored only?** The pattern is generic over any storage
  service that 404s unauthorized requests. The current spec is
  GitHub-only because that's what the federation layer already uses.
  A future proposal could generalize to other hosts.
- **Catalog-level visibility filtering?** The vBrainstem surface
  could choose to dim or hide gated entries the user can't fetch.
  That's a presentation choice, not a spec one.
