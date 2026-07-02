// FareForge frontend.

const $ = id => document.getElementById(id);

const state = {
  data: null,            // last search response
  tab: 'flights',
  sort: 'price',
  selected: { flight: null, hotel: null, car: null },
  selectedBundle: null,
  filters: { stops: 'any', type: 'all', bag: false },
  fromAirport: null,
  toAirport: null
};

// ---------- init ----------

(function init() {
  const today = new Date();
  const in3w = new Date(today.getTime() + 21 * 86400000);
  const in4w = new Date(today.getTime() + 28 * 86400000);
  $('departInput').value = in3w.toISOString().slice(0, 10);
  $('returnInput').value = in4w.toISOString().slice(0, 10);
  $('departInput').min = today.toISOString().slice(0, 10);
  $('returnInput').min = today.toISOString().slice(0, 10);

  loadCurrencies();
  setupAutocomplete('fromInput', 'fromSuggest', a => (state.fromAirport = a));
  setupAutocomplete('toInput', 'toSuggest', a => (state.toAirport = a));

  $('swapBtn').addEventListener('click', () => {
    [state.fromAirport, state.toAirport] = [state.toAirport, state.fromAirport];
    const f = $('fromInput').value;
    $('fromInput').value = $('toInput').value;
    $('toInput').value = f;
  });

  $('searchBtn').addEventListener('click', runSearch);
  $('sortSelect').addEventListener('change', e => { state.sort = e.target.value; renderList(); });
  document.querySelectorAll('.tab').forEach(t =>
    t.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
      t.classList.add('active');
      state.tab = t.dataset.tab;
      renderList();
    })
  );
  $('stopsFilter').addEventListener('change', e => { state.filters.stops = e.target.value; renderList(); });
  $('typeFilter').addEventListener('change', e => { state.filters.type = e.target.value; renderList(); });
  $('bagFilter').addEventListener('change', e => { state.filters.bag = e.target.checked; renderList(); });

  $('bookBtn').addEventListener('click', openBookingModal);
  $('modalClose').addEventListener('click', () => ($('modalBackdrop').hidden = true));
  $('modalBackdrop').addEventListener('click', e => {
    if (e.target === $('modalBackdrop')) $('modalBackdrop').hidden = true;
  });
})();

async function loadCurrencies() {
  try {
    const res = await fetch('/api/currencies');
    const { currencies, live, updatedAt } = await res.json();
    $('currencyInput').innerHTML = currencies
      .map(c => `<option ${c === 'USD' ? 'selected' : ''}>${c}</option>`).join('');
    const pill = $('livePill');
    pill.classList.toggle('live', live);
    $('livePillText').textContent = live
      ? `LIVE rates · ${updatedAt ? new Date(updatedAt).toUTCString().slice(5, 16) : 'now'}`
      : 'offline rates';
  } catch {
    $('livePillText').textContent = 'rates unavailable';
  }
}

// ---------- autocomplete ----------

function setupAutocomplete(inputId, boxId, onPick) {
  const input = $(inputId);
  const box = $(boxId);
  let items = [];
  let timer;

  input.addEventListener('input', () => {
    onPick(null);
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      if (q.length < 2) return box.classList.remove('open');
      const res = await fetch(`/api/locations?q=${encodeURIComponent(q)}`);
      items = await res.json();
      if (!items.length) return box.classList.remove('open');
      box.innerHTML = items.map((a, i) =>
        `<div class="suggest-item" data-i="${i}">
           <span>${a.city}, ${a.country}</span><span class="code">${a.iata}</span>
         </div>`).join('');
      box.classList.add('open');
      box.querySelectorAll('.suggest-item').forEach(el =>
        el.addEventListener('mousedown', () => pick(items[Number(el.dataset.i)]))
      );
    }, 180);
  });

  input.addEventListener('blur', () => setTimeout(() => box.classList.remove('open'), 150));

  function pick(a) {
    input.value = `${a.city} (${a.iata})`;
    box.classList.remove('open');
    onPick(a);
  }
}

// ---------- search ----------

async function runSearch() {
  const err = $('searchError');
  err.hidden = true;

  if (!state.fromAirport || !state.toAirport) {
    err.textContent = 'Pick both origin and destination from the suggestions.';
    err.hidden = false;
    return;
  }

  const params = new URLSearchParams({
    from: state.fromAirport.iata,
    to: state.toAirport.iata,
    depart: $('departInput').value,
    adults: $('adultsInput').value,
    cabin: $('cabinInput').value,
    currency: $('currencyInput').value
  });
  if ($('returnInput').value) params.set('return', $('returnInput').value);

  $('searchBtn').disabled = true;
  $('results').hidden = true;
  $('tripbar').hidden = true;
  $('loader').hidden = false;
  state.selected = { flight: null, hotel: null, car: null };
  state.selectedBundle = null;
  state.filters = { stops: 'any', type: 'all', bag: false };
  $('stopsFilter').value = 'any';
  $('typeFilter').value = 'all';
  $('bagFilter').checked = false;

  try {
    const res = await fetch(`/api/search?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Search failed');
    state.data = data;
    renderResults();
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  } finally {
    $('searchBtn').disabled = false;
    $('loader').hidden = true;
  }
}

// ---------- money ----------

function money(usd) {
  const { currency, rate } = state.data.meta;
  const val = usd * rate;
  return new Intl.NumberFormat(undefined, {
    style: 'currency', currency, maximumFractionDigits: val >= 1000 ? 0 : 2
  }).format(val);
}

// ---------- rendering ----------

function renderResults() {
  const { meta, flights, hotels, cars } = state.data;
  $('routeSummary').innerHTML = `
    <strong>${meta.from.city} (${meta.from.iata}) → ${meta.to.city} (${meta.to.iata})</strong>
    <span class="chip">${meta.departDate}${meta.returnDate ? ' → ' + meta.returnDate : ' · one-way'}</span>
    <span class="chip">${meta.adults} traveler${meta.adults > 1 ? 's' : ''} · ${meta.cabin.replace('_', ' ')}</span>
    <span class="chip">${meta.distanceKm.toLocaleString()} km</span>
    <span class="chip ${meta.international ? 'intl' : ''}">${meta.international ? '🌍 international' : '🏠 domestic'}</span>
    ${meta.flightSource === 'amadeus-live' ? '<span class="chip intl">⚡ live flight offers</span>' : ''}`;

  $('flightCount').textContent = `(${flights.length})`;
  $('hotelCount').textContent = `(${hotels.length})`;
  $('carCount').textContent = `(${cars.length})`;

  renderBundles();
  renderList();
  $('results').hidden = false;
  updateTripbar();
}

function renderBundles() {
  const { bundles } = state.data;
  $('bundles').innerHTML = bundles.map(b => {
    const parts = [
      itemById(b.flightId), itemById(b.hotelId), itemById(b.carId)
    ].filter(Boolean).map(partLabel).join('<br>');
    return `
      <div class="bundle ${state.selectedBundle === b.key ? 'selected' : ''}" data-key="${b.key}">
        <h3>${b.emoji} ${b.name}</h3>
        <p class="tagline">${b.tagline}</p>
        <div class="b-total">${money(b.totalUSD)}</div>
        <div class="b-parts">${parts}</div>
        ${b.savesVsLuxuryUSD ? `<div class="b-saves">saves ${money(b.savesVsLuxuryUSD)} vs 👑</div>` : ''}
      </div>`;
  }).join('');

  $('bundles').querySelectorAll('.bundle').forEach(el =>
    el.addEventListener('click', () => selectBundle(el.dataset.key))
  );
}

function partLabel(item) {
  if (item.type === 'flight') return `✈️ ${item.airline} · ${item.stops === 0 ? 'nonstop' : item.stops + ' stop'}`;
  if (item.type === 'hotel') return `🏨 ${item.name} · ${'★'.repeat(item.stars)}`;
  return `🚗 ${item.vendor} ${item.carClass}`;
}

function itemById(id) {
  if (!id || !state.data) return null;
  const { flights, hotels, cars } = state.data;
  return [...flights, ...hotels, ...cars].find(x => x.id === id) || null;
}

function selectBundle(key) {
  const b = state.data.bundles.find(x => x.key === key);
  if (!b) return;
  state.selectedBundle = key;
  state.selected = { flight: b.flightId, hotel: b.hotelId, car: b.carId };
  renderBundles();
  renderList();
  updateTripbar();
}

function currentItems() {
  let items = [...state.data[state.tab]];
  if (state.tab === 'flights') {
    const f = state.filters;
    if (f.stops !== 'any') items = items.filter(x => x.stops <= Number(f.stops));
    if (f.type !== 'all') items = items.filter(x => x.airlineType === f.type);
    if (f.bag) items = items.filter(x => x.checkedBag);
  }
  if (state.sort === 'price') items.sort((a, b) => a.priceUSD - b.priceUSD);
  if (state.sort === 'value') items.sort((a, b) => b.valueScore - a.valueScore);
  if (state.sort === 'quality') items.sort((a, b) => b.qualityScore - a.qualityScore);
  return items;
}

const TYPE_KEY = { flight: 'flight', hotel: 'hotel', car: 'car' };

function resetFilters() {
  state.filters = { stops: 'any', type: 'all', bag: false };
  $('stopsFilter').value = 'any';
  $('typeFilter').value = 'all';
  $('bagFilter').checked = false;
  renderList();
}

function renderList() {
  const items = currentItems();

  const onFlights = state.tab === 'flights';
  $('flightFilters').style.display = onFlights ? 'flex' : 'none';
  if (onFlights) {
    const total = state.data.flights.length;
    $('filterCount').textContent = items.length === total
      ? `${total} flights` : `showing ${items.length} of ${total} flights`;
  }

  if (!items.length) {
    $('itemList').innerHTML =
      '<div class="no-match">No flights match these filters. <button type="button" id="resetFiltersBtn">Reset filters</button></div>';
    $('resetFiltersBtn').addEventListener('click', resetFilters);
    return;
  }

  $('itemList').innerHTML = items.map(item => {
    const selected = state.selected[TYPE_KEY[item.type]] === item.id;
    return `
      <div class="item ${selected ? 'selected' : ''}" data-id="${item.id}">
        <div class="item-main">
          <div class="item-title">${itemTitle(item)} ${badgeHtml(item)}</div>
          <div class="item-sub">${itemSub(item)}</div>
        </div>
        <div class="item-score">
          <span class="score-label">value ${item.valueScore}/100</span>
          <div class="score-bar"><div class="score-fill" style="width:${item.valueScore}%"></div></div>
        </div>
        <div class="item-price">
          <div class="price">${money(item.priceUSD)}</div>
          <div class="price-sub">${priceSub(item)}</div>
          <button class="select-btn" type="button">${selected ? '✓ Selected' : 'Select'}</button>
        </div>
      </div>`;
  }).join('');

  $('itemList').querySelectorAll('.item').forEach(el =>
    el.querySelector('.select-btn').addEventListener('click', () => toggleSelect(el.dataset.id))
  );
}

const TYPE_LABEL = { 'low-cost': '💸 low-cost', 'full-service': '🛫 full-service', premium: '✨ premium' };

function badgeHtml(item) {
  let html = (item.badges || [])
    .map(b => `<span class="badge ${b}">${b.replace('-', ' ')}</span>`).join('');
  if (item.airlineType) html += `<span class="badge type-${item.airlineType}">${TYPE_LABEL[item.airlineType]}</span>`;
  if (item.live) html += '<span class="badge live">live offer</span>';
  return html;
}

function itemTitle(item) {
  if (item.type === 'flight') return `✈️ ${item.airline} <span style="color:var(--muted);font-weight:400">${item.flightNumber}</span>`;
  if (item.type === 'hotel') return `🏨 ${item.name} <span style="color:var(--accent)">${'★'.repeat(item.stars)}</span>`;
  return `🚗 ${item.vendor} — ${item.carClass}`;
}

function itemSub(item) {
  if (item.type === 'flight') {
    const stops = item.stops === 0
      ? 'Nonstop'
      : `${item.stops} stop${item.stops > 1 ? 's' : ''}${item.via && item.via.length ? ' via ' + item.via.join(', ') : ''}`;
    const extras = [
      item.roundTrip ? 'round trip' : 'one way',
      item.refundable ? 'refundable' : null,
      item.checkedBag ? 'checked bag incl.' : null
    ].filter(Boolean).join(' · ');
    return `${item.from} ${item.departTime} → ${item.to} ${item.arriveTime}` +
      `${item.arriveDayOffset ? ' +' + item.arriveDayOffset + 'd' : ''} · ${item.duration} · ${stops} · ${extras}`;
  }
  if (item.type === 'hotel') {
    return `Guest rating ${item.guestRating}/10 (${item.reviews.toLocaleString()} reviews) · ` +
      `${item.distanceToCenterKm} km to center · ${item.nights} night${item.nights > 1 ? 's' : ''}, ${item.rooms} room${item.rooms > 1 ? 's' : ''}` +
      `${item.breakfastIncluded ? ' · 🥐 breakfast' : ''}${item.freeCancellation ? ' · free cancellation' : ''}`;
  }
  return `${item.model} · ${item.seats} seats · ${item.transmission}` +
    `${item.unlimitedKm ? ' · unlimited km' : ''}${item.freeCancellation ? ' · free cancellation' : ''}` +
    ` · pickup ${item.pickupLocation}`;
}

function priceSub(item) {
  if (item.type === 'flight') return `${money(item.pricePerPersonUSD)} / person`;
  if (item.type === 'hotel') return `${money(item.nightlyUSD)} / night / room`;
  return `${money(item.dailyUSD)} / day · ${item.days} days`;
}

function toggleSelect(id) {
  const item = itemById(id);
  if (!item) return;
  const key = TYPE_KEY[item.type];
  state.selected[key] = state.selected[key] === id ? null : id;
  state.selectedBundle = null;
  renderBundles();
  renderList();
  updateTripbar();
}

// ---------- trip bar & booking ----------

function selectedItems() {
  return ['flight', 'hotel', 'car'].map(k => itemById(state.selected[k])).filter(Boolean);
}

function updateTripbar() {
  const items = selectedItems();
  if (!items.length) { $('tripbar').hidden = true; return; }
  $('tripbar').hidden = false;
  $('tripbarItems').innerHTML = items.map(i => `
    <span class="tb-item"><strong>${shortLabel(i)}</strong> ${money(i.priceUSD)}
      <span class="tb-x" data-id="${i.id}" title="Remove">✕</span></span>`).join('');
  $('tripbarItems').querySelectorAll('.tb-x').forEach(x =>
    x.addEventListener('click', () => toggleSelect(x.dataset.id))
  );
  const total = items.reduce((s, i) => s + i.priceUSD, 0);
  $('tripTotal').textContent = money(total);
}

function shortLabel(i) {
  if (i.type === 'flight') return `✈️ ${i.airline}`;
  if (i.type === 'hotel') return `🏨 ${i.name}`;
  return `🚗 ${i.vendor} ${i.carClass}`;
}

function openBookingModal() {
  const items = selectedItems();
  if (!items.length) return;
  const { bookingLinks } = state.data;
  const linkKey = { flight: 'flights', hotel: 'hotels', car: 'cars' };

  $('modalBody').innerHTML = items.map(i => `
    <div class="modal-section">
      <h4>${shortLabel(i)} — ${money(i.priceUSD)}</h4>
      <p class="m-sub">${itemSub(i)}</p>
      <div class="link-row">
        ${bookingLinks[linkKey[i.type]].map(l =>
          `<a class="book-link" href="${l.url}" target="_blank" rel="noopener noreferrer">Book on ${l.site} ↗</a>`
        ).join('')}
      </div>
    </div>`).join('') +
    `<div class="modal-total">Estimated trip total: <strong>${money(items.reduce((s, i) => s + i.priceUSD, 0))}</strong></div>`;

  $('modalBackdrop').hidden = false;
}
