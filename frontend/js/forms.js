import { compactObject } from "./utils.js";

function readRepeaterRows(container) {
  return Array.from(container.querySelectorAll(".repeater-item")).map((item) =>
    Object.fromEntries(
      Array.from(item.querySelectorAll("[data-name]")).map((field) => {
        const key = field.dataset.name;
        const value = field.type === "checkbox" ? field.checked : field.value.trim();
        return [key, value];
      }),
    ),
  );
}

function normalizeExtra(row) {
  return compactObject({
    extra_type: row.extra_type,
    quantity: row.quantity ? Number(row.quantity) : 1,
    price: row.price ? String(Number(row.price).toFixed(2)) : "0.00",
    description: row.description || undefined,
  });
}

export function readFlightFilterParams(form) {
  const formData = new FormData(form);
  return compactObject({
    origin: String(formData.get("origin") || "").trim().toUpperCase() || undefined,
    destination: String(formData.get("destination") || "").trim().toUpperCase() || undefined,
    departure_date: String(formData.get("departure_date") || "").trim() || undefined,
    max_price: String(formData.get("max_price") || "").trim() || undefined,
    seat_class: String(formData.get("seat_class") || "").trim() || undefined,
    sort_by: String(formData.get("sort_by") || "").trim() || undefined,
    only_available: formData.get("only_available") ? "true" : undefined,
  });
}

export function createBookingPayloadFromForm(form) {
  const formData = new FormData(form);
  const passengerList = form.querySelector("#passenger-list");
  const extraList = form.querySelector("#create-extra-list");

  return {
    flight_id: Number(formData.get("flight_id")),
    contact_name: String(formData.get("contact_name") || "").trim(),
    contact_email: String(formData.get("contact_email") || "").trim(),
    contact_phone: String(formData.get("contact_phone") || "").trim() || null,
    passengers: readRepeaterRows(passengerList).map((row) =>
      compactObject({
        first_name: row.first_name,
        last_name: row.last_name,
        date_of_birth: row.date_of_birth || undefined,
        passenger_type: row.passenger_type || "adult",
        seat_preference: row.seat_preference || undefined,
        seat_number: row.seat_number || undefined,
        assistance_type: row.assistance_type || undefined,
        assistance_notes: row.assistance_notes || undefined,
        mobility_assistance_required: Boolean(row.mobility_assistance_required),
      }),
    ),
    extras: readRepeaterRows(extraList)
      .map(normalizeExtra)
      .filter((extra) => extra.extra_type),
  };
}

export function createExtrasPayloadFromForm(form) {
  const extraList = form.querySelector("#extras-list");
  return {
    extras: readRepeaterRows(extraList)
      .map(normalizeExtra)
      .filter((extra) => extra.extra_type),
  };
}

export function readCancelPayloadFromForm(form) {
  const formData = new FormData(form);
  const refundAmount = String(formData.get("refund_amount") || "").trim();

  return compactObject({
    reason: String(formData.get("reason") || "").trim(),
    refund_status: String(formData.get("refund_status") || "").trim(),
    refund_amount: refundAmount ? String(Number(refundAmount).toFixed(2)) : undefined,
  });
}

export function readReschedulePayloadFromForm(form) {
  const formData = new FormData(form);
  return {
    new_flight_id: Number(formData.get("new_flight_id")),
  };
}
