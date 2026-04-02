# Frontend

Standalone static operations UI for the AeroMellon airline customer-service system.

## What It Covers

- dashboard health and API reachability checks
- flights browser with API-backed filters
- bookings browser with detail inspection
- booking mutation forms for create, extras, cancel, and reschedule
- knowledge base topic and article viewer

## Structure

- `index.html`: app shell and screen layout
- `styles.css`: operational UI layout, forms, tables, and detail panels
- `app.js`: app bootstrap, navigation, screen orchestration, and mutations
- `js/api.js`: shared fetch wrapper and endpoint calls
- `js/forms.js`: form-to-payload helpers
- `js/ui.js`: reusable rendering helpers
- `js/utils.js`: formatting and shared utilities
- `js/constants.js`: screen labels and enum options

## Running

From the project root:

```bash
./run_frontend.sh
```

Then open:

```text
http://localhost:8000
```

## Backend URL

The UI defaults to:

```text
http://localhost:8000
```

You can change the API base URL in the sidebar. The selected value is stored in browser local storage.
