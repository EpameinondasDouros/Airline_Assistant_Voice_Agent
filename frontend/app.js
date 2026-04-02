import {
  BOOKING_STATUS_OPTIONS,
  EMPTY_API_BASE,
  EXTRA_TYPE_OPTIONS,
  REFUND_STATUS_OPTIONS,
  SCREEN_TITLES,
  SEAT_CLASS_OPTIONS,
} from "./js/constants.js";
import { createApiClient } from "./js/api.js";
import {
  createDetailList,
  createEmptyState,
  createFeedback,
  createJsonBlock,
  createMetaGrid,
  createStatusBadge,
  renderOptionList,
  renderTable,
} from "./js/ui.js";
import {
  createBookingPayloadFromForm,
  createExtrasPayloadFromForm,
  readCancelPayloadFromForm,
  readFlightFilterParams,
  readReschedulePayloadFromForm,
} from "./js/forms.js";
import {
  formatCurrency,
  formatDateTime,
  titleCase,
  setText,
  escapeHtml,
} from "./js/utils.js";

const apiClient = createApiClient();

const state = {
  activeScreen: "dashboard",
  flights: [],
  selectedFlight: null,
  bookings: [],
  selectedBooking: null,
  knowledgeTopics: [],
  knowledgeArticles: [],
  selectedArticle: null,
  lastMutation: null,
};

const elements = {
  sidebar: document.querySelector("#sidebar"),
  sidebarToggle: document.querySelector("#sidebar-toggle"),
  navItems: document.querySelectorAll("[data-nav]"),
  screens: document.querySelectorAll(".screen"),
  pageTitle: document.querySelector("#page-title"),
  apiBaseForm: document.querySelector("#api-config-form"),
  apiBaseInput: document.querySelector("#api-base-input"),
  apiResetButton: document.querySelector("#api-reset-button"),
  feedbackBanner: document.querySelector("#feedback-banner"),
  requestMeta: document.querySelector("#request-meta"),
  apiStatusDot: document.querySelector("#api-status-dot"),
  apiStatusText: document.querySelector("#api-status-text"),
  healthSummary: document.querySelector("#health-summary"),
  healthDetail: document.querySelector("#health-detail"),
  dashboardFlightCount: document.querySelector("#dashboard-flight-count"),
  dashboardFlightDetail: document.querySelector("#dashboard-flight-detail"),
  dashboardBookingCount: document.querySelector("#dashboard-booking-count"),
  dashboardBookingDetail: document.querySelector("#dashboard-booking-detail"),
  dashboardSnapshotList: document.querySelector("#dashboard-snapshot-list"),
  refreshHealth: document.querySelector("#refresh-health"),
  refreshDashboard: document.querySelector("#refresh-dashboard"),
  refreshDashboardFlights: document.querySelector("#refresh-dashboard-flights"),
  refreshDashboardBookings: document.querySelector("#refresh-dashboard-bookings"),
  flightSeatClass: document.querySelector("#flight-seat-class"),
  refundStatusSelect: document.querySelector("#refund-status-select"),
  flightFilters: document.querySelector("#flight-filters"),
  applyFlightFilters: document.querySelector("#apply-flight-filters"),
  resetFlightFilters: document.querySelector("#reset-flight-filters"),
  refreshFlights: document.querySelector("#refresh-flights"),
  flightsTableContainer: document.querySelector("#flights-table-container"),
  flightResultsSummary: document.querySelector("#flight-results-summary"),
  flightDetail: document.querySelector("#flight-detail"),
  bookingLimitInput: document.querySelector("#booking-limit-input"),
  bookingReferenceInput: document.querySelector("#booking-reference-input"),
  lookupBooking: document.querySelector("#lookup-booking"),
  refreshBookings: document.querySelector("#refresh-bookings"),
  resetBookingDetail: document.querySelector("#reset-booking-detail"),
  bookingsTableContainer: document.querySelector("#bookings-table-container"),
  bookingResultsSummary: document.querySelector("#booking-results-summary"),
  bookingDetail: document.querySelector("#booking-detail"),
  passengerList: document.querySelector("#passenger-list"),
  createExtraList: document.querySelector("#create-extra-list"),
  extrasList: document.querySelector("#extras-list"),
  addPassengerButton: document.querySelector("#add-passenger-button"),
  addCreateExtraButton: document.querySelector("#add-create-extra-button"),
  addExtraButton: document.querySelector("#add-extra-button"),
  createBookingForm: document.querySelector("#create-booking-form"),
  addExtrasForm: document.querySelector("#add-extras-form"),
  cancelBookingForm: document.querySelector("#cancel-booking-form"),
  rescheduleBookingForm: document.querySelector("#reschedule-booking-form"),
  resetCreateBooking: document.querySelector("#reset-create-booking"),
  resetAddExtras: document.querySelector("#reset-add-extras"),
  resetCancelBooking: document.querySelector("#reset-cancel-booking"),
  resetRescheduleBooking: document.querySelector("#reset-reschedule-booking"),
  mutationResult: document.querySelector("#mutation-result"),
  knowledgeTopics: document.querySelector("#knowledge-topics"),
  knowledgeArticles: document.querySelector("#knowledge-articles"),
  knowledgeDetail: document.querySelector("#knowledge-detail"),
  knowledgeResultsSummary: document.querySelector("#knowledge-results-summary"),
  knowledgeSearchForm: document.querySelector("#knowledge-search-form"),
  refreshTopics: document.querySelector("#refresh-topics"),
  resetKnowledgeSearch: document.querySelector("#reset-knowledge-search"),
};

function initialize() {
  hydrateApiBase();
  hydrateSelects();
  bindGlobalEvents();
  initializeRepeaters();
  switchScreen("dashboard");
  refreshDashboard();
  loadFlights();
  loadBookings();
  loadKnowledgeTopics();
}

function hydrateApiBase() {
  elements.apiBaseInput.value = apiClient.getBaseUrl();
  renderRequestMeta(apiClient.getLastRequestMeta());
}

function hydrateSelects() {
  renderOptionList(elements.flightSeatClass, SEAT_CLASS_OPTIONS, { includeBlank: true, blankLabel: "Any seat class" });
  renderOptionList(elements.refundStatusSelect, REFUND_STATUS_OPTIONS);
}

function bindGlobalEvents() {
  elements.navItems.forEach((item) => {
    item.addEventListener("click", () => {
      const screen = item.dataset.nav;
      if (screen) {
        switchScreen(screen);
      }
    });
  });

  elements.sidebarToggle.addEventListener("click", () => {
    const isOpen = elements.sidebar.classList.toggle("is-open");
    elements.sidebarToggle.setAttribute("aria-expanded", String(isOpen));
  });

  elements.apiBaseForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const baseUrl = elements.apiBaseInput.value.trim() || EMPTY_API_BASE;
    apiClient.setBaseUrl(baseUrl);
    showFeedback(`API base saved: ${baseUrl}`, "success");
    renderRequestMeta(apiClient.getLastRequestMeta());
    refreshDashboard();
  });

  elements.apiResetButton.addEventListener("click", () => {
    elements.apiBaseInput.value = EMPTY_API_BASE;
    apiClient.setBaseUrl(EMPTY_API_BASE);
    showFeedback(`API base reset to ${EMPTY_API_BASE}`, "success");
    refreshDashboard();
  });

  elements.refreshHealth.addEventListener("click", () => loadHealth());
  elements.refreshDashboard.addEventListener("click", () => refreshDashboard());
  elements.refreshDashboardFlights.addEventListener("click", () => loadDashboardFlights());
  elements.refreshDashboardBookings.addEventListener("click", () => loadDashboardBookings());

  elements.applyFlightFilters.addEventListener("click", () => loadFlights({ useFilters: true }));
  elements.resetFlightFilters.addEventListener("click", () => {
    elements.flightFilters.reset();
    elements.flightFilters.querySelector('[name="only_available"]').checked = true;
    loadFlights();
  });
  elements.refreshFlights.addEventListener("click", () => loadFlights({ useFilters: hasActiveFlightFilters() }));

  elements.refreshBookings.addEventListener("click", () => loadBookings());
  elements.lookupBooking.addEventListener("click", () => {
    const reference = elements.bookingReferenceInput.value.trim();
    if (!reference) {
      showFeedback("Enter a booking reference before fetching booking detail.", "error");
      return;
    }
    loadBookingDetail(reference);
  });
  elements.resetBookingDetail.addEventListener("click", () => {
    state.selectedBooking = null;
    renderBookingDetail();
  });

  elements.createBookingForm.addEventListener("submit", handleCreateBooking);
  elements.addExtrasForm.addEventListener("submit", handleAddExtras);
  elements.cancelBookingForm.addEventListener("submit", handleCancelBooking);
  elements.rescheduleBookingForm.addEventListener("submit", handleRescheduleBooking);

  elements.resetCreateBooking.addEventListener("click", () => resetCreateBookingForm());
  elements.resetAddExtras.addEventListener("click", () => resetExtrasForm());
  elements.resetCancelBooking.addEventListener("click", () => elements.cancelBookingForm.reset());
  elements.resetRescheduleBooking.addEventListener("click", () => elements.rescheduleBookingForm.reset());

  elements.knowledgeSearchForm.addEventListener("submit", handleKnowledgeSearch);
  elements.refreshTopics.addEventListener("click", () => loadKnowledgeTopics());
  elements.resetKnowledgeSearch.addEventListener("click", () => {
    elements.knowledgeSearchForm.reset();
    state.knowledgeArticles = [];
    state.selectedArticle = null;
    renderKnowledgeArticles();
    renderKnowledgeDetail();
    setText(elements.knowledgeResultsSummary, "No topic selected.");
  });
}

function initializeRepeaters() {
  addPassengerRow();
  addExtraRow(elements.createExtraList, "create-extra");
  addExtraRow(elements.extrasList, "extras");

  elements.addPassengerButton.addEventListener("click", () => addPassengerRow());
  elements.addCreateExtraButton.addEventListener("click", () => addExtraRow(elements.createExtraList, "create-extra"));
  elements.addExtraButton.addEventListener("click", () => addExtraRow(elements.extrasList, "extras"));

  elements.passengerList.addEventListener("click", handleRepeaterRemove);
  elements.createExtraList.addEventListener("click", handleRepeaterRemove);
  elements.extrasList.addEventListener("click", handleRepeaterRemove);
}

function switchScreen(screen) {
  state.activeScreen = screen;

  elements.screens.forEach((section) => {
    section.classList.toggle("is-visible", section.dataset.screen === screen);
  });

  elements.navItems.forEach((item) => {
    item.classList.toggle("active", item.dataset.nav === screen);
  });

  setText(elements.pageTitle, SCREEN_TITLES[screen] ?? "Operations Console");
  elements.sidebar.classList.remove("is-open");
  elements.sidebarToggle.setAttribute("aria-expanded", "false");
}

function showFeedback(message, tone = "info") {
  elements.feedbackBanner.className = `feedback-banner ${tone}`;
  elements.feedbackBanner.textContent = message;
  elements.feedbackBanner.classList.remove("hidden");
}

function clearFeedback() {
  elements.feedbackBanner.className = "feedback-banner hidden";
  elements.feedbackBanner.textContent = "";
}

function renderRequestMeta(meta) {
  if (!meta) {
    elements.requestMeta.textContent = "No requests yet.";
    return;
  }

  const parts = [
    `${meta.method} ${meta.path}`,
    meta.status ? `Status ${meta.status}` : "Pending or failed before response",
    meta.durationMs != null ? `${meta.durationMs} ms` : null,
  ].filter(Boolean);
  elements.requestMeta.innerHTML = parts.map((part) => `<div>${escapeHtml(String(part))}</div>`).join("");
}

function updateApiStatus(ok, message) {
  elements.apiStatusDot.className = `status-dot ${ok ? "ok" : "error"}`;
  setText(elements.apiStatusText, message);
}

async function runRequest(fn, options = {}) {
  const { loadingMessage = "Loading...", successMessage, suppressSuccess = false } = options;

  if (loadingMessage) {
    showFeedback(loadingMessage, "info");
  }

  try {
    const result = await fn();
    renderRequestMeta(apiClient.getLastRequestMeta());
    if (successMessage && !suppressSuccess) {
      showFeedback(successMessage, "success");
    } else if (!successMessage) {
      clearFeedback();
    }
    return result;
  } catch (error) {
    renderRequestMeta(apiClient.getLastRequestMeta());
    showFeedback(error.message || "Request failed.", "error");
    throw error;
  }
}

async function refreshDashboard() {
  await Promise.allSettled([loadHealth(), loadDashboardFlights(), loadDashboardBookings()]);
}

async function loadHealth() {
  try {
    const result = await runRequest(() => apiClient.getHealth(), {
      loadingMessage: "Checking backend health...",
      suppressSuccess: true,
    });
    setText(elements.healthSummary, result.status === "ok" ? "Healthy" : "Unexpected");
    setText(elements.healthDetail, `Health payload: ${JSON.stringify(result)}`);
    updateApiStatus(result.status === "ok", result.status === "ok" ? "API reachable" : "Unexpected health payload");
    appendDashboardSnapshot("Health", "success", "GET /health", JSON.stringify(result));
  } catch (error) {
    setText(elements.healthSummary, "Unavailable");
    setText(elements.healthDetail, error.message);
    updateApiStatus(false, "API unreachable");
    appendDashboardSnapshot("Health", "error", "GET /health", error.message);
  }
}

async function loadDashboardFlights() {
  try {
    const flights = await runRequest(() => apiClient.getAdminFlights(), {
      loadingMessage: "Loading admin flights for dashboard...",
      suppressSuccess: true,
    });
    setText(elements.dashboardFlightCount, String(flights.length));
    setText(elements.dashboardFlightDetail, summarizeFlightDataset(flights));
    appendDashboardSnapshot("Flights", "success", "GET /api/admin/flights", `${flights.length} flight records loaded`);
  } catch (error) {
    setText(elements.dashboardFlightCount, "Error");
    setText(elements.dashboardFlightDetail, error.message);
    appendDashboardSnapshot("Flights", "error", "GET /api/admin/flights", error.message);
  }
}

async function loadDashboardBookings() {
  try {
    const bookings = await runRequest(() => apiClient.getAdminBookings({ limit: readBookingLimit() }), {
      loadingMessage: "Loading admin bookings for dashboard...",
      suppressSuccess: true,
    });
    setText(elements.dashboardBookingCount, String(bookings.length));
    setText(elements.dashboardBookingDetail, summarizeBookingDataset(bookings));
    appendDashboardSnapshot("Bookings", "success", "GET /api/admin/bookings", `${bookings.length} booking summaries loaded`);
  } catch (error) {
    setText(elements.dashboardBookingCount, "Error");
    setText(elements.dashboardBookingDetail, error.message);
    appendDashboardSnapshot("Bookings", "error", "GET /api/admin/bookings", error.message);
  }
}

function appendDashboardSnapshot(label, tone, endpoint, detail) {
  const item = document.createElement("div");
  item.className = `snapshot-item ${tone}`;
  item.innerHTML = `
    <div class="snapshot-header">
      <strong>${escapeHtml(label)}</strong>
      ${createStatusBadge(tone === "success" ? "ok" : "error", tone === "success" ? "success" : "error")}
    </div>
    <div class="snapshot-endpoint">${escapeHtml(endpoint)}</div>
    <div class="snapshot-detail">${escapeHtml(detail)}</div>
  `;

  elements.dashboardSnapshotList.prepend(item);
  while (elements.dashboardSnapshotList.children.length > 6) {
    elements.dashboardSnapshotList.removeChild(elements.dashboardSnapshotList.lastChild);
  }
}

async function loadFlights(options = {}) {
  const useFilters = Boolean(options.useFilters);
  const params = useFilters ? readFlightFilterParams(elements.flightFilters) : null;

  try {
    const flights = await runRequest(
      () => (useFilters ? apiClient.searchFlights(params) : apiClient.getAdminFlights()),
      {
        loadingMessage: useFilters ? "Searching flights..." : "Loading admin flights...",
        successMessage: useFilters ? "Flight search updated." : "Flights loaded.",
      },
    );

    state.flights = flights;
    state.selectedFlight = flights[0] ?? null;
    renderFlightsTable();
    renderFlightDetail();
  } catch (error) {
    state.flights = [];
    state.selectedFlight = null;
    renderFlightsTable();
    renderFlightDetail();
  }
}

function renderFlightsTable() {
  if (!state.flights.length) {
    elements.flightsTableContainer.innerHTML = createEmptyState("No flights found for the current query.");
    setText(elements.flightResultsSummary, "0 flights");
    return;
  }

  setText(elements.flightResultsSummary, `${state.flights.length} flights loaded`);
  renderTable(elements.flightsTableContainer, {
    columns: [
      { label: "Flight", render: (flight) => escapeHtml(flight.flight_number) },
      { label: "Route", render: (flight) => `${escapeHtml(flight.origin_airport)} → ${escapeHtml(flight.destination_airport)}` },
      { label: "Departure", render: (flight) => escapeHtml(formatDateTime(flight.departure_time)) },
      { label: "Seat class", render: (flight) => escapeHtml(titleCase(flight.seat_class)) },
      { label: "Price", render: (flight) => escapeHtml(formatCurrency(flight.price)) },
      { label: "Availability", render: (flight) => `${escapeHtml(String(flight.available_seats))} / ${escapeHtml(String(flight.capacity))}` },
      { label: "Status", render: (flight) => createStatusBadge(flight.status, flight.status) },
    ],
    rows: state.flights,
    getRowId: (flight) => String(flight.id),
    isSelected: (flight) => state.selectedFlight?.id === flight.id,
    onRowClick: (flight) => {
      state.selectedFlight = flight;
      renderFlightsTable();
      renderFlightDetail();
    },
  });
}

function renderFlightDetail() {
  const flight = state.selectedFlight;
  if (!flight) {
    elements.flightDetail.className = "detail-panel empty-panel";
    elements.flightDetail.innerHTML = "Select a flight row to inspect the full operational record.";
    return;
  }

  elements.flightDetail.className = "detail-panel";
  elements.flightDetail.innerHTML = `
    <div class="detail-header">
      <div>
        <h4>${escapeHtml(flight.flight_number)}</h4>
        <p>${escapeHtml(flight.origin_airport)} → ${escapeHtml(flight.destination_airport)}</p>
      </div>
      ${createStatusBadge(flight.status, flight.status)}
    </div>
    ${createMetaGrid([
      ["Flight ID", flight.id],
      ["Seat class", titleCase(flight.seat_class)],
      ["Price", formatCurrency(flight.price)],
      ["Capacity", flight.capacity],
      ["Booked seats", flight.booked_seats],
      ["Available seats", flight.available_seats],
      ["Terminal", flight.terminal ?? "—"],
      ["Gate", flight.departure_gate ?? "—"],
      ["Departure", formatDateTime(flight.departure_time)],
      ["Arrival", formatDateTime(flight.arrival_time)],
      ["Check-in opens", formatDateTime(flight.check_in_open_at)],
      ["Check-in closes", formatDateTime(flight.check_in_close_at)],
      ["Boarding starts", formatDateTime(flight.boarding_starts_at)],
      ["Boarding closes", formatDateTime(flight.boarding_closes_at)],
    ])}
    <div class="json-section">
      <h5>Raw payload</h5>
      ${createJsonBlock(flight)}
    </div>
  `;
}

async function loadBookings() {
  try {
    const bookings = await runRequest(() => apiClient.getAdminBookings({ limit: readBookingLimit() }), {
      loadingMessage: "Loading booking summaries...",
      successMessage: "Bookings loaded.",
    });
    state.bookings = bookings;
    renderBookingsTable();
  } catch (error) {
    state.bookings = [];
    renderBookingsTable();
  }
}

function renderBookingsTable() {
  if (!state.bookings.length) {
    elements.bookingsTableContainer.innerHTML = createEmptyState("No booking summaries loaded.");
    setText(elements.bookingResultsSummary, "0 bookings");
    return;
  }

  setText(elements.bookingResultsSummary, `${state.bookings.length} bookings loaded`);
  renderTable(elements.bookingsTableContainer, {
    columns: [
      { label: "Reference", render: (booking) => escapeHtml(booking.booking_reference) },
      { label: "Contact", render: (booking) => escapeHtml(booking.contact_name) },
      { label: "Flight ID", render: (booking) => escapeHtml(String(booking.flight_id)) },
      { label: "Status", render: (booking) => createStatusBadge(booking.status, booking.status) },
      { label: "Total", render: (booking) => escapeHtml(formatCurrency(booking.total_price)) },
      { label: "Created", render: (booking) => escapeHtml(formatDateTime(booking.created_at)) },
      { label: "Updated", render: (booking) => escapeHtml(formatDateTime(booking.updated_at)) },
    ],
    rows: state.bookings,
    getRowId: (booking) => booking.booking_reference,
    isSelected: (booking) => state.selectedBooking?.booking_reference === booking.booking_reference,
    onRowClick: (booking) => loadBookingDetail(booking.booking_reference),
  });
}

async function loadBookingDetail(reference) {
  try {
    const booking = await runRequest(() => apiClient.getBooking(reference), {
      loadingMessage: `Loading booking ${reference}...`,
      successMessage: `Booking ${reference} loaded.`,
    });
    state.selectedBooking = booking;
    elements.bookingReferenceInput.value = reference;
    renderBookingsTable();
    renderBookingDetail();
  } catch (error) {
    state.selectedBooking = null;
    renderBookingDetail();
  }
}

function renderBookingDetail() {
  const booking = state.selectedBooking;
  if (!booking) {
    elements.bookingDetail.className = "detail-panel empty-panel";
    elements.bookingDetail.innerHTML =
      "Select a booking row or fetch by reference to inspect passengers, extras, and events.";
    return;
  }

  elements.bookingDetail.className = "detail-panel";
  const passengerItems = booking.passengers.length
    ? booking.passengers
        .map((passenger) =>
          createDetailList([
            ["Passenger", `${passenger.first_name} ${passenger.last_name}`],
            ["Type", titleCase(passenger.passenger_type)],
            ["DOB", passenger.date_of_birth ?? "—"],
            ["Seat preference", passenger.seat_preference ?? "—"],
            ["Seat number", passenger.seat_number ?? "—"],
            ["Assistance", passenger.assistance_type ?? "—"],
            ["Mobility required", passenger.mobility_assistance_required ? "Yes" : "No"],
          ]),
        )
        .join("")
    : createEmptyState("No passengers on this booking.");

  const extraItems = booking.extras.length
    ? booking.extras
        .map((extra) =>
          createDetailList([
            ["Type", titleCase(extra.extra_type)],
            ["Quantity", extra.quantity],
            ["Price", formatCurrency(extra.price)],
            ["Description", extra.description ?? "—"],
          ]),
        )
        .join("")
    : createEmptyState("No extras added.");

  const eventItems = booking.events.length
    ? booking.events
        .map(
          (event) => `
            <div class="event-item">
              <div class="event-topline">
                ${createStatusBadge(event.event_type, event.event_type)}
                <span>${escapeHtml(formatDateTime(event.event_time))}</span>
              </div>
              <strong>${escapeHtml(event.summary)}</strong>
              <p>${escapeHtml(event.details ?? "No additional details.")}</p>
            </div>
          `,
        )
        .join("")
    : createEmptyState("No events recorded.");

  elements.bookingDetail.innerHTML = `
    <div class="detail-header">
      <div>
        <h4>${escapeHtml(booking.booking_reference)}</h4>
        <p>${escapeHtml(booking.contact_name)} · ${escapeHtml(booking.contact_email)}</p>
      </div>
      ${createStatusBadge(booking.status, booking.status)}
    </div>
    ${createMetaGrid([
      ["Booking ID", booking.id],
      ["Flight ID", booking.flight_id],
      ["Rescheduled from", booking.rescheduled_from_booking_id ?? "—"],
      ["Contact phone", booking.contact_phone ?? "—"],
      ["Total price", formatCurrency(booking.total_price)],
      ["Refund status", titleCase(booking.refund_status)],
      ["Refund amount", booking.refund_amount ? formatCurrency(booking.refund_amount) : "—"],
      ["Cancelled at", formatDateTime(booking.cancelled_at)],
      ["Cancellation reason", booking.cancellation_reason ?? "—"],
      ["Created", formatDateTime(booking.created_at)],
      ["Updated", formatDateTime(booking.updated_at)],
    ])}
    <div class="detail-section">
      <h5>Passengers</h5>
      <div class="card-list">${passengerItems}</div>
    </div>
    <div class="detail-section">
      <h5>Extras</h5>
      <div class="card-list">${extraItems}</div>
    </div>
    <div class="detail-section">
      <h5>Events</h5>
      <div class="events-list">${eventItems}</div>
    </div>
    <div class="json-section">
      <h5>Raw payload</h5>
      ${createJsonBlock(booking)}
    </div>
  `;
}

function handleCreateBooking(event) {
  event.preventDefault();
  const payload = createBookingPayloadFromForm(elements.createBookingForm);
  if (!payload.passengers.length) {
    showFeedback("At least one passenger is required to create a booking.", "error");
    return;
  }

  submitMutation({
    loadingMessage: "Creating booking...",
    request: () => apiClient.createBooking(payload),
    successMessage: "Booking created successfully.",
    onSuccess: (booking) => {
      state.lastMutation = booking;
      renderMutationResult(booking);
      loadBookings();
      if (booking?.booking_reference) {
        loadBookingDetail(booking.booking_reference);
      }
    },
  });
}

function handleAddExtras(event) {
  event.preventDefault();
  const formData = new FormData(elements.addExtrasForm);
  const bookingReference = String(formData.get("booking_reference") || "").trim();
  if (!bookingReference) {
    showFeedback("Booking reference is required to add extras.", "error");
    return;
  }

  const payload = createExtrasPayloadFromForm(elements.addExtrasForm);
  if (!payload.extras.length) {
    showFeedback("Add at least one extra line before submitting extras.", "error");
    return;
  }

  submitMutation({
    loadingMessage: `Adding extras to ${bookingReference}...`,
    request: () => apiClient.addExtras(bookingReference, payload),
    successMessage: "Extras added successfully.",
    onSuccess: (booking) => {
      state.lastMutation = booking;
      renderMutationResult(booking);
      loadBookings();
      loadBookingDetail(booking.booking_reference);
    },
  });
}

function handleCancelBooking(event) {
  event.preventDefault();
  const formData = new FormData(elements.cancelBookingForm);
  const bookingReference = String(formData.get("booking_reference") || "").trim();
  if (!bookingReference) {
    showFeedback("Booking reference is required to cancel a booking.", "error");
    return;
  }

  submitMutation({
    loadingMessage: `Cancelling ${bookingReference}...`,
    request: () => apiClient.cancelBooking(bookingReference, readCancelPayloadFromForm(elements.cancelBookingForm)),
    successMessage: "Booking cancelled successfully.",
    onSuccess: (booking) => {
      state.lastMutation = booking;
      renderMutationResult(booking);
      loadBookings();
      loadBookingDetail(booking.booking_reference);
    },
  });
}

function handleRescheduleBooking(event) {
  event.preventDefault();
  const formData = new FormData(elements.rescheduleBookingForm);
  const bookingReference = String(formData.get("booking_reference") || "").trim();
  if (!bookingReference) {
    showFeedback("Booking reference is required to reschedule.", "error");
    return;
  }

  submitMutation({
    loadingMessage: `Rescheduling ${bookingReference}...`,
    request: () => apiClient.rescheduleBooking(bookingReference, readReschedulePayloadFromForm(elements.rescheduleBookingForm)),
    successMessage: "Booking rescheduled successfully.",
    onSuccess: (result) => {
      state.lastMutation = result;
      renderMutationResult(result);
      loadBookings();
      if (result?.new_booking?.booking_reference) {
        loadBookingDetail(result.new_booking.booking_reference);
      }
    },
  });
}

async function submitMutation({ loadingMessage, request, successMessage, onSuccess }) {
  try {
    const result = await runRequest(request, { loadingMessage, successMessage });
    onSuccess(result);
  } catch (_error) {
    renderMutationResult({ error: apiClient.getLastRequestMeta(), message: elements.feedbackBanner.textContent });
  }
}

function renderMutationResult(payload) {
  elements.mutationResult.className = "detail-panel";
  elements.mutationResult.innerHTML = createJsonBlock(payload);
}

async function loadKnowledgeTopics() {
  try {
    const topics = await runRequest(() => apiClient.getKnowledgeTopics(), {
      loadingMessage: "Loading knowledge topics...",
      suppressSuccess: true,
    });
    state.knowledgeTopics = topics;
    renderKnowledgeTopics();
  } catch (error) {
    state.knowledgeTopics = [];
    renderKnowledgeTopics();
  }
}

function renderKnowledgeTopics() {
  if (!state.knowledgeTopics.length) {
    elements.knowledgeTopics.innerHTML = createEmptyState("No knowledge topics loaded.");
    return;
  }

  elements.knowledgeTopics.innerHTML = state.knowledgeTopics
    .map(
      (topic) => `
        <button class="topic-pill" type="button" data-topic="${escapeHtml(topic)}">
          ${escapeHtml(topic)}
        </button>
      `,
    )
    .join("");

  elements.knowledgeTopics.querySelectorAll("[data-topic]").forEach((button) => {
    button.addEventListener("click", () => loadKnowledgeByTopic(button.dataset.topic));
  });
}

async function loadKnowledgeByTopic(topic) {
  try {
    const articles = await runRequest(() => apiClient.getKnowledgeTopic(topic), {
      loadingMessage: `Loading knowledge topic ${topic}...`,
      successMessage: `Topic ${topic} loaded.`,
    });
    state.knowledgeArticles = articles;
    state.selectedArticle = articles[0] ?? null;
    setText(elements.knowledgeResultsSummary, `${articles.length} articles in topic ${topic}`);
    renderKnowledgeArticles();
    renderKnowledgeDetail();
  } catch (error) {
    state.knowledgeArticles = [];
    state.selectedArticle = null;
    setText(elements.knowledgeResultsSummary, error.message);
    renderKnowledgeArticles();
    renderKnowledgeDetail();
  }
}

function handleKnowledgeSearch(event) {
  event.preventDefault();
  const formData = new FormData(elements.knowledgeSearchForm);
  const query = String(formData.get("q") || "").trim();
  if (query.length < 2) {
    showFeedback("Knowledge search requires at least 2 characters.", "error");
    return;
  }

  runRequest(() => apiClient.searchKnowledge(query), {
    loadingMessage: `Searching knowledge for "${query}"...`,
    successMessage: `Knowledge search updated for "${query}".`,
  })
    .then((articles) => {
      state.knowledgeArticles = articles;
      state.selectedArticle = articles[0] ?? null;
      setText(elements.knowledgeResultsSummary, `${articles.length} search results for "${query}"`);
      renderKnowledgeArticles();
      renderKnowledgeDetail();
    })
    .catch((_error) => {
      state.knowledgeArticles = [];
      state.selectedArticle = null;
      renderKnowledgeArticles();
      renderKnowledgeDetail();
    });
}

function renderKnowledgeArticles() {
  if (!state.knowledgeArticles.length) {
    elements.knowledgeArticles.className = "list-stack empty-panel";
    elements.knowledgeArticles.innerHTML = "No articles loaded.";
    return;
  }

  elements.knowledgeArticles.className = "list-stack";
  elements.knowledgeArticles.innerHTML = state.knowledgeArticles
    .map(
      (article) => `
        <button class="article-row ${state.selectedArticle?.id === article.id ? "active" : ""}" type="button" data-article-id="${article.id}">
          <span class="article-row-topic">${escapeHtml(article.topic)}</span>
          <strong>${escapeHtml(article.title)}</strong>
          <span class="article-row-meta">Version ${escapeHtml(String(article.version))} · ${article.is_active ? "active" : "inactive"}</span>
        </button>
      `,
    )
    .join("");

  elements.knowledgeArticles.querySelectorAll("[data-article-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const articleId = Number(button.dataset.articleId);
      state.selectedArticle = state.knowledgeArticles.find((article) => article.id === articleId) ?? null;
      renderKnowledgeArticles();
      renderKnowledgeDetail();
    });
  });
}

function renderKnowledgeDetail() {
  const article = state.selectedArticle;
  if (!article) {
    elements.knowledgeDetail.className = "detail-panel empty-panel";
    elements.knowledgeDetail.innerHTML = "Select an article to inspect its title, topic, content, and version.";
    return;
  }

  elements.knowledgeDetail.className = "detail-panel";
  elements.knowledgeDetail.innerHTML = `
    <div class="detail-header">
      <div>
        <h4>${escapeHtml(article.title)}</h4>
        <p>${escapeHtml(article.topic)}</p>
      </div>
      ${createStatusBadge(article.is_active ? "active" : "inactive", article.is_active ? "active" : "inactive")}
    </div>
    ${createMetaGrid([
      ["Article ID", article.id],
      ["Topic", article.topic],
      ["Version", article.version],
      ["Active", article.is_active ? "Yes" : "No"],
    ])}
    <div class="detail-section">
      <h5>Content</h5>
      <div class="article-content">${escapeHtml(article.content).replace(/\n/g, "<br />")}</div>
    </div>
    <div class="json-section">
      <h5>Raw payload</h5>
      ${createJsonBlock(article)}
    </div>
  `;
}

function addPassengerRow() {
  const index = elements.passengerList.children.length;
  const row = document.createElement("div");
  row.className = "repeater-item";
  row.innerHTML = `
    <div class="repeater-header">
      <strong>Passenger ${index + 1}</strong>
      ${index > 0 ? '<button class="button button-secondary repeater-remove" type="button">Remove</button>' : ""}
    </div>
    <div class="form-grid">
      <label>
        <span class="field-label">First name</span>
        <input data-name="first_name" type="text" required />
      </label>
      <label>
        <span class="field-label">Last name</span>
        <input data-name="last_name" type="text" required />
      </label>
      <label>
        <span class="field-label">Date of birth</span>
        <input data-name="date_of_birth" type="date" />
      </label>
      <label>
        <span class="field-label">Passenger type</span>
        <input data-name="passenger_type" type="text" value="adult" />
      </label>
      <label>
        <span class="field-label">Seat preference</span>
        <input data-name="seat_preference" type="text" placeholder="window" />
      </label>
      <label>
        <span class="field-label">Seat number</span>
        <input data-name="seat_number" type="text" placeholder="12A" />
      </label>
      <label>
        <span class="field-label">Assistance type</span>
        <input data-name="assistance_type" type="text" />
      </label>
      <label>
        <span class="field-label">Assistance notes</span>
        <input data-name="assistance_notes" type="text" />
      </label>
      <label class="checkbox-row">
        <input data-name="mobility_assistance_required" type="checkbox" />
        <span>Mobility assistance required</span>
      </label>
    </div>
  `;
  elements.passengerList.appendChild(row);
}

function addExtraRow(container, prefix) {
  const row = document.createElement("div");
  row.className = "repeater-item";
  row.innerHTML = `
    <div class="repeater-header">
      <strong>Extra</strong>
      <button class="button button-secondary repeater-remove" type="button">Remove</button>
    </div>
    <div class="form-grid">
      <label>
        <span class="field-label">Type</span>
        <select data-name="extra_type">
          <option value="">Select extra type</option>
          ${EXTRA_TYPE_OPTIONS.map(
          (option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`,
        ).join("")}
        </select>
      </label>
      <label>
        <span class="field-label">Quantity</span>
        <input data-name="quantity" type="number" min="1" step="1" value="1" />
      </label>
      <label>
        <span class="field-label">Price</span>
        <input data-name="price" type="number" min="0" step="0.01" value="0" />
      </label>
      <label>
        <span class="field-label">Description</span>
        <input data-name="description" type="text" placeholder="${prefix === "extras" ? "Skis" : "23kg checked bag"}" />
      </label>
    </div>
  `;
  container.appendChild(row);
}

function handleRepeaterRemove(event) {
  const button = event.target.closest(".repeater-remove");
  if (!button) {
    return;
  }

  const item = button.closest(".repeater-item");
  if (item?.parentElement?.children.length > 1) {
    item.remove();
  }
}

function resetCreateBookingForm() {
  elements.createBookingForm.reset();
  elements.passengerList.innerHTML = "";
  elements.createExtraList.innerHTML = "";
  addPassengerRow();
  addExtraRow(elements.createExtraList, "create-extra");
}

function resetExtrasForm() {
  elements.addExtrasForm.reset();
  elements.extrasList.innerHTML = "";
  addExtraRow(elements.extrasList, "extras");
}

function readBookingLimit() {
  const value = Number(elements.bookingLimitInput.value);
  return Number.isFinite(value) && value > 0 ? value : 100;
}

function hasActiveFlightFilters() {
  const params = readFlightFilterParams(elements.flightFilters);
  return Object.keys(params).length > 0;
}

function summarizeFlightDataset(flights) {
  if (!flights.length) {
    return "No flights returned.";
  }

  const scheduled = flights.filter((flight) => flight.status === "scheduled").length;
  const cancelled = flights.filter((flight) => flight.status === "cancelled").length;
  return `${scheduled} scheduled, ${cancelled} cancelled.`;
}

function summarizeBookingDataset(bookings) {
  if (!bookings.length) {
    return "No bookings returned.";
  }

  const byStatus = BOOKING_STATUS_OPTIONS.map((status) => {
    const count = bookings.filter((booking) => booking.status === status.value).length;
    return `${count} ${status.label.toLowerCase()}`;
  });
  return byStatus.join(", ");
}

initialize();
