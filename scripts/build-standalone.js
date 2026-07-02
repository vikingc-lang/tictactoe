// Builds fareforge.html: single-file standalone version of FareForge.
// Reuses the real source modules, strips Node plumbing, and adds an in-browser
// API shim so app.js runs unchanged.
const fs = require('fs');
const path = require('path');
const root = path.join(__dirname, '..');
const read = p => fs.readFileSync(path.join(root, p), 'utf8');

const stripNode = src => src
  .replace(/^const .*= require\(.*\);\s*$/gm, '')
  .replace(/^module\.exports = .*;\s*$/gm, '');

const glue = `
// ---------- standalone in-browser API layer ----------
// Replaces the Express server: intercepts fetch('/api/...') and answers
// locally using the same engine code. External URLs pass through untouched.

const FALLBACK_RATES = {
  USD: 1, EUR: 0.93, GBP: 0.79, INR: 86.5, JPY: 155.2, CNY: 7.25, AUD: 1.52,
  CAD: 1.37, CHF: 0.88, SGD: 1.34, AED: 3.67, THB: 34.6, MXN: 18.4, BRL: 5.6,
  ZAR: 18.2, TRY: 39.5, KRW: 1385, NZD: 1.66, SEK: 10.6, NOK: 10.8, DKK: 6.9
};
const SUPPORTED = Object.keys(FALLBACK_RATES);
const realFetch = window.fetch.bind(window);
let ratesCache = { at: 0, rates: null, live: false };

async function getRatesLocal() {
  if (ratesCache.rates && Date.now() - ratesCache.at < 3600000) return ratesCache;
  try {
    const res = await realFetch('https://open.er-api.com/v6/latest/USD');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    if (data.result !== 'success' || !data.rates) throw new Error('bad payload');
    ratesCache = { at: Date.now(), rates: data.rates, live: true, updatedAt: data.time_last_update_utc };
  } catch (err) {
    console.warn('[rates] live fetch failed (' + err.message + '); using fallback snapshot');
    if (!ratesCache.rates) ratesCache = { at: Date.now(), rates: FALLBACK_RATES, live: false };
  }
  return ratesCache;
}

const isISODate = s => /^\\d{4}-\\d{2}-\\d{2}$/.test(s) && !Number.isNaN(Date.parse(s));

async function apiSearch(q) {
  const from = findAirport(q.get('from'));
  const to = findAirport(q.get('to'));
  const departDate = q.get('depart');
  const returnDate = q.get('return') || null;
  const adults = Math.min(9, Math.max(1, parseInt(q.get('adults'), 10) || 1));
  const cabin = ['economy', 'premium_economy', 'business', 'first'].includes(q.get('cabin')) ? q.get('cabin') : 'economy';
  const currency = SUPPORTED.includes(q.get('currency')) ? q.get('currency') : 'USD';

  if (!from || !to) return [400, { error: 'Unknown origin or destination airport code.' }];
  if (from.iata === to.iata) return [400, { error: 'Origin and destination must differ.' }];
  if (!isISODate(departDate)) return [400, { error: 'Invalid departure date.' }];
  if (returnDate && !isISODate(returnDate)) return [400, { error: 'Invalid return date.' }];
  if (returnDate && returnDate < departDate) return [400, { error: 'Return date is before departure.' }];
  const searchDate = new Date().toISOString().slice(0, 10);
  if (departDate < searchDate) return [400, { error: 'Departure date is in the past.' }];

  const checkout = returnDate || new Date(Date.parse(departDate) + 3 * 86400000).toISOString().slice(0, 10);
  const flights = buildFlights({ from, to, departDate, returnDate, adults, cabin, searchDate });
  const hotels = buildHotels({ to, checkin: departDate, checkout, adults, searchDate });
  const cars = buildCars({ to, pickup: departDate, dropoff: checkout, searchDate });
  const bundles = buildBundles({ flights, hotels, cars });
  const rates = await getRatesLocal();

  return [200, {
    meta: {
      from: { iata: from.iata, city: from.city, country: from.country },
      to: { iata: to.iata, city: to.city, country: to.country },
      international: from.cc !== to.cc,
      distanceKm: haversineKm(from, to),
      departDate, returnDate, adults, cabin, currency,
      rate: rates.rates[currency] || 1,
      liveRates: rates.live,
      ratesUpdatedAt: rates.updatedAt || null,
      flightSource: 'smart-engine',
      searchedAt: new Date().toISOString()
    },
    flights, hotels, cars, bundles,
    bookingLinks: {
      flights: flightLinks({ from, to, departDate, returnDate, adults }),
      hotels: hotelLinks({ to, checkin: departDate, checkout, adults }),
      cars: carLinks({ to, pickup: departDate, dropoff: checkout })
    }
  }];
}

window.fetch = async (url, opts) => {
  const u = String(url);
  if (!u.startsWith('/api/')) return realFetch(url, opts);
  const parsed = new URL(u, 'http://local');
  const q = parsed.searchParams;
  let status = 200, body;
  if (parsed.pathname === '/api/locations') {
    body = searchAirports(q.get('q'), 8);
  } else if (parsed.pathname === '/api/currencies') {
    const r = await getRatesLocal();
    body = { currencies: SUPPORTED, live: r.live, updatedAt: r.updatedAt || null };
  } else if (parsed.pathname === '/api/search') {
    [status, body] = await apiSearch(q);
  } else {
    status = 404; body = { error: 'Not found' };
  }
  return { ok: status < 400, status, json: async () => body };
};
`;

const js = [
  '// FareForge standalone build — generated from src/ by scripts, do not edit by hand.',
  stripNode(read('src/data/airports.js')),
  stripNode(read('src/engine/fareEngine.js')),
  stripNode(read('src/engine/bundles.js')),
  stripNode(read('src/booking.js')),
  glue,
  read('public/app.js')
].join('\n');

if (js.includes('</scr' + 'ipt>')) throw new Error('script content would break inline embedding');

let html = read('public/index.html');
html = html.replace('<link rel="stylesheet" href="styles.css" />',
  '<style>\n' + read('public/styles.css') + '\n  </style>');
html = html.replace('<script src="app.js"></script>',
  '<script>\n' + js + '\n  </script>');
html = html.replace('one search · three deals · zero regrets</span>',
  'one search · three deals · zero regrets · single-file edition</span>');

fs.writeFileSync(path.join(root, 'fareforge.html'), html);
console.log('wrote fareforge.html', (fs.statSync(path.join(root, 'fareforge.html')).size / 1024).toFixed(1) + ' KB');
