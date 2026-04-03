from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    slug: str
    description: str
    messages: list[str]


SCENARIOS: list[Scenario] = [
    Scenario(
        slug="next_available_booking",
        description="Book the next available flight with a seat preference.",
        messages=[
            "Book the next available flight from ATH to JFK in business with a window seat.",
            "Book option 1.",
            "Passenger name is Eleni Pappas. Contact email is eleni.pappas@example.com. Date of birth is 1992-04-16.",
            "No extras and no special assistance.",
        ],
    ),
    Scenario(
        slug="pets_policy",
        description="Ask for the airline pet policy.",
        messages=[
            "Are pets permitted on board and under what conditions?",
        ],
    ),
    Scenario(
        slug="cheapest_next_week",
        description="Find the cheapest available flights within the current week of inventory.",
        messages=[
            "Find the cheapest available flights from FCO to ATH within the following week.",
        ],
    ),
]


def get_scenario(slug: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.slug == slug:
            return scenario
    available = ", ".join(sorted(s.slug for s in SCENARIOS))
    raise ValueError(f"Unknown scenario '{slug}'. Available scenarios: {available}")
