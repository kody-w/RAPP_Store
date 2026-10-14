"""The seller showroom never turns a proposal or broken release into a purchase."""
import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

import lib_rapp
from test_application_contract import complete_application


ROOT = Path(__file__).resolve().parent.parent
CATALOG = json.loads((ROOT / "wildhaven" / "products.json").read_text(encoding="utf-8"))


def evaluate(request):
    node = shutil.which("node")
    assert node, "Node is required to exercise the real storefront module"
    script = r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const contract = require(input.contract);
if (input.action === 'load-failure') {
  const nodes = {};
  globalThis.document = {getElementById: id => nodes[id] || (nodes[id] = {
    hidden: true, textContent: '', replaceChildren() {}, setAttribute() {},
  })};
  globalThis.fetch = async () => ({ok: false, status: 503});
  console.error = () => {};
  require(input.module);
  setImmediate(() => console.log(JSON.stringify({
    status: wildhavenStore.status(), error: nodes['store-error'],
    notice: nodes['store-notice'].textContent,
  })));
} else {
const store = require(input.module);
let result;
if (input.action === 'filter') {
  result = store.filterProducts(input.catalog.products, input.query, input.category).map(p => p.id);
} else if (input.action === 'validate') {
  try { store.validateCatalog(input.catalog); result = {ok: true}; }
  catch (error) { result = {error: error.message}; }
} else {
  result = store.purchaseInfo(input.product, input.catalog, input.entries, contract);
}
console.log(JSON.stringify(result));
}
"""
    result = subprocess.run(
        [node, "-e", script],
        input=json.dumps({
            "module": str(ROOT / "wildhaven" / "storefront.js"),
            "contract": str(ROOT / "store-contract.js"),
            "catalog": CATALOG, "entries": [], **request,
        }),
        text=True, capture_output=True, check=True, timeout=15,
    )
    return json.loads(result.stdout)


def sale(complete_application):
    _, manifest = complete_application
    entry = lib_rapp.build_index_entry(manifest, {}, manifest["id"])
    entry.update(
        installable=True, install_blockers=[], package_sha256="a" * 64, hatcher_sha256="b" * 64,
        egg_url="https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/egg/test-" + "a" * 64 + ".egg",
        hatcher_url="https://raw.githubusercontent.com/kody-w/RAPP_Store/main/api/v1/hatcher/test_" + "b" * 64 + "_hatcher_agent.py",
    )
    catalog = copy.deepcopy(CATALOG)
    catalog["checkout_enabled"] = True
    product = copy.deepcopy(catalog["products"][0])
    product.update(
        status="available", sale_approved=True, delivery_configured=True,
        catalog_id=entry["id"], version=entry["version"],
        price={"amount_minor": 2900, "currency": "USD", "interval": "once"},
        checkout_url="https://buy.stripe.com/SyntheticExample",
    )
    return product, catalog, entry


def test_current_showroom_validates_and_cannot_sell_any_candidate():
    assert evaluate({"action": "validate"}) == {"ok": True}
    for product in CATALOG["products"]:
        result = evaluate({"product": product})
        assert result["enabled"] is False
        assert result["href"] is None
        assert result["reason"]


def test_checkout_requires_an_installable_catalog_release(complete_application):
    product, catalog, entry = sale(complete_application)
    result = evaluate({"product": product, "catalog": catalog, "entries": [entry]})
    assert result["enabled"] is True
    assert result["href"] == product["checkout_url"]
    assert result["label"] == "$29.00 one-time"
    entry["hatcher_sha256"] = "c" * 64
    refused = evaluate({"product": product, "catalog": catalog, "entries": [entry]})
    assert refused["enabled"] is False
    assert "installable release" in refused["reason"]


@pytest.mark.parametrize("change", [
    lambda p, c, e: c.update(checkout_enabled=False),
    lambda p, c, e: p.update(status="prototype"),
    lambda p, c, e: p.update(sale_approved=False),
    lambda p, c, e: p.update(delivery_configured=False),
    lambda p, c, e: p.update(version="999.0.0"),
    lambda p, c, e: p.update(catalog_id="not-admitted"),
    lambda p, c, e: p.update(price=None),
    lambda p, c, e: p.update(price={"amount_minor": -1, "currency": "USD", "interval": "once"}),
    lambda p, c, e: e.update(installable=False),
])
def test_missing_approval_delivery_or_release_cannot_enable_sales(complete_application, change):
    product, catalog, entry = sale(complete_application)
    change(product, catalog, entry)
    result = evaluate({"product": product, "catalog": catalog, "entries": [entry]})
    assert not result["enabled"]
    assert result["href"] is None
    assert result["reason"]


@pytest.mark.parametrize("url", [
    None, "javascript:alert(1)", "http://buy.stripe.com/SyntheticExample",
    "https://buy.stripe.com.evil.example/SyntheticExample",
    "https://owner@buy.stripe.com/SyntheticExample",
    "https://buy.stripe.com:8443/SyntheticExample",
    "https://buy.stripe.com/SyntheticExample#hidden",
    "https://example.com/checkout",
])
def test_purchase_never_routes_to_unapproved_checkout(complete_application, url):
    product, catalog, entry = sale(complete_application)
    product["checkout_url"] = url
    result = evaluate({"product": product, "catalog": catalog, "entries": [entry]})
    assert not result["enabled"]
    assert result["href"] is None
    assert "checkout link" in result["reason"]


def test_search_finds_workflow_text_and_respects_category():
    result = evaluate({"action": "filter", "query": "quota", "category": "all"})
    assert result == ["ai-dyno"]
    assert evaluate({"action": "filter", "query": "quota", "category": "trust"}) == []
    assert evaluate({"action": "filter", "query": "unfinished", "category": "productivity"}) == ["raptr-finisher"]


@pytest.mark.parametrize("change", [
    lambda c: c["products"].append(copy.deepcopy(c["products"][0])),
    lambda c: c["products"][0].update(status="certified"),
    lambda c: c["products"][0].pop("limitations"),
    lambda c: c["seller"].update(inquiry_url="https://example.com/collect"),
])
def test_invalid_public_metadata_is_reported_instead_of_rendered(change):
    catalog = copy.deepcopy(CATALOG)
    change(catalog)
    assert evaluate({"action": "validate", "catalog": catalog}).get("error")


def test_failed_catalog_load_surfaces_an_error_and_leaves_no_purchase_state():
    result = evaluate({"action": "load-failure"})
    assert result["status"]["ready"] is False
    assert result["status"]["purchasable"] == 0
    assert "503" in result["status"]["error"]
    assert result["error"]["hidden"] is False
    assert "No purchase links are enabled" in result["error"]["textContent"]
    assert "could not be verified" in result["notice"]
