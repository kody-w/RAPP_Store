# Proposal 0004 — Per-Rapp Workspaces

| | |
|---|---|
| **Status** | Draft |
| **Sponsor** | @kody-w |
| **Drafted** | 2026-04-28 |
| **Touches** | `SPEC.md` §11 (new). `kody-w/RAPP` brainstem (binder install hook, `utils/workspace.py`, cartridge protocol, optional UI drawer). No catalog/data-shape changes. |
| **Complies with** | Article I (this repo defines the contract; brainstem implements it). Article XVI of the platform constitution (engine surface vs. workspace). |

## 1. Context

When a user drops a rapplication onto a local brainstem, the rapp gets installed (singleton hashed, mounted, registered) but has no persistent place to **collaborate with the user via files**. Today a rapp has three options, all bad:

1. Pass everything as text args through `perform(**kwargs)` — fine for short prompts, hostile for CSVs, PDFs, transcripts, audio.
2. Write to the brainstem's repo root or `.brainstem_data/<name>.json` (the existing services convention) — but `.json` is the wrong shape for blobs, and writing directly to repo root pollutes the engine's working tree (Article XVI).
3. Ask the user to paste content into the UI's textarea — works for vault docs (WildhavenCEO), breaks for anything binary or large.

There is also no surface for the *rapp* to ask the user to *put a file somewhere*. BookFactory wants a transcript. SpineDAG wants a folder. WildhavenCEO wants a vault dump. Each one currently solves this differently inside its UI.

The pattern across all of these is the same: **per-rapp, per-install, persistent file scratchpad**. This proposal carves that out as a first-class platform feature.

## 2. The rule

Every installed rapplication on a local brainstem gets a **workspace directory**:

```
${BRAINSTEM_ROOT}/.brainstem_data/workspaces/<id>/
```

- Created by the binder on install (mode A or mode B — same behavior).
- Preserved on uninstall (user data, not engine data).
- Preserved across version upgrades (same `<id>` keeps the same dir).
- Isolated per rapp — one rapp cannot read or write into another's workspace.
- Path-traversal guarded — no `..` segments in any workspace operation.

The rapp accesses its workspace through three host-mediated surfaces:

**Agent (Python).** The brainstem provides `from utils.workspace import workspace_dir`. Calling `workspace_dir()` from within a singleton's `perform()` returns the absolute `Path` for that rapp's workspace, or `None` if running outside a tethered brainstem (cloud / standalone). The host infers the rapp identity from the calling agent's `__manifest__`.

**UI (cartridge).** The cartridge envelope (SPEC §9.1) gains a `context.workspace` block. The UI gets new message types: `rapp:workspace:list`, `rapp:workspace:read`, `rapp:workspace:write`, `rapp:workspace:request_files`, `rapp:workspace:open_in_finder`. All mediated by the parent — the UI never touches the fs.

**User (brainstem UI).** The brainstem renders a "Workspace" affordance per installed rapp: drop zone, file list, "open in Finder" (local only), and an inbox of outstanding `request_files` prompts the rapp has issued.

The full wire contract lives in SPEC §11.

## 3. Why a directory per rapp, not a shared one

A shared workspace creates two problems:

- **Cross-contamination.** WildhavenCEO's vault docs would be visible to BookFactory, which needs to be impossible by construction. If users are going to drop legal/financial/private docs in, the per-rapp dir is the trust boundary.
- **Naming collisions.** Two rapps both want `transcript.txt`. With per-rapp dirs, no negotiation needed.

The cost is a few extra directories on disk. Negligible.

## 4. Why not just use the existing `.brainstem_data/<name>.json` pattern

That pattern is for **rapp-private state the user doesn't touch** (kanban board JSON, dashboard config). A workspace is **collaborative** — the user actively drops files in, and the rapp reads them. Different shape, different surface. The `.json` convention stays for state; workspaces are additive.

## 5. Why workspace requests are first-class

When BookFactory needs a transcript, the user shouldn't have to read the README to find out where to put it. The rapp posts `rapp:workspace:request_files` with a prompt and the brainstem UI surfaces it: *"BookFactory is asking for a `.txt` or `.md` file named `transcript`."* The user drags one in; the request resolves; the rapp reruns.

This turns the rapp into a participant in a file-based conversation rather than a black box that fails when its inputs are wrong.

## 6. Implementation

This is a doc-only change in *this* repo:

- New `SPEC.md` §11 — Workspace contract.
- New `docs/proposals/0004-per-rapp-workspaces.md` — this file.
- One-line mention under the `.brainstem_data` reference in `CLAUDE.md`.

The companion engine PR in `kody-w/RAPP`:

1. Binder install hook creates `.brainstem_data/workspaces/<id>/` if absent. Uninstall does **not** remove it. (Distinct from the existing `.brainstem_data/<id>/` directory used for rapp-private state and bundled into eggs as `state/...`.)
2. `utils/workspace.py` exposes `workspace_dir()` (resolved from the calling frame's module → singleton manifest). Path-traversal guards on all writes.
3. Brainstem's chat host (the cartridge bridge in the binder UI mount) handles the new `rapp:workspace:*` messages — list/read/write go straight to disk under the resolved path; `open_in_finder` shells out (local only); `request_files` writes to a small JSON queue under the workspace's `.requests/` dir.
4. Brainstem UI gets a Workspace drawer per rapp panel — drop zone, file list, requests inbox.

Cloud mode (vBrainstem at `kody-w.github.io/RAPP_Store/vbrainstem.html`) gets a session-scoped IndexedDB-backed in-memory workspace with the same wire shape. Files don't persist past the tab — that's fine, cloud mode is ephemeral by design.

## 7. Backwards compatibility

The cartridge envelope's `context.workspace` block is additive — UIs that don't read it keep working. Rapps that don't import `utils.workspace` keep working. The brainstem's old `.brainstem_data/<name>.json` convention is unchanged.

## 8. Rollback

Revert this proposal + the SPEC §11 section. The engine PR is rollbackable independently — workspace dirs left behind are user data, not engine state, and the binder simply stops creating new ones.

## 9. References

- [Article I](../../CONSTITUTION.md) — this repo defines the contract; engine work belongs upstream.
- [SPEC §9 — Cartridge protocol](../../SPEC.md#9-cartridge-protocol-rapp-uis-↔-parent-runtime) — the message bus this extends.
- Platform Article XVI — engine surface vs. brainstem workspace.
- Existing convention: `.brainstem_data/<name>.json` (services rapp-private state).
