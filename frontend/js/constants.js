export const EMPTY_API_BASE = "http://localhost:8000";

export const SCREEN_TITLES = {
  concierge: "Concierge",
  dashboard: "Dashboard",
  flights: "Flights",
  bookings: "Bookings",
  actions: "Booking Actions",
  knowledge: "Knowledge",
};

export const CHAT_SUGGESTIONS = [
  "Find me the cheapest flight this week",
  "Change my booking",
  "Add a ski bag",
  "What time does check-in open?",
  "Request wheelchair assistance",
];

export const SEAT_CLASS_OPTIONS = [
  { value: "economy", label: "Economy" },
  { value: "premium_economy", label: "Premium Economy" },
  { value: "business", label: "Business" },
];

export const BOOKING_STATUS_OPTIONS = [
  { value: "confirmed", label: "Confirmed" },
  { value: "cancelled", label: "Cancelled" },
  { value: "rescheduled", label: "Rescheduled" },
];

export const REFUND_STATUS_OPTIONS = [
  { value: "not_requested", label: "Not requested" },
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "paid", label: "Paid" },
];

export const EXTRA_TYPE_OPTIONS = [
  { value: "checked_bag", label: "Checked bag" },
  { value: "cabin_bag", label: "Cabin bag" },
  { value: "sports_equipment", label: "Sports equipment" },
  { value: "pram", label: "Pram" },
  { value: "pet", label: "Pet" },
  { value: "special_item", label: "Special item" },
];
