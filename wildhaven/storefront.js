(function (root) {
  'use strict';

  const labels = Object.freeze({
    prototype: 'Prototype', concept: 'In development', archived: 'Research archive', available: 'Released',
  });
  const categories = Object.freeze({
    efficiency: 'Efficiency', productivity: 'Productivity',
    infrastructure: 'Infrastructure', trust: 'Trust & quality',
  });
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const text = value => typeof value === 'string' && value.trim().length > 0;

  function validateCatalog(catalog) {
    if (!object(catalog) || !object(catalog.seller) || !text(catalog.seller.name)
        || !text(catalog.seller.maker) || typeof catalog.checkout_enabled !== 'boolean'
        || !Array.isArray(catalog.products)) throw new Error('Store product data is incomplete.');
    if (catalog.seller.inquiry_url !== 'https://github.com/kody-w/RAPP_Store/issues/new') {
      throw new Error('The store inquiry destination is not approved.');
    }
    const ids = new Set();
    for (const product of catalog.products) {
      if (!object(product) || !text(product.id) || !/^[a-z][a-z0-9-]*$/.test(product.id)
          || ids.has(product.id) || !Object.hasOwn(labels, product.status)
          || !Object.hasOwn(categories, product.category)
          || !['name', 'mark', 'summary', 'deliverable', 'limitations', 'platforms', 'license_note'].every(key => text(product[key]))
          || typeof product.sale_approved !== 'boolean' || typeof product.delivery_configured !== 'boolean') {
        throw new Error('A product has missing, duplicate, or unsupported metadata.');
      }
      ids.add(product.id);
    }
    return catalog;
  }

  function hostedCheckout(value) {
    if (!text(value)) return null;
    let url;
    try { url = new URL(value); }
    catch (error) {
      if (!(error instanceof TypeError)) throw error;
      return null;
    }
    if (url.protocol !== 'https:' || url.username || url.password || url.port || url.hash) return null;
    const stripe = url.hostname === 'buy.stripe.com' && /^\/[A-Za-z0-9_]+$/.test(url.pathname);
    const gumroad = /^[a-z0-9-]+\.gumroad\.com$/.test(url.hostname) && /^\/l\/[A-Za-z0-9_-]+$/.test(url.pathname);
    const lemon = /^[a-z0-9-]+\.lemonsqueezy\.com$/.test(url.hostname) && /^\/buy\/[A-Za-z0-9-]+$/.test(url.pathname);
    return stripe || gumroad || lemon ? url.href : null;
  }

  function purchaseInfo(product, catalog, entries, contract) {
    const refused = reason => ({enabled: false, href: null, label: 'Not for sale', reason});
    if (!catalog.checkout_enabled) return refused('Paid checkout is not open yet.');
    if (product.status !== 'available') return refused('This preview or archive is not a released product.');
    if (!product.sale_approved || !product.delivery_configured) {
      return refused('Seller approval and configured customer delivery are required.');
    }
    const entry = entries.find(item => item.id === product.catalog_id);
    if (!entry || entry.version !== product.version || !contract.canInstall(entry)) {
      return refused('No matching installable release has been admitted to the RAPP Store.');
    }
    const href = hostedCheckout(product.checkout_url);
    if (!href) return refused('A valid hosted merchant checkout link is required.');
    const price = product.price;
    if (!object(price) || !Number.isSafeInteger(price.amount_minor) || price.amount_minor <= 0
        || price.currency !== 'USD' || !['once', 'month', 'year'].includes(price.interval)) {
      return refused('Approved USD pricing and its billing interval are required.');
    }
    const amount = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'})
      .format(price.amount_minor / 100);
    const label = amount + (price.interval === 'once' ? ' one-time' : ' / ' + price.interval);
    return {enabled: true, href, label, reason: 'The merchant handles payment and the configured delivery.'};
  }

  function filterProducts(products, query, category) {
    if (typeof query !== 'string' || typeof category !== 'string'
        || category !== 'all' && !Object.hasOwn(categories, category)) {
      throw new Error('Unsupported product search or category.');
    }
    const needle = query.trim().toLowerCase();
    return products.filter(product => (category === 'all' || product.category === category)
      && [product.name, product.summary, product.deliverable, categories[product.category]]
        .some(value => value.toLowerCase().includes(needle)));
  }

  const api = {validateCatalog, hostedCheckout, purchaseInfo, filterProducts};
  root.WildhavenStore = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;

  let catalog = null;
  let entries = [];
  let loadError = null;
  let visible = [];
  const byId = id => document.getElementById(id);
  const contract = root.RappStoreContract;
  function node(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = value;
    return element;
  }
  function lookup(id) {
    if (!catalog) throw new Error('Product data is not ready.');
    const product = catalog.products.find(item => item.id === id);
    if (!product) throw new Error('Unknown product.');
    return product;
  }
  function inquire(product) {
    const url = new URL(catalog.seller.inquiry_url);
    url.searchParams.set('title', 'Wildhaven tool inquiry: ' + product.name);
    url.searchParams.set('body', 'I am interested in ' + product.name
      + '.\n\nMy workflow or question:\n\n'
      + 'This is a public inquiry, not a purchase. Do not include credentials, payment details, or private files.');
    return url.href;
  }
  function details(product) {
    const info = purchaseInfo(product, catalog, entries, contract);
    const content = byId('details-content');
    content.replaceChildren();
    content.appendChild(node('span', 'badge ' + product.status, labels[product.status]));
    const title = node('h2', '', product.name);
    title.id = 'details-title';
    content.appendChild(title);
    for (const [heading, value] of [
      ['The idea', product.summary], ['What exists today', product.deliverable],
      ['Before a customer release', product.limitations], ['Platforms', product.platforms],
      ['Customer license', product.license_note], ['Purchase status', info.reason],
    ]) {
      content.appendChild(node('h3', '', heading));
      content.appendChild(node('p', '', value));
    }
    const action = node('a', 'button primary', info.enabled ? 'Buy - ' + info.label : 'Ask about this tool');
    action.href = info.enabled ? info.href : inquire(product);
    content.appendChild(action);
    content.appendChild(node('p', 'disclosure', info.enabled
      ? 'You are leaving this storefront for the merchant checkout. Review its delivery, billing, and refund terms before paying.'
      : 'Opens a public GitHub inquiry. No payment is collected and no early-access entitlement is promised.'));
    byId('product-details').showModal();
  }
  function render() {
    visible = filterProducts(catalog.products, byId('product-search').value, byId('product-category').value);
    const grid = byId('product-grid');
    grid.replaceChildren();
    for (const product of visible) {
      const card = node('article', 'product-card');
      card.dataset.product = product.id;
      const top = node('div', 'card-top');
      const mark = node('span', 'tool-mark', product.mark);
      mark.setAttribute('aria-hidden', 'true');
      top.append(mark, node('span', 'badge ' + product.status, labels[product.status]));
      card.append(top, node('h3', '', product.name), node('p', 'summary', product.summary),
        node('p', 'category-label', categories[product.category]));
      const info = purchaseInfo(product, catalog, entries, contract);
      const bottom = node('div', 'card-bottom');
      bottom.appendChild(node('span', '', info.label));
      const button = node('button', 'details-button', 'View details');
      button.type = 'button';
      button.setAttribute('aria-label', 'View details for ' + product.name);
      button.addEventListener('click', () => details(product));
      bottom.appendChild(button);
      card.appendChild(bottom);
      grid.appendChild(card);
    }
    byId('result-count').textContent = visible.length + ' of ' + catalog.products.length + ' tools';
    byId('empty-state').hidden = visible.length !== 0;
    grid.setAttribute('aria-busy', 'false');
  }

  root.wildhavenStore = Object.freeze({
    status: () => ({
      ready: catalog !== null, error: loadError, seller: catalog ? catalog.seller.name : null,
      products: catalog ? catalog.products.length : 0, visible: visible.length,
      purchasable: catalog ? catalog.products.filter(product => purchaseInfo(product, catalog, entries, contract).enabled).length : 0,
    }),
    search: (query, category = 'all') => {
      if (!catalog) throw new Error('Product data is not ready.');
      const result = filterProducts(catalog.products, query, category);
      byId('product-search').value = query;
      byId('product-category').value = category;
      render();
      return result.map(product => product.id);
    },
    inspect: id => {
      const product = lookup(id);
      details(product);
      return {product, purchase: purchaseInfo(product, catalog, entries, contract)};
    },
    purchase: id => {
      const info = purchaseInfo(lookup(id), catalog, entries, contract);
      if (!info.enabled) throw new Error(info.reason);
      root.location.assign(info.href);
      return {destination: info.href};
    },
  });

  async function load() {
    if (!contract) throw new Error('The RAPP Store contract could not be loaded.');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    const read = async url => {
      const response = await fetch(url, {credentials: 'omit', signal: controller.signal});
      if (!response.ok) throw new Error('Store data could not be loaded (' + response.status + ').');
      return contract.parseJSON(await response.text());
    };
    try {
      const [products, store] = await Promise.all([
        read('wildhaven/products.json'), read('index.json'), contract.ready(),
      ]);
      validateCatalog(products);
      if (store.schema !== 'rapp-store/1.0' || !Array.isArray(store.rapplications)) {
        throw new Error('The canonical RAPP Store catalog is unavailable.');
      }
      entries = store.rapplications;
      catalog = products;
      byId('product-search').addEventListener('input', render);
      byId('product-category').addEventListener('change', render);
      render();
      const available = root.wildhavenStore.status().purchasable;
      byId('store-state').textContent = available ? 'Hosted checkout available' : 'Developer preview';
      byId('store-notice').textContent = available
        ? 'Only qualified releases with approved merchant links can be purchased. Previews and archives remain unavailable.'
        : 'These are product previews, not ten finished releases. Paid checkout is not open yet; explore details or make a public inquiry.';
    } finally {
      clearTimeout(timer);
    }
  }
  load().catch(error => {
    loadError = error.message;
    catalog = null;
    entries = [];
    visible = [];
    byId('product-grid').replaceChildren();
    byId('product-grid').setAttribute('aria-busy', 'false');
    byId('store-error').hidden = false;
    byId('store-error').textContent = 'The storefront is unavailable: ' + error.message + ' No purchase links are enabled.';
    byId('store-state').textContent = 'Store unavailable';
    byId('store-notice').textContent = 'Product data could not be verified. No purchase links are enabled.';
    byId('result-count').textContent = 'Product data unavailable';
    console.error('Wildhaven storefront:', error);
  });
})(globalThis);
