# Maintenance Tracker frontend

React + Vite frontend for the Maintenance Tracker team project. It can run with fictional browser-only data, or load the shared FastAPI equipment and tasks when a backend URL is configured.

## Run

From the repository root:

```sh
cd frontend
npm install
npm run dev
```

Open the URL shown by Vite, usually http://127.0.0.1:5173. Run `npm test` and `npm run build` before sharing changes.

## Connect the backend

The backend code is on `main`. Run it separately (see `backend/README.md`) and copy `.env.example` to `frontend/.env` with:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

Restart Vite after changing `.env`. Ensure the backend's `CORS_ORIGINS` includes the exact Vite origin, such as `http://127.0.0.1:5173`. Never put API keys in a `VITE_` value; they are public in the browser. With the URL empty, the app keeps a fictional local demo and AI actions remain disabled.

## Demo flow

1. Open **Diagnose**, upload or take a photo, select an existing item, and describe symptoms. `POST /api/diagnose` returns severity, confidence, hazards, tools, parts, steps, technician advice, and (if the model succeeds) a scheduled task. A fallback response is clearly marked and creates no task.
2. Open **Equipment**, use **Add equipment from a photo**, and review the result of `POST /api/assets/identify`. Answer its text/date questions, edit or remove suggested schedules, then save the complete draft with `POST /api/assets`. Empty last-done dates create tasks due today.
3. **Maintenance** shows priority and kind, highlights stock shortages, and offers **Snooze 3 days**. Completing a recurring task displays the next due date returned by the backend. Reopening backend recurring tasks is disabled until the duplicate-task backend gap is fixed.
4. Diagnosis and identification show a spinner and use a 90-second timeout. Text assistant requests retain a 30-second timeout. The chat photo button now calls `/api/diagnose` rather than sending an unsupported image to `/api/assistant`.

The original browser demo still supports local equipment, tasks, History, recurrence, and reset. `src/demoApi.mjs` contains the shared backend adapters; `src/DemoFlows.jsx` contains the photo flows; `src/demo-flow.css`, `src/vivid.css`, and `src/depth.css` style the interface.

## Checks

- `npm test`: 15 tests, including multipart diagnosis, identification draft, backend task actions, and local data behavior.
- `npm run build`: production build passed with Vite 7.3.7.
- Browser interaction with the live backend still needs a manual pass after the backend is running. The first screen to test is Diagnose with a mock backend photo, followed by identification and task completion.
