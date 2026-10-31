# LabGuard AI — Smart Lab Equipment & Inventory Maintenance

> An open-source, privacy-first laboratory equipment maintenance tutor and inventory scheduler powered by **Gemma 4**.

## 🚀 Overview
LabGuard AI helps research facilities, universities, and industrial laboratories maintain equipment uptime, safely conduct DIY part replacements, and track calibration dates locally without sending sensitive lab photos or data to third-party clouds.

## ✨ Core Features
- **Visual Equipment Inspector:** Upload photos of equipment wear, leaks, or error displays to get instant damage ratings, safety warnings, and step-by-step repair guides.
- **Long-Context Manual Q&A:** Load entire PDF equipment manuals into Gemma 4's massive context window for instant troubleshooting answers.
- **Smart Inventory & Calibration Tracker:** Track consumable part lifespans, serial numbers, stock counts, and upcoming maintenance schedules, with reminders.
- **Add Equipment from a Photo:** Gemma identifies the item, reads its brand/model label, and proposes a maintenance plan.
- **Legacy Inventory Import:** Bring in old Excel/CSV inventories (English or Spanish headers).

## 🛠️ Tech Stack
- **Frontend:** React + Vite, plain CSS
- **Backend:** Python 3.11+ (FastAPI)
- **AI Model:** Gemma 4 multimodal, running locally via Ollama (Google AI Studio optional)
- **Database:** Local JSON file (`backend/storage/`)

## 📁 Repository Structure
```text
├── .gitignore       # Ignores .env, node_modules, etc.
├── README.md        # Quick setup instructions & demo script
├── frontend/        # (Person 1) React + Vite user interface
├── backend/         # (Person 2) FastAPI backend server
│   ├── ai/          # Gemma 4 vision pipeline & prompt logic
│   └── api/         # Asset CRUD, tasks & schedule routes
└── data/            # (Person 3) Mock lab inventory, test images & manual PDFs
```

## ⚙️ Run It Locally

You need three things running: **Ollama** (the model), the **backend** (port 8000), and the
**frontend** (port 5173). Use two terminals for the backend and frontend.

### 1. Prerequisites (once)
- [Python 3.11+](https://www.python.org/downloads/)
- [Node.js 22.12+](https://nodejs.org/) (includes npm)
- [Ollama](https://ollama.com/download), then download the model (~6.6 GB):
  ```sh
  ollama pull gemma4:e4b
  ```
  Check it's there with `ollama list`. Ollama runs in the background after installing.

### 2. Configure (once)
From the repository root:

```sh
cp .env.example .env                       # Windows PowerShell: Copy-Item .env.example .env
cp frontend/.env.example frontend/.env     # Windows PowerShell: Copy-Item frontend\.env.example frontend\.env
```

- In `.env`, set `GEMMA_MODEL=gemma4:e4b` (the tag shown by `ollama list`).
- In `frontend/.env`, set `VITE_API_BASE_URL=http://127.0.0.1:8000/api` (note the `/api`).

Without a model the backend still runs in **mock mode** (set `AI_PROVIDER=mock`): every
screen works with canned AI answers. Leaving `VITE_API_BASE_URL` empty runs the frontend as
a browser-only demo with sample data and no backend.

### 3. Start the backend (terminal 1)
```sh
cd backend
pip install -r requirements.txt            # first time only
python -m uvicorn main:app --reload --port 8000
```
Wait for `Application startup complete`. The model loads in the background (~40 s the
first time). Check it: http://localhost:8000/health should show `"ai_provider": "ollama"`
and `"model": "gemma4:e4b"`. Interactive API docs: http://localhost:8000/docs

### 4. Start the frontend (terminal 2)
```sh
cd frontend
npm install                                # first time only
npm run dev
```
Open **http://127.0.0.1:5173**. The banner should say **"Connected to the backend."**
If it shows sample products instead, check `frontend/.env` and restart `npm run dev`.

### 5. Optional: load the sample lab inventory
The backend starts with 5 demo lab instruments. To add a spreadsheet inventory, open
http://localhost:8000/docs → `POST /api/assets/import` → **Try it out**, attach a `.csv`
or `.xlsx`, and run it with `dry_run=true` first to preview. Details in
[backend/README.md](backend/README.md).

To reset all data to the demo instruments, stop the backend and delete `backend/storage/`.

### Tests
```sh
cd backend && python -m pytest             # backend (runs in mock mode, no model needed)
cd frontend && npm test                    # frontend
```

### Troubleshooting
| Symptom | Fix |
|---|---|
| `/health` says `"mock"` | `.env` is missing or `AI_PROVIDER` isn't `ollama`; restart the backend after editing |
| AI answers have `"source": "fallback"` | Ollama isn't running or `GEMMA_MODEL` doesn't match `ollama list` |
| First AI request is slow or times out | The model is still loading; wait ~40 s after starting the backend and retry |
| Frontend shows "Could not load data from the backend" | The backend isn't running on port 8000, or `VITE_API_BASE_URL` is wrong |
| `node` or `npm` not found right after installing Node | Open a new terminal so it picks up the updated PATH |

More detail: [backend/README.md](backend/README.md) (all routes and settings) and
[frontend/README.md](frontend/README.md).

## 🎬 Demo Script
1. _TBD_
