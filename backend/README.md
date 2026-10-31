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
| `REMIND_DAYS_BEFORE` | Reminder window in days, default `3` |
| `REMINDER_HOUR` | Hour calendar alarms fire, default `9` |
| `SEARCH_PROVIDER` | Manual finder: `none` (default, saves a search link only) or `brave` |
| `BRAVE_API_KEY` | Brave Search API key, needed only for `brave` |
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
│   ├── store.py       # JSON persistence, task manager, alerts
│   ├── scheduling.py  # Recurring schedules -> one open task each
│   ├── calendar.py    # .ics reminder feed
│   └── importer.py    # CSV / Excel inventory import
├── ai/
│   ├── gemma_client.py  # Ollama / Google AI Studio / mock behind one generate()
│   ├── prompts.py       # Prompt templates
│   ├── diagnose.py      # Photo -> validated DiagnosisResult (retry + fallback)
│   ├── column_mapper.py # Gemma matches unfamiliar spreadsheet headers
│   ├── identify.py      # Photo -> item, brand, model + maintenance plan + questions
│   ├── manual_finder.py # Web search + PDF download for manuals
│   └── manuals.py       # PDF -> text, long-context Q&A
├── seed/mock_inventory.json  # Used until data/mock_inventory.json exists
└── tests/             # pytest, runs in mock mode
```

## API

| Method | Route | What it does |
|---|---|---|
| GET | `/api/assets?category=&status=` | List equipment |
| POST | `/api/assets` | Add equipment |
| POST | `/api/assets/import` | Import a legacy `.csv` / `.xlsx` inventory (see below) |
| POST | `/api/assets/photos/import` | ZIP of images named by asset code (`02001.00.jpg`); attaches them in bulk |
| PUT / GET | `/api/assets/{id}/photo` | Upload / fetch one asset's photo (`photo_url` on the asset) |
| POST | `/api/assets/identify` | Multipart `image`: identify the item and draft it with a maintenance plan (nothing saved) |
| GET / PATCH / DELETE | `/api/assets/{id}` | Read, partially update, delete |
| POST | `/api/assets/{id}/tasks` | Add a maintenance task |
| PATCH | `/api/assets/{id}/tasks/{task_id}` | Update a task (e.g. `{"status": "done"}`) |
| GET | `/api/tasks?status=open\|done\|all&within_days=&asset_id=&environment=` | All tasks across equipment, soonest first |
| POST | `/api/tasks/{task_id}/complete` | `{"completed_on"?, "notes"?}`. Recurring tasks return `next_task` |
| POST | `/api/tasks/{task_id}/snooze` | `{"days": 3}` |
| GET | `/api/reminders` | Overdue + due within `REMIND_DAYS_BEFORE` days; poll it for notifications |
| GET | `/api/calendar.ics` | Open tasks as a calendar feed with alarms |
| GET | `/api/alerts?within_days=30` | Open tasks as dashboard alerts (overdue ones raised to at least high) |
| POST | `/api/diagnose` | Multipart: `image` (+ optional `asset_id`, `notes`). Returns the diagnosis; with `asset_id` it also schedules a task |
| GET | `/api/manuals` | Loaded manuals |
| POST | `/api/manuals` | Multipart: `file` (PDF) |
| POST | `/api/manual-query` | `{"manual_id", "question"}` |
| POST | `/api/assets/{id}/find-manual?download=true` | Search for the manual, save the link, load the PDF |
| POST | `/api/assets/{id}/manual-link` | `{"url", "download"?}`: save a link the user found (loads it if it's a PDF) |

Every AI response has a `source` field: `model` (real Gemma answer), `mock`, or
`fallback` (the model failed; show a warning in the UI). Failed diagnoses never create tasks.

Due dates for diagnosis tasks: critical = today, high = +2 days, medium = +7, low = +30.
High severity marks the asset `needs_attention`; critical marks it `out_of_service`.

### Example

```bash
curl -F image=@gasket.jpg -F asset_id=asset-centrifuge-01 -F notes="lid seal cracked" \
  http://localhost:8000/api/diagnose
```

## Task manager & reminders

Stock: items with `quantity_expected` and `quantity_actual` get a **"Missing N units"** task
whenever the count is short (high priority if none are left). Completing it sets the count
back to expected (found or reordered); fixing the count by hand also clears it.

Recurring maintenance comes from four places on an asset: `service_interval_days`,
`calibration_interval_days`, part `lifespan_days`, and `schedules` (custom jobs like
"Replace water filter every 180 days"). Each one always has **exactly one open task**
(`schedule_id` says which source). Completing it writes the date back to the source
(`last_done`, `last_service_date`, part `installed_date`...) and the next task appears
automatically. A schedule whose `last_done` is unknown gets its first task due today.
Manual and diagnosis tasks are one-off.

- **Snooze** moves the due date and survives later edits to the asset.
- **Reminders**: the frontend polls `GET /api/reminders` and shows browser notifications.
- **Calendar**: `GET /api/calendar.ics` gives every open task as an all-day event with
  alarms at `REMINDER_HOUR` on the due day and `REMIND_DAYS_BEFORE` days earlier.
  Download it and import it into Outlook/Apple/Google Calendar, or subscribe to the URL
  from a calendar app on the same network. Google Calendar's "subscribe by URL" needs a
  public URL, so localhost won't work there.

## Household, lab and workplace settings

Diagnosis and the assistant adapt their language and safety advice to the asset's `environment`
(`household`, `lab` or `enterprise`); the guidance lives in `SETTING_GUIDANCE` in `ai/prompts.py`.
Households get plain words, common tools and a clear line on what needs a professional (gas,
refrigerant, internal wiring, microwave internals); labs get decontamination, PPE, lockout/tagout
and logging. With no asset (or an everyday item still on the default `lab`), Gemma infers the
setting from the photo and equipment. New assets default to `lab`, so set `environment` when
adding household items.

## Adding equipment from a photo

1. `POST /api/assets/identify` with the photo. Gemma names the item (fridge, vacuum,
   centrifuge...), reads the brand/model/serial **only if a label is visible**, and proposes
   2-6 recurring jobs. Intervals that are way off for well-known jobs are corrected.
2. The response has a `draft` and `questions`. Each question has a `target`, e.g.
   `"model"` or `"schedules.2.last_done"`. Write each answer there (dates as `YYYY-MM-DD`;
   skip unknown ones).
3. `POST /api/assets` with the draft. Tasks are scheduled immediately.
4. Optionally `POST /api/assets/{id}/find-manual`.

## Manual finder

Gemma runs offline, so finding manuals is plain web search + download:
- **Always**: every asset with a brand or model has `manual_search_url` (a search link).
- **`SEARCH_PROVIDER=brave`**: searches, ranks results (PDF > model number in URL/title >
  maker's own domain), downloads up to 3 PDFs, checks the model number appears inside,
  and loads the manual for `/api/manual-query`. The best link is saved as `manual_url`.
- **By hand**: `POST /api/assets/{id}/manual-link` with a URL the user found.

Only brand + model text goes to the search provider; photos never leave the machine.

## Importing old inventories (CSV / Excel)

`POST /api/assets/import` (multipart `file`) accepts `.csv` or `.xlsx`. Query options:

| Option | Default | Meaning |
|---|---|---|
| `dry_run` | `false` | Parse and report without saving. Use it for a "this is what we understood" preview |
| `mode` | `append` | `append`: add rows; rows whose serial number exists update that asset. `replace`: wipe inventory first |
| `date_order` | `mdy` | How to read ambiguous dates like `05/10/2026` (`dmy` for day-first) |
| `use_ai` | `true` | Ask Gemma about headers the alias list doesn't recognize |
| `sheet` | first sheet | Excel sheet name |

Header names are recognized in **English and Spanish**, accents ignored ("CÓDIGO",
"Ubicación", "ESTANTE(S)", "CANTIDAD TOTAL REAL"...). Besides equipment fields, a sheet can
carry `code` (SKU / catalog no. / asset tag), expected and counted quantities, `groups`
(kits, comma-separated) and `notes`. Re-imports match existing assets by serial number,
then by code, so they update instead of duplicating.

`stock_count_days` (default 180, 0 = off): each kit/group becomes a `category: "kit"` asset
with a recurring "Physical stock count" task. If the sheet has counted quantities, the import
counts as the latest count.

How it reads a file:
- **Header row** = first row with 2+ filled cells, so title rows like "Lab Inventory 2019" are skipped.
- **Columns** are matched by a list of common names first ("S/N", "Mfr", "Last PM", "Cal Due"...).
  Leftovers go to Gemma with only the header and 3 sample values. Each column in the
  response says whether it was matched by `alias`, `ai`, or left `unmapped`.
- **Dates**: Excel dates, `2026-05-10`, `5/10/2026`, `Mar 3, 2026`, Excel serial numbers.
- **Intervals**: numbers (unit taken from the header, e.g. "Interval (months)"), `6 months`, `annual`, `quarterly`...
- **Status** words like "Working", "needs repair", "Broken", "OOS" map to the three statuses.
- **Next-due dates**: with an interval, the last date is back-calculated; without one, an "(imported)" task is created.
- **Parts** column (optional): `Name | part# | installed | lifespan; Name2` (only the name is required).
- A row with no name, manufacturer or model is **skipped**. A bad value in any other column is a
  **warning** and that value is ignored. Both are listed with Excel row numbers.

```bash
curl -F file=@old_inventory.xlsx "http://localhost:8000/api/assets/import?dry_run=true"
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
