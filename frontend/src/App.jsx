import { useEffect, useMemo, useRef, useState } from "react";
import {
  approveTestingPipeline,
  cancelTestingPipeline,
  createBooking,
  getTestingPipeline,
  getTestingPipelineEvents,
  listAllTripsBooked,
  listFlights,
  listTestingPipelines,
  listTestingTasks,
  listTestingRuns,
  runTestingTaskLive,
  searchFlights,
  sendChatMessage,
  resetChatSession,
  startTestingPipeline,
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

function formatFlightTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatTimestamp(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatCurrency(value) {
  if (value === null || value === undefined || value === "") return "—";
  const amount = Number(value);
  if (Number.isNaN(amount)) return `$${value}`;
  return amount.toLocaleString([], { style: "currency", currency: "USD" });
}

function formatSeatClass(value) {
  if (!value) return "—";
  return String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatJson(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function stripAnsi(value) {
  return String(value || "").replace(/\u001b\[[0-9;]*m/g, "");
}

function pipelineIsTerminal(status) {
  return ["completed", "failed", "blocked_manual_fix", "canceled"].includes(String(status || ""));
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
    extraLegroomRows: new Set(),
  },
  business: {
    rows: Array.from({ length: 4 }, (_, index) => index + 25),
    columns: ["A", "B", "C", "D"],
    windowColumns: new Set(["A", "D"]),
    aisleColumns: new Set(["B", "C"]),
    extraLegroomRows: new Set(),
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
      extraLegroom: false,
    };
  }
  if (row >= 5 && row <= 9) {
    return {
      exists: FULL_PLANE_COLUMNS.includes(column),
      active: className === "premium_economy",
      extraLegroom: false,
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
  const [bookedTrips, setBookedTrips] = useState([]);
  const [tripsStatus, setTripsStatus] = useState("Loading booked trips...");
  const [tripsLoading, setTripsLoading] = useState(false);
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
  const [testingTasks, setTestingTasks] = useState([]);
  const [testingRuns, setTestingRuns] = useState([]);
  const [testingPipelines, setTestingPipelines] = useState([]);
  const [selectedTestingRunId, setSelectedTestingRunId] = useState(null);
  const [selectedPipelineId, setSelectedPipelineId] = useState(null);
  const [selectedPipeline, setSelectedPipeline] = useState(null);
  const [selectedPipelineEvents, setSelectedPipelineEvents] = useState([]);
  const [selectedTaskSlug, setSelectedTaskSlug] = useState("");
  const [testingBusy, setTestingBusy] = useState(false);
  const [pipelineBusy, setPipelineBusy] = useState(false);
  const [, setPipelineStatus] = useState("Loading self-improvement pipelines...");
  const [pipelineForm, setPipelineForm] = useState({
    task_slugs: [],
    target_score: 8,
    max_iterations: 5,
    review_model: "openai:gpt-5.4-mini",
    fixer_model: "openai:gpt-5.4-mini",
    require_manual_approval: true,
  });
  const [testingConversation, setTestingConversation] = useState([]);
  const [testingLiveEvents, setTestingLiveEvents] = useState([]);
  const [testingLogLines, setTestingLogLines] = useState([]);
  const [testingRefinementEvents, setTestingRefinementEvents] = useState([]);
  const [testingLiveActive, setTestingLiveActive] = useState(false);
  const transcriptConsoleRef = useRef(null);
  const liveConsoleRef = useRef(null);
  const pipelineConsoleRef = useRef(null);
  const visibleFlights = useMemo(() => uniqueFlights(flights), [flights]);
  const refinementSections = useMemo(() => {
    const evaluation = [];
    const refinementAnalysis = [];
    const fixPlan = [];
    const fixerEdits = [];
    const completion = [];

    for (const event of testingRefinementEvents) {
      if (!event) continue;
      if (event.kind === "evaluation" || event.kind === "criterion" || event.kind === "finding" || event.kind === "evaluation_error") {
        evaluation.push(event);
        continue;
      }
      if (event.kind === "refinement" || event.kind === "refinement_error") {
        refinementAnalysis.push(event);
        continue;
      }
      if (event.kind === "fixer") {
        if (/edit/i.test(event.title || "") || /edit/i.test(event.body || "")) {
          fixerEdits.push(event);
        } else {
          fixPlan.push(event);
        }
        continue;
      }
      if (event.kind === "completion") {
        completion.push(event);
      }
    }

    return { evaluation, refinementAnalysis, fixPlan, fixerEdits, completion };
  }, [testingRefinementEvents]);
  const bookedTripSummary = useMemo(() => {
    const passengerCount = bookedTrips.reduce((total, trip) => total + (trip.passengers?.length || 0), 0);
    const nextDeparture = bookedTrips
      .map((trip) => trip.flight?.departure_time)
      .filter(Boolean)
      .sort((left, right) => new Date(left) - new Date(right))[0] || null;
    return {
      trips: bookedTrips.length,
      passengers: passengerCount,
      nextDeparture,
    };
  }, [bookedTrips]);
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
    loadBookedTrips();
  }, []);

  useEffect(() => {
    resetChatSession()
      .then(() => {
        setChatMessages([]);
        setChatStatus("Ready");
      })
      .catch((error) => {
        setChatMessages([]);
        setChatStatus(error.message);
      });
  }, []);

  useEffect(() => {
    Promise.all([listTestingTasks(), listTestingRuns()])
      .then(([tasks, runs]) => {
        setTestingTasks(tasks);
        setTestingRuns(runs);
        setSelectedTaskSlug(tasks[0]?.slug || "");
        setPipelineForm((current) =>
          current.task_slugs.length
            ? current
            : {
                ...current,
                task_slugs: tasks[0] ? [tasks[0].slug] : [],
              }
        );
        setSelectedTestingRunId((current) => current || runs[0]?.id || null);
        setTestingStatus(runs.length ? `Loaded ${runs.length} testing runs.` : "No testing runs yet. Run a task to generate one.");
      })
      .catch((error) => {
        setTestingStatus(error.message);
      });
  }, []);

  useEffect(() => {
    refreshTestingPipelines()
      .catch((error) => {
        setTestingPipelines([]);
        setSelectedPipelineId(null);
        setSelectedPipeline(null);
        setSelectedPipelineEvents([]);
        setPipelineStatus(`Pipeline backend unavailable: ${error.message}`);
      });
  }, []);

  useEffect(() => {
    if (liveConsoleRef.current) {
      liveConsoleRef.current.scrollTop = liveConsoleRef.current.scrollHeight;
    }
  }, [testingLiveEvents, testingLiveActive]);

  useEffect(() => {
    if (pipelineConsoleRef.current) {
      pipelineConsoleRef.current.scrollTop = pipelineConsoleRef.current.scrollHeight;
    }
  }, [selectedPipelineEvents, selectedPipelineId]);

  useEffect(() => {
    if (screen === "trips") {
      loadBookedTrips({ silent: bookedTrips.length > 0 });
    }
  }, [screen]);

  useEffect(() => {
    if (!selectedPipelineId) {
      setSelectedPipeline(null);
      setSelectedPipelineEvents([]);
      return;
    }
    refreshPipelineDetails(selectedPipelineId).catch((error) => {
      setPipelineStatus(error.message);
    });
  }, [selectedPipelineId]);

  useEffect(() => {
    if (screen !== "testing" || !selectedPipelineId) {
      return undefined;
    }
    const activeStatus = selectedPipeline?.status;
    if (!activeStatus || pipelineIsTerminal(activeStatus)) {
      return undefined;
    }
    const interval = window.setInterval(() => {
      refreshTestingPipelines(selectedPipelineId).catch((error) => {
        setPipelineStatus(error.message);
      });
    }, 4000);
    return () => window.clearInterval(interval);
  }, [screen, selectedPipelineId, selectedPipeline?.status]);

  function loadBookedTrips({ silent = false } = {}) {
    if (!silent) {
      setTripsStatus("Loading booked trips...");
    }
    setTripsLoading(true);
    return listAllTripsBooked()
      .then((items) => {
        setBookedTrips(items);
        setTripsStatus(items.length ? `Loaded ${items.length} booked trip${items.length === 1 ? "" : "s"}.` : "No booked trips yet.");
      })
      .catch((error) => {
        setBookedTrips([]);
        setTripsStatus(error.message);
      })
      .finally(() => {
        setTripsLoading(false);
      });
  }

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
        setBookingStatus(`Booking confirmed: ${response.booking_reference}`);
        setTripsStatus(`Latest booking confirmed: ${response.booking_reference}`);
        loadBookedTrips({ silent: true }).catch(() => {});
        setChatInput(`Book flight ${selectedFlight.flight_number} for ${payload.contact_name}. Booking reference: ${response.booking_reference}.`);
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

  function refreshPipelineDetails(pipelineId) {
    if (!pipelineId) {
      setSelectedPipeline(null);
      setSelectedPipelineEvents([]);
      return Promise.resolve(null);
    }
    return Promise.all([getTestingPipeline(pipelineId), getTestingPipelineEvents(pipelineId)]).then(
      ([pipelinePayload, events]) => {
        setSelectedPipeline(pipelinePayload.payload);
        setSelectedPipelineEvents(events);
        return pipelinePayload.payload;
      }
    );
  }

  function refreshTestingPipelines(preferredPipelineId = null) {
    return listTestingPipelines().then((pipelines) => {
      setTestingPipelines(pipelines);
      const nextSelected = preferredPipelineId || pipelines[0]?.pipeline_id || null;
      setSelectedPipelineId(nextSelected);
      setPipelineStatus(
        pipelines.length
          ? `Loaded ${pipelines.length} pipeline run${pipelines.length === 1 ? "" : "s"}.`
          : "No self-improvement pipelines yet."
      );
      return refreshPipelineDetails(nextSelected).then(() => pipelines);
    });
  }

  function setPipelineTask(taskSlug) {
    setPipelineForm((current) => ({
      ...current,
      task_slugs: taskSlug ? [taskSlug] : [],
    }));
  }

  function startPipelineRun() {
    if (!pipelineForm.task_slugs.length || pipelineBusy) return;
    setPipelineBusy(true);
    setPipelineStatus("Starting self-improvement pipeline...");
    startTestingPipeline({
      ...pipelineForm,
      task_slugs: pipelineForm.task_slugs,
      target_score: Number(pipelineForm.target_score),
      max_iterations: Number(pipelineForm.max_iterations),
    })
      .then((response) => {
        const nextPipeline = response.payload;
        setSelectedPipelineId(nextPipeline.pipeline_id);
        return refreshTestingPipelines(nextPipeline.pipeline_id);
      })
      .catch((error) => {
        setPipelineStatus(error.message);
      })
      .finally(() => {
        setPipelineBusy(false);
      });
  }

  function approveSelectedPipeline() {
    if (!selectedPipelineId || pipelineBusy) return;
    setPipelineBusy(true);
    setPipelineStatus("Approving the current iteration...");
    approveTestingPipeline(selectedPipelineId)
      .then(() => refreshTestingPipelines(selectedPipelineId))
      .catch((error) => {
        setPipelineStatus(error.message);
      })
      .finally(() => {
        setPipelineBusy(false);
      });
  }

  function cancelSelectedPipeline() {
    if (!selectedPipelineId || pipelineBusy) return;
    setPipelineBusy(true);
    setPipelineStatus("Canceling pipeline...");
    cancelTestingPipeline(selectedPipelineId)
      .then(() => refreshTestingPipelines(selectedPipelineId))
      .catch((error) => {
        setPipelineStatus(error.message);
      })
      .finally(() => {
        setPipelineBusy(false);
      });
  }

  function executeTestingRun(payload = {}) {
    setTestingBusy(true);
    setTestingLiveActive(true);
    setTestingLiveEvents([{ tag: "status", text: "Connecting to live test runner..." }]);
    setTestingLogLines([]);
    setTestingRefinementEvents([]);
    setTestingStatus("Running testing task...");
    runTestingTaskLive(payload, (event) => {
      if (!event || typeof event !== "object") return;
      if (event.type === "status") {
        setTestingStatus(event.message || "Running testing task...");
        setTestingLiveEvents((current) => [...current, { tag: "status", text: event.message || "started" }]);
        return;
      }
      if (event.type === "run_started") {
        setTestingLiveEvents((current) => [...current, { tag: "run", text: `Started ${event.task_count} task${event.task_count === 1 ? "" : "s"}.` }]);
        return;
      }
      if (event.type === "task_started") {
        setTestingLiveEvents((current) => [...current, { tag: "task", text: `Task ${event.task} started.` }]);
        return;
      }
      if (event.type === "user_turn") {
        return;
      }
      if (event.type === "customer_reply") {
        return;
      }
      if (event.type === "transcript_turn") {
        const text = String(event.text || "").trim();
        if (text) {
          setTestingConversation((current) => {
            const last = current[current.length - 1];
            if (last && last.role === event.role && last.text === text) {
              return current;
            }
            return [
              ...current,
              {
                role: event.role || "turn",
                text,
                timestamp: event.timestamp || null,
              },
            ];
          });
          setTestingLiveEvents((current) => {
            const last = current[current.length - 1];
            if (last && last.tag === event.role && last.text === text) {
              return current;
            }
            return [...current, { tag: event.role || "turn", text }];
          });
        }
        return;
      }
      if (event.type === "evaluation_started") {
        setTestingLiveEvents((current) => [...current, { tag: "eval", text: `Evaluating ${event.task}.` }]);
        setTestingRefinementEvents((current) => [
          ...current,
          {
            kind: "evaluation",
            title: "Evaluation started",
            subtitle: event.task || "task",
            timestamp: new Date().toISOString(),
            body: `Evaluation started for ${event.task || "the selected task"}.`,
          },
        ]);
        return;
      }
      if (event.type === "evaluation_complete") {
        setTestingLiveEvents((current) => [...current, { tag: "eval", text: `Evaluation complete for ${event.task}.` }]);
        setTestingRefinementEvents((current) => [
          ...current,
          {
            kind: "evaluation",
            title: "Evaluation complete",
            subtitle: event.task || "task",
            timestamp: new Date().toISOString(),
            body: [
              event.verdict ? `Verdict: ${event.verdict}` : null,
              typeof event.overall_score !== "undefined" ? `Score: ${event.overall_score}` : null,
              typeof event.goal_achieved !== "undefined" ? `Goal achieved: ${event.goal_achieved ? "yes" : "no"}` : null,
              event.answer_quality ? `Answer quality: ${event.answer_quality}` : null,
              event.suggested_next_step ? `Next step: ${event.suggested_next_step}` : null,
            ]
              .filter(Boolean)
              .join("\n"),
          },
        ]);
        return;
      }
      if (event.type === "elevenlabs_analysis") {
        setTestingRefinementEvents((current) => [
          ...current,
          {
            kind: "evaluation",
            title: "ElevenLabs analysis",
            subtitle: event.task || "task",
            timestamp: new Date().toISOString(),
            body: [
              event.call_summary_title || null,
              typeof event.call_successful !== "undefined"
                ? `Call successful: ${event.call_successful ? "yes" : "no"}`
                : null,
              event.transcript_summary || null,
              event.termination_reason ? `Termination: ${event.termination_reason}` : null,
            ]
              .filter(Boolean)
              .join("\n"),
          },
        ]);
        return;
      }
      if (event.type === "evaluation_criterion") {
        setTestingRefinementEvents((current) => [
          ...current,
          {
            kind: "criterion",
            title: String(event.criterion || "Evaluation criterion"),
            subtitle: event.task || "task",
            timestamp: new Date().toISOString(),
            score: event.score,
            body: event.summary || "",
            details: event.evidence_quotes || [],
          },
        ]);
        return;
      }
      if (event.type === "refinement_gate") {
        setTestingRefinementEvents((current) => [
          ...current,
          {
            kind: "evaluation",
            title: "Refinement gate",
            subtitle: event.task || "task",
            timestamp: new Date().toISOString(),
            body: event.message || "",
            details: Array.isArray(event.criteria_below_target) ? event.criteria_below_target : [],
          },
        ]);
        return;
      }
      if (event.type === "evaluation_finding") {
        setTestingRefinementEvents((current) => [
          ...current,
          {
            kind: "finding",
            title: String(event.title || "Finding"),
            subtitle: String(event.severity || "finding"),
            timestamp: new Date().toISOString(),
            body: event.detail || "",
          },
        ]);
        return;
      }
      if (event.type === "root_cause" || event.type === "root_cause_complete") {
        setTestingRefinementEvents((current) => [
          ...current,
          {
            kind: "refinement",
            title: "Refinement analysis",
            subtitle: event.root_cause_category || event.category || event.task || "analysis",
            timestamp: new Date().toISOString(),
            body: [
              event.primary_root_cause || event.summary || event.message || null,
              event.confidence ? `Confidence: ${event.confidence}` : null,
            ]
              .filter(Boolean)
              .join("\n"),
          },
        ]);
        return;
      }
      if (event.type === "refinement_error") {
        setTestingLiveEvents((current) => [...current, { tag: "error", text: event.error || "Refinement analysis failed." }]);
        setTestingRefinementEvents((current) => [
          ...current,
          {
            kind: "refinement_error",
            title: "Refinement error",
            subtitle: event.stage || event.task || "refinement",
            timestamp: new Date().toISOString(),
            body: event.error || "Refinement analysis failed.",
          },
        ]);
        return;
      }
      if (event.type === "fix_plan_ready" || event.type === "fixer_summary" || event.type === "fixer_expected_improvement" || event.type === "fixer_edit") {
        setTestingRefinementEvents((current) => [
          ...current,
          {
            kind: "fixer",
            title:
              event.type === "fix_plan_ready"
                ? "Fix plan ready"
                : event.type === "fixer_summary"
                  ? "Fixer summary"
                  : event.type === "fixer_expected_improvement"
                    ? "Expected improvement"
                    : "Fixer edit",
            subtitle: event.task || event.section || "fixer",
            timestamp: new Date().toISOString(),
            body: event.message || event.summary || event.expected_improvement || event.detail || safeJson(event),
          },
        ]);
        return;
      }
      if (event.type === "evaluation_error") {
        setTestingLiveEvents((current) => [...current, { tag: "error", text: event.error || "Evaluation failed." }]);
        setTestingRefinementEvents((current) => [
          ...current,
          {
            kind: "evaluation_error",
            title: "Evaluation error",
            subtitle: event.task || "task",
            timestamp: new Date().toISOString(),
            body: event.error || "Evaluation failed.",
          },
        ]);
        return;
      }
      if (event.type === "task_finished") {
        setTestingLiveEvents((current) => [...current, { tag: "task", text: `Task ${event.task} finished.` }]);
        setTestingRefinementEvents((current) => [
          ...current,
          {
            kind: "completion",
            title: "Task finished",
            subtitle: event.task || "task",
            timestamp: new Date().toISOString(),
            body: `Task ${event.task || "task"} finished.`,
          },
        ]);
        return;
      }
      if (event.type === "run_finished") {
        setTestingLiveEvents((current) => [...current, { tag: "run", text: "Run finished." }]);
        setTestingRefinementEvents((current) => [
          ...current,
          {
            kind: "completion",
            title: "Run finished",
            subtitle: payload.task ? `task ${payload.task}` : "all tasks",
            timestamp: new Date().toISOString(),
            body: "Live test run completed.",
          },
        ]);
        const scope = payload.task ? `task ${payload.task}` : "all tasks";
        setTestingStatus(`Completed ${scope}.`);
        refreshTestingRuns(selectedTestingRunId).catch(() => {});
        return;
      }
      if (event.type === "error") {
        setTestingStatus(event.message || "Testing failed.");
        setTestingLiveEvents((current) => [...current, { tag: "error", text: event.message || "Testing failed." }]);
        return;
      }
      if (event.type === "log") {
        const cleaned = stripAnsi(event.message || "");
        if (cleaned && cleaned !== "{" && cleaned !== "}") {
          setTestingLogLines((current) => [...current, cleaned]);
        }
        return;
      }
      setTestingLiveEvents((current) => [...current, { tag: event.type || "log", text: event.message ? String(event.message) : safeJson(event) }]);
    })
      .catch((error) => {
        setTestingStatus(error.message);
        setTestingLiveEvents((current) => [...current, { tag: "error", text: error.message }]);
      })
      .finally(() => {
        setTestingBusy(false);
        setTestingLiveActive(false);
      });
  }

  return (
    <div className="app-shell">
      <nav className="topbar">
        <div className="topbar__brand">AeroMellon</div>
        <div className="topbar__links">
          <button className={screen === "search" ? "tab active" : "tab"} onClick={() => setScreen("search")}>Search Flights</button>
          <button className={screen === "trips" ? "tab active" : "tab"} onClick={() => setScreen("trips")}>All Trips Booked</button>
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
          <button className={screen === "trips" ? "sidebar__item active" : "sidebar__item"} onClick={() => setScreen("trips")}>All Trips Booked</button>
          <button className={screen === "concierge" ? "sidebar__item active" : "sidebar__item"} onClick={() => setScreen("concierge")}>Concierge</button>
          <button className={screen === "testing" ? "sidebar__item active" : "sidebar__item"} onClick={() => setScreen("testing")}>Testing</button>
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
        ) : screen === "trips" ? (
          <>
            <header className="page-header">
              <h1>All Trips Booked</h1>
              <p>Confirmed trips for every passenger load here automatically, with flight details, seats, and contact records in one place.</p>
              <div className="status-pill">Trips: {tripsStatus}</div>
            </header>

            <section className="trips-summary">
              <article className="trip-stat-card">
                <small>Booked trips</small>
                <strong>{bookedTripSummary.trips}</strong>
              </article>
              <article className="trip-stat-card">
                <small>Total passengers</small>
                <strong>{bookedTripSummary.passengers}</strong>
              </article>
              <article className="trip-stat-card">
                <small>Next departure</small>
                <strong>{bookedTripSummary.nextDeparture ? `${formatFlightDate(bookedTripSummary.nextDeparture)} · ${formatFlightTime(bookedTripSummary.nextDeparture)}` : "No future trips"}</strong>
              </article>
            </section>

            <section className="trips-toolbar">
              <button type="button" className="button button--primary" onClick={() => loadBookedTrips()} disabled={tripsLoading}>
                <span className="material-symbols-outlined">refresh</span>
                {tripsLoading ? "Refreshing..." : "Refresh trips"}
              </button>
              <p className="testing-muted">This view always pulls the latest confirmed bookings from the backend.</p>
            </section>

            <section className="trips-grid">
              {bookedTrips.length ? bookedTrips.map((trip) => (
                <article className="trip-card" key={trip.booking_reference}>
                  <div className="trip-card__header">
                    <div>
                      <span className="eyebrow">Booking {trip.booking_reference}</span>
                      <h3>{trip.flight.flight_number} · {trip.flight.origin_airport} → {trip.flight.destination_airport}</h3>
                      <p>{formatFlightDate(trip.flight.departure_time)} · {formatFlightTime(trip.flight.departure_time)} to {formatFlightTime(trip.flight.arrival_time)} · {formatSeatClass(trip.flight.seat_class)}</p>
                    </div>
                    <div className="trip-card__price">
                      <span>{trip.passengers.length} passenger{trip.passengers.length === 1 ? "" : "s"}</span>
                      <strong>{formatCurrency(trip.total_price)}</strong>
                    </div>
                  </div>

                  <div className="trip-card__meta">
                    <span>Contact {trip.contact_name}</span>
                    <span>{trip.contact_email}</span>
                    <span>Terminal {trip.flight.terminal ?? "TBA"} · Gate {trip.flight.departure_gate ?? "TBA"}</span>
                    <span>Booked {formatTimestamp(trip.created_at)} · {formatSeatClass(trip.status)}</span>
                  </div>

                  <div className="trip-card__passengers">
                    {trip.passengers.map((passenger) => (
                      <article
                        className="trip-passenger"
                        key={`${trip.booking_reference}-${passenger.id ?? `${passenger.first_name}-${passenger.last_name}`}`}
                      >
                        <strong>{passenger.first_name} {passenger.last_name}</strong>
                        <span>{formatSeatClass(passenger.passenger_type)} · Seat {passenger.seat_number ?? "TBA"}</span>
                        <span>{passenger.seat_preference ? `${formatSeatClass(passenger.seat_preference)} preference` : "No seat preference"}</span>
                      </article>
                    ))}
                  </div>

                  {trip.extras?.length ? (
                    <div className="trip-card__extras">
                      {trip.extras.map((extra) => (
                        <span className="trip-extra" key={`${trip.booking_reference}-${extra.id}`}>
                          {formatSeatClass(extra.extra_type)} x{extra.quantity}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </article>
              )) : (
                <div className="flight-detail">
                  <h3>No booked trips yet</h3>
                  <p>Bookings confirmed from the flight search flow will appear here automatically.</p>
                </div>
              )}
            </section>
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
              <p>Run AI-driven capability tasks against the ElevenLabs agent, then inspect evaluator verdicts, root-cause classifications, tool traces, and backend effects per test id.</p>
            </header>

            <section className="testing-toolbar">
              <button type="button" className="button button--primary" onClick={() => executeTestingRun()} disabled={testingBusy}>
                <span className="material-symbols-outlined">play_arrow</span>
                Run all tasks
              </button>
              <select
                value={selectedTaskSlug}
                onChange={(event) => setSelectedTaskSlug(event.target.value)}
                className="testing-select testing-select--toolbar"
                disabled={testingBusy || !testingTasks.length}
              >
                {testingTasks.map((task) => (
                  <option key={task.slug} value={task.slug}>
                    {task.slug}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="button button--secondary"
                onClick={() => executeTestingRun(selectedTaskSlug ? { task: selectedTaskSlug } : {})}
                disabled={testingBusy || !selectedTaskSlug}
              >
                <span className="material-symbols-outlined">terminal</span>
                Run selected task
              </button>
              <button type="button" className="button button--secondary" onClick={() => refreshTestingRuns(selectedTestingRunId)} disabled={testingBusy}>
                <span className="material-symbols-outlined">refresh</span>
                Refresh runs
              </button>
            </section>

            <section className="testing-workspace">
              <div className="testing-workspace__left">
                <section className="testing-live">
                  <div className="testing-live__header">
                    <div>
                      <span className="eyebrow">Live output</span>
                      <strong>Chat outputs</strong>
                    </div>
                    <span className="status-pill status-pill--center">{testingBusy ? "Running..." : testingLiveActive ? "Streaming..." : "Idle"}</span>
                  </div>
                  <div className="testing-live__panels">
                    <div className="testing-live__panel">
                      <div className="testing-live__panel-head">
                        <span className="eyebrow">Conversation</span>
                        <strong>Readable chat</strong>
                      </div>
                      <div className="testing-transcript" ref={transcriptConsoleRef}>
                        {testingConversation.length ? testingConversation.map((item, index) => (
                          <article className={item.role === "user" ? "transcript-turn transcript-turn--user" : "transcript-turn transcript-turn--agent"} key={`${item.role}-${item.timestamp || index}`}>
                            <div className="transcript-turn__meta">
                              <span>{item.role === "user" ? "User" : item.role === "agent" ? "Agent" : item.role}</span>
                              <time>{formatTimestamp(item.timestamp)}</time>
                            </div>
                            <p>{item.text}</p>
                          </article>
                        )) : <p className="testing-muted">Waiting for conversation turns...</p>}
                      </div>
                    </div>
                    <div className="testing-live__panel">
                      <div className="testing-live__panel-head">
                        <span className="eyebrow">Steps</span>
                        <strong>Execution flow</strong>
                      </div>
                      <div className="testing-steps" ref={liveConsoleRef} aria-live="polite">
                        {testingLiveEvents.length ? testingLiveEvents.map((line, index) => (
                          <div className={`testing-step ${line.tag === "error" ? "testing-step--error" : line.tag === "eval" ? "testing-step--eval" : line.tag === "status" ? "testing-step--status" : "testing-step--accent"}`} key={`${line.tag}-${index}`}>
                            <span className="testing-step__time">{new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
                            <span className="testing-step__tag">{String(line.tag || "log").toUpperCase()}</span>
                            <span className="testing-step__text">{line.text}</span>
                          </div>
                        )) : <p className="testing-muted">[waiting] No live step output yet.</p>}
                      </div>
                    </div>
                  </div>
                </section>
                <section className="testing-refinement">
                  <section className="testing-refinement__card">
                    <div className="testing-refinement__head">
                      <div>
                        <span className="eyebrow">Refinement</span>
                        <strong>Evaluation and fixer flow</strong>
                      </div>
                      <span className="status-pill status-pill--center">{testingBusy ? "Running..." : testingLiveActive ? "Streaming..." : "Idle"}</span>
                    </div>
                    <div className="testing-refinement__timeline">
                      {testingRefinementEvents.length ? (
                        testingRefinementEvents.map((item, index) => (
                          <article
                            key={`${item.kind}-${item.timestamp || index}-${index}`}
                            className={`refinement-event refinement-event--${item.kind || "note"}`}
                          >
                            <div className="refinement-event__meta">
                              <span>{item.subtitle || "refinement"}</span>
                              <time>{formatTimestamp(item.timestamp)}</time>
                            </div>
                            <div className="refinement-event__title-row">
                              <strong>{item.title}</strong>
                              {typeof item.score !== "undefined" ? <span className="refinement-event__score">Score {item.score}</span> : null}
                            </div>
                            {item.body ? <p>{item.body}</p> : null}
                            {Array.isArray(item.details) && item.details.length ? (
                              <details className="refinement-event__details">
                                <summary>Details</summary>
                                <div>
                                  {item.details.map((detail, detailIndex) => (
                                    <div key={`${item.title}-${detailIndex}`}>{typeof detail === "string" ? detail : safeJson(detail)}</div>
                                  ))}
                                </div>
                              </details>
                            ) : null}
                          </article>
                        ))
                      ) : (
                        <p className="testing-muted">Waiting for evaluation and fixer output...</p>
                      )}
                    </div>
                  </section>

                  <section className="testing-refinement__stack">
                    <article className="testing-refinement__mini">
                      <div className="testing-refinement__mini-head">
                        <span className="eyebrow">Evaluation</span>
                        <strong>{refinementSections.evaluation.length ? `${refinementSections.evaluation.length} event${refinementSections.evaluation.length === 1 ? "" : "s"}` : "Waiting"}</strong>
                      </div>
                      {refinementSections.evaluation.length ? (
                        refinementSections.evaluation.map((item, index) => (
                          <div className="refinement-snippet" key={`evaluation-${index}`}>
                            <div className="refinement-snippet__head">
                              <strong>{item.title}</strong>
                              <time>{formatTimestamp(item.timestamp)}</time>
                            </div>
                            {item.body ? <p>{item.body}</p> : null}
                            {Array.isArray(item.details) && item.details.length ? <small>{item.details.length} detail item{item.details.length === 1 ? "" : "s"}</small> : null}
                          </div>
                        ))
                      ) : (
                        <p className="testing-muted">No evaluation events yet.</p>
                      )}
                    </article>

                    <article className="testing-refinement__mini">
                      <div className="testing-refinement__mini-head">
                        <span className="eyebrow">Refinement analysis</span>
                        <strong>{refinementSections.refinementAnalysis.length ? "Ready" : "Waiting"}</strong>
                      </div>
                      {refinementSections.refinementAnalysis.length ? (
                        refinementSections.refinementAnalysis.map((item, index) => (
                          <div className="refinement-snippet" key={`root-${index}`}>
                            <div className="refinement-snippet__head">
                              <strong>{item.title}</strong>
                              <time>{formatTimestamp(item.timestamp)}</time>
                            </div>
                            {item.subtitle ? <small>{item.subtitle}</small> : null}
                            {item.body ? <p>{item.body}</p> : null}
                          </div>
                        ))
                      ) : (
                        <p className="testing-muted">No refinement analysis yet.</p>
                      )}
                    </article>

                    <article className="testing-refinement__mini">
                      <div className="testing-refinement__mini-head">
                        <span className="eyebrow">Fix plan</span>
                        <strong>{refinementSections.fixPlan.length ? "Ready" : "Waiting"}</strong>
                      </div>
                      {refinementSections.fixPlan.length ? (
                        refinementSections.fixPlan.map((item, index) => (
                          <div className="refinement-snippet" key={`fix-${index}`}>
                            <div className="refinement-snippet__head">
                              <strong>{item.title}</strong>
                              <time>{formatTimestamp(item.timestamp)}</time>
                            </div>
                            {item.body ? <p>{item.body}</p> : null}
                          </div>
                        ))
                      ) : (
                        <p className="testing-muted">No fix plan yet.</p>
                      )}
                    </article>

                    <article className="testing-refinement__mini">
                      <div className="testing-refinement__mini-head">
                        <span className="eyebrow">Fixer edits</span>
                        <strong>{refinementSections.fixerEdits.length ? "Captured" : "Waiting"}</strong>
                      </div>
                      {refinementSections.fixerEdits.length ? (
                        refinementSections.fixerEdits.map((item, index) => (
                          <div className="refinement-snippet" key={`edit-${index}`}>
                            <div className="refinement-snippet__head">
                              <strong>{item.title}</strong>
                              <time>{formatTimestamp(item.timestamp)}</time>
                            </div>
                            {item.body ? <p>{item.body}</p> : null}
                          </div>
                        ))
                      ) : (
                        <p className="testing-muted">No fixer edits yet.</p>
                      )}
                    </article>

                    <article className="testing-refinement__mini">
                      <div className="testing-refinement__mini-head">
                        <span className="eyebrow">Completion</span>
                        <strong>{refinementSections.completion.length ? "Done" : "Waiting"}</strong>
                      </div>
                      {refinementSections.completion.length ? (
                        refinementSections.completion.map((item, index) => (
                          <div className="refinement-snippet" key={`completion-${index}`}>
                            <div className="refinement-snippet__head">
                              <strong>{item.title}</strong>
                              <time>{formatTimestamp(item.timestamp)}</time>
                            </div>
                            {item.body ? <p>{item.body}</p> : null}
                          </div>
                        ))
                      ) : (
                        <p className="testing-muted">No completion event yet.</p>
                      )}
                    </article>
                  </section>
                </section>
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
        <button type="button" className={screen === "trips" ? "mobile-nav__item active" : "mobile-nav__item"} onClick={() => setScreen("trips")}>
          <span className="material-symbols-outlined">badge</span>
          <span>Trips</span>
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
