# LabGuard AI — Smart Lab Equipment & Inventory Maintenance

> An open-source, privacy-first laboratory equipment maintenance tutor and inventory scheduler powered by **Gemma 4**.

## 🚀 Overview
LabGuard AI helps research facilities, universities, and industrial laboratories maintain equipment uptime, safely conduct DIY part replacements, and track calibration dates locally without sending sensitive lab photos or data to third-party clouds.

## ✨ Core Features
- **Visual Equipment Inspector:** Upload photos of equipment wear, leaks, or error displays to get instant damage ratings, safety warnings, and step-by-step repair guides.
- **Long-Context Manual Q&A:** Load entire PDF equipment manuals into Gemma 4's massive context window for instant troubleshooting answers.
- **Smart Inventory & Calibration Tracker:** Track consumable part lifespans, serial numbers, and upcoming maintenance schedules.

## 🛠️ Tech Stack
- **Frontend:** Next.js, Tailwind CSS, Lucide Icons
- **Backend:** Python (FastAPI) / Node.js (Express)
- **AI Model:** Gemma 4 Multimodal (via Ollama / Google AI Studio API)
- **Database:** Local JSON / SQLite

## 📁 Repository Structure
```text
├── .gitignore       # Ignores .env, node_modules, etc.
├── README.md        # Quick setup instructions & demo script
├── frontend/        # (Person 1) Next.js user interface & camera module
├── backend/         # (Person 2) FastAPI / Express backend server
│   ├── ai/          # Gemma 4 vision pipeline & prompt logic
│   └── api/         # Asset CRUD & schedule routes
└── data/            # (Person 3) Mock lab inventory, test images & manual PDFs
```

## ⚙️ Quick Setup
1. Clone the repo: `git clone <repo-url> && cd Maintenance-Tracker`
2. Copy env vars: `cp .env.example .env` and fill in keys
3. Backend: see [backend/README.md](backend/README.md)
4. Frontend: see [frontend/README.md](frontend/README.md)

## 🎬 Demo Script
1. _TBD_
