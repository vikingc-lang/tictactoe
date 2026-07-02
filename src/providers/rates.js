// Live currency rates from open.er-api.com (free, no API key). Cached for an
// hour; falls back to a static snapshot when offline so the app never breaks.

const FALLBACK_RATES = {
  USD: 1, EUR: 0.93, GBP: 0.79, INR: 86.5, JPY: 155.2, CNY: 7.25, AUD: 1.52,
  CAD: 1.37, CHF: 0.88, SGD: 1.34, AED: 3.67, THB: 34.6, MXN: 18.4, BRL: 5.6,
  ZAR: 18.2, TRY: 39.5, KRW: 1385, NZD: 1.66, SEK: 10.6, NOK: 10.8, DKK: 6.9
};

const CACHE_TTL_MS = 60 * 60 * 1000;
let cache = { at: 0, rates: null, live: false };

async function getRates() {
  if (cache.rates && Date.now() - cache.at < CACHE_TTL_MS) return cache;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 6000);
    const res = await fetch('https://open.er-api.com/v6/latest/USD', { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`rates HTTP ${res.status}`);
    const data = await res.json();
    if (data.result !== 'success' || !data.rates) throw new Error('rates payload invalid');
    cache = { at: Date.now(), rates: data.rates, live: true, updatedAt: data.time_last_update_utc };
    return cache;
  } catch (err) {
    console.warn(`[rates] live fetch failed (${err.message}); using fallback snapshot`);
    if (!cache.rates) cache = { at: Date.now(), rates: FALLBACK_RATES, live: false };
    return cache;
  }
}

const SUPPORTED = Object.keys(FALLBACK_RATES);

module.exports = { getRates, SUPPORTED };
