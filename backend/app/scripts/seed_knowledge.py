from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.knowledge_article import KnowledgeArticle


ARTICLES = (
    {
        "topic": "flight_booking",
        "title": "Book the Next Available Flight",
        "content": (
            "When a caller asks for the next available flight, search scheduled flights by destination airport and "
            "sort by the earliest departure time after the current moment. Offer the lowest available seat class first "
            "unless the caller requests a specific cabin. Confirm the chosen flight number, departure time, origin, "
            "destination, and total price before creating the booking."
        ),
    },
    {
        "topic": "flight_booking",
        "title": "Find the Cheapest Ticket Within the Next Week",
        "content": (
            "For lowest-fare requests, search all scheduled flights to the requested destination over the next seven days "
            "and sort by total price ascending, then by departure time. Offer at least one fallback if the cheapest fare "
            "is sold out or unsuitable, and clearly state date, time, seat class, and fare conditions."
        ),
    },
    {
        "topic": "pets",
        "title": "Pet Policy for Cabin Travel",
        "content": (
            "Small cats and dogs are permitted in the cabin when the combined weight of pet and carrier does not exceed "
            "8 kg. The pet must remain in an approved soft-sided carrier that fits under the seat for the full journey. "
            "Cabin pet space is capacity-controlled and must be requested before departure."
        ),
    },
    {
        "topic": "pets",
        "title": "Pet Policy for Hold Transport and Restrictions",
        "content": (
            "Larger pets may travel as checked special handling items on selected routes if they are transported in an "
            "airline-approved hard carrier. Pets are not accepted in the hold on routes where local temperature or "
            "operational restrictions make transport unsafe. Trained assistance dogs travel free of charge subject to "
            "documentation checks."
        ),
    },
    {
        "topic": "baggage",
        "title": "Cabin and Hold Baggage Allowance",
        "content": (
            "Economy includes one small personal item and one cabin bag up to 8 kg. Premium Economy includes one cabin "
            "bag up to 10 kg and one checked bag up to 23 kg. Business includes two cabin bags up to 10 kg each and two "
            "checked bags up to 32 kg each."
        ),
    },
    {
        "topic": "baggage",
        "title": "Excess Baggage and Special Item Fees",
        "content": (
            "A first additional checked bag is typically charged at 35 EUR on short-haul routes and 70 EUR on long-haul "
            "routes when added before airport check-in. Sports equipment such as golf bags or skis is charged from 55 EUR "
            "per item. Prams and mobility aids can be carried free of charge. Overweight bags above the included limit "
            "may incur additional fees from 20 EUR per 5 kg block, subject to route rules."
        ),
    },
    {
        "topic": "seat_preferences",
        "content": (
            "Seat preferences can be requested at booking time or added later when inventory allows. Window and aisle "
            "requests are handled as preferences and are not guaranteed until check-in or seat assignment. Extra-legroom "
            "seats may require an additional fee and may be restricted for passengers who cannot assist during an evacuation."
        ),
        "title": "Seat Preference Rules",
    },
    {
        "topic": "booking_changes",
        "title": "Rescheduling an Existing Booking",
        "content": (
            "When a caller asks to reschedule, retrieve the booking by reference, confirm the passenger details, and "
            "search for alternative flights on the new requested date or nearby dates. If the change is accepted, keep "
            "a record of the original booking, issue the new confirmed itinerary, and explain any fare difference or "
            "change fee before completing the update."
        ),
    },
    {
        "topic": "booking_changes",
        "title": "Cancellation and Refund Policy",
        "content": (
            "Flexible fares can be cancelled for a full refund up to departure time. Lower promotional fares may be "
            "non-refundable or refunded as travel credit after deduction of any applicable service fee. All cancellation "
            "and refund outcomes must be recorded against the booking, including request date, refund status, and amount."
        ),
    },
    {
        "topic": "special_assistance",
        "title": "Reduced Mobility and Special Assistance",
        "content": (
            "Passengers may request wheelchair assistance, escorted transit through the terminal, priority boarding, and "
            "help with gate transfers. Assistance should be added to the passenger record before departure so airport teams "
            "can prepare. Mobility aids and essential medical equipment travel free of charge subject to safety screening."
        ),
    },
    {
        "topic": "extras",
        "title": "Adding Bags or Special Items to an Existing Booking",
        "content": (
            "Extra checked bags, cabin bags where fare rules allow, sports equipment, prams, pets, and other special items "
            "can be added to an existing booking before departure, subject to route and capacity restrictions. Confirm the "
            "booking reference, the type of extra requested, the quantity, and any related fee before saving the update."
        ),
    },
    {
        "topic": "flight_operations",
        "title": "Check-In Windows, Gate Information, and Flight Status",
        "content": (
            "Online check-in opens 24 hours before departure. Airport desks generally open 3 hours before departure and "
            "close 45 minutes before departure for short-haul flights and 60 minutes before departure for long-haul flights. "
            "Gate and terminal details are shown on the flight record and may change for operational reasons; always return "
            "the latest stored status before quoting gate information."
        ),
    },
)


def main() -> None:
    session = SessionLocal()
    try:
        existing_articles = {
            (article.topic, article.title): article
            for article in session.scalars(select(KnowledgeArticle))
        }
        created = 0
        updated = 0

        for article in ARTICLES:
            key = (article["topic"], article["title"])
            existing = existing_articles.get(key)
            if existing is None:
                new_article = KnowledgeArticle(**article)
                session.add(new_article)
                existing_articles[key] = new_article
                created += 1
                continue

            if (
                existing.topic != article["topic"]
                or existing.content != article["content"]
                or not existing.is_active
            ):
                existing.topic = article["topic"]
                existing.content = article["content"]
                existing.is_active = True
                existing.version += 1
                updated += 1

        session.commit()
        print(f"Seed complete. Inserted {created} knowledge articles and updated {updated}.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
