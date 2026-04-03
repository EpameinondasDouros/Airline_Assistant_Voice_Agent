from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ExpectedOutcome = Literal["policy_answer", "flight_search", "booking_created", "booking_lookup", "booking_updated"]


@dataclass(frozen=True)
class Scenario:
    slug: str
    description: str
    messages: list[str]
    expected_tools: list[str]
    expected_outcome: ExpectedOutcome
    expected_keywords: list[str]
    mutation_expected: bool = False
    booking_reference_expected: bool = False
    follow_up_question_expected: bool = False


SCENARIOS: list[Scenario] = [
    Scenario(
        slug="next_available_booking",
        description="Book the next available flight to a requested destination.",
        messages=[
            "Book the next available flight from ATH to JFK in business.",
            "Book option 1.",
            "Passenger name is Eleni Pappas. Contact email is eleni.pappas@example.com. Date of birth is 1992-04-16.",
            "No extras and no special assistance.",
        ],
        expected_tools=["find_next_available_flight", "create_flight_booking"],
        expected_outcome="booking_created",
        expected_keywords=["booking", "reference"],
        mutation_expected=True,
        booking_reference_expected=True,
    ),
    Scenario(
        slug="cheapest_next_week_booking",
        description="Find and book the cheapest available ticket within the following week.",
        messages=[
            "Find the cheapest available flights from FCO to ATH within the following week in premium economy.",
            "Book option 1.",
            "Passenger name is Nico Conti. Contact email is nico.conti@example.com. Date of birth is 1989-09-14.",
            "No extras.",
        ],
        expected_tools=["find_cheapest_flights_next_week", "create_flight_booking"],
        expected_outcome="booking_created",
        expected_keywords=["booking", "reference"],
        mutation_expected=True,
        booking_reference_expected=True,
    ),
    Scenario(
        slug="pets_policy",
        description="Enquire whether pets are permitted on board and under what conditions.",
        messages=[
            "Are pets permitted on board and under what conditions?",
        ],
        expected_tools=["get_airline_policy"],
        expected_outcome="policy_answer",
        expected_keywords=["pets", "carrier", "cabin"],
        follow_up_question_expected=True,
    ),
    Scenario(
        slug="reschedule_existing_booking",
        description="Reschedule an existing booking to a different flight.",
        messages=[
            "Reschedule booking reference TMQ7L5N8 to the next available business-class flight from FCO to ATH.",
            "Yes, move me to option 1.",
        ],
        expected_tools=["get_booking_by_reference", "find_next_available_flight", "reschedule_booking"],
        expected_outcome="booking_updated",
        expected_keywords=["rescheduled", "booking"],
        mutation_expected=True,
        booking_reference_expected=True,
    ),
    Scenario(
        slug="baggage_policy",
        description="Enquire about baggage allowance, weight limits, and excess fees.",
        messages=[
            "What is the baggage allowance, cabin versus hold limits, and the excess baggage fees?",
        ],
        expected_tools=["get_airline_policy"],
        expected_outcome="policy_answer",
        expected_keywords=["baggage", "cabin", "fees"],
        follow_up_question_expected=True,
    ),
    Scenario(
        slug="cancel_booking_refund",
        description="Request a refund or cancellation for an existing booking.",
        messages=[
            "Cancel booking reference TMH5Z1P4 and tell me what refund applies.",
            "Yes, go ahead and cancel it.",
        ],
        expected_tools=["get_booking_by_reference", "cancel_booking"],
        expected_outcome="booking_updated",
        expected_keywords=["cancel", "refund"],
        mutation_expected=True,
        booking_reference_expected=True,
    ),
    Scenario(
        slug="booking_with_seat_preference",
        description="Book a flight with a specific seat preference.",
        messages=[
            "I want a flight from ATH to LHR in economy with an aisle seat.",
            "Book option 1.",
            "Passenger name is Dana Kyriakou. Contact email is dana.kyriakou@example.com. Date of birth is 1996-07-22.",
            "No extras.",
        ],
        expected_tools=["find_flights_with_seat_preference", "get_seat_inventory", "create_flight_booking"],
        expected_outcome="booking_created",
        expected_keywords=["booking", "reference"],
        mutation_expected=True,
        booking_reference_expected=True,
    ),
    Scenario(
        slug="booking_with_window_seat",
        description="Book a flight with a window seat and verify seat-specific inventory handling.",
        messages=[
            "I want the next available flight from ATH to LHR in economy with a window seat.",
            "Book option 1.",
            "Passenger name is Marina Theodorou. Contact email is marina.theodorou@example.com. Date of birth is 1993-03-11.",
            "No extras.",
        ],
        expected_tools=["find_flights_with_seat_preference", "get_seat_inventory", "create_flight_booking"],
        expected_outcome="booking_created",
        expected_keywords=["booking", "reference", "window"],
        mutation_expected=True,
        booking_reference_expected=True,
    ),
    Scenario(
        slug="booking_with_extra_legroom",
        description="Book a flight with extra legroom and verify the agent uses the seat inventory.",
        messages=[
            "Find the next available flight from JFK to ATH in business with extra legroom.",
            "Book option 1.",
            "Passenger name is Nikos Vardis. Contact email is nikos.vardis@example.com. Date of birth is 1984-10-02.",
            "No extras.",
        ],
        expected_tools=["find_flights_with_seat_preference", "get_seat_inventory", "create_flight_booking"],
        expected_outcome="booking_created",
        expected_keywords=["booking", "reference", "extra legroom"],
        mutation_expected=True,
        booking_reference_expected=True,
    ),
    Scenario(
        slug="add_extra_bag",
        description="Add an extra bag or special item to an existing booking.",
        messages=[
            "Add one extra checked bag to booking reference TMX4A92K.",
            "Yes, confirm the extra bag.",
        ],
        expected_tools=["get_booking_by_reference", "add_booking_extras"],
        expected_outcome="booking_updated",
        expected_keywords=["checked bag", "booking"],
        mutation_expected=True,
        booking_reference_expected=True,
    ),
    Scenario(
        slug="add_special_item",
        description="Add a special item to an existing booking and verify the booking is updated.",
        messages=[
            "Add a pram to booking reference TMX4A92K.",
            "Yes, confirm it.",
        ],
        expected_tools=["get_booking_by_reference", "add_booking_extras"],
        expected_outcome="booking_updated",
        expected_keywords=["pram", "booking"],
        mutation_expected=True,
        booking_reference_expected=True,
    ),
    Scenario(
        slug="flight_operations_status",
        description="Enquire about check-in times, gate information, or flight status.",
        messages=[
            "For booking reference TMQ7L5N8, what are the check-in times, gate information, and current flight status?",
        ],
        expected_tools=["get_booking_by_reference", "get_flight_details"],
        expected_outcome="booking_lookup",
        expected_keywords=["check-in", "gate", "status"],
        follow_up_question_expected=False,
    ),
    Scenario(
        slug="flight_details_lookup",
        description="Ask for terminal, gate, check-in windows, and boarding times from a booking reference.",
        messages=[
            "For booking reference TMX4A92K, give me the terminal, gate, check-in times, and boarding times.",
        ],
        expected_tools=["get_booking_by_reference", "get_flight_details"],
        expected_outcome="booking_lookup",
        expected_keywords=["terminal", "gate", "check-in", "boarding"],
        follow_up_question_expected=False,
    ),
    Scenario(
        slug="special_assistance_booking",
        description="Request assistance for a passenger with reduced mobility or special needs.",
        messages=[
            "Book the next available flight from JFK to ATH in business for one adult and arrange wheelchair assistance from check-in to boarding.",
            "Book option 1.",
            "Passenger name is Ava Johnson. Contact email is ava.assist@example.com. Date of birth is 1978-08-22.",
            "No extras. Please make sure the mobility assistance is included.",
        ],
        expected_tools=["find_next_available_flight", "create_flight_booking"],
        expected_outcome="booking_created",
        expected_keywords=["booking", "reference"],
        mutation_expected=True,
        booking_reference_expected=True,
    ),
    Scenario(
        slug="special_assistance_wheelchair",
        description="Request wheelchair assistance and confirm the agent captures the assistance details.",
        messages=[
            "Book the next available flight from ATH to JFK in business for one adult and arrange wheelchair assistance from check-in to boarding.",
            "Book option 1.",
            "Passenger name is Eleni Markou. Contact email is eleni.markou@example.com. Date of birth is 1979-05-22.",
            "No extras.",
        ],
        expected_tools=["find_next_available_flight", "create_flight_booking"],
        expected_outcome="booking_created",
        expected_keywords=["booking", "reference", "wheelchair"],
        mutation_expected=True,
        booking_reference_expected=True,
    ),
    Scenario(
        slug="pets_policy_followup",
        description="Ask about pets and verify the assistant asks for the missing aircraft or cabin conditions only if needed.",
        messages=[
            "Can I bring my cat on board?",
        ],
        expected_tools=["get_airline_policy"],
        expected_outcome="policy_answer",
        expected_keywords=["pet", "carrier"],
        follow_up_question_expected=True,
    ),
]


def get_scenario(slug: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.slug == slug:
            return scenario
    available = ", ".join(sorted(s.slug for s in SCENARIOS))
    raise ValueError(f"Unknown scenario '{slug}'. Available scenarios: {available}")
