// Prefilled deep links into real booking sites. FareForge is a comparison
// layer: when the user hits "Book", we hand them off to trusted providers with
// the search already filled in, so they can complete purchase there.

function skyscannerDate(iso) {
  // 2026-07-20 -> 260720
  return iso.slice(2).replace(/-/g, '');
}

function flightLinks({ from, to, departDate, returnDate, adults }) {
  const gfQuery = `Flights from ${from.iata} to ${to.iata} on ${departDate}` +
    (returnDate ? ` through ${returnDate}` : ' one way');
  const sky = `https://www.skyscanner.com/transport/flights/${from.iata.toLowerCase()}/${to.iata.toLowerCase()}/` +
    `${skyscannerDate(departDate)}/${returnDate ? skyscannerDate(returnDate) + '/' : ''}?adultsv2=${adults}`;
  const kayak = `https://www.kayak.com/flights/${from.iata}-${to.iata}/${departDate}` +
    `${returnDate ? '/' + returnDate : ''}?adults=${adults}`;
  return [
    { site: 'Google Flights', url: `https://www.google.com/travel/flights?q=${encodeURIComponent(gfQuery)}` },
    { site: 'Skyscanner', url: sky },
    { site: 'Kayak', url: kayak }
  ];
}

function hotelLinks({ to, checkin, checkout, adults, hotelName }) {
  const rooms = Math.ceil(adults / 2);
  const ss = hotelName ? `${hotelName}, ${to.city}` : `${to.city}, ${to.country}`;
  const booking = `https://www.booking.com/searchresults.html?` + new URLSearchParams({
    ss, checkin, checkout, group_adults: String(adults), no_rooms: String(rooms), group_children: '0'
  });
  const kayak = `https://www.kayak.com/hotels/${encodeURIComponent(to.city)}/${checkin}/${checkout}/${adults}adults`;
  const expedia = `https://www.expedia.com/Hotel-Search?` + new URLSearchParams({
    destination: `${to.city}, ${to.country}`, startDate: checkin, endDate: checkout, adults: String(adults)
  });
  return [
    { site: 'Booking.com', url: booking },
    { site: 'Kayak', url: kayak },
    { site: 'Expedia', url: expedia }
  ];
}

function carLinks({ to, pickup, dropoff }) {
  const kayak = `https://www.kayak.com/cars/${encodeURIComponent(to.city)}/${pickup}/${dropoff}`;
  const expedia = `https://www.expedia.com/carsearch?` + new URLSearchParams({
    locn: `${to.city} (${to.iata})`, date1: pickup, date2: dropoff
  });
  return [
    { site: 'Kayak Cars', url: kayak },
    { site: 'Expedia Cars', url: expedia },
    { site: 'Rentalcars.com', url: 'https://www.rentalcars.com/' }
  ];
}

module.exports = { flightLinks, hotelLinks, carLinks };
