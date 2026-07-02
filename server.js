// FareForge server — search API + static frontend.

const path = require('path');
const express = require('express');

const { searchAirports, findAirport } = require('./src/data/airports');
const { buildFlights, buildHotels, buildCars, haversineKm } = require('./src/engine/fareEngine');
const { buildBundles } = require('./src/engine/bundles');
const { getRates, SUPPORTED } = require('./src/providers/rates');
const amadeus = require('./src/providers/amadeus');
const { flightLinks, hotelLinks, carLinks } = require('./src/booking');

const app = express();
app.use(express.static(path.join(__dirname, 'public')));

const isISODate = s => /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(s));

app.get('/api/locations', (req, res) => {
  res.json(searchAirports(req.query.q, 8));
});

app.get('/api/currencies', async (req, res) => {
  const { live, updatedAt } = await getRates();
  res.json({ currencies: SUPPORTED, live, updatedAt: updatedAt || null });
});

app.get('/api/search', async (req, res) => {
  try {
    const from = findAirport(req.query.from);
    const to = findAirport(req.query.to);
    const departDate = req.query.depart;
    const returnDate = req.query.return || null;
    const adults = Math.min(9, Math.max(1, parseInt(req.query.adults, 10) || 1));
    const cabin = ['economy', 'premium_economy', 'business', 'first'].includes(req.query.cabin)
      ? req.query.cabin : 'economy';
    const currency = SUPPORTED.includes(req.query.currency) ? req.query.currency : 'USD';

    if (!from || !to) return res.status(400).json({ error: 'Unknown origin or destination airport code.' });
    if (from.iata === to.iata) return res.status(400).json({ error: 'Origin and destination must differ.' });
    if (!isISODate(departDate)) return res.status(400).json({ error: 'Invalid departure date.' });
    if (returnDate && !isISODate(returnDate)) return res.status(400).json({ error: 'Invalid return date.' });
    if (returnDate && returnDate < departDate) return res.status(400).json({ error: 'Return date is before departure.' });

    const searchDate = new Date().toISOString().slice(0, 10);
    if (departDate < searchDate) return res.status(400).json({ error: 'Departure date is in the past.' });

    // Hotel & car span: depart -> return (or a 3-night default for one-way trips).
    const checkout = returnDate ||
      new Date(Date.parse(departDate) + 3 * 86400000).toISOString().slice(0, 10);

    // Flights: live provider first, smart engine as fallback / default.
    let flights = null;
    let flightSource = 'smart-engine';
    if (amadeus.isConfigured()) {
      try {
        const live = await amadeus.searchFlights({ from, to, departDate, returnDate, adults, cabin });
        if (live.length) { flights = live; flightSource = 'amadeus-live'; }
      } catch (err) {
        console.warn(`[amadeus] falling back to smart engine: ${err.message}`);
      }
    }
    if (!flights) {
      flights = buildFlights({ from, to, departDate, returnDate, adults, cabin, searchDate });
    }

    const hotels = buildHotels({ to, checkin: departDate, checkout, adults, searchDate });
    const cars = buildCars({ to, pickup: departDate, dropoff: checkout, searchDate });
    const bundles = buildBundles({ flights, hotels, cars });

    const rates = await getRates();
    const rate = rates.rates[currency] || 1;

    res.json({
      meta: {
        from: { iata: from.iata, city: from.city, country: from.country },
        to: { iata: to.iata, city: to.city, country: to.country },
        international: from.cc !== to.cc,
        distanceKm: haversineKm(from, to),
        departDate,
        returnDate,
        adults,
        cabin,
        currency,
        rate,
        liveRates: rates.live,
        ratesUpdatedAt: rates.updatedAt || null,
        flightSource,
        searchedAt: new Date().toISOString()
      },
      flights,
      hotels,
      cars,
      bundles,
      bookingLinks: {
        flights: flightLinks({ from, to, departDate, returnDate, adults }),
        hotels: hotelLinks({ to, checkin: departDate, checkout, adults }),
        cars: carLinks({ to, pickup: departDate, dropoff: checkout })
      }
    });
  } catch (err) {
    console.error('[search] unexpected error:', err);
    res.status(500).json({ error: 'Search failed. Please try again.' });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`✈️  FareForge running at http://localhost:${PORT}`);
  console.log(amadeus.isConfigured()
    ? '   Live flight offers: Amadeus (configured)'
    : '   Live flight offers: not configured — using smart fare engine. Set AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET to enable.');
});
