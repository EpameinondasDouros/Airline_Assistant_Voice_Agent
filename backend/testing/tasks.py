from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


TaskType = Literal[
    "search_available_flights",
    "book_flight",
    "change_booking",
    "add_booking_extras",
    "retrieve_booking",
    "policy_lookup",
    "operational_lookup",
]

ResetMode = Literal["always", "once_per_pipeline", "never"]


@dataclass(frozen=True)
class CapabilityTask:
    slug: str
    description: str
    goal: str
    task_type: TaskType
    initial_user_intent: str
    evaluation_focus: str
    reset_mode: ResetMode = "always"
    required_backend_effects: list[str] = field(default_factory=list)
    allowed_tools_hint: list[str] = field(default_factory=list)


TASKS: list[CapabilityTask] = [
    CapabilityTask(
        slug="search_available_flights",
        description="Search available flights by destination, date window, and price preference without completing a booking.",
        goal="The agent should identify suitable available flight options, explain them clearly, and avoid creating a booking.",
        task_type="search_available_flights",
        reset_mode="always",
        initial_user_intent="I am comparing flights from FCO to ATH for next week. Show me the cheapest premium economy options, sorted by price, but do not book anything yet.",
        evaluation_focus="Did the agent search effectively, return useful options, and stop short of a booking when the customer only wanted comparison shopping?",
        allowed_tools_hint=["find_cheapest_flights_next_week", "find_next_available_flight"],
    ),
    CapabilityTask(
        slug="search_cheapest_flights_next_week",
        description="Find the cheapest available tickets within the next week without creating a booking.",
        goal="The agent should use the cheapest-flight flow, present clear fare options, and avoid turning the comparison into a booking.",
        task_type="search_available_flights",
        reset_mode="always",
        initial_user_intent="Find me the cheapest available tickets from ATH to CDG within the next week. I only want to compare options for now, not book anything yet.",
        evaluation_focus="Did the agent use the cheapest-flight search path, return affordable options in a clear format, and stop short of booking?",
        allowed_tools_hint=["find_cheapest_flights_next_week"],
    ),
    CapabilityTask(
        slug="book_flight",
        description="Book a flight for one adult after finding a suitable option.",
        goal="The agent should search, collect missing passenger details, confirm the choice, create the booking, and return a booking reference.",
        task_type="book_flight",
        reset_mode="once_per_pipeline",
        initial_user_intent="Book the next available business-class flight from ATH to JFK for one adult.",
        evaluation_focus="Did the agent gather only the needed information, create the booking successfully, and communicate the result clearly?",
        required_backend_effects=["booking_created"],
        allowed_tools_hint=["find_next_available_flight", "create_flight_booking"],
    ),
    CapabilityTask(
        slug="book_flight_with_seat_preference",
        description="Book a flight while honoring a specific seat preference.",
        goal="The agent should search for a flight that matches the requested route and cabin, capture the seat preference, create the booking, and clearly confirm the seat preference in the final answer.",
        task_type="book_flight",
        reset_mode="once_per_pipeline",
        initial_user_intent="Book the next available economy flight from ATH to CDG for one adult and I want an aisle seat if possible.",
        evaluation_focus="Did the agent keep the seat preference grounded throughout the flow and confirm it in the final booking response?",
        required_backend_effects=["booking_created"],
        allowed_tools_hint=["find_flights_with_seat_preference", "find_next_available_flight", "create_flight_booking"],
    ),
    CapabilityTask(
        slug="book_flight_with_special_assistance",
        description="Book a flight for a passenger who needs reduced-mobility assistance.",
        goal="The agent should collect the relevant assistance need, create the booking successfully, and clearly confirm the assistance request in the final answer.",
        task_type="book_flight",
        reset_mode="once_per_pipeline",
        initial_user_intent="Book the next available business-class flight from ATH to JFK for one adult. I need wheelchair assistance from check-in through boarding.",
        evaluation_focus="Did the agent gather the assistance details needed for the passenger record and keep the response operational and grounded?",
        required_backend_effects=["booking_created"],
        allowed_tools_hint=["find_next_available_flight", "create_flight_booking", "get_airline_policy"],
    ),
    CapabilityTask(
        slug="cancel_or_reschedule_booking",
        description="Reschedule an existing booking to a different flight after checking the current booking date, with cancellation as a fallback if no suitable replacement exists.",
        goal="The agent should retrieve the existing booking first, use the current departure date as the baseline, offer a valid replacement after that date, and complete either the reschedule or cancellation cleanly.",
        task_type="change_booking",
        reset_mode="always",
        initial_user_intent="I need to move booking reference TMQ7L5N8 to the next available business-class flight from FCO to ATH after my current booking date. If nothing suitable is available after that date, cancel it instead.",
        evaluation_focus="Did the agent retrieve the booking first, use the current departure date as the search baseline, and then complete the correct reschedule or cancellation outcome?",
        required_backend_effects=["booking_updated"],
        allowed_tools_hint=["get_booking_by_reference", "find_next_available_flight", "reschedule_booking", "cancel_booking"],
    ),
    CapabilityTask(
        slug="cancel_booking_for_refund",
        description="Cancel an existing booking and request the appropriate refund outcome.",
        goal="The agent should retrieve the existing booking, confirm the cancellation, complete the cancel action, and communicate the refund status clearly.",
        task_type="change_booking",
        reset_mode="always",
        initial_user_intent="Cancel booking reference TMQ7L5N8 and request the available refund.",
        evaluation_focus="Did the agent verify the booking first, obtain confirmation, cancel it correctly, and explain the refund status without inventing data?",
        required_backend_effects=["booking_updated"],
        allowed_tools_hint=["get_booking_by_reference", "cancel_booking", "get_airline_policy"],
    ),
    CapabilityTask(
        slug="add_baggage_or_special_items",
        description="Add baggage or a special item to an existing booking.",
        goal="The agent should retrieve the booking, confirm the requested add-on, update the booking extras, and explain the result.",
        task_type="add_booking_extras",
        reset_mode="always",
        initial_user_intent="Add one extra checked bag to booking reference TMX4A92K.",
        evaluation_focus="Did the agent use the existing booking correctly, confirm the add-on, and persist the change to the booking?",
        required_backend_effects=["booking_updated", "extras_updated"],
        allowed_tools_hint=["get_booking_by_reference", "add_booking_extras"],
    ),
    CapabilityTask(
        slug="retrieve_booking_by_reference",
        description="Retrieve an existing booking by reference and summarize its current details.",
        goal="The agent should find the booking by reference and return clear operational details without mutating the booking.",
        task_type="retrieve_booking",
        reset_mode="always",
        initial_user_intent="Retrieve booking reference TMQ7L5N8 and tell me the flight details, including status and departure information.",
        evaluation_focus="Did the agent retrieve the correct booking, answer with useful operational details, and avoid making unnecessary changes?",
        allowed_tools_hint=["get_booking_by_reference", "get_flight_details"],
    ),
    CapabilityTask(
        slug="enquire_pet_policy",
        description="Answer a customer question about whether pets are allowed and under what conditions.",
        goal="The agent should answer the pet-policy question directly, use grounded policy information, and summarize the key restrictions and conditions clearly.",
        task_type="policy_lookup",
        reset_mode="always",
        initial_user_intent="Are pets allowed on board, and what are the conditions for bringing one?",
        evaluation_focus="Did the agent use the pet policy knowledge correctly and answer with concrete restrictions instead of vague reassurance?",
        allowed_tools_hint=["get_airline_policy"],
    ),
    CapabilityTask(
        slug="enquire_baggage_allowance",
        description="Answer a customer question about baggage allowance and extra fees.",
        goal="The agent should explain the included baggage allowance, distinguish cabin versus hold where relevant, and mention likely extra-fee conditions clearly.",
        task_type="policy_lookup",
        reset_mode="always",
        initial_user_intent="What baggage allowance do I get, including cabin versus hold bags, and what happens if I need an extra bag?",
        evaluation_focus="Did the agent give a grounded baggage answer with allowance details and fee guidance that match the knowledge base?",
        allowed_tools_hint=["get_airline_policy"],
    ),
    CapabilityTask(
        slug="enquire_special_assistance_policy",
        description="Answer a customer question about reduced-mobility or special assistance options.",
        goal="The agent should explain the available assistance options, when to request them, and any important operational constraints clearly.",
        task_type="policy_lookup",
        reset_mode="always",
        initial_user_intent="What help can the airline provide for a passenger with reduced mobility or special needs?",
        evaluation_focus="Did the agent use the special-assistance knowledge correctly and present the operational steps clearly?",
        allowed_tools_hint=["get_airline_policy"],
    ),
    CapabilityTask(
        slug="enquire_flight_status_and_check_in",
        description="Retrieve booking-linked operational details such as flight status, gate, and check-in timing.",
        goal="The agent should use the booking reference to retrieve the booking and flight details, then answer with the current status, gate or terminal details, and check-in guidance.",
        task_type="operational_lookup",
        reset_mode="always",
        initial_user_intent="For booking reference TMQ7L5N8, what is the flight status, which gate should I expect, and when does check-in open and close?",
        evaluation_focus="Did the agent combine booking lookup with operational flight details and return a grounded answer for status, gate, and check-in timing?",
        allowed_tools_hint=["get_booking_by_reference", "get_flight_details", "get_airline_policy"],
    ),
]


def get_task(slug: str) -> CapabilityTask:
    for task in TASKS:
        if task.slug == slug:
            return task
    available = ", ".join(sorted(task.slug for task in TASKS))
    raise ValueError(f"Unknown testing task '{slug}'. Available tasks: {available}")
