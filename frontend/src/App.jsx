import { useEffect, useMemo, useState } from "react";
import {
  createBooking,
  getChatHistory,
  getTestingRun,
  listFlights,
  listTestingRuns,
  listTestingScenarios,
  runTestingScenario,
  searchFlights,
  sendChatMessage,
} from "./api";

function uniqueFlights(items) {
  const byKey = new Map();
  for (const item of items) {
    const key = `${item.flight_number}:${item.departure_time}`;
    const existing = byKey.get(key);
    if (!existing || Number(item.price) < Number(existing.price)) {
      byKey.set(key, item);
    }
  }
  return Array.from(byKey.values());
}

function formatFlightDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return date.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

function formatTimestamp(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatJson(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function normalizeChatHistory(items) {
  return items.map((item) => ({ role: item.role, text: item.content, createdAt: item.created_at }));
}

function getTestingConversationTurns(run) {
  const topLevelTranscript = run?.transcript;
  if (Array.isArray(topLevelTranscript) && topLevelTranscript.length) {
    return topLevelTranscript.map((item, index) => ({
      key: `${item.role || "turn"}-${item.timestamp || index}`,
      role: item.role || "unknown",
      text: item.text || item.message || item.original_message || "",
      time: item.timestamp || item.time_in_call_secs || null,
      meta: Array.isArray(item.tool_calls) ? item.tool_calls.map((toolCall) => toolCall.tool_name).filter(Boolean) : [],
    }));
  }

  const elevenLabsTranscript = run?.elevenlabs_conversation?.transcript;
  if (Array.isArray(elevenLabsTranscript) && elevenLabsTranscript.length) {
    return elevenLabsTranscript.map((item, index) => ({
      key: `${item.role || "turn"}-${item.time_in_call_secs ?? index}`,
      role: item.role || "unknown",
      text: item.message || item.original_message || "",
      time: item.time_in_call_secs ?? null,
      meta: Array.isArray(item.tool_calls) ? item.tool_calls.map((toolCall) => toolCall.tool_name).filter(Boolean) : [],
    }));
  }

  return [];
}

function safeJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

const SEAT_LAYOUTS = {
  economy: {
    rows: Array.from({ length: 20 }, (_, index) => index + 1),
    columns: ["A", "B", "C", "D", "E", "F"],
    windowColumns: new Set(["A", "F"]),
    aisleColumns: new Set(["C", "D"]),
    extraLegroomRows: new Set([18, 19, 20]),
  },
  premium_economy: {
    rows: Array.from({ length: 5 }, (_, index) => index + 21),
    columns: ["A", "B", "C", "D", "E", "F"],
    windowColumns: new Set(["A", "F"]),
    aisleColumns: new Set(["C", "D"]),
    extraLegroomRows: new Set([21, 22, 23, 24, 25]),
  },
  business: {
    rows: Array.from({ length: 4 }, (_, index) => index + 25),
    columns: ["A", "B", "C", "D"],
    windowColumns: new Set(["A", "D"]),
    aisleColumns: new Set(["B", "C"]),
    extraLegroomRows: new Set([25, 26, 27, 28]),
  },
};

const FULL_PLANE_ROWS = Array.from({ length: 29 }, (_, index) => index + 1);
const FULL_PLANE_COLUMNS = ["A", "B", "C", "D", "E", "F"];

function normalizeSeatClass(value) {
  return String(value || "").toLowerCase();
}

function seatMetadata(seatClass, seatNumber) {
  const layout = SEAT_LAYOUTS[normalizeSeatClass(seatClass)];
  if (!layout || !seatNumber) return { valid: false, window: false, aisle: false, extraLegroom: false };
  const trimmed = String(seatNumber).toUpperCase().trim();
  const row = Number(trimmed.replace(/[^0-9]/g, ""));
  const column = trimmed.replace(/[0-9]/g, "").slice(-1);
  const valid = layout.rows.includes(row) && layout.columns.includes(column);
  return {
    valid,
    window: valid && layout.windowColumns.has(column),
    aisle: valid && layout.aisleColumns.has(column),
    extraLegroom: valid && layout.extraLegroomRows.has(row),
  };
}

function buildSeatNumber(flightClass, row, column) {
  const seatClass = normalizeSeatClass(flightClass);
  const layout = SEAT_LAYOUTS[seatClass];
  if (!layout || !layout.rows.includes(row) || !layout.columns.includes(column)) return "";
  return `${row}${column}`;
}

function getSeatAvailabilityForPlane(row, column, seatClass) {
  const className = normalizeSeatClass(seatClass);
  if (row >= 1 && row <= 4) {
    return {
      exists: ["A", "B", "C", "D"].includes(column),
      active: className === "business",
      extraLegroom: true,
    };
  }
  if (row >= 5 && row <= 9) {
    return {
      exists: FULL_PLANE_COLUMNS.includes(column),
      active: className === "premium_economy",
      extraLegroom: true,
    };
  }
  if (row >= 10 && row <= 26) {
    return {
      exists: FULL_PLANE_COLUMNS.includes(column),
      active: className === "economy",
      extraLegroom: false,
    };
  }
  if (row >= 27 && row <= 29) {
    return {
      exists: FULL_PLANE_COLUMNS.includes(column),
      active: className === "economy",
      extraLegroom: true,
    };
  }
  return { exists: false, active: false, extraLegroom: false };
}

function getDefaultSeatForFlight(flight, preference = "") {
  const seatClass = normalizeSeatClass(flight.seat_class);
  const layout = SEAT_LAYOUTS[seatClass];
  if (!layout) return "";
  const occupied = new Set((flight.occupied_seat_numbers || []).map((seat) => String(seat).toUpperCase()));
  const pref = String(preference || "").toLowerCase();
  const orderedRows = pref === "extra_legroom"
    ? [...layout.rows].filter((row) => layout.extraLegroomRows.has(row)).concat([...layout.rows].filter((row) => !layout.extraLegroomRows.has(row)))
    : [...layout.rows];
  const orderedColumns = pref === "window"
    ? [...layout.columns.filter((col) => layout.windowColumns.has(col)), ...layout.columns.filter((col) => !layout.windowColumns.has(col))]
    : pref === "aisle"
      ? [...layout.columns.filter((col) => layout.aisleColumns.has(col)), ...layout.columns.filter((col) => !layout.aisleColumns.has(col))]
      : layout.columns;
  for (const row of orderedRows) {
    for (const column of orderedColumns) {
      const candidate = buildSeatNumber(seatClass, row, column);
      if (candidate && !occupied.has(candidate)) return candidate;
    }
  }
  return "";
}

function getSeatTypeLabel(seatClass, seatNumber) {
  const meta = seatMetadata(seatClass, seatNumber);
  const parts = [];
  if (meta.window) parts.push("Window");
  if (meta.aisle) parts.push("Aisle");
  if (meta.extraLegroom) parts.push("Extra legroom");
  return parts.length ? parts.join(" · ") : "Standard";
}

function getCabinForRow(row) {
  if (row >= 1 && row <= 4) return "business";
  if (row >= 5 && row <= 9) return "premium_economy";
  if (row >= 10 && row <= 29) return "economy";
  return null;
}

function getCabinLabel(cabin) {
  if (cabin === "economy") return "Economy";
  if (cabin === "premium_economy") return "Premium Economy";
  if (cabin === "business") return "Business";
  return "";
}

function App() {
  const [screen, setScreen] = useState("search");
  const [health, setHealth] = useState("Ready");
  const [flightStatus, setFlightStatus] = useState("Loading flights...");
  const [flights, setFlights] = useState([]);
  const [selectedFlight, setSelectedFlight] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [modalMode, setModalMode] = useState("detail");
  const [bookingStatus, setBookingStatus] = useState("");
  const [bookingDraft, setBookingDraft] = useState({
    contact_name: "Julian Vane",
    contact_email: "julian@example.com",
    contact_phone: "",
    first_name: "Julian",
    last_name: "Vane",
    passenger_type: "adult",
    seat_preference: "window",
    seat_number: "",
  });
  const [flightFilters, setFlightFilters] = useState({
    origin: "ATH",
    destination: "JFK",
    departure_date_from: "2026-04-01",
    departure_date_to: "2026-04-30",
    max_price: "2500",
    sort_by: "departure_time",
    only_available: true,
    limit: 20,
  });
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState([]);
  const [chatStatus, setChatStatus] = useState("Connecting...");
  const [chatPending, setChatPending] = useState(false);
  const [testingStatus, setTestingStatus] = useState("Loading testing workspace...");
  const [testingScenarios, setTestingScenarios] = useState([]);
  const [testingRuns, setTestingRuns] = useState([]);
  const [selectedTestingRunId, setSelectedTestingRunId] = useState(null);
  const [selectedTestingRun, setSelectedTestingRun] = useState(null);
  const [selectedScenarioSlug, setSelectedScenarioSlug] = useState("");
  const [testingBusy, setTestingBusy] = useState(false);
  const visibleFlights = useMemo(() => uniqueFlights(flights), [flights]);
  const testingConversationTurns = useMemo(() => getTestingConversationTurns(selectedTestingRun), [selectedTestingRun]);

  useEffect(() => {
    listFlights(3)
      .then((items) => {
        setFlights(items);
        setFlightStatus(uniqueFlights(items).length ? `Loaded ${uniqueFlights(items).length} flights` : "No flights returned");
      })
      .catch((error) => {
        setFlights([]);
        setFlightStatus(error.message);
        setHealth("Flight API unavailable");
      });
  }, []);

  useEffect(() => {
    getChatHistory()
      .then((items) => {
        setChatMessages(normalizeChatHistory(items));
        setChatStatus(items.length ? "Connected" : "Ready");
      })
      .catch((error) => {
        setChatMessages([]);
        setChatStatus(error.message);
      });
  }, []);

  useEffect(() => {
    Promise.all([listTestingScenarios(), listTestingRuns()])
      .then(([scenarios, runs]) => {
        setTestingScenarios(scenarios);
        setTestingRuns(runs);
        setSelectedScenarioSlug(scenarios[0]?.slug || "");
        setSelectedTestingRunId((current) => current || runs[0]?.id || null);
        setTestingStatus(runs.length ? `Loaded ${runs.length} testing runs.` : "No testing runs yet. Run a scenario to generate one.");
      })
      .catch((error) => {
        setTestingStatus(error.message);
      });
  }, []);

  useEffect(() => {
    if (!selectedTestingRunId) {
      setSelectedTestingRun(null);
      return;
    }
    getTestingRun(selectedTestingRunId)
      .then((response) => {
        setSelectedTestingRun(response.payload);
      })
      .catch((error) => {
        setTestingStatus(error.message);
      });
  }, [selectedTestingRunId]);

  function runFlightSearch() {
    searchFlights({
      origin: flightFilters.origin,
      destination: flightFilters.destination,
      departure_date_from: flightFilters.departure_date_from,
      departure_date_to: flightFilters.departure_date_to,
      max_price: flightFilters.max_price,
      sort_by: flightFilters.sort_by,
      only_available: flightFilters.only_available,
      limit: flightFilters.limit,
    })
      .then((items) => {
        setFlights(items);
        setSelectedFlight(null);
        setDrawerOpen(false);
        setFlightStatus(uniqueFlights(items).length ? `Loaded ${uniqueFlights(items).length} flights` : "No flights returned");
      })
      .catch((error) => {
        setFlightStatus(error.message);
        setHealth("Flight search failed");
      });
  }

  function submitChat(event) {
    event.preventDefault();
    const message = chatInput.trim();
    if (!message || chatPending) return;

    setChatMessages((items) => [...items, { role: "user", text: message }]);
    setChatInput("");
    setChatPending(true);
    setChatStatus("Thinking...");

    sendChatMessage(message)
      .then((response) => {
        setChatStatus(response.accepted ? "Connected" : "Queued");
        setChatMessages((items) => [
          ...items,
          { role: "assistant", text: response.response || "No response received." },
        ]);
      })
      .catch((error) => {
        setChatStatus(error.message);
      })
      .finally(() => {
        setChatPending(false);
      });
  }

  function openFlightDetail(flight) {
    setSelectedFlight(flight);
    setDrawerOpen(true);
    setModalMode("detail");
    setBookingStatus("");
    setBookingDraft((current) => ({
      ...current,
      seat_preference: current.seat_preference || "window",
      seat_number: getDefaultSeatForFlight(flight, current.seat_preference || "window"),
    }));
  }

  function openBookingForm() {
    if (!selectedFlight) return;
    setModalMode("booking");
    setBookingStatus("");
    setBookingDraft((current) => ({
      ...current,
      seat_number: current.seat_number || getDefaultSeatForFlight(selectedFlight, current.seat_preference),
    }));
  }

  function closeFlightModal() {
    setDrawerOpen(false);
    setModalMode("detail");
    setBookingStatus("");
  }

  function handleSeatPreferenceChange(value) {
    setBookingDraft((current) => ({
      ...current,
      seat_preference: value,
      seat_number: value ? getDefaultSeatForFlight(selectedFlight, value) : getDefaultSeatForFlight(selectedFlight, ""),
    }));
  }

  function selectSeat(seatNumber) {
    setBookingDraft((current) => ({ ...current, seat_number: seatNumber }));
  }

  function submitBooking(event) {
    event.preventDefault();
    if (!selectedFlight) return;

    const payload = {
      flight_id: selectedFlight.id,
      contact_name: bookingDraft.contact_name.trim(),
      contact_email: bookingDraft.contact_email.trim(),
      contact_phone: bookingDraft.contact_phone.trim() || null,
      passengers: [
        {
          first_name: bookingDraft.first_name.trim(),
          last_name: bookingDraft.last_name.trim(),
          passenger_type: bookingDraft.passenger_type,
          seat_preference: bookingDraft.seat_preference || null,
          seat_number: bookingDraft.seat_number || null,
        },
      ],
      extras: [],
    };

    setBookingStatus("Creating booking...");
    createBooking(payload)
      .then((response) => {
        setBookingStatus(`Booking confirmed: ${response.booking.booking_reference}`);
        setChatInput(`Book flight ${selectedFlight.flight_number} for ${payload.contact_name}. Booking reference: ${response.booking.booking_reference}.`);
        setModalMode("detail");
      })
      .catch((error) => {
        setBookingStatus(error.message);
      });
  }

  function refreshTestingRuns(preferredRunId = null) {
    return listTestingRuns().then((runs) => {
      setTestingRuns(runs);
      const nextSelected = preferredRunId || runs[0]?.id || null;
      setSelectedTestingRunId(nextSelected);
      return runs;
    });
  }

  function executeTestingRun(payload = {}) {
    setTestingBusy(true);
    setTestingStatus("Running testing scenario...");
    runTestingScenario(payload)
      .then((response) => {
        const preferredRunId = response.results[0]?.id || null;
        return refreshTestingRuns(preferredRunId).then(() => {
          const scope = payload.scenario ? `scenario ${payload.scenario}` : "all scenarios";
          setTestingStatus(`Completed ${scope}. Generated ${response.results.length} run${response.results.length === 1 ? "" : "s"}.`);
        });
      })
      .catch((error) => {
        setTestingStatus(error.message);
      })
      .finally(() => {
        setTestingBusy(false);
      });
  }

  return (
    <div className="app-shell">
      <nav className="topbar">
        <div className="topbar__brand">AeroMellon</div>
        <div className="topbar__links">
          <button className={screen === "search" ? "tab active" : "tab"} onClick={() => setScreen("search")}>Search Flights</button>
          <button className={screen === "concierge" ? "tab active" : "tab"} onClick={() => setScreen("concierge")}>Concierge AI</button>
          <button className={screen === "testing" ? "tab active" : "tab"} onClick={() => setScreen("testing")}>Testing</button>
        </div>
      </nav>

      <aside className="sidebar">
        <div className="sidebar__header">
          <h2>AeroMellon</h2>
          <p>Elite Voyager</p>
        </div>
        <nav className="sidebar__nav" aria-label="Primary">
          <button className={screen === "search" ? "sidebar__item active" : "sidebar__item"} onClick={() => setScreen("search")}>Search Flights</button>
          <button className={screen === "concierge" ? "sidebar__item active" : "sidebar__item"} onClick={() => setScreen("concierge")}>Concierge</button>
          <button className={screen === "testing" ? "sidebar__item active" : "sidebar__item"} onClick={() => setScreen("testing")}>Testing</button>
          <a className="sidebar__item" href="#">My Trips</a>
          <a className="sidebar__item" href="#">Policy Hub</a>
        </nav>
      </aside>

      <main className="page">
        {screen === "search" ? (
          <>
            <header className="page-header">
              <h1>Where will luxury take you?</h1>
              <p>Explore destinations with high-hospitality aviation, tailored for the modern voyager.</p>
              <div className="status-pill">Flight API status: {flightStatus}</div>
              <div className="status-pill">Backend: {health}</div>
            </header>

            <section className="search-bar">
              <label className="search-field search-field--input">
                <span className="material-symbols-outlined">flight_takeoff</span>
                <div>
                  <small>Origin</small>
                  <input value={flightFilters.origin} onChange={(event) => setFlightFilters((current) => ({ ...current, origin: event.target.value.toUpperCase() }))} maxLength={3} placeholder="NYC" />
                </div>
              </label>
              <label className="search-field search-field--input">
                <span className="material-symbols-outlined">location_on</span>
                <div>
                  <small>Destination</small>
                  <input value={flightFilters.destination} onChange={(event) => setFlightFilters((current) => ({ ...current, destination: event.target.value.toUpperCase() }))} maxLength={3} placeholder="LHR" />
                </div>
              </label>
              <label className="search-field search-field--input">
                <span className="material-symbols-outlined">calendar_month</span>
                <div>
                  <small>From</small>
                  <input type="date" value={flightFilters.departure_date_from} onChange={(event) => setFlightFilters((current) => ({ ...current, departure_date_from: event.target.value }))} />
                </div>
              </label>
              <label className="search-field search-field--input">
                <span className="material-symbols-outlined">calendar_month</span>
                <div>
                  <small>To</small>
                  <input type="date" value={flightFilters.departure_date_to} onChange={(event) => setFlightFilters((current) => ({ ...current, departure_date_to: event.target.value }))} />
                </div>
              </label>
              <label className="search-field search-field--input">
                <span className="material-symbols-outlined">payments</span>
                <div>
                  <small>Budget</small>
                  <input type="number" min="0" step="1" value={flightFilters.max_price} onChange={(event) => setFlightFilters((current) => ({ ...current, max_price: event.target.value }))} placeholder="2500" />
                </div>
              </label>
              <button type="button" className="search-button" onClick={runFlightSearch}>
                <span className="material-symbols-outlined">search</span>
              </button>
            </section>

            <section className="results-grid results-grid--single">
              <div className="results-panel">
                {visibleFlights.length ? visibleFlights.map((flight) => (
                  <button
                    type="button"
                    className={selectedFlight?.id === flight.id ? "flight-card flight-card--selected" : "flight-card flight-card--button"}
                    key={flight.id}
                    onClick={() => openFlightDetail(flight)}
                  >
                    <div className="flight-card__row">
                      <div>
                        <small>{formatFlightDate(flight.departure_time)}</small>
                        <strong>{flight.departure_time ? new Date(flight.departure_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</strong>
                        <span>{flight.origin_airport}</span>
                      </div>
                      <div>
                        <small>{flight.arrival_time && flight.departure_time ? `${Math.max(1, Math.round((new Date(flight.arrival_time) - new Date(flight.departure_time)) / 60000 / 60))}h` : "—"}</small>
                        <span>{flight.available_seats} seats left</span>
                      </div>
                      <div>
                        <strong>{flight.arrival_time ? new Date(flight.arrival_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</strong>
                        <span>{flight.destination_airport}</span>
                      </div>
                      <div className="price">${flight.price}</div>
                    </div>
                  </button>
                )) : (
                  <div className="flight-detail">
                    <h3>No flights available</h3>
                    <p>Try widening the date range or clearing some filters.</p>
                  </div>
                )}
              </div>
            </section>

            {drawerOpen && selectedFlight ? (
              <div className="modal-backdrop" onClick={closeFlightModal} role="presentation">
                <aside className="modal-card" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="flight-detail-title">
                  {modalMode === "detail" ? (
                    <>
                      <div className="modal-card__header modal-card__header--booking">
                        <div>
                          <span className="eyebrow">Flight Detail</span>
                          <h3 id="flight-detail-title">{selectedFlight.flight_number}</h3>
                          <p className="modal-card__subtitle">{selectedFlight.origin_airport} to {selectedFlight.destination_airport}</p>
                        </div>
                        <button type="button" className="icon-button" onClick={closeFlightModal} aria-label="Close flight detail">
                          <span className="material-symbols-outlined">close</span>
                        </button>
                      </div>
                      <div className="modal-card__route">
                        <div><span>Day</span><strong>{formatFlightDate(selectedFlight.departure_time)}</strong></div>
                        <div><span>Time</span><strong>{selectedFlight.departure_time ? new Date(selectedFlight.departure_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</strong></div>
                        <div><span>Route</span><strong>{selectedFlight.origin_airport} → {selectedFlight.destination_airport}</strong></div>
                        <div><span>Class</span><strong>{selectedFlight.seat_class}</strong></div>
                        <div><span>Gate</span><strong>{selectedFlight.departure_gate ?? "TBA"}</strong></div>
                        <div><span>Status</span><strong>{selectedFlight.status}</strong></div>
                      </div>
                      <div className="modal-card__meta">
                        <span>{selectedFlight.available_seats} seats left</span>
                        <span>${selectedFlight.price}</span>
                      </div>
                      <div className="modal-card__actions modal-card__actions--inline">
                        <button type="button" className="button button--primary" onClick={openBookingForm}>Start booking</button>
                        <button type="button" className="button button--secondary" onClick={() => setChatInput(`Add baggage to flight ${selectedFlight.flight_number}.`)}>Add baggage</button>
                      </div>
                      {bookingStatus ? <p className="modal-card__status">{bookingStatus}</p> : null}
                    </>
                  ) : (
                    <form className="booking-form" onSubmit={submitBooking}>
                      <div className="modal-card__header modal-card__header--booking">
                        <div>
                          <span className="eyebrow">Booking</span>
                          <h3 id="flight-detail-title">{selectedFlight.flight_number}</h3>
                          <p className="modal-card__subtitle">Select passenger details and a seat before confirming.</p>
                        </div>
                        <button type="button" className="icon-button" onClick={closeFlightModal} aria-label="Close booking">
                          <span className="material-symbols-outlined">close</span>
                        </button>
                      </div>

                      <div className="booking-form__grid">
                        <label className="booking-field">
                          <span>Contact name</span>
                          <input value={bookingDraft.contact_name} onChange={(event) => setBookingDraft((current) => ({ ...current, contact_name: event.target.value }))} required />
                        </label>
                        <label className="booking-field">
                          <span>Contact email</span>
                          <input type="email" value={bookingDraft.contact_email} onChange={(event) => setBookingDraft((current) => ({ ...current, contact_email: event.target.value }))} required />
                        </label>
                        <label className="booking-field">
                          <span>First name</span>
                          <input value={bookingDraft.first_name} onChange={(event) => setBookingDraft((current) => ({ ...current, first_name: event.target.value }))} required />
                        </label>
                        <label className="booking-field">
                          <span>Last name</span>
                          <input value={bookingDraft.last_name} onChange={(event) => setBookingDraft((current) => ({ ...current, last_name: event.target.value }))} required />
                        </label>
                        <label className="booking-field">
                          <span>Passenger type</span>
                          <select value={bookingDraft.passenger_type} onChange={(event) => setBookingDraft((current) => ({ ...current, passenger_type: event.target.value }))}>
                            <option value="adult">Adult</option>
                            <option value="child">Child</option>
                            <option value="infant">Infant</option>
                          </select>
                        </label>
                        <label className="booking-field">
                          <span>Seat preference</span>
                          <select value={bookingDraft.seat_preference} onChange={(event) => handleSeatPreferenceChange(event.target.value)}>
                            <option value="">Any seat</option>
                            <option value="window">Window</option>
                            <option value="aisle">Aisle</option>
                            <option value="extra_legroom">Extra legroom</option>
                          </select>
                        </label>
                        <label className="booking-field booking-field--wide">
                          <span>Seat number</span>
                          <input
                            value={bookingDraft.seat_number}
                            onChange={(event) => setBookingDraft((current) => ({ ...current, seat_number: event.target.value.toUpperCase() }))}
                            placeholder={getDefaultSeatForFlight(selectedFlight, bookingDraft.seat_preference) || "Choose from the map"}
                            required
                          />
                        </label>
                      </div>

                      <div className="seat-map">
                        <div className="seat-map__header">
                          <div>
                            <span className="eyebrow">Seat map</span>
                            <strong>Entire plane</strong>
                          </div>
                          <p>{bookingDraft.seat_number ? `${bookingDraft.seat_number} • ${getSeatTypeLabel(selectedFlight.seat_class, bookingDraft.seat_number)}` : "Pick a seat from the aircraft layout below."}</p>
                        </div>
                        <div className="seat-map__legend">
                          <span><i className="seat seat--legend" />Selectable</span>
                          <span><i className="seat seat--legend seat--selected" />Selected</span>
                          <span><i className="seat seat--legend seat--window" />Window</span>
                          <span><i className="seat seat--legend seat--aisle" />Aisle</span>
                          <span><i className="seat seat--legend seat--extra" />Extra legroom</span>
                          <span><i className="seat seat--legend seat--inactive" />Unavailable</span>
                        </div>
                        <div className="seat-map__grid">
                          {FULL_PLANE_ROWS.map((row) => (
                            <div className="seat-row" key={row}>
                              {row === 1 || row === 5 || row === 10 ? (
                                <div className="seat-row__cabin" style={{ gridColumn: "1 / -1" }}>
                                  <span>{getCabinLabel(getCabinForRow(row))}</span>
                                </div>
                              ) : null}
                              <div className="seat-row__label">{row}</div>
                              {(() => {
                                const cabin = getCabinForRow(row);
                                const columns = cabin === "business" ? ["A", "B", "C", "D"] : FULL_PLANE_COLUMNS;
                                const seatColumns = columns.length;
                                return (
                              <div
                                  className={`seat-row__seats ${cabin === "business" ? "seat-row__seats--business" : ""}`}
                                  style={{ "--seat-columns": seatColumns }}
                                >
                                  {columns.map((column) => {
                                    const planeSeat = getSeatAvailabilityForPlane(row, column, selectedFlight.seat_class);
                                    const seatNumber = planeSeat.exists ? buildSeatNumber(selectedFlight.seat_class, row, column) || `${row}${column}` : "";
                                    const meta = seatMetadata(selectedFlight.seat_class, seatNumber);
                                    const selected = bookingDraft.seat_number === seatNumber;
                                    return (
                                      <button
                                        key={`${row}${column}`}
                                        type="button"
                                        className={[
                                          "seat",
                                          planeSeat.active ? "" : "seat--inactive",
                                          meta.window ? "seat--window" : "",
                                          meta.aisle ? "seat--aisle" : "",
                                          planeSeat.extraLegroom ? "seat--extra" : "",
                                          selected ? "seat--selected" : "",
                                        ]
                                          .filter(Boolean)
                                          .join(" ")}
                                        onClick={() => planeSeat.active && seatNumber ? selectSeat(seatNumber) : null}
                                        aria-pressed={selected}
                                        aria-label={seatNumber ? `Seat ${seatNumber}` : `Unavailable seat ${row}${column}`}
                                        disabled={!planeSeat.active || !seatNumber}
                                      >
                                        {planeSeat.exists ? column : ""}
                                      </button>
                                    );
                                  })}
                                </div>
                                );
                              })()}
                            </div>
                          ))}
                        </div>
                      </div>

                      <div className="modal-card__route modal-card__route--compact">
                        <div><span>Day</span><strong>{formatFlightDate(selectedFlight.departure_time)}</strong></div>
                        <div><span>Route</span><strong>{selectedFlight.origin_airport} → {selectedFlight.destination_airport}</strong></div>
                        <div><span>Class</span><strong>{selectedFlight.seat_class.replaceAll("_", " ")}</strong></div>
                        <div><span>Fare</span><strong>${selectedFlight.price}</strong></div>
                      </div>

                      <div className="modal-card__actions modal-card__actions--inline">
                        <button type="button" className="button button--secondary" onClick={() => setModalMode("detail")}>Back</button>
                        <button type="submit" className="button button--primary">Confirm booking</button>
                      </div>
                      {bookingStatus ? <p className="modal-card__status">{bookingStatus}</p> : null}
                    </form>
                  )}
                </aside>
              </div>
            ) : null}
          </>
        ) : screen === "concierge" ? (
          <>
            <header className="concierge-intro">
              <div className="intro-mark">
                <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>auto_awesome</span>
              </div>
              <h1>Good afternoon, Julian.</h1>
              <p>I&apos;m your AeroMellon Concierge. How may I elevate your journey today?</p>
            </header>

            <section className="chat-thread">
              {chatMessages.length ? chatMessages.map((message, index) => (
                <div className={message.role === "user" ? "chat-row user" : "chat-row"} key={`${message.role}-${message.createdAt || index}`}>
                  <div className={message.role === "user" ? "avatar user" : "avatar ai"}>
                    {message.role === "user" ? "JV" : "AM"}
                  </div>
                  <div className={message.role === "user" ? "bubble user" : "bubble ai"}>
                    <p>{message.text}</p>
                  </div>
                </div>
              )) : null}
            </section>

            <section className="composer-shell">
              <form className="composer" onSubmit={submitChat}>
                <span className="material-symbols-outlined composer__icon">chat_bubble</span>
                <input value={chatInput} onChange={(event) => setChatInput(event.target.value)} placeholder="Tell me where you want to go..." disabled={chatPending} />
                <button type="submit" className="composer__send" disabled={chatPending}>
                  <span className="material-symbols-outlined">arrow_upward</span>
                </button>
              </form>
              <p className="status-pill status-pill--center">AeroMellon AI Concierge • {chatStatus}</p>
            </section>
          </>
        ) : (
          <>
            <header className="page-header">
              <h1>Testing Observatory</h1>
              <p>Run the ElevenLabs agent scenarios directly from the UI, then inspect assertions, tool calls, timeline data, and backend verification per test id.</p>
              <div className="status-pill">Testing: {testingStatus}</div>
            </header>

            <section className="testing-toolbar">
              <button type="button" className="button button--primary" onClick={() => executeTestingRun()} disabled={testingBusy}>
                <span className="material-symbols-outlined">play_arrow</span>
                Run all scenarios
              </button>
              <select
                value={selectedScenarioSlug}
                onChange={(event) => setSelectedScenarioSlug(event.target.value)}
                className="testing-select"
                disabled={testingBusy || !testingScenarios.length}
              >
                {testingScenarios.map((scenario) => (
                  <option key={scenario.slug} value={scenario.slug}>
                    {scenario.slug}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="button button--secondary"
                onClick={() => executeTestingRun(selectedScenarioSlug ? { scenario: selectedScenarioSlug } : {})}
                disabled={testingBusy || !selectedScenarioSlug}
              >
                <span className="material-symbols-outlined">terminal</span>
                Run selected scenario
              </button>
              <button type="button" className="button button--secondary" onClick={() => refreshTestingRuns(selectedTestingRunId)} disabled={testingBusy}>
                <span className="material-symbols-outlined">refresh</span>
                Refresh runs
              </button>
            </section>

            <section className="testing-layout">
              <aside className="testing-sidebar">
                <div className="testing-sidebar__header">
                  <h3>Runs</h3>
                  <span>{testingRuns.length}</span>
                </div>
                {testingRuns.length ? (
                  <div className="testing-run-list">
                    {testingRuns.map((run) => (
                      <button
                        type="button"
                        key={run.id}
                        className={selectedTestingRunId === run.id ? "testing-run testing-run--active" : "testing-run"}
                        onClick={() => setSelectedTestingRunId(run.id)}
                      >
                        <strong>{run.id}</strong>
                        <span>{run.description}</span>
                        <small>{formatTimestamp(run.started_at)}</small>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="testing-empty">
                    <span className="material-symbols-outlined">experiment</span>
                    <p>No runs available yet.</p>
                  </div>
                )}
              </aside>

              <div className="testing-content">
                {selectedTestingRun ? (
                  <>
                    <article className="testing-card testing-card--wide">
                      <div className="testing-card__header">
                        <h3>Conversation</h3>
                        <span className="testing-muted">{testingConversationTurns.length ? `${testingConversationTurns.length} turns` : "No transcript found"}</span>
                      </div>
                      {testingConversationTurns.length ? (
                        <div className="testing-conversation">
                          {testingConversationTurns.map((turn) => (
                            <div key={turn.key} className="testing-turn testing-turn--compact">
                              <div className="testing-turn__head">
                                <strong>{turn.role}</strong>
                                <span>{turn.time ?? "—"}</span>
                              </div>
                              {turn.text ? <p>{turn.text}</p> : null}
                              {turn.meta?.length ? (
                                <div className="testing-inline-list">
                                  {turn.meta.map((toolName) => (
                                    <span key={toolName} className="testing-chip">
                                      {toolName}
                                    </span>
                                  ))}
                                </div>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="testing-muted">No conversation transcript is available for this run.</p>
                      )}
                    </article>

                    <section className="testing-hero">
                      <div>
                        <span className="eyebrow">Test ID</span>
                        <h2>{selectedTestingRun.scenario?.slug}:{selectedTestingRun.run?.conversation_id || "pending"}</h2>
                        <p>{selectedTestingRun.scenario?.description}</p>
                      </div>
                      <div className="testing-hero__stats">
                        <div><span>Outcome</span><strong>{selectedTestingRun.scenario?.expected_outcome || "—"}</strong></div>
                        <div><span>Duration</span><strong>{selectedTestingRun.stats?.total_duration_secs ?? "—"}s</strong></div>
                        <div><span>Tool calls</span><strong>{selectedTestingRun.stats?.tool_call_count ?? 0}</strong></div>
                        <div><span>Conversation</span><strong>{selectedTestingRun.run?.conversation_id || "—"}</strong></div>
                      </div>
                    </section>

                    <article className="testing-card testing-card--wide">
                      <div className="testing-card__header">
                        <h3>Raw JSON</h3>
                      </div>
                      <pre className="testing-pre">{safeJson(selectedTestingRun)}</pre>
                    </article>

                    <section className="testing-grid">
                      <article className="testing-card">
                        <div className="testing-card__header">
                          <h3>Assertions</h3>
                        </div>
                        <div className="testing-kv">
                          {Object.entries(selectedTestingRun.assertions || {}).map(([key, value]) => (
                            <div key={key} className="testing-kv__row">
                              <span>{key}</span>
                              <strong>{typeof value === "boolean" ? (value ? "true" : "false") : formatJson(value)}</strong>
                            </div>
                          ))}
                        </div>
                      </article>

                      <article className="testing-card">
                        <div className="testing-card__header">
                          <h3>Run Metadata</h3>
                        </div>
                        <div className="testing-kv">
                          <div className="testing-kv__row"><span>Started</span><strong>{formatTimestamp(selectedTestingRun.run?.started_at)}</strong></div>
                          <div className="testing-kv__row"><span>Finished</span><strong>{formatTimestamp(selectedTestingRun.run?.finished_at)}</strong></div>
                          <div className="testing-kv__row"><span>Agent</span><strong>{selectedTestingRun.run?.agent_id || "—"}</strong></div>
                          <div className="testing-kv__row"><span>Branch</span><strong>{selectedTestingRun.run?.branch_id || "—"}</strong></div>
                          <div className="testing-kv__row"><span>Commit</span><strong>{selectedTestingRun.run?.git_commit_hash || "—"}</strong></div>
                        </div>
                      </article>

                      <article className="testing-card testing-card--wide">
                        <div className="testing-card__header">
                          <h3>Final Agent Message</h3>
                        </div>
                        <pre className="testing-pre">{selectedTestingRun.final_agent_message || "—"}</pre>
                      </article>

                      <article className="testing-card testing-card--wide">
                        <div className="testing-card__header">
                          <h3>Tool Trace</h3>
                        </div>
                        {selectedTestingRun.tool_trace?.length ? (
                          <div className="testing-trace">
                            {selectedTestingRun.tool_trace.map((item, index) => (
                              <div key={`${item.kind}-${item.request_id || index}`} className="testing-trace__item">
                                <div className="testing-trace__meta">
                                  <span>{item.kind}</span>
                                  <strong>{item.tool_name}</strong>
                                  <small>turn {item.turn_index}</small>
                                </div>
                                <pre className="testing-pre">{formatJson(item.kind === "tool_call" ? item.params : item.result)}</pre>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="testing-muted">No tool activity captured for this run.</p>
                        )}
                      </article>

                      <article className="testing-card testing-card--wide">
                        <div className="testing-card__header">
                          <h3>Conversation Timeline</h3>
                        </div>
                        <div className="testing-timeline">
                          {(selectedTestingRun.elevenlabs_conversation?.transcript || []).map((item, index) => (
                            <div key={`${item.role}-${index}`} className="testing-turn">
                              <div className="testing-turn__head">
                                <strong>{item.role}</strong>
                                <span>{item.time_in_call_secs ?? 0}s</span>
                              </div>
                              {item.message ? <p>{item.message}</p> : null}
                              {item.original_message ? <pre className="testing-pre">{item.original_message}</pre> : null}
                              {item.tool_calls?.length ? (
                                <div className="testing-inline-list">
                                  {item.tool_calls.map((toolCall) => (
                                    <span key={toolCall.request_id} className="testing-chip">{toolCall.tool_name}</span>
                                  ))}
                                </div>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      </article>

                      <article className="testing-card">
                        <div className="testing-card__header">
                          <h3>Backend Verification</h3>
                        </div>
                        {selectedTestingRun.backend_verification ? (
                          <div className="testing-kv">
                            {Object.entries(selectedTestingRun.backend_verification).map(([key, value]) => (
                              <div key={key} className="testing-kv__row">
                                <span>{key}</span>
                                <strong>{formatJson(value)}</strong>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="testing-muted">No backend verification for this run.</p>
                        )}
                      </article>

                      <article className="testing-card">
                        <div className="testing-card__header">
                          <h3>Analysis Summary</h3>
                        </div>
                        <div className="testing-kv">
                          <div className="testing-kv__row"><span>Call successful</span><strong>{selectedTestingRun.elevenlabs_conversation?.analysis?.call_successful || "—"}</strong></div>
                          <div className="testing-kv__row"><span>Summary title</span><strong>{selectedTestingRun.elevenlabs_conversation?.analysis?.call_summary_title || "—"}</strong></div>
                        </div>
                        <pre className="testing-pre">{selectedTestingRun.elevenlabs_conversation?.analysis?.transcript_summary || "—"}</pre>
                      </article>
                    </section>
                  </>
                ) : (
                  <div className="testing-empty testing-empty--large">
                    <span className="material-symbols-outlined">experiment</span>
                    <h2>No run selected</h2>
                    <p>Run a scenario or refresh the workspace to inspect a testing artifact here.</p>
                  </div>
                )}
              </div>
            </section>
          </>
        )}
      </main>

      <nav className="mobile-nav" aria-label="Mobile primary">
        <button type="button" className={screen === "search" ? "mobile-nav__item active" : "mobile-nav__item"} onClick={() => setScreen("search")}>
          <span className="material-symbols-outlined">flight_takeoff</span>
          <span>Search</span>
        </button>
        <button type="button" className={screen === "concierge" ? "mobile-nav__item active" : "mobile-nav__item"} onClick={() => setScreen("concierge")}>
          <span className="material-symbols-outlined">concierge</span>
          <span>Concierge</span>
        </button>
        <button type="button" className={screen === "testing" ? "mobile-nav__item active" : "mobile-nav__item"} onClick={() => setScreen("testing")}>
          <span className="material-symbols-outlined">analytics</span>
          <span>Testing</span>
        </button>
      </nav>
    </div>
  );
}

export default App;
