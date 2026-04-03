const DEFAULT_API_BASE = "https://airlineassistantvoiceagent.up.railway.app";

function getApiBase() {
  return import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || DEFAULT_API_BASE;
}

async function request(path, options = {}) {
  const hasBody = options.body !== undefined && options.body !== null;
  const response = await fetch(`${getApiBase()}${path}`, {
    headers: {
      ...(hasBody ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail || payload.message || detail;
    } catch {
      // keep fallback text
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export function getHealth() {
  return request("/health");
}

export function listFlights(limit = 6) {
  return request(`/api/flights?limit=${encodeURIComponent(limit)}`);
}

export function searchFlights(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  });
  if (!query.has("limit")) {
    query.set("limit", "6");
  }
  return request(`/api/flights/search?${query.toString()}`);
}

export function listKnowledgeTopics() {
  return request("/api/knowledge/topics");
}

export function searchKnowledge(q) {
  return request(`/api/knowledge/search?q=${encodeURIComponent(q)}`);
}

export function sendChatMessage(message) {
  return request("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function getChatHistory() {
  return request("/api/chat/history");
}

export function createBooking(payload) {
  return request("/api/bookings", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listTestingTasks() {
  return request("/api/testing/tasks");
}

export function listTestingRuns() {
  return request("/api/testing/runs");
}

export function getTestingRun(runId) {
  return request(`/api/testing/runs/${encodeURIComponent(runId)}`);
}

export function getTestingRunRefinement(runId) {
  return request(`/api/testing/runs/${encodeURIComponent(runId)}/refinement`);
}

export function runTestingTask(payload = {}) {
  return request("/api/testing/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function runTestingTaskLive(payload = {}, onEvent = () => {}) {
  const response = await fetch(`${getApiBase()}/api/testing/run/live`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok || !response.body) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const errorPayload = await response.json();
      detail = errorPayload.detail || errorPayload.message || detail;
    } catch {
      // keep fallback text
    }
    throw new Error(detail);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        onEvent(JSON.parse(line));
      } catch {
        onEvent({ type: "log", message: line });
      }
    }
  }
  if (buffer.trim()) {
    try {
      onEvent(JSON.parse(buffer));
    } catch {
      onEvent({ type: "log", message: buffer });
    }
  }
  return true;
}

export function listTestingScenarios() {
  return listTestingTasks();
}

export function runTestingScenario(payload = {}) {
  return runTestingTask(payload);
}
