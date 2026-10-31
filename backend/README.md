# Backend

Owner: Paula Contreras Villavicencio

FastAPI server and the Gemma 4 pipeline.

## Run it

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

- Interactive API docs (try every route): http://localhost:8000/docs
- Health check: http://localhost:8000/health

Settings come from `.env` at the repo root (see `../.env.example`). With no `.env`,
the server starts in **mock mode**: every route works and returns canned AI answers,
so the frontend can build before Gemma is set up.

| Variable | Meaning |
|---|---|
| `AI_PROVIDER` | `mock` (default), `ollama` (local), or `google` (AI Studio) |
| `GEMMA_MODEL` | Exact Gemma 4 model name/tag for the chosen provider |
| `OLLAMA_HOST` | Default `http://localhost:11434` |
| `OLLAMA_NUM_CTX` | Context window in tokens, default `32768`. Ollama's own default is small and silently cuts off long manuals |
| `GOOGLE_API_KEY` | Needed only for `google` |
| `CORS_ORIGINS` | Comma-separated, default `http://localhost:3000` |
| `DATA_DIR` | Read-only seed data, default `../data` |
| `STORAGE_DIR` | Where the API writes inventory edits and uploads, default `storage/` (gitignored) |

## Layout

```text
backend/
├── main.py            # App, CORS, /health, loads manuals on startup
├── config.py          # Settings from .env
├── api/
│   ├── schemas.py     # Data contracts (Pydantic): the source of truth for payloads
│   ├── routes.py      # All /api routes
│   └── store.py       # JSON persistence, diagnosis -> task, alerts
├── ai/
│   ├── gemma_client.py  # Ollama / Google AI Studio / mock behind one generate()
│   ├── prompts.py       # Prompt templates
│   ├── diagnose.py      # Photo -> validated DiagnosisResult (retry + fallback)
│   └── manuals.py       # PDF -> text, long-context Q&A
├── seed/mock_inventory.json  # Used until data/mock_inventory.json exists
└── tests/             # pytest, runs in mock mode
```

## API

| Method | Route | What it does |
|---|---|---|
| GET | `/api/assets?category=&status=` | List equipment |
| POST | `/api/assets` | Add equipment |
| GET / PATCH / DELETE | `/api/assets/{id}` | Read, partially update, delete |
| POST | `/api/assets/{id}/tasks` | Add a maintenance task |
| PATCH | `/api/assets/{id}/tasks/{task_id}` | Update a task (e.g. `{"status": "done"}`) |
| GET | `/api/alerts?within_days=30` | Overdue + upcoming service, calibration, parts, tasks (sorted, most urgent first) |
| POST | `/api/diagnose` | Multipart: `image` (+ optional `asset_id`, `notes`). Returns the diagnosis; with `asset_id` it also schedules a task |
| GET | `/api/manuals` | Loaded manuals |
| POST | `/api/manuals` | Multipart: `file` (PDF) |
| POST | `/api/manual-query` | `{"manual_id", "question"}` |

Every AI response has a `source` field: `model` (real Gemma answer), `mock`, or
`fallback` (the model failed; show a warning in the UI). Failed diagnoses never create tasks.

Due dates for diagnosis tasks: critical = today, high = +2 days, medium = +7, low = +30.
High severity marks the asset `needs_attention`; critical marks it `out_of_service`.

### Example

```bash
curl -F image=@gasket.jpg -F asset_id=asset-centrifuge-01 -F notes="lid seal cracked" \
  http://localhost:8000/api/diagnose
```

## Data

- On first run the inventory is copied from `data/mock_inventory.json` (or `seed/` if missing)
  into `storage/inventory.json`. Delete `storage/` to reset to the seed.
- Put sample PDFs in `data/manuals/`; they load at startup.
- Manuals over `MAX_MANUAL_CHARS` (default 400k chars, ~100k tokens) are truncated.
  Scanned PDFs without a text layer are rejected.

## Tests

```bash
cd backend
python -m pytest
```
