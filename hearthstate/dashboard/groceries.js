const els = {
  list: document.querySelector('#groceryList'), empty: document.querySelector('#emptyState'), error: document.querySelector('#errorBanner'),
  theme: document.querySelector('#themeToggle'), refresh: document.querySelector('#refreshButton'), refreshColes: document.querySelector('#refreshColes'),
  budgetForm: document.querySelector('#budgetForm'), budgetInput: document.querySelector('#budgetInput'), quickAddForm: document.querySelector('#quickGroceryForm'), quickAddInput: document.querySelector('#quickGroceryName'),
  sync: document.querySelector('#syncStatus'), itemCount: document.querySelector('#itemCount'), pricedTotal: document.querySelector('#pricedTotal'),
  budgetTotal: document.querySelector('#budgetTotal'), unknownCount: document.querySelector('#unknownCount'), remainingTotal: document.querySelector('#remainingTotal'),
  budgetStatus: document.querySelector('#budgetStatus'), remainingStatus: document.querySelector('#remainingStatus'), budgetSignal: document.querySelector('#budgetSignal'),
  budgetSignalNote: document.querySelector('#budgetSignalNote'), updatedAt: document.querySelector('#updatedAt'),
  comparison: document.querySelector('#retailerComparison'), comparisonNote: document.querySelector('#comparisonNote'), bestDeals: document.querySelector('#bestDeals'),
};
const escapeHTML = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
const money = (value) => value == null ? '—' : new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD' }).format(value);

function syncTheme() {
  const dark = document.documentElement.dataset.theme === 'dark';
  els.theme.setAttribute('aria-pressed', String(dark));
  els.theme.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
  els.theme.textContent = dark ? '☀' : '☾';
  const meta = document.querySelector('meta[name="theme-color"]'); if (meta) meta.content = dark ? '#1d1917' : '#f3ede3';
}
function setTheme(theme) { document.documentElement.dataset.theme = theme; try { localStorage.setItem('hearthstate-theme', theme); } catch (error) {} syncTheme(); }
function checkedLabel(value) {
  if (!value) return '';
  const raw = String(value);
  const parsed = new Date(raw.length === 10 ? `${raw}T12:00:00` : raw);
  if (Number.isNaN(parsed.getTime())) return '';
  return `Checked ${new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' }).format(parsed)}`;
}
function unitLabel(item) { return `${item.quantity === 1 ? '' : `${item.quantity} `}${item.unit || 'each'}`; }
function quantityValue(item) {
  const quantity = Number(item.quantity);
  if (!Number.isFinite(quantity) || quantity <= 0) return '1';
  return Number.isInteger(quantity) ? String(quantity) : String(quantity);
}
function renderQuantityEditor(item) {
  return `<form class="quantity-form" data-item-id="${item.id}"><label for="quantity-${item.id}">Qty</label><div><input id="quantity-${item.id}" name="quantity" type="number" min="0.01" step="0.01" value="${quantityValue(item)}" inputmode="decimal" required /><span>${escapeHTML(item.unit || 'each')}</span><button type="submit">Save</button></div></form>`;
}

function trustedPriceURL(value) {
  try {
    const url = new URL(String(value || ''));
    if (url.protocol !== 'https:' || url.username || url.password || url.port) return '';
    const host = url.hostname.toLowerCase();
    const belongsTo = (domain) => host === domain || host.endsWith(`.${domain}`);
    if (belongsTo('coles.com.au') || belongsTo('woolworths.com.au')) return url.href;
  } catch (error) {}
  return '';
}

function retailerFromPrice(item) {
  const confidence = String(item.price_confidence || '').trim().toLowerCase();
  const source = String(item.price_source || '').trim();
  if (confidence === 'manual' || source.toLowerCase().startsWith('manual')) return null;
  const safeURL = trustedPriceURL(item.price_url);
  if (!safeURL) return null;
  try {
    const host = new URL(safeURL).hostname.toLowerCase();
    const belongsTo = (domain) => host === domain || host.endsWith(`.${domain}`);
    if (belongsTo('coles.com.au')) return 'Coles';
    if (belongsTo('woolworths.com.au')) return 'Woolworths';
  } catch (error) {}
  return null;
}

function confidenceLabel(price, retailer) {
  if (price?.confidence === 'live') return 'Live';
  if (price?.confidence === 'curated') return 'Curated';
  return retailer || 'Unknown';
}

function renderRetailerPrices(item) {
  const prices = item.retailer_prices || {};
  return `<div class="retailer-price-grid" aria-label="Store prices">${['coles', 'woolworths'].map((retailer) => {
    const price = prices[retailer] || {};
    const safeURL = trustedPriceURL(price.url);
    const label = price.retailer_label || (retailer === 'coles' ? 'Coles' : 'Woolworths');
    const value = price.line_total != null ? money(price.line_total) : 'Unknown';
    const detail = price.price != null ? `${money(price.price)} each${price.size_match === 'closest' ? ' · closest pack' : ''}` : 'No safe match';
    const source = safeURL ? `<a href="${escapeHTML(safeURL)}" target="_blank" rel="noreferrer">${escapeHTML(price.title || 'View product')}</a>` : `<span>${escapeHTML(price.title || 'No safe match')}</span>`;
    const freshness = price.stale ? ' · stale' : price.observed_at ? ` · ${escapeHTML(checkedLabel(price.observed_at))}` : '';
    return `<div class="retailer-price ${price.matched ? '' : 'is-unknown'} ${price.stale ? 'is-stale' : ''}"><div><strong>${escapeHTML(label)}</strong><span class="price-badge ${price.confidence === 'live' ? 'is-live' : price.confidence === 'curated' ? 'is-curated' : 'is-unknown'}">${escapeHTML(confidenceLabel(price, label))}</span></div><strong>${value}</strong><small>${escapeHTML(detail)}${freshness}</small><small>${source}</small></div>`;
  }).join('')}</div>${item.retailer_savings > 0 ? `<div class="retailer-savings">Save ${money(item.retailer_savings)} at ${escapeHTML(item.cheapest_retailer_label)} for this item</div>` : ''}`;
}

function renderItem(item) {
  const priced = item.price != null;
  const source = item.price_source || '';
  const observedRetailer = retailerFromPrice(item);
  const confidence = String(item.price_confidence || '').trim().toLowerCase();
  const safePriceURL = trustedPriceURL(item.price_url);
  const priceDetail = priced
    ? `<div class="grocery-price"><strong>${money(item.line_total)}</strong><span>${item.quantity === 1 ? money(item.price) : `${money(item.price)} each`}</span></div>`
    : `<div class="grocery-price unknown-price"><strong>Unknown</strong><span>Not counted</span></div>`;
  const provenance = priced
    ? `<div class="price-provenance"><span class="price-badge ${confidence === 'live' ? 'is-live' : confidence === 'curated' ? 'is-curated' : 'is-manual'}">${confidence === 'live' ? 'Live' : observedRetailer || 'Manual'}</span>${safePriceURL ? `<a href="${escapeHTML(safePriceURL)}" target="_blank" rel="noreferrer">${escapeHTML(source)}</a>` : `<span>${escapeHTML(source)}</span>`}<small>${escapeHTML(checkedLabel(item.price_checked_at))}${item.price_note ? ` · ${escapeHTML(item.price_note)}` : ''}</small></div>`
    : `<form class="quick-price-form" data-item-id="${item.id}"><label>Set a price</label><div><span>$</span><input name="price" type="number" min="0" step="0.01" placeholder="0.00" required /><button type="submit">Save</button></div></form>`;
  return `<article class="grocery-record"><div class="grocery-check" aria-hidden="true"></div><div class="grocery-record-main"><div class="grocery-name-line"><strong>${escapeHTML(item.name)}</strong><span>${escapeHTML(unitLabel(item))}</span></div>${renderRetailerPrices(item)}${provenance}</div>${renderQuantityEditor(item)}${priceDetail}</article>`;
}

function renderComparison(payload) {
  if (!els.comparison || !els.comparisonNote) return;
  const totals = payload.retailer_totals || [];
  const refresh = payload.refresh || {};
  const statuses = refresh.statuses || {};
  const statusText = Object.entries(statuses).map(([retailer, status]) => `${retailer === 'coles' ? 'Coles' : 'Woolworths'}: ${String(status).replaceAll('-', ' ')}`).join(' · ');
  if (!payload.total_count || !totals.length) {
    els.comparisonNote.textContent = 'Add an open grocery item to compare retailer totals.';
    els.comparison.innerHTML = '';
    if (els.bestDeals) els.bestDeals.innerHTML = '<p class="muted-copy">Add items to see store-by-store savings.</p>';
    return;
  }
  const comparisonSummary = payload.recommended_retailer_label
    ? `${payload.recommended_retailer_label} is lowest for the fully matched, equivalent cart.`
    : payload.comparison_not_comparable_items?.length
      ? `Totals are shown for planning, but product sizes or variants differ for: ${payload.comparison_not_comparable_items.join(', ')}.`
      : 'No retailer has a complete match for every item yet.';
  els.comparisonNote.textContent = `${comparisonSummary}${statusText ? ` ${statusText}.` : ''}${refresh.error ? ' Live refresh fell back safely to curated data.' : ''}`;
  els.comparison.innerHTML = totals.map((retailer) => {
    const lines = payload.comparison?.[retailer.retailer]?.lines || [];
    const status = retailer.complete
      ? retailer.comparable
        ? `${retailer.priced_count} of ${payload.total_count} equivalent items matched${retailer.live_count ? ` · ${retailer.live_count} live` : ''}${retailer.stale_count ? ` · ${retailer.stale_count} stale` : ''}`
        : 'Complete prices · products are not equivalent'
      : `Partial · ${retailer.unknown_count} item${retailer.unknown_count === 1 ? '' : 's'} not matched`;
    const unknown = retailer.unknown_items?.length ? `<small class="retailer-unknown">Missing: ${retailer.unknown_items.map(escapeHTML).join(', ')}</small>` : '';
    const products = lines.length ? `<details class="retailer-products"><summary>Products compared</summary><ul>${lines.map((line) => `<li><span>${escapeHTML(line.name || '')} · ${money(line.line_total)}</span><small>${line.match ? `${escapeHTML(line.match.title)} · ${money(line.match.price)} each · ${line.match.confidence === 'live' ? 'live' : 'curated'}${line.match.stale ? ' · stale' : ''}${line.match.size_match === 'closest' ? ` · closest pack${line.match.requested_size ? ` for ${escapeHTML(line.match.requested_size)}` : ''}` : ''}` : 'No safe match'}</small></li>`).join('')}</ul></details>` : '';
    const recommended = retailer.retailer === payload.recommended_retailer && retailer.comparable;
    return `<div class="retailer-total${recommended ? ' is-recommended' : ''}"><div><strong>${escapeHTML(retailer.retailer_label)}</strong><span>${escapeHTML(status)}</span>${unknown}${products}</div><strong>${money(retailer.total)}</strong></div>`;
  }).join('');
  if (els.bestDeals) {
    const deals = payload.best_deals || [];
    els.bestDeals.innerHTML = deals.length
      ? `<ul>${deals.slice(0, 6).map((deal) => `<li><strong>${escapeHTML(deal.name || '')}</strong><span>Save ${money(deal.savings)} at ${escapeHTML(deal.retailer_label)}${deal.stale ? ' · last known price' : ''}</span></li>`).join('')}</ul>`
      : '<p class="muted-copy">No safe per-item savings yet. Equivalent sizes are required.</p>';
  }
}

function render(payload) {
  const { items } = payload;
  els.itemCount.textContent = payload.total_count;
  els.pricedTotal.textContent = money(payload.priced_total);
  els.budgetTotal.textContent = money(payload.budget);
  els.unknownCount.textContent = payload.unknown_price_count;
  els.remainingTotal.textContent = payload.remaining == null ? '—' : money(payload.remaining);
  els.budgetStatus.textContent = payload.budget == null ? 'Set a target below' : (payload.over_budget ? 'Over the known subtotal' : 'Known prices included');
  els.remainingStatus.textContent = payload.remaining == null ? 'Set a weekly budget' : (payload.over_budget ? 'Over budget' : 'After known prices');
  els.budgetSignal.textContent = payload.budget == null ? 'Set a weekly target' : (payload.over_budget ? `${money(Math.abs(payload.remaining))} over known budget` : `${money(payload.remaining)} left on known prices`);
  els.budgetSignalNote.textContent = payload.unknown_price_count ? `${payload.unknown_price_count} item${payload.unknown_price_count === 1 ? '' : 's'} still need a price.` : 'Every open item has a price.';
  if (payload.budget != null) els.budgetInput.value = payload.budget.toFixed(2);
  els.list.innerHTML = items.map(renderItem).join('');
  els.list.classList.toggle('is-hidden', items.length === 0); els.empty.classList.toggle('is-hidden', items.length !== 0);
  els.updatedAt.textContent = `UPDATED ${new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(payload.generated_at || Date.now())).toUpperCase()}`;
  renderComparison(payload);
  els.list.querySelectorAll('.quick-price-form').forEach((form) => form.addEventListener('submit', saveManualPrice));
  els.list.querySelectorAll('.quantity-form').forEach((form) => form.addEventListener('submit', saveQuantity));
}

async function load() {
  els.sync.textContent = 'Loading grocery list'; els.refresh.classList.add('is-loading');
  try { const response = await hearthstateFetch('/api/groceries', { cache: 'no-store' }); if (!response.ok) throw new Error(`Request failed: ${response.status}`); const payload = await response.json(); render(payload); els.error.classList.add('is-hidden'); els.sync.textContent = payload.refresh?.enabled ? 'Live provider configured · cached prices shown' : 'Curated prices · refresh provider not configured'; }
  catch (error) { els.error.textContent = 'Could not load the grocery budget.'; els.error.classList.remove('is-hidden'); els.sync.textContent = 'Offline'; console.error(error); }
  finally { els.refresh.classList.remove('is-loading'); }
}
async function saveManualPrice(event) {
  event.preventDefault(); const form = event.currentTarget; const response = await hearthstateFetch('/api/groceries/price', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ item_id: form.dataset.itemId, price: Number(new FormData(form).get('price')), source: 'Manual entry', confidence: 'manual', note: 'Entered by household' }) });
  if (!response.ok) { els.error.textContent = 'Could not save that price.'; els.error.classList.remove('is-hidden'); return; } await load();
}
async function saveQuantity(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const quantity = Number(new FormData(form).get('quantity'));
  if (!Number.isFinite(quantity) || quantity <= 0) {
    els.error.textContent = 'Quantity must be greater than zero.';
    els.error.classList.remove('is-hidden');
    return;
  }
  const response = await hearthstateFetch('/api/groceries/item', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ item_id: form.dataset.itemId, quantity }) });
  if (!response.ok) { els.error.textContent = 'Could not update that quantity.'; els.error.classList.remove('is-hidden'); return; }
  await load();
}
async function quickAddGrocery(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const name = String(new FormData(form).get('name') || '').trim();
  if (!name) return;
  const button = form.querySelector('button[type="submit"]');
  if (button) { button.disabled = true; button.textContent = 'Adding…'; }
  try {
    const response = await hearthstateFetch('/api/groceries', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    const created = await response.json();
    form.reset();
    if (created.item?.id) {
      if (button) button.textContent = 'Searching…';
      try {
        const searchResponse = await hearthstateFetch('/api/groceries/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ item_id: created.item.id }) });
        if (searchResponse.ok) render(await searchResponse.json());
        else await load();
      } catch (searchError) {
        console.error(searchError);
        await load();
      }
    } else {
      await load();
    }
    els.quickAddInput.focus();
  } catch (error) {
    els.error.textContent = 'Could not add that grocery item.';
    els.error.classList.remove('is-hidden');
    console.error(error);
  } finally {
    if (button) { button.disabled = false; button.textContent = 'Add item'; }
  }
}
els.quickAddForm.addEventListener('submit', quickAddGrocery);
els.budgetForm.addEventListener('submit', async (event) => { event.preventDefault(); const budget = Number(new FormData(els.budgetForm).get('budget')); if (!Number.isFinite(budget) || budget < 0) return; const response = await hearthstateFetch('/api/groceries/budget', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ budget, updated_by: 'grant' }) }); if (!response.ok) { els.error.textContent = 'Could not save the weekly budget.'; els.error.classList.remove('is-hidden'); return; } render(await response.json()); });
els.refreshColes.addEventListener('click', async () => {
  els.refreshColes.disabled = true;
  els.refreshColes.textContent = 'Checking…';
  try {
    const response = await hearthstateFetch('/api/groceries/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    const payload = await response.json();
    render(payload);
    const statuses = Object.values(payload.refresh?.statuses || {});
    els.sync.textContent = statuses.includes('live') ? 'Live · Coles + Woolworths compared' : 'Curated fallback · Coles + Woolworths compared';
    els.error.classList.add('is-hidden');
  } catch (error) {
    els.error.textContent = 'Could not refresh supermarket prices.';
    els.error.classList.remove('is-hidden');
    console.error(error);
  } finally {
    els.refreshColes.disabled = false;
    els.refreshColes.textContent = 'Refresh Coles + Woolworths';
  }
});
els.theme.addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark')); els.refresh.addEventListener('click', load); syncTheme(); load(); window.setInterval(load, 60000);
