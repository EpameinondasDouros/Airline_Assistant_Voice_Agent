import { EMPTY_API_BASE } from "./constants.js";

const STORAGE_KEY = "aeromellon-api-base";

function normalizeBaseUrl(value) {
  const base = (value || EMPTY_API_BASE).trim().replace(/\/+$/, "");
  return base || EMPTY_API_BASE;
}

async function parseJsonSafe(response) {
  const text = await response.text();
  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text);
  } catch (_error) {
    return text;
  }
}

export function createApiClient() {
  let baseUrl = normalizeBaseUrl(localStorage.getItem(STORAGE_KEY) || EMPTY_API_BASE);
  let lastRequestMeta = null;

  async function request(path, options = {}) {
    const startedAt = performance.now();
    const url = `${baseUrl}${path}`;
    const method = options.method || "GET";

    lastRequestMeta = {
      method,
      path,
      status: null,
      durationMs: null,
      url,
    };

    let response;

    try {
      response = await fetch(url, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
      });
    } catch (_error) {
      lastRequestMeta.durationMs = Math.round(performance.now() - startedAt);
      throw new Error(`Network error while calling ${path}. Check API base URL and backend availability.`);
    }

    const data = await parseJsonSafe(response);
    lastRequestMeta.status = response.status;
    lastRequestMeta.durationMs = Math.round(performance.now() - startedAt);

    if (!response.ok) {
      const detail =
        data && typeof data === "object" && "detail" in data ? data.detail : response.statusText || "Request failed.";
      throw new Error(String(detail));
    }

    return data;
  }

  return {
    getBaseUrl() {
      return baseUrl;
    },
    setBaseUrl(value) {
      baseUrl = normalizeBaseUrl(value);
      localStorage.setItem(STORAGE_KEY, baseUrl);
    },
    getLastRequestMeta() {
      return lastRequestMeta;
    },
    getHealth() {
      return request("/health");
    },
    getAdminFlights() {
      return request("/api/admin/flights");
    },
    searchFlights(params) {
      const search = new URLSearchParams(params).toString();
      return request(`/api/flights/search${search ? `?${search}` : ""}`);
    },
    getAdminBookings({ limit }) {
      return request(`/api/admin/bookings?limit=${encodeURIComponent(limit)}`);
    },
    getBooking(bookingReference) {
      return request(`/api/bookings/${encodeURIComponent(bookingReference)}`);
    },
    createBooking(payload) {
      return request("/api/bookings", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    addExtras(bookingReference, payload) {
      return request(`/api/bookings/${encodeURIComponent(bookingReference)}/extras`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    cancelBooking(bookingReference, payload) {
      return request(`/api/bookings/${encodeURIComponent(bookingReference)}/cancel`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    rescheduleBooking(bookingReference, payload) {
      return request(`/api/bookings/${encodeURIComponent(bookingReference)}/reschedule`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    getKnowledgeTopics() {
      return request("/api/knowledge/topics");
    },
    getKnowledgeTopic(topic) {
      return request(`/api/knowledge/${encodeURIComponent(topic)}`);
    },
    searchKnowledge(query) {
      return request(`/api/knowledge/search?q=${encodeURIComponent(query)}`);
    },
  };
}
