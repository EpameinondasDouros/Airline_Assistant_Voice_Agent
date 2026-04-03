import { useEffect, useMemo, useState } from "react";
import {
  listFlights,
  listKnowledgeTopics,
  searchFlights,
  searchKnowledge,
  sendChatMessage,
} from "./api";

const quickPills = [
  "Find me the cheapest flight this week",
  "Change my booking",
  "Add a ski bag",
  "What time does check-in open?",
  "Request wheelchair assistance",
];

function App() {
  const [screen, setScreen] = useState("search");
  const [health, setHealth] = useState("Ready");
  const [flightStatus, setFlightStatus] = useState("Loading flights...");
  const [flights, setFlights] = useState([]);
  const [selectedFlight, setSelectedFlight] = useState(null);
  const [topics, setTopics] = useState([]);
  const [query, setQuery] = useState("baggage");
  const [searchResults, setSearchResults] = useState([]);
  const [flightFilters, setFlightFilters] = useState({
    origin: "NYC",
    destination: "LHR",
    departure_date: "2024-10-12",
    max_price: "2500",
    seat_class: "business",
    seat_preference: "",
    sort_by: "departure_time",
    only_available: true,
    limit: 6,
  });
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState([
    {
      role: "assistant",
      text: "Your upcoming flight to Reykjavík (KEF) is scheduled for this Friday. Would you like me to arrange a lounge pass or pre-order your preferred Nordic breakfast?",
    },
    {
      role: "user",
      text: "Can I bring my pet on this flight? I'm traveling with a small French Bulldog.",
    },
    {
      role: "assistant",
      text: "AeroMellon loves welcoming furry companions. For flights to Iceland, small pets under 8kg can travel in the cabin. Your French Bulldog qualifies.",
      actions: ["Add Pet to Booking", "View Pet Policy"],
    },
  ]);
  const [chatStatus, setChatStatus] = useState("Idle");

  useEffect(() => {
    listFlights(3)
      .then((items) => {
        setFlights(items);
        setSelectedFlight(items[0] ?? null);
        setFlightStatus(items.length ? `Loaded ${items.length} flights` : "No flights returned");
      })
      .catch((error) => {
        setFlights([]);
        setSelectedFlight(null);
        setFlightStatus(error.message);
        setHealth("Flight API unavailable");
      });

    listKnowledgeTopics()
      .then(setTopics)
      .catch(() => setTopics([]));
  }, []);

  const recommendedFlight = flights[0];
  const cheapestFlight = useMemo(() => flights.slice().sort((a, b) => a.price - b.price)[0], [flights]);
  const fastestFlight = useMemo(
    () =>
      flights.slice().sort((a, b) => {
        const aMinutes = (a.arrival_minutes ?? 0) - (a.departure_minutes ?? 0);
        const bMinutes = (b.arrival_minutes ?? 0) - (b.departure_minutes ?? 0);
        return aMinutes - bMinutes;
      })[0],
    [flights],
  );
  const flightToShow = selectedFlight ?? recommendedFlight;

  function runFlightSearch() {
    searchFlights({
      origin: flightFilters.origin,
      destination: flightFilters.destination,
      departure_date: flightFilters.departure_date,
      max_price: flightFilters.max_price,
      seat_class: flightFilters.seat_class,
      seat_preference: flightFilters.seat_preference,
      sort_by: flightFilters.sort_by,
      only_available: flightFilters.only_available,
      limit: flightFilters.limit,
    })
      .then((items) => {
        setFlights(items);
        setSelectedFlight(items[0] ?? null);
        setFlightStatus(items.length ? `Loaded ${items.length} flights` : "No flights returned");
      })
      .catch((error) => {
        setFlightStatus(error.message);
        setHealth("Flight search failed");
      });
  }

  function runKnowledgeSearch(event) {
    event.preventDefault();
    searchKnowledge(query)
      .then(setSearchResults)
      .catch((error) => {
        setSearchResults([]);
        setHealth(error.message);
      });
  }

  function submitChat(event) {
    event.preventDefault();
    const message = chatInput.trim();
    if (!message) return;

    setChatMessages((items) => [...items, { role: "user", text: message }]);
    setChatInput("");
    setChatStatus("Sending...");

    sendChatMessage(message)
      .then((response) => {
        setChatStatus(response.accepted ? "Submitted" : "Queued");
        setChatMessages((items) => [
          ...items,
          { role: "assistant", text: response.response || "Message submitted to the session." },
        ]);
      })
      .catch((error) => {
        setChatStatus(error.message);
      });
  }

  return (
    <div className="app-shell">
      <nav className="topbar">
        <div className="topbar__brand">AeroMellon</div>
        <div className="topbar__links">
          <button className={screen === "search" ? "tab active" : "tab"} onClick={() => setScreen("search")}>Search Flights</button>
          <button className={screen === "concierge" ? "tab active" : "tab"} onClick={() => setScreen("concierge")}>Concierge AI</button>
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
                  <input
                    value={flightFilters.origin}
                    onChange={(event) =>
                      setFlightFilters((current) => ({
                        ...current,
                        origin: event.target.value.toUpperCase(),
                      }))
                    }
                    maxLength={3}
                    placeholder="NYC"
                  />
                </div>
              </label>
              <label className="search-field search-field--input">
                <span className="material-symbols-outlined">location_on</span>
                <div>
                  <small>Destination</small>
                  <input
                    value={flightFilters.destination}
                    onChange={(event) =>
                      setFlightFilters((current) => ({
                        ...current,
                        destination: event.target.value.toUpperCase(),
                      }))
                    }
                    maxLength={3}
                    placeholder="LHR"
                  />
                </div>
              </label>
              <label className="search-field search-field--input">
                <span className="material-symbols-outlined">calendar_month</span>
                <div>
                  <small>Date</small>
                  <input
                    type="date"
                    value={flightFilters.departure_date}
                    onChange={(event) =>
                      setFlightFilters((current) => ({
                        ...current,
                        departure_date: event.target.value,
                      }))
                    }
                  />
                </div>
              </label>
              <label className="search-field search-field--input">
                <span className="material-symbols-outlined">payments</span>
                <div>
                  <small>Budget</small>
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={flightFilters.max_price}
                    onChange={(event) =>
                      setFlightFilters((current) => ({
                        ...current,
                        max_price: event.target.value,
                      }))
                    }
                    placeholder="2500"
                  />
                </div>
              </label>
              <button type="button" className="search-button" onClick={runFlightSearch}>
                <span className="material-symbols-outlined">search</span>
              </button>
            </section>

            <section className="results-grid">
              <aside className="filters-panel">
                <h3>Price Range</h3>
                <div className="range-bar" />
                <div className="range-labels">
                  <span>$450</span>
                  <span>$4,200</span>
                </div>

                <h3>Topics</h3>
                <div className="topic-list">
                  {topics.map((topic) => (
                    <button
                      type="button"
                      key={topic}
                      className="topic-chip"
                      onClick={() => setQuery(topic)}
                    >
                      {topic}
                    </button>
                  ))}
                </div>

                <form className="knowledge-search" onSubmit={runKnowledgeSearch}>
                  <h3>Knowledge Search</h3>
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="baggage"
                  />
                  <button type="submit">Search</button>
                </form>

                <div className="flight-search-options">
                  <h3>Flight Options</h3>
                  <select
                    value={flightFilters.seat_class}
                    onChange={(event) =>
                      setFlightFilters((current) => ({
                        ...current,
                        seat_class: event.target.value,
                      }))
                    }
                  >
                    <option value="economy">Economy</option>
                    <option value="premium_economy">Premium Economy</option>
                    <option value="business">Business</option>
                  </select>
                  <select
                    value={flightFilters.seat_preference}
                    onChange={(event) =>
                      setFlightFilters((current) => ({
                        ...current,
                        seat_preference: event.target.value,
                      }))
                    }
                  >
                    <option value="">Any seat preference</option>
                    <option value="window">Window</option>
                    <option value="aisle">Aisle</option>
                    <option value="extra_legroom">Extra legroom</option>
                  </select>
                  <select
                    value={flightFilters.sort_by}
                    onChange={(event) =>
                      setFlightFilters((current) => ({
                        ...current,
                        sort_by: event.target.value,
                      }))
                    }
                  >
                    <option value="departure_time">Departure time</option>
                    <option value="price">Price</option>
                  </select>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={flightFilters.only_available}
                      onChange={(event) =>
                        setFlightFilters((current) => ({
                          ...current,
                          only_available: event.target.checked,
                        }))
                      }
                    />
                    <span>Only available flights</span>
                  </label>
                </div>
              </aside>

              <div className="results-panel">
                <div className="compare-row">
                  <button type="button" className="compare-card primary">
                    <small>Recommended</small>
                    <strong>{recommendedFlight ? `$${recommendedFlight.price}` : "—"}</strong>
                  </button>
                  <button type="button" className="compare-card">
                    <small>Cheapest</small>
                    <strong>{cheapestFlight ? `$${cheapestFlight.price}` : "—"}</strong>
                  </button>
                  <button type="button" className="compare-card">
                    <small>Fastest</small>
                    <strong>{fastestFlight ? `$${fastestFlight.price}` : "—"}</strong>
                  </button>
                </div>

                <div className="flight-card featured">
                  <div className="flight-card__badge">Recommended Option</div>
                  <div className="flight-card__row">
                    <div>
                      <strong>{flightToShow?.departure_time ? new Date(flightToShow.departure_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</strong>
                      <span>{flightToShow?.origin_airport ?? "NYC"}</span>
                    </div>
                    <div>
                      <small>{flightToShow?.arrival_time && flightToShow?.departure_time ? `${Math.max(1, Math.round((new Date(flightToShow.arrival_time) - new Date(flightToShow.departure_time)) / 60000 / 60))}h` : "—"}</small>
                      <span>{flightToShow ? `${flightToShow.available_seats} seats left` : "Non-stop"}</span>
                    </div>
                    <div>
                      <strong>{flightToShow?.arrival_time ? new Date(flightToShow.arrival_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</strong>
                      <span>{flightToShow?.destination_airport ?? "LHR"}</span>
                    </div>
                    <div className="price">{flightToShow ? `$${flightToShow.price}` : "$1,240"}</div>
                  </div>
                </div>

                {flights.slice(0, 2).map((flight) => (
                  <button
                    type="button"
                    className={selectedFlight?.id === flight.id ? "flight-card flight-card--selected" : "flight-card flight-card--button"}
                    key={flight.id}
                    onClick={() => setSelectedFlight(flight)}
                  >
                    <div className="flight-card__row">
                      <div>
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
                ))}

                {searchResults.length > 0 ? (
                  <div className="knowledge-results">
                    <h3>Knowledge Matches</h3>
                    {searchResults.map((item) => (
                      <article key={item.id ?? item.title} className="knowledge-card">
                        <span className="eyebrow">{item.topic}</span>
                        <h4>{item.title}</h4>
                        <p>{item.content}</p>
                      </article>
                    ))}
                  </div>
                ) : null}

                <div className="flight-detail">
                  <h3>Selected flight</h3>
                  {selectedFlight ? (
                    <div className="flight-detail__grid">
                      <div>
                        <span>Flight</span>
                        <strong>{selectedFlight.flight_number}</strong>
                      </div>
                      <div>
                        <span>Class</span>
                        <strong>{selectedFlight.seat_class}</strong>
                      </div>
                      <div>
                        <span>Status</span>
                        <strong>{selectedFlight.status}</strong>
                      </div>
                      <div>
                        <span>Gate</span>
                        <strong>{selectedFlight.departure_gate ?? "TBA"}</strong>
                      </div>
                    </div>
                  ) : (
                    <p>No flight selected.</p>
                  )}
                </div>

                <section className="spotlight">
                  <div className="spotlight__copy">
                    <span className="eyebrow">Voyager Select</span>
                    <h2>Discover Autumn in London</h2>
                    <p>
                      From the royal parks cloaked in gold to cozy hearths in Mayfair, London in
                      October is a masterclass in atmospheric elegance. Our elite concierge team is
                      ready to curate your stay.
                    </p>
                  </div>
                  <div className="spotlight__gallery">
                    <div className="gallery-tile" />
                    <div className="gallery-tile gallery-tile--offset" />
                  </div>
                </section>
              </div>
            </section>
          </>
        ) : (
          <>
            <header className="concierge-intro">
              <div className="intro-mark">
                <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>
                  auto_awesome
                </span>
              </div>
              <h1>Good afternoon, Julian.</h1>
              <p>I&apos;m your AeroMellon Concierge. How may I elevate your journey today?</p>
            </header>

            <section className="chat-thread">
              {chatMessages.map((message, index) => (
                <div className={message.role === "user" ? "chat-row user" : "chat-row"} key={`${message.role}-${index}`}>
                  <div className={message.role === "user" ? "avatar user" : "avatar ai"}>
                    {message.role === "user" ? "JV" : "AM"}
                  </div>
                  <div className={message.role === "user" ? "bubble user" : "bubble ai"}>
                    <p>{message.text}</p>
                    {message.actions ? (
                      <div className="message-actions">
                        {message.actions.map((action) => (
                          <button type="button" key={action} className="action-button">
                            {action}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
              ))}
            </section>

            <section className="composer-shell">
              <div className="prompt-row">
                {quickPills.map((pill) => (
                  <button type="button" className="prompt-pill" key={pill}>
                    {pill}
                  </button>
                ))}
              </div>

              <form className="composer" onSubmit={submitChat}>
                <span className="material-symbols-outlined composer__icon">chat_bubble</span>
                <input
                  value={chatInput}
                  onChange={(event) => setChatInput(event.target.value)}
                  placeholder="Tell me where you want to go..."
                />
                <button type="submit" className="composer__send">
                  <span className="material-symbols-outlined">arrow_upward</span>
                </button>
              </form>
              <p className="status-pill status-pill--center">
                AeroMellon AI Concierge • {chatStatus}
              </p>
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
      </nav>
    </div>
  );
}

export default App;
