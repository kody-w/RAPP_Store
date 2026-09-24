# Public inputs and materialization

This is an experimental source template, not an installed application or fresh-device acceptance certificate. Use the complete feature-gated Store installer; never install only the singleton agent.

Applications execute locally in Docker. Intelligence uses the official Copilot CLI with cloud inference and adopter-supplied private authentication. No account, token, runtime identity, application output or private session archive is supplied by this template.

From the installed layout, inspect without effects:

```sh
python singleton/scotty_support_3d47c4537516d094aef2bde15ee014ea0721c4cbef0321254cf3b2a6ebc2d6e3/deploy/local/materialize.py --app all
```

Materialize explicitly once, selecting the same private `materialize` directory under the controller's configured Dock home:

```sh
python singleton/scotty_support_3d47c4537516d094aef2bde15ee014ea0721c4cbef0321254cf3b2a6ebc2d6e3/deploy/local/materialize.py --app all --materialize --cache "$RAPP_DOCK_HOME/materialize"
```

Docker Desktop and its installed BuildKit/buildx plugin are required. The public Docker configuration does not inherit registry credentials. Verified existing IDs are reused; registry pulls use exact digests. Derived images are built from locked public bases and source, with actual IDs recorded in `materialized-images.json`. A derived tag is not a published registry artifact and rebuilt bytes are not promised to be identical. Jobs only inspect these identities and retain `pull_policy: never`. No image is deleted.

`--build --component NAME` explicitly replays a public build without replacing an existing image. `--fetch-artifact NAME --cache PATH` fetches a named locked release/source archive only. Corrupt cache entries, wrong platforms, unknown inputs and mismatching source or image identities refuse rather than repin.

The OpenShorts preparation helpers, public source, Debian/model pins and SHA-256/SHA-512 dependency manifests are carried. Frontend and renderer npm compilation occurs inside network-disabled builds, not on the host. Their direct public npm transport and the backend's PyPI transport failed on the reference Mac; cached qualification images remain usable only when their exact IDs are present. No NAS/session workaround is attempted. Read the exact per-component blockers in `components.lock.json` and `generated/materialization.json`; new-machine jobs remain unqualified.

Upstream licenses and notices are retained in the scoped support. Historical private execution proofs were omitted, not redacted and reidentified. The new capability lock and synthetic closure evidence identify these new bytes. Canonical RAPP/1 resources are unchanged; their public protocol-authority references are not adopter identities.
