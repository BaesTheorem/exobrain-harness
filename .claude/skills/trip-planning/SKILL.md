---
name: trip-planning
description: "Plan a trip and find the lowest real cost for each part: flights, hotels, vacation rentals and rental cars. Searches flights through LetsFG, Kiwi, Skiplagged and Google Flights (fli), including split tickets and cheapest-date calendars; checks each finalist flight's on-time record; searches hotels through trivago, Skiplagged, LetsFG and Airbnb; prices rental cars through OctoTrip, Skiplagged and Gondola plus Costco Travel and AutoSlash; then runs the /shopping discount pipeline (promo codes, cashback portals, discounted gift cards, net-cost ranking). Use when Alex says '/trip-planning', 'plan a trip', 'find me flights', 'cheapest flight to', 'how much to fly to', 'cheapest dates to fly', 'find a hotel in', 'where should I stay', 'rent a car', 'rental car in', 'is this fare good', 'when should I book', 'compare these flights', or wants to price out travel for a concert, wedding, conference or vacation."
---

# /trip-planning

Goal: a trip plan with the lowest real cost for each part, each figure marked as live (from a
search inside its 15-minute window) or estimated. MIST searches and ranks. Alex books and pays.
Do not call a book tool, do not enter passenger or passport data, and do not add a card.

For a backpacking or overnight hike, the route, camps and map come from `/backpacking`. This skill
covers the travel to and from the trailhead, and the hotel night before, when there is one.

## Tools

All MCP servers below are registered at user scope. Find their tool names with ToolSearch
(`letsfg`, `kiwi`, `skiplagged`, `trivago`, `fli`, `airbnb`). Each source does one job best:

| Job | Best source | Second source |
| --- | --- | --- |
| Cheapest dates in a range | `fli dates MCI LAX --from 2026-11-01 --to 2026-11-30 -d 4 --round` (Google Flights, free, no credits) | Skiplagged `sk_flex_departure_calendar`, `sk_flex_return_calendar` |
| Fares on fixed dates | LetsFG (all airlines and OTAs, split tickets, Starlink data) | fli `flights`, Skiplagged `sk_flights_search` |
| Split tickets | LetsFG | Kiwi `search-flight` (Kiwi Guarantee covers a missed connection) |
| "Where can I go cheaply" | Skiplagged `sk_destinations_anywhere` | |
| Flight on-time record | LetsFG `check-flight` (below) | |
| Hotels | trivago (metasearch, radius search around a venue) | Skiplagged `sk_hotels_search` + `sk_hotel_details`, LetsFG `search_hotels` |
| Hotel price trend by month | trivago `trivago-destination-price-trends` | |
| Vacation rentals | `airbnb` MCP (runs with `--ignore-robots-txt`) | |
| Rental cars | `octotrip-cars` `search` (live DiscoverCars prices, no auth) | `gondola` (free account), `skiplagged` `sk_cars_search`, step 5 manual lanes |
| Discounts | `shopping/bin/shop codes <domain>`, `shop best <offers.json>` (the `/shopping` pipeline) | |
| Calendar | `/calendar`, for travel days after Alex picks | |

Access notes:

- **LetsFG CLI**: `letsfg search MCI LAX 2026-11-20 --return 2026-11-24 --currency USD --json`.
  Token in `~/.letsfg/config.json`, refreshes itself. The default currency is EUR, so always pass
  `--currency USD`. Use the CLI from scripts and routines. The CLI has no hotel command.
- **LetsFG MCP** needs its own OAuth. If it answers 401, re-run the login (see
  [[reference_mcp_login_from_console]]: `claude mcp login letsfg --no-browser` inside `script`).
- **Flight reliability**: `curl -s -X POST https://letsfg.co/api/trips/check-flight -H
  'Content-Type: application/json' -d '{"flightCode":"WN1234"}'`. No auth. 5 to 20 s each, so run
  it only on the 3 to 5 finalists.
- **fli** reads Google Flights without an official API (`uv tool install 'flights[mcp]' --with
  click`, because the package omits `click`). When it fails or its price disagrees with LetsFG,
  trust LetsFG and the airline's own page.
- **Kiwi, Skiplagged, trivago, OctoTrip** are hosted servers with no auth.
- **Gondola** needs a free account (OAuth). Its server rejects Claude Code's default loopback
  port, so the server is registered with its own client (`--client-id gond_mcp_...
  --callback-port 47615`). If the token is lost, run `claude mcp login gondola`; do not remove
  and re-add the server without those two flags. It can also book, cancel and look up
  a card's rental cover; this skill uses only its search and cover tools.

Home airport is MCI. Read the home address from [[user_contact_and_home]] only when ground
travel or drive time to MCI matters.

## 1. Pin the trip

Get these before you search: origin and destination (IATA codes, or every airport in reach, for
example MCI, and also STL or OMA when a fare gap could pay for the drive), dates and how much they
can move, number of travelers, bags, hard limits (latest arrival, no red-eyes, direct only), and
the hotel area. Ask once for anything missing. A search costs credits, so do not search on a
guess.

## 2. Search flights

- When the dates can move, start with `fli dates` (free) to find the cheap days, then spend
  LetsFG credits only on those days.
- Run the fixed-date search on LetsFG and on one second source (fli or Skiplagged). When the
  two disagree by more than approximately $15, open the airline's own page for the truth.
- LetsFG credits: 75 a day, 90 banked. A new search costs 1, more dates or airports on a route you
  just searched cost 0.5, and the same search again costs double. Plan the date and airport
  grid first, then search it once. A 429 says when credits come back.
- A search takes 2 to 3 minutes and expires after 15. A price older than 15 minutes is an
  estimate.
- Offer prices are the total for one person, taxes included. Do not add tax on top.
- **Split tickets** (separate tickets on one trip) are cheaper but carry a risk: if the first
  flight is late, the second airline owes Alex nothing. Rank a split ticket only with a layover
  of 3 hours or more domestic, 4 or more international, and a carry-on-only trip. Mark every
  split itinerary as such in the table.
- **Hidden-city fares** (Skiplagged: the ticket goes past the city where Alex gets off) are
  one-way only, with no checked bag, and the airline can cancel the rest of the trip or close a
  loyalty account when it finds out. Show one only when it saves a large amount, mark it
  "hidden city" in the table, and never put it in a round trip.
- **Starlink**: state "confirmed_all" as a fact. Describe "likely_*" as "rolling out on this
  aircraft type, not guaranteed".

## 3. Check the finalists

For the 3 to 5 offers that Alex can actually choose, run the reliability check on every flight
number. Two fares at the same price are not equal when one flight averages a 15-minute delay or
cancels 5% of the time. On a connection, compare the average arrival delay of the first flight
with the layover length.

Then check the airline's own site for the same flights. Booking direct makes changes,
cancellations and irregular operations simpler. When the direct fare is within approximately
$20 of the LetsFG fare, recommend the direct booking.

## 4. Search hotels

- Start with trivago. When the trip has a fixed place (a venue, a trailhead, a wedding), use
  `trivago-accommodation-radius-search` around its coordinates, not the city search.
- When the dates can move, `trivago-destination-price-trends` shows which month or week is
  cheaper.
- Check the 3 to 5 best hotels on Skiplagged (`sk_hotel_details` gives the room-level rate) and
  on LetsFG (`resolve_hotel_city`, then `search_hotels`). LetsFG offers state `refundable` and
  `free_cancellation_until`.
- For a group or a stay of 4 or more nights, also search the `airbnb` MCP. Add the cleaning and
  service fees to the nightly rate before you compare.
- Prefer a refundable rate when the dates can still move. For the area, read reviews from the
  primary source, and never rely on a WebSearch synthesis.

## 5. Search rental cars

- Get the baseline from `octotrip-cars` `search`: total, per day, pay now or later, vendor,
  free cancellation, deposit. Its booking links carry an affiliate tag, so book through the
  vendor or the cheapest source, not through the link by default.
- Compare with Skiplagged `sk_cars_search` and, when Alex has signed in, Gondola
  `search_vehicles`.
- Price the airport and one off-airport branch in the city. Airport fees often make the
  off-airport branch cheaper by more than the ride costs.
- Manual lanes that no tool reaches, for Alex to check:
  - **Costco Travel** (members only): waives one additional driver fee, no cancellation fee.
    Akamai blocks every headless route, so it is a link for Alex, never a scrape.
  - **AutoSlash** (free, e-mail): applies coupons and membership codes to a quote, and tracks a
    booked rental for price drops when given the confirmation number.
  - **Turo**: no API. Give Alex the search link when a peer rental can beat the counters.
- **Cover**: before Alex pays for the counter CDW, find out whether the card Alex pays with gives
  primary rental cover (the issuer's benefits page, or Gondola `credit_card_coverage`). Never
  assume which card he holds; ask once.
- Prefer pay-later with free cancellation, then rebook if AutoSlash finds a lower price.

## 6. Run the discount pipeline

Follow `/shopping` steps 3 and 5 on every bookable source: airline direct, hotel direct, the
LetsFG offer, the OTAs (Expedia, Hotels.com, Booking.com) for hotels, and the rental vendors.

- **Codes:** `shop codes <domain>` for hotel brands and OTAs. Airline promo codes are rare and
  usually come from the airline's e-mail list, so check the airline's deals page.
- **Cashback portals:** Rakuten, TopCashback and BeFrugal pay on OTAs and on many hotel brands.
  Airlines usually pay 0%. Read the rate from the portal's store page.
- **Discounted gift cards:** CardCash, Raise and GCX sell Southwest, hotel brand and Hotels.com
  cards at a discount. A gift card cannot be refunded to a card, so use one only on a booking
  that will not change.
- **Programs:** the hotel's member rate (free, usually 5 to 10%), Southwest's free bags and
  free changes, a fare's own change fee. Put the value of a free change into the notes column,
  not into the net cost.

Write `tmp/trip/<trip-slug>.json` in the `shop best` schema (one offer for each bookable option,
`tax_rate: 0` for flights because the price includes tax, the hotel's tax rate from its own
checkout page), then run `shopping/bin/shop best tmp/trip/<trip-slug>.json`.

## 7. Report

Lead with the recommended plan: each flight (airline, flight number, times, on-time record,
split or not), the hotel (rate type, cancel deadline), the car (vendor, pickup place, cancel
terms, cover), the net cost after codes and cashback,
and where to book each part, with a link. Then one table per part with every option you ranked.
Mark live and estimated prices. When the dates can move, give the cheaper alternative date and
the saving. Close with one question when there is a decision (book now or watch the fare, direct
or split).

After Alex picks, add the travel days to the calendar per `/calendar`. Delete `tmp/trip/` files
after the trip is booked.
