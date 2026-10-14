# Wildhaven Homes LLC storefront

The public seller showroom is `wildhaven/index.html`, served by the existing
RAPP Store GitHub Pages site:

<https://kody-w.github.io/RAPP_Store/wildhaven/>

It is original storefront code, not a copy of Cloudroom's marketing site.
Cloudroom's Apache-2.0 core is an optional, separate private agent backend.
Neither a Cloudroom account nor a running agent server is required to browse
this page.

## What is live

- Ten product candidates, with prototype, concept, or research-archive labels.
- Workflow search, category filtering, and product detail dialogs.
- Actual deliverable, limitations, platform status, and licensing notes.
- Public inquiry links; opening the editor does not submit an issue.
- A link to the already-cataloged Wildhaven workspace application.
- Hosted-checkout routing, disabled until a qualified offer is configured.

The earlier discovery catalog's scores and proposed prices are not readiness
certificates, approved commercial terms, or evidence of demand. A wrapper
component is not automatically an independently released product.

This seller metadata is **not** a rapplication submission, catalog admission,
quality promotion, or extension of RAPP/1. `index.json`, published eggs,
singletons, catalog integrity pins, and the receiver/approval flow are unchanged.

## Enabling a real paid offer

Keep `wildhaven/products.json` free of credentials. It contains public product
copy and hosted merchant links only.

For an individual paid product:

1. Publish a qualified complete application through the existing `[RAPP]`
   receiver and approval flow. The canonical entry must pass the existing
   `RappStoreContract.canInstall` check; no singleton fallback is accepted.
2. Confirm customer license terms, prerequisites, support/refund terms, and
   the exact digital deliverable. Configure those in the merchant's account.
   For hosted digital delivery, attach the qualified package there.
3. Set `catalog_id` and `version` to the exact admitted release. Mark the
   product `status: "available"`, `sale_approved: true`, and
   `delivery_configured: true` only when those facts are true.
4. Supply its public hosted `checkout_url` and approved `price`, for example
   `{"amount_minor": 2900, "currency": "USD", "interval": "once"}`.
   Intervals are `once`, `month`, or `year`; this example is not an approved
   price. Recognized links are Stripe Payment Links, Gumroad product links,
   and Lemon Squeezy buy links over HTTPS.
5. Set the store-level `checkout_enabled` to `true`. Exercise the real
   provider checkout in its authorized test mode, then independently confirm
   live configuration and delivery before claiming that purchases work.

The storefront cannot create merchant accounts, verify their ownership, apply
tax settings, grant private GitHub access, or prove that a remote seller has
uploaded the promised files. A public link is not proof of entitlement or
successful fulfillment. Those responsibilities belong to the merchant
integration, not a static page or an agent runtime.

No private payment integration or merchant account was configured by this
change. No test charges or real purchases were made.

## Privacy and Cloudroom

The page makes same-origin requests for product and canonical catalog data.
It has no analytics, customer database, account creation, or payment fields.
Checkout leaves the site for the configured merchant. GitHub inquiries are
public; do not enter private information.

Official Cloudroom source:
<https://github.com/davidondrej/cloudroom-core>, Apache License 2.0.
The source was cloned for evaluation; this storefront does not redistribute
or embed its runtime. Cloudroom does not supply ecommerce or a custom shop on
`cloudroom.dev`. Its API requires private authentication and must never be
exposed to storefront visitors.

Cloudroom setup instructions are upstream. A new Linux service installation,
account provisioning, harness authentication, and production history/storage
configuration were not performed here. Do not silently turn on model-spending
agent jobs in response to a checkout click.

## Operator and agent checks

The static page exposes a bounded, public semantic API:

```javascript
wildhavenStore.status()
wildhavenStore.search("quota", "all")
wildhavenStore.inspect("ai-dyno")
wildhavenStore.purchase("ai-dyno")
```

`purchase` uses the same release and merchant checks as the UI. It throws an
explicit error when unavailable; it is not a bypass or a proof of payment.
`inspect` opens the normal detail dialog and returns public product metadata.

Run the focused regressions:

```text
python -m pytest tests\test_wildhaven_storefront.py tests\test_desktop_ui.py -q
node --check wildhaven\storefront.js
```

On Windows, use `PYTHONUTF8=1` for the existing UTF-8 storefront fixtures.
The existing complete-application filesystem validator additionally uses
POSIX-only directory flags, so its Linux CI result remains necessary.
