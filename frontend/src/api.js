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

export function listTestingScenarios() {
  return request("/api/testing/scenarios");
}

export function listTestingRuns() {
  return request("/api/testing/runs");
}

export function getTestingRun(runId) {
  return request(`/api/testing/runs/${encodeURIComponent(runId)}`);
}

export function runTestingScenario(payload = {}) {
  return request("/api/testing/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
