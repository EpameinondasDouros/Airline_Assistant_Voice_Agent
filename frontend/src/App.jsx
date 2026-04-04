import { useEffect, useMemo, useRef, useState } from "react";
import {
  approveTestingPipeline,
  cancelTestingPipeline,
  createBooking,
  getChatHistory,
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

function normalizeChatHistory(items) {
  return items.map((item) => ({ role: item.role, text: item.content, createdAt: item.created_at }));
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
  const [pipelineStatus, setPipelineStatus] = useState("Loading self-improvement pipelines...");
  const [pipelineForm, setPipelineForm] = useState({
    task_slugs: [],
    target_score: 8,
    max_iterations: 5,
    review_model: "openai:gpt-4o-mini",
    fixer_model: "openai:gpt-4o-mini",
    require_manual_approval: true,
  });
  const [testingLiveEvents, setTestingLiveEvents] = useState([]);
  const [testingLogLines, setTestingLogLines] = useState([]);
  const [testingLiveActive, setTestingLiveActive] = useState(false);
  const liveConsoleRef = useRef(null);
  const logConsoleRef = useRef(null);
  const pipelineConsoleRef = useRef(null);
  const visibleFlights = useMemo(() => uniqueFlights(flights), [flights]);
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
  const selectedPipelineIteration = useMemo(() => {
    const iterations = selectedPipeline?.iterations;
    return Array.isArray(iterations) && iterations.length ? iterations[iterations.length - 1] : null;
  }, [selectedPipeline]);

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
    Promise.all([listTestingTasks(), listTestingRuns(), listTestingPipelines()])
      .then(([tasks, runs, pipelines]) => {
        setTestingTasks(tasks);
        setTestingRuns(runs);
        setTestingPipelines(pipelines);
        setSelectedTaskSlug(tasks[0]?.slug || "");
        setPipelineForm((current) =>
          current.task_slugs.length
            ? current
            : {
                ...current,
                task_slugs: tasks.map((task) => task.slug),
              }
        );
        setSelectedTestingRunId((current) => current || runs[0]?.id || null);
        setSelectedPipelineId((current) => current || pipelines[0]?.pipeline_id || null);
        setTestingStatus(runs.length ? `Loaded ${runs.length} testing runs.` : "No testing runs yet. Run a task to generate one.");
        setPipelineStatus(pipelines.length ? `Loaded ${pipelines.length} pipeline run${pipelines.length === 1 ? "" : "s"}.` : "No self-improvement pipelines yet.");
      })
      .catch((error) => {
        setTestingStatus(error.message);
        setPipelineStatus(error.message);
      });
  }, []);

  useEffect(() => {
    if (liveConsoleRef.current) {
      liveConsoleRef.current.scrollTop = liveConsoleRef.current.scrollHeight;
    }
  }, [testingLiveEvents, testingLiveActive]);

  useEffect(() => {
    if (logConsoleRef.current) {
      logConsoleRef.current.scrollTop = logConsoleRef.current.scrollHeight;
    }
  }, [testingLogLines]);

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

  function togglePipelineTask(taskSlug) {
    setPipelineForm((current) => {
      const exists = current.task_slugs.includes(taskSlug);
      return {
        ...current,
        task_slugs: exists
          ? current.task_slugs.filter((slug) => slug !== taskSlug)
          : [...current.task_slugs, taskSlug],
      };
    });
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
        return;
      }
      if (event.type === "evaluation_complete") {
        setTestingLiveEvents((current) => [...current, { tag: "eval", text: `Evaluation complete for ${event.task}.` }]);
        return;
      }
      if (event.type === "evaluation_error") {
        setTestingLiveEvents((current) => [...current, { tag: "error", text: event.error || "Evaluation failed." }]);
        return;
      }
      if (event.type === "task_finished") {
        setTestingLiveEvents((current) => [...current, { tag: "task", text: `Task ${event.task} finished.` }]);
        return;
      }
      if (event.type === "run_finished") {
        setTestingLiveEvents((current) => [...current, { tag: "run", text: "Run finished." }]);
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
              <div className="status-pill">Testing: {testingStatus}</div>
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

            <section className="pipeline-shell">
              <div className="pipeline-shell__header">
                <div>
                  <span className="eyebrow">Self-improvement pipeline</span>
                  <h2>Testing → Refinement → Code Change → Git Push</h2>
                  <p>Run iterative improvement loops against staging until the selected tasks reach the target score or the max-iteration limit.</p>
                </div>
                <div className="status-pill status-pill--center">Pipeline: {pipelineStatus}</div>
              </div>

              <div className="pipeline-grid">
                <section className="pipeline-card">
                  <div className="pipeline-card__head">
                    <span className="eyebrow">Create</span>
                    <strong>New pipeline</strong>
                  </div>
                  <div className="pipeline-task-list">
                    {testingTasks.map((task) => (
                      <label className="pipeline-task-option" key={task.slug}>
                        <input
                          type="checkbox"
                          checked={pipelineForm.task_slugs.includes(task.slug)}
                          onChange={() => togglePipelineTask(task.slug)}
                          disabled={pipelineBusy}
                        />
                        <span>
                          <strong>{task.slug}</strong>
                          <small>{task.description}</small>
                        </span>
                      </label>
                    ))}
                  </div>
                  <div className="pipeline-form-grid">
                    <label className="booking-field">
                      <span>Target score</span>
                      <input
                        type="number"
                        min="1"
                        max="10"
                        value={pipelineForm.target_score}
                        onChange={(event) => setPipelineForm((current) => ({ ...current, target_score: event.target.value }))}
                      />
                    </label>
                    <label className="booking-field">
                      <span>Max iterations</span>
                      <input
                        type="number"
                        min="1"
                        max="10"
                        value={pipelineForm.max_iterations}
                        onChange={(event) => setPipelineForm((current) => ({ ...current, max_iterations: event.target.value }))}
                      />
                    </label>
                    <label className="booking-field">
                      <span>Review model</span>
                      <input
                        value={pipelineForm.review_model}
                        onChange={(event) => setPipelineForm((current) => ({ ...current, review_model: event.target.value }))}
                      />
                    </label>
                    <label className="booking-field">
                      <span>Fixer model</span>
                      <input
                        value={pipelineForm.fixer_model}
                        onChange={(event) => setPipelineForm((current) => ({ ...current, fixer_model: event.target.value }))}
                      />
                    </label>
                  </div>
                  <label className="pipeline-toggle">
                    <input
                      type="checkbox"
                      checked={pipelineForm.require_manual_approval}
                      onChange={(event) =>
                        setPipelineForm((current) => ({ ...current, require_manual_approval: event.target.checked }))
                      }
                    />
                    <span>Pause for approval before code apply and git push</span>
                  </label>
                  <div className="pipeline-actions">
                    <button type="button" className="button button--primary" onClick={startPipelineRun} disabled={pipelineBusy || !pipelineForm.task_slugs.length}>
                      <span className="material-symbols-outlined">rocket_launch</span>
                      Start pipeline
                    </button>
                    <button
                      type="button"
                      className="button button--secondary"
                      onClick={approveSelectedPipeline}
                      disabled={pipelineBusy || selectedPipeline?.status !== "waiting_approval"}
                    >
                      <span className="material-symbols-outlined">done_all</span>
                      Approve iteration
                    </button>
                    <button
                      type="button"
                      className="button button--secondary"
                      onClick={cancelSelectedPipeline}
                      disabled={pipelineBusy || !selectedPipeline || pipelineIsTerminal(selectedPipeline.status)}
                    >
                      <span className="material-symbols-outlined">cancel</span>
                      Cancel pipeline
                    </button>
                  </div>
                </section>

                <section className="pipeline-card">
                  <div className="pipeline-card__head">
                    <span className="eyebrow">History</span>
                    <strong>Saved pipelines</strong>
                  </div>
                  <div className="pipeline-history">
                    {testingPipelines.length ? testingPipelines.map((pipeline) => (
                      <button
                        type="button"
                        key={pipeline.pipeline_id}
                        className={selectedPipelineId === pipeline.pipeline_id ? "pipeline-history__item active" : "pipeline-history__item"}
                        onClick={() => setSelectedPipelineId(pipeline.pipeline_id)}
                      >
                        <strong>{pipeline.pipeline_id}</strong>
                        <span>{pipeline.status} · iteration {pipeline.current_iteration}</span>
                        <small>{pipeline.task_slugs.join(", ")}</small>
                      </button>
                    )) : (
                      <p className="testing-muted">No pipelines yet. Start one from the left.</p>
                    )}
                  </div>
                </section>
              </div>

              {selectedPipeline ? (
                <section className="pipeline-detail">
                  <div className="pipeline-detail__header">
                    <div>
                      <span className="eyebrow">Selected pipeline</span>
                      <strong>{selectedPipeline.pipeline_id}</strong>
                      <p>{selectedPipeline.task_slugs?.join(", ")} · {selectedPipeline.status} · stage {selectedPipeline.stage}</p>
                    </div>
                    <div className="testing-metric-grid">
                      <article className="testing-metric">
                        <small>Current iteration</small>
                        <strong>{selectedPipeline.current_iteration || 0}</strong>
                      </article>
                      <article className="testing-metric">
                        <small>Target</small>
                        <strong>{selectedPipeline.target_score}/10</strong>
                      </article>
                      <article className="testing-metric">
                        <small>Branch</small>
                        <strong>{selectedPipeline.branch_name || "—"}</strong>
                      </article>
                      <article className="testing-metric">
                        <small>Deployed SHA</small>
                        <strong>{selectedPipeline.latest_deploy_sha ? selectedPipeline.latest_deploy_sha.slice(0, 10) : "—"}</strong>
                      </article>
                    </div>
                  </div>

                  {selectedPipeline.stop_reason ? (
                    <p className="testing-muted">Stop reason: {selectedPipeline.stop_reason}</p>
                  ) : null}

                  {selectedPipelineIteration ? (
                    <div className="pipeline-iteration">
                      <div className="pipeline-card__head">
                        <span className="eyebrow">Iteration snapshot</span>
                        <strong>Iteration {selectedPipelineIteration.iteration}</strong>
                      </div>
                      <div className="pipeline-iteration__meta">
                        <span>Status {selectedPipelineIteration.status}</span>
                        <span>Selected task {selectedPipelineIteration.selected_task_slug || "—"}</span>
                        <span>Deploy {selectedPipelineIteration.deploy_status || "pending"}</span>
                        <span>Commit {selectedPipelineIteration.git_commit_sha ? selectedPipelineIteration.git_commit_sha.slice(0, 10) : "—"}</span>
                      </div>
                      <div className="pipeline-task-results">
                        {(selectedPipelineIteration.task_results || []).map((result) => (
                          <article className="pipeline-task-result" key={`${selectedPipelineIteration.iteration}-${result.task_slug}`}>
                            <strong>{result.task_slug}</strong>
                            <span>Score {result.overall_score ?? "—"}/10</span>
                            <span>{result.goal_achieved ? "Goal achieved" : "Goal not met"}</span>
                            <span>{result.root_cause_category || "—"}</span>
                          </article>
                        ))}
                      </div>
                      {(selectedPipelineIteration.changed_paths || []).length ? (
                        <div className="pipeline-changes">
                          <span className="eyebrow">Changed paths</span>
                          <pre>{selectedPipelineIteration.changed_paths.join("\n")}</pre>
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  <div className="pipeline-event-panel">
                    <div className="pipeline-card__head">
                      <span className="eyebrow">Timeline</span>
                      <strong>events.jsonl stream</strong>
                    </div>
                    <pre className="testing-live__console" ref={pipelineConsoleRef} aria-live="polite">
                      {selectedPipelineEvents.length
                        ? selectedPipelineEvents
                            .map((event) => {
                              const stamp = event.timestamp ? formatTimestamp(event.timestamp) : "—";
                              return `[${stamp}] [${String(event.type).toUpperCase()}] ${event.message || ""}`;
                            })
                            .join("\n")
                        : "[waiting] No pipeline events yet."}
                    </pre>
                  </div>
                </section>
              ) : null}
            </section>

            {testingLiveActive || testingLiveEvents.length ? (
              <section className="testing-live">
                <div className="testing-live__header">
                  <div>
                    <span className="eyebrow">Live output</span>
                    <strong>Streaming test run</strong>
                  </div>
                  <span className="status-pill status-pill--center">{testingBusy ? "Running..." : "Complete"}</span>
                </div>
                <div className="testing-live__panels">
                  <div className="testing-live__panel">
                    <div className="testing-live__panel-head">
                      <span className="eyebrow">Steps</span>
                      <strong>Execution flow</strong>
                    </div>
                    <pre className="testing-live__console" ref={liveConsoleRef} aria-live="polite">
                      {testingLiveEvents.length
                        ? testingLiveEvents
                            .map((line) => {
                              const stamp = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
                              return `[${stamp}] [${String(line.tag).toUpperCase()}] ${line.text}`;
                            })
                            .join("\n")
                        : "[waiting] No live output yet."}
                    </pre>
                  </div>
                  <div className="testing-live__panel">
                    <div className="testing-live__panel-head">
                      <span className="eyebrow">Logs</span>
                      <strong>Raw agent output</strong>
                    </div>
                    <pre className="testing-live__console testing-live__console--logs" ref={logConsoleRef} aria-live="polite">
                      {testingLogLines.length ? testingLogLines.join("\n") : "[waiting] No raw log output yet."}
                    </pre>
                  </div>
                </div>
              </section>
            ) : null}
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
