# Maintenance Tracker frontend

Owner: Person 1 (frontend). React + Vite, with plain CSS and no UI kit.
This is a frontend demo; no real AI, shared database, or backend is bundled.

## Run locally

Install Node.js 22.12 or later with npm. From the repository root:

```sh
cd frontend
npm install
npm run dev
```

Open the local URL printed in the terminal (normally http://127.0.0.1:5173).
Dependencies install once; `npm run dev` is used each time you work on the UI.

```sh
npm test
npm run build
npm run preview
```

`npm test` checks the data logic and API adapter. `npm run build` creates `dist/`;
`npm run preview` serves that production build. Do not commit `node_modules/` or
`dist/`. Commit the generated package-lock.json after the first successful install.

## What works

- Overview, equipment, maintenance, and history navigation.
- Three fictional sample products with original inline SVG illustrations.
- Equipment search, task search, task status filters, and equipment selection.
- Add equipment and tasks with validated input and native keyboard-accessible dialogs.
- Complete and reopen tasks; counts and history update immediately.
- Browser localStorage persistence, with a visible warning if storage fails.
- Responsive layouts and reduced-motion support.
- A pending AI panel with an optional backend adapter, loading/error states,
  cancellation, and a 30-second timeout.

Sample reminders are relative to the first visit, not manufacturer schedules.
Saved records keep their dates on subsequent visits. All task dates use the
user's local calendar. Reset demo asks before replacing locally saved changes.

## Proposed backend handoff

The data model is in `src/model.mjs`. The frontend currently stores equipment
and tasks only in the browser. It does not fetch or synchronize these records.

Before connecting the AI panel, agree this proposed endpoint with Person 2:

```http
POST /assistant
Content-Type: application/json

{"equipment_id":"eq-001","message":"Where can I find the product manual?"}
```

```json
{"answer":"A plain-text response from the backend."}
```

The backend must know the same equipment IDs. For user-created equipment,
implement equipment/task synchronization before using those IDs with the AI.
Treat this endpoint as a proposal; change `src/api.mjs` to match the agreed API.

To configure an available backend, copy `.env.example` to `.env` and set:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Restart Vite after changing `.env`. The backend must permit the frontend origin
through CORS. With an empty URL, the Ask assistant button is intentionally
disabled and no question is sent. Model selection and credentials stay on the
backend. Every `VITE_` value is public: never put an API key there.

## One-minute UI acceptance check

1. Open Overview: three products and three open tasks appear.
2. Select the bicycle: only its tasks appear. Clear the equipment filter.
3. Complete the overdue task: the attention count decreases; History shows it.
4. Reopen it from History, then return to Maintenance.
5. Add equipment, then add a task for it. Search for its name.
6. Refresh: added records and completion changes remain.
7. Use a phone-width window: navigation, forms, and cards remain usable.
8. Use Tab, Enter, and Escape: open a dialog, submit it, or close it.
9. With no backend configured, confirm the panel says AI connection pending.

## Your first frontend edit

Change the heading `Keep good things going.` in `src/App.jsx`, save, and watch
Vite refresh the browser. Change the `--green` color in `src/styles.css` next.
`App.jsx` owns screens and interactions; `model.mjs` owns data behavior;
`api.mjs` is the single place to adapt the AI request.

## Verification

Verified on Windows with Node.js 22.14.0 and npm 10.9.2:

- `npm install` completed and generated `package-lock.json`.
- `npm test` passed all 10 model/API tests.
- `npm run build` completed successfully with Vite 7.3.7.

Browser interactions have not been manually verified. Use the UI acceptance
check above before merging.
