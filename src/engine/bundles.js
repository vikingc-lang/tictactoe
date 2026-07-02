// Trip Bundles: FareForge's signature move. Instead of making you eyeball three
// lists, it cross-combines flight + hotel + car and serves three ready-made
// trips with different personalities.

const PERSONAS = [
  {
    key: 'penny',
    name: 'The Penny Pincher',
    emoji: '🪙',
    tagline: 'Every dollar stays in your pocket. Zero frills, maximum trip.',
    pick: items => [...items].sort((a, b) => a.priceUSD - b.priceUSD)[0]
  },
  {
    key: 'sweet',
    name: 'The Sweet Spot',
    emoji: '🎯',
    tagline: 'The mathematically optimal trip — best bang for every buck.',
    pick: items => [...items].sort((a, b) => b.valueScore - a.valueScore)[0]
  },
  {
    key: 'first',
    name: 'First-Class Treatment',
    emoji: '👑',
    tagline: 'You only live once. Nonstop, five stars, leather seats.',
    pick: items => [...items].sort((a, b) => b.qualityScore - a.qualityScore || a.priceUSD - b.priceUSD)[0]
  }
];

function buildBundles({ flights, hotels, cars }) {
  const bundles = PERSONAS.map(p => {
    const flight = flights.length ? p.pick(flights) : null;
    const hotel = hotels.length ? p.pick(hotels) : null;
    const car = cars.length ? p.pick(cars) : null;
    const parts = [flight, hotel, car].filter(Boolean);
    const totalUSD = Math.round(parts.reduce((s, x) => s + x.priceUSD, 0) * 100) / 100;
    return {
      key: p.key,
      name: p.name,
      emoji: p.emoji,
      tagline: p.tagline,
      flightId: flight && flight.id,
      hotelId: hotel && hotel.id,
      carId: car && car.id,
      totalUSD
    };
  });

  // Show how much the thrifty option saves versus going full luxury.
  const penny = bundles.find(b => b.key === 'penny');
  const first = bundles.find(b => b.key === 'first');
  if (penny && first && first.totalUSD > penny.totalUSD) {
    penny.savesVsLuxuryUSD = Math.round((first.totalUSD - penny.totalUSD) * 100) / 100;
  }
  return bundles;
}

module.exports = { buildBundles };
