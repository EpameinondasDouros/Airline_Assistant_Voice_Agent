const DEFAULT_API_BASE = "https://airlineassistantvoiceagent.up.railway.app";

function getApiBase() {
  return import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || DEFAULT_API_BASE;
}

function getPipelineApiBase() {
  return import.meta.env.VITE_PIPELINE_API_BASE_URL?.replace(/\/$/, "") || getApiBase();
}

async function request(path, options = {}, baseUrl = getApiBase()) {
  const hasBody = options.body !== undefined && options.body !== null;
  const response = await fetch(`${baseUrl}${path}`, {
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

export function resetChatSession() {
  return request("/api/chat/reset", {
    method: "POST",
  });
}

export function createBooking(payload) {
  return request("/api/bookings", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listAllTripsBooked(limit = 500) {
  return request(`/api/bookings/all-trips-booked?limit=${encodeURIComponent(limit)}`);
}

export function listTestingTasks() {
  return request("/api/testing/tasks");
}

export function listTestingRuns() {
  return request("/api/testing/runs");
}

export function listTestingPipelines() {
  return request("/api/testing/pipelines", {}, getPipelineApiBase());
}

export function getTestingPipeline(pipelineId) {
  return request(`/api/testing/pipelines/${encodeURIComponent(pipelineId)}`, {}, getPipelineApiBase());
}

export function getTestingPipelineEvents(pipelineId) {
  return request(`/api/testing/pipelines/${encodeURIComponent(pipelineId)}/events`, {}, getPipelineApiBase());
}

export function getTestingPipelineDeliverables(pipelineId) {
  return request(`/api/testing/pipelines/${encodeURIComponent(pipelineId)}/deliverables`, {}, getPipelineApiBase());
}

export function getTestingPipelineDeliverableUrl(pipelineId, name) {
  return `${getPipelineApiBase()}/api/testing/pipelines/${encodeURIComponent(pipelineId)}/deliverables/${encodeURIComponent(name)}`;
}

export function getTestingPipelineApplyResult(pipelineId, iterationNumber) {
  return request(
    `/api/testing/pipelines/${encodeURIComponent(pipelineId)}/iterations/${encodeURIComponent(iterationNumber)}/apply-result`,
    {},
    getPipelineApiBase(),
  );
}

export function startTestingPipeline(payload) {
  return request(
    "/api/testing/pipelines",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    getPipelineApiBase(),
  );
}

export function approveTestingPipeline(pipelineId) {
  return request(
    `/api/testing/pipelines/${encodeURIComponent(pipelineId)}/approve`,
    {
      method: "POST",
    },
    getPipelineApiBase(),
  );
}

export function cancelTestingPipeline(pipelineId) {
  return request(
    `/api/testing/pipelines/${encodeURIComponent(pipelineId)}/cancel`,
    {
      method: "POST",
    },
    getPipelineApiBase(),
  );
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
  let depth = 0;
  let inString = false;
  let escape = false;
  let objectStart = -1;

  function consumeBuffer() {
    let consumedThrough = 0;
    for (let index = 0; index < buffer.length; index += 1) {
      const char = buffer[index];
      if (escape) {
        escape = false;
        continue;
      }
      if (char === "\\") {
        if (inString) escape = true;
        continue;
      }
      if (char === '"') {
        inString = !inString;
        continue;
      }
      if (inString) continue;
      if (char === "{") {
        if (depth === 0) {
          objectStart = index;
        }
        depth += 1;
      } else if (char === "}") {
        if (depth > 0) depth -= 1;
        if (depth === 0 && objectStart >= 0) {
          const chunk = buffer.slice(objectStart, index + 1).trim();
          if (chunk) {
            try {
              onEvent(JSON.parse(chunk));
            } catch {
              onEvent({ type: "log", message: chunk });
            }
          }
          consumedThrough = index + 1;
          objectStart = -1;
        }
      }
    }
    if (consumedThrough > 0) {
      buffer = buffer.slice(consumedThrough);
    }
  }

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    consumeBuffer();
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

export function getPipelineApiBaseUrl() {
  return getPipelineApiBase();
}
