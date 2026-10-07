---
name: trip-planning
description: "Plan a trip that needs flights or a hotel and find the lowest real cost for it. Searches every airline, OTA and split-ticket combination through LetsFG (MCP server and CLI), checks each candidate flight's on-time record, searches hotels, then runs the /shopping discount pipeline (promo codes, cashback portals, discounted gift cards, net-cost ranking) on the bookable options. Use when Alex says '/trip-planning', 'plan a trip', 'find me flights', 'cheapest flight to', 'how much to fly to', 'find a hotel in', 'where should I stay', 'is this fare good', 'when should I book', 'compare these flights', or wants to price out travel for a concert, wedding, conference or vacation."
---

# /trip-planning

Goal: a trip plan with the lowest real cost for each part, each figure marked as live (from a
search inside its 15-minute window) or estimated. MIST searches and ranks. Alex books and pays.
Do not call a book tool, do not enter passenger or passport data, and do not add a card.

For a backpacking or overnight hike, the route, camps and map come from `/backpacking`. This skill
covers the travel to and from the trailhead, and the hotel night before, when there is one.

## Tools

| Lane | Command | Notes |
| --- | --- | --- |
| Flights, MCP | the `letsfg` server (`https://letsfg.co/mcp`, user scope) | Find the tool names with ToolSearch "letsfg". OAuth: if it answers 401, Alex runs `/mcp` in a terminal session and authenticates `letsfg`. |
| Flights, CLI | `letsfg search MCI LAX 2026-11-20 --return 2026-11-24 --currency USD --json` | Official CLI (`uv tool install letsfg`). Token in `~/.letsfg/config.json`, refreshes itself. The default currency is EUR, so always pass `--currency USD`. Use it from scripts and routines. |
| Flight reliability | `curl -s -X POST https://letsfg.co/api/trips/check-flight -H 'Content-Type: application/json' -d '{"flightCode":"WN1234"}'` | No auth. 5 to 20 s each, so run it only on the 3 to 5 finalists. |
| Hotels | MCP tools `resolve_hotel_city`, `search_hotels` | The CLI has no hotel command. |
| Discounts | `shopping/bin/shop codes <domain>`, `shop best <offers.json>` | The `/shopping` pipeline. Read that skill for steps 3 and 5. |
| Calendar | `/calendar` | Holds for travel days after Alex picks. |

Home airport is MCI. Read the home address from [[user_contact_and_home]] only when ground
travel or drive time to MCI matters.

## 1. Pin the trip

Get these before you search: origin and destination (IATA codes, or every airport in reach, for
example MCI, and also STL or OMA when a fare gap could pay for the drive), dates and how much they
can move, number of travelers, bags, hard limits (latest arrival, no red-eyes, direct only), and
the hotel area. Ask once for anything missing. A search costs credits, so do not search on a
guess.

## 2. Search flights

- Credits: 75 a day, 90 banked. A new search costs 1, more dates or airports on a route you
  just searched cost 0.5, and the same search again costs double. Plan the date and airport
  grid first, then search it once. A 429 says when credits come back.
- A search takes 2 to 3 minutes and expires after 15. A price older than 15 minutes is an
  estimate.
- Offer prices are the total for one person, taxes included. Do not add tax on top.
- **Split tickets** (separate tickets on one trip) are cheaper but carry a risk: if the first
  flight is late, the second airline owes Alex nothing. Rank a split ticket only with a layover
  of 3 hours or more domestic, 4 or more international, and a carry-on-only trip. Mark every
  split itinerary as such in the table.
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

`resolve_hotel_city`, then `search_hotels` for the dates. Each offer states `refundable` and
`free_cancellation_until`. Prefer a refundable rate when the dates can still move. Filter by
the area Alex gave, not by the city. For the area, read reviews from the primary source, and
never rely on a WebSearch synthesis.

## 5. Run the discount pipeline

Follow `/shopping` steps 3 and 5 on every bookable source: airline direct, hotel direct, the
LetsFG offer, and the OTAs (Expedia, Hotels.com, Booking.com) for hotels.

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

## 6. Report

Lead with the recommended plan: each flight (airline, flight number, times, on-time record,
split or not), the hotel (rate type, cancel deadline), the net cost after codes and cashback,
and where to book each part, with a link. Then one table per part with every option you ranked.
Mark live and estimated prices. When the dates can move, give the cheaper alternative date and
the saving. Close with one question when there is a decision (book now or watch the fare, direct
or split).

After Alex picks, add the travel days to the calendar per `/calendar`. Delete `tmp/trip/` files
after the trip is booked.
