# Admissions & Finance AI Agent 🚀

A **standalone, read-only conversational analytics agent** for coaching-institute admissions and finance operations. It answers natural-language questions from high-volume student data (40,000+ row Google Sheets or Excel dumps) and streams back prose, interactive tables and charts.

The model does **not** write SQL for a business metric. It picks a skill, the skill calls a tool, and the tool delegates to sealed analytics functions that replicate the spreadsheet's own formulas. Every number is auditable, and a missing data source produces an explicit decline rather than a plausible-looking figure.

---

## 🌟 Features

- **🧠 Skills & Tools Architecture**: A router selects exactly one skill per question; the skill offers the model a scoped set of pydantic-validated tools. Skills are declarative `SKILL.md` files, so adding a capability means adding a file.
- **🔒 Sealed Analytics**: Business logic lives in pure typed Python over DuckDB, faithful to the workbook down to the deliberate `> 3498` vs `>= 3498` distinction. A build-failing test keeps threshold literals out of the tool layer.
- **📊 Multi-Source Ingestion**: Google Sheets (windowed reads with backoff), Excel (`TRY.xlsx`, 42,000 rows in under a second), or synthetic sample data — selected explicitly, with no silent fallback. Typed staging plus an atomic swap means a failed refresh leaves the last good data intact.
- **🕗 Catch-Up Scheduling**: A daily 08:30 Asia/Kolkata refresh driven off a persisted last-success, so a restart never skips or repeats a day. Every run is audited in `refresh_runs`, and stale data is flagged on every answer.
- **🧵 Conversation Memory**: Slot-based memory means "and for Pune?" works, and any scope inherited from an earlier turn is stated in the provenance rather than applied silently.
- **🛡️ Guardrails & PII Masking**: Prompt-injection screening on input, PII masking on output, and an ad-hoc SQL path that is `SELECT`-only, row-capped and PII-denied on a read-only connection with file access disabled.
- **📡 Real-Time SSE Streaming**: Fine-grained JSON-Patch updates, with a status line per tool call.
- **🔍 Traceable Logging**: Every line carries a request id, echoed as `X-Request-Id`, so one chat turn reads as a single story — skill chosen, each tool call with its arguments and duration, and the answer. Login attempts, blocked inputs and refused SQL are recorded as the audit trail.
- **🎨 Modern UI**: React + Vite + TypeScript + Tailwind, rendering native table and chart blocks (Recharts) rather than markdown the model retyped.

---

## 📐 Architecture Overview

```
                      ┌─────────────────────────────────┐
                      │    React / Vite / TS Frontend   │
                      └────────────────┬────────────────┘
                                       │ POST /chat/stream (SSE)
                                       ▼
                      ┌─────────────────────────────────┐
                      │         FastAPI Backend         │
                      └────────────────┬────────────────┘
                                       ▼
                      ┌─────────────────────────────────┐
                      │  Guardrails  →  Memory slots    │
                      └────────────────┬────────────────┘
                                       ▼
                      ┌─────────────────────────────────┐
                      │  Router — picks ONE skill        │
                      └────────────────┬────────────────┘
                                       ▼
                      ┌─────────────────────────────────┐
                      │  Skill (SKILL.md) → its tools    │
                      └────────────────┬────────────────┘
                                       │ pydantic-validated args
                                       ▼
                      ┌─────────────────────────────────┐
                      │  Sealed analytics → ToolResult   │
                      │  values + table + chart + prov.  │
                      └────────────────┬────────────────┘
              ┌────────────────────────┴────────────────────────┐
              ▼                                                 ▼
   ┌──────────────────────────────┐              ┌──────────────────────────────┐
   │ DuckDB — analytics           │              │ SQLite — app state           │
   │ rd26, rd25, finance, targets │              │ users, chat, memory, audit   │
   │ replaced every morning       │              │ survives every refresh       │
   └──────────────┬───────────────┘              └──────────────────────────────┘
                  ▲
   ┌──────────────┴───────────────┐
   │ Ingestion: GSheets / Excel / │
   │ sample → typed staging → swap │
   └──────────────────────────────┘
```

---

## 📁 Repository Structure

```
.
├── backend/
│   ├── app/
│   │   ├── agent/         # Router, skills (SKILL.md), tools, tool loop, memory
│   │   ├── analytics/     # Sealed business logic + shared filters and thresholds
│   │   ├── api/           # Auth, Chat, and Admin API endpoints
│   │   ├── core/          # Config, logging, DuckDB (analytics), SQLite (app state), security
│   │   ├── data/          # Sources, typed ingestion, availability, registry, schema
│   │   ├── guardrails/    # Injection scanning & PII anonymization
│   │   ├── streaming/     # SSE streaming & JSON Patch state events
│   │   ├── main.py        # FastAPI app factory + refresh scheduler
│   │   └── models.py      # Request / response Pydantic models
│   ├── tests/             # Skills, tools, router, memory, explorer, parity, render
│   ├── requirements.txt   # Python dependencies
│   └── run.py             # Server entry point (Uvicorn)
├── frontend/
│   ├── src/
│   │   ├── api/           # API client & SSE consumer
│   │   ├── components/    # Login & Chat UI components
│   │   ├── state/         # JSON Patch render state management
│   │   ├── App.tsx        # Application root component
│   │   └── index.css      # Styling & design system
│   ├── package.json       # Frontend dependencies
│   └── vite.config.ts     # Vite build configuration
├── DESIGN.md              # Design decisions and how implementation amended them
├── RUNNING.md             # Detailed local development guide
├── backend/README.md      # Architecture guide: the three contracts, layout, invariants
└── README.md              # This file
```

---

## 🛠️ Quick Start

### 1. Prerequisites
- **Python**: Version 3.11 or 3.12 (Python 3.12 recommended)
- **Node.js**: Version 18+

---

### 2. Backend Setup

```bash
cd backend

# Create virtual environment with Python 3.12
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start backend server (runs on http://localhost:8500)
python run.py
```

*Note: On initial startup the backend creates an admin user (`admin` / `admin123`), builds both databases and loads the source named by `DATA_SOURCE` (synthetic sample data by default). Chat answers need a model endpoint with tool-calling support — see [RUNNING.md](RUNNING.md) §2 for OpenRouter's free tier, Groq or a local Ollama.*

---

### 3. Frontend Setup

```bash
cd frontend

# Install Node dependencies
npm install

# Start Vite development server (runs on http://localhost:5173)
npm run dev
```

---

## 🔌 API Reference

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/auth/login` | `POST` | Authenticate user and receive JWT bearer token |
| `/chat/stream` | `POST` | Streaming SSE endpoint for natural language query execution |
| `/chat` | `POST` | Non-streaming JSON endpoint returning complete response state |
| `/refresh` | `POST` | Reload the analytics tables from the configured source |
| `/refresh/history` | `GET` | Audit trail of refresh runs, with row counts and errors |
| `/meta` | `GET` | Freshness, table availability, registered skills and tool count |
| `/health` | `GET` | System health check endpoint |

---

## 🧪 Testing

```bash
cd backend
pytest tests/
```

No model, network access or credentials required, and the suite runs against a temp
directory so it never touches your local `data/`. It covers skill-definition validity,
tool schemas and argument validation, keyword routing, memory inheritance, the explorer's
refusal of writes and PII, analytics invariants, and the render/scheduling logic.

---

## 🔒 Security & Privacy

- **Git Security**: Sensitive configuration files (`.env`), Google Service Account credentials (`*.json`), and large proprietary datasets (`TRY.xlsx`, `*.pdf`) are excluded via `.gitignore`.
- **PII Protection**: Student names and registration numbers are automatically masked before any analytics response is emitted.

---

## 📜 License

MIT License
