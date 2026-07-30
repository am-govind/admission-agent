# Admissions & Finance AI Agent 🚀

A **standalone, read-only conversational analytics agent** built for educational and coaching institute admissions and finance operations. It turns natural language questions into precise, audited SQL analytics against high-volume student data (such as 40,000+ record Excel dumps or live Google Sheets), streaming back insights, interactive tables, and charts.

---

## 🌟 Features

- **⚡ Fast Text-to-SQL Analytics Engine**: High-performance DuckDB query execution with automatic schema inference, numeric sanitization, and time-anchored aggregations.
- **📊 Multi-Source Ingestion**:
  - **Excel (`.xlsx`)**: Native streaming ingestion for large dumps (e.g. `TRY.xlsx` with 42,000+ records) in under 3 seconds.
  - **Google Sheets API**: Live morning sync & on-demand manual refresh.
  - **Offline Fallback**: Built-in synthetic sample data generator so the application is instantly runnable out of the box with zero external credentials.
- **🛡️ Guardrails & PII Masking**: Input prompt-injection filtering and strict output PII masking for student names and registration numbers.
- **📡 Real-Time SSE Streaming**: Low-latency Server-Sent Events (SSE) protocol delivering fine-grained JSON-Patch updates to the frontend.
- **🎨 Premium Modern UI**: Clean React + Vite + TypeScript interface powered by Tailwind CSS, rendering streaming markdown text, formatted tables, and charts.

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
                                       │
                ┌──────────────────────┼──────────────────────┐
                ▼                      ▼                      ▼
     ┌───────────────────┐   ┌───────────────────┐  ┌───────────────────┐
     │ Guardrails Filter │   │ Text-to-SQL Agent │  │  Data Ingestion   │
     │ (PII & Injection) │   │ (LLM / Prompts)   │  │ (Excel/GSheets)   │
     └───────────────────┘   └─────────┬─────────┘  └─────────┬─────────┘
                                       │                      │
                                       ▼                      ▼
                             ┌──────────────────────────────────┐
                             │       DuckDB Storage & Engine    │
                             │ (rd26, rd25, finance, targets)   │
                             └──────────────────────────────────┘
```

---

## 📁 Repository Structure

```
.
├── backend/
│   ├── app/
│   │   ├── agent/         # Text-to-SQL prompt engineering & LLM runtime
│   │   ├── api/           # Auth, Chat, and Admin API endpoints
│   │   ├── core/          # Config, Security (JWT/Bcrypt), and DuckDB connection
│   │   ├── data/          # Ingestion engines (Excel, GSheets, Sample Data, Registry)
│   │   ├── guardrails/    # Injection scanning & PII anonymization
│   │   ├── streaming/     # SSE streaming & JSON Patch state events
│   │   ├── main.py        # FastAPI app factory
│   │   └── models.py      # Request / response Pydantic models
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
├── DESIGN.md              # Technical design specifications
├── RUNNING.md             # Detailed local development guide
└── README.md              # Documentation
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

*Note: On initial startup, the backend automatically initializes an admin user (`admin` / `admin123`) and ingests available data.*

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
| `/refresh` | `POST` | Reload data into DuckDB from Excel / Google Sheets |
| `/meta` | `GET` | View database metadata and last refresh timestamp |
| `/health` | `GET` | System health check endpoint |

---

## 🧪 Testing

Run backend tests using Pytest:

```bash
cd backend
pytest tests/
```

---

## 🔒 Security & Privacy

- **Git Security**: Sensitive configuration files (`.env`), Google Service Account credentials (`*.json`), and large proprietary datasets (`TRY.xlsx`, `*.pdf`) are excluded via `.gitignore`.
- **PII Protection**: Student names and registration numbers are automatically masked before any analytics response is emitted.

---

## 📜 License

MIT License
