from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


TaskType = Literal[
    "search_available_flights",
    "book_flight",
    "change_booking",
    "add_booking_extras",
    "retrieve_booking",
]


@dataclass(frozen=True)
class CapabilityTask:
    slug: str
    description: str
    goal: str
    task_type: TaskType
    initial_user_intent: str
    evaluation_focus: str
    required_backend_effects: list[str] = field(default_factory=list)
    allowed_tools_hint: list[str] = field(default_factory=list)


TASKS: list[CapabilityTask] = [
    CapabilityTask(
        slug="search_available_flights",
        description="Search available flights by destination, date window, and price preference without completing a booking.",
        goal="The agent should identify suitable available flight options, explain them clearly, and avoid creating a booking.",
        task_type="search_available_flights",
        initial_user_intent="I am comparing flights from FCO to ATH for next week. Show me the cheapest premium economy options, sorted by price, but do not book anything yet.",
        evaluation_focus="Did the agent search effectively, return useful options, and stop short of a booking when the customer only wanted comparison shopping?",
        allowed_tools_hint=["find_cheapest_flights_next_week", "find_next_available_flight"],
    ),
    CapabilityTask(
        slug="book_flight",
        description="Book a flight for one adult after finding a suitable option.",
        goal="The agent should search, collect missing passenger details, confirm the choice, create the booking, and return a booking reference.",
        task_type="book_flight",
        initial_user_intent="Book the next available business-class flight from ATH to JFK for one adult.",
        evaluation_focus="Did the agent gather only the needed information, create the booking successfully, and communicate the result clearly?",
        required_backend_effects=["booking_created"],
        allowed_tools_hint=["find_next_available_flight", "create_flight_booking"],
    ),
    CapabilityTask(
        slug="cancel_or_reschedule_booking",
        description="Reschedule an existing booking to a different flight after checking the current booking date, with cancellation as a fallback if no suitable replacement exists.",
        goal="The agent should retrieve the existing booking first, use the current departure date as the baseline, offer a valid replacement after that date, and complete either the reschedule or cancellation cleanly.",
        task_type="change_booking",
        initial_user_intent="I need to move booking reference TMQ7L5N8 to the next available business-class flight from FCO to ATH after my current booking date. If nothing suitable is available after that date, cancel it instead.",
        evaluation_focus="Did the agent retrieve the booking first, use the current departure date as the search baseline, and then complete the correct reschedule or cancellation outcome?",
        required_backend_effects=["booking_updated"],
        allowed_tools_hint=["get_booking_by_reference", "find_next_available_flight", "reschedule_booking", "cancel_booking"],
    ),
    CapabilityTask(
        slug="add_baggage_or_special_items",
        description="Add baggage or a special item to an existing booking.",
        goal="The agent should retrieve the booking, confirm the requested add-on, update the booking extras, and explain the result.",
        task_type="add_booking_extras",
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
        initial_user_intent="Retrieve booking reference TMQ7L5N8 and tell me the flight details, including status and departure information.",
        evaluation_focus="Did the agent retrieve the correct booking, answer with useful operational details, and avoid making unnecessary changes?",
        allowed_tools_hint=["get_booking_by_reference", "get_flight_details"],
    ),
]


def get_task(slug: str) -> CapabilityTask:
    for task in TASKS:
        if task.slug == slug:
            return task
    available = ", ".join(sorted(task.slug for task in TASKS))
    raise ValueError(f"Unknown testing task '{slug}'. Available tasks: {available}")
