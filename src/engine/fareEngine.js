// FareForge smart fare engine.
// Produces realistic, deterministic fare options for any airport pair. The same
// search always yields the same offers (seeded by route + dates), while prices
// still respond to real-world drivers: distance, booking lead time, weekends,
// hub size and local cost of living. Used standalone or as the fallback when no
// live provider (Amadeus) is configured.

const { AIRPORTS, findAirport } = require('../data/airports');

// ---------- seeded randomness ----------

function hashString(str) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------- geo / time helpers ----------

const EARTH_RADIUS_KM = 6371;

function haversineKm(a, b) {
  const toRad = d => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return Math.round(2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(s)));
}

function daysBetween(fromISO, toISO) {
  return Math.round((new Date(toISO) - new Date(fromISO)) / 86400000);
}

function minutesToHhMm(min) {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}h ${String(m).padStart(2, '0')}m`;
}

function addMinutes(dateISO, startMin, durMin) {
  // Returns clock strings and +N day marker, all in local naive time.
  const dep = startMin;
  const arr = startMin + durMin;
  const fmt = m => {
    const mm = ((m % 1440) + 1440) % 1440;
    return `${String(Math.floor(mm / 60)).padStart(2, '0')}:${String(mm % 60).padStart(2, '0')}`;
  };
  return { depart: fmt(dep), arrive: fmt(arr), dayOffset: Math.floor(arr / 1440) };
}

// Booking lead time drives price the way real revenue management does.
function leadTimeFactor(searchDateISO, departISO) {
  const daysOut = daysBetween(searchDateISO, departISO);
  if (daysOut <= 3) return 1.65;
  if (daysOut <= 7) return 1.45;
  if (daysOut <= 14) return 1.25;
  if (daysOut <= 30) return 1.1;
  if (daysOut <= 60) return 1.0;
  return 0.92;
}

function isWeekend(dateISO) {
  const d = new Date(dateISO).getUTCDay();
  return d === 0 || d === 5 || d === 6;
}

// ---------- airline pools ----------
// Entries: [name, IATA code, quality 0-10, type]. Types: 'low-cost' (budget
// carriers — cheaper fares, bags/refunds rarely included), 'full-service'
// (legacy carriers) and 'premium' (top-rated international flag carriers).

const AIRLINES = {
  NA: [
    ['Delta Air Lines', 'DL', 8.1, 'full-service'], ['United Airlines', 'UA', 7.6, 'full-service'],
    ['American Airlines', 'AA', 7.4, 'full-service'], ['Air Canada', 'AC', 7.5, 'full-service'],
    ['Alaska Airlines', 'AS', 8.0, 'full-service'], ['Aeromexico', 'AM', 7.2, 'full-service'],
    ['JetBlue', 'B6', 7.8, 'low-cost'], ['Southwest', 'WN', 7.7, 'low-cost'],
    ['WestJet', 'WS', 7.3, 'low-cost'], ['Spirit Airlines', 'NK', 6.0, 'low-cost'],
    ['Frontier Airlines', 'F9', 6.1, 'low-cost'], ['Volaris', 'Y4', 6.3, 'low-cost']
  ],
  EU: [
    ['Lufthansa', 'LH', 7.9, 'full-service'], ['Air France', 'AF', 7.8, 'full-service'],
    ['KLM', 'KL', 8.0, 'full-service'], ['British Airways', 'BA', 7.6, 'full-service'],
    ['Iberia', 'IB', 7.3, 'full-service'], ['SWISS', 'LX', 8.2, 'full-service'],
    ['Turkish Airlines', 'TK', 8.0, 'full-service'], ['SAS', 'SK', 7.4, 'full-service'],
    ['LOT Polish', 'LO', 7.2, 'full-service'],
    ['Ryanair', 'FR', 6.4, 'low-cost'], ['easyJet', 'U2', 6.8, 'low-cost'],
    ['Vueling', 'VY', 6.6, 'low-cost'], ['Wizz Air', 'W6', 6.3, 'low-cost'],
    ['Norwegian', 'DY', 6.9, 'low-cost'], ['Eurowings', 'EW', 6.7, 'low-cost'],
    ['Transavia', 'HV', 6.8, 'low-cost'], ['Pegasus', 'PC', 6.5, 'low-cost']
  ],
  ME: [
    ['Emirates', 'EK', 8.7, 'premium'], ['Qatar Airways', 'QR', 8.8, 'premium'],
    ['Etihad Airways', 'EY', 8.4, 'premium'], ['Saudia', 'SV', 7.4, 'full-service'],
    ['Royal Jordanian', 'RJ', 7.2, 'full-service'], ['EL AL', 'LY', 7.3, 'full-service'],
    ['flydubai', 'FZ', 7.0, 'low-cost'], ['Air Arabia', 'G9', 6.6, 'low-cost'],
    ['flynas', 'XY', 6.7, 'low-cost']
  ],
  SAS: [
    ['Air India', 'AI', 7.0, 'full-service'], ['Vistara', 'UK', 8.1, 'full-service'],
    ['SriLankan', 'UL', 7.3, 'full-service'],
    ['IndiGo', '6E', 7.5, 'low-cost'], ['SpiceJet', 'SG', 6.6, 'low-cost'],
    ['Akasa Air', 'QP', 7.4, 'low-cost'], ['Air India Express', 'IX', 6.8, 'low-cost']
  ],
  EAS: [
    ['Singapore Airlines', 'SQ', 9.0, 'premium'], ['ANA', 'NH', 8.8, 'premium'],
    ['Japan Airlines', 'JL', 8.6, 'premium'], ['Cathay Pacific', 'CX', 8.4, 'premium'],
    ['EVA Air', 'BR', 8.5, 'premium'], ['Korean Air', 'KE', 8.3, 'full-service'],
    ['Thai Airways', 'TG', 7.9, 'full-service'], ['Malaysia Airlines', 'MH', 7.6, 'full-service'],
    ['China Eastern', 'MU', 7.0, 'full-service'],
    ['VietJet Air', 'VJ', 6.5, 'low-cost'], ['AirAsia', 'AK', 6.7, 'low-cost'],
    ['Scoot', 'TR', 6.9, 'low-cost'], ['Cebu Pacific', '5J', 6.5, 'low-cost'],
    ['Peach', 'MM', 6.8, 'low-cost'], ['ZIPAIR', 'ZG', 7.0, 'low-cost']
  ],
  OC: [
    ['Qantas', 'QF', 8.3, 'full-service'], ['Air New Zealand', 'NZ', 8.5, 'premium'],
    ['Virgin Australia', 'VA', 7.7, 'full-service'], ['Fiji Airways', 'FJ', 7.5, 'full-service'],
    ['Jetstar', 'JQ', 6.7, 'low-cost']
  ],
  SAM: [
    ['LATAM', 'LA', 7.6, 'full-service'], ['Avianca', 'AV', 7.3, 'full-service'],
    ['Azul', 'AD', 7.6, 'full-service'], ['Copa Airlines', 'CM', 7.7, 'full-service'],
    ['GOL', 'G3', 7.0, 'low-cost'], ['Sky Airline', 'H2', 6.4, 'low-cost'],
    ['Flybondi', 'FO', 6.0, 'low-cost']
  ],
  AF: [
    ['Ethiopian Airlines', 'ET', 7.7, 'full-service'], ['Kenya Airways', 'KQ', 7.2, 'full-service'],
    ['EgyptAir', 'MS', 7.0, 'full-service'], ['Royal Air Maroc', 'AT', 7.1, 'full-service'],
    ['Airlink', '4Z', 7.3, 'full-service'], ['Air Mauritius', 'MK', 7.5, 'full-service'],
    ['FlySafair', 'FA', 7.0, 'low-cost']
  ]
};

const GLOBAL_CONNECTORS = [
  ['Emirates', 'EK', 8.7, 'premium'], ['Qatar Airways', 'QR', 8.8, 'premium'],
  ['Turkish Airlines', 'TK', 8.0, 'full-service'], ['Lufthansa', 'LH', 7.9, 'full-service'],
  ['Singapore Airlines', 'SQ', 9.0, 'premium'], ['British Airways', 'BA', 7.6, 'full-service']
];

// Fare behavior by airline type.
const TYPE_PRICE_MULT = { 'low-cost': 0.78, 'full-service': 1.0, premium: 1.1 };
const TYPE_BAG_PROB = { 'low-cost': 0.12, 'full-service': 0.6, premium: 0.9 };
const TYPE_REFUND_PROB = { 'low-cost': 0.08, 'full-service': 0.35, premium: 0.5 };

function airlinePool(from, to) {
  const pool = [...(AIRLINES[from.region] || []), ...(AIRLINES[to.region] || [])];
  if (from.region !== to.region) pool.push(...GLOBAL_CONNECTORS);
  // Dedupe by code.
  const seen = new Set();
  return pool.filter(([, code]) => (seen.has(code) ? false : seen.add(code)));
}

// ---------- flights ----------

const CABIN_MULT = { economy: 1, premium_economy: 1.7, business: 3.4, first: 5.5 };

function flightLegPriceUSD(km, from, to) {
  // Short hops have a floor; long haul gets cheaper per km.
  const perKm = km < 1500 ? 0.11 : km < 5000 ? 0.085 : 0.062;
  const hubDiscount = 1 - 0.03 * (4 - Math.min(from.tier, to.tier)); // big hubs = more competition
  return (38 + km * perKm) * hubDiscount;
}

// Plausible connection hubs for a route: big airports that don't force a
// silly detour, ranked by how little they add to the great-circle distance.
function layoverHubs(from, to) {
  const direct = haversineKm(from, to);
  return AIRPORTS
    .filter(a => a.tier <= 2 && a.city !== from.city && a.city !== to.city)
    .map(a => ({ a, detour: (haversineKm(from, a) + haversineKm(a, to)) / direct }))
    .filter(h => h.detour < 1.45)
    // Rank by detour, but favor mega-hubs — connections happen at big airports.
    .sort((x, y) => (x.detour + (x.a.tier - 1) * 0.12) - (y.detour + (y.a.tier - 1) * 0.12))
    .slice(0, 8)
    .map(h => h.a.iata);
}

function buildFlights({ from, to, departDate, returnDate, adults, cabin, searchDate }) {
  const km = haversineKm(from, to);
  const roundTrip = Boolean(returnDate);
  const seed = hashString(`${from.iata}-${to.iata}-${departDate}-${returnDate || 'ow'}-${cabin}`);
  const rng = mulberry32(seed);
  // Budget carriers are mostly short/medium-haul; only a handful of hybrid
  // LCCs operate long-haul routes.
  const LONG_HAUL_LCC = new Set(['DY', 'TR', 'ZG', 'JQ', 'FZ', '5J', 'AK', 'IX']);
  const pool = airlinePool(from, to).filter(([, code, , t]) =>
    t !== 'low-cost' || km < 4500 || (km < 9500 && LONG_HAUL_LCC.has(code)));
  const lccPool = pool.filter(([, , , t]) => t === 'low-cost');
  const hubs = layoverHubs(from, to);
  const cabinMult = CABIN_MULT[cabin] || 1;

  let base = flightLegPriceUSD(km, from, to) * leadTimeFactor(searchDate, departDate);
  if (isWeekend(departDate)) base *= 1.08;
  if (roundTrip) {
    let ret = flightLegPriceUSD(km, from, to) * leadTimeFactor(searchDate, returnDate) * 0.95;
    if (isWeekend(returnDate)) ret *= 1.08;
    base += ret;
  }
  base *= cabinMult;

  const nonstopMinutes = Math.round((km / 830) * 60 + 40);
  const count = 12;
  const flights = [];

  for (let i = 0; i < count; i++) {
    // Guarantee a spread: the first few offers are low-cost carriers (LCCs
    // mostly fly short/medium haul, so only within ~7000 km), and a couple of
    // slots are forced nonstop so every route shows the full range.
    const useLcc = i < 3 && lccPool.length && km < 7000;
    const [airline, code, quality, airlineType] = useLcc
      ? lccPool[Math.floor(rng() * lccPool.length)]
      : pool[Math.floor(rng() * pool.length)];

    const canNonstop = km < 13500;
    let stops;
    if (canNonstop && (i === 3 || i === 4)) stops = 0;
    else if (canNonstop && rng() < (km < 3500 ? 0.62 : 0.38)) stops = 0;
    else stops = rng() < 0.85 ? 1 : 2;

    // Pick real-looking connection points for one/two-stop itineraries.
    const via = [];
    if (stops > 0 && hubs.length) {
      const first = hubs[Math.floor(rng() * hubs.length)];
      via.push(first);
      if (stops > 1) {
        const rest = hubs.filter(h => h !== first);
        if (rest.length) via.push(rest[Math.floor(rng() * rest.length)]);
      }
    }

    const layover = stops === 0 ? 0 : stops * Math.round(70 + rng() * 150);
    const durationMin = nonstopMinutes + layover + (stops > 0 ? Math.round(km * 0.004) : 0);

    // Nonstops, better airlines and full-service fares command a premium;
    // LCCs and red-eyes go cheaper.
    const departMin = Math.round((300 + rng() * 1080) / 5) * 5;
    const redEye = departMin >= 1260 || departMin <= 330;
    let price = base * (0.82 + rng() * 0.42);
    if (stops === 0) price *= 1.16;
    if (stops === 2) price *= 0.86;
    price *= 0.94 + (quality - 6.4) * 0.045;
    price *= TYPE_PRICE_MULT[airlineType] || 1;
    if (redEye) price *= 0.93;

    const clocks = addMinutes(departDate, departMin, durationMin);
    const refundable = rng() < (TYPE_REFUND_PROB[airlineType] || 0.3);
    const checkedBag = rng() < (TYPE_BAG_PROB[airlineType] || 0.5);

    flights.push({
      id: `FL-${seed.toString(36)}-${i}`,
      type: 'flight',
      airline,
      airlineType,
      flightNumber: `${code}${100 + Math.floor(rng() * 4800)}`,
      from: from.iata,
      to: to.iata,
      fromCity: from.city,
      toCity: to.city,
      departDate,
      returnDate: returnDate || null,
      roundTrip,
      departTime: clocks.depart,
      arriveTime: clocks.arrive,
      arriveDayOffset: clocks.dayOffset,
      durationMin,
      duration: minutesToHhMm(durationMin),
      distanceKm: km,
      stops,
      via,
      cabin,
      airlineRating: quality,
      refundable,
      checkedBag,
      pricePerPersonUSD: round2(price),
      priceUSD: round2(price * adults)
    });
  }

  flights.sort((a, b) => a.priceUSD - b.priceUSD);
  return attachValueScores(flights, f => {
    // Higher is better: cheap, few stops, good airline, sane duration.
    let s = f.airlineRating * 8;
    s -= f.stops * 14;
    s -= (f.durationMin - nonstopMinutes) / 22;
    if (f.refundable) s += 5;
    if (f.checkedBag) s += 4;
    return s;
  });
}

// ---------- hotels ----------

const HOTEL_BRANDS = [
  { name: 'ibis Styles', stars: 3, mult: 0.75 },
  { name: 'Holiday Inn Express', stars: 3, mult: 0.85 },
  { name: 'Mercure', stars: 4, mult: 1.05 },
  { name: 'Novotel', stars: 4, mult: 1.1 },
  { name: 'Hilton Garden Inn', stars: 4, mult: 1.15 },
  { name: 'Courtyard by Marriott', stars: 4, mult: 1.2 },
  { name: 'Radisson Blu', stars: 4, mult: 1.25 },
  { name: 'Hyatt Regency', stars: 5, mult: 1.7 },
  { name: 'InterContinental', stars: 5, mult: 1.95 },
  { name: 'The Ritz-Carlton', stars: 5, mult: 2.6 }
];

const INDIE_PATTERNS = [
  city => `The ${city} Grand`,
  city => `${city} Central Suites`,
  city => `Old Town Boutique ${city}`,
  city => `${city} Riverside Hotel`,
  city => `Casa ${city}`,
  city => `${city} Skyline Residences`
];

function buildHotels({ to, checkin, checkout, adults, searchDate }) {
  const nights = Math.max(1, daysBetween(checkin, checkout));
  const rooms = Math.ceil(adults / 2);
  const seed = hashString(`HTL-${to.iata}-${checkin}-${checkout}`);
  const rng = mulberry32(seed);
  const baseNight = 92 * to.costIndex * leadTimeFactor(searchDate, checkin) * (isWeekend(checkin) ? 1.07 : 1);

  const hotels = [];
  for (let i = 0; i < 9; i++) {
    let name, stars, mult;
    if (rng() < 0.6) {
      const b = HOTEL_BRANDS[Math.floor(rng() * HOTEL_BRANDS.length)];
      name = `${b.name} ${to.city}`;
      stars = b.stars;
      mult = b.mult;
    } else {
      name = INDIE_PATTERNS[Math.floor(rng() * INDIE_PATTERNS.length)](to.city);
      stars = 3 + Math.floor(rng() * 3);
      mult = 0.7 + (stars - 3) * 0.45 + rng() * 0.25;
    }
    const rating = round1(Math.min(9.7, 6.6 + stars * 0.45 + rng() * 0.9));
    const centerKm = round1(0.3 + rng() * 7.5);
    const nightly = baseNight * mult * (1 - Math.min(centerKm, 6) * 0.022) * (0.9 + rng() * 0.25);
    const breakfast = rng() < (stars >= 4 ? 0.6 : 0.4);
    const freeCancel = rng() < 0.65;

    hotels.push({
      id: `HT-${seed.toString(36)}-${i}`,
      type: 'hotel',
      name,
      city: to.city,
      country: to.country,
      stars,
      guestRating: rating,
      reviews: 120 + Math.floor(rng() * 4200),
      distanceToCenterKm: centerKm,
      breakfastIncluded: breakfast,
      freeCancellation: freeCancel,
      checkin,
      checkout,
      nights,
      rooms,
      nightlyUSD: round2(nightly),
      priceUSD: round2(nightly * nights * rooms)
    });
  }

  hotels.sort((a, b) => a.priceUSD - b.priceUSD);
  return attachValueScores(hotels, h => {
    let s = h.guestRating * 9 + h.stars * 4;
    s -= h.distanceToCenterKm * 2.2;
    if (h.breakfastIncluded) s += 6;
    if (h.freeCancellation) s += 5;
    return s;
  });
}

// ---------- rental cars ----------

const CAR_CLASSES = [
  { cls: 'Economy', model: 'Toyota Yaris or similar', daily: 27, seats: 4, bags: 1 },
  { cls: 'Compact', model: 'VW Golf or similar', daily: 33, seats: 5, bags: 2 },
  { cls: 'Intermediate', model: 'Toyota Corolla or similar', daily: 41, seats: 5, bags: 2 },
  { cls: 'Standard', model: 'Skoda Octavia or similar', daily: 48, seats: 5, bags: 3 },
  { cls: 'SUV', model: 'Nissan Qashqai or similar', daily: 63, seats: 5, bags: 4 },
  { cls: 'Minivan', model: 'Kia Carnival or similar', daily: 79, seats: 7, bags: 4 },
  { cls: 'Luxury', model: 'BMW 5 Series or similar', daily: 118, seats: 5, bags: 3 }
];

const CAR_VENDORS = [
  ['Hertz', 8.0], ['Avis', 7.8], ['Budget', 7.2], ['Enterprise', 8.2],
  ['Sixt', 8.1], ['Europcar', 7.4], ['Alamo', 7.6], ['National', 7.9], ['Thrifty', 6.9]
];

// Markets where rentals are predominantly automatic transmission.
const AUTO_MARKETS = new Set(['US', 'CA', 'AU', 'NZ', 'JP', 'KR', 'CN', 'AE', 'QA', 'SA', 'SG', 'HK']);

function buildCars({ to, pickup, dropoff, searchDate }) {
  const days = Math.max(1, daysBetween(pickup, dropoff));
  const seed = hashString(`CAR-${to.iata}-${pickup}-${dropoff}`);
  const rng = mulberry32(seed);
  const marketMult = 0.55 + to.costIndex * 0.55;
  const lead = leadTimeFactor(searchDate, pickup) * 0.92 + 0.08; // cars swing less with lead time

  const cars = [];
  for (let i = 0; i < 8; i++) {
    const spec = CAR_CLASSES[Math.floor(rng() * CAR_CLASSES.length)];
    const [vendor, vendorRating] = CAR_VENDORS[Math.floor(rng() * CAR_VENDORS.length)];
    const daily = spec.daily * marketMult * lead * (0.85 + rng() * 0.4);
    const automatic = AUTO_MARKETS.has(to.cc) ? true : rng() < 0.45;
    const unlimitedKm = rng() < 0.7;
    const freeCancel = rng() < 0.75;

    cars.push({
      id: `CR-${seed.toString(36)}-${i}`,
      type: 'car',
      vendor,
      vendorRating,
      carClass: spec.cls,
      model: spec.model,
      seats: spec.seats,
      bags: spec.bags,
      transmission: automatic ? 'Automatic' : 'Manual',
      unlimitedKm,
      freeCancellation: freeCancel,
      pickupLocation: `${to.city} Airport (${to.iata})`,
      pickup,
      dropoff,
      days,
      dailyUSD: round2(daily),
      priceUSD: round2(daily * days)
    });
  }

  cars.sort((a, b) => a.priceUSD - b.priceUSD);
  return attachValueScores(cars, c => {
    let s = c.vendorRating * 9 + c.seats * 2;
    if (c.unlimitedKm) s += 6;
    if (c.freeCancellation) s += 5;
    if (c.transmission === 'Automatic') s += 3;
    return s;
  });
}

// ---------- scoring ----------

function round2(n) { return Math.round(n * 100) / 100; }
function round1(n) { return Math.round(n * 10) / 10; }

// valueScore (0–100) blends quality with price: what you get per dollar.
function attachValueScores(items, qualityFn) {
  if (!items.length) return items;
  const prices = items.map(i => i.priceUSD);
  const minP = Math.min(...prices);
  const maxP = Math.max(...prices);
  const qualities = items.map(qualityFn);
  const minQ = Math.min(...qualities);
  const maxQ = Math.max(...qualities);

  items.forEach((item, idx) => {
    const priceNorm = maxP === minP ? 1 : 1 - (item.priceUSD - minP) / (maxP - minP);
    const qualNorm = maxQ === minQ ? 1 : (qualities[idx] - minQ) / (maxQ - minQ);
    item.qualityScore = Math.round(qualNorm * 100);
    item.valueScore = Math.round((priceNorm * 0.55 + qualNorm * 0.45) * 100);
  });

  const bestValue = [...items].sort((a, b) => b.valueScore - a.valueScore)[0];
  const cheapest = [...items].sort((a, b) => a.priceUSD - b.priceUSD)[0];
  const finest = [...items].sort((a, b) => b.qualityScore - a.qualityScore)[0];
  bestValue.badges = [...(bestValue.badges || []), 'best-value'];
  cheapest.badges = [...(cheapest.badges || []), 'cheapest'];
  finest.badges = [...(finest.badges || []), 'top-quality'];
  return items;
}

module.exports = { buildFlights, buildHotels, buildCars, haversineKm, findAirport };
