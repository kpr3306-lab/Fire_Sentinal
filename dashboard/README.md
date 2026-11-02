# Fire Sentinel Prototype 2 — Dashboard

React + Vite + Tailwind. Talks to the Flask backend via `/api/*`, proxied
by Vite's dev server so there's no CORS setup needed locally.

## Setup

```bash
cd dashboard
npm install
npm run dev
```

Opens on `http://localhost:5173`. Make sure the backend (`backend/run.py`)
is running on port 5000 first — the dashboard is entirely empty without it.

## What's fully built this session
- **Dashboard** page — live speedometer-style gauges (temperature, humidity,
  MQ-2/7/135, UV), flame indicator, risk score panel, on-demand camera
  capture, snapshot gallery, detection timeline, emergency contacts, gas
  source hint. Polls the backend every 3 seconds.
- **Rooms** page — create/delete rooms, declare electrical/gas appliances
  per room.
- **System** page — device list with self-registered IP:port, room
  assignment, manual IP/port override, and a one-click Telegram/email
  alert test.
- **Alerts** page — full alert history table.

## What's a placeholder this session
Incidents, Analytics, AI/ML, and Reports show a "planned for a later
session" placeholder — the nav is wired up and functional, but the content
is deferred until the ML phase (Analytics and AI/ML in particular depend on
having real trend/model data to visualize meaningfully).

## The GaugeTile component
`src/components/GaugeTile.jsx` is a from-scratch SVG speedometer: 270° sweep,
tick marks, colored safe/warning/danger zone bands, an animated needle, and a
monospace digital readout. Zone thresholds are passed as props per gauge, so
retuning what counts as "elevated" for a given sensor is a one-line change
where that gauge is used (see `src/pages/Dashboard.jsx`), not a change to the
gauge component itself.

## Next session
Once you've sent over the reference image and feature doc, I'll refine the
visual design against those specifically, and build out Analytics/AI-ML/
Incidents/Reports plus any additional interaction patterns from your reference.
