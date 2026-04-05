import { useEffect, useMemo, useRef, useState } from "react";
import {
  approveTestingPipeline,
  cancelTestingPipeline,
  createBooking,
  getTestingPipeline,
  getTestingPipelineApplyResult,
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

function pipelineEventCategory(type) {
  const eventType = String(type || "").toLowerCase();
  if (eventType.includes("error") || eventType.includes("failed") || eventType.includes("blocked")) return "error";
  if (eventType.includes("approval")) return "approval";
  if (eventType.includes("deploy") || eventType.includes("git") || eventType.includes("code_apply") || eventType.includes("agent_sync")) return "code";
  if (eventType.includes("fix") || eventType.includes("refinement") || eventType.includes("root_cause")) return "refine";
  if (eventType.includes("evaluation") || eventType.includes("criterion") || eventType.includes("finding")) return "evaluation";
  if (eventType.includes("iteration") || eventType.includes("testing") || eventType.includes("task") || eventType.includes("run")) return "testing";
  return "note";
}

function formatPipelineEventTitle(type) {
  const eventType = String(type || "").replaceAll("_", " ").trim();
  if (!eventType) return "Pipeline event";
  return eventType.replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatElevenLabsTranscriptItems(transcript) {
  if (!Array.isArray(transcript) || transcript.length === 0) return [];

  const lines = ["ElevenLabs transcript:"];
  for (const item of transcript) {
    const role = String(item?.role || "");
    const text = String(item?.message || item?.text || "").trim();
    if (text) {
      if (role === "agent") {
        lines.push(`- Agent: ${text}`);
      } else if (role === "user" || role === "user_transcript") {
        lines.push(`- User: ${text}`);
      } else {
        lines.push(`- ${role || "Transcript"}: ${text}`);
      }
    }

    for (const toolCall of item?.tool_calls || []) {
      const name = String(toolCall?.tool_name || "unknown_tool").trim();
      const method = String(toolCall?.tool_details?.method || "").trim();
      const url = String(toolCall?.tool_details?.url || "").trim();
      const params = String(toolCall?.params_as_json || "").trim();
      const parts = [name];
      if (method) parts.push(method);
      if (url) parts.push(url);
      let line = `- Tool call: ${parts.filter(Boolean).join(" | ")}`;
      if (params) line += ` | params=${params}`;
      lines.push(line);
    }

    for (const toolResult of item?.tool_results || []) {
      const name = String(toolResult?.tool_name || "unknown_tool").trim();
      const status = toolResult?.is_error ? "error" : "ok";
      const latency = toolResult?.tool_latency_secs;
      const resultValue = String(toolResult?.result_value || "").trim();
      const parts = [name, status];
      if (typeof latency !== "undefined" && latency !== null && latency !== "") {
        parts.push(`latency=${latency}s`);
      }
      let line = `- Tool result: ${parts.join(" | ")}`;
      if (resultValue) line += ` | ${resultValue}`;
      lines.push(line);
    }
  }
  return lines;
}

function formatPipelineEventBody(event) {
  const parts = [];
  if (event.message) parts.push(String(event.message));
  const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
  const runtime = payload.event_payload && typeof payload.event_payload === "object" ? payload.event_payload : {};
  const extraLines = [];

  if (payload.task && !parts.some((line) => line.includes(String(payload.task)))) {
    extraLines.push(`Task: ${payload.task}`);
  }
  if (typeof payload.iteration !== "undefined") {
    extraLines.push(`Iteration: ${payload.iteration}`);
  }
  if (typeof payload.overall_score !== "undefined") {
    extraLines.push(`Score: ${payload.overall_score}/10`);
  }
  if (typeof payload.goal_achieved !== "undefined") {
    extraLines.push(`Goal achieved: ${payload.goal_achieved ? "yes" : "no"}`);
  }
  if (typeof payload.edit_count !== "undefined") {
    extraLines.push(`Edit count: ${payload.edit_count}`);
  }
  if (typeof payload.invalid_count !== "undefined") {
    extraLines.push(`Invalid edits: ${payload.invalid_count}`);
  }
  if (typeof payload.repaired_count !== "undefined") {
    extraLines.push(`Repaired edits: ${payload.repaired_count}`);
  }
  if (typeof payload.edit_index !== "undefined") {
    extraLines.push(`Edit index: ${payload.edit_index}`);
  }
  if (payload.health_url) {
    extraLines.push(`Health URL: ${payload.health_url}`);
  }
  if (typeof payload.health_status !== "undefined") {
    extraLines.push(`Health status: ${payload.health_status}`);
  }
  if (payload.phase) {
    extraLines.push(`Phase: ${payload.phase}`);
  }
  if (payload.path) {
    extraLines.push(`Path: ${payload.path}`);
  }
  if (payload.selector_type || payload.selector_value) {
    extraLines.push(`Selector: ${payload.selector_type || "unknown"}:${payload.selector_value || ""}`);
  }
  if (payload.error && !parts.some((line) => line.includes(String(payload.error)))) {
    extraLines.push(`Error: ${payload.error}`);
  }
  if (Array.isArray(payload.changed_paths) && payload.changed_paths.length) {
    extraLines.push(`Changed paths: ${payload.changed_paths.join(", ")}`);
  }
  if (typeof payload.stderr === "string" && payload.stderr.trim()) {
    extraLines.push(`stderr: ${payload.stderr.trim()}`);
  }
  if (typeof payload.stdout === "string" && payload.stdout.trim()) {
    extraLines.push(`stdout: ${payload.stdout.trim()}`);
  }
  if (typeof payload.approved !== "undefined") {
    extraLines.push(`Approved: ${payload.approved ? "yes" : "no"}`);
  }
  if (runtime.text && !parts.some((line) => line.includes(String(runtime.text)))) {
    extraLines.push(String(runtime.text));
  }
  if (runtime.message && !parts.some((line) => line.includes(String(runtime.message)))) {
    extraLines.push(String(runtime.message));
  }
  if (String(event.type || "") === "elevenlabs_analysis") {
    extraLines.push(...formatElevenLabsTranscriptItems(payload.transcript));
  }

  if (extraLines.length) {
    parts.push(extraLines.join("\n"));
  }
  return parts.join("\n");
}

const PIPELINE_PHASE_ORDER = [
  "start",
  "testing",
  "evaluation",
  "refinement",
  "fix_plan",
  "approval",
  "code_deploy",
  "final",
];

const PIPELINE_PHASE_LABELS = {
  start: "Start Pipeline",
  testing: "Testing",
  evaluation: "Evaluation",
  refinement: "Refinement Analysis",
  fix_plan: "Fix Planning",
  approval: "Approval",
  code_deploy: "Code Change / Deploy",
  final: "Final Summary",
};

const ACTIVE_PIPELINE_STATUSES = new Set(["running", "waiting_approval", "approving", "applying", "deploy_wait"]);

function getPipelineEventPayload(event) {
  return event?.payload && typeof event.payload === "object" ? event.payload : {};
}

function getPipelineRuntimePayload(event) {
  const payload = getPipelineEventPayload(event);
  return payload.event_payload && typeof payload.event_payload === "object" ? payload.event_payload : {};
}

function getPipelineEventIterationNumber(event) {
  const payload = getPipelineEventPayload(event);
  return event?.iteration ?? payload.iteration ?? null;
}

function getPipelineEventTaskSlug(event) {
  const payload = getPipelineEventPayload(event);
  const runtime = getPipelineRuntimePayload(event);
  return payload.task || payload.task_slug || runtime.task || null;
}

function getPipelinePhase(type) {
  const eventType = String(type || "").toLowerCase();
  if (eventType === "pipeline_started") return "start";
  if ([
    "iteration_started",
    "testing_started",
    "fixture_reset_skipped",
    "task_started",
    "user_turn",
    "customer_reply",
    "transcript_turn",
    "conversation_finalizing",
    "task_finished",
    "testing_complete",
    "run_started",
    "run_finished",
  ].includes(eventType)) {
    return "testing";
  }
  if ([
    "evaluation_started",
    "evaluation_complete",
    "elevenlabs_analysis",
    "evaluation_criterion",
    "evaluation_finding",
    "refinement_gate",
    "evaluation_error",
  ].includes(eventType)) {
    return "evaluation";
  }
  if (["refinement_started", "root_cause_complete", "refinement_error"].includes(eventType)) {
    return "refinement";
  }
  if ([
    "fix_plan_validation_started",
    "fix_plan_validation_failed",
    "fix_plan_repair_started",
    "fix_plan_repair_finished",
    "fix_plan_ready",
    "fixer_summary",
    "fixer_expected_improvement",
    "fixer_edit",
  ].includes(eventType)) {
    return "fix_plan";
  }
  if (eventType === "approval_required") return "approval";
  if ([
    "code_apply_started",
    "code_apply_finished",
    "agent_sync_started",
    "agent_sync_finished",
    "agent_sync_failed",
    "git_commit_finished",
    "git_push_finished",
    "git_push_skipped",
    "deploy_wait_started",
    "deploy_wait_health_check",
    "deploy_wait_progress",
    "deploy_verified",
    "deploy_skipped",
  ].includes(eventType)) {
    return "code_deploy";
  }
  if ([
    "iteration_complete",
    "pipeline_complete",
    "pipeline_failed",
    "pipeline_blocked",
  ].includes(eventType)) {
    return "final";
  }
  return "testing";
}

function getIterationTaskSlug(iterationRecord, fallbackTaskSlugs = []) {
  if (!iterationRecord) return fallbackTaskSlugs[0] || "";
  if (iterationRecord.selected_task_slug) return iterationRecord.selected_task_slug;
  if (Array.isArray(iterationRecord.task_results) && iterationRecord.task_results.length) {
    return iterationRecord.task_results[iterationRecord.task_results.length - 1]?.task_slug || fallbackTaskSlugs[0] || "";
  }
  return fallbackTaskSlugs[0] || "";
}

function buildPipelineTranscriptTurns(events) {
  const turns = [];
  for (const event of events) {
    const type = String(event?.type || "");
    const runtime = getPipelineRuntimePayload(event);
    let role = null;
    let text = "";
    let timestamp = event?.timestamp || null;

    if (type === "transcript_turn") {
      role = runtime.role || "turn";
      if (role === "user_transcript") role = "user";
      text = String(runtime.text || runtime.message || "").trim();
      timestamp = runtime.timestamp || timestamp;
    } else if (type === "user_turn") {
      role = "user";
      text = String(runtime.message || getPipelineEventPayload(event).message || "").trim();
    } else if (type === "customer_reply") {
      role = "user";
      text = String(runtime.message || getPipelineEventPayload(event).message || "").trim();
    }

    if (!text) continue;
    const last = turns[turns.length - 1];
    if (last && last.role === role && last.text === text) continue;
    turns.push({
      role,
      text,
      timestamp,
    });
  }
  return turns;
}

function formatPipelineSelectorOption(pipeline) {
  if (!pipeline) return "";
  const score = typeof pipeline.latest_evaluator_score === "number" ? ` · ${pipeline.latest_evaluator_score}/10` : "";
  return `${pipeline.pipeline_id} · ${pipeline.status}${score}`;
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
    rows: Array.from({ length: 20 }, (_, index) => index + 10),
    columns: ["A", "B", "C", "D", "E", "F"],
    windowColumns: new Set(["A", "F"]),
    aisleColumns: new Set(["C", "D"]),
    extraLegroomRows: new Set([18, 19, 20]),
  },
  premium_economy: {
    rows: Array.from({ length: 5 }, (_, index) => index + 5),
    columns: ["A", "B", "C", "D", "E", "F"],
    windowColumns: new Set(["A", "F"]),
    aisleColumns: new Set(["C", "D"]),
    extraLegroomRows: new Set(),
  },
  business: {
    rows: Array.from({ length: 4 }, (_, index) => index + 1),
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
  const cabin = getCabinForRow(row);
  if (!cabin) return { exists: false, active: false, extraLegroom: false };

  const layout = SEAT_LAYOUTS[cabin];
  const exists = layout.columns.includes(column);
  return {
    exists,
    active: exists && className === cabin,
    extraLegroom: exists && cabin === "economy" && layout.extraLegroomRows.has(row),
  };
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
  for (const [cabin, layout] of Object.entries(SEAT_LAYOUTS)) {
    if (layout.rows.includes(row)) return cabin;
  }
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
    seat_class: "",
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
    skip_fixture_reset: true,
  });
  const [selectedPipelineIterationNumber, setSelectedPipelineIterationNumber] = useState(null);
  const [selectedPipelineTaskSlug, setSelectedPipelineTaskSlug] = useState("");
  const [expandedPipelineIterations, setExpandedPipelineIterations] = useState([]);
  const [pipelineApplyResults, setPipelineApplyResults] = useState({});
  const [testingConversation, setTestingConversation] = useState([]);
  const [testingLiveEvents, setTestingLiveEvents] = useState([]);
  const [testingLogLines, setTestingLogLines] = useState([]);
  const [testingRefinementEvents, setTestingRefinementEvents] = useState([]);
  const [testingTaskBlocks, setTestingTaskBlocks] = useState([]);
  const [testingLiveActive, setTestingLiveActive] = useState(false);
  const currentTestingTaskRef = useRef(null);
  const transcriptConsoleRef = useRef(null);
  const liveConsoleRef = useRef(null);
  const logConsoleRef = useRef(null);
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
  const selectedPipelineSummary = useMemo(
    () => testingPipelines.find((pipeline) => pipeline.pipeline_id === selectedPipelineId) || null,
    [testingPipelines, selectedPipelineId]
  );
  const effectivePipelineSummary = useMemo(
    () => ({
      pipeline_id: selectedPipeline?.pipeline_id || selectedPipelineSummary?.pipeline_id || "",
      status: selectedPipeline?.status || selectedPipelineSummary?.status || "idle",
      stage: selectedPipeline?.stage || selectedPipelineSummary?.stage || "idle",
      target_score: selectedPipeline?.target_score ?? selectedPipelineSummary?.target_score ?? pipelineForm.target_score,
      max_iterations: selectedPipeline?.max_iterations ?? selectedPipelineSummary?.max_iterations ?? pipelineForm.max_iterations,
      current_iteration: selectedPipeline?.current_iteration ?? selectedPipelineSummary?.current_iteration ?? 0,
      branch_name: selectedPipeline?.branch_name || selectedPipelineSummary?.branch_name || "—",
      latest_evaluator_score: selectedPipelineSummary?.latest_evaluator_score ?? null,
      latest_task_slug: selectedPipelineSummary?.latest_task_slug || selectedPipeline?.latest_task_slug || "",
      stop_reason: selectedPipeline?.stop_reason || selectedPipelineSummary?.stop_reason || "",
      require_manual_approval:
        typeof selectedPipeline?.require_manual_approval === "boolean"
          ? selectedPipeline.require_manual_approval
          : Boolean(selectedPipelineSummary?.require_manual_approval ?? pipelineForm.require_manual_approval),
    }),
    [selectedPipeline, selectedPipelineSummary, pipelineForm]
  );
  const pipelineIterations = useMemo(() => {
    const manifestIterations = Array.isArray(selectedPipeline?.iterations) ? selectedPipeline.iterations : [];
    return [...manifestIterations].sort((left, right) => Number(left.iteration || 0) - Number(right.iteration || 0));
  }, [selectedPipeline]);
  const pipelineIterationNumbers = useMemo(() => {
    const values = new Set();
    for (const iteration of pipelineIterations) {
      if (iteration?.iteration) values.add(Number(iteration.iteration));
    }
    for (const event of selectedPipelineEvents) {
      const iteration = getPipelineEventIterationNumber(event);
      if (iteration) values.add(Number(iteration));
    }
    return [...values].sort((left, right) => left - right);
  }, [pipelineIterations, selectedPipelineEvents]);
  const pipelineEventsByIteration = useMemo(() => {
    const groups = new Map();
    for (const event of selectedPipelineEvents) {
      const iteration = getPipelineEventIterationNumber(event) || 0;
      if (!groups.has(iteration)) groups.set(iteration, []);
      groups.get(iteration).push(event);
    }
    return groups;
  }, [selectedPipelineEvents]);
  const pipelineTimeline = useMemo(() => {
    const globalStartEvents = [];
    const globalFinalEvents = [];
    const iterationGroups = [];

    for (const event of selectedPipelineEvents) {
      const iteration = getPipelineEventIterationNumber(event);
      const phase = getPipelinePhase(event.type);
      if (!iteration && phase === "start") {
        globalStartEvents.push(event);
      }
      if (!iteration && phase === "final") {
        globalFinalEvents.push(event);
      }
    }

    for (const iterationNumber of pipelineIterationNumbers) {
      const events = pipelineEventsByIteration.get(iterationNumber) || [];
      const phases = PIPELINE_PHASE_ORDER.map((phaseKey) => ({
        key: phaseKey,
        label: PIPELINE_PHASE_LABELS[phaseKey],
        events: events.filter((event) => getPipelinePhase(event.type) === phaseKey),
      })).filter((phase) => phase.events.length);
      const record = pipelineIterations.find((item) => Number(item.iteration) === Number(iterationNumber)) || null;
      iterationGroups.push({
        iterationNumber,
        record,
        phases,
      });
    }

    return { globalStartEvents, globalFinalEvents, iterationGroups };
  }, [selectedPipelineEvents, pipelineIterationNumbers, pipelineEventsByIteration, pipelineIterations]);
  const selectedIterationRecord = useMemo(
    () =>
      pipelineIterations.find((iteration) => Number(iteration.iteration) === Number(selectedPipelineIterationNumber)) ||
      pipelineIterations[pipelineIterations.length - 1] ||
      null,
    [pipelineIterations, selectedPipelineIterationNumber]
  );
  const selectedIterationTaskOptions = useMemo(() => {
    const values = new Set();
    if (Array.isArray(selectedIterationRecord?.task_results)) {
      for (const result of selectedIterationRecord.task_results) {
        if (result?.task_slug) values.add(result.task_slug);
      }
    }
    for (const event of selectedPipelineEvents) {
      const eventIteration = getPipelineEventIterationNumber(event);
      if (selectedIterationRecord && Number(eventIteration) !== Number(selectedIterationRecord.iteration)) continue;
      const taskSlug = getPipelineEventTaskSlug(event);
      if (taskSlug) values.add(taskSlug);
    }
    return [...values];
  }, [selectedIterationRecord, selectedPipelineEvents]);
  const selectedTaskResult = useMemo(() => {
    if (!selectedPipelineTaskSlug || !Array.isArray(selectedIterationRecord?.task_results)) return null;
    return selectedIterationRecord.task_results.find((result) => result.task_slug === selectedPipelineTaskSlug) || null;
  }, [selectedIterationRecord, selectedPipelineTaskSlug]);
  const selectedPipelineContextEvents = useMemo(() => {
    return selectedPipelineEvents.filter((event) => {
      const iteration = getPipelineEventIterationNumber(event);
      if (selectedIterationRecord && Number(iteration || 0) !== Number(selectedIterationRecord.iteration)) {
        return false;
      }
      const eventTask = getPipelineEventTaskSlug(event);
      if (!selectedPipelineTaskSlug) return true;
      if (!eventTask) return true;
      return eventTask === selectedPipelineTaskSlug;
    });
  }, [selectedPipelineEvents, selectedIterationRecord, selectedPipelineTaskSlug]);
  const pipelineConversationTurns = useMemo(
    () => buildPipelineTranscriptTurns(selectedPipelineContextEvents),
    [selectedPipelineContextEvents]
  );
  const pipelineTestingStepEvents = useMemo(() => {
    return selectedPipelineContextEvents.filter((event) => {
      const phase = getPipelinePhase(event.type);
      return phase === "testing" && !["transcript_turn", "user_turn", "customer_reply"].includes(String(event.type || ""));
    });
  }, [selectedPipelineContextEvents]);
  const pipelineDetailSections = useMemo(() => {
    const sections = {
      evaluation: [],
      rootCause: [],
      fixPlan: [],
      fixerEdits: [],
      codeDeploy: [],
      completion: [],
    };

    for (const event of selectedPipelineContextEvents) {
      const payload = getPipelineEventPayload(event);
      const item = {
        id: `${event.timestamp}-${event.type}-${getPipelineEventTaskSlug(event) || "pipeline"}`,
        type: event.type,
        title: formatPipelineEventTitle(event.type),
        timestamp: event.timestamp,
        body: formatPipelineEventBody(event),
        payload,
      };

      if (["evaluation_started", "evaluation_complete", "elevenlabs_analysis", "evaluation_criterion", "evaluation_finding", "refinement_gate", "evaluation_error"].includes(event.type)) {
        sections.evaluation.push(item);
        continue;
      }
      if (["refinement_started", "root_cause_complete", "refinement_error"].includes(event.type)) {
        sections.rootCause.push(item);
        continue;
      }
      if ([
        "fix_plan_validation_started",
        "fix_plan_validation_failed",
        "fix_plan_repair_started",
        "fix_plan_repair_finished",
        "fix_plan_ready",
        "fixer_summary",
        "fixer_expected_improvement",
      ].includes(event.type)) {
        sections.fixPlan.push(item);
        continue;
      }
      if (event.type === "fixer_edit") {
        sections.fixerEdits.push(item);
        continue;
      }
      if (["approval_required", "code_apply_started", "code_apply_finished", "agent_sync_started", "agent_sync_finished", "agent_sync_failed", "git_commit_finished", "git_push_finished", "git_push_skipped", "deploy_wait_started", "deploy_wait_health_check", "deploy_wait_progress", "deploy_verified", "deploy_skipped"].includes(event.type)) {
        sections.codeDeploy.push(item);
        continue;
      }
      if (["task_finished", "iteration_complete", "pipeline_complete", "pipeline_failed", "pipeline_blocked"].includes(event.type)) {
        sections.completion.push(item);
      }
    }

    return sections;
  }, [selectedPipelineContextEvents]);
  const pipelineIterationAccordions = useMemo(() => {
    const globalFinalEvents = selectedPipelineEvents.filter(
      (event) => !getPipelineEventIterationNumber(event) && ["pipeline_complete", "pipeline_failed", "pipeline_blocked"].includes(String(event.type || ""))
    );
    const lastIterationNumber = pipelineIterationNumbers[pipelineIterationNumbers.length - 1] || null;

    return pipelineIterationNumbers.map((iterationNumber) => {
      const record =
        pipelineIterations.find((iteration) => Number(iteration.iteration) === Number(iterationNumber)) || null;
      const latestTaskResult =
        Array.isArray(record?.task_results) && record.task_results.length
          ? record.task_results[record.task_results.length - 1]
          : null;
      const events = (pipelineEventsByIteration.get(iterationNumber) || []).filter(Boolean);
      const taskSlug =
        getIterationTaskSlug(record, selectedPipeline?.task_slugs || []) ||
        getPipelineEventTaskSlug(events.find((event) => getPipelineEventTaskSlug(event))) ||
        "";

      const transcriptTurns = buildPipelineTranscriptTurns(events);
      const testingSetupEvents = events.filter((event) =>
        ["iteration_started", "testing_started", "fixture_reset_skipped", "task_started", "conversation_finalizing"].includes(String(event.type || ""))
      );
      const evaluationEvents = events.filter((event) =>
        ["evaluation_started", "evaluation_complete", "elevenlabs_analysis", "evaluation_criterion", "evaluation_finding", "refinement_gate", "evaluation_error"].includes(String(event.type || ""))
      );
      const analysisEvents = events.filter((event) =>
        ["refinement_started", "root_cause_complete", "refinement_error"].includes(String(event.type || ""))
      );
      const fixPlanEvents = events.filter((event) =>
        [
          "fix_plan_validation_started",
          "fix_plan_validation_failed",
          "fix_plan_repair_started",
          "fix_plan_repair_finished",
          "fix_plan_ready",
          "fixer_summary",
          "fixer_expected_improvement",
          "fixer_edit",
        ].includes(String(event.type || ""))
      );
      const approvalEvents = events.filter((event) => String(event.type || "") === "approval_required");
      const codeChangeEvents = events.filter((event) =>
        ["code_apply_started", "code_apply_finished", "git_commit_finished", "git_push_finished", "git_push_skipped"].includes(String(event.type || ""))
      );
      const syncPostDeployEvents = events.filter((event) =>
        ["agent_sync_started", "agent_sync_finished", "agent_sync_failed", "deploy_wait_started", "deploy_wait_health_check", "deploy_wait_progress", "deploy_verified", "deploy_skipped"].includes(String(event.type || ""))
      );
      const iterationResultEvents = events.filter((event) =>
        ["task_finished", "testing_complete", "iteration_complete"].includes(String(event.type || ""))
      );
      const completionEvents =
        Number(iterationNumber) === Number(lastIterationNumber)
          ? [
              ...events.filter((event) => ["pipeline_complete", "pipeline_failed", "pipeline_blocked"].includes(String(event.type || ""))),
              ...globalFinalEvents,
            ]
          : events.filter((event) => ["pipeline_complete", "pipeline_failed", "pipeline_blocked"].includes(String(event.type || "")));

      return {
        iterationNumber,
        record,
        taskSlug,
        overallScore: latestTaskResult?.overall_score ?? null,
        applyResult: pipelineApplyResults[Number(iterationNumber)] || null,
        sections: [
          {
            key: "testing",
            label: "Testing",
            transcriptTurns,
            events: testingSetupEvents,
            emptyText: "No testing transcript is available for this iteration.",
          },
          {
            key: "evaluation",
            label: "Evaluation",
            events: evaluationEvents,
            emptyText: "No evaluation output yet.",
          },
          {
            key: "analysis",
            label: "Analysis",
            events: analysisEvents,
            emptyText:
              latestTaskResult?.needs_refinement === false
                ? "No analysis was needed because this iteration already met the target."
                : "No analysis output yet.",
          },
          {
            key: "fix_planning",
            label: "Fix Planning",
            events: fixPlanEvents,
            emptyText:
              latestTaskResult?.needs_refinement === false
                ? "No fix plan was needed for this iteration."
                : "No fix plan yet.",
          },
          {
            key: "approval",
            label: "Approval",
            events: approvalEvents,
            emptyText:
              record?.status === "waiting_approval"
                ? "Approval is expected but the event has not arrived yet."
                : "No approval step was required.",
          },
          {
            key: "code_change",
            label: "Code Change",
            events: codeChangeEvents,
            emptyText: "No code-change events for this iteration.",
          },
          {
            key: "sync_post_deploy",
            label: "Sync Post-Deploy",
            events: syncPostDeployEvents,
            emptyText: "No sync or deploy events for this iteration.",
          },
          {
            key: "iteration_results",
            label: "Iteration Results",
            events: iterationResultEvents,
            emptyText: "No iteration result events yet.",
          },
          {
            key: "complete",
            label: "Complete",
            events: completionEvents,
            emptyText: "No terminal completion event yet.",
          },
        ],
      };
    });
  }, [selectedPipelineEvents, pipelineIterationNumbers, pipelineIterations, pipelineEventsByIteration, selectedPipeline?.task_slugs, pipelineApplyResults]);
  const latestApprovalEvent = useMemo(() => {
    for (let index = selectedPipelineEvents.length - 1; index >= 0; index -= 1) {
      const event = selectedPipelineEvents[index];
      if (event?.type === "approval_required") return event;
    }
    return null;
  }, [selectedPipelineEvents]);
  const pipelineCurrentTaskSlug = pipelineForm.task_slugs[0] || "";
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
    searchFlights({
      origin: "ATH",
      destination: "JFK",
      departure_date_from: "2026-04-01",
      departure_date_to: "2026-04-30",
      seat_class: "",
      max_price: "2500",
      sort_by: "departure_time",
      only_available: true,
      limit: 20,
    })
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
    if (logConsoleRef.current) {
      logConsoleRef.current.scrollTop = logConsoleRef.current.scrollHeight;
    }
  }, [testingLogLines, testingLiveActive]);

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
      setPipelineApplyResults({});
      return;
    }
    setPipelineApplyResults({});
    refreshPipelineDetails(selectedPipelineId).catch((error) => {
      setPipelineStatus(error.message);
    });
  }, [selectedPipelineId]);

  useEffect(() => {
    if (!selectedPipelineId) return;
    const pendingIterations = pipelineIterations.filter((iteration) => {
      const iterationNumber = Number(iteration?.iteration || 0);
      if (!iterationNumber || !expandedPipelineIterations.includes(iterationNumber)) return false;
      if (!iteration?.apply_result_path) return false;
      return !pipelineApplyResults[iterationNumber];
    });
    if (!pendingIterations.length) return;

    let canceled = false;
    Promise.all(
      pendingIterations.map((iteration) =>
        getTestingPipelineApplyResult(selectedPipelineId, Number(iteration.iteration))
          .then((payload) => ({
            iterationNumber: Number(iteration.iteration),
            payload,
          }))
          .catch((error) => ({
            iterationNumber: Number(iteration.iteration),
            payload: { error: error.message },
          }))
      )
    ).then((results) => {
      if (canceled) return;
      setPipelineApplyResults((current) => {
        const next = { ...current };
        for (const result of results) {
          next[result.iterationNumber] = result.payload;
        }
        return next;
      });
    });

    return () => {
      canceled = true;
    };
  }, [selectedPipelineId, pipelineIterations, expandedPipelineIterations, pipelineApplyResults]);

  useEffect(() => {
    if (!pipelineIterationNumbers.length) {
      setSelectedPipelineIterationNumber(null);
      setExpandedPipelineIterations([]);
      return;
    }
    const latestIteration =
      Number(selectedPipeline?.current_iteration) ||
      pipelineIterationNumbers[pipelineIterationNumbers.length - 1] ||
      null;
    setSelectedPipelineIterationNumber((current) =>
      current && pipelineIterationNumbers.includes(Number(current)) ? current : latestIteration
    );
    setExpandedPipelineIterations((current) => {
      const filtered = current.filter((value) => pipelineIterationNumbers.includes(Number(value)));
      if (filtered.length) return filtered;
      return latestIteration ? [latestIteration] : [];
    });
  }, [selectedPipeline?.current_iteration, pipelineIterationNumbers]);

  useEffect(() => {
    const fallbackTask =
      getIterationTaskSlug(selectedIterationRecord, selectedPipeline?.task_slugs || []) ||
      selectedIterationTaskOptions[0] ||
      "";
    setSelectedPipelineTaskSlug((current) => {
      if (current && selectedIterationTaskOptions.includes(current)) return current;
      return fallbackTask;
    });
  }, [selectedIterationRecord, selectedIterationTaskOptions, selectedPipeline?.task_slugs]);

  useEffect(() => {
    if (screen !== "refinement" || !selectedPipelineId) {
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
    }, 2000);
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

  function appendTestingTaskStep(taskSlug, step) {
    if (!taskSlug || !step) return;
    setTestingTaskBlocks((current) => {
      const next = [...current];
      const index = next.findIndex((item) => item.task === taskSlug);
      const block =
        index >= 0
          ? next[index]
          : {
              task: taskSlug,
              status: "running",
              startedAt: new Date().toISOString(),
              finishedAt: null,
              conversation: [],
              steps: [],
            };
      const last = block.steps[block.steps.length - 1];
      if (last && last.tag === step.tag && last.text === step.text) {
        if (index === -1) next.push(block);
        return next;
      }
      const updated = {
        ...block,
        steps: [...block.steps, step],
      };
      if (index >= 0) {
        next[index] = updated;
      } else {
        next.push(updated);
      }
      return next;
    });
  }

  function appendTestingTaskConversation(taskSlug, turn) {
    if (!taskSlug || !turn?.text) return;
    setTestingTaskBlocks((current) => {
      const next = [...current];
      const index = next.findIndex((item) => item.task === taskSlug);
      const block =
        index >= 0
          ? next[index]
          : {
              task: taskSlug,
              status: "running",
              startedAt: new Date().toISOString(),
              finishedAt: null,
              conversation: [],
              steps: [],
            };
      const last = block.conversation[block.conversation.length - 1];
      if (last && last.role === turn.role && last.text === turn.text) {
        if (index === -1) next.push(block);
        return next;
      }
      const updated = {
        ...block,
        conversation: [...block.conversation, turn],
      };
      if (index >= 0) {
        next[index] = updated;
      } else {
        next.push(updated);
      }
      return next;
    });
  }

  function updateTestingTaskStatus(taskSlug, status, extra = {}) {
    if (!taskSlug) return;
    setTestingTaskBlocks((current) => {
      const next = [...current];
      const index = next.findIndex((item) => item.task === taskSlug);
      const block =
        index >= 0
          ? next[index]
          : {
              task: taskSlug,
              status: "running",
              startedAt: new Date().toISOString(),
              finishedAt: null,
              conversation: [],
              steps: [],
            };
      const updated = {
        ...block,
        status,
        ...extra,
      };
      if (index >= 0) {
        next[index] = updated;
      } else {
        next.push(updated);
      }
      return next;
    });
  }

  function executeTestingRun(payload = {}) {
    setTestingBusy(true);
    setTestingLiveActive(true);
    currentTestingTaskRef.current = payload.task || null;
    setTestingConversation([]);
    setTestingLiveEvents([{ tag: "status", text: "Connecting to live test runner..." }]);
    setTestingLogLines([]);
    setTestingRefinementEvents([]);
    setTestingTaskBlocks([]);
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
        currentTestingTaskRef.current = event.task || currentTestingTaskRef.current;
        updateTestingTaskStatus(event.task || currentTestingTaskRef.current, "running", {
          startedAt: event.timestamp || new Date().toISOString(),
        });
        setTestingLiveEvents((current) => [...current, { tag: "task", text: `Task ${event.task} started.` }]);
        appendTestingTaskStep(event.task || currentTestingTaskRef.current, {
          tag: "task",
          text: `Task ${event.task} started.`,
          timestamp: event.timestamp || new Date().toISOString(),
        });
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
          const taskSlug = event.task || currentTestingTaskRef.current || payload.task || selectedTaskSlug || "task";
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
          appendTestingTaskConversation(taskSlug, {
            role: event.role || "turn",
            text,
            timestamp: event.timestamp || null,
          });
          setTestingLiveEvents((current) => {
            const last = current[current.length - 1];
            if (last && last.tag === event.role && last.text === text) {
              return current;
            }
            return [...current, { tag: event.role || "turn", text }];
          });
          appendTestingTaskStep(taskSlug, {
            tag: event.role || "turn",
            text,
            timestamp: event.timestamp || new Date().toISOString(),
          });
        }
        return;
      }
      if (event.type === "evaluation_started") {
        setTestingLiveEvents((current) => [...current, { tag: "eval", text: `Evaluating ${event.task}.` }]);
        appendTestingTaskStep(event.task || currentTestingTaskRef.current, {
          tag: "eval",
          text: `Evaluating ${event.task}.`,
          timestamp: new Date().toISOString(),
        });
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
        appendTestingTaskStep(event.task || currentTestingTaskRef.current, {
          tag: "eval",
          text: `Evaluation complete for ${event.task}.`,
          timestamp: new Date().toISOString(),
        });
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
              ...formatElevenLabsTranscriptItems(event.transcript),
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
        appendTestingTaskStep(event.task || currentTestingTaskRef.current, {
          tag: "error",
          text: event.error || "Refinement analysis failed.",
          timestamp: new Date().toISOString(),
        });
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
      if (
        event.type === "fix_plan_validation_started" ||
        event.type === "fix_plan_validation_failed" ||
        event.type === "fix_plan_repair_started" ||
        event.type === "fix_plan_repair_finished" ||
        event.type === "fix_plan_ready" ||
        event.type === "fixer_summary" ||
        event.type === "fixer_expected_improvement" ||
        event.type === "fixer_edit"
      ) {
        setTestingRefinementEvents((current) => [
          ...current,
          {
            kind: "fixer",
            title:
              event.type === "fix_plan_validation_started"
                ? "Fix plan validation started"
                : event.type === "fix_plan_validation_failed"
                  ? "Fix plan validation failed"
                  : event.type === "fix_plan_repair_started"
                    ? "Fix plan repair started"
                    : event.type === "fix_plan_repair_finished"
                      ? "Fix plan repair finished"
                      : event.type === "fix_plan_ready"
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
        appendTestingTaskStep(event.task || currentTestingTaskRef.current, {
          tag: "error",
          text: event.error || "Evaluation failed.",
          timestamp: new Date().toISOString(),
        });
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
        updateTestingTaskStatus(event.task || currentTestingTaskRef.current, "completed", {
          finishedAt: event.timestamp || new Date().toISOString(),
        });
        appendTestingTaskStep(event.task || currentTestingTaskRef.current, {
          tag: "task",
          text: `Task ${event.task} finished.`,
          timestamp: event.timestamp || new Date().toISOString(),
        });
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
        appendTestingTaskStep(currentTestingTaskRef.current || payload.task, {
          tag: "error",
          text: event.message || "Testing failed.",
          timestamp: new Date().toISOString(),
        });
        updateTestingTaskStatus(currentTestingTaskRef.current || payload.task, "failed");
        return;
      }
      if (event.type === "log") {
        const cleaned = stripAnsi(event.message || "");
        if (cleaned) {
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
          <button className={screen === "refinement" ? "tab active" : "tab"} onClick={() => setScreen("refinement")}>Refinement</button>
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
          <button className={screen === "refinement" ? "sidebar__item active" : "sidebar__item"} onClick={() => setScreen("refinement")}>Refinement</button>
          <button className={screen === "testing" ? "sidebar__item active" : "sidebar__item"} onClick={() => setScreen("testing")}>Testing</button>
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
                <span className="material-symbols-outlined">airline_seat_recline_normal</span>
                <div>
                  <small>Ticket class</small>
                  <select value={flightFilters.seat_class} onChange={(event) => setFlightFilters((current) => ({ ...current, seat_class: event.target.value }))}>
                    <option value="">All classes</option>
                    <option value="economy">Economy</option>
                    <option value="premium_economy">Premium Economy</option>
                    <option value="business">Business</option>
                  </select>
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
                                    const seatNumber = planeSeat.exists ? buildSeatNumber(cabin, row, column) || `${row}${column}` : "";
                                    const meta = seatMetadata(cabin, seatNumber);
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
        ) : screen === "refinement" ? (
          <>
            <header className="page-header">
              <h1>Refinement</h1>
              <p>Run the self-improvement pipeline from the UI, inspect each iteration as it unfolds, and review testing, evaluation, refinement, approval, code apply, deploy, and final outcome in one place.</p>
            </header>

            <section className="pipeline-page">
              <section className="pipeline-control-bar">
                <div className="pipeline-control-grid">
                  <label className="pipeline-field">
                    <span>Recent pipeline</span>
                    <select
                      value={selectedPipelineId || ""}
                      onChange={(event) => setSelectedPipelineId(event.target.value || null)}
                      className="testing-select testing-select--full"
                      disabled={pipelineBusy || !testingPipelines.length}
                    >
                      <option value="">Select pipeline</option>
                      {testingPipelines.map((pipeline) => (
                        <option key={pipeline.pipeline_id} value={pipeline.pipeline_id}>
                          {formatPipelineSelectorOption(pipeline)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="pipeline-field">
                    <span>Task</span>
                    <select
                      value={pipelineCurrentTaskSlug}
                      onChange={(event) => setPipelineTask(event.target.value)}
                      className="testing-select testing-select--full"
                      disabled={pipelineBusy || !testingTasks.length}
                    >
                      {testingTasks.map((task) => (
                        <option key={task.slug} value={task.slug}>
                          {task.slug}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="pipeline-field">
                    <span>Target score</span>
                    <input
                      className="pipeline-input"
                      type="number"
                      min="1"
                      max="10"
                      value={pipelineForm.target_score}
                      onChange={(event) =>
                        setPipelineForm((current) => ({ ...current, target_score: event.target.value }))
                      }
                      disabled={pipelineBusy}
                    />
                  </label>
                  <label className="pipeline-field">
                    <span>Max iterations</span>
                    <input
                      className="pipeline-input"
                      type="number"
                      min="1"
                      max="10"
                      value={pipelineForm.max_iterations}
                      onChange={(event) =>
                        setPipelineForm((current) => ({ ...current, max_iterations: event.target.value }))
                      }
                      disabled={pipelineBusy}
                    />
                  </label>
                </div>

                <div className="pipeline-actions">
                  <button type="button" className="button button--primary" onClick={startPipelineRun} disabled={pipelineBusy || !pipelineCurrentTaskSlug}>
                    <span className="material-symbols-outlined">rocket_launch</span>
                    Start pipeline
                  </button>
                  {effectivePipelineSummary.status === "waiting_approval" ? (
                    <button type="button" className="button button--secondary" onClick={approveSelectedPipeline} disabled={pipelineBusy || !selectedPipelineId}>
                      <span className="material-symbols-outlined">task_alt</span>
                      Approve
                    </button>
                  ) : null}
                  {selectedPipelineId && ACTIVE_PIPELINE_STATUSES.has(String(effectivePipelineSummary.status || "")) ? (
                    <button type="button" className="button button--secondary" onClick={cancelSelectedPipeline} disabled={pipelineBusy}>
                      <span className="material-symbols-outlined">cancel</span>
                      Cancel
                    </button>
                  ) : null}
                </div>

                <details className="pipeline-advanced">
                  <summary>Advanced settings</summary>
                  <div className="pipeline-advanced__grid">
                    <label className="pipeline-field">
                      <span>Review model</span>
                      <input
                        className="pipeline-input"
                        value={pipelineForm.review_model}
                        onChange={(event) =>
                          setPipelineForm((current) => ({ ...current, review_model: event.target.value }))
                        }
                        disabled={pipelineBusy}
                      />
                    </label>
                    <label className="pipeline-field">
                      <span>Fixer model</span>
                      <input
                        className="pipeline-input"
                        value={pipelineForm.fixer_model}
                        onChange={(event) =>
                          setPipelineForm((current) => ({ ...current, fixer_model: event.target.value }))
                        }
                        disabled={pipelineBusy}
                      />
                    </label>
                    <label className="pipeline-toggle">
                      <input
                        type="checkbox"
                        checked={pipelineForm.require_manual_approval}
                        onChange={(event) =>
                          setPipelineForm((current) => ({
                            ...current,
                            require_manual_approval: event.target.checked,
                          }))
                        }
                        disabled={pipelineBusy}
                      />
                      <span>Require manual approval before apply</span>
                    </label>
                    <div className="pipeline-toggle pipeline-toggle--static">
                      <span>Database reset is disabled. Pipeline runs always preserve existing data.</span>
                    </div>
                  </div>
                </details>
              </section>

              {effectivePipelineSummary.status === "waiting_approval" && latestApprovalEvent ? (
                <section className="pipeline-approval-banner">
                  <div>
                    <span className="eyebrow">Approval required</span>
                    <strong>{latestApprovalEvent.message || "The current iteration is waiting for approval."}</strong>
                  </div>
                  <div className="pipeline-actions">
                    <button type="button" className="button button--primary" onClick={approveSelectedPipeline} disabled={pipelineBusy || !selectedPipelineId}>
                      <span className="material-symbols-outlined">task_alt</span>
                      Approve iteration
                    </button>
                    <button type="button" className="button button--secondary" onClick={cancelSelectedPipeline} disabled={pipelineBusy}>
                      <span className="material-symbols-outlined">cancel</span>
                      Cancel pipeline
                    </button>
                  </div>
                </section>
              ) : null}

              <section className="pipeline-timeline-card">
                <div className="pipeline-timeline-card__head">
                  <div>
                    <span className="eyebrow">Pipeline iterations</span>
                    <strong>Iteration workflow</strong>
                  </div>
                  <span className="testing-muted">
                    {pipelineIterationAccordions.length ? `${pipelineIterationAccordions.length} iteration${pipelineIterationAccordions.length === 1 ? "" : "s"}` : "No iterations yet"}
                  </span>
                </div>

                <div className="pipeline-accordions" ref={pipelineConsoleRef}>
                  {pipelineIterationAccordions.length ? (
                    pipelineIterationAccordions.map((iteration) => {
                      const expanded = expandedPipelineIterations.includes(Number(iteration.iterationNumber));
                      return (
                        <section className="pipeline-accordion" key={`iteration-${iteration.iterationNumber}`}>
                          <button
                            type="button"
                            className="pipeline-accordion__trigger"
                            onClick={() =>
                              setExpandedPipelineIterations((current) =>
                                current.includes(Number(iteration.iterationNumber))
                                  ? current.filter((value) => Number(value) !== Number(iteration.iterationNumber))
                                  : [...current, Number(iteration.iterationNumber)].sort((left, right) => left - right)
                              )
                            }
                            aria-expanded={expanded}
                          >
                            <div className="pipeline-accordion__summary">
                              <span className="eyebrow">Iteration {iteration.iterationNumber}</span>
                              <strong>{iteration.taskSlug || effectivePipelineSummary.latest_task_slug || "Pipeline task"}</strong>
                              <small>
                                {formatSeatClass(iteration.record?.status || "running")}
                                {typeof iteration.overallScore === "number" ? ` · ${iteration.overallScore}/10` : ""}
                              </small>
                            </div>
                            <span className={expanded ? "pipeline-accordion__chevron pipeline-accordion__chevron--open" : "pipeline-accordion__chevron"}>
                              <span className="material-symbols-outlined">expand_more</span>
                            </span>
                          </button>

                          {expanded ? (
                            <div className="pipeline-accordion__content">
                              {iteration.sections.map((section) => {
                                const codeChanges = section.key === "code_change" ? iteration.applyResult : null;
                                const hasCodeChanges = Boolean(
                                  codeChanges &&
                                    (codeChanges.error ||
                                      (Array.isArray(codeChanges.applied_changes) && codeChanges.applied_changes.length))
                                );
                                return (
                                <section className={`pipeline-phase-section pipeline-phase-section--${section.key}`} key={`${iteration.iterationNumber}-${section.key}`}>
                                  <div className="pipeline-phase-section__head">
                                    <strong>{section.label}</strong>
                                  </div>

                                  {section.key === "testing" ? (
                                    section.transcriptTurns && section.transcriptTurns.length ? (
                                      <div className="pipeline-transcript pipeline-transcript--inline">
                                        {section.transcriptTurns.map((item, index) => (
                                          <article className={item.role === "user" ? "transcript-turn transcript-turn--user" : "transcript-turn transcript-turn--agent"} key={`${iteration.iterationNumber}-${item.role}-${item.timestamp || index}`}>
                                            <div className="transcript-turn__meta">
                                              <span>{item.role === "user" ? "User" : item.role === "agent" ? "Agent" : item.role}</span>
                                              <time>{formatTimestamp(item.timestamp)}</time>
                                            </div>
                                            <p>{item.text}</p>
                                          </article>
                                        ))}
                                      </div>
                                    ) : section.events.length ? (
                                      <div className="pipeline-section-card__list">
                                        {section.events.map((event, index) => (
                                          <article className={`pipeline-step-card pipeline-step-card--${pipelineEventCategory(event.type)}`} key={`${event.timestamp}-${event.type}-${index}`}>
                                            <div className="pipeline-event-card__meta">
                                              <span>{formatPipelineEventTitle(event.type)}</span>
                                              <time>{formatTimestamp(event.timestamp)}</time>
                                            </div>
                                            <p>{formatPipelineEventBody(event)}</p>
                                          </article>
                                        ))}
                                      </div>
                                    ) : (
                                      <p className="testing-muted">{section.emptyText}</p>
                                    )
                                  ) : section.events.length || hasCodeChanges ? (
                                    <div className="pipeline-section-card__list">
                                      {section.events.map((event, index) => (
                                        <article className="pipeline-detail-event" key={`${event.timestamp}-${event.type}-${index}`}>
                                          <div className="pipeline-event-card__meta">
                                            <span>{formatPipelineEventTitle(event.type)}</span>
                                            <time>{formatTimestamp(event.timestamp)}</time>
                                          </div>
                                          <p>{formatPipelineEventBody(event)}</p>
                                        </article>
                                      ))}
                                      {section.key === "code_change" && hasCodeChanges ? (
                                        <div className="pipeline-code-changes">
                                          <div className="pipeline-code-summary">
                                            {Array.isArray(codeChanges?.applied_changes) ? (
                                              <span>
                                                {codeChanges.applied_changes.filter((change) => change.applied).length} applied change
                                                {codeChanges.applied_changes.filter((change) => change.applied).length === 1 ? "" : "s"}
                                              </span>
                                            ) : null}
                                            {iteration.record?.git_commit_sha ? (
                                              <span>Commit {String(iteration.record.git_commit_sha).slice(0, 12)}</span>
                                            ) : null}
                                            {typeof codeChanges?.compile_result?.success === "boolean" ? (
                                              <span>Validation {codeChanges.compile_result.success ? "passed" : "failed"}</span>
                                            ) : null}
                                          </div>
                                          {codeChanges?.error ? (
                                            <article className="pipeline-detail-event pipeline-detail-event--error">
                                              <p>{codeChanges.error}</p>
                                            </article>
                                          ) : null}
                                          {Array.isArray(codeChanges?.applied_changes)
                                            ? codeChanges.applied_changes.map((change, index) => (
                                                <details className="pipeline-change-card" key={`${change.path}-${change.selector_value}-${index}`}>
                                                  <summary className="pipeline-change-card__summary">
                                                    <div className="pipeline-change-card__summary-copy">
                                                      <strong>{change.path}</strong>
                                                      <span>{change.selector_type}:{change.selector_value}</span>
                                                    </div>
                                                    <span>{change.applied ? "Applied" : "Not applied"}</span>
                                                  </summary>
                                                  {change.error ? <p className="testing-muted">{change.error}</p> : null}
                                                  <div className="pipeline-change-diff">
                                                    <div className="pipeline-change-pane">
                                                      <span className="eyebrow">Before</span>
                                                      <pre>{change.before_content || "—"}</pre>
                                                    </div>
                                                    <div className="pipeline-change-pane">
                                                      <span className="eyebrow">After</span>
                                                      <pre>{change.after_content || "—"}</pre>
                                                    </div>
                                                  </div>
                                                </details>
                                              ))
                                            : null}
                                        </div>
                                      ) : null}
                                      {section.key === "approval" &&
                                      Number(selectedPipeline?.approval_pending_iteration || 0) === Number(iteration.iterationNumber) ? (
                                        <div className="pipeline-inline-actions">
                                          <button
                                            type="button"
                                            className="button button--primary"
                                            onClick={approveSelectedPipeline}
                                            disabled={pipelineBusy || !selectedPipelineId}
                                          >
                                            <span className="material-symbols-outlined">task_alt</span>
                                            Approve iteration
                                          </button>
                                          <button
                                            type="button"
                                            className="button button--secondary"
                                            onClick={cancelSelectedPipeline}
                                            disabled={pipelineBusy || !selectedPipelineId}
                                          >
                                            <span className="material-symbols-outlined">cancel</span>
                                            Cancel pipeline
                                          </button>
                                        </div>
                                      ) : null}
                                    </div>
                                  ) : (
                                    <>
                                      <p className="testing-muted">{section.emptyText}</p>
                                      {section.key === "approval" &&
                                      Number(selectedPipeline?.approval_pending_iteration || 0) === Number(iteration.iterationNumber) ? (
                                        <div className="pipeline-inline-actions">
                                          <button
                                            type="button"
                                            className="button button--primary"
                                            onClick={approveSelectedPipeline}
                                            disabled={pipelineBusy || !selectedPipelineId}
                                          >
                                            <span className="material-symbols-outlined">task_alt</span>
                                            Approve iteration
                                          </button>
                                          <button
                                            type="button"
                                            className="button button--secondary"
                                            onClick={cancelSelectedPipeline}
                                            disabled={pipelineBusy || !selectedPipelineId}
                                          >
                                            <span className="material-symbols-outlined">cancel</span>
                                            Cancel pipeline
                                          </button>
                                        </div>
                                      ) : null}
                                    </>
                                  )}
                                </section>
                                );
                              })}
                            </div>
                          ) : null}
                        </section>
                      );
                    })
                  ) : (
                    <p className="testing-muted">No pipeline iterations yet.</p>
                  )}
                </div>
              </section>

            </section>
          </>
        ) : (
          <>
            <header className="page-header">
              <h1>Testing</h1>
              <p>Run a single live task or the full task set and inspect the live chat and execution flow without entering the pipeline loop.</p>
              <div className="status-pill">Workspace: {testingStatus}</div>
            </header>

            <section className="pipeline-page">
              <section className="testing-quickrun testing-quickrun--standalone">
                <div className="testing-quickrun__content">
                  <section className="testing-toolbar">
                    <button type="button" className="button button--primary" onClick={() => executeTestingRun({ include_evaluation: false })} disabled={testingBusy}>
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
                      onClick={() => executeTestingRun(selectedTaskSlug ? { task: selectedTaskSlug, include_evaluation: false } : { include_evaluation: false })}
                      disabled={testingBusy || !selectedTaskSlug}
                    >
                      <span className="material-symbols-outlined">terminal</span>
                      Run selected task
                    </button>
                  </section>

                  <section className="testing-live">
                    <div className="testing-live__header">
                      <div>
                        <span className="eyebrow">Live quick run</span>
                        <strong>Per-test stream</strong>
                      </div>
                      <span className="status-pill status-pill--center">{testingBusy ? "Running..." : testingLiveActive ? "Streaming..." : "Idle"}</span>
                    </div>
                    {testingTaskBlocks.length ? (
                      <div className="testing-task-blocks">
                        {testingTaskBlocks.map((block) => (
                          <article className="testing-task-block" key={block.task}>
                            <div className="testing-task-block__header">
                              <div>
                                <span className="eyebrow">Test</span>
                                <strong>{block.task}</strong>
                              </div>
                              <span className={`status-pill status-pill--center ${block.status === "failed" ? "status-pill--error" : ""}`}>
                                {block.status === "completed" ? "Completed" : block.status === "failed" ? "Failed" : "Running"}
                              </span>
                            </div>
                            <div className="testing-live__panels">
                              <div className="testing-live__panel">
                                <div className="testing-live__panel-head">
                                  <span className="eyebrow">Conversation</span>
                                  <strong>Readable chat</strong>
                                </div>
                                <div className="testing-transcript">
                                  {block.conversation.length ? block.conversation.map((item, index) => (
                                    <article className={item.role === "user" ? "transcript-turn transcript-turn--user" : "transcript-turn transcript-turn--agent"} key={`${block.task}-${item.role}-${item.timestamp || index}`}>
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
                                <div className="testing-steps" aria-live="polite">
                                  {block.steps.length ? block.steps.map((line, index) => (
                                    <div className={`testing-step ${line.tag === "error" ? "testing-step--error" : line.tag === "eval" ? "testing-step--eval" : line.tag === "status" ? "testing-step--status" : "testing-step--accent"}`} key={`${block.task}-${line.tag}-${index}`}>
                                      <span className="testing-step__time">{formatTimestamp(line.timestamp)}</span>
                                      <span className="testing-step__tag">{String(line.tag || "log").toUpperCase()}</span>
                                      <span className="testing-step__text">{line.text}</span>
                                    </div>
                                  )) : <p className="testing-muted">[waiting] No step output yet.</p>}
                                </div>
                              </div>
                            </div>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <p className="testing-muted">Start a run to create a live block for each test.</p>
                    )}
                  </section>
                </div>
              </section>
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
        <button type="button" className={screen === "refinement" ? "mobile-nav__item active" : "mobile-nav__item"} onClick={() => setScreen("refinement")}>
          <span className="material-symbols-outlined">auto_fix_high</span>
          <span>Refinement</span>
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
