// Optional live-data provider: Amadeus Self-Service APIs (free tier).
// Activates automatically when AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET are
// set (get keys at https://developers.amadeus.com). When active, real flight
// offers replace the smart-engine estimates; on any failure we fall back
// silently so search never breaks.

const BASE = process.env.AMADEUS_ENV === 'production'
  ? 'https://api.amadeus.com'
  : 'https://test.api.amadeus.com';

let token = { value: null, expiresAt: 0 };

function isConfigured() {
  return Boolean(process.env.AMADEUS_CLIENT_ID && process.env.AMADEUS_CLIENT_SECRET);
}

async function getToken() {
  if (token.value && Date.now() < token.expiresAt - 30000) return token.value;
  const res = await fetch(`${BASE}/v1/security/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'client_credentials',
      client_id: process.env.AMADEUS_CLIENT_ID,
      client_secret: process.env.AMADEUS_CLIENT_SECRET
    })
  });
  if (!res.ok) throw new Error(`Amadeus auth failed: HTTP ${res.status}`);
  const data = await res.json();
  token = { value: data.access_token, expiresAt: Date.now() + data.expires_in * 1000 };
  return token.value;
}

async function apiGet(path, params) {
  const t = await getToken();
  const url = `${BASE}${path}?${new URLSearchParams(params)}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  const res = await fetch(url, { headers: { Authorization: `Bearer ${t}` }, signal: controller.signal });
  clearTimeout(timer);
  if (!res.ok) throw new Error(`Amadeus ${path} failed: HTTP ${res.status}`);
  return res.json();
}

// Known low-cost carrier codes, for airline-type filtering of live offers.
const LCC_CODES = new Set([
  'FR', 'U2', 'VY', 'W6', 'DY', 'EW', 'HV', 'PC', 'NK', 'F9', 'WN', 'B6', 'WS', 'Y4', 'G4',
  '6E', 'SG', 'QP', 'IX', 'AK', 'D7', 'TR', 'VJ', '5J', 'MM', 'ZG', 'JQ', 'TT', 'FZ', 'G9',
  'XY', 'G3', 'H2', 'FO', 'FA'
]);
const PREMIUM_CODES = new Set(['SQ', 'QR', 'EK', 'NH', 'JL', 'CX', 'BR', 'EY', 'NZ']);

function carrierType(code) {
  if (LCC_CODES.has(code)) return 'low-cost';
  if (PREMIUM_CODES.has(code)) return 'premium';
  return 'full-service';
}

function isoDurationToMin(dur) {
  const m = /PT(?:(\d+)H)?(?:(\d+)M)?/.exec(dur || '');
  return m ? (Number(m[1] || 0) * 60 + Number(m[2] || 0)) : 0;
}

// Maps Amadeus flight offers into FareForge's flight shape.
async function searchFlights({ from, to, departDate, returnDate, adults, cabin }) {
  const params = {
    originLocationCode: from.iata,
    destinationLocationCode: to.iata,
    departureDate: departDate,
    adults: String(adults),
    travelClass: cabin.toUpperCase(),
    currencyCode: 'USD',
    max: '12'
  };
  if (returnDate) params.returnDate = returnDate;

  const data = await apiGet('/v2/shopping/flight-offers', params);
  const carriers = (data.dictionaries && data.dictionaries.carriers) || {};

  return (data.data || []).map((offer, i) => {
    const out = offer.itineraries[0];
    const segs = out.segments;
    const first = segs[0];
    const last = segs[segs.length - 1];
    const durationMin = isoDurationToMin(out.duration);
    const carrierCode = first.carrierCode;
    const total = Number(offer.price.grandTotal || offer.price.total);
    return {
      id: `LIVE-FL-${offer.id || i}`,
      type: 'flight',
      live: true,
      airline: carriers[carrierCode] || carrierCode,
      airlineType: carrierType(carrierCode),
      via: segs.slice(0, -1).map(s => s.arrival.iataCode),
      flightNumber: `${carrierCode}${first.number}`,
      from: from.iata,
      to: to.iata,
      fromCity: from.city,
      toCity: to.city,
      departDate,
      returnDate: returnDate || null,
      roundTrip: Boolean(returnDate),
      departTime: first.departure.at.slice(11, 16),
      arriveTime: last.arrival.at.slice(11, 16),
      arriveDayOffset: last.arrival.at.slice(0, 10) === departDate ? 0 : 1,
      durationMin,
      duration: `${Math.floor(durationMin / 60)}h ${String(durationMin % 60).padStart(2, '0')}m`,
      stops: segs.length - 1,
      cabin,
      airlineRating: 7.5,
      refundable: false,
      checkedBag: Boolean(offer.pricingOptions && offer.pricingOptions.includedCheckedBagsOnly),
      pricePerPersonUSD: Math.round((total / adults) * 100) / 100,
      priceUSD: total
    };
  });
}

module.exports = { isConfigured, searchFlights };
