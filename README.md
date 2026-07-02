# ✈️ FareForge

**One search · three deals · zero regrets.**

FareForge finds the cheapest and best fares for **flights, hotels and rental cars** between any
two places — same country or across the world — then lets you pick your options and hand off to
real booking sites to buy.

![Node](https://img.shields.io/badge/node-%E2%89%A518-brightgreen) ![License](https://img.shields.io/badge/license-MIT-blue)

## The creative twist: Trip Bundles 🎁

Most comparison sites make you eyeball three separate lists. FareForge cross-combines
flight + hotel + car into three ready-made trips with personalities:

| Bundle | What it optimizes |
|---|---|
| 🪙 **The Penny Pincher** | Absolute lowest total price |
| 🎯 **The Sweet Spot** | Best value-per-dollar (price × quality score) |
| 👑 **First-Class Treatment** | Maximum comfort — nonstop, five stars, leather seats |

Tap a bundle and every component is auto-selected; the Penny Pincher card even shows how much
you save versus going full luxury. You can still mix & match any individual flight, hotel and
car — a sticky trip bar keeps a running total.

## Features

- 🌍 **120+ major airports worldwide** with typeahead search — domestic and international routes
- ✈️🏨🚗 Ranked options for flights, hotels and rental cars with **Cheapest / Best value / Top quality** badges and a 0–100 value score on every option
- 📡 **Live internet data**:
  - Real-time currency conversion (20+ currencies) via [open.er-api.com](https://www.exchangerate-api.com) — no API key needed, refreshed hourly, "LIVE rates" indicator in the header
  - Optional **live flight offers via Amadeus** (see below)
- 🧠 **Smart fare engine** fallback: realistic route-aware pricing driven by great-circle distance, booking lead time, weekends, hub competition and local cost of living — deterministic, so the same search always returns the same offers
- 🛒 **Select & book**: choose your options, hit *Book my trip*, and get prefilled deep links to Google Flights, Skyscanner, Kayak, Booking.com, Expedia and Rentalcars to complete the purchase securely
- 📱 Responsive dark UI, no frontend framework or build step

## Quick start

```bash
npm install
npm start
# open http://localhost:3000
```

### Zero-install option

Just open **`fareforge.html`** in any browser — it's the whole app in one self-contained file
(engine, data and UI inlined; live currency rates fetched directly from the browser). Generated
from the same source modules, minus the optional Amadeus server-side integration.

## Enable live flight offers (optional, free)

1. Create a free account at [developers.amadeus.com](https://developers.amadeus.com) and create an app to get API keys.
2. Run with:

```bash
AMADEUS_CLIENT_ID=your_id AMADEUS_CLIENT_SECRET=your_secret npm start
```

Live offers replace the smart-engine flight estimates and are marked with a **live offer** badge.
If the API errors or rate-limits, FareForge falls back to the smart engine automatically — search
never breaks. Set `AMADEUS_ENV=production` to use production data instead of the test sandbox.

## API

| Endpoint | Description |
|---|---|
| `GET /api/locations?q=par` | Airport/city typeahead |
| `GET /api/currencies` | Supported currencies + live-rate status |
| `GET /api/search?from=JFK&to=CDG&depart=2026-07-20&return=2026-07-27&adults=2&cabin=economy&currency=EUR` | Full search: flights, hotels, cars, bundles, booking links |

## Architecture

```
server.js                 Express app: static frontend + JSON API
src/data/airports.js      Curated airport dataset (IATA, geo, hub tier, cost index)
src/engine/fareEngine.js  Smart fare engine (flights/hotels/cars, value scoring)
src/engine/bundles.js     Trip Bundle optimizer (Penny Pincher / Sweet Spot / First-Class)
src/providers/rates.js    Live currency rates (cached, offline fallback)
src/providers/amadeus.js  Optional live flight offers (auto-enabled by env vars)
src/booking.js            Prefilled deep links to booking partners
public/                   Vanilla JS single-page frontend
```

## Notes

- Hotel and car searches span your travel dates (one-way trips default to a 3-night stay).
- All engine prices are computed in USD and converted with live rates at display time.
- FareForge is a comparison layer: actual purchase happens on the partner sites it links to.
