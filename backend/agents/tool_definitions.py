from __future__ import annotations

from typing import Any


def _llm_string(description: str, *, enum: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "string", "description": description}
    if enum:
        payload["enum"] = enum
    return payload


def _llm_integer(description: str) -> dict[str, Any]:
    return {"type": "integer", "description": description}


def _constant_string(value: str, description: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "string", "constant_value": value}
    if description:
        payload["description"] = description
    return payload


def _query_schema(properties: dict[str, dict[str, Any]], required: list[str]) -> dict[str, Any]:
    return {"properties": properties, "required": required}


def _tool(
    *,
    name: str,
    description: str,
    url: str,
    method: str,
    path_params_schema: dict[str, dict[str, Any]] | None = None,
    query_params_schema: dict[str, Any] | None = None,
    request_body_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "webhook",
        "name": name,
        "description": description,
        "response_timeout_secs": 20,
        "disable_interruptions": False,
        "force_pre_tool_speech": False,
        "tool_call_sound_behavior": "auto",
        "tool_error_handling_mode": "auto",
        "execution_mode": "immediate",
        "api_schema": {
            "url": url,
            "method": method,
            "path_params_schema": path_params_schema or {},
            "query_params_schema": query_params_schema,
            "request_body_schema": request_body_schema,
            "request_headers": {},
            "content_type": "application/json",
            "auth_connection": None,
        },
    }


def build_tool_definitions(base_url: str) -> list[dict[str, Any]]:
    api_base = base_url.rstrip("/")

    return [
        _tool(
            name="find_next_available_flight",
            description=(
                "Use this tool when the caller wants the next available flight between two airports. "
                "Ask for both origin and destination airport codes before calling. "
                "If the caller asks for a seat class or a seat preference like window, aisle, or extra_legroom, include it. "
                "It returns up to 3 available flights sorted by earliest departure."
            ),
            url=f"{api_base}/api/flights/search",
            method="GET",
            query_params_schema=_query_schema(
                properties={
                    "origin": _llm_string(
                        "Departure airport code such as ATH, LHR, JFK, FCO, CDG, AMS, MAD, FRA, or DXB."
                    ),
                    "destination": _llm_string(
                        "Destination airport code such as ATH, LHR, JFK, FCO, CDG, AMS, MAD, FRA, or DXB."
                    ),
                    "seat_class": _llm_string(
                        "Optional cabin class filter.",
                        enum=["economy", "premium_economy", "business"],
                    ),
                    "seat_preference": _llm_string(
                        "Optional seat preference filter.",
                        enum=["window", "aisle", "extra_legroom"],
                    ),
                    "sort_by": _constant_string("departure_time"),
                    "only_available": _constant_string("true"),
                    "limit": _constant_string("3"),
                },
                required=["origin", "destination"],
            ),
        ),
        _tool(
            name="find_cheapest_flights_next_week",
            description=(
                "Use this tool when the caller asks for the cheapest available tickets between two airports in the currently "
                "available week of inventory. Ask for both origin and destination airport codes before calling. "
                "If the caller asks for a seat class or a seat preference like window, aisle, or extra_legroom, include it. "
                "It returns up to 3 available flights sorted by lowest price."
            ),
            url=f"{api_base}/api/flights/search",
            method="GET",
            query_params_schema=_query_schema(
                properties={
                    "origin": _llm_string("Departure airport code."),
                    "destination": _llm_string("Destination airport code."),
                    "seat_class": _llm_string(
                        "Optional cabin class filter.",
                        enum=["economy", "premium_economy", "business"],
                    ),
                    "seat_preference": _llm_string(
                        "Optional seat preference filter.",
                        enum=["window", "aisle", "extra_legroom"],
                    ),
                    "sort_by": _constant_string("price"),
                    "only_available": _constant_string("true"),
                    "limit": _constant_string("3"),
                },
                required=["origin", "destination"],
            ),
        ),
        _tool(
            name="find_flights_with_seat_preference",
            description=(
                "Use this tool when the caller explicitly wants flights that support a specific seat preference such as "
                "window, aisle, or extra_legroom. Ask for origin, destination, and the requested seat preference before calling. "
                "Include seat_class if the caller specifies economy, premium_economy, or business. "
                "It returns up to 3 available flights sorted by earliest departure."
            ),
            url=f"{api_base}/api/flights/search",
            method="GET",
            query_params_schema=_query_schema(
                properties={
                    "origin": _llm_string("Departure airport code."),
                    "destination": _llm_string("Destination airport code."),
                    "seat_preference": _llm_string(
                        "Requested seat preference.",
                        enum=["window", "aisle", "extra_legroom"],
                    ),
                    "seat_class": _llm_string(
                        "Optional cabin class filter.",
                        enum=["economy", "premium_economy", "business"],
                    ),
                    "sort_by": _constant_string("departure_time"),
                    "only_available": _constant_string("true"),
                    "limit": _constant_string("3"),
                },
                required=["origin", "destination", "seat_preference"],
            ),
        ),
        _tool(
            name="create_flight_booking",
            description=(
                "Use this tool after the caller confirms a flight and provides contact and passenger details. "
                "It creates a booking and returns a booking reference."
            ),
            url=f"{api_base}/api/bookings",
            method="POST",
            request_body_schema={
                "type": "object",
                "properties": {
                    "flight_id": _llm_integer("The selected flight id."),
                    "contact_name": _llm_string("Primary contact full name."),
                    "contact_email": _llm_string("Primary contact email address."),
                    "contact_phone": _llm_string("Primary contact phone number."),
                    "passengers": {
                        "type": "array",
                        "description": "List of passengers to include in the booking.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "first_name": _llm_string("Passenger first name."),
                                "last_name": _llm_string("Passenger last name."),
                                "date_of_birth": _llm_string("Passenger date of birth in YYYY-MM-DD format."),
                                "passenger_type": _llm_string("Passenger type, usually adult or child."),
                                "seat_preference": _llm_string("Optional seat preference such as window, aisle, or extra_legroom."),
                                "assistance_type": _llm_string("Optional assistance type such as wheelchair."),
                                "assistance_notes": _llm_string("Optional assistance notes."),
                                "mobility_assistance_required": {
                                    "type": "boolean",
                                    "description": "Whether mobility assistance is required."
                                },
                            },
                            "required": ["first_name", "last_name"],
                        },
                    },
                    "extras": {
                        "type": "array",
                        "description": "Optional extras to attach at booking time.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "extra_type": _llm_string(
                                    "Extra type such as checked_bag, cabin_bag, sports_equipment, pram, pet, or special_item."
                                ),
                                "quantity": {"type": "integer", "description": "Quantity of this extra."},
                                "price": {"type": "number", "description": "Price for this extra line."},
                                "description": _llm_string("Optional description for the extra."),
                            },
                            "required": ["extra_type", "quantity", "price"],
                        },
                    },
                },
                "required": ["flight_id", "contact_name", "contact_email", "passengers"],
            },
        ),
        _tool(
            name="get_booking_by_reference",
            description=(
                "Use this tool when the caller provides a booking reference and you need to retrieve the current reservation "
                "details before a cancellation, reschedule, or extras change."
            ),
            url=f"{api_base}/api/bookings/{{booking_reference}}",
            method="GET",
            path_params_schema={
                "booking_reference": _llm_string("The booking reference returned at booking time.")
            },
        ),
        _tool(
            name="cancel_booking",
            description=(
                "Use this tool when the caller wants to cancel an existing booking and request a refund or travel credit."
            ),
            url=f"{api_base}/api/bookings/{{booking_reference}}/cancel",
            method="POST",
            path_params_schema={
                "booking_reference": _llm_string("The booking reference to cancel.")
            },
            request_body_schema={
                "type": "object",
                "properties": {
                    "reason": _llm_string("Why the booking is being cancelled."),
                    "refund_status": _llm_string("Refund state such as pending, approved, rejected, or paid."),
                    "refund_amount": {"type": "number", "description": "Refund amount if known."},
                },
                "required": ["reason"],
            },
        ),
        _tool(
            name="reschedule_booking",
            description=(
                "Use this tool after finding a new flight for the caller and confirming they want to move the booking."
            ),
            url=f"{api_base}/api/bookings/{{booking_reference}}/reschedule",
            method="POST",
            path_params_schema={
                "booking_reference": _llm_string("The booking reference to reschedule.")
            },
            request_body_schema={
                "type": "object",
                "properties": {
                    "new_flight_id": _llm_integer("The new selected flight id.")
                },
                "required": ["new_flight_id"],
            },
        ),
        _tool(
            name="add_booking_extras",
            description=(
                "Use this tool when the caller wants to add baggage, sports equipment, a pram, a pet, or another special item "
                "to an existing booking."
            ),
            url=f"{api_base}/api/bookings/{{booking_reference}}/extras",
            method="POST",
            path_params_schema={
                "booking_reference": _llm_string("The booking reference to update.")
            },
            request_body_schema={
                "type": "object",
                "properties": {
                    "extras": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "extra_type": _llm_string(
                                    "Extra type such as checked_bag, cabin_bag, sports_equipment, pram, pet, or special_item."
                                ),
                                "quantity": {"type": "integer", "description": "Quantity of the extra."},
                                "price": {"type": "number", "description": "Price for this extra line."},
                                "description": _llm_string("Optional description for the extra."),
                            },
                            "required": ["extra_type", "quantity", "price"],
                        },
                    }
                },
                "required": ["extras"],
            },
        ),
        _tool(
            name="get_airline_policy",
            description=(
                "Use this tool when the caller asks about airline policies or operational guidance such as pets, baggage, "
                "special assistance, check-in, cancellation and refunds, seat preferences, extras, or booking changes."
            ),
            url=f"{api_base}/api/knowledge/{{topic}}",
            method="GET",
            path_params_schema={
                "topic": _llm_string(
                    "Knowledge topic. Use one of: pets, baggage, special_assistance, flight_operations, booking_changes, seat_preferences, extras, flight_booking."
                )
            },
        ),
        _tool(
            name="get_flight_details",
            description=(
                "Use this tool when the caller asks for operational details about a specific flight such as status, terminal, "
                "gate, check-in windows, or boarding times."
            ),
            url=f"{api_base}/api/flights/{{flight_id}}",
            method="GET",
            path_params_schema={
                "flight_id": _llm_integer("The flight id returned by a flight search result.")
            },
        ),
    ]
