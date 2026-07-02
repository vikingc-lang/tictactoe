// Curated list of ~120 major airports worldwide.
// tier: 1 = mega-hub, 2 = large, 3 = regional. costIndex: relative city price level (1.0 = global average).
// region keys map into airline pools in the fare engine.

const AIRPORTS = [
  // North America
  { iata: 'JFK', city: 'New York', country: 'United States', cc: 'US', region: 'NA', lat: 40.6413, lon: -73.7781, tier: 1, costIndex: 1.55 },
  { iata: 'EWR', city: 'Newark', country: 'United States', cc: 'US', region: 'NA', lat: 40.6895, lon: -74.1745, tier: 2, costIndex: 1.45 },
  { iata: 'LAX', city: 'Los Angeles', country: 'United States', cc: 'US', region: 'NA', lat: 33.9416, lon: -118.4085, tier: 1, costIndex: 1.4 },
  { iata: 'SFO', city: 'San Francisco', country: 'United States', cc: 'US', region: 'NA', lat: 37.6213, lon: -122.379, tier: 1, costIndex: 1.6 },
  { iata: 'ORD', city: 'Chicago', country: 'United States', cc: 'US', region: 'NA', lat: 41.9742, lon: -87.9073, tier: 1, costIndex: 1.25 },
  { iata: 'MIA', city: 'Miami', country: 'United States', cc: 'US', region: 'NA', lat: 25.7959, lon: -80.287, tier: 1, costIndex: 1.3 },
  { iata: 'DFW', city: 'Dallas', country: 'United States', cc: 'US', region: 'NA', lat: 32.8998, lon: -97.0403, tier: 1, costIndex: 1.1 },
  { iata: 'ATL', city: 'Atlanta', country: 'United States', cc: 'US', region: 'NA', lat: 33.6407, lon: -84.4277, tier: 1, costIndex: 1.05 },
  { iata: 'SEA', city: 'Seattle', country: 'United States', cc: 'US', region: 'NA', lat: 47.4502, lon: -122.3088, tier: 2, costIndex: 1.35 },
  { iata: 'BOS', city: 'Boston', country: 'United States', cc: 'US', region: 'NA', lat: 42.3656, lon: -71.0096, tier: 2, costIndex: 1.4 },
  { iata: 'DEN', city: 'Denver', country: 'United States', cc: 'US', region: 'NA', lat: 39.8561, lon: -104.6737, tier: 2, costIndex: 1.15 },
  { iata: 'LAS', city: 'Las Vegas', country: 'United States', cc: 'US', region: 'NA', lat: 36.086, lon: -115.1537, tier: 2, costIndex: 1.05 },
  { iata: 'MCO', city: 'Orlando', country: 'United States', cc: 'US', region: 'NA', lat: 28.4312, lon: -81.3081, tier: 2, costIndex: 1.0 },
  { iata: 'IAH', city: 'Houston', country: 'United States', cc: 'US', region: 'NA', lat: 29.9902, lon: -95.3368, tier: 2, costIndex: 1.05 },
  { iata: 'PHX', city: 'Phoenix', country: 'United States', cc: 'US', region: 'NA', lat: 33.4373, lon: -112.0078, tier: 2, costIndex: 1.0 },
  { iata: 'HNL', city: 'Honolulu', country: 'United States', cc: 'US', region: 'NA', lat: 21.3187, lon: -157.9225, tier: 2, costIndex: 1.45 },
  { iata: 'YYZ', city: 'Toronto', country: 'Canada', cc: 'CA', region: 'NA', lat: 43.6777, lon: -79.6248, tier: 1, costIndex: 1.2 },
  { iata: 'YVR', city: 'Vancouver', country: 'Canada', cc: 'CA', region: 'NA', lat: 49.1967, lon: -123.1815, tier: 2, costIndex: 1.25 },
  { iata: 'YUL', city: 'Montreal', country: 'Canada', cc: 'CA', region: 'NA', lat: 45.4706, lon: -73.7408, tier: 2, costIndex: 1.1 },
  { iata: 'MEX', city: 'Mexico City', country: 'Mexico', cc: 'MX', region: 'NA', lat: 19.4363, lon: -99.0721, tier: 1, costIndex: 0.65 },
  { iata: 'CUN', city: 'Cancun', country: 'Mexico', cc: 'MX', region: 'NA', lat: 21.0365, lon: -86.8771, tier: 2, costIndex: 0.85 },

  // Europe
  { iata: 'LHR', city: 'London', country: 'United Kingdom', cc: 'GB', region: 'EU', lat: 51.47, lon: -0.4543, tier: 1, costIndex: 1.5 },
  { iata: 'LGW', city: 'London', country: 'United Kingdom', cc: 'GB', region: 'EU', lat: 51.1537, lon: -0.1821, tier: 2, costIndex: 1.5 },
  { iata: 'CDG', city: 'Paris', country: 'France', cc: 'FR', region: 'EU', lat: 49.0097, lon: 2.5479, tier: 1, costIndex: 1.35 },
  { iata: 'ORY', city: 'Paris', country: 'France', cc: 'FR', region: 'EU', lat: 48.7262, lon: 2.3652, tier: 2, costIndex: 1.35 },
  { iata: 'AMS', city: 'Amsterdam', country: 'Netherlands', cc: 'NL', region: 'EU', lat: 52.3105, lon: 4.7683, tier: 1, costIndex: 1.35 },
  { iata: 'FRA', city: 'Frankfurt', country: 'Germany', cc: 'DE', region: 'EU', lat: 50.0379, lon: 8.5622, tier: 1, costIndex: 1.2 },
  { iata: 'MUC', city: 'Munich', country: 'Germany', cc: 'DE', region: 'EU', lat: 48.3537, lon: 11.775, tier: 1, costIndex: 1.25 },
  { iata: 'BER', city: 'Berlin', country: 'Germany', cc: 'DE', region: 'EU', lat: 52.3667, lon: 13.5033, tier: 2, costIndex: 1.1 },
  { iata: 'MAD', city: 'Madrid', country: 'Spain', cc: 'ES', region: 'EU', lat: 40.4983, lon: -3.5676, tier: 1, costIndex: 1.0 },
  { iata: 'BCN', city: 'Barcelona', country: 'Spain', cc: 'ES', region: 'EU', lat: 41.2974, lon: 2.0833, tier: 1, costIndex: 1.05 },
  { iata: 'FCO', city: 'Rome', country: 'Italy', cc: 'IT', region: 'EU', lat: 41.8003, lon: 12.2389, tier: 1, costIndex: 1.1 },
  { iata: 'MXP', city: 'Milan', country: 'Italy', cc: 'IT', region: 'EU', lat: 45.63, lon: 8.7231, tier: 2, costIndex: 1.15 },
  { iata: 'VCE', city: 'Venice', country: 'Italy', cc: 'IT', region: 'EU', lat: 45.5053, lon: 12.3519, tier: 3, costIndex: 1.25 },
  { iata: 'ZRH', city: 'Zurich', country: 'Switzerland', cc: 'CH', region: 'EU', lat: 47.4647, lon: 8.5492, tier: 1, costIndex: 1.75 },
  { iata: 'GVA', city: 'Geneva', country: 'Switzerland', cc: 'CH', region: 'EU', lat: 46.2381, lon: 6.1089, tier: 2, costIndex: 1.7 },
  { iata: 'VIE', city: 'Vienna', country: 'Austria', cc: 'AT', region: 'EU', lat: 48.1103, lon: 16.5697, tier: 2, costIndex: 1.15 },
  { iata: 'CPH', city: 'Copenhagen', country: 'Denmark', cc: 'DK', region: 'EU', lat: 55.618, lon: 12.656, tier: 2, costIndex: 1.45 },
  { iata: 'OSL', city: 'Oslo', country: 'Norway', cc: 'NO', region: 'EU', lat: 60.1976, lon: 11.1004, tier: 2, costIndex: 1.55 },
  { iata: 'ARN', city: 'Stockholm', country: 'Sweden', cc: 'SE', region: 'EU', lat: 59.6498, lon: 17.9238, tier: 2, costIndex: 1.35 },
  { iata: 'HEL', city: 'Helsinki', country: 'Finland', cc: 'FI', region: 'EU', lat: 60.3172, lon: 24.9633, tier: 2, costIndex: 1.3 },
  { iata: 'DUB', city: 'Dublin', country: 'Ireland', cc: 'IE', region: 'EU', lat: 53.4264, lon: -6.2499, tier: 2, costIndex: 1.3 },
  { iata: 'LIS', city: 'Lisbon', country: 'Portugal', cc: 'PT', region: 'EU', lat: 38.7756, lon: -9.1354, tier: 2, costIndex: 0.95 },
  { iata: 'ATH', city: 'Athens', country: 'Greece', cc: 'GR', region: 'EU', lat: 37.9364, lon: 23.9445, tier: 2, costIndex: 0.9 },
  { iata: 'PRG', city: 'Prague', country: 'Czechia', cc: 'CZ', region: 'EU', lat: 50.1008, lon: 14.26, tier: 2, costIndex: 0.85 },
  { iata: 'WAW', city: 'Warsaw', country: 'Poland', cc: 'PL', region: 'EU', lat: 52.1657, lon: 20.9671, tier: 2, costIndex: 0.75 },
  { iata: 'BUD', city: 'Budapest', country: 'Hungary', cc: 'HU', region: 'EU', lat: 47.4298, lon: 19.2611, tier: 2, costIndex: 0.8 },
  { iata: 'IST', city: 'Istanbul', country: 'Turkey', cc: 'TR', region: 'EU', lat: 41.2753, lon: 28.7519, tier: 1, costIndex: 0.7 },
  { iata: 'KEF', city: 'Reykjavik', country: 'Iceland', cc: 'IS', region: 'EU', lat: 63.985, lon: -22.6056, tier: 3, costIndex: 1.6 },
  { iata: 'EDI', city: 'Edinburgh', country: 'United Kingdom', cc: 'GB', region: 'EU', lat: 55.95, lon: -3.3725, tier: 3, costIndex: 1.25 },
  { iata: 'MAN', city: 'Manchester', country: 'United Kingdom', cc: 'GB', region: 'EU', lat: 53.3654, lon: -2.2728, tier: 2, costIndex: 1.15 },
  { iata: 'NCE', city: 'Nice', country: 'France', cc: 'FR', region: 'EU', lat: 43.6584, lon: 7.2159, tier: 3, costIndex: 1.3 },
  { iata: 'BRU', city: 'Brussels', country: 'Belgium', cc: 'BE', region: 'EU', lat: 50.9014, lon: 4.4844, tier: 2, costIndex: 1.2 },

  // Middle East
  { iata: 'DXB', city: 'Dubai', country: 'United Arab Emirates', cc: 'AE', region: 'ME', lat: 25.2532, lon: 55.3657, tier: 1, costIndex: 1.25 },
  { iata: 'AUH', city: 'Abu Dhabi', country: 'United Arab Emirates', cc: 'AE', region: 'ME', lat: 24.4331, lon: 54.6511, tier: 2, costIndex: 1.15 },
  { iata: 'DOH', city: 'Doha', country: 'Qatar', cc: 'QA', region: 'ME', lat: 25.2731, lon: 51.6081, tier: 1, costIndex: 1.2 },
  { iata: 'RUH', city: 'Riyadh', country: 'Saudi Arabia', cc: 'SA', region: 'ME', lat: 24.9576, lon: 46.6988, tier: 2, costIndex: 1.0 },
  { iata: 'JED', city: 'Jeddah', country: 'Saudi Arabia', cc: 'SA', region: 'ME', lat: 21.6796, lon: 39.1565, tier: 2, costIndex: 0.95 },
  { iata: 'TLV', city: 'Tel Aviv', country: 'Israel', cc: 'IL', region: 'ME', lat: 32.0114, lon: 34.8867, tier: 2, costIndex: 1.35 },
  { iata: 'AMM', city: 'Amman', country: 'Jordan', cc: 'JO', region: 'ME', lat: 31.7226, lon: 35.9932, tier: 3, costIndex: 0.8 },

  // South Asia
  { iata: 'DEL', city: 'New Delhi', country: 'India', cc: 'IN', region: 'SAS', lat: 28.5562, lon: 77.1, tier: 1, costIndex: 0.45 },
  { iata: 'BOM', city: 'Mumbai', country: 'India', cc: 'IN', region: 'SAS', lat: 19.0896, lon: 72.8656, tier: 1, costIndex: 0.5 },
  { iata: 'BLR', city: 'Bengaluru', country: 'India', cc: 'IN', region: 'SAS', lat: 13.1986, lon: 77.7066, tier: 1, costIndex: 0.5 },
  { iata: 'MAA', city: 'Chennai', country: 'India', cc: 'IN', region: 'SAS', lat: 12.9941, lon: 80.1709, tier: 2, costIndex: 0.45 },
  { iata: 'HYD', city: 'Hyderabad', country: 'India', cc: 'IN', region: 'SAS', lat: 17.2403, lon: 78.4294, tier: 2, costIndex: 0.45 },
  { iata: 'CCU', city: 'Kolkata', country: 'India', cc: 'IN', region: 'SAS', lat: 22.6547, lon: 88.4467, tier: 2, costIndex: 0.4 },
  { iata: 'COK', city: 'Kochi', country: 'India', cc: 'IN', region: 'SAS', lat: 10.152, lon: 76.4019, tier: 3, costIndex: 0.4 },
  { iata: 'GOI', city: 'Goa', country: 'India', cc: 'IN', region: 'SAS', lat: 15.3808, lon: 73.8314, tier: 3, costIndex: 0.5 },
  { iata: 'CMB', city: 'Colombo', country: 'Sri Lanka', cc: 'LK', region: 'SAS', lat: 7.1808, lon: 79.8841, tier: 3, costIndex: 0.45 },
  { iata: 'DAC', city: 'Dhaka', country: 'Bangladesh', cc: 'BD', region: 'SAS', lat: 23.8433, lon: 90.3978, tier: 2, costIndex: 0.4 },
  { iata: 'KTM', city: 'Kathmandu', country: 'Nepal', cc: 'NP', region: 'SAS', lat: 27.6966, lon: 85.3591, tier: 3, costIndex: 0.4 },
  { iata: 'ISB', city: 'Islamabad', country: 'Pakistan', cc: 'PK', region: 'SAS', lat: 33.5607, lon: 72.8516, tier: 3, costIndex: 0.4 },
  { iata: 'MLE', city: 'Male', country: 'Maldives', cc: 'MV', region: 'SAS', lat: 4.1918, lon: 73.529, tier: 3, costIndex: 1.5 },

  // East / Southeast Asia
  { iata: 'HND', city: 'Tokyo', country: 'Japan', cc: 'JP', region: 'EAS', lat: 35.5494, lon: 139.7798, tier: 1, costIndex: 1.3 },
  { iata: 'NRT', city: 'Tokyo', country: 'Japan', cc: 'JP', region: 'EAS', lat: 35.772, lon: 140.3929, tier: 1, costIndex: 1.3 },
  { iata: 'KIX', city: 'Osaka', country: 'Japan', cc: 'JP', region: 'EAS', lat: 34.4342, lon: 135.2328, tier: 2, costIndex: 1.15 },
  { iata: 'ICN', city: 'Seoul', country: 'South Korea', cc: 'KR', region: 'EAS', lat: 37.4602, lon: 126.4407, tier: 1, costIndex: 1.1 },
  { iata: 'PEK', city: 'Beijing', country: 'China', cc: 'CN', region: 'EAS', lat: 40.0799, lon: 116.6031, tier: 1, costIndex: 0.75 },
  { iata: 'PVG', city: 'Shanghai', country: 'China', cc: 'CN', region: 'EAS', lat: 31.1443, lon: 121.8083, tier: 1, costIndex: 0.85 },
  { iata: 'CAN', city: 'Guangzhou', country: 'China', cc: 'CN', region: 'EAS', lat: 23.3924, lon: 113.2988, tier: 1, costIndex: 0.7 },
  { iata: 'HKG', city: 'Hong Kong', country: 'Hong Kong', cc: 'HK', region: 'EAS', lat: 22.308, lon: 113.9185, tier: 1, costIndex: 1.35 },
  { iata: 'TPE', city: 'Taipei', country: 'Taiwan', cc: 'TW', region: 'EAS', lat: 25.0797, lon: 121.2342, tier: 1, costIndex: 0.95 },
  { iata: 'SIN', city: 'Singapore', country: 'Singapore', cc: 'SG', region: 'EAS', lat: 1.3644, lon: 103.9915, tier: 1, costIndex: 1.4 },
  { iata: 'BKK', city: 'Bangkok', country: 'Thailand', cc: 'TH', region: 'EAS', lat: 13.69, lon: 100.7501, tier: 1, costIndex: 0.55 },
  { iata: 'HKT', city: 'Phuket', country: 'Thailand', cc: 'TH', region: 'EAS', lat: 8.1132, lon: 98.3169, tier: 3, costIndex: 0.6 },
  { iata: 'KUL', city: 'Kuala Lumpur', country: 'Malaysia', cc: 'MY', region: 'EAS', lat: 2.7456, lon: 101.7099, tier: 1, costIndex: 0.55 },
  { iata: 'CGK', city: 'Jakarta', country: 'Indonesia', cc: 'ID', region: 'EAS', lat: -6.1256, lon: 106.6559, tier: 1, costIndex: 0.5 },
  { iata: 'DPS', city: 'Bali (Denpasar)', country: 'Indonesia', cc: 'ID', region: 'EAS', lat: -8.7482, lon: 115.1672, tier: 2, costIndex: 0.6 },
  { iata: 'MNL', city: 'Manila', country: 'Philippines', cc: 'PH', region: 'EAS', lat: 14.5086, lon: 121.0198, tier: 2, costIndex: 0.5 },
  { iata: 'SGN', city: 'Ho Chi Minh City', country: 'Vietnam', cc: 'VN', region: 'EAS', lat: 10.8188, lon: 106.652, tier: 2, costIndex: 0.45 },
  { iata: 'HAN', city: 'Hanoi', country: 'Vietnam', cc: 'VN', region: 'EAS', lat: 21.2212, lon: 105.8072, tier: 2, costIndex: 0.45 },

  // Oceania
  { iata: 'SYD', city: 'Sydney', country: 'Australia', cc: 'AU', region: 'OC', lat: -33.9399, lon: 151.1753, tier: 1, costIndex: 1.35 },
  { iata: 'MEL', city: 'Melbourne', country: 'Australia', cc: 'AU', region: 'OC', lat: -37.669, lon: 144.841, tier: 1, costIndex: 1.3 },
  { iata: 'BNE', city: 'Brisbane', country: 'Australia', cc: 'AU', region: 'OC', lat: -27.3842, lon: 153.1175, tier: 2, costIndex: 1.2 },
  { iata: 'PER', city: 'Perth', country: 'Australia', cc: 'AU', region: 'OC', lat: -31.9385, lon: 115.9672, tier: 2, costIndex: 1.2 },
  { iata: 'AKL', city: 'Auckland', country: 'New Zealand', cc: 'NZ', region: 'OC', lat: -37.0082, lon: 174.785, tier: 2, costIndex: 1.25 },
  { iata: 'NAN', city: 'Nadi', country: 'Fiji', cc: 'FJ', region: 'OC', lat: -17.7554, lon: 177.4434, tier: 3, costIndex: 0.9 },

  // South America
  { iata: 'GRU', city: 'Sao Paulo', country: 'Brazil', cc: 'BR', region: 'SAM', lat: -23.4356, lon: -46.4731, tier: 1, costIndex: 0.65 },
  { iata: 'GIG', city: 'Rio de Janeiro', country: 'Brazil', cc: 'BR', region: 'SAM', lat: -22.809, lon: -43.2506, tier: 2, costIndex: 0.65 },
  { iata: 'EZE', city: 'Buenos Aires', country: 'Argentina', cc: 'AR', region: 'SAM', lat: -34.8222, lon: -58.5358, tier: 1, costIndex: 0.6 },
  { iata: 'SCL', city: 'Santiago', country: 'Chile', cc: 'CL', region: 'SAM', lat: -33.393, lon: -70.7858, tier: 2, costIndex: 0.75 },
  { iata: 'BOG', city: 'Bogota', country: 'Colombia', cc: 'CO', region: 'SAM', lat: 4.7016, lon: -74.1469, tier: 2, costIndex: 0.55 },
  { iata: 'LIM', city: 'Lima', country: 'Peru', cc: 'PE', region: 'SAM', lat: -12.0219, lon: -77.1143, tier: 2, costIndex: 0.55 },

  // Africa
  { iata: 'CAI', city: 'Cairo', country: 'Egypt', cc: 'EG', region: 'AF', lat: 30.1219, lon: 31.4056, tier: 1, costIndex: 0.4 },
  { iata: 'JNB', city: 'Johannesburg', country: 'South Africa', cc: 'ZA', region: 'AF', lat: -26.1367, lon: 28.2411, tier: 1, costIndex: 0.6 },
  { iata: 'CPT', city: 'Cape Town', country: 'South Africa', cc: 'ZA', region: 'AF', lat: -33.9715, lon: 18.6021, tier: 2, costIndex: 0.65 },
  { iata: 'NBO', city: 'Nairobi', country: 'Kenya', cc: 'KE', region: 'AF', lat: -1.3192, lon: 36.9278, tier: 2, costIndex: 0.55 },
  { iata: 'ADD', city: 'Addis Ababa', country: 'Ethiopia', cc: 'ET', region: 'AF', lat: 8.9779, lon: 38.7993, tier: 2, costIndex: 0.45 },
  { iata: 'LOS', city: 'Lagos', country: 'Nigeria', cc: 'NG', region: 'AF', lat: 6.5774, lon: 3.321, tier: 2, costIndex: 0.6 },
  { iata: 'CMN', city: 'Casablanca', country: 'Morocco', cc: 'MA', region: 'AF', lat: 33.3675, lon: -7.59, tier: 2, costIndex: 0.55 },
  { iata: 'RAK', city: 'Marrakech', country: 'Morocco', cc: 'MA', region: 'AF', lat: 31.6069, lon: -8.0363, tier: 3, costIndex: 0.6 },
  { iata: 'MRU', city: 'Mauritius', country: 'Mauritius', cc: 'MU', region: 'AF', lat: -20.4302, lon: 57.6836, tier: 3, costIndex: 0.9 }
];

const byIata = new Map(AIRPORTS.map(a => [a.iata, a]));

function findAirport(code) {
  return byIata.get(String(code || '').toUpperCase()) || null;
}

function searchAirports(q, limit = 8) {
  const s = String(q || '').trim().toLowerCase();
  if (!s) return [];
  const scored = [];
  for (const a of AIRPORTS) {
    let score = -1;
    if (a.iata.toLowerCase() === s) score = 100;
    else if (a.iata.toLowerCase().startsWith(s)) score = 80;
    else if (a.city.toLowerCase().startsWith(s)) score = 70;
    else if (a.city.toLowerCase().includes(s)) score = 50;
    else if (a.country.toLowerCase().startsWith(s)) score = 30;
    if (score >= 0) scored.push([score - a.tier, a]);
  }
  scored.sort((x, y) => y[0] - x[0]);
  return scored.slice(0, limit).map(([, a]) => a);
}

module.exports = { AIRPORTS, findAirport, searchAirports };
