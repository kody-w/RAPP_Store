# Planting Novell in the batcave

Novell is published to the RAPP store. The batcave cubby is **prepared but not
planted**, because the batcave itself is not published yet.

## Why this is not done

`examples/rapp-batcave` lives on the **local-only branch `add-rapp-batcave`** in
`kody-w/RAPP`. It is not on `main` and not on `origin` — `git ls-tree main` finds
no batcave, and there is no `remotes/origin/add-rapp-batcave`. The branch is
in-flight work held by a parallel session, and the cubby path is gated by
`examples/rapp-batcave/.github/CODEOWNERS` plus the `cubby-guard.yml` workflow.

Planting Novell would mean either committing into a contested checkout or pushing
somebody else's unpushed branch to origin. Both are Kody's call, not an
autonomous one. So the payload is staged here and the plant is one copy away.

## The payload

Novell drops into the existing `kody-w` cubby as a rapplication plus an egg:

```
examples/rapp-batcave/cubbies/kody-w/
  rapplications/novell/          <- copy the store bundle here
    manifest.json
    singleton/novell_agent.py
    ui/index.html
    README.md
    DOCTRINE.md
  eggs/novell.rapp.egg           <- copy from ../eggs/novell.rapp.egg
```

## Plant it

From a clean scratch clone (never the contested working checkout):

```bash
git clone ~/Documents/GitHub/RAPP /tmp/rapp-plant
cd /tmp/rapp-plant && git checkout add-rapp-batcave

SRC=~/Documents/GitHub/RAPP_Store/apps/@kody-w/novell
DST=examples/rapp-batcave/cubbies/kody-w

mkdir -p "$DST/rapplications/novell"
cp -R "$SRC"/{manifest.json,singleton,ui,README.md,DOCTRINE.md} "$DST/rapplications/novell/"
cp "$SRC/eggs/novell.rapp.egg" "$DST/eggs/"

git add "$DST" && git commit -m "batcave: plant Novell in the kody-w cubby"
```

## One thing to decide first

`cubby.json` entries carry a `rappid`. **Do not mint Novell's the way the store
generator does** — `scripts/build_pokedex_api.py:113` computes
`sha256("@kody-w/novell")[:32]`, which is the name-hash mint the estate's identity
law forbids (the comment there says the existing 32-hex values are
"grandfathered", but a *new* mint is fresh drift, not grandfathered).

Novell ships with **no rappid** on purpose. The store bundle and the `.egg` are
both lawful without one — `EGG_SPEC` does not require a rappid, and the catalog
entry does not either. Mint one only after the generator is fixed to derive
identity from content rather than from `owner/slug`.
